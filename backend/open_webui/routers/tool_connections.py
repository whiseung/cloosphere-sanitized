import json
import logging
import re
from typing import Any, Optional

from extension_modules.utils.llm import generate_text_from_app
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.tool_connections import (
    ToolConnectionForm,
    ToolConnectionResponse,
    ToolConnections,
    ToolConnectionUserResponse,
)
from open_webui.utils.access_control import (
    has_access,
    has_permission,
    has_permission_min_level,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.crypto import (
    is_masked,
    mask_config_dict,
    mask_sensitive_value,
    resolve_config_dict,
)
from open_webui.utils.mcp_client import MCP_PRESETS, MCPClient, MCPClientError
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# GetToolConnections
############################


@router.get("/", response_model=list[ToolConnectionUserResponse])
async def get_tool_connections(user=Depends(get_verified_user)):
    tool_connections = []

    if user.role == "admin":
        tool_connections = ToolConnections.get_tool_connections()
    else:
        tool_connections = ToolConnections.get_tool_connections_by_user_id(
            user.id, "read"
        )

    return [
        _mask_tool_connection_user_response(tool_connection)
        for tool_connection in tool_connections
    ]


@router.get("/list", response_model=list[ToolConnectionUserResponse])
async def get_tool_connection_list(user=Depends(get_verified_user)):
    tool_connections = []

    if user.role == "admin":
        tool_connections = ToolConnections.get_tool_connections()
    else:
        tool_connections = ToolConnections.get_tool_connections_by_user_id(
            user.id, "write"
        )

    return [
        _mask_tool_connection_user_response(tool_connection)
        for tool_connection in tool_connections
    ]


############################
# CreateNewToolConnection
############################


@router.post("/create", response_model=Optional[ToolConnectionResponse])
async def create_new_tool_connection(
    request: Request, form_data: ToolConnectionForm, user=Depends(get_verified_user)
):
    # 마켓플레이스가 만든 연결(meta.source=="marketplace")은 workspace.marketplace 권한으로,
    # 그 외 일반 도구 연결은 기존 workspace.tools 권한으로 게이팅한다.
    if user.role != "admin":
        is_marketplace = (form_data.meta or {}).get("source") == "marketplace"
        if is_marketplace:
            allowed = has_permission_min_level(
                user.id,
                "workspace.marketplace",
                "write",
                request.app.state.config.USER_PERMISSIONS,
            )
        else:
            allowed = has_permission(
                user.id, "workspace.tools", request.app.state.config.USER_PERMISSIONS
            )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )

    if ToolConnections.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    tool_connection = ToolConnections.insert_new_tool_connection(user.id, form_data)

    if tool_connection:
        return tool_connection
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create tool connection"),
        )


############################
# GetToolConnectionById
############################


def _mask_connection_key(data: Optional[dict]) -> Optional[dict]:
    """Mask `data.connection.key` for API response.

    The bearer token / API key field is named `key` — too short for the
    generic `mask_config_dict` heuristic to catch — so we mask it
    explicitly. Operates on a deep copy; never mutates the input.
    """
    import copy as _copy

    if not isinstance(data, dict):
        return data
    out = _copy.deepcopy(data)
    connection = out.get("connection")
    if isinstance(connection, dict):
        key_value = connection.get("key")
        if isinstance(key_value, str) and key_value:
            connection["key"] = mask_sensitive_value(key_value)
    return out


def _unmask_connection_spec(
    masked_data: Optional[dict], original_data: Optional[dict]
) -> Optional[dict]:
    """Restore `connection.spec` to its original (unmasked) value.

    The inline OpenAPI spec is non-secret structural data, but
    `mask_config_dict` recursively masks any string under a sensitive-looking
    key inside it (e.g. an example/default named `token`), which would corrupt
    the spec shown in the editor and persist on re-save. Keep it verbatim.
    """
    if not isinstance(masked_data, dict) or not isinstance(original_data, dict):
        return masked_data
    orig_conn = original_data.get("connection")
    masked_conn = masked_data.get("connection")
    if isinstance(orig_conn, dict) and isinstance(masked_conn, dict):
        if "spec" in orig_conn:
            masked_conn["spec"] = orig_conn["spec"]
    return masked_data


def _mask_tool_connection_response(tool_connection) -> ToolConnectionResponse:
    """Mask sensitive fields in tool connection data for API response."""
    resp = tool_connection.model_dump()
    if resp.get("data") and isinstance(resp["data"], dict):
        original_data = resp["data"]
        resp["data"] = mask_config_dict(resp["data"])
        resp["data"] = _mask_connection_key(resp["data"])
        resp["data"] = _unmask_connection_spec(resp["data"], original_data)
    return ToolConnectionResponse(**resp)


def _mask_tool_connection_user_response(tool_connection) -> ToolConnectionUserResponse:
    """List endpoints — mask the same sensitive fields and keep `user`."""
    resp = tool_connection.model_dump()
    if resp.get("data") and isinstance(resp["data"], dict):
        original_data = resp["data"]
        resp["data"] = mask_config_dict(resp["data"])
        resp["data"] = _mask_connection_key(resp["data"])
        resp["data"] = _unmask_connection_spec(resp["data"], original_data)
    return ToolConnectionUserResponse(**resp)


def _resolve_connection_key(
    new_data: Optional[dict], current_data: Optional[dict]
) -> Optional[dict]:
    """If the form submitted a masked placeholder for `connection.key`,
    fall back to the current saved (plaintext) value — same UX as the
    `resolve_config_dict` masked-field handling, but for the explicitly
    named `key` field which the generic helper does not cover."""
    if not isinstance(new_data, dict):
        return new_data
    new_conn = new_data.get("connection")
    if not isinstance(new_conn, dict):
        return new_data
    new_key = new_conn.get("key")
    if not (isinstance(new_key, str) and is_masked(new_key)):
        return new_data
    cur_conn = (
        current_data.get("connection") if isinstance(current_data, dict) else None
    )
    cur_key = cur_conn.get("key") if isinstance(cur_conn, dict) else None
    if isinstance(cur_key, str) and cur_key:
        new_conn["key"] = cur_key
    return new_data


@router.get("/{id}", response_model=Optional[ToolConnectionResponse])
async def get_tool_connection_by_id(id: str, user=Depends(get_verified_user)):
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)

    if tool_connection:
        if (
            user.role == "admin"
            or tool_connection.user_id == user.id
            or has_access(user.id, "read", tool_connection.access_control)
        ):
            return _mask_tool_connection_response(tool_connection)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateToolConnectionById
############################


@router.post("/{id}/update", response_model=Optional[ToolConnectionResponse])
async def update_tool_connection_by_id(
    id: str,
    form_data: ToolConnectionForm,
    user=Depends(get_verified_user),
):
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        tool_connection.user_id != user.id
        and not has_access(user.id, "write", tool_connection.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if ToolConnections.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # Resolve masked sensitive values before saving — covers generic
    # password/secret/token names plus the explicit connection.key field.
    if form_data.data and tool_connection.data:
        form_data.data = resolve_config_dict(form_data.data, tool_connection.data)
        form_data.data = _resolve_connection_key(form_data.data, tool_connection.data)

    tool_connection = ToolConnections.update_tool_connection_by_id(
        id=id, form_data=form_data
    )
    if tool_connection:
        return _mask_tool_connection_response(tool_connection)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to update tool connection"),
        )


############################
# DeleteToolConnectionById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_tool_connection_by_id(id: str, user=Depends(get_verified_user)):
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        tool_connection.user_id != user.id
        and not has_access(user.id, "write", tool_connection.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Deleting tool connection: {id} (name: {tool_connection.name})")

    result = ToolConnections.delete_tool_connection_by_id(id=id)
    return result


############################
# MCP Presets
############################


@router.get("/mcp/presets")
async def get_mcp_presets(user=Depends(get_verified_user)):
    """MCP 서버 프리셋 목록 조회"""
    return MCP_PRESETS


############################
# GetToolConnectionTools
############################


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict
    # OpenAPI 도구의 HTTP method/path (있으면 프론트 read/write 분류에 사용).
    method: Optional[str] = None
    path: Optional[str] = None
    # 마켓플레이스 권위 메타 (1st-party 서비스만). category=도메인 그룹,
    # read_only=True(read)/False(write)/None(권위 판별 불가 → 빈값, 사용자/AI 가 설정).
    category: Optional[str] = None
    read_only: Optional[bool] = None
    # OAuth 스코프 기반 사용 가능 여부 (마켓플레이스 oauth 연결만). usable=None 이면 판별 불가(배지 미표시).
    # reason: "not_granted"(테넌트 미동의 → 관리자 동의/재로그인) | "not_requested"(미요청 → 설정+앱등록).
    usable: Optional[bool] = None
    scope_reason: Optional[str] = None
    needed_scopes: Optional[list[str]] = None


@router.get("/{id}/tools", response_model=list[ToolInfo])
async def get_tool_connection_tools(id: str, user=Depends(get_verified_user)):
    """연결된 서버의 도구 목록 조회"""
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and tool_connection.user_id != user.id
        and not has_access(user.id, "read", tool_connection.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    connection = (
        tool_connection.data.get("connection", {}) if tool_connection.data else {}
    )
    conn_type = connection.get("type")

    if not connection.get("enabled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection is disabled",
        )

    if conn_type == "openapi":
        tools = await _get_openapi_tools(connection)
    elif conn_type == "mcp":
        tools = await _get_mcp_tools(connection, user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown connection type: {conn_type}",
        )

    # 마켓플레이스 1st-party 서비스면 권위 메타(카테고리/read_only) + 스코프 사용가능 여부 부여.
    service_id = (tool_connection.meta or {}).get("service_id")
    if service_id:
        from open_webui.utils.marketplace_tool_meta import (
            evaluate_category_access,
            get_tool_meta,
        )

        # 호출 사용자의 granted 스코프 + Cloosphere 가 요청 중인 스코프 (provider 별)
        granted_scopes, requested_scopes = _get_oauth_scopes(
            connection.get("auth_type"), user.id
        )
        cat_access_cache: dict = {}

        for t in tools:
            m = get_tool_meta(service_id, t.name)
            if m:
                t.category = m.get("category")
                t.read_only = m.get("read_only")
            if t.category not in cat_access_cache:
                cat_access_cache[t.category] = evaluate_category_access(
                    service_id, t.category, granted_scopes, requested_scopes
                )
            acc = cat_access_cache[t.category]
            t.usable = acc.get("usable")
            t.scope_reason = acc.get("reason")
            t.needed_scopes = acc.get("needed") or None
    return tools


def _get_oauth_scopes(
    auth_type: Optional[str], user_id: str
) -> tuple[Optional[list[str]], list[str]]:
    """마켓플레이스 oauth 연결의 (granted 스코프, Cloosphere 요청 스코프).

    granted=None 이면 provider 비-oauth 이거나 저장된 토큰/스코프 없음(판별 불가).
    """
    provider = {"oauth_google": "google", "oauth_microsoft": "microsoft"}.get(
        auth_type or ""
    )
    if not provider or not user_id:
        return None, []

    from open_webui.config import GMAIL_DELEGATED_SCOPES, GRAPH_DELEGATED_SCOPES
    from open_webui.models.user_oauth_tokens import UserOAuthTokens

    requested = (
        GMAIL_DELEGATED_SCOPES if provider == "google" else GRAPH_DELEGATED_SCOPES
    )
    granted: Optional[list[str]] = None
    try:
        row = UserOAuthTokens.get(user_id, provider)
        if row and row.scopes:
            granted = row.scopes.split()
    except Exception:
        log.exception("Failed to read granted scopes for %s/%s", user_id, provider)
    return granted, list(requested)


async def _get_mcp_tools(connection: dict, user_id: str) -> list[ToolInfo]:
    """MCP 서버에서 도구 목록 가져오기. auth_type=oauth_* 면 호출 사용자(user_id)
    의 OAuth 토큰을 동적 주입하는 resolver 를 MCPClient 에 전달."""
    from open_webui.utils.oauth_tokens import resolver_for_auth_type

    token_resolver = resolver_for_auth_type(user_id, connection.get("auth_type"))
    try:
        async with MCPClient(connection, token_resolver=token_resolver) as client:
            tools = await client.list_tools()
            return [
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema,
                )
                for tool in tools
            ]
    except MCPClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MCP error: {str(e)}",
        )
    except Exception as e:
        log.exception(f"Failed to get MCP tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to MCP server: {str(e)}",
        )


async def _get_openapi_tools(connection: dict) -> list[ToolInfo]:
    """OpenAPI 연결에서 도구 목록 추출. 인라인 spec(connection.spec) 또는
    url/path fetch 양쪽 지원."""
    from extension_modules.server import get_connector

    try:
        connector = get_connector(connection)
        specs = await connector.list_tools()
        return [
            ToolInfo(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                method=(spec.metadata or {}).get("method"),
                path=(spec.metadata or {}).get("path"),
            )
            for spec in specs
        ]
    except Exception as e:
        log.exception(f"Failed to get OpenAPI tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load OpenAPI spec: {e}",
        )


############################
# ClassifyTools (AI read/write 분류)
############################


class ClassifyToolsForm(BaseModel):
    model: Optional[str] = None
    # 분류 대상 도구 이름. None=전체, 리스트=그 이름들만(보통 활성/체크된 도구).
    tool_names: Optional[list[str]] = None


class ClassifyToolsResponse(BaseModel):
    classifications: dict


# 명백한 side-effect(파괴/전송/권한) 동사 — AI 가 read 로 강등하지 못하게 막는 안전 바닥.
_FORCE_WRITE_PREFIXES = (
    "delete_",
    "remove_",
    "drop_",
    "purge_",
    "erase_",
    "destroy_",
    "wipe_",
    "revoke_",
    "uninstall_",
    "deregister_",
    "send_",
    "reply_",
    "forward_",
    "post_",
    "share_",
    "publish_",
    "upload_",
    "cancel_",
    "reject_",
    "decline_",
    "grant_",
    "assign_",
)


def _is_force_write(name: str) -> bool:
    n = (name or "").lower().replace("-", "_")
    return any(n.startswith(p) for p in _FORCE_WRITE_PREFIXES)


def _parse_classification_json(text: str) -> dict:
    """LLM 출력(마크다운 코드펜스 가능)에서 첫 JSON object 추출."""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


@router.post("/{id}/classify", response_model=ClassifyToolsResponse)
async def classify_tool_connection_tools(
    id: str,
    request: Request,
    form_data: ClassifyToolsForm,
    user=Depends(get_verified_user),
):
    """연결 서버의 도구를 LLM 으로 read/write 1회 배치 분류한다. 결과는 프론트가
    per-tool approval override 로 저장(사용자 검토/수정 가능)한다. 파괴/전송/권한
    동사는 read 로 강등 불가(안전 바닥). 누락/무효 응답은 보수적 write."""
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if (
        user.role != "admin"
        and tool_connection.user_id != user.id
        and not has_access(user.id, "read", tool_connection.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    connection = (
        tool_connection.data.get("connection", {}) if tool_connection.data else {}
    )
    conn_type = connection.get("type")
    if not connection.get("enabled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Connection is disabled"
        )

    if conn_type == "openapi":
        tools = await _get_openapi_tools(connection)
    elif conn_type == "mcp":
        tools = await _get_mcp_tools(connection, user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown connection type: {conn_type}",
        )

    # 분류 대상 한정(보통 활성/체크된 도구만). None 이면 전체.
    if form_data.tool_names is not None:
        wanted = set(form_data.tool_names)
        tools = [t for t in tools if t.name in wanted]

    if not tools:
        return ClassifyToolsResponse(classifications={})

    # 모델 해석: 요청 model → TASK_MODEL → 임의 가용 모델.
    model_id = (form_data.model or "").strip() or (
        request.app.state.config.TASK_MODEL or ""
    ).strip()
    if not model_id:
        models = getattr(request.app.state, "MODELS", {}) or {}
        model_id = next(iter(models), "")
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No model available for classification"),
        )

    tool_lines = "\n".join(
        f"- {t.name}: {(t.description or '').strip()[:200]}" for t in tools
    )
    system_prompt = (
        "You classify software tools by their side effects to decide whether each "
        "needs human approval before execution. Respond with strict JSON only."
    )
    prompt = (
        "For each tool below, decide its category:\n"
        '- "read": only retrieves, queries, searches, or inspects data. No side '
        "effects, no state change; nothing is created, modified, deleted, or sent.\n"
        '- "write": creates, updates, deletes, sends, moves, shares, uploads, or '
        "causes ANY state change or external action.\n"
        'If a tool\'s effect is unclear, choose "write" (safer).\n\n'
        'Return ONLY a JSON object mapping each exact tool name to "read" or '
        '"write". No explanation, no markdown.\n\nTools:\n' + tool_lines
    )

    try:
        text = await generate_text_from_app(
            request.app, model_id, prompt, system_prompt
        )
    except Exception as e:
        log.exception(f"AI tool classification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("AI classification failed"),
        )

    parsed = _parse_classification_json(text or "")
    classifications: dict = {}
    for t in tools:
        v = parsed.get(t.name)
        cat = v if v in ("read", "write") else "write"  # 누락/무효 → 보수적 write
        if _is_force_write(t.name):
            cat = "write"  # 안전 바닥
        classifications[t.name] = cat

    return ClassifyToolsResponse(classifications=classifications)


############################
# VerifyReachability
############################


class OpReachability(BaseModel):
    name: str
    method: str
    path: str
    ok: bool  # 2xx/3xx/4xx=살아있음, 5xx/타임아웃/연결오류=실패
    status: Optional[int] = None
    latency_ms: int = 0
    detail: Optional[str] = None


class ConnReachability(BaseModel):
    base_url: str
    total: int
    probed: int
    ok: int
    failed: int
    results: list[OpReachability]


# 한 번에 프로브할 GET operation 상한 (남용/과부하 방지).
_REACHABILITY_PROBE_CAP = 50


async def _probe_op(
    base_url: str, op_path: str, method: str, name: str, headers: dict, sem
) -> OpReachability:
    """단일 operation 서버사이드 GET 프로브. 응답 본문은 반환하지 않는다(SSRF 노출
    최소화). 2xx/3xx/4xx=엔드포인트 살아있음(ok), 5xx=백엔드 오류(실패),
    타임아웃/연결오류=도달 불가(실패)."""
    import time as _time

    import aiohttp

    target = f"{base_url}{op_path}"
    async with sem:
        start = _time.monotonic()
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(target, headers=headers) as resp:
                    ms = int((_time.monotonic() - start) * 1000)
                    ok = resp.status < 500
                    return OpReachability(
                        name=name,
                        method=method,
                        path=op_path,
                        ok=ok,
                        status=resp.status,
                        latency_ms=ms,
                        detail=None if ok else f"HTTP {resp.status}",
                    )
        except Exception as e:
            return OpReachability(
                name=name,
                method=method,
                path=op_path,
                ok=False,
                latency_ms=int((_time.monotonic() - start) * 1000),
                detail=str(e) or type(e).__name__,
            )


@router.post("/{id}/verify", response_model=ConnReachability)
async def verify_tool_connection_reachability(id: str, user=Depends(get_verified_user)):
    """OpenAPI 도구 연결의 함수(operation)별 실제 서버 도달 여부 확인.

    인라인 스펙은 파싱만으로는 외부 서버 도달을 보장하지 못하므로, 각 GET
    operation 경로로 실제 서버사이드 프로브를 보낸다(부작용 회피 위해 GET 만).
    같은 host 라도 MSA 게이트웨이 뒤 특정 마이크로서비스만 죽은 경우(5xx/timeout)
    를 함수별로 구분한다. 편집(write) 권한이 있는 사용자만 호출 가능."""
    import asyncio

    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )

    if (
        user.role != "admin"
        and tool_connection.user_id != user.id
        and not has_access(user.id, "write", tool_connection.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    connection = (
        tool_connection.data.get("connection", {}) if tool_connection.data else {}
    )
    if connection.get("type") != "openapi":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reachability check is only supported for OpenAPI connections",
        )

    base_url = (connection.get("url") or "").rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No base URL configured",
        )

    # 정적 인증 헤더(있으면) — 401 도 reachable 이지만 더 대표적인 응답을 위해.
    headers = {}
    auth_type = connection.get("auth_type")
    key = connection.get("key")
    if auth_type == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif auth_type == "api_key" and key:
        headers["X-API-Key"] = key

    # GET operation 수집 (부작용 회피 — GET 만 프로브).
    spec = connection.get("spec") or {}
    ops: list[tuple] = []
    for op_path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for m, op in methods.items():
            if m.lower() != "get" or not isinstance(op, dict):
                continue
            op_name = op.get("operationId") or f"{m.upper()} {op_path}"
            ops.append((op_name, m.lower(), op_path))

    total = len(ops)
    probe_ops = ops[:_REACHABILITY_PROBE_CAP]

    # GET operation 이 없으면 base host 자체로 1회 프로브.
    if not probe_ops:
        sem = asyncio.Semaphore(1)
        r = await _probe_op(base_url, "", "get", "(base)", headers, sem)
        return ConnReachability(
            base_url=base_url,
            total=0,
            probed=1,
            ok=1 if r.ok else 0,
            failed=0 if r.ok else 1,
            results=[r],
        )

    sem = asyncio.Semaphore(8)
    results = list(
        await asyncio.gather(
            *[_probe_op(base_url, p, m, n, headers, sem) for (n, m, p) in probe_ops]
        )
    )
    ok_count = sum(1 for r in results if r.ok)
    return ConnReachability(
        base_url=base_url,
        total=total,
        probed=len(results),
        ok=ok_count,
        failed=len(results) - ok_count,
        results=results,
    )


############################
# CallTool
############################


class ToolCallRequest(BaseModel):
    arguments: dict = {}


class ToolCallResponse(BaseModel):
    content: Any
    is_error: bool = False


@router.post("/{id}/tools/{tool_name}/call", response_model=ToolCallResponse)
async def call_tool(
    id: str,
    tool_name: str,
    request: ToolCallRequest,
    user=Depends(get_verified_user),
):
    """도구 호출"""
    tool_connection = ToolConnections.get_tool_connection_by_id(id=id)
    if not tool_connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and tool_connection.user_id != user.id
        and not has_access(user.id, "write", tool_connection.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    connection = (
        tool_connection.data.get("connection", {}) if tool_connection.data else {}
    )
    conn_type = connection.get("type")

    if not connection.get("enabled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection is disabled",
        )

    if conn_type == "mcp":
        return await _call_mcp_tool(connection, tool_name, request.arguments, user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool calling not supported for type: {conn_type}",
        )


async def _call_mcp_tool(
    connection: dict, tool_name: str, arguments: dict, user_id: str
) -> ToolCallResponse:
    """MCP 도구 호출. auth_type=oauth_* 면 호출 사용자 토큰 동적 주입."""
    from open_webui.utils.oauth_tokens import resolver_for_auth_type

    token_resolver = resolver_for_auth_type(user_id, connection.get("auth_type"))
    try:
        async with MCPClient(connection, token_resolver=token_resolver) as client:
            result = await client.call_tool(tool_name, arguments)

            # MCP 응답 형식 처리
            content = result.get("content", [])
            is_error = result.get("isError", False)

            # content가 배열이면 텍스트만 추출
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                content = "\n".join(text_parts) if text_parts else content

            return ToolCallResponse(content=content, is_error=is_error)

    except MCPClientError as e:
        return ToolCallResponse(content=str(e), is_error=True)
    except Exception as e:
        log.exception(f"Failed to call MCP tool: {e}")
        return ToolCallResponse(content=f"Error: {str(e)}", is_error=True)
