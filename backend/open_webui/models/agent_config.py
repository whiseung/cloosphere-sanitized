"""
AgentConfig - Unified agent configuration model.

This module provides a Pydantic model that consolidates all agent-related
settings from model.params and model.meta into a single structured object.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class KnowledgeBaseRef(BaseModel):
    """Knowledge base reference."""

    id: str
    name: Optional[str] = None
    collection_names: Optional[List[str]] = None
    description: Optional[str] = None


class DbSphereRef(BaseModel):
    """Database connection reference."""

    id: str
    name: Optional[str] = None


class GlossaryRef(BaseModel):
    """Glossary reference."""

    id: str
    name: Optional[str] = None


class KnowledgeGraphRef(BaseModel):
    """Knowledge Graph reference."""

    id: str
    name: Optional[str] = None


class ToolConnectionRef(BaseModel):
    """MCP/OpenAPI tool connection reference."""

    id: str
    name: Optional[str] = None
    connection: Optional[Dict[str, Any]] = None


class AutoEvaluationConfig(BaseModel):
    """Auto evaluation settings."""

    enabled: bool = False
    sampling_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    evaluation_types: List[str] = Field(default_factory=list)
    judge_model_id: Optional[str] = None


class ResponseFormatConfig(BaseModel):
    """Response format settings."""

    type: str = "text"  # "text" | "json_schema"
    json_schema: Optional[Dict[str, Any]] = None


class WebSearchConfig(BaseModel):
    """Agent-level web search overrides (inherits admin defaults)."""

    result_count: Optional[int] = None  # None = 관리자 기본값 사용
    domain_filter_list: Optional[List[str]] = None  # None = 관리자 기본값 사용


class ImageGenerationConfig(BaseModel):
    """Image generation connection reference (supports multiple connections)."""

    connection_ids: List[int] = Field(default_factory=list)
    names: List[str] = Field(default_factory=list)

    # Legacy single connection support
    connection_idx: Optional[int] = None
    name: Optional[str] = None


class CapabilitiesConfig(BaseModel):
    """Model capability flags.

    Values: "off" (disabled), "on" (default enabled), "user" (visible, default disabled).
    Legacy boolean values are normalized: True → "on", False → "off".
    """

    web_search: str = "off"
    image_generation: str = "off"
    # ask_user — 정보 부족/의도 모호 시 에이전트가 사용자에게 되묻는 도구의
    # 활성화 여부. **디폴트 off (opt-in)** — 모달이 흐름을 끊으므로 운영자가
    # 명시적으로 켰을 때만 LLM 에 노출. 위험 도구 승인 게이트(write SQL /
    # write tool server)는 별개로 항상 작동 — capabilities 토글 대상이 아니다.
    ask_user: str = "off"
    # document_tools — LLM 이 PPT/Word/Excel 파일을 직접 생성하는 툴
    # (create_pptx / create_docx / create_xlsx) 의 활성화 여부.
    # **디폴트 on** — 일반 채팅에서도 자주 쓰이는 산출 기능이라 opt-out.
    document_tools: str = "on"
    # gmail / calendar — Google Workspace 채팅 통합 도구 (gmail_send/search/get,
    # calendar_create_event/list_events/find_free_slots) 의 활성화 여부.
    # **디폴트 off (opt-in)** — 외부 API + 사용자 명의 발송이라 명시적 활성화 필요.
    # 실제 LLM 노출은 5축 게이트 (admin enable + group features.* + capability +
    # per-conversation toggle + OAuth token) 모두 통과 시.
    gmail: str = "off"
    calendar: str = "off"
    # drive — Google Drive 채팅 통합 도구 (drive_search/get_content/create_doc) 의
    # 활성화 여부. **디폴트 off (opt-in)** — gmail/calendar 와 동일 정책.
    drive: str = "off"
    # show_reasoning — 에이전트의 추론 과정 노출 **수준**. off/on/user 의 3-state
    # capability 와 달리 노출 정도를 고르는 토글이라 별도 값 도메인을 쓴다:
    #   "brief"    — 간략(기본): 기존 단순 상태표시(툴 이름) — 모든 에이전트 디폴트
    #   "detailed" — 상세: ChatGPT/Gemini 식 라이브 "추론 과정" 윈도우(자연어 narration)
    #   "off"      — 없음: 아무것도 표시 안 함
    # **디폴트 brief** — 기존 동작이라 안전. detailed 만 인자 미리보기를 노출하므로
    # SQL/PII 민감 에이전트는 brief/off 로 둘 수 있다.
    show_reasoning: str = "brief"
    # grounding — 엄격 근거 준수(grounding) 모드. 의미상 binary(on/off)이며,
    # **미설정(None)** 은 컨텍스트 기본으로 해석한다 — 에이전트(base_model_id 있음)
    # = on, 기본 모델 = off (AgentConfig.is_grounding_enabled() 가 판정).
    #   "on"  : 답변을 연결된 데이터(KB/DB/도구 등 이번 턴 수집 컨텍스트)에만
    #           근거하고, 자료가 없으면 "자료 없음"을 명시한다(환각 방지) — 기존 동작.
    #   "off" : 연결된 소스를 우선하되 부족하면 일반 지식으로 보완(거부하지 않음).
    #           사용자의 PRIVATE 데이터(문서 본문/DB 값/메일·일정·파일 내용)는
    #           여전히 날조 금지. web_search 가 켜진 에이전트는 이미 보완 모드라 무관.
    # "user" 3-state 는 사용하지 않는다.
    grounding: Optional[str] = None
    image_generation_config: Optional[ImageGenerationConfig] = None
    web_search_config: Optional[Dict[str, Any]] = None

    @field_validator(
        "web_search",
        "image_generation",
        "ask_user",
        "document_tools",
        "gmail",
        "calendar",
        "drive",
        mode="before",
    )
    @classmethod
    def normalize_capability(cls, v: Union[bool, str, None]) -> str:
        if v is True:
            return "on"
        if v is False:
            return "off"
        if v is None:
            return "off"
        if isinstance(v, str) and v in ("off", "on", "user"):
            return v
        return "off"

    @field_validator("grounding", mode="before")
    @classmethod
    def normalize_grounding(cls, v: Union[bool, str, None]) -> Optional[str]:
        """binary(on/off) + 미설정(None). 명시값만 보존하고, 미설정/미인식은
        None 으로 둬서 is_grounding_enabled() 가 컨텍스트 기본을 적용하게 한다."""
        if v is True:
            return "on"
        if v is False:
            return "off"
        if isinstance(v, str) and v in ("on", "off"):
            return v
        return None

    @field_validator("show_reasoning", mode="before")
    @classmethod
    def normalize_show_reasoning(cls, v: Union[bool, str, None]) -> str:
        """off | brief | detailed 로 정규화. legacy "on"/True → "detailed",
        명시적 False → "off", 그 외(미설정/미인식) → "brief"(기본)."""
        if v is True or v == "on":
            return "detailed"
        if v is False or v == "none":
            return "off"
        if isinstance(v, str) and v in ("off", "brief", "detailed"):
            return v
        return "brief"

    def is_enabled(self, cap: str) -> bool:
        """Check if a capability is not 'off' (i.e. 'on' or 'user')."""
        val = getattr(self, cap, "off")
        return val in ("on", "user")


class AgentConfig(BaseModel):
    """
    Unified agent configuration.

    Consolidates all agent-related settings from model.params and model.meta
    into a single structured object for consistent access across agents.

    Usage:
        # In main.py - create from model_info
        agent_config = AgentConfig.from_model_info(
            params=model_info.params.model_dump(),
            meta=model_info.meta.model_dump(),
            model_id=model_info.id,
            base_model_id=model_info.base_model_id,
        )
        # KG가 attach된 경우 KG.sources를 explicit 리소스에 union
        agent_config.resolve_kg_inheritance()
        metadata["agent_config"] = agent_config

        # In agents - access via property
        dbsphere_id = self.agent_config.get_first_dbsphere_id()
        knowledge_ids = self.agent_config.get_knowledge_ids()
    """

    # Capability flags (from model.params)
    enable_kbsphere: bool = False
    enable_dbsphere: bool = False

    # System prompts (from model.params)
    system_prompt: Optional[str] = None
    format_prompt: Optional[str] = None
    # format_prompt 적용 범위 (params JSON 파생, DB 마이그레이션 없음).
    # "always" | "exclude_chat_uploads". 현재 턴 chat upload 시 영구 format_prompt
    # 를 적용할지 결정. fail-safe 기본(None/미인식) = exclude_chat_uploads —
    # ad-hoc 업로드 질의에 영구 포맷이 새지 않게 한다. UI(FE)는 미노출 — params/raw
    # API 로만 "always" override (B1: 리포맷 전용 에이전트용 escape hatch).
    format_prompt_scope: Optional[str] = None

    # Resource references (from model.meta)
    knowledge_bases: List[KnowledgeBaseRef] = Field(default_factory=list)
    dbspheres: List[DbSphereRef] = Field(default_factory=list)
    glossaries: List[GlossaryRef] = Field(default_factory=list)
    knowledge_graphs: List[KnowledgeGraphRef] = Field(default_factory=list)
    guardrail_ids: List[str] = Field(default_factory=list)
    tool_connections: List[ToolConnectionRef] = Field(default_factory=list)

    # KG → resource 자동 머지로 주입된 ID 추적 (provenance용)
    # key: KG id, value: {"knowledge_ids": [...], "dbsphere_ids": [...], "glossary_ids": [...]}
    inherited_from_kg: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)

    # Behavior settings (from model.meta)
    auto_evaluation: Optional[AutoEvaluationConfig] = None
    response_format: Optional[ResponseFormatConfig] = None
    capabilities: Optional[CapabilitiesConfig] = None
    web_search_config: Optional[WebSearchConfig] = None

    # Model identification
    model_id: Optional[str] = None
    base_model_id: Optional[str] = None

    @classmethod
    def from_model_info(
        cls,
        params: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        base_model_id: Optional[str] = None,
    ) -> "AgentConfig":
        """
        Create AgentConfig from model params and meta.

        Args:
            params: Model params dict (from model_info.params.model_dump())
            meta: Model meta dict (from model_info.meta.model_dump())
            model_id: Model ID
            base_model_id: Base model ID (set if this is an agent)

        Returns:
            AgentConfig instance
        """
        params = params or {}
        meta = meta or {}

        # Parse capability flags from params
        enable_kbsphere = params.get("enable_kbsphere", False)
        enable_dbsphere = params.get("enable_dbsphere", False)

        # Parse system prompts from params
        system_prompt = params.get("system") or params.get("system_prompt")
        format_prompt = params.get("format_prompt")
        format_prompt_scope = params.get("format_prompt_scope")

        # Parse knowledge bases from meta
        knowledge_bases: List[KnowledgeBaseRef] = []
        raw_knowledge = meta.get("knowledge", [])
        if isinstance(raw_knowledge, list):
            for kb in raw_knowledge:
                if isinstance(kb, dict):
                    knowledge_bases.append(
                        KnowledgeBaseRef(
                            id=kb.get("id", ""),
                            name=kb.get("name"),
                            collection_names=kb.get("collection_names"),
                            description=kb.get("description"),
                        )
                    )
                elif isinstance(kb, str):
                    knowledge_bases.append(KnowledgeBaseRef(id=kb))

        # Parse dbspheres from meta (support both singular and plural)
        dbspheres: List[DbSphereRef] = []
        raw_dbspheres = meta.get("dbspheres", []) or meta.get("dbsphere", [])
        if isinstance(raw_dbspheres, list):
            for db in raw_dbspheres:
                if isinstance(db, dict):
                    dbspheres.append(
                        DbSphereRef(
                            id=db.get("id", ""),
                            name=db.get("name"),
                        )
                    )
                elif isinstance(db, str):
                    dbspheres.append(DbSphereRef(id=db))

        # Parse glossaries from meta
        glossaries: List[GlossaryRef] = []
        raw_glossaries = meta.get("glossaries", []) or meta.get("glossary", [])
        if isinstance(raw_glossaries, list):
            for g in raw_glossaries:
                if isinstance(g, dict):
                    glossaries.append(
                        GlossaryRef(
                            id=g.get("id", ""),
                            name=g.get("name"),
                        )
                    )
                elif isinstance(g, str):
                    glossaries.append(GlossaryRef(id=g))

        # Parse knowledge graphs from meta
        knowledge_graphs: List[KnowledgeGraphRef] = []
        raw_kgs = (
            meta.get("knowledge_graphs", [])
            or meta.get("knowledgeGraphs", [])
            or meta.get("knowledge_graph", [])
        )
        if isinstance(raw_kgs, list):
            for g in raw_kgs:
                if isinstance(g, dict):
                    knowledge_graphs.append(
                        KnowledgeGraphRef(
                            id=g.get("id", ""),
                            name=g.get("name"),
                        )
                    )
                elif isinstance(g, str):
                    knowledge_graphs.append(KnowledgeGraphRef(id=g))

        # Parse guardrail IDs from meta
        guardrail_ids: List[str] = []
        raw_guardrails = meta.get("guardrails", [])
        if isinstance(raw_guardrails, list):
            for g in raw_guardrails:
                if isinstance(g, dict):
                    gid = g.get("id")
                    if gid:
                        guardrail_ids.append(gid)
                elif isinstance(g, str):
                    guardrail_ids.append(g)

        # Parse tool connections from meta
        tool_connections: List[ToolConnectionRef] = []
        raw_tools = meta.get("toolConnections", []) or meta.get("tool_connections", [])
        if isinstance(raw_tools, list):
            for t in raw_tools:
                if isinstance(t, dict):
                    tool_connections.append(
                        ToolConnectionRef(
                            id=t.get("id", ""),
                            name=t.get("name"),
                            connection=t.get("connection"),
                        )
                    )
                elif isinstance(t, str):
                    tool_connections.append(ToolConnectionRef(id=t))

        # 마켓플레이스 도구(meta.marketplaceTools)를 tool_connections 로 병합한다.
        # UX 만 마켓플레이스 섹션으로 분리돼 있고, 런타임 처리는 일반 tool_connection 과
        # 완전히 동일하다 (ToolConnectionManager → use_tool_server_* → 2단계 컨텍스트 승격).
        raw_mp = meta.get("marketplaceTools", []) or meta.get("marketplace_tools", [])
        if isinstance(raw_mp, list):
            existing_ids = {tc.id for tc in tool_connections}
            for t in raw_mp:
                tc_id = (
                    t.get("id")
                    if isinstance(t, dict)
                    else (t if isinstance(t, str) else None)
                )
                if tc_id and tc_id not in existing_ids:
                    tool_connections.append(
                        ToolConnectionRef(
                            id=tc_id,
                            name=t.get("name") if isinstance(t, dict) else None,
                        )
                    )
                    existing_ids.add(tc_id)

        # Parse auto evaluation from meta
        auto_evaluation: Optional[AutoEvaluationConfig] = None
        raw_eval = meta.get("autoEvaluation") or meta.get("auto_evaluation")
        if isinstance(raw_eval, dict):
            auto_evaluation = AutoEvaluationConfig(
                enabled=raw_eval.get("enabled", False),
                sampling_rate=raw_eval.get(
                    "samplingRate", raw_eval.get("sampling_rate", 0.1)
                ),
                evaluation_types=raw_eval.get(
                    "evaluationTypes", raw_eval.get("evaluation_types", [])
                ),
                judge_model_id=raw_eval.get(
                    "judgeModelId", raw_eval.get("judge_model_id")
                ),
            )

        # Parse response format from meta
        response_format: Optional[ResponseFormatConfig] = None
        raw_format = meta.get("responseFormat") or meta.get("response_format")
        if isinstance(raw_format, dict):
            response_format = ResponseFormatConfig(
                type=raw_format.get("type", "text"),
                json_schema=raw_format.get("json_schema"),
            )

        # Parse capabilities from meta
        capabilities: Optional[CapabilitiesConfig] = None
        raw_caps = meta.get("capabilities")
        if isinstance(raw_caps, dict):
            # Parse image_generation_config
            img_gen_config = None
            raw_img_config = raw_caps.get("image_generation_config")
            if isinstance(raw_img_config, dict):
                # Support both new multi-select and legacy single-select
                connection_ids = raw_img_config.get("connection_ids", [])
                names = raw_img_config.get("names", [])
                # Legacy fallback
                connection_idx = raw_img_config.get("connection_idx")
                name = raw_img_config.get("name")
                if not connection_ids and connection_idx is not None:
                    connection_ids = [connection_idx]
                    names = [name] if name else []
                img_gen_config = ImageGenerationConfig(
                    connection_ids=connection_ids,
                    names=names,
                    connection_idx=connection_idx,
                    name=name,
                )

            # ask_user: 키가 없으면 "off" (opt-in). 구 키 `human_in_the_loop`
            # (이전 PR 임시 이름) 도 fallback — 명시적으로 저장돼 있으면 존중.
            ask_user_val = raw_caps.get("ask_user")
            if ask_user_val is None:
                ask_user_val = raw_caps.get("human_in_the_loop", "off")
            capabilities = CapabilitiesConfig(
                web_search=raw_caps.get("web_search", False),
                image_generation=raw_caps.get("image_generation", False),
                ask_user=ask_user_val,
                document_tools=raw_caps.get("document_tools", "on"),
                # gmail / calendar / drive — legacy 에이전트(키 없음)는 False → "off"
                # 로 정규화. 신규 도구라 opt-in 정책.
                gmail=raw_caps.get("gmail", False),
                calendar=raw_caps.get("calendar", False),
                drive=raw_caps.get("drive", False),
                # show_reasoning — 노출 수준(brief/detailed/off). 키 없으면 brief(기본).
                show_reasoning=raw_caps.get("show_reasoning", "brief"),
                # grounding — 키 없으면 None(미설정). 컨텍스트 기본(에이전트 on /
                # 기본 모델 off)은 is_grounding_enabled() 가 is_agent() 로 해석.
                grounding=raw_caps.get("grounding"),
                image_generation_config=img_gen_config,
            )
        else:
            # capabilities 키 자체가 없는 (legacy) 에이전트 — ask_user 디폴트 off.
            capabilities = CapabilitiesConfig(ask_user="off")

        # Parse web search config from meta
        web_search_config: Optional[WebSearchConfig] = None
        raw_ws = (
            raw_caps.get("web_search_config") if isinstance(raw_caps, dict) else None
        )
        if isinstance(raw_ws, dict):
            result_count = raw_ws.get("result_count")
            domain_filter_list = raw_ws.get("domain_filter_list")
            web_search_config = WebSearchConfig(
                result_count=int(result_count) if result_count is not None else None,
                domain_filter_list=domain_filter_list,
            )

        return cls(
            enable_kbsphere=enable_kbsphere,
            enable_dbsphere=enable_dbsphere,
            system_prompt=system_prompt,
            format_prompt=format_prompt,
            format_prompt_scope=format_prompt_scope,
            knowledge_bases=knowledge_bases,
            dbspheres=dbspheres,
            glossaries=glossaries,
            knowledge_graphs=knowledge_graphs,
            guardrail_ids=guardrail_ids,
            tool_connections=tool_connections,
            auto_evaluation=auto_evaluation,
            response_format=response_format,
            capabilities=capabilities,
            web_search_config=web_search_config,
            model_id=model_id,
            base_model_id=base_model_id,
        )

    def resolve_kg_inheritance(self, user: Any = None) -> None:
        """KG에 연결된 KB/DB/Glossary 를 provenance 용도로만 기록한다.

        에이전트에 KG 를 attach 한 경우, KG 내부의 KB/DB/Glossary 는 **KG 도구
        (KGToolManager) 가 KGService 를 통해 직접 접근** 한다. 이들을 에이전트
        최상위 리소스 리스트에 union 하면 KbSphere/DbSphere/Glossary 도구가
        KG 와 병렬로 활성화돼 스코프 밖 검색을 수행 → 결과 오염.

        따라서 여기서는 `inherited_from_kg[kg_id]` 에 provenance 만 기록하고
        `knowledge_bases` / `dbspheres` / `glossaries` 배열은 건드리지 않는다.

        호출 시점: AgentConfig 생성 직후, metadata 에 주입하기 전.
        """
        if not self.knowledge_graphs:
            return

        try:
            from open_webui.models.knowledge_graph import KnowledgeGraphs
        except Exception:
            return

        for kg_ref in self.knowledge_graphs:
            if not kg_ref.id:
                continue
            try:
                kg = KnowledgeGraphs.get_kg_by_id(id=kg_ref.id)
            except Exception:
                continue
            if not kg:
                continue

            kg_data = kg.data or {}

            kg_g_ids = list(kg_data.get("glossary_ids") or [])
            if not kg_g_ids:
                kg_g_ids = list(
                    (kg_data.get("sources") or {}).get("glossary_ids") or []
                )

            kg_db_ids: List[str] = []
            kg_kb_ids: List[str] = []
            _seen_db: set = set()
            _seen_kb: set = set()
            for _link in KnowledgeGraphs.get_knowledge_links(kg_ref.id):
                _db = _link.dbsphere_id
                if _db and _db not in _seen_db:
                    kg_db_ids.append(_db)
                    _seen_db.add(_db)
                for _kb in _link.knowledge_ids or []:
                    if _kb and _kb not in _seen_kb:
                        kg_kb_ids.append(_kb)
                        _seen_kb.add(_kb)

            if not kg_db_ids:
                kg_db_ids = list(
                    (kg_data.get("sources") or {}).get("dbsphere_ids") or []
                )
            if not kg_kb_ids:
                kg_kb_ids = list(
                    (kg_data.get("sources") or {}).get("knowledge_ids") or []
                )

            if kg_kb_ids or kg_db_ids or kg_g_ids:
                self.inherited_from_kg[kg_ref.id] = {
                    "knowledge_ids": kg_kb_ids,
                    "dbsphere_ids": kg_db_ids,
                    "glossary_ids": kg_g_ids,
                }

    def get_first_dbsphere_id(self) -> Optional[str]:
        """Return the first dbsphere ID (common usage pattern)."""
        return self.dbspheres[0].id if self.dbspheres else None

    def get_dbsphere_ids(self) -> List[str]:
        """Return list of all connected dbsphere IDs (multi-DB selection)."""
        return [db.id for db in self.dbspheres if db.id]

    def get_knowledge_ids(self) -> List[str]:
        """Return list of knowledge base IDs."""
        return [kb.id for kb in self.knowledge_bases if kb.id]

    def get_knowledge_list(self) -> List[Dict[str, Any]]:
        """Return knowledge bases as list of dicts (for backward compatibility)."""
        return [kb.model_dump() for kb in self.knowledge_bases]

    def get_glossary_ids(self) -> List[str]:
        """Return list of glossary IDs."""
        return [g.id for g in self.glossaries if g.id]

    def has_knowledge(self) -> bool:
        """Check if any knowledge bases are configured."""
        return len(self.knowledge_bases) > 0

    def has_dbsphere(self) -> bool:
        """Check if any dbspheres are configured."""
        return len(self.dbspheres) > 0

    def has_glossary(self) -> bool:
        """Check if any glossaries are configured."""
        return len(self.glossaries) > 0

    def get_knowledge_graph_ids(self) -> List[str]:
        """Return list of knowledge graph IDs."""
        return [kg.id for kg in self.knowledge_graphs if kg.id]

    def has_knowledge_graph(self) -> bool:
        """Check if any knowledge graphs are configured."""
        return len(self.knowledge_graphs) > 0

    def has_web_search(self) -> bool:
        """Check if web search is enabled via capabilities (on or user)."""
        return self.capabilities is not None and self.capabilities.is_enabled(
            "web_search"
        )

    def has_image_generation(self) -> bool:
        """Check if image generation is enabled via capabilities (on or user)."""
        return self.capabilities is not None and self.capabilities.is_enabled(
            "image_generation"
        )

    def is_ask_user_enabled(self) -> bool:
        """ask_user 도구 등록 여부 — 정보 부족 시 LLM 이 사용자에게 되묻기 활성화.

        위험 도구 승인 게이트(write SQL / tool server write 등) 와는 무관 — 그
        게이트는 항상 작동하며 별도 토글이 없다. 이 함수는 ask_user 도구 자체의
        노출만 제어한다. **디폴트 off (opt-in)** — capabilities 가 없거나
        명시적으로 "off" 일 때 비활성.
        """
        if self.capabilities is None:
            return False
        return self.capabilities.is_enabled("ask_user")

    def has_document_tools(self) -> bool:
        """Check if document generation tools are enabled (default on)."""
        # capabilities 미설정 시 디폴트 on (필드 디폴트와 일치)
        if self.capabilities is None:
            return True
        return self.capabilities.is_enabled("document_tools")

    def is_grounding_enabled(self) -> bool:
        """엄격 grounding(근거 준수) 모드 여부.

        - on  : 답변을 연결된 데이터(KB/DB/도구 등 수집 컨텍스트)에만 근거하고,
                자료가 없으면 "자료 없음"을 명시한다(환각 방지) — 기존 동작.
        - off : 연결된 소스를 우선하되 부족하면 일반 지식으로 보완(거부 안 함).
                PRIVATE 데이터(문서 본문/DB 값/메일·일정·파일 내용) 날조는 여전히 금지.

        **미설정(None) 시 컨텍스트 기본**: 에이전트(base_model_id 있음) = on,
        기본 모델 = off. 에이전트는 연결 리소스에 근거하는 게 자연스럽고, 기본 모델
        (plain LLM)은 근거할 소스가 없어 strict grounding 이 일반 질의를 거부하게
        만들기 때문. 명시적으로 저장된 on/off 는 그대로 존중한다.
        """
        explicit = self.capabilities.grounding if self.capabilities else None
        if explicit is None:
            return self.is_agent()
        return explicit != "off"

    def get_show_reasoning_level(self) -> str:
        """추론 과정 노출 수준: 'brief' | 'detailed' | 'off'. **디폴트 'brief'**.

        - brief(기본): 기존 단순 상태표시(툴 이름). 모든 에이전트 디폴트.
        - detailed: 라이브 "추론 과정" 윈도우(자연어 narration + 결과 미리보기)
        - off: 미표시

        capabilities 미설정(legacy)도 'brief' — 기존 동작과 동일해 안전.
        """
        if self.capabilities is None:
            return "brief"
        level = getattr(self.capabilities, "show_reasoning", "brief")
        return level if level in ("off", "brief", "detailed") else "brief"

    def has_gmail(self) -> bool:
        """Check if Gmail integration is enabled via capabilities (on or user).

        디폴트 off (opt-in) — legacy 에이전트(`capabilities is None`) 는
        자동으로 비활성. 외부 API + 사용자 명의 발송이라 명시적 활성화 필요.
        """
        return self.capabilities is not None and self.capabilities.is_enabled("gmail")

    def has_calendar(self) -> bool:
        """Check if Google Calendar integration is enabled via capabilities (on or user).

        디폴트 off (opt-in) — has_gmail() 와 동일 정책.
        """
        return self.capabilities is not None and self.capabilities.is_enabled(
            "calendar"
        )

    def has_drive(self) -> bool:
        """Check if Google Drive integration is enabled via capabilities (on or user).

        디폴트 off (opt-in) — has_gmail() / has_calendar() 와 동일 정책.
        """
        return self.capabilities is not None and self.capabilities.is_enabled("drive")

    def get_image_connection_ids(self) -> List[int]:
        """Return the image generation connection indices if configured."""
        if self.capabilities and self.capabilities.image_generation_config:
            cfg = self.capabilities.image_generation_config
            if cfg.connection_ids:
                return cfg.connection_ids
            # Legacy fallback
            if cfg.connection_idx is not None:
                return [cfg.connection_idx]
        return []

    def get_image_connection_idx(self) -> Optional[int]:
        """Return the first image generation connection index (legacy compat)."""
        ids = self.get_image_connection_ids()
        return ids[0] if ids else None

    def has_tool_connections(self) -> bool:
        """Check if any tool connections are configured."""
        return len(self.tool_connections) > 0

    def get_tool_connection_ids(self) -> List[str]:
        """Return list of tool connection IDs."""
        return [tc.id for tc in self.tool_connections if tc.id]

    def has_guardrails(self) -> bool:
        """Check if any guardrails are configured."""
        return len(self.guardrail_ids) > 0

    def is_agent(self) -> bool:
        """Check if this model is an agent (has base_model_id)."""
        return self.base_model_id is not None

    def effective_format_prompt(self, has_chat_upload: bool) -> str:
        """현재 턴 chat upload 여부 + format_prompt_scope 로 적용할 format_prompt 결정.

        영구 format_prompt 가 대화 중간에 올린 ad-hoc 업로드 파일 질의(요약/재구성)
        에까지 강제 적용되는 것을 차단한다. fail-safe: scope 가 None/미인식이면
        exclude_chat_uploads 로 취급 — 업로드 턴엔 format 미적용. scope="always"
        일 때만 업로드 턴에도 적용(리포맷 전용 에이전트 escape hatch).

        Args:
            has_chat_upload: 현재 턴에 chat-upload 파일 본문이 있으면 True.

        Returns:
            적용할 format_prompt (제외 시 빈 문자열). 비어있으면 항상 "".
        """
        fp = (self.format_prompt or "").strip()
        if not fp:
            return ""
        if has_chat_upload and self.format_prompt_scope != "always":
            return ""
        return fp
