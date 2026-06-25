"""
Tool Connection Meta-Tools for UnifiedAgent (Two-Stage Selection)

LLM이 도구 서버를 2단계로 선택하는 메타 도구를 제공:
1. list_tool_servers — 등록된 도구 서버 요약 목록 반환
2. use_tool_server — 서버 도구 조회(list) 또는 호출(call)

이를 통해 N서버 × M API의 프롬프트 폭발 없이 에이전트가 필요한 도구만 선택적으로 사용.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from extension_modules.server import ServerConnectorError, get_connector
from extension_modules.server.base import ServerConnector, ToolSpec
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HITL 휴리스틱 — 외부 도구를 read/write 로 자동 분류
# ---------------------------------------------------------------------------
# OpenAPI: HTTP method 기반. GET/HEAD/OPTIONS → read, 그 외 → write.
# MCP: mcp_connector 가 도구의 annotations(readOnlyHint/destructiveHint)를 ToolSpec.metadata
#      에 채우면 그것이 권위 신호로 우선된다. annotation 이 없는 서버(예: softeria M365)는
#      도구 이름 prefix/suffix 휴리스틱으로 폴백.
# 보수적 디폴트: 분류 불가 시 "write" (승인 게이트). 안전 우선.
_READ_NAME_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "find_",
    "fetch_",
    "read_",
    "describe_",
    "show_",
    "query_",
    "lookup_",
    "view_",
    "retrieve_",
    "browse_",
    "scan_",
    "check_",
    "count_",
    "verify_",
    "validate_",
    "inspect_",
    "is_",
    "has_",
    "download_",
    "export_",
)
_READ_NAME_SUFFIXES = (
    "_get",
    "_list",
    "_search",
    "_find",
    "_fetch",
    "_read",
    "_info",
    "_status",
    "_stats",
    "_count",
    "_check",
    "_health",
    "_metrics",
)
# write(상태 변경) 동사 접두사. 이름이 read 처럼 끝나도(예: create_..._list, delete_..._list)
# 접두사가 write 면 write 로 본다 — 접미사 휴리스틱보다 우선해 위험한 오분류를 막는다.
_WRITE_NAME_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "set_",
    "send_",
    "move_",
    "copy_",
    "share_",
    "upload_",
    "put_",
    "post_",
    "patch_",
    "insert_",
    "modify_",
    "edit_",
    "write_",
    "replace_",
    "reply_",
    "forward_",
    "accept_",
    "decline_",
    "cancel_",
    "complete_",
    "enable_",
    "disable_",
    "clear_",
    "mark_",
    "rename_",
    "merge_",
    "archive_",
    "restore_",
    "revoke_",
    "grant_",
    "assign_",
    "unassign_",
    "register_",
    "deregister_",
    "install_",
    "uninstall_",
    "run_",
    "execute_",
    "trigger_",
    "approve_",
    "reject_",
    "publish_",
    "unpublish_",
    "start_",
    "stop_",
    "draft_",
    "import_",
    "sync_",
    "push_",
)


def classify_tool_action(tool_spec: ToolSpec) -> str:
    """ToolSpec → "read" | "write".

    우선순위: 사용자 override > MCP annotations > OpenAPI method > 도구 이름 patterns
    > 보수적 디폴트(write).
    """
    meta = tool_spec.metadata or {}
    source = meta.get("source")

    # 0) 사용자 명시 override (Tool Connection 편집 화면 셀렉터)
    override = meta.get("approval_override")
    if override in ("read", "write"):
        return override

    # 1) MCP annotations (mcp_connector 가 ToolSpec.metadata 에 채움). 서버가 선언하면
    #    이름 휴리스틱보다 권위 있는 신호다. readOnlyHint True→read / False→write.
    ro = meta.get("readOnlyHint")
    if ro is True or meta.get("read_only") is True:
        return "read"
    if ro is False:
        return "write"
    if meta.get("destructiveHint") is True:
        return "write"

    # 2) OpenAPI: HTTP method
    if source == "openapi":
        method = (meta.get("method") or "").upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        return "write"

    # 3) 도구 이름 patterns (MCP / 알 수 없는 source)
    # MCP 서버는 도구명을 하이픈으로 짓는 경우가 많다(예: softeria M365 의
    # list-mail-folder-messages, create-todo-task-list). 하이픈을 언더스코어로 정규화한다.
    # 판정 순서가 중요: write 동사 접두사(create_/delete_ 등)를 read 접미사(_list 등)보다
    # 먼저 본다 — 그래야 create_..._list / delete_..._list 가 read 로 새지 않는다.
    name = (tool_spec.name or "").lower().replace("-", "_")
    if any(name.startswith(p) for p in _READ_NAME_PREFIXES):
        return "read"
    if any(name.startswith(p) for p in _WRITE_NAME_PREFIXES):
        return "write"
    if any(name.endswith(s) for s in _READ_NAME_SUFFIXES):
        return "read"

    # 4) 보수적 디폴트
    return "write"


class ListToolServersInput(BaseModel):
    """list_tool_servers 입력 (파라미터 없음)"""

    pass


class UseToolServerReadInput(BaseModel):
    """use_tool_server_read 입력 — list 와 read 분류 도구의 call."""

    server_id: str = Field(..., description="도구 서버 ID")
    action: str = Field(
        default="list",
        description='"list" to browse available tools (each tagged with category: read|write), '
        'or "call" to execute a read-only tool',
    )
    tool_name: Optional[str] = Field(
        default=None, description='Tool name to call (required when action="call")'
    )
    arguments: Optional[Dict[str, Any]] = Field(
        default=None, description='Tool arguments (required when action="call")'
    )


class UseToolServerWriteInput(BaseModel):
    """use_tool_server_write 입력 — write/destructive 도구만, 사용자 승인 필요."""

    server_id: str = Field(..., description="도구 서버 ID")
    tool_name: str = Field(..., description="Write/destructive tool name to call")
    arguments: Optional[Dict[str, Any]] = Field(
        default=None, description="Tool arguments"
    )


class ToolConnectionManager:
    """
    도구 연결 메타 도구 관리자.

    AgentConfig.tool_connections에서 전달받은 도구 연결 정보를 기반으로
    list_tool_servers / use_tool_server 2개의 StructuredTool을 생성.
    """

    def __init__(
        self,
        tool_connections: list,
        user_id: Optional[str] = None,
    ):
        """
        Args:
            tool_connections: List[ToolConnectionRef] from AgentConfig
            user_id: 현재 채팅 사용자 ID. auth_type=oauth_microsoft/oauth_google
                연결을 호출할 때 이 user_id 의 OAuth 토큰을 동적으로 주입한다.
                None 이면 oauth_* 연결은 인증 없이 호출되어 401 에러 반환.
        """
        self._tool_connections = tool_connections
        self._user_id = user_id
        self._server_summaries: List[Dict[str, str]] = []
        self._connection_configs: Dict[str, dict] = {}
        # tc_model.meta.approval_overrides — 사용자가 도구별로 read/write 라벨을
        # 명시한 override. classify_tool_action 이 휴리스틱보다 먼저 본다.
        self._approval_overrides: Dict[str, Dict[str, str]] = {}
        # 마켓플레이스 연결의 service_id (권위 read_only 메타 조회용). 비-마켓 연결은 None.
        self._service_ids: Dict[str, Optional[str]] = {}

        # 커넥터 & 스펙 캐시 (요청 단위 재사용)
        self._connector_cache: Dict[str, ServerConnector] = {}
        self._specs_cache: Dict[str, List[ToolSpec]] = {}

        # DB에서 서버 정보 조회하여 요약 구축
        self._build_server_summaries()

    def _make_token_resolver(self, config: dict):
        """auth_type 에 따라 동적 토큰 resolver 반환 (공용 헬퍼 위임)."""
        from open_webui.utils.oauth_tokens import resolver_for_auth_type

        resolver = resolver_for_auth_type(self._user_id, config.get("auth_type"))
        if resolver is None and (config.get("auth_type") or "").lower().startswith(
            "oauth_"
        ):
            logger.warning(
                "[ToolConnectionManager] oauth auth_type=%s 인 연결이 user_id 없이 "
                "호출돼 토큰 주입을 건너뜁니다",
                config.get("auth_type"),
            )
        return resolver

    def _build_server_summaries(self):
        """tool_connections에서 서버 요약 목록 구축."""
        from open_webui.models.tool_connections import ToolConnections

        for tc_ref in self._tool_connections:
            if not tc_ref.id:
                continue

            tc_model = ToolConnections.get_tool_connection_by_id(tc_ref.id)
            if not tc_model:
                logger.warning(
                    f"[ToolConnectionManager] Tool connection not found: {tc_ref.id}"
                )
                continue

            # 연결 설정 확인
            connection_config = (tc_model.data or {}).get("connection", {})
            if not connection_config.get("enabled", False):
                logger.info(
                    f"[ToolConnectionManager] Skipping disabled connection: {tc_ref.id}"
                )
                continue

            conn_type = connection_config.get("type", "unknown").upper()
            # Prefer meta.tool_description (AI-generated) over plain description
            tool_desc = (
                (tc_model.meta or {}).get("tool_description", "")
                or tc_model.description
                or ""
            )
            self._server_summaries.append(
                {
                    "id": tc_ref.id,
                    "name": tc_model.name or tc_ref.name or "Unknown",
                    "description": tool_desc,
                    "type": conn_type,
                }
            )
            self._connection_configs[tc_ref.id] = connection_config
            self._service_ids[tc_ref.id] = (tc_model.meta or {}).get("service_id")

            # 사용자가 도구별로 라벨링한 read/write override (디폴트는 휴리스틱).
            # 형식: { tool_name: "read" | "write" }
            overrides = (tc_model.meta or {}).get("approval_overrides") or {}
            if isinstance(overrides, dict):
                self._approval_overrides[tc_ref.id] = {
                    str(k): v for k, v in overrides.items() if v in ("read", "write")
                }

    async def _get_connector(self, server_id: str) -> ServerConnector:
        """커넥터 가져오기 (캐시 활용)."""
        if server_id in self._connector_cache:
            return self._connector_cache[server_id]

        config = self._connection_configs.get(server_id)
        if not config:
            raise ServerConnectorError(
                f"No connection config found for server: {server_id}"
            )

        token_resolver = self._make_token_resolver(config)
        connector = get_connector(config, token_resolver=token_resolver)
        await connector.connect()
        self._connector_cache[server_id] = connector
        return connector

    async def _get_tool_specs(self, server_id: str) -> List[ToolSpec]:
        """도구 스펙 가져오기 (캐시 활용). 사용자 approval_override 를 spec.metadata
        에 주입해 classify_tool_action 이 휴리스틱보다 우선 적용한다."""
        if server_id in self._specs_cache:
            return self._specs_cache[server_id]

        connector = await self._get_connector(server_id)
        specs = await connector.list_tools()

        overrides = self._approval_overrides.get(server_id) or {}
        if overrides:
            for spec in specs:
                ov = overrides.get(spec.name)
                if ov:
                    spec.metadata = {**(spec.metadata or {}), "approval_override": ov}

        # 마켓플레이스 서비스의 권위있는 read_only 를 readOnlyHint 로 주입한다. classify_tool_action
        # 은 사용자 override > readOnlyHint > 휴리스틱 순이므로, override 가 우선되고 권위값이
        # 휴리스틱보다 우선된다. read_only=None(판별 불가)은 주입하지 않아 휴리스틱으로 폴백.
        service_id = self._service_ids.get(server_id)
        if service_id:
            from open_webui.utils.marketplace_tool_meta import get_tool_meta

            for spec in specs:
                m = get_tool_meta(service_id, spec.name)
                if m and m.get("read_only") is not None:
                    spec.metadata = {
                        **(spec.metadata or {}),
                        "readOnlyHint": m["read_only"],
                    }

        self._specs_cache[server_id] = specs
        return specs

    async def _list_tool_servers(self) -> str:
        """등록된 도구 서버 요약 목록 반환."""
        if not self._server_summaries:
            return "No tool servers are available."

        return json.dumps(self._server_summaries, ensure_ascii=False, indent=2)

    async def _list_server_tools(self, server_id: str) -> str:
        """서버의 도구 목록 + read/write 분류 반환 (call 전 LLM 이 분류 확인용)."""
        specs = await self._get_tool_specs(server_id)
        tools_info = [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "category": classify_tool_action(spec),
            }
            for spec in specs
        ]
        if not tools_info:
            return f"No tools available on server '{server_id}'."
        return json.dumps(tools_info, ensure_ascii=False, indent=2)

    async def _resolve_and_classify(
        self, server_id: str, tool_name: str
    ) -> Optional[str]:
        """도구 이름 → "read"|"write" (찾을 수 없으면 None)."""
        try:
            specs = await self._get_tool_specs(server_id)
        except Exception:
            return None
        for spec in specs:
            if spec.name == tool_name:
                return classify_tool_action(spec)
        return None

    async def _call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
    ) -> str:
        """실제 외부 도구 호출 (분류 가드 통과 후만 사용)."""
        try:
            connector = await self._get_connector(server_id)
            result = await connector.call_tool(tool_name, arguments or {})
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except ServerConnectorError as e:
            logger.warning(
                f"[ToolConnectionManager] Server connector error for {server_id}: {e}"
            )
            return f"Error connecting to server: {e}"
        except Exception as e:
            logger.warning(
                f"[ToolConnectionManager] Unexpected error for {server_id}: {e}"
            )
            return f"Error: {e}"

    async def _use_tool_server_read(
        self,
        server_id: str,
        action: str = "list",
        tool_name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Read-only path — list 와 read 분류 도구의 call 만 허용. HITL 자동승인."""
        valid_ids = {s["id"] for s in self._server_summaries}
        if server_id not in valid_ids:
            return (
                f"Error: Unknown server_id '{server_id}'. Use list_tool_servers first."
            )

        if action == "list":
            return await self._list_server_tools(server_id)
        if action == "call":
            if not tool_name:
                return "Error: tool_name is required when action='call'."
            category = await self._resolve_and_classify(server_id, tool_name)
            if category is None:
                return (
                    f"Error: Tool '{tool_name}' not found on server '{server_id}'. "
                    f"Use action='list' to see available tools."
                )
            if category != "read":
                return (
                    f"Error: Tool '{tool_name}' is classified as '{category}'. "
                    f"use_tool_server_read only allows read-only tools "
                    f"(GET/HEAD/OPTIONS for OpenAPI; get_/list_/search_/... names for MCP). "
                    f"For write/destructive operations, use use_tool_server_write — "
                    f"that path requires user approval."
                )
            return await self._call_tool(server_id, tool_name, arguments)
        return f"Error: Unknown action '{action}'. Use 'list' or 'call'."

    async def _use_tool_server_write(
        self,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Write path — write 분류 도구의 call 만. HITL 승인 게이트로 가로채진다."""
        valid_ids = {s["id"] for s in self._server_summaries}
        if server_id not in valid_ids:
            return (
                f"Error: Unknown server_id '{server_id}'. Use list_tool_servers first."
            )
        if not tool_name:
            return "Error: tool_name is required."
        category = await self._resolve_and_classify(server_id, tool_name)
        if category is None:
            return (
                f"Error: Tool '{tool_name}' not found on server '{server_id}'. "
                f"Use use_tool_server_read with action='list' to see available tools."
            )
        if category != "write":
            return (
                f"Error: Tool '{tool_name}' is classified as '{category}'. "
                f"use_tool_server_write is only for write/destructive operations. "
                f"For read-only tools, use use_tool_server_read."
            )
        return await self._call_tool(server_id, tool_name, arguments)

    def get_tools(self) -> List[StructuredTool]:
        """메타 도구 3개 반환:
        - list_tool_servers (서버 요약)
        - use_tool_server_read (browse + read-only call, 자동승인)
        - use_tool_server_write (write/destructive call, HITL 승인 필수)

        도구를 read/write 두 갈래로 쪼갠 이유는 LangChain HumanInTheLoopMiddleware
        의 정책이 도구 이름 단위라서다 — 외부 도구 N 개를 펼치지 않고도 표준
        그대로 read 자동 / write 승인 정책을 적용할 수 있음. LLM 은 list 결과의
        category 필드를 보고 적절한 도구를 선택한다.
        """
        if not self._server_summaries:
            return []

        server_summary_text = ", ".join(
            f"{s['name']} ({s['type']})" for s in self._server_summaries
        )

        list_tool = StructuredTool.from_function(
            coroutine=self._list_tool_servers,
            name="list_tool_servers",
            description=(
                f"List available external tool servers. "
                f"Currently registered: {server_summary_text}. "
                f"Call this to get server IDs and details before using "
                f"use_tool_server_read or use_tool_server_write. "
                f"ALWAYS check the available external tool servers before telling "
                f"the user something cannot be done — they may provide the needed "
                f"capability."
            ),
            args_schema=ListToolServersInput,
        )

        read_tool = StructuredTool.from_function(
            coroutine=self._use_tool_server_read,
            name="use_tool_server_read",
            description=(
                "Browse and call READ-ONLY tools on an external server. "
                'Use action="list" to enumerate the server\'s tools — each tool is '
                'tagged with `category: "read" | "write"` based on heuristics '
                "(OpenAPI HTTP method, MCP tool-name patterns). "
                'Use action="call" with tool_name + arguments to execute a tool '
                "classified as `read`. "
                "For write/destructive tools (POST/PUT/DELETE, INSERT/UPDATE/DELETE-style "
                "MCP tools, etc.), use use_tool_server_write — that path requires user approval."
            ),
            args_schema=UseToolServerReadInput,
        )

        write_tool = StructuredTool.from_function(
            coroutine=self._use_tool_server_write,
            name="use_tool_server_write",
            description=(
                "Execute a WRITE / DESTRUCTIVE tool on an external server "
                "(POST/PUT/PATCH/DELETE for OpenAPI; mutating MCP tools). "
                "REQUIRES USER APPROVAL — every call is intercepted by the HITL gate "
                "and the user must explicitly approve before execution. "
                "Use only when the user has clearly asked to perform a side-effecting "
                "operation. Always preview the change first by inspecting the tool "
                "schema via use_tool_server_read action='list'."
            ),
            args_schema=UseToolServerWriteInput,
        )

        return [list_tool, read_tool, write_tool]
