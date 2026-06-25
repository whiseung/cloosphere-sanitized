"""마켓플레이스 — Cloosphere 1st-party 서비스 연결 카탈로그 + 핸들러.

`MARKETPLACE_SERVICES` 는 워크스페이스 > 마켓플레이스 생성 페이지의 카탈로그(서비스 picker)를
구동한다. 실제 연결은 tool_connection 행으로 저장된다(meta.source="marketplace"). docker
컨테이너 자체는 관리자가 별도로 `docker compose up` 하고(services/<svc>/), 여기서는 카탈로그
메타데이터(이름/설명/아이콘/auth_type/기본 URL)만 제공한다.

서비스별 connection_kind:
  - mcp: tool_connection 으로 노출 (Google Workspace → oauth_google, Microsoft 365 →
        oauth_microsoft). 생성은 워크스페이스 생성 페이지 → tool_connections create 경로.
  - rest-config: PersistentConfig 직접 set/unset (RestConfigHandler). 현재 카탈로그에는
        rest-config 서비스가 없다(PPT Generator 는 제거됨). 핸들러는 향후 재사용 대비 잔존.
"""

import logging
from typing import Optional

import httpx
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MODELS", logging.INFO))


# ── 핸들러 ────────────────────────────────────────────────────────────────
class MarketplaceHandler:
    """서비스 연결 핸들러 베이스. 각 connection_kind 가 구현한다."""

    async def get_status(self, app, service: dict) -> dict:
        """{connected: bool, healthy: bool, detail: str} 반환."""
        raise NotImplementedError

    async def connect(self, app, user_id: str, service: dict, settings: dict) -> None:
        raise NotImplementedError

    async def disconnect(self, app, user_id: str, service: dict) -> None:
        raise NotImplementedError


class RestConfigHandler(MarketplaceHandler):
    """PPT Generator — PRESENTON_BASE_URL/TIMEOUT + 엔진 사용 여부(PRESENTON_ENABLED) 관리.

    마켓플레이스 연결이 단일 진입점이다: connect = 엔진 ON + URL 설정,
    disconnect = 엔진 OFF + URL 제거. (문서 템플릿 탭에는 더 이상 엔진 토글이 없다.)"""

    async def get_status(self, app, service: dict) -> dict:
        c = app.state.config
        base = (c.PRESENTON_BASE_URL or "").strip().rstrip("/")
        if not base:
            return {"connected": False, "healthy": False, "detail": "Not connected"}
        # health probe — Presenton 템플릿 목록 (routers/document_templates.py 의 test 와 동일 경로)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}/api/v1/ppt/template/all")
            healthy = r.status_code == 200
            return {
                "connected": True,
                "healthy": healthy,
                "detail": "OK" if healthy else f"HTTP {r.status_code}",
                "url": base,
            }
        except Exception as e:  # noqa: BLE001
            return {
                "connected": True,
                "healthy": False,
                "detail": f"Unreachable: {e}",
                "url": base,
            }

    async def connect(self, app, user_id: str, service: dict, settings: dict) -> None:
        base_url = (settings.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("base_url is required")
        c = app.state.config
        c.PRESENTON_BASE_URL = base_url  # 직접 할당 → auto-save + Redis 동기화
        timeout = settings.get("timeout")
        if timeout:
            try:
                c.PRESENTON_TIMEOUT = int(timeout)
            except (TypeError, ValueError):
                pass
        c.PRESENTON_ENABLED = True  # 연결 = 엔진 사용 (단일 진입점)

    async def disconnect(self, app, user_id: str, service: dict) -> None:
        c = app.state.config
        c.PRESENTON_BASE_URL = ""
        c.PRESENTON_ENABLED = False  # 연결 끊기면 엔진도 사용 불가


class McpHandler(MarketplaceHandler):
    """MCP tool_connection 으로 노출되는 서비스(Google Workspace 등).

    마켓플레이스가 만든 connection 은 meta.source="marketplace" +
    meta.service_id 로 식별한다(워크스페이스>도구에도 그대로 노출됨)."""

    def _find(self, service_id: str):
        from open_webui.models.tool_connections import ToolConnections

        for tc in ToolConnections.get_tool_connections():
            meta = tc.meta or {}
            if (
                meta.get("source") == "marketplace"
                and meta.get("service_id") == service_id
            ):
                return tc
        return None

    async def get_status(self, app, service: dict) -> dict:
        tc = self._find(service["id"])
        if not tc:
            return {"connected": False, "healthy": False, "detail": "Not connected"}
        url = ((tc.data or {}).get("connection") or {}).get("url", "")
        # auth-gated MCP 서버는 토큰 없는 probe 가 401 이 정상이므로, connection 존재만으로
        # connected/healthy 판정한다(서버 down 여부는 워크스페이스>도구에서 도구 목록으로 확인).
        return {"connected": True, "healthy": True, "detail": "Connected", "url": url}

    async def connect(self, app, user_id: str, service: dict, settings: dict) -> None:
        from open_webui.models.tool_connections import (
            ToolConnectionForm,
            ToolConnections,
        )

        url = (settings.get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        connection = {
            "type": "mcp",
            "url": url,
            "auth_type": service.get("auth_type", "none"),
            "key": "",
            "headers": {},
            "enabled": True,
        }
        form = ToolConnectionForm(
            name=service["name"],
            description=service.get("description", ""),
            data={"connection": connection},
            meta={"source": "marketplace", "service_id": service["id"]},
            access_control=None,  # 공개 read (조직 공용 서비스)
        )
        existing = self._find(service["id"])
        if existing:
            ToolConnections.update_tool_connection_by_id(existing.id, form)
        else:
            ToolConnections.insert_new_tool_connection(user_id, form)

    async def disconnect(self, app, user_id: str, service: dict) -> None:
        from open_webui.models.tool_connections import ToolConnections

        existing = self._find(service["id"])
        if existing:
            ToolConnections.delete_tool_connection_by_id(existing.id)


# ── 레지스트리 ──────────────────────────────────────────────────────────────
_REST = RestConfigHandler()
_MCP = McpHandler()

_HANDLERS: dict[str, MarketplaceHandler] = {"rest-config": _REST, "mcp": _MCP}

# 1st-party 서비스 매니페스트. 새 서비스 추가 = 여기에 항목 1개 + (필요 시) 핸들러 재사용.
# fields: 설정 모달이 렌더할 입력 스키마. icon: 프론트 아이콘 키.
MARKETPLACE_SERVICES: list[dict] = [
    {
        "id": "google-workspace",
        "name": "Google Workspace",
        "description": (
            "Let agents read and act across Google Workspace for each user — Gmail, "
            "Calendar, Drive, Docs, Sheets, Slides, Forms, Tasks, Contacts and Chat. "
            "Everyone connects with their own Google sign-in, so data stays scoped to "
            "that person — no shared keys."
        ),
        "category": "productivity",
        "tags": [
            "gws",
            "gmail",
            "calendar",
            "drive",
            "docs",
            "sheets",
            "slides",
            "forms",
            "tasks",
            "contacts",
            "chat",
            "email",
        ],
        "connection_kind": "mcp",
        "icon": "google-workspace",
        "auth_type": "oauth_google",
        "docs": "services/GoogleWorkspaceMCP/README.md",
        "fields": [
            {
                "key": "url",
                "label": "Service URL",
                "type": "url",
                "default": "http://localhost:8000/mcp",
                "required": True,
            },
        ],
    },
    {
        "id": "microsoft-365",
        "name": "Microsoft 365",
        "description": (
            "Let agents read and act on Outlook mail, Teams, OneDrive/SharePoint, "
            "and the calendar for each user. Everyone connects with their own "
            "Microsoft sign-in, so data stays scoped to that person — no shared keys."
        ),
        "category": "productivity",
        "tags": ["m365", "outlook", "email", "teams", "sharepoint", "calendar"],
        "connection_kind": "mcp",
        "icon": "microsoft-365",
        "auth_type": "oauth_microsoft",
        "docs": "services/Microsoft365MCP/README.md",
        "fields": [
            {
                "key": "url",
                "label": "Service URL",
                "type": "url",
                "default": "http://localhost:8001/mcp",
                "required": True,
            },
        ],
    },
]


def get_service(service_id: str) -> Optional[dict]:
    return next((s for s in MARKETPLACE_SERVICES if s["id"] == service_id), None)


def get_handler(service: dict) -> MarketplaceHandler:
    return _HANDLERS[service["connection_kind"]]


async def list_services_with_status(app) -> list[dict]:
    """모든 서비스 매니페스트 + 현재 연결/상태를 병합해 반환."""
    out = []
    for svc in MARKETPLACE_SERVICES:
        handler = get_handler(svc)
        try:
            svc_status = await handler.get_status(app, svc)
        except Exception as e:  # noqa: BLE001
            log.warning("marketplace status %s failed: %s", svc["id"], e)
            svc_status = {"connected": False, "healthy": False, "detail": str(e)}
        out.append({**svc, "status": svc_status})
    return out
