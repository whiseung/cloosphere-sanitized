"""Teams 봇 설정 관리자 API.

관리자 > 설정 > 채널 > 봇 연결 UI 에서 사용.
- GET  /api/v1/teams-bot/config              — 현재 설정 (password 마스킹)
- POST /api/v1/teams-bot/config              — 설정 저장 (마스킹된 값은 유지)
- GET  /api/v1/teams-bot/messaging-endpoint  — 현재 도메인 기반 URL 계산
- GET  /api/v1/teams-bot/manifest.zip        — Teams sideload zip 생성

실제 activity 수신은 별도 라우터 `teams_bot.py` 에서 담당 (격리).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi import File as FastAPIFile
from fastapi.responses import Response, StreamingResponse
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.auth import get_admin_user
from open_webui.utils.crypto import is_masked, mask_sensitive_value
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", "INFO"))

router = APIRouter()


class TeamsBotConfigForm(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_password: str = ""  # 마스킹된 값이면 기존 유지
    tenant_id: str = ""
    model_id: str = ""
    # 브랜딩
    name: str = ""  # 앱 이름
    description_short: str = ""  # ≤ 80자
    description_full: str = ""  # ≤ 4000자
    developer_name: str = ""
    developer_website: str = ""
    # 배포 범위
    scopes: list[str] = ["personal"]  # personal/team/groupchat 조합
    accent_color: str = "#171717"  # "#RRGGBB"
    default_group_capability: str = ""  # "team"|"groupchat"|"meetings"|""


_ALLOWED_SCOPES = ("personal", "team", "groupchat")
_ALLOWED_GROUP_CAPABILITY = ("team", "groupchat", "meetings")
# Scope 별 RSC (resource-specific consent) 필수 permission — team/groupchat 이
# 실제로 메시지를 읽으려면 Teams Admin Center 설치 시 admin consent 로 승인되는
# 이 권한들이 매니페스트에 선언되어 있어야 한다.
_SCOPE_RSC_PERMISSIONS = {
    "team": [
        {"name": "ChannelMessage.Read.Group", "type": "Application"},
        {"name": "TeamMember.Read.Group", "type": "Application"},
    ],
    "groupchat": [
        {"name": "ChatMessage.Read.Chat", "type": "Application"},
        {"name": "ChatMember.Read.Chat", "type": "Application"},
    ],
}


# Teams manifest 기본값 (관리자 미입력 시 사용).
_DEFAULT_BRANDING = {
    "name": "Cloosphere",
    "description_short": "Chat with your Cloosphere agents inside Teams.",
    "description_full": (
        "Cloosphere AI agent integration for Microsoft Teams — ask your knowledge "
        "base, run queries, and get streamed answers directly in Teams."
    ),
    "developer_name": "Cloocus",
    "developer_website": "https://www.cloocus.com",
    "developer_privacy": "https://www.cloocus.com/privacy",
    "developer_terms": "https://www.cloocus.com/terms",
    "accent_color": "#171717",
    "version": "0.1.0",
}


def _value(cfg_obj, name: str, default=""):
    """AppConfig.__getattr__ 는 PersistentConfig 의 value 를 직접 반환하므로
    getattr(cfg, KEY) 만 하면 값이다. AttributeError 시 default."""
    try:
        v = getattr(cfg_obj, name)
    except AttributeError:
        return default
    return v if v is not None else default


def _icon_present(cfg, icon_kind: str) -> bool:
    """업로드된 아이콘 있는지. icon_kind: 'color' | 'outline'."""
    key = "TEAMS_BOT_COLOR_ICON" if icon_kind == "color" else "TEAMS_BOT_OUTLINE_ICON"
    return bool(_value(cfg, key, ""))


def _decode_icon(cfg, icon_kind: str) -> Optional[bytes]:
    """저장된 data URL 을 바이트로 디코드. 없으면 None."""
    key = "TEAMS_BOT_COLOR_ICON" if icon_kind == "color" else "TEAMS_BOT_OUTLINE_ICON"
    data_url = _value(cfg, key, "")
    if not data_url or not isinstance(data_url, str):
        return None
    # data:image/png;base64,AAAA...
    if "," not in data_url:
        return None
    try:
        return base64.b64decode(data_url.split(",", 1)[1])
    except Exception:
        return None


def _normalize_scopes(raw) -> list[str]:
    """저장된 scopes 를 유효 목록으로 정규화. 빈 값/무효값은 personal 로 복원."""
    if isinstance(raw, str):
        # 과거 env 호환: CSV 또는 JSON 문자열
        raw = raw.strip()
        if raw.startswith("["):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [raw]
        else:
            raw = [s.strip() for s in raw.split(",") if s.strip()]
    if not isinstance(raw, list):
        raw = []
    out = []
    for s in raw:
        s = str(s).strip().lower()
        if s in _ALLOWED_SCOPES and s not in out:
            out.append(s)
    return out or ["personal"]


def _response_shape(cfg) -> dict:
    pw = _value(cfg, "TEAMS_BOT_APP_PASSWORD", "")
    return {
        "enabled": bool(_value(cfg, "TEAMS_BOT_ENABLED", False)),
        "app_id": _value(cfg, "TEAMS_BOT_APP_ID", ""),
        "app_password": mask_sensitive_value(pw) if pw else "",
        "tenant_id": _value(cfg, "TEAMS_BOT_TENANT_ID", ""),
        "model_id": _value(cfg, "TEAMS_BOT_MODEL_ID", ""),
        "name": _value(cfg, "TEAMS_BOT_NAME", ""),
        "description_short": _value(cfg, "TEAMS_BOT_DESCRIPTION_SHORT", ""),
        "description_full": _value(cfg, "TEAMS_BOT_DESCRIPTION_FULL", ""),
        "developer_name": _value(cfg, "TEAMS_BOT_DEVELOPER_NAME", ""),
        "developer_website": _value(cfg, "TEAMS_BOT_DEVELOPER_WEBSITE", ""),
        "has_color_icon": _icon_present(cfg, "color"),
        "has_outline_icon": _icon_present(cfg, "outline"),
        "scopes": _normalize_scopes(_value(cfg, "TEAMS_BOT_SCOPES", ["personal"])),
        "accent_color": _value(cfg, "TEAMS_BOT_ACCENT_COLOR", "#171717") or "#171717",
        "default_group_capability": _value(
            cfg, "TEAMS_BOT_DEFAULT_GROUP_CAPABILITY", ""
        )
        or "",
    }


@router.get("/config")
async def get_teams_bot_config(request: Request, user=Depends(get_admin_user)):
    """admin only. password 는 마스킹된 형태로 반환."""
    return _response_shape(request.app.state.config)


@router.post("/config")
async def update_teams_bot_config(
    request: Request,
    form_data: TeamsBotConfigForm,
    user=Depends(get_admin_user),
):
    cfg = request.app.state.config

    # 활성화 + model_id 필수 validation
    if form_data.enabled and not (form_data.model_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Default agent/model is required when Teams bot is enabled.",
        )

    # password 가 마스킹된 값이면 기존 값 유지
    new_password = form_data.app_password or ""
    current_password = _value(cfg, "TEAMS_BOT_APP_PASSWORD", "")
    if is_masked(new_password):
        new_password = current_password

    # AppConfig.__setattr__ 이 자동으로 _state[key].value 업데이트 + save() + redis sync
    cfg.TEAMS_BOT_ENABLED = bool(form_data.enabled)
    cfg.TEAMS_BOT_APP_ID = (form_data.app_id or "").strip()
    cfg.TEAMS_BOT_APP_PASSWORD = new_password
    cfg.TEAMS_BOT_TENANT_ID = (form_data.tenant_id or "").strip()
    cfg.TEAMS_BOT_MODEL_ID = (form_data.model_id or "").strip()
    # 브랜딩 (길이 제한은 Teams 매니페스트 스키마 준수)
    cfg.TEAMS_BOT_NAME = (form_data.name or "").strip()[:30]
    cfg.TEAMS_BOT_DESCRIPTION_SHORT = (form_data.description_short or "").strip()[:80]
    cfg.TEAMS_BOT_DESCRIPTION_FULL = (form_data.description_full or "").strip()[:4000]
    cfg.TEAMS_BOT_DEVELOPER_NAME = (form_data.developer_name or "").strip()[:32]
    cfg.TEAMS_BOT_DEVELOPER_WEBSITE = (form_data.developer_website or "").strip()[:2048]

    # 배포 범위
    cfg.TEAMS_BOT_SCOPES = _normalize_scopes(form_data.scopes)
    accent = (form_data.accent_color or "").strip() or "#171717"
    # "#RRGGBB" 형식 검증 (7자, '#' + hex6). 실패 시 기본값.
    if not (
        len(accent) == 7
        and accent.startswith("#")
        and all(c in "0123456789abcdefABCDEF" for c in accent[1:])
    ):
        accent = "#171717"
    cfg.TEAMS_BOT_ACCENT_COLOR = accent
    default_cap = (form_data.default_group_capability or "").strip().lower()
    if default_cap and default_cap not in _ALLOWED_GROUP_CAPABILITY:
        default_cap = ""
    cfg.TEAMS_BOT_DEFAULT_GROUP_CAPABILITY = default_cap

    return _response_shape(cfg)


_ALLOWED_ICON_KINDS = ("color", "outline")
_ALLOWED_IMAGE_TYPES = ("image/png", "image/jpeg")


@router.post("/icon/{kind}")
async def upload_icon(
    kind: str,
    request: Request,
    file: UploadFile = FastAPIFile(...),
    user=Depends(get_admin_user),
):
    """Teams 매니페스트 아이콘 업로드.
    kind: 'color' (192x192 권장) | 'outline' (32x32 흰색 실루엣 권장).
    PNG/JPEG 만 허용. 최대 200KB (Teams 매니페스트 제한 고려).
    """
    if kind not in _ALLOWED_ICON_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"icon kind must be one of {_ALLOWED_ICON_KINDS}",
        )
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"only png/jpeg allowed, got {content_type}",
        )
    data = await file.read()
    if len(data) > 200 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="icon file too large (max 200KB)",
        )
    data_url = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    cfg = request.app.state.config
    if kind == "color":
        cfg.TEAMS_BOT_COLOR_ICON = data_url
    else:
        cfg.TEAMS_BOT_OUTLINE_ICON = data_url
    return {"ok": True, "kind": kind, "bytes": len(data)}


@router.get("/icon/{kind}")
async def get_icon(kind: str, request: Request, user=Depends(get_admin_user)):
    """미리보기용 — 업로드된 아이콘을 이미지로 반환. 없으면 404."""
    if kind not in _ALLOWED_ICON_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"icon kind must be one of {_ALLOWED_ICON_KINDS}",
        )
    cfg = request.app.state.config
    data = _decode_icon(cfg, kind)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no icon")
    # 업로드 시 png/jpeg 허용했으나 저장 시 mime 을 data url prefix 에 보관하므로 추출
    key = "TEAMS_BOT_COLOR_ICON" if kind == "color" else "TEAMS_BOT_OUTLINE_ICON"
    data_url = _value(cfg, key, "")
    mime = "image/png"
    if isinstance(data_url, str) and data_url.startswith("data:"):
        mime = data_url.split(";", 1)[0][5:] or "image/png"
    return Response(content=data, media_type=mime)


@router.delete("/icon/{kind}")
async def delete_icon(kind: str, request: Request, user=Depends(get_admin_user)):
    """아이콘 제거 → 기본 Cloosphere 로고로 복원."""
    if kind not in _ALLOWED_ICON_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"icon kind must be one of {_ALLOWED_ICON_KINDS}",
        )
    cfg = request.app.state.config
    if kind == "color":
        cfg.TEAMS_BOT_COLOR_ICON = ""
    else:
        cfg.TEAMS_BOT_OUTLINE_ICON = ""
    return {"ok": True, "kind": kind}


@router.get("/messaging-endpoint")
async def get_messaging_endpoint(request: Request, user=Depends(get_admin_user)):
    """Azure Bot Messaging endpoint 에 등록할 전체 URL 계산.
    우선순위:
      1) env CLOOSPHERE_PUBLIC_URL (관리자가 public HTTPS 도메인 명시한 경우)
      2) request host header 기반 자동 계산
    """
    public_url = os.environ.get("CLOOSPHERE_PUBLIC_URL", "").strip().rstrip("/")
    if not public_url:
        scheme = request.url.scheme
        host = request.headers.get("host") or request.url.hostname or ""
        public_url = f"{scheme}://{host}"
    return {
        "messaging_endpoint": f"{public_url}/api/v1/teams/messages",
        "public_base": public_url,
    }


def _find_teams_app_assets() -> Optional[Path]:
    """repo 에 체크인된 teams_app/ 폴더 위치 탐지. 없으면 None."""
    candidates = [
        Path("/cloosphere/teams_app"),
        Path(__file__).resolve().parent.parent.parent.parent / "teams_app",
    ]
    for p in candidates:
        if p.is_dir() and (p / "manifest.json").is_file():
            return p
    return None


def _derive_valid_domains(request: Optional[Request]) -> list[str]:
    """매니페스트 validDomains 자동 산출.
    - CLOOSPHERE_PUBLIC_URL / WEBUI_URL env 의 호스트
    - 요청 Host 헤더 (없으면 스킵)
    https 도메인 화이트리스트로, 카드 내 외부 링크 렌더링 허용 대상.
    """
    from urllib.parse import urlparse

    hosts: list[str] = []

    def _push(url: str) -> None:
        if not url:
            return
        try:
            u = urlparse(url if "://" in url else "https://" + url)
            host = (u.hostname or "").strip()
        except Exception:
            return
        if host and host not in hosts and host not in ("localhost", "127.0.0.1"):
            hosts.append(host)

    for env_name in ("CLOOSPHERE_PUBLIC_URL", "WEBUI_URL"):
        _push(os.environ.get(env_name, ""))
    if request is not None:
        _push(request.headers.get("host") or "")
    return hosts


def _build_manifest_dict(cfg, app_id: str, request: Optional[Request] = None) -> dict:
    """관리자 설정을 반영한 Teams manifest v1.17 dict 생성. 빈 값은 기본값 사용."""
    name = _value(cfg, "TEAMS_BOT_NAME", "") or _DEFAULT_BRANDING["name"]
    desc_short = (
        _value(cfg, "TEAMS_BOT_DESCRIPTION_SHORT", "")
        or _DEFAULT_BRANDING["description_short"]
    )
    desc_full = (
        _value(cfg, "TEAMS_BOT_DESCRIPTION_FULL", "")
        or _DEFAULT_BRANDING["description_full"]
    )
    dev_name = (
        _value(cfg, "TEAMS_BOT_DEVELOPER_NAME", "")
        or _DEFAULT_BRANDING["developer_name"]
    )
    dev_website = (
        _value(cfg, "TEAMS_BOT_DEVELOPER_WEBSITE", "")
        or _DEFAULT_BRANDING["developer_website"]
    )

    scopes = _normalize_scopes(_value(cfg, "TEAMS_BOT_SCOPES", ["personal"]))
    accent = (
        _value(cfg, "TEAMS_BOT_ACCENT_COLOR", "") or _DEFAULT_BRANDING["accent_color"]
    )
    default_cap = (
        (_value(cfg, "TEAMS_BOT_DEFAULT_GROUP_CAPABILITY", "") or "").strip().lower()
    )
    if default_cap and default_cap not in _ALLOWED_GROUP_CAPABILITY:
        default_cap = ""

    # scope 별 RSC permissions 자동 수집
    rsc_perms: list[dict] = []
    for s in scopes:
        for perm in _SCOPE_RSC_PERMISSIONS.get(s, []):
            if perm not in rsc_perms:
                rsc_perms.append(perm)

    commands = [
        {"title": "agent", "description": "Select a Cloosphere agent"},
        {"title": "current", "description": "Show the selected agent"},
        {"title": "reset", "description": "Clear the current conversation context"},
        {
            "title": "lang",
            "description": "Change language (e.g. /lang en, /lang ko)",
        },
        {"title": "help", "description": "Show available commands"},
    ]

    manifest: dict = {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
        "manifestVersion": "1.17",
        "version": _DEFAULT_BRANDING["version"],
        "id": app_id,
        "developer": {
            "name": dev_name,
            "websiteUrl": dev_website,
            "privacyUrl": dev_website.rstrip("/") + "/privacy"
            if dev_website
            else _DEFAULT_BRANDING["developer_privacy"],
            "termsOfUseUrl": dev_website.rstrip("/") + "/terms"
            if dev_website
            else _DEFAULT_BRANDING["developer_terms"],
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "name": {"short": name[:30], "full": name[:100]},
        "description": {
            "short": desc_short[:80],
            "full": desc_full[:4000],
        },
        "accentColor": accent,
        "bots": [
            {
                "botId": app_id,
                "scopes": scopes,
                "supportsFiles": False,
                "isNotificationOnly": False,
                "commandLists": [{"scopes": scopes, "commands": commands}],
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": _derive_valid_domains(request),
    }

    # 다중 scope 일 때만 defaultGroupCapability 의미 있음
    if default_cap and len(scopes) > 1:
        manifest["defaultGroupCapability"] = default_cap

    # team/groupchat scope 선택 시 RSC 권한 선언 — 없으면 채널/그룹챗에서 메시지 못 읽음
    if rsc_perms:
        manifest["authorization"] = {"permissions": {"resourceSpecific": rsc_perms}}

    return manifest


@router.get("/manifest.zip")
async def download_manifest(request: Request, user=Depends(get_admin_user)):
    """현재 config 를 바탕으로 Teams manifest.zip 스트리밍 반환."""
    cfg = request.app.state.config
    app_id = (_value(cfg, "TEAMS_BOT_APP_ID", "") or "").strip()
    if not app_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TEAMS_BOT_APP_ID is not set. Save the config first.",
        )

    # 아이콘: 업로드된 것 우선, 없으면 teams_app/ 기본값.
    color_bytes = _decode_icon(cfg, "color")
    outline_bytes = _decode_icon(cfg, "outline")

    if color_bytes is None or outline_bytes is None:
        assets_dir = _find_teams_app_assets()
        if assets_dir is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No uploaded icons and default teams_app/ assets not found.",
            )
        if color_bytes is None:
            color_path = assets_dir / "color.png"
            if not color_path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Default color.png missing.",
                )
            color_bytes = color_path.read_bytes()
        if outline_bytes is None:
            outline_path = assets_dir / "outline.png"
            if not outline_path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Default outline.png missing.",
                )
            outline_bytes = outline_path.read_bytes()

    try:
        manifest_dict = _build_manifest_dict(cfg, app_id, request)
        manifest_body = json.dumps(manifest_dict, ensure_ascii=False, indent=2)
    except Exception as e:
        log.exception("[teams_bot_config] manifest build failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Manifest build failed: {e}",
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", manifest_body)
        z.writestr("color.png", color_bytes)
        z.writestr("outline.png", outline_bytes)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="cloosphere-teams.zip"',
        },
    )
