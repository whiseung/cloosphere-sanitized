"""
UnifiedAgent - Combined DbSphere + KbSphere agent.

This agent provides both SQL query generation (DbSphere) and knowledge base
search (KbSphere) capabilities in a single agent. It extends ReactToolsBase
to inherit KbSphere functionality and conditionally adds DbSphere components.
"""

import ast
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from extension_modules.agent import prefetch
from extension_modules.agent.hitl_confirmation import (
    extract_hitl_confirmation_content,
    hitl_ack_message,
    is_hitl_confirmation,
)
from extension_modules.agent.prompts import (
    get_unified_final_answer_prompt,
    get_unified_system_prompt,
    resolve_citation_mode,
    split_source_contexts,
)
from extension_modules.agent.unified_state import (
    UnifiedAgentOutput,
    UnifiedAgentState,
)
from extension_modules.dbsphere.chart.plotly_generator import PlotlyChartGenerator
from extension_modules.dbsphere.dbsphere_state import (
    DBConfig,
)
from extension_modules.dbsphere.memory.search_memory import (
    SearchEngineDbSphereMemory,
)
from extension_modules.dbsphere.sql_runners.base import SqlRunnerBase
from extension_modules.dbsphere.tools.dbsphere_info import create_dbsphere_info_tool
from extension_modules.dbsphere.tools.get_table_details import (
    create_get_table_details_tool,
)
from extension_modules.dbsphere.tools.run_sql import (
    create_run_sql_read_tool,
    create_run_sql_write_tool,
)
from extension_modules.dbsphere.tools.visualize_data import (
    create_visualize_data_tool,
)
from extension_modules.glossary.tools import GlossaryTools
from extension_modules.guardrail.middleware import (
    GuardrailBlockedError,
    RuleBasedPIIMiddleware,
    create_guardrail_middlewares,
)
from extension_modules.react.react_middleware_base import MiddlewareBase
from extension_modules.react.tools_base import ReactToolsBase
from fastapi import Request
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, dynamic_prompt
from langchain.agents.middleware.pii import PIIDetectionError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from open_webui.models.dbsphere import DbSpheres
from open_webui.models.glossary import Glossaries
from open_webui.models.message_trace import RunType
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.models.users import Users
from open_webui.routers.dbsphere import decrypt_connection_password
from open_webui.socket.main import get_event_call, get_event_emitter
from open_webui.utils.misc import openai_chat_chunk_message_template
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


def _nan_safe(obj):
    """NaN/Inf → None 재귀 치환. NaN/Inf 는 유효한 JSON 이 아니라 차트 청크에 섞이면
    프론트 JSON.parse 실패 + 후속 직렬화 단계 예외로 스트림이 [DONE] 전에 끊긴다."""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_safe(v) for v in obj]
    return obj


# build_sql_results_context 크기 가드 — 에이전트가 쿼리를 여러 번 돌리거나 SQL 본문이
# 아주 길어도 final_answer 컨텍스트가 무한정 커지지 않게 한다.
# (각 결과 preview 는 이미 run_sql.py 에서 1500자로 캡됨 → 'rows 수천 개'는 비용 문제 아님.)
_SQL_CTX_MAX_QUERIES = 12  # 포함할 성공 쿼리 수 (오래된 것부터 버림)
_SQL_CTX_MAX_SQL_CHARS = 2000  # 쿼리별 SQL 본문 길이 캡
# 쿼리별 결과 content 안전 캡 (run_sql 1500 캡의 이중 안전망)
_SQL_CTX_MAX_RESULT_CHARS = 2000


def build_sql_results_context(
    messages: list, *, max_queries: int | None = _SQL_CTX_MAX_QUERIES
) -> str:
    """run_sql 가 실행한 성공 쿼리들을 {SQL 본문 + 결과} 로 묶어 final_answer 컨텍스트를 만든다.

    기존 구현은 '마지막 성공 ToolMessage 결과 preview' 만 넘겨서, final_answer 가 어떤
    WHERE/GROUP BY 로 데이터가 뽑혔는지 알 수 없었다 (지역/grain 오해의 직접 원인).
    여기서는 AIMessage.tool_calls 의 SQL 인자를 tool_call_id 로 ToolMessage 결과와
    페어링해, 실행 순서대로 성공 쿼리들의 {SQL 본문 + (best-effort intent) + 결과}
    를 함께 넘긴다. 실패(Error...) 쿼리는 본문에서 제외하고 건수만 노트로 남긴다.

    크기 가드: 결과 preview 는 run_sql 단계에서 이미 1500자로 캡되고(rows 수와 무관),
    여기서 추가로 쿼리 수(max_queries)·SQL 본문 길이·결과 길이를 캡한다. 따라서 최악의
    경우(수천 rows × 수십 회 실행)에도 컨텍스트 크기는 대략 max_queries × ~4KB 로 유계다.

    Args:
        messages: agent_result["messages"] (LangChain 메시지 리스트). 비-메시지 / 비-문자열
            content 는 안전하게 skip 한다 (절대 raise 하지 않음).
        max_queries: 포함할 성공 쿼리 수 상한 (최근 우선). None=전부. 기본 12.

    Returns:
        섹션 본문 문자열. 성공 쿼리가 0건이면 "" (호출부가 ## SQL Query Results 섹션 자체를 생략).
    """
    # 1) tool_call_id -> {sql, dbsphere_id, intent} 맵 (run_sql_read/write 호출만)
    sql_by_call_id: dict[str, dict] = {}
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        # run_sql 직전 AIMessage 의 평문 content 가 있으면 best-effort intent 로 사용.
        # (tool-calling 턴은 보통 content 가 비어 있어 대개 생략된다.)
        intent = (
            msg.content.strip()
            if isinstance(msg.content, str) and msg.content.strip()
            else ""
        )
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                name = tc.get("name")
                tc_id = tc.get("id")
                args = tc.get("args")
            except AttributeError:
                continue  # malformed tool_call (dict 아님) — skip, raise 안 함
            if name not in ("run_sql_read", "run_sql_write") or not tc_id:
                continue
            sql = args.get("sql") if isinstance(args, dict) else None
            dbsphere_id = args.get("dbsphere_id") if isinstance(args, dict) else None
            sql_by_call_id[tc_id] = {
                "sql": sql if isinstance(sql, str) else "",
                "dbsphere_id": dbsphere_id,
                "intent": intent,
            }

    # 2) ToolMessage 순회 — 성공 건 수집(실행 순서), 실패 건은 카운트만
    records: list[dict] = []
    failed_count = 0
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = getattr(msg, "content", None)
        if not isinstance(content, str):
            continue
        if content.startswith("Query executed successfully") or content.startswith(
            "Statement executed successfully"
        ):
            info = sql_by_call_id.get(getattr(msg, "tool_call_id", None) or "", {})
            records.append(
                {
                    "sql": info.get("sql") or "",
                    "dbsphere_id": info.get("dbsphere_id"),
                    "intent": info.get("intent") or "",
                    "result": content,
                }
            )
        elif content.startswith("Error executing SQL query: "):
            failed_count += 1
        # 그 외(validator 거부, invalid-db 메시지 등)는 실제 실행이 아니므로 무시

    if not records:
        return ""

    # 3) max_queries 적용 (최근 우선)
    notes = ""
    total = len(records)
    if max_queries is not None and total > max_queries:
        records = records[-max_queries:]
        notes += (
            f"_Note: showing the last {max_queries} of {total} successful queries._\n\n"
        )
    if failed_count > 0:
        notes += (
            f"_Note: {failed_count} SQL attempt(s) failed and were retried; "
            "only successful queries are shown below._\n\n"
        )

    # 4) 렌더 — 실행 순서, 1-based. SQL 본문·결과는 길이 캡 적용.
    blocks: list[str] = []
    for i, rec in enumerate(records, start=1):
        db = rec.get("dbsphere_id")
        parts = [f"### Query {i}" + (f" (database: {db})" if db else "")]
        if rec.get("intent"):
            parts.append(rec["intent"])
        sql = rec.get("sql") or ""
        if sql:
            if len(sql) > _SQL_CTX_MAX_SQL_CHARS:
                sql = sql[:_SQL_CTX_MAX_SQL_CHARS] + "\n-- ...(SQL truncated)"
            parts.append("```sql\n" + sql + "\n```")
        else:
            parts.append("_SQL text unavailable for this result._")
        result = rec["result"]
        if len(result) > _SQL_CTX_MAX_RESULT_CHARS:
            result = result[:_SQL_CTX_MAX_RESULT_CHARS] + "\n...(truncated)"
        parts.append(result)
        blocks.append("\n".join(parts))

    return notes + "\n\n".join(blocks)


MAX_HISTORY_MESSAGES = 20  # 최근 10턴 (user+assistant 쌍)

# HITL resume 시 1턴의 features(GWS 토글)를 복원하기 위한 프로세스-로컬 stash.
# 프론트 resume payload 가 features 를 누락해도 작성 턴에서 Gmail/Drive 가 살아있게.
# key=thread_id, value=features dict.  interrupt emit 시 저장, resume __init__ 에서 복원.
_HITL_RESUME_FEATURES: dict[str, dict] = {}

# Models that need a manual submit_result tool instead of native structured output.
# These models don't support response_format (ProviderStrategy) or tool_choice (ToolStrategy).
# Matching is by substring in model ID. Ollama models are detected separately via owned_by.
MODELS_NEED_SUBMIT_TOOL = {"gpt-oss", "gemma", "llama"}


class _SubmitResultInput(BaseModel):
    """Input schema for submit_result tool."""

    answerable: bool = Field(
        default=True,
        description=(
            "Set to true if you gathered enough information to answer the user's question. "
            "Set to false if no relevant data was found despite searching."
        ),
    )
    language: str = Field(
        default="Korean",
        description=(
            "The language to use for the response. "
            "Detect and match the language of the user's latest message. "
            "Examples: Korean, English, Japanese, Chinese, etc."
        ),
    )


def _create_submit_result_tool() -> StructuredTool:
    """Create a submit_result tool for models without native structured output.

    This replaces ToolStrategy/ProviderStrategy for models that don't support
    response_format or tool_choice. The agent calls this tool to signal
    that data gathering is complete.

    return_direct=True causes the agent to exit immediately after this tool.
    """

    def submit_result(
        answerable: bool,
        language: str,
        runtime: ToolRuntime,
    ) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Result submitted successfully.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "answerable": answerable,
                "language": language,
            }
        )

    return StructuredTool.from_function(
        func=submit_result,
        name="submit_result",
        description=(
            "Set the output format for your final answer. "
            "The final answer will be generated according to the language "
            "and parameters you specify here. "
            "You MUST call this after gathering data to configure the response."
        ),
        args_schema=_SubmitResultInput,
        return_direct=True,
    )


# Max text chunks before aborting a text-only response in streaming detection.
# After this many content chunks without tool_calls, we assume it's a text response.
_STREAM_TEXT_DETECT_CHUNKS = 3


class _ForceSubmitMiddleware(AgentMiddleware):
    """Middleware that streams model output and forces submit_result when text is detected.

    For models in MODELS_NEED_SUBMIT_TOOL: instead of batch ainvoke, this streams
    the model output. If the first few chunks contain only text (no tool_calls),
    the stream is cancelled early and a forced submit_result tool call is returned.
    This saves tokens that would otherwise be wasted on unwanted text responses.
    """

    async def awrap_model_call(self, request, handler):
        # Bind tools to model (handler normally does this)
        bound_model = (
            request.model.bind_tools(request.tools) if request.tools else request.model
        )

        # Build messages with system message
        messages = list(request.messages)
        if request.system_message:
            messages = [request.system_message, *messages]

        # Stream and detect text vs tool calls
        collected = None
        has_tool_calls = False
        text_chunks = 0
        stream = bound_model.astream(
            messages,
            stream_options={"include_usage": True},
        )

        try:
            async for chunk in stream:
                # Accumulate chunks
                collected = chunk if collected is None else collected + chunk

                if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                    has_tool_calls = True

                if not has_tool_calls and getattr(chunk, "content", ""):
                    text_chunks += 1
                    if text_chunks >= _STREAM_TEXT_DETECT_CHUNKS:
                        # Text-only response detected → cancel stream early
                        logger.info(
                            "[ForceSubmitMiddleware] Text response detected after "
                            f"{text_chunks} chunks, forcing submit_result"
                        )
                        break
        finally:
            # Explicitly close the async generator to free resources
            await stream.aclose()

        # Ensure usage_metadata is always a dict (streaming may not include it)
        _usage = getattr(collected, "usage_metadata", None) or {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        if has_tool_calls and collected:
            # Normal tool call response — return as-is
            ai_msg = AIMessage(
                content=getattr(collected, "content", ""),
                tool_calls=getattr(collected, "tool_calls", []),
                usage_metadata=_usage,
            )
            return ModelResponse(result=[ai_msg])

        # Text-only or empty → force submit_result
        # Try to parse language/answerable from text if model output JSON
        language = "Korean"
        answerable = True
        content = getattr(collected, "content", "") if collected else ""
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                data = json.loads(content.strip())
                language = data.get("language", language)
                answerable = data.get("answerable", answerable)
            except (json.JSONDecodeError, ValueError):
                pass

        forced_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"forced_{uuid.uuid4().hex[:8]}",
                    "name": "submit_result",
                    "args": {
                        "answerable": answerable,
                        "language": language,
                    },
                }
            ],
            usage_metadata=_usage,
        )
        return ModelResponse(result=[forced_msg])


# Memory selective retrieval constants
MEMORY_SELECTIVE_THRESHOLD = 20  # 이 수 이상이면 vector search로 전환
MEMORY_SEARCH_TOP_K = 10  # vector search 반환 수


def _log_messages_debug(
    log: logging.Logger,
    error: Exception,
    initial_messages: list,
    state_messages: list,
) -> None:
    """Log message details when LangGraph agent fails with an API error.

    Helps diagnose issues like 'tool_calls must be followed by tool messages'
    by dumping the message roles, tool_calls, and tool_call_ids.
    """
    try:
        lines = [f"[UnifiedAgent] Agent error details — {error}"]

        # Initial messages (after sanitization, before agent run)
        lines.append(f"  initial_messages ({len(initial_messages)}):")
        for i, m in enumerate(initial_messages):
            role = m.get("role") if isinstance(m, dict) else getattr(m, "type", "?")
            has_tc = bool(
                m.get("tool_calls")
                if isinstance(m, dict)
                else getattr(m, "tool_calls", None)
            )
            tc_id = (
                m.get("tool_call_id")
                if isinstance(m, dict)
                else getattr(m, "tool_call_id", None)
            )
            content_preview = ""
            raw = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            if isinstance(raw, str):
                content_preview = raw[:80].replace("\n", "\\n")
            lines.append(
                f"    [{i}] role={role} tool_calls={has_tc} tool_call_id={tc_id}"
                f" content={content_preview!r}"
            )

        # State messages (accumulated during agent run — includes LangChain objects)
        lines.append(f"  state_messages ({len(state_messages)}):")
        for i, m in enumerate(state_messages):
            mtype = type(m).__name__
            tc = getattr(m, "tool_calls", None)
            tc_id = getattr(m, "tool_call_id", None)
            content = getattr(m, "content", "")
            if isinstance(content, str):
                content = content[:80].replace("\n", "\\n")
            tc_info = ""
            if tc:
                tc_info = f" tool_calls={[c.get('id', '?') for c in tc]}"
            if tc_id:
                tc_info += f" tool_call_id={tc_id}"
            lines.append(f"    [{i}] {mtype}{tc_info} content={content!r}")

        log.exception("\n".join(lines))
    except Exception:
        log.exception(f"[UnifiedAgent] Failed to log debug info: {error}")


# ---------------------------------------------------------------------------
# Dynamic Pydantic builder for json_schema response_format
# ---------------------------------------------------------------------------


def _json_type_to_python(schema: dict):
    """JSON Schema 타입 → Python 타입."""
    json_type = schema.get("type", "string")
    enum_values = schema.get("enum")

    if enum_values is not None:
        from typing import Literal

        return Literal[tuple(enum_values)]

    type_map = {"string": str, "integer": int, "number": float, "boolean": bool}

    if json_type == "array":
        item_type = _json_type_to_python(schema.get("items", {}))
        return List[item_type]

    if json_type == "object":
        return _schema_to_pydantic(f"Nested_{id(schema)}", schema)

    return type_map.get(json_type, str)


def _schema_to_pydantic(model_name: str, schema: dict):
    """JSON Schema object → dynamic Pydantic model."""
    from pydantic import Field, create_model

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    field_defs = {}
    for field_name, field_schema in properties.items():
        python_type = _json_type_to_python(field_schema)
        description = field_schema.get("description")
        if field_name in required_fields:
            field_defs[field_name] = (
                python_type,
                Field(..., description=description) if description else ...,
            )
        else:
            field_defs[field_name] = (
                Optional[python_type],
                Field(None, description=description) if description else None,
            )

    return create_model(model_name, **field_defs)


def _build_pydantic_from_response_format(json_schema_def: dict):
    """agent_config.response_format.json_schema → Pydantic model."""
    name = json_schema_def.get("name", "StructuredResponse")
    schema = json_schema_def.get("schema", {})
    return _schema_to_pydantic(name, schema)


def _create_dynamic_prompt_with_trace(middleware_ref: MiddlewareBase):
    """Create dynamic prompt middleware that also updates middleware for tracing.

    Currently disabled — system prompt is static (schema/memory moved to tool description).
    Kept for future use if dynamic per-turn prompt injection is needed again.
    """
    from extension_modules.agent.prompts import get_unified_dynamic_prompt

    @dynamic_prompt
    def _prompt(request: ModelRequest) -> str:
        state = request.state
        prompt = get_unified_dynamic_prompt(state)
        middleware_ref._system_prompt = prompt  # Update for tracing capture
        return prompt

    return _prompt


class UnifiedAgent(ReactToolsBase):
    """
    Unified Agent combining DbSphere and KbSphere capabilities.

    This agent inherits from ReactToolsBase to get KbSphere functionality
    and conditionally adds DbSphere components based on configuration.

    Capabilities:
    - KbSphere: Document search, knowledge base search, web search
    - DbSphere: SQL generation, execution, visualization
    """

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        """
        Initialize UnifiedAgent.

        Args:
            api_config: API configuration (model settings, etc.)
            base_url: LLM API base URL
            api_key: LLM API key
            metadata: Request metadata (user_id, chat_id, model info, etc.)
            request: FastAPI request object
        """
        # Auto-detect capabilities from connected resources
        agent_config = metadata.get("agent_config")

        self._enable_web_search = False
        self._web_search_config = None
        self._enable_image_generation = False
        self._enable_glossary = False
        self._enable_tool_connections = False
        self._enable_code_interpreter = False
        self._enable_knowledge_graph = False
        # Google Workspace 통합 — 5축 게이트 통과 시에만 True (아래 블록에서 평가)
        self._enable_gmail = False
        self._enable_calendar = False
        self._enable_drive = False
        self._project_context = metadata.get("project_context")

        # 프론트엔드 features 플래그 (사용자가 채팅에서 활성화했는지)
        user_features = (metadata.get("features") or {}) if metadata else {}
        # HITL resume 보강: 프론트 resume payload 가 features 를 누락하면 GWS 5축
        # 게이트가 떨어져 작성 턴에서 Gmail/Drive 도구가 사라진다.  interrupt 시점에
        # 저장해둔 1턴 features 로 복원한다 (현재 명시값 우선).
        _gws_restored = False
        _hitl_resume_meta = metadata.get("hitl_resume") if metadata else None
        if isinstance(_hitl_resume_meta, dict):
            _stashed_features = _HITL_RESUME_FEATURES.get(
                _hitl_resume_meta.get("thread_id")
            )
            if _stashed_features:
                user_features = {**_stashed_features, **user_features}
                _gws_restored = True
        user_enabled_web_search = user_features.get("web_search", False)
        user_enabled_gmail = user_features.get("gmail", False)
        user_enabled_calendar = user_features.get("calendar", False)
        user_enabled_drive = user_features.get("drive", False)
        # has_permission 의 user_id 인자가 빈 문자열이면 get_user_groups 가 빈
        # 결과를 주고 default_permissions fallback 으로 가짜 True 가 날 위험 →
        # fail-closed 를 위해 5축 게이트의 첫 축으로 명시 가드.
        user_id_for_gate = metadata.get("user_id", "") or ""

        if agent_config:
            from open_webui.models.agent_config import AgentConfig

            if isinstance(agent_config, AgentConfig):
                self._enable_kbsphere = agent_config.has_knowledge()
                self._enable_dbsphere = agent_config.has_dbsphere()
                # 에이전트 기능 등록 AND 사용자가 채팅에서 활성화한 경우에만 웹검색
                self._enable_web_search = (
                    agent_config.has_web_search() and user_enabled_web_search
                )
                self._web_search_config = agent_config.web_search_config
                # 에이전트 기능 등록 AND 사용자가 채팅에서 활성화 AND 전역 설정 활성화
                user_enabled_image_generation = user_features.get(
                    "image_generation", False
                )
                self._enable_image_generation = (
                    agent_config.has_image_generation()
                    and user_enabled_image_generation
                    and request.app.state.config.ENABLE_IMAGE_GENERATION
                )
                self._enable_glossary = agent_config.has_glossary()
                self._enable_tool_connections = agent_config.has_tool_connections()
                self._enable_knowledge_graph = agent_config.has_knowledge_graph()

                # Gmail / Calendar 5축 AND 게이트.  한 축이라도 False 면 도구
                # 비노출. (5) OAuth 축은 아래에서 사용자 토큰의 scope 보유 여부로
                # 평가 (클라이언트 features payload 를 신뢰하지 않는 fail-closed) —
                # 토큰 만료/폐기 등 잔여 케이스는 tool 실행 시점에 _common.get_token()
                # 이 최종 검증.
                from open_webui.utils.access_control import has_permission

                self._enable_gmail = (
                    bool(user_id_for_gate)
                    and request.app.state.config.ENABLE_GMAIL_INTEGRATION
                    and has_permission(
                        user_id_for_gate,
                        "features.gmail",
                        request.app.state.config.USER_PERMISSIONS,
                    )
                    and agent_config.has_gmail()
                    and user_enabled_gmail
                )
                self._enable_calendar = (
                    bool(user_id_for_gate)
                    and request.app.state.config.ENABLE_CALENDAR_INTEGRATION
                    and has_permission(
                        user_id_for_gate,
                        "features.calendar",
                        request.app.state.config.USER_PERMISSIONS,
                    )
                    and agent_config.has_calendar()
                    and user_enabled_calendar
                )
                self._enable_drive = (
                    bool(user_id_for_gate)
                    and request.app.state.config.ENABLE_DRIVE_INTEGRATION
                    and has_permission(
                        user_id_for_gate,
                        "features.drive",
                        request.app.state.config.USER_PERMISSIONS,
                    )
                    and agent_config.has_drive()
                    and user_enabled_drive
                )
                # (5) OAuth 축 — 사용자의 google 토큰이 기능별 필수 scope 를
                # 보유해야 도구 노출. GWS scope 도입 이전 SSO 토큰은 row 가
                # 있어도 scope 미달 → fail-closed.
                if self._enable_gmail or self._enable_calendar or self._enable_drive:
                    from open_webui.config import GWS_FEATURE_REQUIRED_SCOPES
                    from open_webui.models.user_oauth_tokens import UserOAuthTokens

                    _gws_row = UserOAuthTokens.get(user_id_for_gate, "google")
                    _gws_granted = (
                        set((_gws_row.scopes or "").split()) if _gws_row else set()
                    )
                    self._enable_gmail = (
                        self._enable_gmail
                        and GWS_FEATURE_REQUIRED_SCOPES["gmail"] <= _gws_granted
                    )
                    self._enable_calendar = (
                        self._enable_calendar
                        and GWS_FEATURE_REQUIRED_SCOPES["calendar"] <= _gws_granted
                    )
                    self._enable_drive = (
                        self._enable_drive
                        and GWS_FEATURE_REQUIRED_SCOPES["drive"] <= _gws_granted
                    )
                # resume 작성 턴에서 GWS 활성 복원 결과 로그 (resume 시에만).
                if _hitl_resume_meta:
                    logger.info(
                        "[UnifiedAgent] GWS gate (resume) restored=%s → "
                        "gmail=%s calendar=%s drive=%s",
                        _gws_restored,
                        self._enable_gmail,
                        self._enable_calendar,
                        self._enable_drive,
                    )
            elif isinstance(agent_config, dict):
                self._enable_kbsphere = bool(agent_config.get("knowledge_bases"))
                self._enable_dbsphere = bool(agent_config.get("dbspheres"))
                # 메인 경로(AgentConfig 인스턴스)와 일관되게 dict 형태로 hydration
                # 된 경우에도 보조 capability 들을 그대로 켠다. KG 가 누락되면
                # KGToolManager 가 attach 되지 않아 도구 호출 자체가 사라진다.
                self._enable_glossary = bool(agent_config.get("glossaries"))
                self._enable_tool_connections = bool(
                    agent_config.get("tool_connections")
                )
                self._enable_knowledge_graph = bool(
                    agent_config.get("knowledge_graphs")
                )
            else:
                self._enable_kbsphere = False
                self._enable_dbsphere = False
        else:
            # Fallback: detect from model meta
            model_info = metadata.get("model", {})
            meta = model_info.get("info", {}).get("meta", {})
            self._enable_kbsphere = bool(meta.get("knowledge"))
            self._enable_dbsphere = bool(meta.get("dbspheres"))

        # Initialize ReactToolsBase (provides KbSphere functionality)
        super().__init__(
            api_config=api_config,
            base_url=base_url,
            api_key=api_key,
            metadata=metadata,
            # Common tools always enabled
            enable_evaluation=False,
            enable_extract_context_info=False,
            # Web search independently controlled by capabilities.web_search
            enable_web_search=self._enable_web_search,
            web_search_config=self._web_search_config,
            request=request,
        )

        # Store capability flags
        # 모델 knowledge 또는 프로젝트 knowledge가 있으면 KbSphere 활성화
        self.enable_kbsphere = self._enable_kbsphere or bool(self.knowledges)
        self.enable_dbsphere = self._enable_dbsphere

        # Code interpreter for data_analysis projects
        if (
            self._project_context
            and self._project_context.get("type") == "data_analysis"
        ):
            self._enable_code_interpreter = True

        # Request reference
        self.request = request

        # DbSphere components (initialized lazily)
        # Single-slot fields below mirror the FIRST connected DB for backward
        # compatibility; multi-DB routing uses dbsphere_registry.
        self.dbsphere_id: Optional[str] = None
        self.dbsphere_info = None
        self.db_config: Optional[DBConfig] = None
        self.sql_runner: Optional[SqlRunnerBase] = None
        self.dbsphere_memory: Optional[SearchEngineDbSphereMemory] = None
        self.chart_generator: Optional[PlotlyChartGenerator] = None

        # Multi-DB: all connected dbsphere ids + per-DB registry
        # {dbsphere_id: {info, data, db_config, dialect, allow_dml, runner, memory}}
        self.dbsphere_ids: List[str] = []
        self.dbsphere_registry: Dict[str, dict] = {}

        # Working directory for query results
        self.working_directory = "data/cache/unified_agent"

        # Initialize DbSphere if enabled
        if self.enable_dbsphere:
            self._init_dbsphere_components()

        logger.info(
            f"[UnifiedAgent] Initialized - "
            f"kbsphere={self.enable_kbsphere}, "
            f"dbsphere={self.enable_dbsphere}, "
            f"glossary={self._enable_glossary}, "
            f"web_search={self._enable_web_search}, "
            f"image_generation={self._enable_image_generation}, "
            f"gmail={self._enable_gmail}, "
            f"calendar={self._enable_calendar}, "
            f"drive={self._enable_drive}, "
            f"files={len(self.files)}, "
            f"file_collections={len(self.file_collections)}"
        )

    def _init_dbsphere_components(self) -> None:
        """Initialize DbSphere-specific components."""
        # Legacy single-DB id (first DB) for backward-compat code paths.
        self.dbsphere_id = self._get_dbsphere_id_from_metadata()
        # All connected dbsphere ids (multi-DB). Fallback to the single legacy id.
        ids: List[str] = []
        if self.agent_config:
            ids = self.agent_config.get_dbsphere_ids()
        if not ids and self.dbsphere_id:
            ids = [self.dbsphere_id]
        self.dbsphere_ids = ids
        self.chart_generator = PlotlyChartGenerator()
        os.makedirs(self.working_directory, exist_ok=True)

    def _get_dbsphere_id_from_metadata(self) -> Optional[str]:
        """Get dbsphere ID from model metadata."""
        # New pattern: use agent_config
        if self.agent_config:
            dbsphere_id = self.agent_config.get_first_dbsphere_id()
            if dbsphere_id:
                return dbsphere_id

        # Legacy pattern (fallback for backward compatibility)
        model_info = self.metadata.get("model", {})
        meta = model_info.get("info", {}).get("meta", {})

        # Try to get dbsphere from meta (support both singular and plural)
        dbsphere_list = meta.get("dbspheres", []) or meta.get("dbsphere", [])
        if isinstance(dbsphere_list, list) and dbsphere_list:
            first_dbsphere = dbsphere_list[0]
            if isinstance(first_dbsphere, dict):
                return first_dbsphere.get("id")
            elif isinstance(first_dbsphere, str):
                return first_dbsphere

        # Fallback: check enhanced_params
        enhanced_params = self.metadata.get("enhanced_params", {})
        return enhanced_params.get("dbsphere_id")

    def _load_dbsphere_config(self) -> Optional[DBConfig]:
        """Load database configuration from DbSphere model."""
        if not self.dbsphere_id:
            logger.warning("[UnifiedAgent] No dbsphere_id found in metadata")
            return None

        # Verify user has read access to this DbSphere
        user_id = self.metadata.get("user_id", "")
        user = Users.get_user_by_id(user_id) if user_id else None

        if not user or user.role != "admin":
            user_dbspheres = DbSpheres.get_dbspheres_by_user_id(user_id, "read")
            if self.dbsphere_id not in [db.id for db in user_dbspheres]:
                logger.warning(
                    f"[UnifiedAgent] User {user_id} has no access to DbSphere {self.dbsphere_id}"
                )
                return None

        dbsphere = DbSpheres.get_dbsphere_by_id(self.dbsphere_id)
        if not dbsphere:
            logger.error(f"[UnifiedAgent] DbSphere not found: {self.dbsphere_id}")
            return None

        self.dbsphere_info = dbsphere

        data = dbsphere.data
        if data:
            data = decrypt_connection_password(data)
            return DBConfig.from_dbsphere_data(data)

        logger.error(
            f"[UnifiedAgent] DbSphere {self.dbsphere_id} has no connection data"
        )
        return None

    def _load_dbsphere_entry(self, dbsphere_id: str) -> Optional[dict]:
        """Load one DB's config + metadata for the registry (no connection opened).

        Mirrors _load_dbsphere_config but for an arbitrary id and returns a dict.
        """
        if not dbsphere_id:
            return None

        # Verify user has read access to this DbSphere
        user_id = self.metadata.get("user_id", "")
        user = Users.get_user_by_id(user_id) if user_id else None
        if not user or user.role != "admin":
            user_dbspheres = DbSpheres.get_dbspheres_by_user_id(user_id, "read")
            if dbsphere_id not in [db.id for db in user_dbspheres]:
                logger.warning(
                    "[UnifiedAgent] User %s has no access to DbSphere %s",
                    user_id,
                    dbsphere_id,
                )
                return None

        dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
        if not dbsphere:
            logger.error("[UnifiedAgent] DbSphere not found: %s", dbsphere_id)
            return None

        data = dbsphere.data
        if not data:
            logger.error(
                "[UnifiedAgent] DbSphere %s has no connection data", dbsphere_id
            )
            return None

        db_config = DBConfig.from_dbsphere_data(decrypt_connection_password(data))
        if not db_config:
            logger.error(
                "[UnifiedAgent] DbSphere %s: failed to build DBConfig", dbsphere_id
            )
            return None

        from extension_modules.dbsphere.sql_runners import get_dialect_name

        dialect = get_dialect_name(db_config.get_db_type_enum())
        allow_dml = bool((dbsphere.meta or {}).get("allow_dml", False))
        return {
            "info": dbsphere,
            # dbsphere.data carries the extracted schema (table_overview etc.) used
            # by the stage-1 catalog; connection fields are never surfaced.
            "data": dbsphere.data,
            "db_config": db_config,
            "dialect": dialect,
            "allow_dml": allow_dml,
        }

    def _build_dbsphere_registry(self) -> None:
        """Build the per-DB registry for ALL connected dbspheres (lazy connect).

        Runner/memory objects are created but NOT connected — SqlRunnerBase is
        lazy-connect, so unused DBs cost nothing until a query runs against them.
        """
        for dbsphere_id in self.dbsphere_ids:
            if dbsphere_id in self.dbsphere_registry:
                continue
            entry = self._load_dbsphere_entry(dbsphere_id)
            if not entry:
                continue
            runner = self._create_sql_runner(entry["db_config"])
            if runner is None:
                continue
            entry["runner"] = runner
            entry["memory"] = self._create_dbsphere_memory(dbsphere_id)
            self.dbsphere_registry[dbsphere_id] = entry

        # Backward-compat single slots = first registry entry.
        if self.dbsphere_registry:
            first_id = next(iter(self.dbsphere_registry))
            first = self.dbsphere_registry[first_id]
            self.dbsphere_id = first_id
            self.dbsphere_info = first["info"]
            self.db_config = first["db_config"]
            self.sql_runner = first["runner"]
            self.dbsphere_memory = first["memory"]

    def _create_sql_runner(
        self, db_config: "Optional[DBConfig]" = None
    ) -> Optional[SqlRunnerBase]:
        """Create SQL runner based on database type."""
        cfg = db_config if db_config is not None else self.db_config
        if not cfg:
            return None

        from extension_modules.dbsphere.sql_runners import create_sql_runner

        runner = create_sql_runner(cfg)
        if not runner:
            db_type = cfg.get_db_type_enum()
            logger.error(f"[UnifiedAgent] Unsupported database type: {db_type}")
        return runner

    def _create_dbsphere_memory(
        self, dbsphere_id: Optional[str] = None
    ) -> Optional[SearchEngineDbSphereMemory]:
        """Create DbSphere memory using search_engine."""
        target_id = dbsphere_id or self.dbsphere_id
        if not target_id:
            return None

        user_id = self.metadata.get("user_id", "")
        chat_id = self.metadata.get("chat_id")
        # Reuse embedding_config from ReactToolsBase (already loaded in __init__)
        embedding_config = self.embedding_config

        # Get trace context from request
        from open_webui.utils.tracing import get_trace_context

        trace_context = get_trace_context(self.request)

        async def create_embedding(text: str) -> Optional[List[float]]:
            try:
                from extension_modules.search_engine import generate_embedding_async

                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=user_id,
                    chat_id=chat_id,
                    trace_context=trace_context,
                )
            except Exception as e:
                logger.warning(f"[UnifiedAgent] Failed to generate embedding: {e}")
                return None

        return SearchEngineDbSphereMemory(
            app=self.request.app,
            dbsphere_id=target_id,
            user_id=user_id,
            embedding_func=create_embedding,
        )

    def _get_db_dialect(self) -> str:
        """Get database dialect name for prompts (registry delegation)."""
        if not self.db_config:
            return "SQL"

        from extension_modules.dbsphere.sql_runners import get_dialect_name

        return get_dialect_name(self.db_config.get_db_type_enum())

    def get_tools(self) -> List[StructuredTool]:
        """
        Get the tools available to this agent.

        Combines:
        - Common tools: extract_context_info, evaluation_result (always)
        - KbSphere tools: get_file_contents, knowledge_handler, search_web (if enabled)
        - DbSphere tools: run_sql, visualize_data (if enabled)
        """
        tools = []

        # KbSphere + web search + file upload tools (from parent class)
        if self.enable_kbsphere or self._enable_web_search or self.file_collections:
            tools = super().get_tools()
        else:
            # Only common tools (extract_context_info, evaluation_result)
            from extension_modules.react.tool_models import (
                EvaluateSearchResultsOutput,
                ExtractContextInfoInput,
            )

            if self.enable_extract_context_info:
                extract_tool = StructuredTool.from_function(
                    func=self.extract_context_info,
                    name="extract_context_info",
                    description="""
                    이 도구는 어떤 도구보다 **가장 먼저 수행** 되어야 합니다.

                    질문에서 언어 및 질문에서 오탈자나 문맥을 정제한 질문을 추출합니다.
                    - language: 짧은 언어 식별자 (예: Korean/English 등)
                    - normalized_question: 질문에서 오탈자나 문맥 (채팅 히스토리 포함)을 정제한 질문
                    """,
                    args_schema=ExtractContextInfoInput,
                )
                tools.append(extract_tool)

            if self.enable_evaluation:
                eval_tool = StructuredTool.from_function(
                    func=self.evaluation_result,
                    name="evaluation_result",
                    description="""검색 결과를 평가합니다.
                    검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하고 점수와 이유를 추출하여 상태를 설정 합니다.
                    context를 리턴 받는 모든 도구를 호출시 무조건 이 도구를 통해 평가를 수행해야 합니다.
                    """,
                    args_schema=EvaluateSearchResultsOutput,
                )
                tools.append(eval_tool)

        # DbSphere tools (3-stage: dbsphere_info → get_table_details → run_sql).
        # Multi-DB: fixed tool names + a dbsphere_id selector routed through the
        # per-DB registry. dbsphere_info is a catalog over ALL connected DBs.
        if self.enable_dbsphere and self.dbsphere_registry:
            registry = self.dbsphere_registry
            dbsphere_ids = list(registry.keys())

            # Stage 1: catalog of all connected DBs
            tools.append(create_dbsphere_info_tool(registry=registry))

            # Stage 2: Table details (dbsphere_id selector)
            tools.append(
                create_get_table_details_tool(
                    registry=registry,
                    dbsphere_ids=dbsphere_ids,
                )
            )

            # Stage 3: SQL execution — read 는 항상, write 는 DbSphere 인스턴스의
            # meta.allow_dml 이 true 인 DB 만 selector 에 포함. 도구 이름은 고정
            # (run_sql_read / run_sql_write) 이라 HITL 정책 (hitl_policy.py) 이
            # 그대로 동작한다.
            tools.append(
                create_run_sql_read_tool(
                    registry=registry,
                    dbsphere_ids=dbsphere_ids,
                    working_directory=self.working_directory,
                )
            )
            write_ids = [did for did, e in registry.items() if e.get("allow_dml")]
            if write_ids:
                tools.append(
                    create_run_sql_write_tool(
                        registry=registry,
                        dbsphere_ids=write_ids,
                        working_directory=self.working_directory,
                    )
                )
                logger.info(
                    "[UnifiedAgent] run_sql_write 등록 (allow_dml DBs): %s", write_ids
                )
            else:
                logger.info("[UnifiedAgent] run_sql_write 미등록 (allow_dml DB 없음)")

            # Visualization tool (global, filename-keyed — DB-agnostic)
            tools.append(
                create_visualize_data_tool(
                    working_directory=self.working_directory,
                    chart_generator=self.chart_generator,
                )
            )

        # Glossary 도구
        if self._enable_glossary:
            glossary_ids = self.agent_config.get_glossary_ids()

            # Permission filter: 타 사용자의 private glossary가 에이전트에 묶여있어도
            # 현재 실행 user_id 기준으로 access_control 재검증 (KB 패턴과 동일)
            user_id = self.metadata.get("user_id", "")
            if user_id and glossary_ids:
                user = Users.get_user_by_id(user_id)
                if user and user.role != "admin":
                    allowed = {
                        g.id
                        for g in Glossaries.get_glossaries_by_user_id(user_id, "read")
                    }
                    blocked = [gid for gid in glossary_ids if gid not in allowed]
                    if blocked:
                        logger.warning(
                            "User %s blocked from glossaries %s in agent %s",
                            user_id,
                            blocked,
                            self.metadata.get("model_id"),
                        )
                    glossary_ids = [gid for gid in glossary_ids if gid in allowed]

            # 각 glossary 메타데이터 조회 → 동적 description 생성
            glossary_lines = []
            for gid in glossary_ids:
                g = Glossaries.get_glossary_by_id(gid)
                if g:
                    line = f"- {g.name}"
                    if g.description:
                        line += f": {g.description}"
                    glossary_lines.append(line)

            if not glossary_ids:
                # 권한 필터 후 남은 glossary 없으면 tool 자체를 추가하지 않음
                pass
            else:
                if glossary_lines:
                    dynamic_desc = (
                        "용어집에서 용어를 검색합니다.\n\n"
                        "중요: 답을 안다고 생각해도 건너뛰지 말고, 사용자 질문의 "
                        "핵심 용어·약어·도메인 단어는 답변 전에 먼저 이 도구로 "
                        "조회하세요.\n\n"
                        "등록된 용어집:\n"
                        + "\n".join(glossary_lines)
                        + "\n\n사용 시점:\n"
                        "- 사용자 질문에 모르는 약어, 전문 용어, 업무 용어가 있을 때\n"
                        "- 용어의 정확한 의미나 정의가 필요할 때\n"
                        "- 동의어나 유사 표현을 알고 싶을 때\n\n"
                        "참고: 검색 결과가 없으면 해당 용어가 용어집에 등록되지 않은 것입니다."
                    )
                else:
                    dynamic_desc = None  # 기본 description 사용

                glossary_tools_instance = GlossaryTools(
                    self.request.app, glossary_ids, description=dynamic_desc
                )
                tools.extend(glossary_tools_instance.get_tools())

        # Image generation tool
        if self._enable_image_generation:
            from extension_modules.agent.image_tool import create_image_generation_tool

            connection_idx = None
            agent_config = self.metadata.get("agent_config")
            if agent_config:
                from open_webui.models.agent_config import AgentConfig

                if isinstance(agent_config, AgentConfig):
                    connection_idx = agent_config.get_image_connection_idx()

            # Also check user features for connection_idx (from chat dropdown)
            user_features = (
                (self.metadata.get("features") or {}) if self.metadata else {}
            )
            if user_features.get("image_connection_idx") is not None:
                connection_idx = user_features.get("image_connection_idx")

            tools.append(
                create_image_generation_tool(
                    self.request, self._user, connection_idx=connection_idx
                )
            )

        # Short-term memory tool (chat history beyond context window)
        chat_id = self.metadata.get("chat_id")
        user_id = self.metadata.get("user_id")
        if chat_id and user_id:
            from extension_modules.agent.memory_tools import (
                create_get_recent_history_tool,
            )

            tools.append(
                create_get_recent_history_tool(
                    chat_id=chat_id,
                    user_id=user_id,
                    current_message_count=MAX_HISTORY_MESSAGES,
                )
            )

        # Code interpreter (data_analysis projects) — 3-stage tools
        if self._enable_code_interpreter and self._project_context:
            from extension_modules.agent.code_interpreter_tool import (
                create_code_interpreter_tools,
            )

            ci_tools = create_code_interpreter_tools(
                app=self.request.app,
                project_context=self._project_context,
                event_emitter=self.event_emitter,
            )
            tools.extend(ci_tools)

        # Tool connection meta-tools (two-stage selection)
        if self._enable_tool_connections:
            from extension_modules.agent.tool_connection_tools import (
                ToolConnectionManager,
            )

            tc_manager = ToolConnectionManager(
                tool_connections=self.agent_config.tool_connections,
                user_id=self.metadata.get("user_id"),
            )
            tools.extend(tc_manager.get_tools())

        # Knowledge graph tools (term resolution + semantic search + traversal)
        if self._enable_knowledge_graph:
            from extension_modules.knowledge_graph import KGToolManager

            # Last user message is cached on self by _run before get_tools().
            # KG tools save successful Q-SQL pairs to DbSphere memory using it
            # (mirrors dbsphere_agent.save_sql_memory behavior).
            kg_manager = KGToolManager(
                app=self.request.app,
                kg_ids=self.agent_config.get_knowledge_graph_ids(),
                user_id=self.metadata.get("user_id", ""),
                chat_id=self.metadata.get("chat_id"),
                user_question=getattr(self, "_last_user_question", ""),
            )
            kg_tools = kg_manager.get_tools()
            tools.extend(kg_tools)
            logger.info(
                f"[UnifiedAgent] Added {len(kg_tools)} KG tools: "
                f"{[t.name for t in kg_tools]}"
            )

        # UI action tools (client-side DOM manipulation via embed widget)
        # embed widget 호스트 페이지에서만 의미가 있으므로 client_type=="widget" 일 때만 등록.
        # 일반 web chat 도 session_id/chat_id/message_id 를 모두 가지므로 그것만으로는
        # 게이트가 되지 않는다 (EmbedChat.svelte 가 client_type:'widget' 을 보냄).
        client_type = (self.metadata.get("client_type") or "").lower()
        session_id = self.metadata.get("session_id")
        chat_id = self.metadata.get("chat_id")
        message_id = self.metadata.get("message_id")
        if client_type == "widget" and session_id and chat_id and message_id:
            try:
                from extension_modules.agent.ui_action_tools import UIActionManager
                from open_webui.socket.main import sio as _sio

                ui_manager = UIActionManager(
                    sio=_sio,
                    session_id=session_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=self.metadata.get("user_id") or None,
                )
                ui_tools = ui_manager.get_tools()
                tools.extend(ui_tools)
                logger.info(
                    f"[UnifiedAgent] Added {len(ui_tools)} UI action tools: "
                    f"{[t.name for t in ui_tools]}"
                )
            except Exception as e:
                logger.warning(f"[UnifiedAgent] UI action tools unavailable: {e}")

        # ask_user — 에이전트 capabilities.ask_user (구 human_in_the_loop) 가
        # on/user 일 때만 등록. 정보 부족 / 모호 의도 시 LLM 이 사용자에게
        # 직접 되묻는 도구. 위험 도구 승인 게이트와는 별개 — 게이트는 항상 활성.
        if self.agent_config and self.agent_config.is_ask_user_enabled():
            # ask_user 는 HITL interrupt(respond)로만 동작 → checkpointer 가 있어야
            # 그래프를 일시정지/재개할 수 있다. 없으면 가로채지 못해 도구 본체
            # (NotImplementedError)까지 흘러가므로 등록 자체를 건너뛴다. 정책 측에서는
            # resolve_interrupt_policy 가 ENABLE_HITL 과 무관하게 ask_user 를
            # respond-only 로 항상 가로채므로, checkpointer 만 있으면 정상 동작한다.
            _ckpt = getattr(self.request.app.state, "checkpointer", None)
            if _ckpt is not None:
                from extension_modules.agent.ask_user_form_tool import (
                    create_ask_user_form_tool,
                )
                from extension_modules.agent.ask_user_tool import create_ask_user_tool

                # ask_user: 단일 질문 / ask_user_form: 여러 항목을 한 카드에 폼으로.
                # 둘 다 respond-only interrupt 로 동작 — 같은 capability(ask_user)
                # 토글에 묶어 함께 노출하고, LLM 이 상황에 맞게 고른다.
                tools.append(create_ask_user_tool())
                tools.append(create_ask_user_form_tool())
                logger.info("[UnifiedAgent] Added ask_user + ask_user_form tools")
            else:
                logger.info(
                    "[UnifiedAgent] ask_user enabled but no checkpointer → skip "
                    "(interrupt requires a checkpointer)"
                )

        # document_tools — LLM 이 직접 PPT/Word/Excel 파일을 생성하는 툴 3개.
        # 디폴트 on (capabilities.document_tools = "on"). user_id 가 metadata 에
        # 있어야 Files 테이블에 귀속 가능 — 없으면 등록 자체를 스킵.
        if self.agent_config and self.agent_config.has_document_tools():
            user_id = self.metadata.get("user_id")
            if user_id:
                from extension_modules.tools.document import make_document_tools

                # attached_files: 채팅에 첨부된 파일 ID 리스트. Presenton 경로에서
                # 사용자가 직접 .pptx 를 첨부해 그 디자인을 템플릿으로 쓰는 데 사용.
                # 첨부는 metadata["files"] 에 [{"type","file":{"id",...}},...] 형태로 옴
                # (process_chat_payload, middleware.py:195).
                attached_files = [
                    fid
                    for f in (self.metadata.get("files") or [])
                    if isinstance(f, dict)
                    and (fid := (f.get("file") or {}).get("id") or f.get("id"))
                ]
                # event_emitter 주입 → Presenton 경로가 생성 단계별 진행상황을 표시.
                doc_tools = make_document_tools(
                    user_id,
                    event_emitter=getattr(self, "event_emitter", None),
                    attached_files=attached_files,
                )
                tools.extend(doc_tools)
                logger.info(
                    f"[UnifiedAgent] Added {len(doc_tools)} document tools: "
                    f"{[t.name for t in doc_tools]}"
                )
            else:
                logger.warning(
                    "[UnifiedAgent] document_tools enabled but user_id missing — skipped"
                )

        # Google Workspace tools — 5축 게이트 (T-B07) 통과 시에만 활성.
        # 자세한 게이트 평가는 __init__ 의 L431 isinstance(AgentConfig) 블록에서.
        if self._enable_gmail or self._enable_calendar or self._enable_drive:
            user_id = self.metadata.get("user_id")
            if user_id:
                enabled: set[str] = set()
                if self._enable_gmail:
                    enabled.add("gmail")
                if self._enable_calendar:
                    enabled.add("calendar")
                if self._enable_drive:
                    enabled.add("drive")

                from extension_modules.tools.google import make_google_tools
                from extension_modules.tools.google.inprocess._extract import (
                    resolve_extraction_config,
                )

                # [P2] Drive 바이너리/Gmail 첨부(PDF/Office) 본문 추출 설정 —
                # request.app.state.config 에서 RAG 엔진/kwargs 를 평문으로 resolve
                # 해 builder 에 전달(no-request 계약 유지).  None 이면 추출 비활성.
                extraction_config = None
                try:
                    extraction_config = resolve_extraction_config(
                        self.request.app.state.config
                    )
                except Exception as exc:  # config 부재/형상 변경에도 도구는 동작.
                    logger.warning(
                        "[UnifiedAgent] resolve_extraction_config failed: %s", exc
                    )

                # T-B21 quota tracking 의 정확도를 위해 chat_id 를 conversation_id
                # 로 전달.  None 이면 user 단위 quota 로 fallback.
                google_tools = make_google_tools(
                    user_id,
                    enabled,
                    conversation_id=self.metadata.get("chat_id"),
                    extraction_config=extraction_config,
                )
                tools.extend(google_tools)
                logger.info(
                    f"[UnifiedAgent] Added {len(google_tools)} Google tools "
                    f"(enabled={sorted(enabled)}): {[t.name for t in google_tools]}"
                )
            else:
                logger.warning(
                    "[UnifiedAgent] Google tools enabled but user_id missing — skipped"
                )

        # drive_select_files (HITL picker) — Drive 활성 시 등록.  실제 가로채기는
        # 아래 scoped HITL policy 가 담당.  capabilities.ask_user 와 무관(정확성 가드).
        # checkpointer 부재 시엔 본체 graceful fallback 으로 안전 진행(M-4).
        if self._enable_drive:
            from extension_modules.agent.drive_select_files_tool import (
                create_drive_select_files_tool,
            )

            tools.append(create_drive_select_files_tool())
            logger.info("[UnifiedAgent] Added drive_select_files (HITL picker) tool")

        return tools

    async def _prepare_context(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Prepare context before agent execution.

        - DbSphere: Pre-load schema + memory (stored on self for tool description)
        - KbSphere: Just tool setup (actual search is on-demand)

        Returns:
            Context dict with active_capabilities
        """
        context = {
            "active_capabilities": [],
        }

        # DbSphere context (build per-DB registry; lazy connect)
        if self.enable_dbsphere:
            context["active_capabilities"].append("dbsphere")

            if not self.dbsphere_registry:
                self._build_dbsphere_registry()

            if self.dbsphere_registry:
                logger.info(
                    "[UnifiedAgent] DbSphere initialized: %d DB(s) %s "
                    "(3-stage: dbsphere_info → get_table_details → run_sql)",
                    len(self.dbsphere_registry),
                    list(self.dbsphere_registry.keys()),
                )

        # KbSphere context (tools will search on-demand)
        if self.enable_kbsphere:
            context["active_capabilities"].append("kbsphere")

        # Glossary
        if self._enable_glossary:
            context["active_capabilities"].append("glossary")

        # Web search (independent of KbSphere)
        if self._enable_web_search:
            if "web_search" not in context["active_capabilities"]:
                context["active_capabilities"].append("web_search")

        # Tool connections (two-stage selection)
        if self._enable_tool_connections:
            context["active_capabilities"].append("tool_connections")

        # Knowledge graph (term resolution, semantic search, traversal)
        if self._enable_knowledge_graph:
            context["active_capabilities"].append("knowledge_graph")

        # Code interpreter (data_analysis projects)
        if self._enable_code_interpreter:
            context["active_capabilities"].append("code_interpreter")

        # Document tools (PPT/Word/Excel 생성 — capability 디폴트 on)
        if self.agent_config and self.agent_config.has_document_tools():
            context["active_capabilities"].append("document_tools")

        # Gmail / Calendar — 5축 게이트는 __init__ 에서 평가되어 self._enable_*
        # 에 저장됨. 도구는 get_tools() 에서 attach 되지만, system prompt 의 hint
        # 블록 활성화를 위해 active_capabilities 에도 합류시켜야 LLM 이 도구 존재
        # 와 사용 시나리오 가이드를 인지할 수 있다 (그 없으면 Korean query 등
        # ambiguous 한 케이스에서 도구가 attached 돼있어도 "no tool" hallucinate).
        if self._enable_gmail:
            context["active_capabilities"].append("gmail")
        if self._enable_calendar:
            context["active_capabilities"].append("calendar")
        if self._enable_drive:
            context["active_capabilities"].append("drive")

        # Capabilities configured on the agent (agent_config.has_*) but NOT
        # active this turn (5축 게이트 axis 1/2/3/5 중 하나 실패 — 가장 흔한
        # 케이스는 axis 5 = 사용자 토글 OFF or OAuth 미연결). LLM 이 이를
        # 인지하면 "도구 없음" hallucinate 대신 사용자에게 토글/연결 안내를
        # 정확히 줄 수 있다 — agent prompt + final-answer prompt 양쪽에서
        # 이 리스트를 보고 unavailable_hint / ## Unavailable Capabilities
        # 섹션을 렌더한다.
        unavailable: list[str] = []
        if (
            self.agent_config
            and self.agent_config.has_gmail()
            and not self._enable_gmail
        ):
            unavailable.append("gmail")
        if (
            self.agent_config
            and self.agent_config.has_calendar()
            and not self._enable_calendar
        ):
            unavailable.append("calendar")
        if (
            self.agent_config
            and self.agent_config.has_drive()
            and not self._enable_drive
        ):
            unavailable.append("drive")
        context["unavailable_capabilities"] = unavailable

        return context

    @staticmethod
    def _sanitize_messages_for_agent(
        messages: List[Dict[str, Any]],
        max_messages: int = MAX_HISTORY_MESSAGES,
    ) -> List[Dict[str, Any]]:
        """Sanitize messages before passing to LangGraph agent.

        1. Strip tool_calls from assistant messages and drop tool-role messages.
           These are internal artifacts from previous agent runs or OpenWebUI's
           native tool calling; the new agent run will generate its own tool calls.
        2. Truncate to max_messages (user/assistant only) to stay within limits.
        """
        cleaned = []
        dropped_tool = 0
        stripped_tool_calls = 0
        for m in messages:
            role = m.get("role")
            if role == "tool":
                dropped_tool += 1
                continue
            if role == "assistant" and "tool_calls" in m:
                stripped_tool_calls += 1
                cleaned.append({k: v for k, v in m.items() if k != "tool_calls"})
                continue
            cleaned.append(m)
        if dropped_tool or stripped_tool_calls:
            logger.info(
                f"[UnifiedAgent] sanitize_messages: dropped {dropped_tool} tool msgs, "
                f"stripped tool_calls from {stripped_tool_calls} assistant msgs "
                f"(total {len(messages)} → {len(cleaned)})"
            )
        return cleaned[-max_messages:]

    async def _run_agent(
        self,
        payload: Dict[str, Any],
        tools: List[StructuredTool],
        context: Dict[str, Any],
        *,
        resume_input: Any = None,
        resume_thread_id: Optional[str] = None,
        resume_chain_run_id: Optional[str] = None,
        resume_trace_id: Optional[str] = None,
        resume_decisions: Optional[List[Dict[str, Any]]] = None,
    ) -> UnifiedAgentState:
        """Run the LangGraph agent.

        Args:
            resume_input: HITL resume 시 langgraph Command(resume=...) 인스턴스.
                None 이면 새 invocation, 있으면 기존 그래프를 깨움 (retry 1회).
            resume_thread_id: resume 시 깨울 thread_id. resume_input 과 짝.
            resume_chain_run_id: 첫 invocation 의 chain trace 의 run_id. middleware
                에 주입해서 child run 들이 같은 chain 의 child 로 박힘 (트레이스
                두 개로 쪼개지지 않게).
            resume_trace_id: 첫 invocation 의 trace_id. 같은 trace 안에 보이도록.
        """
        # Variant A2 — raw user message stash for knowledge_handler.
        # system prompt 의 KV-cache conditioning 이 LLM tool args 를 흔드는 retrieval drift 차단
        # (Channel B/C/D). 압축 전 시점에 stash 하여 auto_compress_history 영향 회피.
        self._raw_user_message_for_retrieval = self._get_last_user_message(payload)
        logger.debug(
            "[UnifiedAgent] raw_user_message stashed (len=%d)",
            len(self._raw_user_message_for_retrieval or ""),
        )

        llm = self._create_llm(payload, stream=False)
        messages, user_system_prompt = self._extract_messages_and_prompt(payload)
        messages = self._sanitize_messages_for_agent(messages)
        # PR4 (option B): 현재 턴 업로드 파일을 합성 tool 메시지로 추론 루프에 주입한다.
        # 모델 tool-call 확률성 제거 + 루프가 파일을 '보게' 하여 KB 검색으로 새지 않게.
        # 신규 run 1회만 (resume 는 checkpointer state 에 이미 있어 중복 주입 방지).
        if resume_input is None:
            messages = await self._inject_prefetched_files(messages)
        attached_files = self.metadata.get("message_info", {}).get("file_ids", [])

        active_caps = context.get("active_capabilities", [])
        unavailable_caps = context.get("unavailable_capabilities", [])
        logger.info(
            "[UnifiedAgent] active_capabilities=%s, unavailable=%s, tools=%d",
            active_caps,
            unavailable_caps,
            len(tools),
        )

        # Build system prompt (unified framework + user's task prompt)
        system_prompt = get_unified_system_prompt(
            active_capabilities=active_caps,
            task_prompt=user_system_prompt or "",
            unavailable_capabilities=unavailable_caps,
            current_datetime=self._current_datetime_for_prompt(),
        )
        if "code_interpreter" in active_caps:
            logger.info(
                "[UnifiedAgent] system_prompt contains CODE INTERPRETER: %s",
                "CODE INTERPRETER" in system_prompt,
            )

        # Create agent with middleware
        middleware_metadata = {
            **self.metadata,
            "llm_model_id": payload.get("model"),
        }

        from open_webui.utils.tracing import get_trace_context

        trace_context = get_trace_context(self.request)
        middleware = MiddlewareBase(
            self.event_emitter,
            self.event_call,
            middleware_metadata,
            trace_context=trace_context,
        )
        middleware._system_prompt = system_prompt  # Initial system prompt for tracing
        middleware._tool_descriptions = {
            t.name: t.description for t in tools if t.description
        }
        # Resume 흐름이면 첫 invocation 의 chain trace 를 그대로 이어간다 — middleware
        # 의 _trace_id / _chain_run_id 를 미리 주입하고, 트레이스 stack 에도 chain_run_id
        # 를 push 해서 그 이후 새로 시작되는 LLM/tool child run 들이 dotted_order 상
        # 그 chain 의 child 로 박힌다. 그렇지 않으면 resume 마다 새 chain 이 만들어져
        # 트레이스가 두 chain 으로 쪼개진다.
        if resume_input is not None:
            if resume_trace_id:
                middleware._trace_id = resume_trace_id
            if resume_chain_run_id:
                middleware._chain_run_id = resume_chain_run_id
                # _effective_run_stack 은 _start_trace_run 이 dotted_order 계산 시
                # 부모를 결정할 때 본다. 같은 chain 의 child 로 인식되도록 push.
                stack = getattr(middleware, "_effective_run_stack", None)
                if isinstance(stack, list):
                    stack.append(resume_chain_run_id)
                logger.info(
                    "[UnifiedAgent] resume: chain_run_id=%s trace_id=%s 재사용",
                    resume_chain_run_id,
                    resume_trace_id,
                )

            # HITL 사용자 결정 자체를 별도 trace run 으로 기록 — 트레이스에서
            # "사용자가 approve/reject 했다" 가 시각적으로 보이도록.
            if resume_decisions:
                try:
                    from open_webui.models.message_trace import RunType

                    decision_run_id = middleware._start_trace_run(
                        run_type=RunType.TASK.value,
                        name="hitl_decision",
                        inputs={
                            "thread_id": resume_thread_id,
                            "decisions": resume_decisions,
                        },
                        push_stack=False,  # 자식 가지지 않는 leaf
                    )
                    if decision_run_id:
                        middleware._complete_trace_run(
                            decision_run_id,
                            outputs={
                                "decision_count": len(resume_decisions),
                                "approved": sum(
                                    1
                                    for d in resume_decisions
                                    if d.get("type") == "approve"
                                ),
                                "rejected": sum(
                                    1
                                    for d in resume_decisions
                                    if d.get("type") == "reject"
                                ),
                            },
                        )
                except Exception as e:
                    logger.warning("[UnifiedAgent] hitl_decision trace failed: %s", e)
        self._middleware = middleware  # Store for _run_stream final answer tracing
        # show_reasoning 라이브 스트리밍 레벨 주입 — 미들웨어가 툴 실행 중 in-place
        # collapsible 블록을 emit 하도록 (off 면 비활성).
        middleware._show_reasoning_level = (
            self.agent_config.get_show_reasoning_level() if self.agent_config else "off"
        )

        # Determine if this model needs a manual submit_result tool
        # (models without native structured output / tool_choice support)
        model_info = self.metadata.get("model", {})
        _is_ollama = model_info.get("owned_by") == "ollama"
        _needs_submit_tool = _is_ollama or any(
            part in (payload.get("model") or "").lower()
            for part in MODELS_NEED_SUBMIT_TOOL
        )

        if _needs_submit_tool:
            tools.append(_create_submit_result_tool())

        # Tool call limit: prevents runaway agent loops.
        # [H1] 전역 합산(__all__) 한도.  검색→다건 읽기→종합→작성(gmail_send/
        # create_docx) 멀티스텝이 budget 소진으로 작성 산출물을 못 만들고 종료되는
        # 회귀(10 도달 시 exit_behavior=end → compose blocked)를 막기 위해 20 으로
        # 상향.  ceiling 이라 짧게 끝나는 작업의 비용엔 영향 없음.
        tool_limit = ToolCallLimitMiddleware(run_limit=20, exit_behavior="end")

        # HITL middleware — ENABLE_HITL 설정으로 활성/비활성 제어.
        # 비활성 시 모든 도구 자동승인 (빈 policy).
        # 활성 시 build_interrupt_policy 로 도구별 승인 정책 적용.
        from extension_modules.agent.hitl_policy import (
            CloosphereHITLMiddleware,
        )

        enable_hitl = getattr(
            getattr(self.request.app.state, "config", None),
            "ENABLE_HITL",
            False,
        )

        # checkpointer 가용 여부 — scoped picker 가로채기와 create_agent 가 공유.
        _checkpointer = getattr(self.request.app.state, "checkpointer", None)
        _picker_active = (
            self._enable_drive
            and _checkpointer is not None
            and any(getattr(t, "name", None) == "drive_select_files" for t in tools)
        )

        from extension_modules.agent.hitl_policy import resolve_interrupt_policy

        policy = resolve_interrupt_policy(
            tools, enable_hitl=enable_hitl, picker_active=_picker_active
        )
        logger.info(
            "[UnifiedAgent] HITL policy: enable_hitl=%s picker_active=%s interrupt=%s",
            enable_hitl,
            _picker_active,
            [k for k in policy],
        )

        hitl_middleware = CloosphereHITLMiddleware(
            interrupt_on=policy,
            description_prefix="도구 실행 승인 필요",
        )

        # Force submit_result middleware: streams model output to detect
        # text-only responses early and cancel, saving tokens.
        # Only active for models that need submit_result.
        force_submit = _ForceSubmitMiddleware() if _needs_submit_tool else None

        # Load guardrail middlewares from agent config
        # If pre-agent check already created middlewares, reuse them
        # to avoid double LLM Judge calls
        guardrail_middlewares = getattr(self, "_guardrail_middlewares", [])
        effective_ids = self._get_effective_guardrail_ids()
        if not guardrail_middlewares and effective_ids:
            guardrail_middlewares = create_guardrail_middlewares(
                effective_ids,
                app=self.request.app,
                metadata=self.metadata,
                trace_context=trace_context,
            )
            self._guardrail_middlewares = guardrail_middlewares

        # HITL interrupt-resume 용 checkpointer — 위 정책 결정에서 읽은 값 재사용.
        checkpointer = _checkpointer

        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=UnifiedAgentState,
            middleware=[
                # Guardrails are handled separately:
                # - Input: pre-agent check in run()
                # - Output: _apply_output_guardrails() in _run_stream()
                tool_limit,  # 1st: tool call limit
                middleware,  # 2nd: tracing + usage
                *(
                    [force_submit] if force_submit else []
                ),  # 3rd: force submit (streaming)
                hitl_middleware,  # 4th: HITL approval gate (항상 등록)
            ],
            # Lightweight structured output: just answerable bool + language.
            # - GPT/Gemini: 자동 전략 (ProviderStrategy 또는 ToolStrategy)
            # - Ollama/gpt-oss: submit_result 도구로 대체 (tool_choice 미지원)
            response_format=(None if _needs_submit_tool else UnifiedAgentOutput),
            checkpointer=checkpointer,
        )

        # Enable error handling for all tool errors (not just ToolInvocationError).
        # Default _default_handle_tool_errors only catches ToolInvocationError and
        # re-raises everything else. When parallel tool calls are made and one fails
        # (e.g., network error), the failed call produces no ToolMessage, causing
        # "tool_calls must be followed by tool messages" API error on next LLM call.
        _patched_tool_errors = False
        for node in agent.nodes.values():
            inner = getattr(node, "bound", node)
            if hasattr(inner, "_handle_tool_errors"):
                inner._handle_tool_errors = True
                _patched_tool_errors = True
                break
        logger.info(
            f"[UnifiedAgent] ToolNode handle_tool_errors patched: {_patched_tool_errors}"
        )

        # Initial state
        state_snapshot = {
            "messages": messages,
            "attached_files": attached_files,
            "active_capabilities": active_caps,
            "db_dialect": self._get_db_dialect() if self.enable_dbsphere else "SQL",
            "task_prompt": user_system_prompt or "",
        }
        # Use astream to capture intermediate states, allowing recovery
        # when structured output parsing fails at the end of the agent run.
        # Without this, a JSON parsing error in UnifiedAgentOutput would
        # discard all gathered tool results.
        #
        # Retry logic: transient LLM API errors (e.g., "tool_calls must be
        # followed by tool messages", rate limits, timeouts) are retried up to
        # max_retries times with exponential backoff.
        # Resume 모드면 retry 1회 (또 interrupt 가능), 그 외엔 transient error
        # 대비 최대 3회.
        max_retries = 1 if resume_input is not None else 3
        last_err = None

        # thread_id 전략:
        #   - resume: 호출자가 지정한 thread_id 강제 (그래프를 정확히 그 thread 로 깨움)
        #   - 일반 첫 attempt: message_id 그대로 (HITL interrupt 발생 시 /resume 가
        #     같은 thread 를 깨워야 함 — 안정적이고 추적 가능한 id 필요).
        #   - 일반 retry: fresh suffix — transient LLM error 후 같은 thread 로 재호출하면
        #     langgraph 가 이전 final/error state 를 보고 조기 종료하는 부작용 회피.
        import uuid as _uuid

        _thread_base = (
            self.metadata.get("message_id") or self.metadata.get("chat_id") or "anon"
        )

        for attempt in range(1, max_retries + 1):
            last_state = state_snapshot
            astream_kwargs = {"stream_mode": "values"}
            if checkpointer is not None:
                if resume_input is not None and resume_thread_id:
                    thread_id = resume_thread_id
                elif attempt == 1:
                    thread_id = _thread_base
                else:
                    thread_id = f"{_thread_base}:retry{attempt}:{_uuid.uuid4().hex[:6]}"
                astream_kwargs["config"] = {"configurable": {"thread_id": thread_id}}
            astream_input = resume_input if resume_input is not None else state_snapshot
            try:
                async for state in agent.astream(astream_input, **astream_kwargs):
                    last_state = state

                # HITL interrupt 감지: stream 이 정상 종료해도 graph 가 멈춰
                # 사람의 결정을 기다리는 상태일 수 있음 (HITL middleware 가
                # interrupt() 발생). aget_state 로 확인 후 마커를 last_state 에
                # 박아 _run_stream 에서 hitl_request SSE 로 전환한다.
                if checkpointer is not None and "config" in astream_kwargs:
                    interrupts = await self._detect_hitl_interrupts(
                        agent, astream_kwargs["config"]
                    )
                    if interrupts:
                        last_state["__hitl_interrupt__"] = {
                            "thread_id": astream_kwargs["config"]["configurable"][
                                "thread_id"
                            ],
                            "interrupts": interrupts,
                        }
                        result = last_state
                        break  # interrupt 도 정상 종료의 일종 — retry 안 함

                result = last_state
                break  # success
            except Exception as e:
                error_str = str(e).lower()
                if "structured output" in error_str or "extra data" in error_str:
                    logger.warning(
                        f"[UnifiedAgent] Structured output parsing failed, "
                        f"recovering with last known state: {e}"
                    )
                    # Use last captured state — tool results are preserved,
                    # only answerable/language are missing (use defaults)
                    result = last_state
                    result.setdefault("answerable", True)
                    result.setdefault("language", "")
                    break  # recovered, no retry needed

                last_err = e
                is_retryable = (
                    "tool_calls" in error_str
                    or "tool_call_id" in error_str
                    or "rate limit" in error_str
                    or "timeout" in error_str
                    or "server error" in error_str
                    or "500" in error_str
                    or "429" in error_str
                    or "503" in error_str
                )

                if is_retryable and attempt < max_retries:
                    wait = 2 ** (attempt - 1)  # 1s → 2s → 4s
                    logger.warning(
                        f"[UnifiedAgent] Retryable error (attempt {attempt}/{max_retries}), "
                        f"retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                    # Reset state for clean retry
                    state_snapshot = {
                        "messages": messages,
                        "attached_files": attached_files,
                        "active_capabilities": active_caps,
                        "db_dialect": self._get_db_dialect()
                        if self.enable_dbsphere
                        else "SQL",
                        "task_prompt": user_system_prompt or "",
                    }
                    continue
                else:
                    # Non-retryable or max retries exhausted
                    _log_messages_debug(
                        logger, e, messages, last_state.get("messages", [])
                    )
                    raise
        else:
            # All retries exhausted
            _log_messages_debug(
                logger, last_err, messages, last_state.get("messages", [])
            )
            raise last_err

        # Fallback: extract_context_info가 호출되지 않은 경우 원본 질의 사용
        if not (result.get("normalized_question") or "").strip():
            result["normalized_question"] = self._get_last_user_message(payload)

        # Verify agent result state (structured output, messages)
        msg_types = [type(m).__name__ for m in result.get("messages", [])]
        last_msgs = msg_types[-5:] if len(msg_types) > 5 else msg_types
        logger.debug(
            f"[UnifiedAgent] agent result - "
            f"language='{result.get('language', '')}', "
            f"answerable={result.get('answerable')}, "
            f"normalized_q='{(result.get('normalized_question') or '')[:30]}', "
            f"msg_count={len(msg_types)}, last_types={last_msgs}"
        )

        return result

    async def _emit_hitl_request(self, hitl_marker: Dict[str, Any]) -> None:
        """HITL interrupt 정보를 클라이언트로 발행 (socket.io event_emitter).

        클라이언트는 이 이벤트를 받아 ToolApprovalCard 모달을 띄우고 사용자
        결정을 받아 POST /api/v1/chats/{chat_id}/resume 로 응답한다.
        """
        try:
            await self.event_emitter(
                {
                    "type": "hitl_request",
                    "data": {
                        "thread_id": hitl_marker.get("thread_id"),
                        "chat_id": self.metadata.get("chat_id"),
                        "message_id": self.metadata.get("message_id"),
                        "interrupts": hitl_marker.get("interrupts", []),
                        # resume 시 같은 trace 의 같은 chain 으로 이어가도록.
                        "chain_run_id": hitl_marker.get("chain_run_id"),
                        "trace_id": hitl_marker.get("trace_id"),
                    },
                }
            )
            logger.warning(
                "[UnifiedAgent] HITL interrupt emitted (thread_id=%s, n=%d)",
                hitl_marker.get("thread_id"),
                len(hitl_marker.get("interrupts", [])),
            )
            # resume 작성 턴에서 GWS 활성 복원용으로 1턴 features 저장.
            _tid = hitl_marker.get("thread_id")
            if _tid:
                _HITL_RESUME_FEATURES[_tid] = self.metadata.get("features") or {}
                if len(_HITL_RESUME_FEATURES) > 200:
                    for _k in list(_HITL_RESUME_FEATURES)[:-100]:
                        _HITL_RESUME_FEATURES.pop(_k, None)
        except Exception as e:
            logger.error("[UnifiedAgent] event_emitter hitl_request failed: %s", e)

    @staticmethod
    async def _detect_hitl_interrupts(agent, config: dict) -> List[Dict[str, Any]]:
        """LangGraph 그래프 state 를 조회해 HITL interrupt 가 걸려있는지 확인.

        반환: interrupt 리스트 — 각 항목은 langgraph Interrupt.value (HITL
        middleware 가 만든 dict: {"action_requests": [...], "review_configs": [...]}).
        없으면 빈 리스트.
        """
        try:
            graph_state = await agent.aget_state(config)
        except Exception as e:
            logger.warning("[UnifiedAgent] aget_state failed: %s", e)
            return []

        interrupts: List[Dict[str, Any]] = []
        for task in graph_state.tasks or []:
            for itr in getattr(task, "interrupts", None) or []:
                val = getattr(itr, "value", None)
                if isinstance(val, dict):
                    interrupts.append(val)
                else:
                    interrupts.append({"value": str(val)})
        return interrupts

    def _check_chart_data(self, chart_data_list: List[Dict]) -> str:
        """Check chart data list status and return message for final answer prompt."""
        if not chart_data_list:
            return ""

        no_self_chart = (
            "The chart(s) will be displayed separately below your answer. "
            "Do NOT generate any charts in your text (no mermaid, ASCII, markdown tables as charts, or code block charts)."
        )

        messages = []
        has_success = False
        for chart_data in chart_data_list:
            status = chart_data.get("status")
            error_reason = chart_data.get("error_reason")
            requested = chart_data.get("requested_chart_type")
            used = chart_data.get("used_chart_type")

            if status in ("explicit_success", "auto_success"):
                chart_type = used or requested or "chart"
                messages.append(
                    f"A {chart_type} chart has already been generated and will be displayed to the user."
                )
                has_success = True

            elif status == "fallback_auto":
                if requested and used and requested != used:
                    reason_text = (
                        f"요청한 차트 유형('{requested}')은 데이터 구조상 생성할 수 없어 "
                        f"'{used}' 차트로 대체 시각화했습니다."
                    )
                    if error_reason:
                        reason_text += f" 사유: {error_reason}."
                    messages.append(reason_text)
                else:
                    chart_type = used or "chart"
                    messages.append(f"A {chart_type} chart has already been generated.")
                has_success = True

            elif status == "error":
                base = "차트 생성에 실패했습니다."
                if error_reason:
                    base += f" 사유: {error_reason}."
                messages.append(base)

        result = " ".join(messages)
        if has_success:
            result += f" {no_self_chart}"
        return result

    @staticmethod
    def _extract_language_from_output(messages: list) -> str:
        """Extract language from UnifiedAgentOutput in the last ToolMessage.

        Parses 'language=' from Pydantic repr or JSON format.
        Returns empty string if not found.
        """
        for msg in reversed(messages):
            if not isinstance(msg, ToolMessage):
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                continue

            # Try Pydantic repr: UnifiedAgentOutput(answerable=True, language='English')
            lang_idx = content.find("language=")
            if lang_idx != -1:
                value_str = content[lang_idx + len("language=") :].strip()
                # Find end of value (comma or closing paren)
                for end_char in (",", ")"):
                    end_idx = value_str.find(end_char)
                    if end_idx != -1:
                        value_str = value_str[:end_idx].strip()
                        break
                try:
                    return ast.literal_eval(value_str)
                except (ValueError, SyntaxError):
                    return value_str.strip("'\"")

            # Try JSON format
            try:
                json_start = content.find("{")
                if json_start != -1:
                    data = json.loads(content[json_start:])
                    if isinstance(data, dict) and "language" in data:
                        return data["language"]
            except (json.JSONDecodeError, ValueError):
                pass

        return ""

    @staticmethod
    def _detect_language_from_text(text: str) -> str:
        """Detect language from text using langdetect, returning a full language name."""
        _LANG_CODE_MAP = {
            "ko": "Korean",
            "en": "English",
            "ja": "Japanese",
            "zh-cn": "Chinese",
            "zh-tw": "Chinese",
            "zh": "Chinese",
            "fr": "French",
            "de": "German",
            "es": "Spanish",
            "it": "Italian",
            "pt": "Portuguese",
            "ru": "Russian",
            "ar": "Arabic",
            "hi": "Hindi",
            "vi": "Vietnamese",
            "th": "Thai",
            "id": "Indonesian",
        }
        if not text or not text.strip():
            return "Korean"
        try:
            from langdetect import detect

            code = detect(text.strip()[:500])
            return _LANG_CODE_MAP.get(code, "Korean")
        except Exception:
            return "Korean"

    @staticmethod
    def _extract_structured_response(content: str) -> str:
        """Extract response text from LangGraph structured response ToolMessage.

        LangGraph produces ToolMessage with Python repr format:
            Returning structured response: UnifiedAgentOutput(response='...')

        Uses ast.literal_eval for safe, robust parsing that handles
        both single/double quotes and escaped characters.
        """
        # Find the response= field value
        resp_idx = content.find("response=")
        if resp_idx == -1:
            # Try JSON format as fallback
            try:
                json_start = content.find("{")
                if json_start != -1:
                    data = json.loads(content[json_start:])
                    if isinstance(data, dict) and "response" in data:
                        return data["response"]
            except (json.JSONDecodeError, ValueError):
                pass
            return ""

        # Extract the quoted string value
        value_str = content[resp_idx + len("response=") :].strip()
        # Strip trailing ) from Pydantic repr: UnifiedAgentOutput(response='...')
        if value_str.endswith(")"):
            value_str = value_str[:-1].strip()

        try:
            value = ast.literal_eval(value_str)
            return value if isinstance(value, str) else ""
        except (ValueError, SyntaxError):
            return ""

    # Built-in PII type names (used to distinguish from custom patterns)
    _BUILTIN_PII_TYPES = frozenset(
        {"email", "credit_card", "ip", "mac", "mac_address", "url", "api_key"}
    )

    @staticmethod
    def _detect_guardrail_markers(
        messages: List[Dict[str, Any]],
    ) -> str:
        """Detect guardrail redaction/mask/hash markers in messages.

        Returns a context string describing what was detected, or empty string.
        """
        import re

        markers = {
            "redacted": set(),  # [REDACTED_EMAIL], [BLOCKED]
            "masked": False,
            "hashed": set(),  # <email_hash:...>, <blocked_hash:...>
        }

        redact_pattern = re.compile(r"\[REDACTED_(\w+)\]|\[BLOCKED\]")
        hash_pattern = re.compile(r"<(\w+)_hash:[a-f0-9]+>")

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            for m in redact_pattern.finditer(content):
                matched = m.group(0)
                if matched == "[BLOCKED]":
                    markers["redacted"].add("blocked_word")
                else:
                    markers["redacted"].add(m.group(1).lower())

            for m in hash_pattern.finditer(content):
                markers["hashed"].add(m.group(1))

            # Mask patterns: ****@****.com, ****-****-****-1234, *.*.*. etc.
            if re.search(r"\*{3,}", content):
                markers["masked"] = True

        if not markers["redacted"] and not markers["masked"] and not markers["hashed"]:
            return ""

        parts = []
        if markers["redacted"]:
            types = ", ".join(sorted(markers["redacted"]))
            parts.append(f"Redacted: {types}")
        if markers["masked"]:
            parts.append("Some content has been masked")
        if markers["hashed"]:
            types = ", ".join(sorted(markers["hashed"]))
            parts.append(f"Hashed: {types}")

        return "; ".join(parts)

    @classmethod
    def _infer_detection_source(cls, guardrail_context: str) -> str:
        """Infer detection_source from guardrail context string.

        Returns "blocked_word", "custom_pattern", or "pii".
        """
        ctx_lower = guardrail_context.lower()
        if "blocked" in ctx_lower:
            return "blocked_word"

        # Extract redacted type names from context (e.g. "Redacted: 주민등록번호, email")
        import re

        redacted_match = re.search(r"Redacted:\s*(.+?)(?:;|$)", guardrail_context)
        if redacted_match:
            types = {t.strip().lower() for t in redacted_match.group(1).split(",")}
            # Remove blocked_word if present
            types.discard("blocked_word")
            if types:
                # If any type is NOT a built-in PII type → custom_pattern
                non_builtin = types - cls._BUILTIN_PII_TYPES
                if non_builtin:
                    return "custom_pattern"

        return "pii"

    def _get_effective_guardrail_ids(self) -> List[str]:
        """Get merged guardrail IDs from agent config + group + org + global (deduplicated)."""
        from open_webui.utils.guardrails import get_effective_guardrail_ids

        agent_ids = (
            list(self.agent_config.guardrail_ids)
            if self.agent_config and self.agent_config.has_guardrails()
            else []
        )
        user_id = self.metadata.get("user_id", "")

        return get_effective_guardrail_ids(
            user_id=user_id,
            request=self.request,
            source_guardrail_ids=agent_ids,
        )

    def _build_guardrail_context_from_middlewares(self) -> str:
        """Build guardrail context string from middleware violation data.

        Unlike _detect_guardrail_markers (which relies on text markers like
        [BLOCKED], [REDACTED_EMAIL]), this reads directly from middleware state,
        so it works for ALL strategies including mask (***).
        """
        types = self._collect_middleware_violation_types()
        if not types:
            return ""
        types_display = ", ".join(types)
        return f"Detected: {types_display}"

    def _collect_middleware_violation_types(self) -> List[str]:
        """Collect detected violation type names from guardrail middlewares.

        This captures type info that may be lost in mask/hash strategies
        (where markers like **** don't contain type names).
        """
        types: List[str] = []
        for mw in getattr(self, "_guardrail_middlewares", []):
            for vtype in getattr(mw, "detected_violation_types", []):
                if vtype not in types:
                    types.append(vtype)
        return types

    def _enrich_guardrail_context(
        self, marker_context: str, middleware_types: List[str]
    ) -> str:
        """Enrich guardrail context with middleware violation types.

        When mask/hash strategy is used, _detect_guardrail_markers only sees
        '****' or hashes without type info. This method merges type names
        collected from middleware processing to provide specific context.
        """
        if not middleware_types:
            return marker_context

        # Parse types already in marker_context (from redact strategy)
        import re

        existing_types: set = set()
        redacted_match = re.search(r"Redacted:\s*(.+?)(?:;|$)", marker_context)
        if redacted_match:
            existing_types = {
                t.strip().lower() for t in redacted_match.group(1).split(",")
            }

        # Find new types from middleware not already in marker context
        new_types = [t for t in middleware_types if t.lower() not in existing_types]

        if not new_types:
            return marker_context

        # Add detected types info to context
        types_str = ", ".join(new_types)
        if marker_context:
            return f"{marker_context}; Detected types: {types_str}"
        return f"Detected types: {types_str}"

    def _get_last_user_message(self, payload: dict) -> str:
        """payload에서 마지막 user 메시지 텍스트 추출."""
        messages = payload.get("messages", [])
        for msg in reversed(messages):
            role = msg.get("role", "")
            if role != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, str):
                        parts.append(part)
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                return " ".join(parts)
        return ""

    async def _load_selective_memories(self, user_id: str, payload: dict) -> str:
        """Load relevant memories via vector search when memory count is high.

        Uses the last user message as search query to find semantically
        relevant memories. Falls back to recency-based if search fails.
        """
        from open_webui.models.memories import Memories
        from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

        query = self._get_last_user_message(payload) or ""
        if not query:
            logger.info("[UnifiedAgent] No user message for memory search")
            return ""

        collection_name = f"user-memory-{user_id}"

        try:
            embedding = await self.request.app.state.EMBEDDING_FUNCTION(query)
            results = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=[embedding],
                limit=MEMORY_SEARCH_TOP_K,
            )
        except Exception as e:
            logger.warning(f"[UnifiedAgent] Memory vector search failed: {e}")
            # Fallback: load most recent memories up to top-k
            memories = Memories.get_memories_by_user_id(user_id)
            if memories:
                memories.sort(key=lambda m: m.updated_at, reverse=True)
                return self._format_memories(memories[:MEMORY_SEARCH_TOP_K])
            return ""

        if not results or not results.ids or not results.ids[0]:
            logger.info("[UnifiedAgent] Memory vector search returned no results")
            return ""

        # Fetch full memory records by IDs from search results
        memory_ids = results.ids[0]
        memories = []
        for mid in memory_ids:
            mem = Memories.get_memory_by_id(mid)
            if mem and mem.source != "profile":
                memories.append(mem)

        if not memories:
            return ""

        # Entity-based search boost
        try:
            from open_webui.models.memory_entity import MemoryEntities

            query_entities = MemoryEntities.find_matching_entities(user_id, query)
            if query_entities:
                query_entity_names = {e.name for e in query_entities}
                # Load all user entities once (avoid N+1)
                all_entities = MemoryEntities.get_entities_by_user_id(user_id)
                entity_by_memory: dict[str, set] = {}
                for e in all_entities:
                    entity_by_memory.setdefault(e.memory_id, set()).add(e.name)

                # Partition into boosted and non-boosted
                boosted = []
                rest = []
                for mem in memories:
                    mem_entity_names = entity_by_memory.get(mem.id, set())
                    if mem_entity_names & query_entity_names:
                        boosted.append(mem)
                    else:
                        rest.append(mem)
                memories = boosted + rest
                if boosted:
                    logger.info(
                        f"[UnifiedAgent] Entity boost: {len(boosted)} memories boosted"
                    )
        except Exception as e:
            logger.debug(f"[UnifiedAgent] Entity boost skipped: {e}")

        formatted = self._format_memories(memories)
        logger.info(
            f"[UnifiedAgent] Memory selective: "
            f"{len(memories)}/{MEMORY_SEARCH_TOP_K} relevant entries"
        )
        return formatted

    @staticmethod
    def _format_memories(memories: list) -> str:
        """Format memory list as numbered lines with dates."""
        from datetime import datetime

        lines = []
        for i, mem in enumerate(memories, 1):
            date_str = datetime.fromtimestamp(mem.created_at).strftime("%Y-%m-%d")
            lines.append(f"{i}. [{date_str}] {mem.content}")
        return "\n".join(lines)

    @staticmethod
    def _infer_guardrail_action(guardrail_context: str) -> str:
        """마커 문자열에서 action 추론 (mask/hash/redact)."""
        ctx_lower = guardrail_context.lower()
        if "masked" in ctx_lower or "mask" in ctx_lower:
            return "mask"
        if "hashed" in ctx_lower or "hash" in ctx_lower:
            return "hash"
        return "redact"

    def _log_guardrail_event(
        self,
        action: str,
        detection_source: str,
        detection_detail: str,
        guardrail_name: str = "",
        original_content: str = "",
        processed_content: str = "",
    ):
        """가드레일 이벤트 로그 저장 (fire-and-forget, 에러 시 warning만)."""
        try:
            from open_webui.models.guardrail_log import (
                GuardrailLogCreateForm,
                GuardrailLogs,
            )

            user_id = self.metadata.get("user_id")
            user_email = ""
            user_name = ""

            if user_id:
                user = Users.get_user_by_id(user_id)
                if user:
                    user_email = user.email or ""
                    user_name = user.name or ""

            # Resolve guardrail_id from agent_config
            guardrail_id = ""
            if self.agent_config and hasattr(self.agent_config, "guardrail_ids"):
                ids = self.agent_config.guardrail_ids or []
                if ids:
                    guardrail_id = ids[0]

            GuardrailLogs.insert_guardrail_log(
                GuardrailLogCreateForm(
                    user_id=user_id,
                    user_email=user_email,
                    user_name=user_name,
                    chat_id=self.metadata.get("chat_id"),
                    message_id=self.metadata.get("message_id"),
                    guardrail_id=guardrail_id,
                    guardrail_name=guardrail_name,
                    action=action,
                    detection_source=detection_source,
                    detection_detail=detection_detail,
                    original_content=original_content or "",
                    processed_content=processed_content or "",
                )
            )
        except Exception as exc:
            logger.warning(f"[UnifiedAgent] Failed to log guardrail event: {exc}")

        # --- MessageTrace 기록 ---
        # LLM Judge는 middleware에서 이미 추적하므로 제외
        if detection_source == "llm_judge":
            return

        try:
            from open_webui.models.message_trace import RunType
            from open_webui.utils.tracing import get_trace_context

            trace_context = get_trace_context(self.request)
            if trace_context and trace_context.enabled:
                with trace_context.start_run(
                    run_type=RunType.GUARDRAIL.value,
                    name=f"guardrail:{guardrail_name or detection_source}",
                    inputs={
                        "detection_source": detection_source,
                        "original_content": original_content[:200]
                        if original_content
                        else "",
                    },
                    push_stack=False,
                ) as run:
                    if run:
                        run.set_outputs(
                            {
                                "action": action,
                                "detection_detail": detection_detail,
                                "guardrail_name": guardrail_name,
                            }
                        )
        except Exception as exc:
            logger.debug(f"[UnifiedAgent] Failed to trace guardrail event: {exc}")

    def _input_pii_engines(self) -> List[Any]:
        """에이전트의 input PII redaction 엔진 목록 (prefetch 본문 redact 용)."""
        return [
            mw._engine
            for mw in (getattr(self, "_guardrail_middlewares", []) or [])
            if isinstance(mw, RuleBasedPIIMiddleware)
            and getattr(mw, "_apply_to_input", False)
        ]

    def _collect_upload_ids(self) -> List[str]:
        """현재 self.files 의 비-collection 업로드 파일 id (get_file_contents 대상과 동일).

        chat upload 본문은 metadata["files"]=self.files 에 있음 (message_info.file_ids
        는 이 경로에서 비어 있음). PR4 prefetch(option A/B)의 공통 트리거 소스.
        """
        return [
            f.get("id")
            for f in (getattr(self, "files", None) or [])
            if isinstance(f, dict) and f.get("type") != "collection" and f.get("id")
        ]

    async def _fetch_prefetch_sources(
        self, upload_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """업로드 본문을 읽어 size gate → input PII redact → 빈 파일 안내까지 적용 (option A/B 공통).

        순서 의존(redact 는 size gate 절단 후·빈 마킹 전). get_file_contents 실패/빈
        결과 시 [] 반환. 한 곳에 모아 두 prefetch 경로의 파이프라인 drift 를 방지한다.
        """
        try:
            prefetched = await self.get_file_contents(upload_ids)
        except Exception as e:
            logger.warning("[UnifiedAgent] prefetch get_file_contents failed: %s", e)
            return []
        sources = prefetched.get("sources", []) if isinstance(prefetched, dict) else []
        if not sources:
            return []
        sources = prefetch.apply_size_gate(sources)
        sources = prefetch.redact_pii(sources, self._input_pii_engines())
        sources = prefetch.mark_empty_sources(sources)
        return sources

    async def _inject_prefetched_files(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """현재 턴 업로드 파일 본문을 합성 tool 메시지로 추론 루프에 주입한다 (PR4 option B).

        get_file_contents 의 확률적 tool-call 을 결정적 코드 주입으로 대체하고, 무엇보다
        루프가 파일을 '보게' 하여 KB 검색으로 새지 않도록 한다(option A 의 KB 지배 결함 해소).
        sanitize 직후 호출(합성 tool 메시지가 strip 되지 않도록). 주입된 ToolMessage 는
        _run_stream 의 build_source_bundles 가 chat_upload bundle 로 수집 → uploaded_ctx.
        """
        upload_ids = self._collect_upload_ids()
        if not upload_ids:
            return messages
        sources = await self._fetch_prefetch_sources(upload_ids)
        if not sources:
            return messages
        tool_messages = prefetch.build_prefetch_tool_messages(sources)
        logger.info(
            "[UnifiedAgent] prefetched %d uploaded file(s) into agent loop (PR4)",
            len(upload_ids),
        )
        return list(messages) + tool_messages

    async def _prefetch_uploaded_files(
        self, source_bundles: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """현재 턴 업로드 파일을 source_bundles 에 merge 한다 (PR4 option A — _run_stream fallback).

        option B(_inject_prefetched_files)가 루프에 주입하면 이미 chat_upload bundle 이
        있어 file_id dedup 으로 여기서 skip — 주로 no-tools 경로(_run_agent 미호출)에서 동작.
        resume 재진입에도 안전(merge 가 local 이라 checkpointer state 미오염).
        """
        upload_ids = self._collect_upload_ids()
        if not upload_ids:
            return source_bundles
        missing = prefetch.compute_missing_file_ids(upload_ids, source_bundles)
        if not missing:
            return source_bundles
        sources = await self._fetch_prefetch_sources(missing)
        if not sources:
            return source_bundles
        prefetch.merge_prefetched_bundles(
            source_bundles, self._bundle_sources_by_provenance(sources)
        )
        logger.info(
            "[UnifiedAgent] prefetched %d uploaded file(s) via _run_stream fallback (PR4)",
            len(missing),
        )
        return source_bundles

    @staticmethod
    def _current_datetime_for_prompt() -> str:
        """Human-readable current date/time + IANA timezone for the system prompt.

        Lets the tool-calling LLM resolve relative dates ("내일"/tomorrow) instead
        of guessing. No per-user timezone is propagated yet, so we use
        ``AGENT_DEFAULT_TIMEZONE`` (default ``Asia/Seoul`` — the product locale);
        the user can always name another timezone explicitly.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        tz_name = os.environ.get("AGENT_DEFAULT_TIMEZONE", "Asia/Seoul")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz_name = "Asia/Seoul"
            tz = ZoneInfo(tz_name)
        return f"{datetime.now(tz).strftime('%Y-%m-%d (%a) %H:%M')}, timezone {tz_name}"

    async def _run_stream(
        self,
        agent_result: UnifiedAgentState,
        payload: Dict[str, Any],
        context: Dict[str, Any],
    ):
        """
        Generate unified streaming response.

        Output order:
        1. SQL query code block (DbSphere)
        2. Source events (KbSphere)
        3. LLM final answer streaming
        4. Chart JSON (DbSphere)
        5. Memory save (DbSphere)
        """
        model_name = payload.get("model")
        payload["stream_options"] = {"include_usage": True}
        active_caps = context.get("active_capabilities", [])

        # HITL interrupt 처리: _run_agent 가 마커를 박아두면 여기서 stream 을
        # 중단하고 사용자 결정을 기다린다 (POST /api/v1/chats/{chat_id}/resume).
        # 인터럽트 정보는 socket.io 채널의 hitl_request 이벤트로 전달되고,
        # SSE 자체는 표준 OpenAI chunk (finish_reason="stop") + [DONE] 으로 정상
        # 종료한다 — hitl_pending 같은 비표준 finish_reason 을 박으면 OpenAI
        # 호환 클라이언트가 깨질 수 있고, 어차피 hitl 신호는 socket 측에 있다.
        hitl_marker = (agent_result or {}).get("__hitl_interrupt__")
        if hitl_marker:
            # 첫 invocation 의 chain_run_id + trace_id 를 보존해서 hitl_marker 에
            # 박는다. 클라이언트가 resume 호출 시 그것을 다시 보내면 resume 흐름의
            # 새 _run_agent 가 같은 chain 의 child 로 이어가서 트레이스가 분리되지
            # 않는다. chain trace 자체는 close 하지 않고 'running' 으로 유지 — 진짜
            # close 는 resume 의 graph 정상 종료 시 aafter_agent 가 한다.
            if self._middleware:
                cid = getattr(self._middleware, "_chain_run_id", None)
                tid = getattr(self._middleware, "_trace_id", None)
                if cid:
                    hitl_marker["chain_run_id"] = cid
                if tid:
                    hitl_marker["trace_id"] = tid
                # ★ middleware._effective_run_stack 은 trace_context._run_stack 과
                # 동일 list 객체 (property 가 그대로 반환). chain_run_id 가 stack 에
                # 남아있으면 background_tasks_handler (title_generation, tags_generation,
                # post_processing) 가 trace_ctx.start_run_async 호출 시 그것을 parent
                # 로 보고 child 로 박혀버린다 — 트레이스 화면에서 chain 안에 task
                # 들이 잘못 들어가는 원인. SSE 종료 직전에 stack 에서 pop 해 root
                # 분리. resume 흐름의 _run_agent 가 다시 push.
                stack = getattr(self._middleware, "_effective_run_stack", None)
                if isinstance(stack, list) and cid:
                    while cid in stack:
                        stack.remove(cid)
            # 진행 중이던 LLM child run 만 닫는다 — 그 자체가 interrupt 로 끊긴
            # 단일 unit 이라 보존할 의미 적음.
            try:
                if self._middleware and getattr(
                    self._middleware, "_current_run_id", None
                ):
                    self._middleware._complete_trace_run(
                        self._middleware._current_run_id,
                        outputs={"status": "interrupted"},
                    )
                    self._middleware._current_run_id = None
            except Exception as e:
                logger.warning("[UnifiedAgent] HITL trace finalize failed: %s", e)

            await self._emit_hitl_request(hitl_marker)
            # 정상 종료 흐름과 동일하게 spinner 를 dismiss — 안 그러면 클라이언트
            # 의 chat-level loading 상태가 풀리지 않아 모달 떠있는 동안 progress
            # 인디케이터가 계속 돈다.
            try:
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": "Awaiting user approval",
                            "done": True,
                            "detail": "Awaiting user approval",
                        },
                    }
                )
            except Exception:
                pass
            # content/tool_calls 둘 다 빈 chunk → 헬퍼가 자동으로 finish_reason="stop"
            yield self._sse(openai_chat_chunk_message_template(model_name))
            yield "data: [DONE]\n\n"
            return

        # PR5: 현재 턴 신호 — self.files(=chatFiles 누적)에 업로드 파일이 있으면 True.
        # FE 가 채팅 누적 파일을 전송하고 PR4 가 매 턴 재주입하므로 "파일이 올라온
        # 채팅"이면 매 턴이 파일 컨텍스트 턴 (결정 A). 이 신호로 ad-hoc 업로드 질의에
        # 영구 format_prompt / cross-session memory 가 새지 않도록 게이트한다.
        has_chat_upload = bool(self._collect_upload_ids())
        if has_chat_upload:
            logger.info(
                "[UnifiedAgent] chat upload present (PR5) → cross-session memory "
                "suppressed; format_prompt gated by scope=%s",
                self.agent_config.format_prompt_scope if self.agent_config else None,
            )

        # Query user long-term memory (selective retrieval)
        # Full dump when < MEMORY_SELECTIVE_THRESHOLD, vector search top-k otherwise
        user_memory_context = ""
        user_id = self.metadata.get("user_id")
        memory_enabled = False
        if user_id:
            from open_webui.models.users import Users

            user_obj = Users.get_user_by_id(user_id)
            if user_obj and user_obj.settings:
                memory_enabled = (user_obj.settings.ui or {}).get("memory", False)

        if user_id and memory_enabled and not has_chat_upload:
            try:
                from open_webui.models.memories import Memories

                memory_count = Memories.get_memory_count_by_user_id(user_id)

                if 0 < memory_count < MEMORY_SELECTIVE_THRESHOLD:
                    # Few memories: full dump (existing behavior)
                    memories = Memories.get_memories_by_user_id(user_id)
                    if memories:
                        user_memory_context = self._format_memories(memories)
                        logger.info(
                            f"[UnifiedAgent] Memory full dump: {len(memories)} entries"
                        )

                elif memory_count >= MEMORY_SELECTIVE_THRESHOLD:
                    # Many memories: Profile + vector search top-k
                    profile = Memories.get_profile_by_user_id(user_id)
                    selective_facts = await self._load_selective_memories(
                        user_id, payload
                    )

                    parts = []
                    if profile:
                        parts.append(f"### Profile\n{profile.content}")
                    if selective_facts:
                        parts.append(f"### Relevant Context\n{selective_facts}")
                    user_memory_context = "\n\n".join(parts)

                    logger.info(
                        f"[UnifiedAgent] Memory selective: "
                        f"profile={'yes' if profile else 'no'}, "
                        f"facts={'yes' if selective_facts else 'no'}"
                    )

            except Exception as e:
                logger.warning(f"[UnifiedAgent] Failed to load user memory: {e}")
        else:
            if not user_id:
                logger.info("[UnifiedAgent] No user_id in metadata, skipping memory")

        # Load org memories and append to user_memory_context
        # PR5: 현재 턴 업로드 시 org memory(cross-session)도 억제 — user memory 와 동일 게이트.
        org_memory_context = ""
        if user_id and not has_chat_upload:
            try:
                from open_webui.internal.db import get_db
                from open_webui.models.memories import Memories
                from open_webui.models.organization import OrganizationalUnit
                from sqlalchemy import String, cast

                with get_db() as db:
                    unit = (
                        db.query(OrganizationalUnit)
                        .filter(
                            cast(OrganizationalUnit.member_ids, String).like(
                                f'%"{user_id}"%'
                            )
                        )
                        .first()
                    )
                    if unit:
                        org_memories = Memories.get_org_memories(unit.organization_id)
                        if org_memories:
                            org_lines = [
                                f"{i + 1}. {m.content}"
                                for i, m in enumerate(org_memories)
                            ]
                            org_memory_context = (
                                "\n### Organization Context\n" + "\n".join(org_lines)
                            )
                            logger.info(
                                f"[UnifiedAgent] Org memory loaded: "
                                f"{len(org_memories)} entries for org {unit.organization_id}"
                            )
            except Exception as e:
                logger.warning(f"[UnifiedAgent] Org memory load failed: {e}")

        if org_memory_context:
            user_memory_context += org_memory_context

        # Load conversation summary (adaptive compression)
        conversation_summary = ""
        chat_id = self.metadata.get("chat_id")
        if chat_id and user_id:
            try:
                from open_webui.models.chats import Chats

                chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
                if chat and chat.chat:
                    conversation_summary = (chat.chat or {}).get("summary", "")
            except Exception:
                pass

        # 1. SQL queries (available for memory save)
        query_history = agent_result.get("query_history", [])
        # Note: SQL display is controlled by the format_prompt, not hardcoded here

        # 2. Aggregate and emit sources (KbSphere)
        # PR3: split typed bundles. chat-upload 파일은 [i] 인덱스 없는 전용 섹션으로,
        # KB/web(citation-worthy) source 만 citation source event 로 emit 한다 —
        # 그래야 [i] 마커가 FE citation 리스트와 위치 정합(Source.svelte: [i]→citation[i-1]).
        source_bundles = self.build_source_bundles(agent_result)
        # PR4: 현재 턴 업로드 파일을 결정적으로 prefetch 주입 (tool-call 확률성 제거).
        source_bundles = await self._prefetch_uploaded_files(source_bundles)
        (
            source_ctx,
            uploaded_ctx,
            citation_events,
            has_citation_sources,
            has_uploaded_files,
        ) = split_source_contexts(source_bundles)
        bundle_count = sum(len(b) for b in source_bundles.values())

        for source_event in citation_events:
            await self.event_emitter({"type": "source", "data": source_event})

        # json_schema(structured output) → citation off (마커가 schema 를 깨뜨림).
        use_structured = bool(
            self.agent_config
            and self.agent_config.response_format
            and self.agent_config.response_format.type == "json_schema"
            and self.agent_config.response_format.json_schema
        )
        citation_mode = resolve_citation_mode(
            has_uploaded=has_uploaded_files,
            has_citation_sources=has_citation_sources,
            use_structured=use_structured,
        )

        logger.info(
            "[UnifiedAgent] sources=%d cited=%d uploaded=%s citation_mode=%s "
            "source_ctx_len=%d",
            bundle_count,
            len(citation_events),
            has_uploaded_files,
            citation_mode,
            len(source_ctx),
        )

        # 3. Build final answer prompt
        # Build curated SQL context: every successful run_sql query (SQL body +
        # result), in execution order — so final_answer knows the actual WHERE/
        # GROUP BY scope, not just the last result preview.
        # (llm_response is no longer extracted — structured output is just answerable: bool)
        sql_results = build_sql_results_context(agent_result.get("messages", []))

        chart_status = self._check_chart_data(agent_result.get("chart_data_list", []))

        # Extract glossary lookup results from tool messages
        glossary_context = ""
        if "glossary" in active_caps:
            glossary_entries = []
            for msg in agent_result.get("messages", []):
                if not isinstance(msg, ToolMessage):
                    continue
                # Check tool name first (most reliable)
                tool_name = getattr(msg, "name", "")
                content = getattr(msg, "content", "")
                if not isinstance(content, str):
                    continue
                if tool_name != "lookup_glossary_term" and (
                    '"found"' not in content or '"results"' not in content
                ):
                    continue
                # Try parsing as JSON (Pydantic model_dump_json)
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    # Try extracting JSON from Pydantic repr format
                    json_start = content.find("{")
                    if json_start == -1:
                        continue
                    try:
                        data = json.loads(content[json_start:])
                    except (json.JSONDecodeError, TypeError):
                        continue

                if data.get("found") and data.get("results"):
                    for entry in data["results"]:
                        term = entry.get("term", "")
                        desc = entry.get("description", "")
                        if term and desc:
                            line = f"- **{term}**: {desc}"
                            synonyms = entry.get("synonyms")
                            if synonyms:
                                line += f" (동의어: {', '.join(synonyms)})"
                            example = entry.get("example")
                            if example:
                                line += f"\n  예시: {example}"
                            glossary_entries.append(line)

            if glossary_entries:
                # Deduplicate by term
                seen = set()
                unique = []
                for entry in glossary_entries:
                    term_key = entry.split("**")[1] if "**" in entry else entry
                    if term_key not in seen:
                        seen.add(term_key)
                        unique.append(entry)
                glossary_context = "\n".join(unique)

        # Extract knowledge graph results from tool messages
        kg_context = ""
        kg_source_events: list[dict] = []
        if "knowledge_graph" in active_caps:
            _kg_tool_names = {
                "kg_resolve_term",
                "kg_search_concepts",
                "kg_neighbors",
                "kg_find_related_tables",
                "kg_explore_context",
                "kg_fetch_data",
                "kg_fetch_document",
                "kg_cypher",
            }
            kg_results = []
            for msg in agent_result.get("messages", []):
                if not isinstance(msg, ToolMessage):
                    continue
                tool_name = getattr(msg, "name", "")
                content = getattr(msg, "content", "")
                if (
                    tool_name in _kg_tool_names
                    and isinstance(content, str)
                    and content.strip()
                ):
                    # JSON with {"text": ..., "sources": [...]} → parse sources
                    display_text = content.strip()
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "text" in parsed:
                            display_text = parsed["text"]
                            for src in parsed.get("sources", []):
                                kg_source_events.append(src)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    kg_results.append(f"### {tool_name}\n{display_text}")
            if kg_results:
                kg_context = "\n\n".join(kg_results)

        # Emit KG source events to frontend (SQL buttons, KB citations)
        for src in kg_source_events:
            await self.event_emitter({"type": "source", "data": src})

        # Extract tool_connections results from tool messages
        tool_connections_context = ""
        tc_tool_names = {
            "list_tool_servers",
            "use_tool_server",  # legacy (phase 5 이전)
            "use_tool_server_read",
            "use_tool_server_write",
        }
        # active_caps 조건은 의도적으로 제거 — resume 흐름의 _prepare_context 가
        # _enable_tool_connections 시점과 어긋나면 active_caps 에 "tool_connections"
        # 가 안 들어올 수 있음. 도구 결과가 graph state 에 있으면 무조건 final_answer
        # 에 노출하는 게 안전.
        tc_results = []
        all_tool_msg_names = []
        for msg in agent_result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = getattr(msg, "name", "")
            all_tool_msg_names.append(tool_name)
            content = getattr(msg, "content", "")
            if (
                tool_name in tc_tool_names
                and isinstance(content, str)
                and content.strip()
            ):
                tc_results.append(f"[{tool_name}] {content}")
        if tc_results:
            tool_connections_context = "\n".join(tc_results)
        logger.debug(
            "[UnifiedAgent] tool_connections_context build: tc_results=%d ctx_len=%d",
            len(tc_results),
            len(tool_connections_context),
        )

        # Extract UI action tool results (fill_form_field, click_element 등)
        # 이 도구들은 embed widget 호스트 페이지와 통신해 payload 를 반환한다 (도메인 무관).
        # final_answer LLM 이 그 결과를 답변 근거로 활용할 수 있도록 컨텍스트로 승격.
        ui_action_context = ""
        _ui_action_tool_names = {
            "fill_form_field",
            "fill_form",
            "click_element",
            "read_form",
            "highlight_element",
            "navigate_to",
            "get_page_info",
        }
        ui_action_results: list[str] = []
        for msg in agent_result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = getattr(msg, "name", "")
            content = getattr(msg, "content", "")
            if (
                tool_name in _ui_action_tool_names
                and isinstance(content, str)
                and content.strip()
            ):
                ui_action_results.append(f"[{tool_name}] {content}")
        if ui_action_results:
            ui_action_context = "\n".join(ui_action_results)

        # Extract recent history tool results and merge with user memory context
        for msg in agent_result.get("messages", []):
            if (
                isinstance(msg, ToolMessage)
                and getattr(msg, "name", "") == "get_recent_history"
                and isinstance(getattr(msg, "content", ""), str)
            ):
                history_result = msg.content.strip()
                if history_result and "No " not in history_result[:10]:
                    if user_memory_context:
                        user_memory_context += (
                            f"\n\n## Retrieved Conversation History\n{history_result}"
                        )
                    else:
                        user_memory_context = (
                            f"## Retrieved Conversation History\n{history_result}"
                        )

        # Extract code_interpreter results from tool messages
        # Separate: Plotly JSON charts, base64 images, and text results
        code_interpreter_context = ""
        code_interpreter_images = []
        code_interpreter_plotly = []
        if "code_interpreter" in active_caps:
            from extension_modules.agent.code_interpreter_tool import (
                PLOTLY_JSON_MARKER,
            )

            ci_text_results = []
            for msg in agent_result.get("messages", []):
                if not isinstance(msg, ToolMessage):
                    continue
                tool_name = getattr(msg, "name", "")
                content = getattr(msg, "content", "")
                if (
                    tool_name == "code_interpreter"
                    and isinstance(content, str)
                    and content.strip()
                ):
                    for line in content.split("\n"):
                        if line.startswith(PLOTLY_JSON_MARKER):
                            # Extract Plotly JSON
                            plotly_json_str = line[len(PLOTLY_JSON_MARKER) :]
                            try:
                                code_interpreter_plotly.append(
                                    json.loads(plotly_json_str)
                                )
                            except json.JSONDecodeError:
                                ci_text_results.append(line)
                        elif line.startswith("![chart](data:image/png;base64,"):
                            code_interpreter_images.append(line)
                        else:
                            ci_text_results.append(line)
            if ci_text_results:
                code_interpreter_context = "\n".join(ci_text_results).strip()

        # Extract image generation results from tool messages
        image_generation_content = ""
        for msg in agent_result.get("messages", []):
            if (
                isinstance(msg, ToolMessage)
                and hasattr(msg, "content")
                and isinstance(msg.content, str)
                and "![Generated Image]" in msg.content
            ):
                image_generation_content = msg.content
                break

        # show_reasoning=detailed 커밋: 추론 과정을 done=true 로 한 번 더 emit 해 최종
        # 상태(접힘 pill)로 마감한다. ⚠️ 전용 side-channel(agent_reasoning) 이벤트로만
        # 보낸다 — SSE/message.content 에는 절대 넣지 않는다(content 는 OpenAI 호환
        # API·임베드 등 모든 소비자가 읽는 답변 본문이므로 오염 금지). brief/off 는
        # 윈도우 없음(brief 는 기존 status 표시). 예외는 가드한다.
        if (
            self.agent_config
            and self.agent_config.get_show_reasoning_level() == "detailed"
            and self._middleware is not None
        ):
            try:
                data = self._middleware.reasoning_data(done=True)
                if data is not None:
                    await self.event_emitter({"type": "agent_reasoning", "data": data})
            except Exception as e:
                logger.warning(f"[UnifiedAgent] show_reasoning commit failed: {e}")

        # Emit image content directly in stream (before final answer)
        if image_generation_content:
            yield self._sse(
                openai_chat_chunk_message_template(
                    model_name, content=image_generation_content + "\n\n"
                )
            )

        # Extract document generation results (create_pptx/docx/xlsx) — same pattern
        # as image. LLM 이 'I cannot generate files' 로 hallucination 해도 다운로드
        # 링크가 LLM 응답 전에 사용자에게 직접 스트림됨.
        from extension_modules.tools.document._common import DOCUMENT_TOOL_MARKER

        document_tool_links: list[str] = []  # final answer prompt 에 직접 박을 링크들
        for msg in agent_result.get("messages", []):
            if (
                isinstance(msg, ToolMessage)
                and hasattr(msg, "content")
                and isinstance(msg.content, str)
                and DOCUMENT_TOOL_MARKER in msg.content
            ):
                # 본문의 첫 줄에서 detection 마커(`[document_tool] 파일 생성 완료: `)
                # 만 떼어내고 나머지(`[파일명](url) (size KB)`)를 사용자에게 노출.
                # 그 뒤의 LLM 행동 지시 텍스트(`위 마크다운 링크를...`)는 LLM 전용.
                first_line = msg.content.split("\n", 1)[0]
                marker_prefix = f"{DOCUMENT_TOOL_MARKER}: "
                visible = (
                    first_line[len(marker_prefix) :]
                    if first_line.startswith(marker_prefix)
                    else first_line
                )
                yield self._sse(
                    openai_chat_chunk_message_template(
                        model_name, content=f"📎 다운로드: {visible}\n\n"
                    )
                )
                document_tool_links.append(visible)

        # Extract tool error payloads — any ToolMessage whose content is a JSON
        # object with an ``error`` field. Convention used by Google Workspace
        # tools (_format_error in inprocess/{gmail,calendar}.py) and safe to
        # apply universally: a tool that returns `{"error": "...", "message":
        # "..."}` is signalling an explicit, actionable failure (Gmail API
        # disabled, google_reauth_required, quota exceeded, ...). Surfacing
        # these in a dedicated section prevents the final-answer LLM from
        # collapsing them into a generic "no data / tool unavailable" reply.
        tool_errors_context = ""
        tool_error_lines: list[str] = []
        for msg in agent_result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                continue
            stripped = content.strip()
            if not stripped.startswith("{") or '"error"' not in stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except (ValueError, json.JSONDecodeError):
                continue
            # Require a TRUTHY error field — guards against tools that include
            # an explicit `error: null` / `error: ""` on success paths.
            if not isinstance(parsed, dict) or not parsed.get("error"):
                continue
            tool_name = getattr(msg, "name", "") or "<unknown>"
            tool_error_lines.append(f"[{tool_name}] {stripped}")
        if tool_error_lines:
            tool_errors_context = "\n".join(tool_error_lines)
            logger.info(
                "[UnifiedAgent] tool_errors_context: %d error(s) detected — %s",
                len(tool_error_lines),
                [line.split("]", 1)[0][1:] for line in tool_error_lines],
            )

        # Extract Google Workspace tool SUCCESS results (gmail_/calendar_/drive_)
        # into a dedicated gathered-data section. Mirror of tool_errors_context
        # but for successes: these tools return JSON payloads that otherwise have
        # NO path to the final answer — redacted_messages drops ToolMessages,
        # llm_response is "", and there is no KB/SQL/KG-style slot for them.
        # Without this the final-answer LLM never sees the fetched
        # emails/events/files and falls back to "no data / not activated" even
        # though the tool succeeded (see gmail_search returning real mail).
        google_results_context = ""
        google_result_lines: list[str] = []
        for msg in agent_result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = getattr(msg, "name", "") or ""
            if not tool_name.startswith(("gmail_", "calendar_", "drive_")):
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            stripped = content.strip()
            # Skip HITL confirmation markers — these are streamed VERBATIM into the
            # assistant content below (so the frontend renders the confirmation
            # card). Feeding them to the final-answer LLM instead makes it
            # paraphrase the draft into prose and the card never renders.
            if is_hitl_confirmation(stripped):
                continue
            # Skip error payloads — already surfaced via tool_errors_context above
            # (Google tools signal failures as {"error": "...", ...}).
            if stripped.startswith("{") and '"error"' in stripped:
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict) and parsed.get("error"):
                        continue
                except (ValueError, json.JSONDecodeError):
                    pass
            google_result_lines.append(f"[{tool_name}] {stripped}")
        if google_result_lines:
            # [T5/M1] 다건 종합 시 최종 답변 프롬프트 폭증 방지 — 누적 총량 budget.
            # 개별 결과는 이미 도구 레벨에서 self-cap (단건 ≤50k, gmail_get 본문+
            # 첨부 ≤100k, 배치 drive_get_contents/gmail_get_batch ≤200k) 이므로
            # 여기서 줄 단위 truncation 은 하지 않는다 (정당한 결과를 잘라 종합이
            # 부분 데이터로 진행되는 것을 막기 위해).  budget 은 도구 최대 self-cap
            # (200k) 보다 크게 잡아 단일 결과는 항상 통째로 통과, 누적만 bound.
            # 한계: budget(~300k≈수 개 문서) 초과의 "관련 자료 전부 종합" 은
            # map-reduce 요약이 필요하며 현 설계 범위 밖 (후속).
            _ctx_budget = int(
                os.environ.get("GOOGLE_RESULTS_CONTEXT_MAX_CHARS", "300000")
            )
            _kept: list[str] = []
            _used = 0
            _dropped = 0
            for _line in google_result_lines:
                if _kept and _used + len(_line) > _ctx_budget:
                    _dropped += 1
                    continue
                _kept.append(_line)
                _used += len(_line)
            if _dropped:
                _kept.append(
                    f"[note] {_dropped} additional Google result(s) omitted "
                    f"(context budget {_ctx_budget} chars exceeded). Narrow the "
                    "search or read fewer items."
                )
            google_results_context = "\n".join(_kept)
            logger.info(
                "[UnifiedAgent] google_results_context: %d result(s) "
                "(%d dropped, %d chars) — %s",
                len(google_result_lines),
                _dropped,
                _used,
                [line.split("]", 1)[0][1:] for line in google_result_lines],
            )

        # Extract language from structured output (UnifiedAgentOutput)
        detected_language = agent_result.get("language") or ""
        if not detected_language:
            detected_language = self._extract_language_from_output(
                agent_result.get("messages", [])
            )
        if not detected_language:
            # Fallback: detect language directly from the user's last message
            detected_language = self._detect_language_from_text(
                self._get_last_user_message(payload)
            )

        # Get format_prompt from agent_config.
        # PR5: 현재 턴에 chat upload 가 있으면 format_prompt_scope 로 적용 여부 결정
        # (fail-safe 기본 exclude_chat_uploads — ad-hoc 업로드 질의에 영구 포맷 미적용).
        # scope="always" 일 때만 업로드 턴에도 유지. format_prompt="" 면 prompts.py 가
        # 자동으로 기본 가이드라인으로 떨어진다(무수정).
        format_prompt = ""
        if self.agent_config:
            format_prompt = self.agent_config.effective_format_prompt(has_chat_upload)

        # Use redacted messages from agent result (guardrail middleware processed)
        # instead of original payload messages to prevent PII leakage
        redacted_messages = []
        for msg in agent_result.get("messages", []):
            if isinstance(msg, HumanMessage):
                redacted_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage) and not msg.tool_calls:
                redacted_messages.append({"role": "assistant", "content": msg.content})

        # Detect guardrail-processed content for final answer context.
        # Only check the LAST user message (current turn) to avoid false
        # positives from markers left in chat history by previous turns.
        last_user_msgs = [m for m in redacted_messages if m["role"] == "user"]
        current_turn_msgs = [last_user_msgs[-1]] if last_user_msgs else []
        guardrail_context = self._detect_guardrail_markers(current_turn_msgs)

        # Enrich with middleware violation types (mask/hash may lose type in markers)
        mw_violation_types = self._collect_middleware_violation_types()
        if guardrail_context or mw_violation_types:
            guardrail_context = self._enrich_guardrail_context(
                guardrail_context, mw_violation_types
            )

        # Merge pre-agent guardrail context (from input check before agent run)
        pre_ctx = getattr(self, "_pre_agent_guardrail_context", "")
        if pre_ctx:
            if guardrail_context:
                guardrail_context = f"{guardrail_context}; {pre_ctx}"
            else:
                guardrail_context = pre_ctx

        if guardrail_context:
            inferred_action = self._infer_guardrail_action(guardrail_context)
            det_source = self._infer_detection_source(guardrail_context)
            self._log_guardrail_event(
                action=inferred_action,
                detection_source=det_source,
                detection_detail=guardrail_context,
                original_content=self._get_last_user_message(payload),
            )

        # Fallback: if normalized_question is empty, extract from payload
        # When guardrail processed (PII redact/mask), use redacted messages
        # to prevent original PII leaking into the final answer prompt.
        normalized_q = agent_result.get("normalized_question") or ""
        if not normalized_q.strip():
            if guardrail_context and redacted_messages:
                user_msgs = [
                    m["content"] for m in redacted_messages if m["role"] == "user"
                ]
                raw_content = user_msgs[-1] if user_msgs else ""
                # Extract text-only (content may be multipart list with images)
                if isinstance(raw_content, list):
                    text_parts = []
                    for block in raw_content:
                        if isinstance(block, str):
                            text_parts.append(block)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    normalized_q = " ".join(text_parts)
                else:
                    normalized_q = raw_content
            else:
                normalized_q = self._get_last_user_message(payload) or ""

        final_prompt = get_unified_final_answer_prompt(
            sources_context=source_ctx,
            uploaded_files_context=uploaded_ctx,
            citation_mode=citation_mode,
            llm_response="",  # Agent output is just answerable: bool, no text analysis
            sql_results=sql_results if "dbsphere" in active_caps else "",
            chart_status_message=chart_status,
            image_generation_content=image_generation_content,
            document_tool_links=document_tool_links,
            normalized_question=normalized_q,
            language=detected_language,
            messages=redacted_messages,
            active_capabilities=active_caps,
            format_prompt=format_prompt,
            guardrail_context=guardrail_context,
            glossary_context=glossary_context,
            tool_connections_context=tool_connections_context,
            ui_action_context=ui_action_context,
            user_memory_context=user_memory_context,
            conversation_summary=conversation_summary,
            code_interpreter_context=code_interpreter_context,
            kg_context=kg_context,
            tool_errors_context=tool_errors_context,
            google_results_context=google_results_context,
            unavailable_capabilities=context.get("unavailable_capabilities", []),
            # 엄격 근거 준수(grounding) 토글. off 면 연결 소스 부족 시 일반 지식으로
            # 보완(거부 안 함). 미설정/legacy 는 기존 동작 유지 위해 True.
            grounding_enabled=(
                self.agent_config.is_grounding_enabled() if self.agent_config else True
            ),
            # Include image blocks from user messages so the final answer LLM
            # can see uploaded images (vision capability).
            include_images=True,
        )

        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Generating final answer...",
                    "done": False,
                    "detail": "Generating final answer...",
                },
            }
        )

        # Usage tracking helper
        _MAX_PREVIEW = 1000

        async def insert_usage(usage: dict):
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            # Enrich with conversation preview for conversation logs
            enriched = dict(usage) if usage else {}
            if normalized_q:
                enriched["request_summary"] = {
                    "input_preview": normalized_q[:500],
                    "message_count": len(payload.get("messages", [])),
                }
            output_text = "".join(self._full_response_parts)
            if output_text:
                enriched["output_preview"] = output_text[:_MAX_PREVIEW]
            if self.metadata.get("client_type"):
                enriched["client_type"] = self.metadata["client_type"]

            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: Usages.insert_new_usage(
                    user_id=self.metadata.get("user_id"),
                    chat_id=self.metadata.get("chat_id"),
                    agent_id=agent_id,
                    model_id=model_name,
                    message_id=self.metadata.get("message_id"),
                    message_type=UsageMessageType.GENERATION,
                    total_tokens=usage.get("total_tokens"),
                    usage=enriched,
                ),
            )

        # 4. Stream LLM final answer (with tracing)
        #
        # The entire streaming + post-processing block is wrapped in try/finally.
        # When the middleware finishes consuming the stream (natural end or break
        # for code_interpreter), it calls aclose() on the generator. This sends
        # GeneratorExit, and the finally block ensures cleanup always runs
        # (trace completion + spinner dismiss).
        self._final_answer_run_id = None
        self._full_response_parts = []
        self._final_token_usage = None
        self._stream_finalized = False

        if hasattr(self, "_middleware") and self._middleware:
            # Extract system prompt from final_prompt for tracing
            final_system_prompt = None
            for msg in final_prompt:
                if hasattr(msg, "type") and msg.type == "system":
                    content = msg.content if hasattr(msg, "content") else str(msg)
                    final_system_prompt = content
                    break

            self._final_answer_run_id = self._middleware.start_trace_run(
                run_type=RunType.LLM.value,
                name="final_answer",
                inputs={
                    "system_prompt": final_system_prompt,
                    "normalized_question": agent_result.get("normalized_question", ""),
                    "active_capabilities": active_caps,
                },
                model_id=model_name,
            )
            # source 정보를 _finalize_stream에서 outputs에 포함하기 위해 저장
            self._source_trace_info = {
                "sources_count": bundle_count,
                "source_ctx_len": len(source_ctx),
                "citation_mode": citation_mode,
                # PR6: source_type 별 count (chat_upload vs knowledge_base vs web …) —
                # 트레이스/대시보드가 업로드 기반 턴과 RAG 턴을 segment 할 수 있게.
                "source_type_counts": {
                    st: len(bundles) for st, bundles in source_bundles.items()
                },
                "source_names": [
                    b.get("display_name", "?")
                    for bundles in source_bundles.values()
                    for b in bundles
                ],
            }

        # HITL confirmation cards (gmail_send / calendar_create_event /
        # drive_create_doc): the tool returned a ``[*_confirmation_required]``
        # marker block instead of performing the write. Stream that block VERBATIM
        # into the assistant content so the frontend ContentRenderer renders the
        # confirmation card (Create/Cancel buttons + the HMAC message_id needed to
        # confirm). The card IS the response, so we short-circuit the final-answer
        # LLM — avoids a duplicate prose preview and a wasted model call. Mirrors
        # the image / document direct-stream paths above.
        # NOTE: use_structured 는 PR3 에서 이미 위(citation_mode 산출 직전)에서 계산됨
        # — 여기 중복 계산 제거(merge).
        hitl_confirmation_content = extract_hitl_confirmation_content(
            agent_result.get("messages", [])
        )

        try:
            # === Streaming loop ===
            if hitl_confirmation_content:
                ack = hitl_ack_message(detected_language)
                # Stream ack + verbatim marker block to the client (frontend turns
                # the marker into a card). Keep only the human-readable ack in
                # _full_response_parts — the raw marker JSON is structural, not
                # answer text (used for usage/eval/memory previews).
                self._full_response_parts.append(ack)
                yield self._sse(
                    openai_chat_chunk_message_template(
                        model_name,
                        content=f"{ack}\n\n{hitl_confirmation_content}",
                    )
                )
            elif use_structured:
                # --- 구조화 응답: ainvoke + JSON 단일 청크 ---
                try:
                    PydanticModel = _build_pydantic_from_response_format(
                        self.agent_config.response_format.json_schema
                    )
                    structured_chain = self._create_llm(
                        payload, stream=False
                    ).with_structured_output(PydanticModel, include_raw=True)
                    result = await structured_chain.ainvoke(final_prompt)

                    # usage 처리 (include_raw=True → raw AIMessage에 usage_metadata 포함)
                    raw_msg = result.get("raw")
                    if raw_msg and raw_msg.usage_metadata:
                        self._final_token_usage = raw_msg.usage_metadata
                        try:
                            await insert_usage(raw_msg.usage_metadata)
                        except Exception as e:
                            logger.warning(
                                f"[UnifiedAgent] Failed to insert usage: {e}"
                            )

                    # JSON 직렬화 → 단일 청크 전송
                    parsed = result.get("parsed")
                    if parsed:
                        json_str = parsed.model_dump_json(indent=2)
                        self._full_response_parts.append(json_str)
                        yield self._sse(
                            openai_chat_chunk_message_template(
                                model_name, content=json_str
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"[UnifiedAgent] Structured output failed: {e}",
                        exc_info=True,
                    )
                    yield self._sse(
                        openai_chat_chunk_message_template(
                            model_name,
                            content=f"\u26a0\ufe0f 구조화 응답 생성 중 오류가 발생했습니다: {e}",
                        )
                    )
            else:
                # --- 일반 응답 ---
                # 출력 가드레일이 있으면 버퍼링 모드 (원문 노출 방지)
                has_output_guardrail = any(
                    getattr(mw, "_apply_to_output", False)
                    for mw in getattr(self, "_guardrail_middlewares", [])
                )

                try:
                    async for chunk in self._create_llm(payload, stream=True).astream(
                        final_prompt
                    ):
                        if chunk.usage_metadata:
                            self._final_token_usage = chunk.usage_metadata
                            try:
                                await insert_usage(chunk.usage_metadata)
                            except Exception as e:
                                logger.warning(
                                    f"[UnifiedAgent] Failed to insert usage: {e}"
                                )
                        piece = getattr(chunk, "content", "")
                        # Gemini/Vertex AI returns list of content blocks
                        if isinstance(piece, list):
                            piece = "".join(
                                block.get("text", "")
                                if isinstance(block, dict)
                                else str(block)
                                for block in piece
                            )
                        if isinstance(piece, str) and piece:
                            self._full_response_parts.append(piece)
                            if not has_output_guardrail:
                                yield self._sse(
                                    openai_chat_chunk_message_template(
                                        model_name, content=piece
                                    )
                                )

                    # 버퍼링 모드: 가드레일 체크 후 한 번에 전송
                    if has_output_guardrail:
                        guardrail_replacement = await self._apply_output_guardrails()
                        final_content = (
                            guardrail_replacement
                            if guardrail_replacement is not None
                            else "".join(self._full_response_parts)
                        )
                        yield self._sse(
                            openai_chat_chunk_message_template(
                                model_name, content=final_content
                            )
                        )

                except Exception as e:
                    logger.error(
                        f"[UnifiedAgent] Error during final answer streaming: {e}",
                        exc_info=True,
                    )
                    # Yield error to user so they don't see empty response
                    yield self._sse(
                        openai_chat_chunk_message_template(
                            model_name,
                            content=f"\u26a0\ufe0f 응답 생성 중 오류가 발생했습니다: {e}",
                        )
                    )

            # === Post-streaming (runs when generator completes normally) ===
            # If middleware called aclose() (code_interpreter break), GeneratorExit
            # is raised and we skip directly to the finally block.

            # 4.5. Output code_interpreter charts (Plotly JSON or base64 images)
            if code_interpreter_plotly:
                # Reuse DbSphere chart rendering: [[dbsphere:chart]] marker
                chart_content = f"\n\n[[dbsphere:chart]]\n```json\n{json.dumps(_nan_safe(code_interpreter_plotly))}\n```\n\n"
                self._full_response_parts.append(chart_content)
                yield self._sse(
                    openai_chat_chunk_message_template(
                        model_name, content=chart_content
                    )
                )
            elif code_interpreter_images:
                # Fallback: base64 PNG images as markdown
                img_content = "\n\n" + "\n".join(code_interpreter_images) + "\n\n"
                self._full_response_parts.append(img_content)
                yield self._sse(
                    openai_chat_chunk_message_template(model_name, content=img_content)
                )

            # 5. Output chart data if available (DbSphere)
            chart_data_list = agent_result.get("chart_data_list", [])
            if chart_data_list:
                charts_json = []
                for chart_data in chart_data_list:
                    chart_result = chart_data.get("chart_result", {})
                    charts_json.append(chart_result)
                chart_content = f"\n\n[[dbsphere:chart]]\n```json\n{json.dumps(_nan_safe(charts_json))}\n```\n\n"
                self._full_response_parts.append(chart_content)
                yield self._sse(
                    openai_chat_chunk_message_template(
                        model_name, content=chart_content
                    )
                )

            # 5.1. Emit query execution events (DbSphere SQL results)
            query_history = agent_result.get("query_history", [])
            if query_history and chart_data_list:
                for i, sql in enumerate(query_history):
                    chart_result = (
                        chart_data_list[i].get("chart_result", {})
                        if i < len(chart_data_list)
                        else {}
                    )
                    await self.event_emitter(
                        {
                            "type": "source",
                            "data": {
                                "type": "query_execution",
                                "id": f"query-{i}",
                                "name": f"SQL Query {i + 1}",
                                "sql": sql,
                                "result": {
                                    "columns": chart_result.get("columns", []),
                                    "data": chart_result.get("data", [])[:100],
                                    "total_rows": len(chart_result.get("data", [])),
                                },
                            },
                        }
                    )
            elif query_history:
                # SQL은 있지만 차트 데이터가 없는 경우 (빈 결과 등)
                for i, sql in enumerate(query_history):
                    await self.event_emitter(
                        {
                            "type": "source",
                            "data": {
                                "type": "query_execution",
                                "id": f"query-{i}",
                                "name": f"SQL Query {i + 1}",
                                "sql": sql,
                                "result": None,
                            },
                        }
                    )

            # 5.5. Apply output guardrails (streaming mode only)
            # In buffered mode (has_output_guardrail), guardrails are already applied
            # above before sending the response. This handles the streaming fallback.
            if not use_structured and not any(
                getattr(mw, "_apply_to_output", False)
                for mw in getattr(self, "_guardrail_middlewares", [])
            ):
                guardrail_replacement = await self._apply_output_guardrails()
                if guardrail_replacement is not None:
                    await self.event_emitter(
                        {
                            "type": "replace",
                            "data": {"content": guardrail_replacement},
                        }
                    )

            # 6. Finalize final_answer trace BEFORE memory save
            # so that embedding traces don't appear under final_answer
            await self._finalize_stream()

            # 7. Save final SQL query to memory (DbSphere)
            # Only save the last query (the one that actually answered the question).
            # Intermediate queries (schema exploration, data sampling) are excluded.
            if self.dbsphere_registry and query_history:
                try:
                    normalized_question = (
                        agent_result.get("normalized_question")
                        or self._get_last_user_message(payload)
                        or ""
                    )
                    final_sql = query_history[-1]
                    # Route the save to the DB that executed the final SQL
                    # (multi-DB). Falls back to the first DB's memory.
                    target_id = (
                        agent_result.get("last_sql_dbsphere_id") or self.dbsphere_id
                    )
                    entry = self.dbsphere_registry.get(target_id) if target_id else None
                    target_memory = (
                        entry.get("memory") if entry else self.dbsphere_memory
                    )
                    if target_memory:
                        await target_memory.save_sql_memory(
                            question=normalized_question,
                            sql=final_sql,
                            success=True,
                            metadata={
                                "user_id": self.metadata.get("user_id"),
                                "chat_id": self.metadata.get("chat_id"),
                                "origin": "llm_auto",  # 에이전트 자동저장
                            },
                        )
                except Exception as e:
                    logger.warning(
                        f"[UnifiedAgent] Failed to save query to memory: {e}"
                    )

            # 8. Trigger auto-evaluation (non-blocking background task)
            if self.agent_config and self.agent_config.auto_evaluation:
                try:
                    from extension_modules.auto_evaluation.trigger import (
                        should_evaluate,
                        trigger_auto_evaluations,
                    )

                    if should_evaluate(self.agent_config.auto_evaluation):
                        # Use raw (pre-grouping) sources for richer evaluation context.
                        # _raw_sources 는 build_source_bundles → _collect_sources_from_result
                        # 부수효과로 이미 설정됨(단일 write).
                        raw = getattr(self, "_raw_sources", None)
                        eval_contexts = raw if raw else None
                        full_response = "".join(self._full_response_parts)
                        eval_query = agent_result.get(
                            "normalized_question"
                        ) or self._get_last_user_message(payload)

                        # Get trace_id from middleware for shared tracing
                        eval_trace_id = None
                        if hasattr(self, "_middleware") and self._middleware:
                            eval_trace_id = getattr(self._middleware, "_trace_id", None)

                        trigger_auto_evaluations(
                            app=self.request.app,
                            auto_eval_config=self.agent_config.auto_evaluation,
                            user_id=self.metadata.get("user_id", ""),
                            chat_id=self.metadata.get("chat_id", ""),
                            message_id=self.metadata.get("message_id", ""),
                            model_id=self.agent_config.model_id or model_name,
                            user_query=eval_query,
                            assistant_response=full_response,
                            retrieved_contexts=eval_contexts,
                            trace_id=eval_trace_id,
                        )
                except Exception as e:
                    logger.warning(
                        f"[UnifiedAgent] Auto-evaluation trigger failed: {e}"
                    )

            # 9. Trigger auto memory extraction (non-blocking background task)
            if memory_enabled and redacted_messages:
                try:
                    from extension_modules.agent.memory_extractor import (
                        auto_extract_memories,
                    )

                    llm_config = self._build_extraction_llm_config(payload)
                    if llm_config and llm_config.get("model_id"):
                        asyncio.create_task(
                            auto_extract_memories(
                                user_id=self.metadata.get("user_id", ""),
                                messages=redacted_messages,
                                chat_id=self.metadata.get("chat_id", ""),
                                llm_config=llm_config,
                                app=self.request.app,
                            )
                        )
                    else:
                        logger.warning(
                            "[UnifiedAgent] Memory extraction skipped: no valid model configured"
                        )
                except Exception as e:
                    logger.warning(
                        f"[UnifiedAgent] Auto memory extraction trigger failed: {e}"
                    )

            # 10. Trigger conversation compression (non-blocking background task)
            # Uses full chat history from DB (not redacted_messages which is truncated)
            chat_id = self.metadata.get("chat_id")
            compress_user_id = self.metadata.get("user_id")
            if chat_id and compress_user_id:
                try:
                    from extension_modules.agent.message_compressor import (
                        auto_compress_history,
                    )
                    from open_webui.models.chats import Chats

                    chat_obj = Chats.get_chat_by_id_and_user_id(
                        chat_id, compress_user_id
                    )
                    if chat_obj and chat_obj.chat:
                        full_messages = (chat_obj.chat or {}).get("messages", [])
                        if full_messages:
                            compress_config = self._build_extraction_llm_config(payload)
                            if compress_config and compress_config.get("model_id"):
                                asyncio.create_task(
                                    auto_compress_history(
                                        chat_id=chat_id,
                                        user_id=compress_user_id,
                                        messages=full_messages,
                                        llm_config=compress_config,
                                    )
                                )
                except Exception as e:
                    logger.warning(f"[UnifiedAgent] Compression trigger failed: {e}")

        finally:
            # Always runs: on normal completion AND on GeneratorExit (aclose).
            # Handles trace completion + spinner dismiss. Idempotent.
            await self._finalize_stream()

    def _build_extraction_llm_config(self, payload: dict) -> dict:
        """Build LLM config for memory extraction with fallback chain.

        Priority: MEMORY_EXTRACTION_MODEL → TASK_MODEL → chat model
        """
        from extension_modules.utils.llm import get_model_config_from_app

        app = self.request.app
        chat_model_config = {
            "model_id": payload.get("model"),
            "api_key": self.api_key,
            "base_url": self.base_url,
            "api_config": self.api_config,
        }

        # Try MEMORY_EXTRACTION_MODEL first
        extraction_model = getattr(app.state.config, "MEMORY_EXTRACTION_MODEL", None)
        if extraction_model and str(extraction_model).strip():
            config = get_model_config_from_app(app, str(extraction_model).strip())
            if config:
                return config

        # Fallback to TASK_MODEL (external first, then default)
        for attr in ("TASK_MODEL_EXTERNAL", "TASK_MODEL"):
            model_id = getattr(app.state.config, attr, None)
            if model_id and str(model_id).strip():
                config = get_model_config_from_app(app, str(model_id).strip())
                if config:
                    return config

        # Final fallback: chat model
        return chat_model_config

    async def _apply_output_guardrails(self) -> str | None:
        """Apply output guardrails to the full response after streaming completes.

        Returns:
            None if passed, or replacement content string if blocked/redacted.
        """
        guardrail_mws = getattr(self, "_guardrail_middlewares", [])
        if not guardrail_mws:
            return None

        full_response = "".join(self._full_response_parts)
        if not full_response:
            return None

        state = {"messages": [AIMessage(content=full_response)]}
        try:
            for mw in guardrail_mws:
                update = await mw.aafter_model(state, runtime=None)
                if update:
                    state = {**state, **update}

            # Check if response was modified (redacted)
            modified_msg = state["messages"][-1]
            if modified_msg.content != full_response:
                self._full_response_parts = [modified_msg.content]
                # Log output redact trace
                mw_types = self._collect_middleware_violation_types()
                det_ctx = ", ".join(mw_types) if mw_types else "output_redacted"
                self._log_guardrail_event(
                    action="redact",
                    detection_source=(
                        "blocked_word"
                        if any("blocked" in t for t in mw_types)
                        else "pii"
                    ),
                    detection_detail=f"Output: {det_ctx}",
                    original_content=full_response[:500],
                )
                return modified_msg.content

        except GuardrailBlockedError as e:
            logger.warning(
                f"[UnifiedAgent] Output guardrail blocked: "
                f"name={e.guardrail_name}, reason={e.reason}"
            )
            reason_lower = e.reason.lower()
            if "blocked word" in reason_lower:
                det_source = "blocked_word"
            elif "pii" in reason_lower:
                det_source = "pii"
            else:
                det_source = "llm_judge"
            self._log_guardrail_event(
                action="block",
                detection_source=det_source,
                detection_detail=e.reason,
                guardrail_name=e.guardrail_name,
                original_content=full_response,
            )
            blocked_msg = (
                f"\u26a0\ufe0f 응답이 가드레일에 의해 차단되었습니다: {e.reason}"
            )
            self._full_response_parts = [blocked_msg]
            return blocked_msg

        return None

    async def _finalize_stream(self):
        """Run post-streaming cleanup (trace completion + spinner dismiss).

        Idempotent: safe to call multiple times (uses _stream_finalized flag).
        Called from:
        1. Normal flow: at the end of _run_stream generator
        2. Interrupted flow: via StreamingResponse.background (called by middleware
           after breaking out of the streaming loop for code_interpreter)
        """
        if getattr(self, "_stream_finalized", False):
            logger.debug("[UnifiedAgent] _finalize_stream already called, skipping")
            return
        self._stream_finalized = True
        logger.info("[UnifiedAgent] _finalize_stream running")

        # Complete trace
        try:
            run_id = getattr(self, "_final_answer_run_id", None)
            if run_id and hasattr(self, "_middleware") and self._middleware:
                full_response = "".join(getattr(self, "_full_response_parts", []))
                source_info = getattr(self, "_source_trace_info", {})
                self._middleware.complete_trace_run(
                    run_id,
                    outputs={
                        "response": full_response,
                        "response_length": len(full_response),
                        **source_info,
                    },
                    token_usage=getattr(self, "_final_token_usage", None),
                )
        except Exception as e:
            logger.warning(f"[UnifiedAgent] Trace completion failed: {e}")

        # Chain trace 정리 — aafter_agent (LangGraph) 가 정상 흐름에서 chain 을
        # close 하지만, HITL resume 흐름에서 우리가 chain_run_id 를 재사용+stack 에
        # push 한 경우 그것이 살아있어 background_tasks_handler (title/tags/post_processing)
        # trace 가 같은 chain 의 child 로 잘못 박힌다. 여기서 명시적으로 close +
        # stack 에서 제거해 background tasks 가 root level 로 박히도록.
        try:
            if self._middleware:
                cid = getattr(self._middleware, "_chain_run_id", None)
                if cid:
                    self._middleware._complete_trace_run(
                        cid,
                        outputs={"status": "completed"},
                    )
                    self._middleware._chain_run_id = None
                stack = getattr(self._middleware, "_effective_run_stack", None)
                if isinstance(stack, list):
                    # 우리 chain_run_id 가 stack 어디든 남아있으면 제거
                    while cid and cid in stack:
                        stack.remove(cid)
        except Exception as e:
            logger.warning("[UnifiedAgent] chain trace cleanup failed: %s", e)

        # Dismiss spinner
        try:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Task completed!",
                        "done": True,
                        "detail": "Task completed!",
                    },
                }
            )
        except Exception:
            pass

        # Cleanup SQL runner connections — close every DB in the registry.
        for did, entry in getattr(self, "dbsphere_registry", {}).items():
            runner = entry.get("runner")
            if runner:
                try:
                    await runner.close()
                except Exception as e:
                    logger.debug(
                        f"[UnifiedAgent] Failed to close SQL runner {did}: {e}"
                    )
        # Backward-compat: close the legacy single runner if it isn't in the
        # registry (e.g. single-DB paths that set sql_runner directly).
        runner = getattr(self, "sql_runner", None)
        if runner and runner not in [
            e.get("runner") for e in getattr(self, "dbsphere_registry", {}).values()
        ]:
            try:
                await runner.close()
            except Exception as e:
                logger.debug(f"[UnifiedAgent] Failed to close SQL runner: {e}")

    def _create_error_response(
        self,
        error_msg: str,
        model_name: str,
    ) -> StreamingResponse:
        """Create error streaming response."""

        async def error_generator():
            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=error_msg)
            )

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    async def run(
        self,
        *,
        request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
        run_flow: bool = False,
    ) -> StreamingResponse:
        """
        Run the UnifiedAgent.

        Args:
            request: FastAPI request
            payload: Request payload with messages and model settings
            metadata: Request metadata
            user: User object
            run_flow: If True, return dict instead of StreamingResponse

        Returns:
            StreamingResponse with agent results
        """
        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)
        self._user = user

        model_name = payload.get("model", "")

        # Prepare context (DbSphere pre-loading)
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Preparing context...",
                    "done": False,
                },
            }
        )

        messages, _ = self._extract_messages_and_prompt(payload)
        context = await self._prepare_context(messages)

        # Cache last user message for downstream tool managers
        # (KG tools save successful Q-SQL pairs to DbSphere memory)
        self._last_user_question = ""
        for _m in reversed(messages or []):
            if isinstance(_m, dict) and _m.get("role") == "user":
                _c = _m.get("content", "")
                if isinstance(_c, str):
                    self._last_user_question = _c
                elif isinstance(_c, list):
                    self._last_user_question = " ".join(
                        p.get("text", "")
                        for p in _c
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                break

        # Get tools
        self.tools = self.get_tools()

        # Skip agent phase if no tools (e.g., code_interpreter only)
        # Code interpreter is handled by middleware post-processing, not as an agent tool
        if not self.tools:
            logger.info(
                "[UnifiedAgent] No tools available - skipping agent phase, "
                "proceeding directly to final answer"
            )

            # Initialize middleware for tracing (even without agent phase)
            import uuid

            from open_webui.utils.tracing import get_trace_context

            trace_context = get_trace_context(self.request)
            middleware_metadata = {
                **self.metadata,
                "llm_model_id": payload.get("model"),
            }
            middleware = MiddlewareBase(
                self.event_emitter,
                self.event_call,
                middleware_metadata,
                trace_context=trace_context,
            )
            middleware._system_prompt = ""
            middleware._tool_descriptions = {}
            # Manually initialize trace_id (normally done in on_start lifecycle)
            if trace_context and trace_context.enabled:
                middleware._trace_id = trace_context.trace_id
            else:
                middleware._trace_id = str(uuid.uuid4())
            self._middleware = middleware
            middleware._show_reasoning_level = (
                self.agent_config.get_show_reasoning_level()
                if self.agent_config
                else "off"
            )

            # Apply guardrail middlewares to user input (even without agent phase)
            input_messages = self._to_langchain_messages(
                messages[-MAX_HISTORY_MESSAGES:], system_prompt=None
            )
            user_message = self._get_last_user_message(payload)
            if not input_messages:
                input_messages = [HumanMessage(content=user_message)]
            effective_ids = self._get_effective_guardrail_ids()
            if effective_ids:
                guardrail_mws = create_guardrail_middlewares(
                    effective_ids,
                    app=self.request.app,
                    metadata=self.metadata,
                    trace_context=trace_context,
                )
                self._guardrail_middlewares = guardrail_mws
                state = {"messages": input_messages}
                try:
                    for mw in guardrail_mws:
                        update = await mw.abefore_model(state, runtime=None)
                        if update:
                            state = {**state, **update}
                    input_messages = state.get("messages", input_messages)
                    # Sync redacted content back to payload
                    for msg in reversed(input_messages):
                        if isinstance(msg, HumanMessage) and msg.content:
                            payload_msgs = payload.get("messages", [])
                            if payload_msgs:
                                payload_msgs[-1]["content"] = msg.content
                            break
                    self._pre_agent_guardrail_context = (
                        self._build_guardrail_context_from_middlewares()
                    )
                    # Log redact/mask trace for input guardrail
                    if self._pre_agent_guardrail_context:
                        mw_types = self._collect_middleware_violation_types()
                        self._log_guardrail_event(
                            action="redact",
                            detection_source=(
                                "blocked_word"
                                if any("blocked" in t for t in mw_types)
                                else "pii"
                            ),
                            detection_detail=self._pre_agent_guardrail_context,
                            original_content=user_message,
                        )
                except GuardrailBlockedError as e:
                    logger.warning(
                        f"[UnifiedAgent] Guardrail blocked (no-tools path): "
                        f"name={e.guardrail_name}, reason={e.reason}"
                    )
                    reason_lower = e.reason.lower()
                    if "blocked word" in reason_lower:
                        det_source = "blocked_word"
                    elif "pii" in reason_lower:
                        det_source = "pii"
                    else:
                        det_source = "llm_judge"
                    self._log_guardrail_event(
                        action="block",
                        detection_source=det_source,
                        detection_detail=e.reason,
                        guardrail_name=e.guardrail_name,
                        original_content=user_message,
                    )
                    await self.event_emitter(
                        {
                            "type": "status",
                            "data": {
                                "description": "Guardrail blocked: {{detail}}",
                                "detail": e.guardrail_name,
                                "done": True,
                            },
                        }
                    )
                    return self._create_error_response(
                        f"\u26a0\ufe0f {e.reason}", payload.get("model", "")
                    )
                except PIIDetectionError as e:
                    logger.warning(
                        f"[UnifiedAgent] PII blocked (no-tools path): "
                        f"pii_type={e.pii_type}, matches={len(e.matches)}"
                    )
                    self._log_guardrail_event(
                        action="block",
                        detection_source="pii",
                        detection_detail=e.pii_type,
                        original_content=user_message,
                    )
                    await self.event_emitter(
                        {
                            "type": "status",
                            "data": {
                                "description": "PII detected: {{detail}}",
                                "detail": e.pii_type,
                                "done": True,
                            },
                        }
                    )
                    return self._create_error_response(
                        f"\u26a0\ufe0f PII detected ({e.pii_type})",
                        payload.get("model", ""),
                    )

            # Build minimal agent result for _run_stream
            result = {
                "messages": input_messages,
                "language": "",
                "answerable": True,
                "normalized_question": "",
                "query_history": [],
                "chart_data_list": [],
                "active_capabilities": context.get("active_capabilities", []),
                "skipped_agent": True,  # Flag: agent phase was skipped
            }
        else:
            # Pre-agent input guardrail check (before agent loop starts)
            effective_ids = self._get_effective_guardrail_ids()
            if effective_ids:
                from open_webui.utils.tracing import get_trace_context as _gtc

                _pre_agent_trace = _gtc(self.request)
                guardrail_mws = create_guardrail_middlewares(
                    effective_ids,
                    app=self.request.app,
                    metadata=self.metadata,
                    trace_context=_pre_agent_trace,
                )
                self._guardrail_middlewares = guardrail_mws
                user_message = self._get_last_user_message(payload)
                input_msgs = self._to_langchain_messages(
                    messages[-MAX_HISTORY_MESSAGES:], system_prompt=None
                )
                if not input_msgs:
                    input_msgs = [HumanMessage(content=user_message)]
                state = {"messages": input_msgs}
                try:
                    for mw in guardrail_mws:
                        update = await mw.abefore_model(state, runtime=None)
                        if update:
                            state = {**state, **update}
                    # Sync redacted content back to payload so _run_stream
                    # uses the sanitized message (not the original)
                    redacted_msgs = state.get("messages", input_msgs)
                    for msg in reversed(redacted_msgs):
                        if isinstance(msg, HumanMessage) and msg.content:
                            payload_msgs = payload.get("messages", [])
                            if payload_msgs:
                                payload_msgs[-1]["content"] = msg.content
                            break
                    # Collect violation info from middlewares so _run_stream
                    # can build guardrail_context even for mask (***) strategy
                    self._pre_agent_guardrail_context = (
                        self._build_guardrail_context_from_middlewares()
                    )
                    # Log redact/mask trace for input guardrail
                    if self._pre_agent_guardrail_context:
                        mw_types = self._collect_middleware_violation_types()
                        self._log_guardrail_event(
                            action="redact",
                            detection_source=(
                                "blocked_word"
                                if any("blocked" in t for t in mw_types)
                                else "pii"
                            ),
                            detection_detail=self._pre_agent_guardrail_context,
                            original_content=user_message,
                        )
                except GuardrailBlockedError as e:
                    logger.warning(
                        f"[UnifiedAgent] Guardrail blocked (pre-agent): "
                        f"name={e.guardrail_name}, reason={e.reason}"
                    )
                    reason_lower = e.reason.lower()
                    if "blocked word" in reason_lower:
                        det_source = "blocked_word"
                    elif "pii" in reason_lower:
                        det_source = "pii"
                    else:
                        det_source = "llm_judge"
                    self._log_guardrail_event(
                        action="block",
                        detection_source=det_source,
                        detection_detail=e.reason,
                        guardrail_name=e.guardrail_name,
                        original_content=user_message,
                    )
                    await self.event_emitter(
                        {
                            "type": "status",
                            "data": {
                                "description": "Guardrail blocked: {{detail}}",
                                "detail": e.guardrail_name,
                                "done": True,
                            },
                        }
                    )
                    return self._create_error_response(
                        f"\u26a0\ufe0f {e.reason}", payload.get("model", "")
                    )
                except PIIDetectionError as e:
                    logger.warning(
                        f"[UnifiedAgent] PII blocked (pre-agent): pii_type={e.pii_type}"
                    )
                    self._log_guardrail_event(
                        action="block",
                        detection_source="pii",
                        detection_detail=e.pii_type,
                        original_content=user_message,
                    )
                    return self._create_error_response(
                        f"\u26a0\ufe0f PII detected ({e.pii_type})",
                        payload.get("model", ""),
                    )

            # Run agent
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Processing your request...",
                        "done": False,
                    },
                }
            )

            try:
                result = await self._run_agent(
                    payload=payload,
                    tools=self.tools,
                    context=context,
                )
            except GuardrailBlockedError as e:
                logger.warning(
                    f"[UnifiedAgent] Guardrail blocked (GuardrailBlockedError): "
                    f"name={e.guardrail_name}, reason={e.reason}"
                )
                # Infer detection source from reason
                reason_lower = e.reason.lower()
                if "blocked word" in reason_lower:
                    det_source = "blocked_word"
                elif "pii" in reason_lower:
                    det_source = "pii"
                else:
                    det_source = "llm_judge"
                self._log_guardrail_event(
                    action="block",
                    detection_source=det_source,
                    detection_detail=e.reason,
                    guardrail_name=e.guardrail_name,
                    original_content=self._get_last_user_message(payload),
                )
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": "Guardrail blocked: {{detail}}",
                            "detail": e.guardrail_name,
                            "done": True,
                        },
                    }
                )
                return self._create_error_response(
                    f"\u26a0\ufe0f {e.reason}", model_name
                )
            except PIIDetectionError as e:
                logger.warning(
                    f"[UnifiedAgent] PII blocked (PIIDetectionError): "
                    f"pii_type={e.pii_type}, matches={len(e.matches)}"
                )
                self._log_guardrail_event(
                    action="block",
                    detection_source="pii",
                    detection_detail=e.pii_type,
                    original_content=self._get_last_user_message(payload),
                )
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": "PII detected: {{detail}}",
                            "detail": e.pii_type,
                            "done": True,
                        },
                    }
                )
                return self._create_error_response(
                    f"\u26a0\ufe0f Detected {e.pii_type} in content. "
                    "Please remove sensitive information and try again.",
                    model_name,
                )
            except Exception as e:
                logger.exception(f"[UnifiedAgent] Error in run: {e}")
                return self._create_error_response(
                    f"\u26a0\ufe0f Error processing request: {str(e)}", model_name
                )

        # Return results
        if run_flow:
            aggregated_sources = self.build_aggregated_sources_by_filename(result)
            return {
                "messages": result["messages"],
                "sources": aggregated_sources,
                "query_history": result.get("query_history", []),
                "chart_data_list": result.get("chart_data_list", []),
            }

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        return StreamingResponse(
            self._run_stream(result, payload, context),
            media_type="text/event-stream",
            headers=headers,
        )

    async def resume(
        self,
        *,
        request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
        thread_id: str,
        decisions: List[Dict[str, Any]],
        chain_run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> StreamingResponse:
        """이전에 HITL interrupt 로 멈춘 그래프를 사용자 결정으로 재개.

        Args:
            thread_id: interrupt 발생 시 클라이언트가 hitl_request 이벤트로
                받은 값 (UnifiedAgent 내부적으로 첫 attempt 의 message_id 와 동일).
            decisions: HITL 결정 리스트. 형식:
                [{"type": "approve"} | {"type": "edit", "edited_action": {...}} |
                 {"type": "reject", "message": "..."} | {"type": "respond", "message": "..."}]
                interrupt 의 action_requests 와 동일 순서.

        Returns:
            StreamingResponse — resume 한 그래프가 끝날 때까지의 SSE 스트림.
            도중에 다시 interrupt 가 걸리면 hitl_request 이벤트가 또 발행된다.
        """
        from langgraph.types import Command

        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)
        self._user = user

        model_name = payload.get("model", "")
        checkpointer = getattr(self.request.app.state, "checkpointer", None)
        if checkpointer is None:
            return self._create_error_response(
                "⚠️ HITL resume requires checkpointer (init_checkpointer not set up).",
                model_name,
            )

        # Resume 시점에는 도구/시스템 프롬프트 등 그래프 구성이 첫 invocation 과
        # 정확히 같아야 함 — 따라서 _run_agent 와 동일 경로로 agent 를 재구성한다.
        # 단 input 만 Command(resume=...) 로 바꿔 그래프를 깨움.
        messages, _ = self._extract_messages_and_prompt(payload)
        context = await self._prepare_context(messages)
        self._last_user_question = ""
        for _m in reversed(messages or []):
            if isinstance(_m, dict) and _m.get("role") == "user":
                _c = _m.get("content", "")
                if isinstance(_c, str):
                    self._last_user_question = _c
                break
        self.tools = self.get_tools()

        agent_result = await self._run_agent(
            payload=payload,
            tools=self.tools,
            context=context,
            resume_input=Command(resume={"decisions": decisions}),
            resume_thread_id=thread_id,
            resume_chain_run_id=chain_run_id,
            resume_trace_id=trace_id,
            resume_decisions=decisions,
        )

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            self._run_stream(agent_result, payload, context),
            media_type="text/event-stream",
            headers=headers,
        )
