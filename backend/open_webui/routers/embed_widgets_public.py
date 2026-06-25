"""Public (unauthenticated / cross-origin) endpoints for embed widgets.

호스트 사이트(외부 웹)에서 호출되는 엔드포인트를 모아둔 라우터.
CORS `*` 허용 + 위젯 단위 allowed_domains 검증이 보안 경계.
관리자 CRUD 는 `embed_widgets_admin.py` 참조.
"""

import fnmatch
import logging
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from extension_modules.embed_sso import (
    SSOExchangeRequest,
    SSOUserClaims,
    get_sso_provider,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.auths import Auths
from open_webui.models.embed_widgets import EmbedWidgets
from open_webui.models.models import Model
from open_webui.models.users import Users
from open_webui.utils.auth import create_token, get_password_hash
from open_webui.utils.license import require_feature
from open_webui.utils.misc import parse_duration
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("embed_widget"))])


############################
# Helpers
############################


def _check_domain_allowed(request: Request, allowed_domains: list[str]) -> bool:
    """Validate request origin against allowed domains list."""
    if not allowed_domains:
        return True

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return True

    try:
        parsed = urlparse(origin)
        hostname = parsed.hostname or ""
    except Exception:
        return False

    for pattern in allowed_domains:
        if fnmatch.fnmatch(hostname, pattern):
            return True

    return False


def _cors_response(content: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "*",
        },
    )


def _cors_preflight(methods: str) -> Response:
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": f"{methods}, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        },
    )


############################
# Widget Config (Public)
############################


@router.options("/id/{id}/config")
async def get_embed_widget_config_options(id: str):
    return _cors_preflight("GET")


@router.get("/id/{id}/config")
async def get_embed_widget_config(id: str, request: Request):
    """Return widget config for embed rendering (no auth).

    Validates Origin header against `config.allowed_domains`.
    Allows any origin (CORS *) so external sites can fetch.
    """
    widget = EmbedWidgets.get_widget_by_id(id)

    if not widget or not widget.is_active:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": ERROR_MESSAGES.NOT_FOUND},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    allowed_domains = (widget.config or {}).get("allowed_domains", [])
    if not _check_domain_allowed(request, allowed_domains):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": ERROR_MESSAGES.ACCESS_PROHIBITED},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # /command 자동완성에 쓸 에이전트 목록 (기본 model_id + config.allowed_agents 중복 제거)
    cfg = widget.config or {}
    model_ids: list[str] = [widget.model_id]
    for a in cfg.get("allowed_agents") or []:
        if a and a not in model_ids:
            model_ids.append(a)

    agents: list[dict[str, Any]] = []
    if model_ids:
        with get_db() as db:
            rows = db.query(Model).filter(Model.id.in_(model_ids)).all()
        by_id = {m.id: m for m in rows}
        for mid in model_ids:
            m = by_id.get(mid)
            if m:
                meta = {}
                if isinstance(m.meta, dict):
                    meta = m.meta
                elif hasattr(m.meta, "model_dump"):
                    meta = m.meta.model_dump()
                agents.append(
                    {
                        "id": m.id,
                        "name": m.name or m.id,
                        "profile_image_url": meta.get("profile_image_url") or "",
                    }
                )
            else:
                agents.append({"id": mid, "name": mid, "profile_image_url": ""})

    return JSONResponse(
        content={
            "id": widget.id,
            "name": widget.name,
            "model_id": widget.model_id,
            "agents": agents,
            "config": widget.config,
            "is_active": widget.is_active,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


############################
# SSO Token Exchange (Public)
############################


class SSOExchangeBody(BaseModel):
    """Request body for `POST /id/{id}/auth/sso-exchange`."""

    provider: str
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    issuer: Optional[str] = None


def _match_or_create_user(
    claims: SSOUserClaims,
    provider_name: str,
    sso_config: dict[str, Any],
):
    """Look up an existing user by oauth_sub/email, or create one if allowed."""
    provider_sub = f"{provider_name}@{claims.sub}"

    user = Users.get_user_by_oauth_sub(provider_sub)

    if not user and sso_config.get("match_by", "email") == "email":
        existing = Users.get_user_by_email(claims.email)
        if existing:
            Users.update_user_oauth_sub_by_id(existing.id, provider_sub)
            user = Users.get_user_by_id(existing.id)

    if user:
        return user

    if not sso_config.get("auto_signup", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "User is not registered and auto-signup is disabled for this widget"
            ),
        )

    default_role = sso_config.get("default_role", "user")
    if default_role not in ("pending", "user", "admin"):
        default_role = "user"

    name = claims.name or claims.email.split("@")[0]
    picture_url = claims.picture or "/user.png"

    new_user = Auths.insert_new_auth(
        email=claims.email,
        password=get_password_hash(str(uuid.uuid4())),
        name=name,
        profile_image_url=picture_url,
        role=default_role,
        oauth_sub=provider_sub,
    )

    if not new_user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Failed to provision user"),
        )

    log.info(
        f"[embed-sso] auto-provisioned user via {provider_name}: "
        f"{claims.email} (role={default_role})"
    )
    return new_user


@router.options("/id/{id}/auth/sso-exchange")
async def sso_exchange_options(id: str):
    return _cors_preflight("POST")


@router.post("/id/{id}/auth/sso-exchange")
async def sso_exchange(id: str, body: SSOExchangeBody, request: Request):
    """Exchange a host-site SSO token for a Cloosphere JWT.

    호스트 사이트가 이미 보유한 SSO 토큰(예: Microsoft Entra ID id_token)을
    검증하고, 매칭되는 사용자를 찾거나 자동 가입시킨 뒤 Cloosphere JWT를 반환.
    위젯의 `config.sso` 설정으로 동작이 제어된다.
    """
    widget = EmbedWidgets.get_widget_by_id(id)
    if not widget or not widget.is_active:
        return _cors_response(
            {"detail": ERROR_MESSAGES.NOT_FOUND}, status.HTTP_404_NOT_FOUND
        )

    allowed_domains = (widget.config or {}).get("allowed_domains", [])
    if not _check_domain_allowed(request, allowed_domains):
        return _cors_response(
            {"detail": ERROR_MESSAGES.ACCESS_PROHIBITED},
            status.HTTP_403_FORBIDDEN,
        )

    sso_config: dict[str, Any] = (widget.config or {}).get("sso") or {}
    if not sso_config.get("enabled"):
        return _cors_response(
            {"detail": "SSO is not enabled for this widget"},
            status.HTTP_403_FORBIDDEN,
        )

    allowed_providers = sso_config.get("providers") or []
    if "*" not in allowed_providers and body.provider not in allowed_providers:
        return _cors_response(
            {"detail": (f"Provider '{body.provider}' is not allowed for this widget")},
            status.HTTP_403_FORBIDDEN,
        )

    provider_options = (sso_config.get("provider_options") or {}).get(body.provider, {})

    try:
        provider = get_sso_provider(body.provider, provider_options)
        claims = await provider.verify(
            SSOExchangeRequest(
                provider=body.provider,
                id_token=body.id_token,
                access_token=body.access_token,
                issuer=body.issuer or provider_options.get("issuer"),
            )
        )
    except ValueError as e:
        log.warning(f"[embed-sso] verification failed: {e}")
        return _cors_response(
            {"detail": f"Token verification failed: {e}"},
            status.HTTP_401_UNAUTHORIZED,
        )
    except Exception as e:
        log.exception(f"[embed-sso] unexpected error during verification: {e}")
        return _cors_response(
            {"detail": "Internal error during token verification"},
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        user = _match_or_create_user(claims, body.provider, sso_config)
    except HTTPException as e:
        return _cors_response({"detail": e.detail}, e.status_code)

    cfg = request.app.state.config
    expires_in = getattr(cfg, "JWT_EXPIRES_IN", "24h") or "24h"
    expires_delta = parse_duration(expires_in)

    jwt_token = create_token(
        data={"id": user.id},
        expires_delta=expires_delta,
    )

    return _cors_response(
        {
            "token": jwt_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "profile_image_url": user.profile_image_url,
            },
        }
    )


############################
# Guest Token Exchange (Public)
############################


class GuestExchangeBody(BaseModel):
    """Request body for `POST /id/{id}/auth/guest`."""

    guest_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    origin_url: Optional[str] = None
    referrer: Optional[str] = None
    user_context: Optional[dict] = None


def _match_or_create_guest(widget_id: str, body: GuestExchangeBody) -> Any:
    """게스트 사용자 조회/생성.

    매핑 키 우선순위: guest_id > email > anonymous(매번 새 유저).
    같은 위젯 + 같은 키 → 기존 유저 재사용.
    """
    if body.guest_id:
        oauth_sub = f"embed_guest@{widget_id}:{body.guest_id}"
    elif body.email:
        oauth_sub = f"embed_guest@{widget_id}:{body.email}"
    else:
        anon_id = str(uuid.uuid4())[:8]
        oauth_sub = f"embed_guest@{widget_id}:anon:{anon_id}"

    user = Users.get_user_by_oauth_sub(oauth_sub)

    if not user:
        email = body.email or f"guest_{oauth_sub.split(':')[-1]}@embed.local"
        name = body.name or "Guest"

        user = Auths.insert_new_auth(
            email=email,
            password=get_password_hash(str(uuid.uuid4())),
            name=name,
            profile_image_url="/user.png",
            role="user",
            oauth_sub=oauth_sub,
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT("Failed to create guest user"),
            )

        log.info(
            f"[embed-guest] created guest user: {email} "
            f"(widget={widget_id}, oauth_sub={oauth_sub})"
        )
    else:
        if body.name and body.name != user.name:
            Users.update_user_by_id(user.id, {"name": body.name})

    info = {
        "embed_guest": True,
        "widget_id": widget_id,
        "origin_url": body.origin_url,
        "referrer": body.referrer,
        "user_context": body.user_context,
    }
    Users.update_user_by_id(user.id, {"info": info})

    return user


@router.options("/id/{id}/auth/guest")
async def guest_exchange_options(id: str):
    return _cors_preflight("POST")


@router.post("/id/{id}/auth/guest")
async def guest_exchange(id: str, body: GuestExchangeBody, request: Request):
    """비로그인 게스트에게 Cloosphere JWT를 발급한다.

    호스트 사이트가 자체 인증 정보(이름, 이메일 등)를 전달하면
    게스트 유저를 생성/재사용하고, 출처(origin_url, referrer)와
    사용자 컨텍스트를 user.info에 기록한다.
    위젯의 `config.guest.enabled` 설정으로 동작이 제어된다.
    """
    widget = EmbedWidgets.get_widget_by_id(id)
    if not widget or not widget.is_active:
        return _cors_response(
            {"detail": ERROR_MESSAGES.NOT_FOUND}, status.HTTP_404_NOT_FOUND
        )

    allowed_domains = (widget.config or {}).get("allowed_domains", [])
    if not _check_domain_allowed(request, allowed_domains):
        return _cors_response(
            {"detail": ERROR_MESSAGES.ACCESS_PROHIBITED},
            status.HTTP_403_FORBIDDEN,
        )

    guest_config: dict[str, Any] = (widget.config or {}).get("guest") or {}
    if not guest_config.get("enabled"):
        return _cors_response(
            {"detail": "Guest mode is not enabled for this widget"},
            status.HTTP_403_FORBIDDEN,
        )

    try:
        user = _match_or_create_guest(id, body)
    except HTTPException as e:
        return _cors_response({"detail": e.detail}, e.status_code)

    expires_in = guest_config.get("jwt_expires_in", "24h") or "24h"
    expires_delta = parse_duration(expires_in)

    jwt_token = create_token(
        data={"id": user.id},
        expires_delta=expires_delta,
    )

    try:
        from open_webui.models.audit_log import AuditAction
        from open_webui.utils.audit_logger import AuditLogger

        AuditLogger.log_auth_event(
            action=AuditAction.GUEST_SESSION,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            success=True,
            meta={
                "widget_id": id,
                "widget_name": widget.name,
                "origin_url": body.origin_url,
                "referrer": body.referrer,
                "user_context": body.user_context,
            },
        )
    except Exception as e:
        log.warning(f"[embed-guest] audit log failed: {e}")

    return _cors_response(
        {
            "token": jwt_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "profile_image_url": user.profile_image_url,
            },
        }
    )
