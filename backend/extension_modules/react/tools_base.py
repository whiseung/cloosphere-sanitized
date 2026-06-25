import asyncio
import json
import logging
import os
import re
import unicodedata
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
)

import aiohttp
from extension_modules.react.react_base import (
    AgentStateBase,
    ReactAgentBase,
)
from extension_modules.react.tool_models import (
    DocumentToolsInput,
    EvaluateSearchResultsOutput,
    ExtractContextInfoInput,
    FilesContentsInput,
    KnowledgeHandlerInputBase,
    WebLoaderToolInput,
    WebSearchToolInput,
)
from extension_modules.search_engine import (
    EmbeddingConfig,
    SearchQuery,
    create_knowledge_config,
    generate_embedding_async,
    get_configured_search_engine,
    get_embedding_config_from_app,
    get_embedding_dimension,
)
from extension_modules.search_engine.filter_builder import (
    build_filter_description,
    build_knowledge_filter,
)
from langchain.tools import ToolRuntime
from langchain_core.messages import (
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from open_webui.models.files import Files
from open_webui.models.knowledge import Knowledges
from open_webui.models.users import Users
from open_webui.retrieval.web.main import SearchResult
from pydantic import BaseModel, Field, create_model

log = logging.getLogger(__name__)


# Raw query fallback (Variant A2) — standalone-validity guard 상수
_RAW_QUERY_MIN_LENGTH = 5
_PRONOUN_ONLY_PATTERN = re.compile(
    r"^[\s\?\!\.]*"
    r"(그럼|그러면|그건|그건요|그게|그것|그거|이건|이거|저건|저거)"
    r"(\s+(뭐|뭐야|뭐임|뭐냐|머|머야|어때|어떻|왜|왜요|어디|어디서))?"
    r"[\s\?\!\.]*$"
)

# Filter sentinel values (F2) — LLM 이 "전체/임의 값" 의도로 박는 magic string.
# 이 값이 filter 에 들어가면 OData 절이 wrong column 에 박혀 retrieval 0건이 되므로 strip.
# 비교 시점에 `.strip().lower()` 적용 — Casing variants (`Null`, `NONE`, `Nan`) 자동 cover.
_FILTER_SENTINEL_VALUES = frozenset(
    {"any", "all", "none", "null", "na", "n/a", "전체", "모두", "없음", "-"}
)


def _is_sentinel_value(value: str) -> bool:
    """Return True if the trimmed, lowercased value matches a sentinel literal."""
    return value.strip().lower() in _FILTER_SENTINEL_VALUES


class ToolListBase(BaseModel):
    tools: StructuredTool
    tool_start_message: Optional[str] = None
    tool_end_message: Optional[str] = None
    command_output: Optional[BaseModel] = None


class ReactToolsBase(ReactAgentBase):
    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        **kwargs,
    ):
        super().__init__(api_config, base_url, api_key, metadata, **kwargs)
        self.metadata = metadata
        self.request = kwargs.get("request")  # FastAPI request 객체

        # 임베딩 설정 - 관리자 페이지 > 설정 > 문서 > 임베딩에서 설정된 값 사용
        if self.request:
            # 관리자 설정 기반 임베딩 설정
            self.embedding_config = get_embedding_config_from_app(self.request.app)
            log.info(
                f"[ReactToolsBase] Embedding config loaded from app: "
                f"engine={self.embedding_config.engine}, "
                f"model={self.embedding_config.model}, "
                f"url={self.embedding_config.url[:30] if self.embedding_config.url else 'EMPTY'}..., "
                f"api_key={'SET' if self.embedding_config.api_key else 'EMPTY'}"
            )
        else:
            # fallback: 환경변수 기반 임베딩 설정
            log.warning(
                "[ReactToolsBase] No request object, using env vars for embedding config"
            )
            self.embedding_config = EmbeddingConfig(
                engine=kwargs.get(
                    "embedding_engine",
                    os.getenv("RAG_EMBEDDING_ENGINE", "azure_openai"),
                ),
                model=kwargs.get(
                    "embedding_model",
                    os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-large"),
                ),
                url=kwargs.get(
                    "embedding_url", os.getenv("RAG_AZURE_OPENAI_API_BASE_URL", "")
                ),
                api_key=kwargs.get(
                    "embedding_key", os.getenv("RAG_AZURE_OPENAI_API_KEY", "")
                ),
                api_version=kwargs.get(
                    "azure_api_version",
                    os.getenv("RAG_AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                ),
            )

        # 임베딩 모델 설정에서 벡터 차원 추출
        embedding_model = self.embedding_config.model
        vector_dim = get_embedding_dimension(embedding_model)

        # 인덱스 설정 - knowledge 검색용
        # 인덱스명: default_knowledge (모든 지식기반이 공유하는 인덱스)
        # None을 전달하면 create_knowledge_config()가 기본값 "default_knowledge" 사용
        self.index_name = kwargs.get("index_name") or None

        # 멀티벡터 검색 설정 - 관리자 페이지 > 설정 > 문서에서 설정
        if self.request:
            config = self.request.app.state.config
            self.enable_question_vector = getattr(
                config, "KB_QUESTION_GENERATION_ENABLED", False
            )
            self.question_vector_weight = getattr(
                config, "KB_QUESTION_VECTOR_WEIGHT", 0.5
            )
            # 검색엔진 설정 - 관리자 페이지 > 설정 > 검색엔진에서 설정
            self.search_top_k = getattr(config, "SEARCH_ENGINE_TOP_K", 10)
            self.reranker_top_k = getattr(config, "SEARCH_ENGINE_RERANKER_TOP_K", 3)
            self.reranker_threshold = getattr(
                config, "SEARCH_ENGINE_RERANKER_THRESHOLD", 0.0
            )
        else:
            # fallback: kwargs 또는 기본값
            self.enable_question_vector = kwargs.get("enable_question_vector", False)
            self.question_vector_weight = kwargs.get("question_vector_weight", 0.5)
            self.search_top_k = kwargs.get("search_top_k", 10)
            self.reranker_top_k = kwargs.get("reranker_top_k", 3)
            self.reranker_threshold = kwargs.get("reranker_threshold", 0.0)

        self.index_config = create_knowledge_config(
            index_name=self.index_name,
            vector_dim=vector_dim,
            embedding_model=embedding_model,
            enable_question_vector=self.enable_question_vector,
        )
        self._search_engine = None

        self.files = metadata.get("files") or []
        self.file_collections = (
            self._get_file_collections(self.files) if self.files else []
        )

        # New pattern: use agent_config for knowledge bases
        self.knowledges = self._get_knowledge_list()
        self.enable_evaluation = kwargs.get("enable_evaluation", False)
        self.enable_extract_context_info = kwargs.get(
            "enable_extract_context_info", False
        )
        self.enable_web_search = kwargs.get("enable_web_search", True)
        self.tavily_api_key = kwargs.get("tavily_api_key", True)
        self._web_search_config = kwargs.get("web_search_config")

    def _get_knowledge_list(self) -> List[Dict[str, Any]]:
        """
        Get knowledge base list from agent_config, metadata, and chat files.

        Sources (merged, deduplicated by id):
        1. agent_config.knowledge_bases (primary)
        2. Legacy model.info.meta.knowledge (fallback)
        3. metadata["files"] with type='collection' (e.g. project knowledge)

        Returns:
            List of knowledge base dicts with id, name, description, etc.
        """
        knowledges = []

        # New pattern: use agent_config
        if self.agent_config and self.agent_config.has_knowledge():
            knowledges = list(self.agent_config.get_knowledge_list())
        else:
            # Legacy pattern (fallback for backward compatibility)
            knowledges = list(
                self.metadata.get("model", {})
                .get("info", {})
                .get("meta", {})
                .get("knowledge", [])
            )

        # Merge collection-type files from chat (e.g. # selected knowledge, project knowledge)
        existing_ids = {k.get("id") for k in knowledges}
        for file in self.files:
            if file.get("type") == "collection":
                # # 선택: id 필드, 프로젝트 지식기반: collection_name 필드
                kb_id = file.get("collection_name") or file.get("id")
                if kb_id and kb_id not in existing_ids:
                    knowledges.append(
                        {
                            "id": kb_id,
                            "name": file.get("name", ""),
                            "description": file.get(
                                "description", file.get("name", "")
                            ),
                        }
                    )
                    existing_ids.add(kb_id)

        return knowledges

    def _get_search_engine(self):
        """검색 엔진 인스턴스 반환 (lazy initialization)"""
        if self._search_engine is None:
            if self.request:
                # 관리자 설정 기반 엔진 생성 (with_embedding=False - 수동 임베딩 사용)
                self._search_engine = get_configured_search_engine(
                    self.request.app,
                    self.index_config,
                    with_embedding=False,  # 수동으로 임베딩 생성하므로 자동 임베딩 비활성화
                )
            else:
                # 환경변수 기반 Azure Search 사용 (fallback)
                from extension_modules.search_engine import (
                    AzureSearchConfig,
                    get_search_engine,
                )

                azure_config = AzureSearchConfig(
                    endpoint=os.getenv("SEARCH_ENGINE_AZURE_ENDPOINT", ""),
                    api_key=os.getenv("SEARCH_ENGINE_AZURE_API_KEY", ""),
                    api_version=os.getenv(
                        "SEARCH_ENGINE_AZURE_API_VERSION", "2024-07-01"
                    ),
                )
                # embedding_config는 이미 self.embedding_config에 있지만
                # 여기서는 수동으로 임베딩을 생성하므로 엔진에 전달하지 않음
                self._search_engine = get_search_engine(
                    self.index_config,
                    azure_config,
                    embedding_config=None,  # 수동 임베딩 사용
                )
        return self._search_engine

    async def _generate_query_embedding(
        self,
        query: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[float]:
        """쿼리에 대한 비동기 임베딩 생성 (사용량 추적 및 트레이싱 포함)"""
        # Get trace context from request
        trace_context = None
        if self.request:
            from open_webui.utils.tracing import get_trace_context

            trace_context = get_trace_context(self.request)

        embedding = await generate_embedding_async(
            text=query,
            config=self.embedding_config,
            user_id=user_id,
            chat_id=chat_id,
            trace_context=trace_context,
        )
        return embedding

    def create_search_filter_model(
        self,
        model_name: str,
        base_model: Type[BaseModel],
        filter_schema: dict,
    ) -> Type[BaseModel]:
        """
        filter_schema를 기반으로 새로운 pydantic 모델을 생성한다.

        """
        return create_model(
            model_name,
            __base__=base_model,
            **filter_schema,
        )

    def create_knowledge_handler_input(self, knowledge: Dict[str, Any]):
        return create_model(
            "KnowledgeHandlerInput",
            __base__=KnowledgeHandlerInputBase,
            queries=Field(
                ...,
                description=(
                    "검색어를 제공하세요. **사용자 원본 질문을 그대로 첫 번째 query 로 사용**하고, "
                    "의미 재구성 / 단순화 / 임의 영어 변환 / 한국어 보충 표현 삭제는 금지합니다. "
                    "추가 검색어를 같이 제공하려면 list 로 전달하세요 (BM25 + dense 양쪽 매칭 강화)."
                ),
            ),
        )

    def get_tools(self):
        tools = []
        if self.file_collections:
            # Build file info for tool description so LLM knows available file IDs
            file_info = "\n".join(
                f"  - id: '{f.get('id', '')}', name: '{f.get('name', f.get('id', 'unknown'))}'"
                for f in self.files
                if f.get("type") != "collection"
            )

            files_tool = StructuredTool.from_function(
                coroutine=self.get_file_contents,
                name="get_file_contents",
                description=f"""사용자가 업로드한 파일의 컨텐츠를 조회합니다.
이 도구가 존재하면 사용자가 파일을 업로드한 것이므로, 반드시 이 도구를 호출하여 파일 내용을 확인하세요.
file_ids를 생략하면 모든 파일의 컨텐츠를 반환합니다.

업로드된 파일 목록:
{file_info}""",
                args_schema=FilesContentsInput,
            )
            tools.append(files_tool)

        if self.knowledges:
            # 사용자가 접근 가능한 지식 기반 목록만 조회하여 도구 생성
            kb_user_id = self.metadata.get("user_id", "")
            kb_user = Users.get_user_by_id(kb_user_id) if kb_user_id else None
            if kb_user and kb_user.role == "admin":
                user_knowledge_bases = Knowledges.get_knowledge_bases()
            else:
                user_knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(
                    kb_user_id, "read"
                )
            accessible_kb_ids = {kb.id for kb in user_knowledge_bases}

            # Collect combined filter schema from all accessible KBs
            combined_filter_schema = []
            for knowledge in self.knowledges:
                kb_id = knowledge.get("id")
                if kb_id in accessible_kb_ids:
                    kb = Knowledges.get_knowledge_by_id(kb_id)
                    if kb and kb.meta and kb.meta.get("filter_schema"):
                        for field in kb.meta["filter_schema"]:
                            if not any(
                                f["label"] == field["label"]
                                for f in combined_filter_schema
                            ):
                                combined_filter_schema.append(field)

            # Register a SINGLE knowledge_handler tool (not one-per-KB). Previously a
            # tool was appended per KB all named "knowledge_handler", so LangChain kept
            # only the last one and only the last KB's description reached the LLM.
            # Now: one tool whose description lists every connected KB, plus a
            # knowledge_ids selector (Literal enum) so the LLM can scope the search.
            accessible_ids_ordered = [
                knowledge.get("id")
                for knowledge in self.knowledges
                if knowledge.get("id") in accessible_kb_ids
            ]

            if accessible_ids_ordered:
                catalog_lines = []
                for knowledge in self.knowledges:
                    kb_id = knowledge.get("id")
                    if kb_id not in accessible_kb_ids:
                        continue
                    kb_obj = Knowledges.get_knowledge_by_id(kb_id)
                    # Prefer meta.tool_description (AI-facing), fallback to description
                    if kb_obj and kb_obj.meta and kb_obj.meta.get("tool_description"):
                        kb_desc = kb_obj.meta["tool_description"]
                    else:
                        kb_desc = knowledge.get("description", "")
                    kb_name = (kb_obj.name if kb_obj else "") or kb_id
                    line = f"- {kb_id} | {kb_name}: {kb_desc}".strip()
                    # Per-KB filters — each KB has its OWN filter_schema; a filter
                    # only applies to the KB that defines it (see knowledge_handler).
                    kb_schema = (
                        kb_obj.meta.get("filter_schema")
                        if kb_obj and kb_obj.meta
                        else None
                    )
                    if kb_schema:
                        kb_filter_desc = build_filter_description(kb_schema)
                        indented = "\n".join(
                            "  " + ln for ln in kb_filter_desc.split("\n")
                        )
                        line += "\n" + indented
                    catalog_lines.append(line)

                catalog_desc = (
                    "연결된 지식 기반에서 문서를 검색합니다.\n\n"
                    "사용 가능한 지식 기반:\n" + "\n".join(catalog_lines) + "\n\n"
                    "knowledge_ids 로 검색 대상을 좁힐 수 있습니다. 질문과 명확히 "
                    "관련된 지식 기반만 선택하고, 어디에 답이 있을지 불확실하면 "
                    "knowledge_ids 를 생략하여 전체를 검색하세요.\n"
                    "filters 의 각 항목은 그 필터를 정의한 지식 기반에만 적용됩니다 — "
                    "위 각 지식 기반에 표시된 '사용 가능한 검색 필터' 항목만 사용하세요."
                )

                # Dynamic args schema: always expose the knowledge_ids selector;
                # add filters only when some KB defines a filter_schema.
                schema_fields: Dict[str, Any] = {
                    "knowledge_ids": (
                        Optional[List[Literal[tuple(accessible_ids_ordered)]]],
                        Field(
                            default=None,
                            description=(
                                "검색할 지식 기반 id 목록. 생략하면 전체 지식 기반을 "
                                "검색합니다. 위 '사용 가능한 지식 기반' 목록의 id "
                                "중에서만 선택하세요."
                            ),
                        ),
                    ),
                }
                if combined_filter_schema:
                    filter_hint = build_filter_description(combined_filter_schema)
                    schema_fields["filters"] = (
                        Optional[Dict[str, Any]],
                        Field(
                            default=None,
                            description=(
                                f"선택적 검색 필터. {filter_hint}. "
                                '예: {{"부서": "재무팀", "연도": 2024}}. '
                                "**필터 사용 원칙: 사용자 질의에 명시적으로 드러난 "
                                "조건만 필터로 사용하세요. 맥락이나 추측으로 필터 값을 "
                                "유추하지 마세요 — 추측한 필터는 정작 답이 들어있는 "
                                "문서를 조용히 제외시켜 검색 누락을 유발합니다. 질의에 "
                                "필터 조건이 명확하지 않으면 filters 없이 검색하고 "
                                "관련도 랭킹에 맡기세요. 필터를 건 검색이 충분한 답을 "
                                "주지 못하면 filters 를 완전히 제거하고 전체 범위로 "
                                "다시 검색하세요.**"
                            ),
                        ),
                    )

                KnowledgeHandlerInput = create_model(
                    "KnowledgeHandlerInput",
                    __base__=KnowledgeHandlerInputBase,
                    **schema_fields,
                )

                knowledge_tool = StructuredTool.from_function(
                    coroutine=self.knowledge_handler,
                    name="knowledge_handler",
                    description=catalog_desc,
                    args_schema=KnowledgeHandlerInput,
                )
                tools.append(knowledge_tool)

                # --- 문서 주소지정 도구 (P1): 요약 조회 + 다중 문서 비교 ---
                # 기존 knowledge_handler(top-k 의미검색)는 그대로 두고, 문서를 직접
                # 지정해 다루는 경로를 별도 도구로 추가한다 (additive — 일반 검색
                # 경로 불변). 접근 가능한 연결 KB 의 file_id → collection 매핑을
                # 한 번 만들어 도구 설명(카탈로그)과 호출 시 접근 검증에 함께 사용.
                doc_file_map: Dict[str, str] = {}  # file_id -> collection(kb) id
                doc_catalog_lines: List[str] = []
                compare_kb_map: Dict[str, str] = {}  # kb_id -> kb name
                for kb_id in accessible_ids_ordered:
                    kb_obj = Knowledges.get_knowledge_by_id(kb_id)
                    if not kb_obj:
                        continue
                    compare_kb_map[kb_id] = kb_obj.name or kb_id
                    kb_file_ids = (kb_obj.data or {}).get("file_ids") or []
                    if not kb_file_ids:
                        continue
                    for f in Files.get_files_by_ids(kb_file_ids):
                        if f.id in doc_file_map:
                            continue
                        fname = (f.meta or {}).get("name") or f.filename or f.id
                        doc_file_map[f.id] = kb_id
                        # 카탈로그(도구 설명) 토큰 보호 — 표시는 100건까지만,
                        # 접근 화이트리스트(doc_file_map)는 전체 보존.
                        if len(doc_catalog_lines) < 100:
                            doc_catalog_lines.append(
                                f"  - id: '{f.id}', name: '{fname}'"
                            )
                self._doc_file_map = doc_file_map
                self._compare_kb_map = compare_kb_map

                if doc_file_map:
                    catalog_block = "\n".join(doc_catalog_lines)
                    hidden = len(doc_file_map) - len(doc_catalog_lines)
                    if hidden > 0:
                        catalog_block += (
                            f"\n  ...(외 {hidden}개 문서 — 목록에 없으면 "
                            "knowledge_handler 로 검색)"
                        )
                    kb_block = "\n".join(
                        f"  - id: '{kid}', name: '{kname}'"
                        for kid, kname in compare_kb_map.items()
                    )

                    # ── 문서 처리 통합 디스패처 (A/B: freeform-args 품질 영향 측정) ──
                    # 기존 3개(get_document_summary/summarize_document/compare_documents)를
                    # 단일 document_tools(operation, args) 로 합쳐 톱레벨 도구 수를 줄인다.
                    # 라우팅은 동일 메서드로(동작 불변), 인자만 operation 별 dict 로 받는다.
                    cmp_filter_line = ""
                    cmp_filter_arg = ""
                    if combined_filter_schema:
                        cmp_filter_arg = ", filters?:{...}"
                        cmp_filter_line = (
                            "\n  · filters(선택): "
                            + build_filter_description(combined_filter_schema)
                            + " — 질의에 명시된 조건만, 추측 금지"
                        )
                    doc_dispatch_desc = (
                        "문서 처리 통합 도구. operation 으로 작업을 고르고 args 에 인자를 "
                        "dict 로 전달하세요.\n\n"
                        "operation 목록:\n"
                        "- 'get_summary': 지정 문서의 사전 생성된 짧은 요약 조회. "
                        "args={file_ids:[...]}. 특정 문서 개요를 빠르게.\n"
                        "- 'summarize': 단일 문서 '심층 요약'(문서 전문 기반). "
                        "args={file_id:'..', focus?:'관점'}. 상세 요약 필요 시.\n"
                        "- 'compare': 여러 대상 비교 근거 수집(대상별 펜싱+RRF). "
                        f"args={{aspects:[검색어들], file_ids?:[...], knowledge_ids?:[...]{cmp_filter_arg}}}. "
                        "'A와 B 비교', '프로젝트 1·2·3·4 차이' 등 다중대상 질의.\n"
                        "  · aspects 는 속성별로 분해+한/영·단위 포함 "
                        "(예: ['정격 유량 rated flow m3/hr','정격 양정 total head m','모델명 model']).\n"
                        "  · 문서끼리=file_ids, 지식기반끼리=knowledge_ids."
                        + cmp_filter_line
                        + "\n\n조회 가능한 문서 목록:\n"
                        + catalog_block
                        + "\n\n비교 가능한 지식 기반 목록:\n"
                        + kb_block
                    )
                    doc_tools_tool = StructuredTool.from_function(
                        coroutine=self.document_tools,
                        name="document_tools",
                        description=doc_dispatch_desc,
                        args_schema=DocumentToolsInput,
                    )
                    tools.append(doc_tools_tool)

        if self.enable_extract_context_info:
            extract_context_info_tool = StructuredTool.from_function(
                func=self.extract_context_info,
                name="extract_context_info",
                description="""
                이 도구는 어떤 도구보다 **가장 먼저 수행** 되어야 합니다. 

                질문에서 언어 및 질문에서 오탈자나 문맥을 정제한 질문을 추출합니다.
                - language: 짧은 언어 식별자 (예: Korean/English 등)
                - normalized_question: 질문에서 오탈자나 문맥 (채팅 히스토리 포함)을 정제한 질문

                규칙:
                - 목표 응답 언어 결정: 사용자의 명시적 요청(예: 'write in English')을 최우선으로 하고, 그렇지 않으면 입력 텍스트의 주 언어를 감지하세요.
                """,
                args_schema=ExtractContextInfoInput,
            )
            tools.append(extract_context_info_tool)

        if self.enable_evaluation:
            evaluation_tool = StructuredTool.from_function(
                func=self.evaluation_result,
                name="evaluation_result",
                description="""검색 결과를 평가합니다. 
                검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하고 점수와 이유를 추출하여 상태를 설정 합니다.
                context를 리턴 받는 모든 도구를 호출시 무조건 이 도구를 통해 평가를 수행해야 합니다.
                
                """,
                args_schema=EvaluateSearchResultsOutput,
            )
            tools.append(evaluation_tool)

        if self.enable_web_search:
            web_search_tool = StructuredTool.from_function(
                coroutine=self.search_web,
                name="search_web",
                description="외부 웹 검색 엔진으로 쿼리를 검색하여 결과 목록을 반환합니다. "
                "웹 검색은 내부 데이터에 없는 최신 정보나 외부 정보가 필요할 때만 사용합니다.",
                args_schema=WebSearchToolInput,
            )
            tools.append(web_search_tool)

            web_loader_tool = StructuredTool.from_function(
                coroutine=self.load_web_page,
                name="load_web_page",
                description="URL에서 웹 페이지의 전체 내용을 추출합니다. "
                "사용자가 특정 URL 본문 추출을 요청하거나, "
                "기존 검색 결과만으로 답변이 어려운 경우에만 사용하세요.",
                args_schema=WebLoaderToolInput,
            )
            tools.append(web_loader_tool)

        return tools

    def _get_raw_query_fallback_enabled(self) -> bool:
        """Return whether raw user message fallback (Variant A2) is enabled.

        Checks request.app.state.config.SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED.
        Defaults to True when config not present (e.g., embedded usage without request).
        """
        if self.request:
            return bool(
                getattr(
                    self.request.app.state.config,
                    "SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED",
                    True,
                )
            )
        return True

    @staticmethod
    def _normalize_for_dedup(text: str) -> str:
        """NFKC normalize + lowercase + whitespace collapse for dedup key."""
        if text is None:
            return ""
        normalized = unicodedata.normalize("NFKC", text)
        return " ".join(normalized.lower().split())

    @staticmethod
    def _is_standalone_valid_query(text: Optional[str]) -> bool:
        """Return True if raw user message is suitable for standalone retrieval.

        Guards:
        - None / 빈 문자열
        - strip 후 길이 < 5자 (ACME fixtures 기준)
        - JSON 형태 ({...})
        - 대명사-only follow-up ("그럼?", "그건 뭐야")
        """
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) < _RAW_QUERY_MIN_LENGTH:
            return False
        if stripped.startswith("{") and stripped.endswith("}"):
            return False
        if _PRONOUN_ONLY_PATTERN.match(stripped):
            return False
        return True

    @staticmethod
    def _strip_sentinel_filter_values(
        filters: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Drop sentinel ('Any', '전체', null, ...) values from LLM-provided filters (F2).

        LLM 이 "조건 없음" 의도로 sentinel 을 박으면 OData filter 가 wrong column 에
        그대로 박혀 retrieval 0건이 됨. None / 빈 dict 면 그대로 반환.
        """
        if not filters:
            return filters
        cleaned: Dict[str, Any] = {}
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, list):
                kept = [
                    v for v in value if v is not None and not _is_sentinel_value(str(v))
                ]
                if kept:
                    cleaned[key] = kept
                continue
            if isinstance(value, str):
                if not value.strip() or _is_sentinel_value(value):
                    continue
                cleaned[key] = value
                continue
            # int / float / bool / dict 등은 그대로 통과
            cleaned[key] = value
        return cleaned or None

    @staticmethod
    def _build_search_query_list(
        queries: Union[str, List[str]],
        raw_user_message: Optional[str],
        enable_fallback: bool = True,
    ) -> List[str]:
        """Build dedup'd search query list with raw user message prepend (Variant A2).

        Mitigates LLM query drift (Channel B/C/D) by anchoring retrieval with
        the raw user message. Falls back to LLM-only when:
        - feature flag off
        - raw_user_message is None
        - standalone-validity guard fails (follow-up noise)
        """
        # str -> [str] 변환 (backward compat)
        llm_queries = [queries] if isinstance(queries, str) else list(queries)

        if not enable_fallback or raw_user_message is None:
            return llm_queries

        if not ReactToolsBase._is_standalone_valid_query(raw_user_message):
            return llm_queries

        # Prepend raw + dedup (raw 가 first → dedup 후에도 first 보존)
        combined = [raw_user_message] + llm_queries
        seen = set()
        result = []
        for q in combined:
            key = ReactToolsBase._normalize_for_dedup(q)
            if not key:  # 빈 문자열 / whitespace-only → skip
                continue
            if key not in seen:
                seen.add(key)
                result.append(q)
        return result

    async def knowledge_handler(
        self,
        queries: Union[str, List[str]],
        filters: Optional[Dict[str, Any]] = None,
        knowledge_ids: Optional[List[str]] = None,
    ):
        """
        지식 기반 검색 핸들러.
        AzureSearchEngine을 사용하여 검색하고 임베딩 사용량을 추적합니다.
        enable_question_vector=True인 경우 멀티벡터 검색 수행 (vector + vector_question).

        Args:
            queries: 검색어 (단일 문자열 또는 목록)
            filters: 선택적 검색 필터. KB filter_schema에 정의된 label을 키로 사용.
                     예: {"부서": "재무팀", "연도": 2024}
            knowledge_ids: 검색 대상 지식 기반 id 목록. 생략하면 전체 검색.
        """
        # Raw user message fallback (Variant A2) — system prompt 가 LLM 의 query 작성을
        # 흔드는 retrieval drift 차단. UnifiedAgent._run_agent 진입 시 stash 됨.
        raw_user_message = getattr(self, "_raw_user_message_for_retrieval", None)
        enable_fallback = self._get_raw_query_fallback_enabled()
        llm_query_count = (
            1 if isinstance(queries, str) else len(queries) if queries else 0
        )
        query_list = self._build_search_query_list(
            queries=queries,
            raw_user_message=raw_user_message,
            enable_fallback=enable_fallback,
        )
        # F2 — LLM 이 'Any', '전체' 등 sentinel 값을 filter 에 넣으면 OData 에서
        # AND 충돌로 retrieval 0건이 되므로 사전 strip.
        filters = self._strip_sentinel_filter_values(filters)

        # 진단 로그 (DEBUG 레벨). Variant A2 활성 여부 + raw 사용 여부 + dedup 효과.
        if log.isEnabledFor(logging.DEBUG):
            raw_used = bool(
                raw_user_message
                and enable_fallback
                and self._is_standalone_valid_query(raw_user_message)
            )
            log.debug(
                "[knowledge_handler] raw_fallback=%s, llm_n=%d, final_n=%d, "
                "raw_used=%s, dedup_collapsed=%d",
                enable_fallback,
                llm_query_count,
                len(query_list),
                raw_used,
                max(0, llm_query_count + 1 - len(query_list)) if raw_used else 0,
            )

        # Resolve which knowledge bases to search. The LLM may pass knowledge_ids to
        # scope the search; omitting it searches ALL connected KBs (default behavior).
        all_kb_ids = [c.get("id") for c in self.knowledges if c.get("id")]
        if knowledge_ids:
            selected_set = {kid for kid in knowledge_ids if kid in set(all_kb_ids)}
            if not selected_set:
                log.warning(
                    "[knowledge_handler] knowledge_ids=%s matched no connected KB; "
                    "falling back to ALL",
                    knowledge_ids,
                )
                selected_set = set(all_kb_ids)
        else:
            selected_set = set(all_kb_ids)

        # Per-knowledge search settings override
        effective_top_k = self.search_top_k
        effective_reranker_top_k = self.reranker_top_k
        effective_threshold = self.reranker_threshold
        effective_question_vector = self.enable_question_vector
        effective_question_weight = self.question_vector_weight
        threshold_overridden = False

        for kb_info in self.knowledges:
            if kb_info.get("id") not in selected_set:
                continue
            kb = Knowledges.get_knowledge_by_id(kb_info.get("id"))
            if not kb or not kb.meta:
                continue
            ss = kb.meta.get("search_settings") or {}
            if ss.get("top_k") is not None:
                effective_top_k = max(effective_top_k, ss["top_k"])
            if ss.get("reranker_top_k") is not None:
                effective_reranker_top_k = max(
                    effective_reranker_top_k, ss["reranker_top_k"]
                )
            if ss.get("reranker_threshold") is not None:
                if not threshold_overridden:
                    # 첫 per-KB override: 전역값 대신 per-KB 값으로 시작
                    effective_threshold = ss["reranker_threshold"]
                    threshold_overridden = True
                else:
                    # 여러 KB: per-KB 값 중 가장 낮은 값 사용
                    effective_threshold = min(
                        effective_threshold, ss["reranker_threshold"]
                    )
            if ss.get("question_vector_weight") is not None:
                effective_question_weight = ss["question_vector_weight"]

        collection_ids = [cid for cid in all_kb_ids if cid in selected_set]

        # Build base collection filter
        collection_filter = " or ".join(
            [f"collection eq '{c}'" for c in collection_ids]
        )

        # Apply user-defined filters PER KB. Each filter only applies to the KB
        # that defines it:
        #   (collection eq A and <A's filters>) or (collection eq B and <B's
        #   filters>) or (collection eq C)
        # A single global AND (collection eq A or B) and <field eq v> would wrongly
        # exclude docs from KBs that don't have that field (different KBs have
        # different filter_schema). Each KB owns its own filters.
        filter_expr = collection_filter
        if filters and collection_ids:
            parts = []
            for cid in collection_ids:
                kb = Knowledges.get_knowledge_by_id(cid)
                kb_schema = kb.meta.get("filter_schema") if kb and kb.meta else None
                if kb_schema:
                    # build_knowledge_filter scopes to this single collection and
                    # only applies the labels present in THIS KB's schema.
                    sub = build_knowledge_filter(
                        collection_ids=[cid],
                        filter_schema=kb_schema,
                        filter_values=filters,
                    )
                    parts.append(f"({sub})")
                else:
                    parts.append(f"collection eq '{cid}'")
            if parts:
                filter_expr = " or ".join(parts)

        # 사용자 정보 추출 (사용량 추적용)
        user_id = self.metadata.get("user_id")
        chat_id = self.metadata.get("chat_id")

        search_engine = self._get_search_engine()
        if not search_engine:
            log.warning("Search engine not configured")
            return {"sources": []}

        # Trace context for RETRIEVAL span
        trace_context = None
        if self.request:
            from open_webui.utils.tracing import get_trace_context

            trace_context = get_trace_context(self.request)

        if trace_context and trace_context.enabled:
            from open_webui.models.message_trace import RunType

            ctx_manager = trace_context.start_run_async(
                run_type=RunType.RETRIEVAL.value,
                name="knowledge_search",
                inputs={
                    "queries": query_list,
                    "collection_ids": collection_ids,
                    "filter": filter_expr,
                },
                push_stack=False,
            )
        else:
            from extension_modules.search_engine.embedding import (
                _null_async_context,
            )

            ctx_manager = _null_async_context()

        all_results = []

        try:
            async with ctx_manager as retrieval_run:
                # 1. 모든 쿼리의 임베딩을 병렬 생성
                query_vectors = await asyncio.gather(
                    *(
                        self._generate_query_embedding(
                            query=query,
                            user_id=user_id,
                            chat_id=chat_id,
                        )
                        for query in query_list
                    )
                )

                # 2. 모든 검색을 병렬 수행
                async def _search_single(
                    query: str,
                    query_vector: List[float],
                    filter_to_use: str,
                ):
                    if effective_question_vector:
                        return await search_engine.multi_vector_search(
                            text=query,
                            vector=query_vector,
                            secondary_vector=query_vector,
                            top_k=effective_top_k,
                            filter_expr=filter_to_use,
                            primary_weight=1 - effective_question_weight,
                            secondary_weight=effective_question_weight,
                            reranker_threshold=effective_threshold,
                            user_id=user_id,
                            chat_id=chat_id,
                        )
                    else:
                        search_query = SearchQuery(
                            query=query,
                            filter=filter_to_use,
                            top_k=effective_top_k,
                            top_k_vector=effective_top_k * 3,
                            reranker_threshold=effective_threshold,
                        )
                        return await search_engine.search(
                            query=search_query,
                            query_vector=query_vector,
                        )

                # 1차: full filter (collection + user filter)
                search_results = await asyncio.gather(
                    *(
                        _search_single(query, vector, filter_expr)
                        for query, vector in zip(query_list, query_vectors)
                    )
                )

                # F4 — Filter fallback retry. user filter 가 적용된 1차 검색이 0건이면
                # LLM 의 filter value 가 KB chunk metadata 와 매칭 안 됐을 가능성이 큼
                # (예: LLM 'TH' vs KB 'Thailand'). collection_filter 만으로 재검색하여
                # 정보 회수. ACME 회귀 즉시 해소.
                total_hits = sum(len(r) for r in search_results)
                if (
                    total_hits == 0
                    and filter_expr != collection_filter
                    and collection_filter
                ):
                    log.info(
                        "[knowledge_handler] FILTER_FALLBACK: user filter 0 hits "
                        "→ retry with collection_filter only. dropped_filter=%r",
                        filter_expr,
                    )
                    search_results = await asyncio.gather(
                        *(
                            _search_single(query, vector, collection_filter)
                            for query, vector in zip(query_list, query_vectors)
                        )
                    )

                for results in search_results:
                    all_results.extend(results)

                # 다중 질의 융합: RRF(Reciprocal Rank Fusion).
                # 질의마다 점수 스케일이 달라 단순 score 정렬은 한 질의 결과가
                # 독식하기 쉬움. 각 질의의 "순위"만으로 합산(1/(C+rank))하여
                # 여러 질의에서 고르게 상위인 문서를 끌어올린다. 질의가 1개면
                # 순위=점수 순서라 기존 동작과 동일(회귀 없음).
                _RRF_C = 60
                rrf_scores: Dict[str, float] = {}
                rep: Dict[str, Any] = {}  # id -> 대표 SearchResult(최고 score 보존)
                for results in search_results:
                    for rank, r in enumerate(results):
                        rrf_scores[r.id] = rrf_scores.get(r.id, 0.0) + 1.0 / (
                            _RRF_C + rank + 1
                        )
                        if r.id not in rep or r.score > rep[r.id].score:
                            rep[r.id] = r
                unique_results = sorted(
                    rep.values(), key=lambda r: rrf_scores[r.id], reverse=True
                )

                if log.isEnabledFor(logging.DEBUG):
                    log.debug(
                        "[knowledge_handler] queries=%d, unique=%d, top5_scores=%s, "
                        "reranker_threshold=%.3f, top_k=%d, question_vector=%s",
                        len(query_list),
                        len(unique_results),
                        [round(r.score, 4) for r in unique_results[:5]],
                        effective_threshold,
                        effective_top_k,
                        effective_question_vector,
                    )

                # RETRIEVAL trace outputs 기록
                if retrieval_run:
                    retrieval_run.set_outputs(
                        {
                            "total_results": len(unique_results),
                            "top_scores": [
                                round(r.score, 4) for r in unique_results[:5]
                            ],
                            "reranked": any(r.reranked for r in unique_results)
                            if unique_results
                            else False,
                            "sources": [
                                {
                                    "name": r.metadata.get("name", "")
                                    if r.metadata
                                    else "",
                                    "score": round(r.score, 4),
                                }
                                for r in unique_results[:effective_reranker_top_k]
                            ],
                        }
                    )

            # SearchResult를 dict로 변환
            items = [
                {
                    "id": r.id,
                    "content": r.content.encode("utf-8", errors="surrogatepass").decode(
                        "utf-8", errors="replace"
                    )
                    if r.content
                    else "",
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in unique_results[:effective_reranker_top_k]
            ]

            return self._items_to_openwebui_sources(
                items,
                source_type="knowledge_base",
                source_scope="agent_knowledge",
                citation_policy="required",
                origin_tool="knowledge_handler",
            )

        finally:
            # 검색 엔진 리소스 정리
            if self._search_engine:
                await self._search_engine.close()
                self._search_engine = None

    async def document_tools(
        self, operation: str, args: Optional[Dict[str, Any]] = None
    ):
        """문서 처리 통합 디스패처 — operation 으로 요약/심층요약/비교 라우팅(동작 불변).

        개별 타입드 도구를 단일 도구로 합친 형태(톱레벨 도구 수↓). 인자는 operation
        별 dict 로 받고, 필수 인자 누락 시 명확한 오류를 돌려 LLM 이 자가수정하게 한다.
        """
        args = args or {}
        op = (operation or "").strip().lower()
        try:
            if op in ("get_summary", "summary", "get_document_summary"):
                file_ids = args.get("file_ids") or args.get("file_id")
                if not file_ids:
                    return {
                        "sources": [],
                        "error": "get_summary 는 args.file_ids(목록)가 필요합니다.",
                    }
                return await self.get_document_summary(file_ids)
            if op in ("summarize", "summarize_document", "deep_summary"):
                file_id = args.get("file_id") or args.get("file_ids")
                if isinstance(file_id, list):
                    file_id = file_id[0] if file_id else None
                if not file_id:
                    return {
                        "sources": [],
                        "error": "summarize 는 args.file_id 가 필요합니다.",
                    }
                return await self.summarize_document(file_id, args.get("focus"))
            if op in ("compare", "compare_documents"):
                aspects = args.get("aspects") or args.get("aspect")
                if not aspects:
                    return {
                        "sources": [],
                        "error": "compare 는 args.aspects(검색어 목록)가 필요합니다.",
                    }
                return await self.compare_documents(
                    aspects,
                    file_ids=args.get("file_ids"),
                    knowledge_ids=args.get("knowledge_ids"),
                    filters=args.get("filters"),
                )
            return {
                "sources": [],
                "error": (
                    f"알 수 없는 operation '{operation}'. "
                    "get_summary | summarize | compare 중에서 사용하세요."
                ),
            }
        except Exception as e:
            log.warning("[document_tools] op=%s failed: %s", operation, e)
            return {"sources": [], "error": f"document_tools 오류: {e}"}

    async def get_document_summary(self, file_ids: Union[str, List[str]]):
        """지정한 문서(파일)의 사전 생성 요약(file.meta.summary)을 조회한다.

        인제스트 시 _generate_file_summary_sync 가 만들어 file.meta 에 저장해 둔
        문서 단위 요약을 그대로 반환한다 — 검색/임베딩 비용 0, 문서 전체 반영.
        "문서 X 요약" 류 질의가 top-k 청크 검색으로 변질돼 일부만 반영되던 문제를
        해소한다. 접근 가능한(연결 KB 소속) 문서만 허용 — get_tools 에서 만든
        self._doc_file_map 화이트리스트로 필터링하여 권한 우회를 차단.
        """
        if isinstance(file_ids, str):
            file_ids = [file_ids]
        allowed = getattr(self, "_doc_file_map", {}) or {}

        items: List[Dict[str, Any]] = []
        for fid in file_ids or []:
            if fid not in allowed:
                log.warning(
                    "[get_document_summary] file_id=%s not in accessible docs; skipped",
                    fid,
                )
                continue
            f = Files.get_file_by_id(fid)
            if not f:
                continue
            meta = f.meta or {}
            fname = meta.get("name") or f.filename or fid
            # deep_summary(전문 map-reduce) 우선, 없으면 짧은 사전요약
            deep = meta.get("deep_summary")
            short = meta.get("summary")
            if deep:
                content, kind = deep, "deep"
            elif short:
                content, kind = short, "short"
            else:
                content, kind = (
                    f"'{fname}' 문서에는 사전 생성된 요약이 없습니다. 문서 전체의 "
                    "상세 요약이 필요하면 summarize_document 를, 특정 내용 검색은 "
                    "knowledge_handler 를 사용하세요.",
                    "none",
                )
            items.append(
                {
                    "id": fid,
                    "content": content,
                    "metadata": {
                        "name": fname,
                        "file_id": fid,
                        "summary_kind": kind,
                    },
                }
            )

        return self._items_to_openwebui_sources(
            items,
            source_type="knowledge_base",
            source_scope="document_summary",
            citation_policy="optional",
            origin_tool="get_document_summary",
        )

    def _doc_summary_sources(
        self, file_id: str, fname: str, content: str, kind: str
    ) -> Dict[str, Any]:
        """summarize_document 결과를 OpenWebUI sources 포맷으로 래핑."""
        return self._items_to_openwebui_sources(
            [
                {
                    "id": file_id,
                    "content": content,
                    "metadata": {
                        "name": fname,
                        "file_id": file_id,
                        "summary_kind": kind,
                    },
                }
            ],
            source_type="knowledge_base",
            source_scope="document_summary",
            citation_policy="optional",
            origin_tool="summarize_document",
        )

    async def summarize_document(self, file_id: str, focus: Optional[str] = None):
        """단일 문서의 심층 요약(전문 map-reduce)을 반환한다.

        get_document_summary(짧은 사전요약)와 달리 문서 전문을 토큰 윈도로 나눠
        MAP→REDUCE 하여 문서 전체를 빠짐없이 반영한 요약을 만든다(검색 top-k 아님).
        - 이미 생성된 deep_summary 가 있으면 그대로 반환(캐시)
        - 없으면 전문을 청크에서 복원해 생성 후 file.meta.deep_summary 에 캐시
        - KB search_settings.deep_summary_mode == 'off' 이면 짧은 요약으로 폴백
        - focus 지정 시 그 관점 중심으로 생성하며 캐시하지 않음(질의별 1회성)
        접근은 self._doc_file_map 화이트리스트로 검증.
        """
        allowed = getattr(self, "_doc_file_map", {}) or {}
        if file_id not in allowed:
            log.warning(
                "[summarize_document] file_id=%s not accessible; skipped", file_id
            )
            return {"sources": []}

        f = Files.get_file_by_id(file_id)
        if not f:
            return {"sources": []}
        meta = f.meta or {}
        fname = meta.get("name") or f.filename or file_id

        kb_id = allowed[file_id]
        kb = Knowledges.get_knowledge_by_id(kb_id)
        ss = (kb.meta.get("search_settings") if kb and kb.meta else None) or {}
        deep_mode = ss.get("deep_summary_mode", "on_demand")
        model_override = ss.get("file_summary_model")

        # 1) 캐시된 deep_summary (focus 없을 때만 캐시 사용)
        cached = meta.get("deep_summary")
        if cached and not focus:
            return self._doc_summary_sources(file_id, fname, cached, "deep")

        # 2) off 모드 → 짧은 요약 폴백 (생성하지 않음)
        if deep_mode == "off":
            short = meta.get("summary")
            content = short or (
                f"'{fname}' 문서의 심층 요약이 비활성화되어 있고 사전 요약도 "
                "없습니다. knowledge_handler 로 검색하세요."
            )
            return self._doc_summary_sources(
                file_id, fname, content, "short" if short else "none"
            )

        # 3) 생성 — 앱 컨텍스트 필요
        if not self.request:
            short = meta.get("summary")
            if short:
                return self._doc_summary_sources(file_id, fname, short, "short")
            return {"sources": []}

        from open_webui.retrieval.deep_summary import (
            generate_deep_summary,
            stitch_document_text,
        )

        # 전문 복원: file_id 로 전체 청크를 가져와(검색 아님) chunk_index 순 + start_index
        # 기반 오버랩 제거로 잇는다.
        text = ""
        search_engine = self._get_search_engine()
        if search_engine:
            try:
                safe_c = kb_id.replace("'", "''")
                safe_f = file_id.replace("'", "''")
                filter_expr = f"collection eq '{safe_c}' and file_id eq '{safe_f}'"
                docs = await search_engine.filter_by_metadata(filter_expr, 2000)
                if len(docs) >= 2000:
                    log.warning(
                        "[summarize_document] file_id=%s hit chunk fetch limit 2000 "
                        "— 요약이 일부만 반영될 수 있음",
                        file_id,
                    )
                text = stitch_document_text(docs)
            except Exception as e:
                log.warning("[summarize_document] chunk fetch failed: %s", e)
            finally:
                if self._search_engine:
                    await self._search_engine.close()
                    self._search_engine = None

        if not text.strip():
            short = meta.get("summary")
            if short:
                return self._doc_summary_sources(file_id, fname, short, "short")
            return {"sources": []}

        deep = await generate_deep_summary(
            self.request.app,
            text,
            fname,
            model_override=model_override,
            focus=focus,
        )
        if not deep:
            short = meta.get("summary")
            if short:
                return self._doc_summary_sources(file_id, fname, short, "short")
            return {"sources": []}

        # focus 없을 때만 캐시 (focus 요약은 질의별 1회성)
        if not focus:
            try:
                Files.update_file_metadata_by_id(file_id, {"deep_summary": deep})
            except Exception as e:
                log.warning("[summarize_document] cache write failed: %s", e)

        log.info(
            "[summarize_document] file_id=%s generated deep summary (focus=%s, len=%d)",
            file_id,
            bool(focus),
            len(deep),
        )
        return self._doc_summary_sources(file_id, fname, deep, "deep")

    async def compare_documents(
        self,
        aspects: Union[str, List[str]],
        file_ids: Optional[List[str]] = None,
        knowledge_ids: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ):
        """여러 대상(문서/지식기반)을 여러 검색어(aspects)로 대상별 개별 검색해 비교 근거를 모은다.

        knowledge_handler 의 "전역 병합 → 전역 top-k 컷" 과 달리 대상마다 독립
        펜싱 검색 + 대상별 고정 쿼터를 유지하여, 한 대상이 점수를 독식해 다른
        대상이 0건이 되는 비교 실패를 차단한다. 각 대상에서 aspects(다중 질의)를
        모두 검색해 RRF 로 융합(사양표 청크 recall↑), 필터는 knowledge_handler 와
        동일하게 KB filter_schema 로 결합하며 0건이면 대상별로 필터를 빼고 재검색한다.

        - file_ids: 문서 단위 — "collection eq C and file_id eq X" 펜싱
        - knowledge_ids: 지식기반 단위 — "collection eq KB" 펜싱
        - filters: KB filter_schema 라벨→값 (그 KB 스키마에만 적용)
        접근은 self._doc_file_map / self._compare_kb_map 화이트리스트로 검증.
        """
        aspect_list = [aspects] if isinstance(aspects, str) else list(aspects or [])
        aspect_list = [a for a in aspect_list if a and a.strip()]
        if not aspect_list:
            return {"sources": []}
        filters = self._strip_sentinel_filter_values(filters)

        allowed_files = getattr(self, "_doc_file_map", {}) or {}
        allowed_kbs = getattr(self, "_compare_kb_map", {}) or {}

        # 비교 대상 entity 구성 (필터는 검색 시점에 KB 스키마로 결합).
        entities: List[Dict[str, Any]] = []
        seen_keys = set()

        for fid in file_ids or []:
            if fid not in allowed_files:
                log.warning(
                    "[compare_documents] file_id=%s not accessible; skipped", fid
                )
                continue
            if ("file", fid) in seen_keys:
                continue
            seen_keys.add(("file", fid))
            f = Files.get_file_by_id(fid)
            label = (((f.meta or {}).get("name") or f.filename) if f else None) or fid
            entities.append(
                {
                    "kind": "document",
                    "id": fid,
                    "label": label,
                    "collection_id": allowed_files[fid],
                    "file_id": fid,
                }
            )

        for kid in knowledge_ids or []:
            if kid not in allowed_kbs:
                log.warning(
                    "[compare_documents] knowledge_id=%s not accessible; skipped", kid
                )
                continue
            if ("kb", kid) in seen_keys:
                continue
            seen_keys.add(("kb", kid))
            entities.append(
                {
                    "kind": "knowledge_base",
                    "id": kid,
                    "label": allowed_kbs.get(kid) or kid,
                    "collection_id": kid,
                    "file_id": None,
                }
            )

        if not entities:
            log.warning(
                "[compare_documents] no accessible compare targets "
                "(file_ids=%s, knowledge_ids=%s)",
                file_ids,
                knowledge_ids,
            )
            return {"sources": []}

        # 대상 수 상한 (비용/컨텍스트 보호)
        MAX_ENTITIES = 8
        if len(entities) > MAX_ENTITIES:
            log.info(
                "[compare_documents] %d targets exceeds cap %d; truncating",
                len(entities),
                MAX_ENTITIES,
            )
            entities = entities[:MAX_ENTITIES]

        user_id = self.metadata.get("user_id")
        chat_id = self.metadata.get("chat_id")

        search_engine = self._get_search_engine()
        if not search_engine:
            log.warning("Search engine not configured")
            return {"sources": []}

        # 대상별 고정 쿼터 (전역 top-k 대신) → 모든 대상이 근거를 가짐
        per_entity_k = max(self.reranker_top_k, 3)
        _RRF_C = 60

        def _entity_filter(entity: Dict[str, Any], use_filters: bool) -> str:
            """KB filter_schema 로 필터 결합(knowledge_handler 와 동일) + file_id 펜싱."""
            kb_id = entity["collection_id"]
            kb_schema = None
            if use_filters and filters:
                kb = Knowledges.get_knowledge_by_id(kb_id)
                kb_schema = kb.meta.get("filter_schema") if kb and kb.meta else None
            if kb_schema:
                base = build_knowledge_filter(
                    collection_ids=[kb_id],
                    filter_schema=kb_schema,
                    filter_values=filters,
                )
            else:
                base = f"collection eq '{kb_id.replace(chr(39), chr(39) * 2)}'"
            if entity.get("file_id"):
                safe_f = entity["file_id"].replace("'", "''")
                return f"({base}) and file_id eq '{safe_f}'"
            return base

        try:
            # 모든 aspect 질의 임베딩을 1회 생성하여 전 대상 검색에 재사용
            query_vectors = await asyncio.gather(
                *(
                    self._generate_query_embedding(
                        query=a, user_id=user_id, chat_id=chat_id
                    )
                    for a in aspect_list
                )
            )

            async def _search_one(aspect_text, qvec, filter_expr):
                sq = SearchQuery(
                    query=aspect_text,
                    filter=filter_expr,
                    top_k=per_entity_k,
                    top_k_vector=per_entity_k * 3,
                    reranker_threshold=self.reranker_threshold,
                )
                try:
                    return await search_engine.search(query=sq, query_vector=qvec)
                except Exception as e:
                    log.warning("[compare_documents] search failed: %s", e)
                    return []

            async def _search_entity(entity: Dict[str, Any]):
                filt = _entity_filter(entity, use_filters=True)
                result_lists = await asyncio.gather(
                    *(
                        _search_one(a, qv, filt)
                        for a, qv in zip(aspect_list, query_vectors)
                    )
                )
                # 대상별 필터 0건 폴백: user filter 로 한 건도 못 찾으면 그 대상만
                # 필터를 빼고 재검색 (필터값 불일치로 비교 대상이 통째 누락 방지).
                if filters and sum(len(r) for r in result_lists) == 0:
                    filt2 = _entity_filter(entity, use_filters=False)
                    if filt2 != filt:
                        result_lists = await asyncio.gather(
                            *(
                                _search_one(a, qv, filt2)
                                for a, qv in zip(aspect_list, query_vectors)
                            )
                        )
                # aspect 질의 간 RRF 융합 (질의별 점수 스케일 차이에 강건)
                rrf: Dict[str, float] = {}
                rep: Dict[str, Any] = {}
                for rl in result_lists:
                    for rank, r in enumerate(rl):
                        rrf[r.id] = rrf.get(r.id, 0.0) + 1.0 / (_RRF_C + rank + 1)
                        if r.id not in rep or r.score > rep[r.id].score:
                            rep[r.id] = r
                fused = sorted(rep.values(), key=lambda r: rrf[r.id], reverse=True)[
                    :per_entity_k
                ]
                return entity, fused

            per_entity_results = await asyncio.gather(
                *(_search_entity(e) for e in entities)
            )

            items: List[Dict[str, Any]] = []
            for entity, results in per_entity_results:
                for r in results:
                    meta = dict(r.metadata or {})
                    # 비교 대상 라벨 stamp — 최종 컨텍스트/인용에서 어떤 문서·
                    # 지식기반의 근거인지 구분 가능하게.
                    meta["compare_entity"] = entity["label"]
                    meta["compare_entity_kind"] = entity["kind"]
                    items.append(
                        {
                            "id": r.id,
                            "content": r.content.encode(
                                "utf-8", errors="surrogatepass"
                            ).decode("utf-8", errors="replace")
                            if r.content
                            else "",
                            "score": r.score,
                            "metadata": meta,
                        }
                    )

            log.info(
                "[compare_documents] aspects=%d entities=%d items=%d per_entity_k=%d",
                len(aspect_list),
                len(entities),
                len(items),
                per_entity_k,
            )

            return self._items_to_openwebui_sources(
                items,
                source_type="knowledge_base",
                source_scope="document_comparison",
                citation_policy="required",
                origin_tool="compare_documents",
            )
        finally:
            # 검색 엔진 리소스 정리 (knowledge_handler 와 동일 패턴)
            if self._search_engine:
                await self._search_engine.close()
                self._search_engine = None

    @staticmethod
    def _get_file_collections(files: List[Any]):
        collections = []
        for file in files:
            # Skip collection-type files (e.g. project knowledge) —
            # they are handled as knowledge bases, not file collections
            if file.get("type") == "collection":
                continue
            file_id = file.get("id")
            if file_id:
                collections.append("file-" + file_id)

        return collections

    async def get_file_contents(
        self, file_ids: Optional[Union[str, List[str]]] = None
    ) -> list[dict]:
        """
        파일 아이디 목록을 받아서 파일 컨텐츠 (id, filename, content) 목록을 반환 합니다.
        file_ids가 None이면 업로드된 모든 파일의 컨텐츠를 반환합니다.
        """
        if file_ids is None:
            # Return all uploaded (non-collection) files
            file_ids = [
                f.get("id")
                for f in self.files
                if f.get("type") != "collection" and f.get("id")
            ]
        elif isinstance(file_ids, str):
            file_ids = [file_ids]

        files = Files.get_files_by_ids(file_ids)
        files = [file.model_dump() for file in files]

        for file in files:
            if not file.get("meta", {}).get("file_id", None):
                file["meta"]["file_id"] = file.get("id")

        return self._items_to_openwebui_sources(
            files,
            source_type="chat_upload",
            source_scope="current_chat",
            citation_policy="optional",
            origin_tool="get_file_contents",
        )

    def _items_to_openwebui_sources(
        self,
        items: Any,
        *,
        source_type: str = "unknown",
        source_scope: str = "unknown",
        citation_policy: str = "required",
        origin_tool: str = "",
        collection_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Azure Search items 또는 OpenWebUI FileModel -> OpenWebUI sources 포맷으로 변환한다.

        provenance(source_type/source_scope/citation_policy/origin_tool/file_id/
        collection_id)를 각 source 의 metadata 에 stamp 한다. downstream(typed
        aggregation·citation 정책 분기·평가)이 chat upload 와 KB 를 구분하는 근거. (PR1)
        기본값은 legacy 동작 보존 — citation_policy='required'(인용 on).
        """
        # items가 {"items":[...]}일 수도, list일 수도 있다.
        if isinstance(items, dict) and isinstance(items.get("items"), list):
            items_list = items.get("items") or []
        elif isinstance(items, list):
            items_list = items
        else:
            items_list = []

        sources: List[Dict[str, Any]] = []
        for idx, it in enumerate(items_list, start=1):
            # dict가 아닌 객체(FileModel 등)인 경우 dict로 변환 시도
            if not isinstance(it, dict):
                try:
                    if hasattr(it, "model_dump"):
                        it = it.model_dump()
                    else:
                        it = dict(it)
                except Exception:
                    continue

            sid = it.get("id")
            # FileModel의 경우 content 필드가 없을 수 있으므로 data 또는 meta에서 찾거나 기본값 처리
            content = it.get("content") or it.get("data", {}).get("content") or ""

            meta_raw = it.get("metadata") or it.get("meta") or {}
            meta: Dict[str, Any] = {}

            if isinstance(meta_raw, str):
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    meta = {"raw": meta_raw}
            elif isinstance(meta_raw, dict):
                # copy — provenance stamp 가 SearchResult.metadata 등 호출자 원본
                # dict 를 in-place 변형하지 않도록 (aliasing guard).
                meta = dict(meta_raw)

            # 파일명 추출 (OpenWebUI FileModel은 주로 'meta' 내부에 'name'이 있음)
            name = (
                it.get("filename")
                or it.get("name")
                or meta.get("name")
                or meta.get("file_name")
                or meta.get("filename")
                or meta.get("title")
                or meta.get("source")
                or meta.get("url")
            )

            stable_source = (
                meta.get("source")
                or meta.get("url")
                or (f"file:{name}" if name else None)
                or f"file:doc_{idx}"
            )

            meta["source"] = stable_source
            if name and "name" not in meta:
                meta["name"] = name

            # --- provenance stamping (PR1) — metadata-only, transport shape 불변 ---
            meta["source_type"] = source_type
            meta["source_scope"] = source_scope
            meta["citation_policy"] = citation_policy
            if origin_tool:
                meta["origin_tool"] = origin_tool
            resolved_file_id = it.get("file_id") or meta.get("file_id") or sid
            if resolved_file_id:
                meta["file_id"] = resolved_file_id
            if collection_id:
                meta["collection_id"] = collection_id

            sources.append(
                {
                    "source": {
                        "id": sid if sid else stable_source,
                        "name": name or stable_source,
                    },
                    "document": [content if isinstance(content, str) else str(content)],
                    "metadata": [meta],
                    **(
                        {"distances": [it.get("score")]}
                        if it.get("score") is not None
                        else {}
                    ),
                }
            )

        return {"sources": sources}

    async def search_tavily(
        self,
        queries: Union[str, List[str]],
        max_results: int = 3,
    ) -> list[SearchResult]:
        api_key = self.tavily_api_key
        if not api_key:
            raise RuntimeError(
                "Tavily API Key가 없습니다. `TAVILY_API_KEY` 환경변수를 설정하세요."
            )

        url = "https://api.tavily.com/search"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        timeout = aiohttp.ClientTimeout(total=10)

        if isinstance(queries, str):
            query_list = [queries.strip()]
        else:
            query_list = [q.strip() for q in queries if q and q.strip()]

        async def _search_once(session, query: str):
            payload = {
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
            }
            async with session.post(url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

        all_results: list[SearchResult] = []

        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            for q_index, query in enumerate(query_list):
                last_err = None
                for attempt in range(3):
                    try:
                        json_response = await _search_once(session, query)
                        results = json_response.get("results", [])

                        for rank, result in enumerate(results):
                            all_results.append(
                                SearchResult(
                                    link=result.get("url") or result.get("link", ""),
                                    title=result.get("title", ""),
                                    snippet=result.get("content")
                                    or result.get("snippet"),
                                    score=result.get("score"),
                                )
                            )
                        break
                    except Exception as e:
                        last_err = e
                        await asyncio.sleep(min(1.5 * (attempt + 1), 5))
                else:
                    if last_err:
                        raise last_err

        def sort_key(r: SearchResult):
            return -(r.score or 0)

        return sorted(all_results, key=sort_key)

    async def search_web(self, query: str):
        """
        관리자 설정 검색 엔진으로 웹 검색 후 OpenWebUI sources 포맷으로 반환.
        에이전트 오버라이드(result_count, domain_filter)가 있으면 우선 적용.
        """
        from open_webui.routers.retrieval import search_web as retrieval_search_web

        if not self.request:
            raise RuntimeError("FastAPI request 객체가 없습니다.")

        config = self.request.app.state.config
        engine = config.WEB_SEARCH_ENGINE

        # 에이전트 오버라이드 (None이면 search_web이 관리자 기본값 사용)
        override_result_count = None
        override_domain_filter = None
        if self._web_search_config:
            override_result_count = self._web_search_config.result_count
            override_domain_filter = self._web_search_config.domain_filter_list

        log.info(
            f"[search_web] engine={engine}, query='{query}', "
            f"override_result_count={override_result_count}, "
            f"override_domain_filter={override_domain_filter}"
        )

        try:
            results = await asyncio.to_thread(
                retrieval_search_web,
                self.request,
                engine,
                query.strip(),
                result_count=override_result_count,
                domain_filter_list=override_domain_filter,
            )
        except Exception as e:
            log.warning(f"[search_web] Search failed for query '{query[:50]}': {e}")
            results = []

        sources: List[Dict[str, Any]] = []
        lines: List[str] = []

        for idx, r in enumerate(results, start=1):
            url = getattr(r, "link", None) or ""
            title = getattr(r, "title", None) or url
            snippet = getattr(r, "snippet", None) or ""

            meta = {
                "source": url,
                "name": title,
                "title": title,
                "link": url,
                "snippet": snippet,
            }
            sources.append(
                {
                    "source": {
                        "type": "url",
                        "id": url or f"web_{idx}",
                        "name": title,
                        "url": url,
                    },
                    "document": [snippet],
                    "metadata": [meta],
                }
            )
            lines.append(f"[{idx}] {title} - {url}\n{snippet}".strip())

        return {"sources": sources, "content": "\n\n".join(lines)}

    async def load_web_page(self, urls: Union[str, List[str]]):
        """
        URL에서 웹 페이지 전체 내용을 추출하여 sources 포맷으로 반환.
        """
        from open_webui.retrieval.web.utils import get_web_loader

        if not self.request:
            raise RuntimeError("FastAPI request 객체가 없습니다.")

        config = self.request.app.state.config
        url_list = [urls] if isinstance(urls, str) else urls

        try:
            loader = get_web_loader(
                url_list,
                verify_ssl=config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
                requests_per_second=config.WEB_SEARCH_CONCURRENT_REQUESTS,
                trust_env=config.WEB_SEARCH_TRUST_ENV,
            )
            # 브라우저 User-Agent 설정 (봇 차단 방지, WebBaseLoader 계열만)
            if hasattr(loader, "session"):
                loader.session.headers["User-Agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            # 비동기 aload() 사용 (aiohttp 기반, 더 안정적)
            docs = await loader.aload()
        except Exception as e:
            log.warning(f"[load_web_page] Failed to load URLs {url_list}: {e}")
            return {"sources": [], "content": f"Error loading web pages: {e}"}

        if not docs:
            log.warning(f"[load_web_page] No content extracted from URLs: {url_list}")

        sources: List[Dict[str, Any]] = []
        lines: List[str] = []

        for idx, doc in enumerate(docs, start=1):
            content = doc.page_content or ""
            doc_meta = doc.metadata or {}
            url = doc_meta.get("source") or (
                url_list[idx - 1] if idx <= len(url_list) else ""
            )
            title = doc_meta.get("title") or url

            meta = {
                "source": url,
                "name": title,
                "title": title,
                "link": url,
            }
            sources.append(
                {
                    "source": {
                        "type": "url",
                        "id": url or f"page_{idx}",
                        "name": title,
                        "url": url,
                    },
                    "document": [content],
                    "metadata": [meta],
                }
            )
            lines.append(f"[{idx}] {title} - {url}\n{content}".strip())

        return {"sources": sources, "content": "\n\n".join(lines)}

    def extract_context_info(
        self,
        language: str,
        normalized_question: str,
        runtime: ToolRuntime[None, AgentStateBase],
    ) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Successfully extract_context_info",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "language": language,
                "normalized_question": normalized_question,
            }
        )

    def evaluation_result(
        self,
        eval_score: int,
        eval_reason: str,
        runtime: ToolRuntime[None, AgentStateBase],
    ) -> Command:
        answerable = eval_score > 3
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Successfully evaluation_result"
                        if answerable
                        else "도구 사용에도 정확한 답변을 얻을 수 없습니다. 다른 도구를 사용하세요.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "answerable": answerable,
                "eval_score": eval_score,
                "eval_reason": eval_reason,
            }
        )
