import base64
import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Union

import bcrypt
import jwt
import requests
from fastapi import BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    SRC_LOG_LEVELS,
    STATIC_DIR,
    TRUSTED_SIGNATURE_KEY,
    WEBUI_SECRET_KEY,
)
from open_webui.models.users import Users
from open_webui.utils.audit_middleware import update_audit_context_user
from pytz import UTC

logging.getLogger("passlib").setLevel(logging.ERROR)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OAUTH"])

SESSION_SECRET = WEBUI_SECRET_KEY
ALGORITHM = "HS256"

##############
# Auth Utils
##############


def verify_signature(payload: str, signature: str) -> bool:
    """
    Verifies the HMAC signature of the received payload.
    """
    try:
        expected_signature = base64.b64encode(
            hmac.new(TRUSTED_SIGNATURE_KEY, payload.encode(), hashlib.sha256).digest()
        ).decode()

        # Compare securely to prevent timing attacks
        return hmac.compare_digest(expected_signature, signature)

    except Exception:
        return False


def override_static(path: str, content: str):
    # Ensure path is safe
    if "/" in path or ".." in path:
        log.error(f"Invalid path: {path}")
        return

    file_path = os.path.join(STATIC_DIR, path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(base64.b64decode(content))  # Convert Base64 back to raw binary


def get_license_data(app, key):
    if key:
        try:
            res = requests.post(
                "https://api.openwebui.com/api/v1/license/",
                json={"key": key, "version": "1"},
                timeout=5,
            )

            if getattr(res, "ok", False):
                payload = getattr(res, "json", lambda: {})()
                for k, v in payload.items():
                    if k == "resources":
                        for p, c in v.items():
                            globals().get("override_static", lambda a, b: None)(p, c)
                    elif k == "count":
                        setattr(app.state, "USER_COUNT", v)
                    elif k == "name":
                        setattr(app.state, "WEBUI_NAME", v)
                    elif k == "metadata":
                        setattr(app.state, "LICENSE_METADATA", v)
                return True
            else:
                log.error(
                    f"License: retrieval issue: {getattr(res, 'text', 'unknown error')}"
                )
        except Exception as ex:
            log.exception(f"License: Uncaught Exception: {ex}")
    return False


bearer_security = HTTPBearer(auto_error=False)


def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_token(data: dict, expires_delta: Union[timedelta, None] = None) -> str:
    payload = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        payload.update({"exp": expire})

    encoded_jwt = jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    try:
        decoded = jwt.decode(token, SESSION_SECRET, algorithms=[ALGORITHM])
        return decoded
    except Exception:
        return None


def extract_token_from_auth_header(auth_header: str):
    return auth_header[len("Bearer ") :]


def create_api_key():
    key = str(uuid.uuid4()).replace("-", "")
    return f"sk-{key}"


def get_http_authorization_cred(auth_header: Optional[str]):
    if not auth_header:
        return None
    try:
        scheme, credentials = auth_header.split(" ")
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)
    except Exception:
        return None


def get_current_user(
    request: Request,
    background_tasks: BackgroundTasks,
    auth_token: HTTPAuthorizationCredentials = Depends(bearer_security),
):
    token = None

    if auth_token is not None:
        token = auth_token.credentials

    if token is None and "token" in request.cookies:
        token = request.cookies.get("token")

    if token is None:
        raise HTTPException(status_code=403, detail="Not authenticated")

    # auth by api key
    if token.startswith("sk-"):
        request.state.auth_type = "api_key"

        if not request.state.enable_api_key:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.API_KEY_NOT_ALLOWED
            )

        if request.app.state.config.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS:
            allowed_paths = [
                path.strip()
                for path in str(
                    request.app.state.config.API_KEY_ALLOWED_ENDPOINTS
                ).split(",")
            ]

            # Check if the request path matches any allowed endpoint.
            if not any(
                request.url.path == allowed
                or request.url.path.startswith(allowed + "/")
                for allowed in allowed_paths
            ):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.API_KEY_NOT_ALLOWED
                )

        return get_current_user_by_api_key(token)

    # auth by jwt token
    try:
        data = decode_token(token)
    except Exception:
        data = None

    if data is not None and "id" in data:
        user = Users.get_user_by_id(data["id"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.INVALID_TOKEN,
            )
        else:
            # Refresh the user's last active timestamp asynchronously
            # to prevent blocking the request
            if background_tasks:
                background_tasks.add_task(Users.update_user_last_active_by_id, user.id)

            # Update audit context with user information
            update_audit_context_user(
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
            )
        return user

    # JWT 실패 — 외부 IDP ID 토큰(Entra / Google) passthrough 시도.
    # TrustedAudiences 에 등록된 audience 만 수용. 성공하면 `oauth_oid`/`oauth_sub`/
    # `email` 로 Cloosphere 사용자 매핑. auto_provision 활성화 시 미매칭 사용자 생성.
    external_user = _try_external_id_token(token, request)
    if external_user is not None:
        if background_tasks:
            background_tasks.add_task(
                Users.update_user_last_active_by_id, external_user.id
            )
        update_audit_context_user(
            user_id=external_user.id,
            user_email=external_user.email,
            user_name=external_user.name,
        )
        return external_user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.UNAUTHORIZED,
    )


def _try_external_id_token(token: str, request: Request):
    """외부 IDP ID 토큰 검증 + 사용자 매핑. 실패 시 None (상위가 401 결정).

    실패 경로:
    - 토큰 malformed, audience not trusted, 서명/만료/aud/iss 검증 실패 → None
    - 매칭 사용자 없고 auto_provision 꺼짐 → None
    """
    import logging as _logging

    log = _logging.getLogger(__name__)
    try:
        from open_webui.utils.external_token import (
            ExternalTokenError,
            extract_user_identity,
            verify_external_id_token,
        )
    except Exception:
        return None

    try:
        claims, audience = verify_external_id_token(token)
    except ExternalTokenError as e:
        log.info("[external_token] reject: %s", e)
        return None
    except Exception:
        log.exception("[external_token] unexpected verification error")
        return None

    oid, sub, email, name = extract_user_identity(claims, audience)

    # 사용자 매핑 우선순위: oauth_oid → oauth_sub → email
    user = None
    if oid:
        user = Users.get_user_by_oauth_oid(oid)
    if user is None and sub:
        user = Users.get_user_by_oauth_sub(sub)
    if user is None and email:
        try:
            user = Users.get_user_by_email(email.lower().strip())
        except Exception:
            user = None
        # 기존 사용자와 매칭됐고 oid 가 있는데 저장돼 있지 않으면 백필
        if user is not None and oid and not getattr(user, "oauth_oid", None):
            try:
                Users.update_user_oauth_oid_by_id(user.id, oid)
            except Exception:
                log.exception("[external_token] oauth_oid backfill failed")

    if user is None:
        if not audience.auto_provision:
            log.info(
                "[external_token] no matching user & auto_provision disabled for audience=%s",
                audience.audience[:12],
            )
            return None
        if not email:
            log.info("[external_token] cannot auto-provision without email claim")
            return None
        # 신규 사용자 생성
        import uuid as _uuid

        try:
            user = Users.insert_new_user(
                id=str(_uuid.uuid4()),
                name=name or email.split("@")[0],
                email=email.lower().strip(),
                profile_image_url="/user.png",
                role=audience.default_role or "user",
                oauth_sub=sub,
            )
            if user and oid:
                Users.update_user_oauth_oid_by_id(user.id, oid)
            # default_group_ids 자동 가입
            if user and audience.default_group_ids:
                try:
                    from open_webui.models.groups import Groups

                    for gid in audience.default_group_ids:
                        try:
                            g = Groups.get_group_by_id(gid)
                            if g and user.id not in (g.user_ids or []):
                                Groups.update_group_user_ids_by_id(
                                    gid, list((g.user_ids or []) + [user.id])
                                )
                        except Exception:
                            log.exception(
                                "[external_token] group join failed gid=%s", gid
                            )
                except Exception:
                    log.exception(
                        "[external_token] default_group_ids processing failed"
                    )
        except Exception:
            log.exception("[external_token] auto-provision failed")
            return None

    if user is None:
        return None

    # 감사/로그용 플래그
    try:
        request.state.auth_type = "external_id_token"
        request.state.external_audience = audience.audience
        request.state.external_idp = audience.idp_type
    except Exception:
        pass
    return user


def get_current_user_by_api_key(api_key: str):
    user = Users.get_user_by_api_key(api_key)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.INVALID_TOKEN,
        )
    else:
        Users.update_user_last_active_by_id(user.id)

        # Update audit context with user information
        update_audit_context_user(
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
        )

    return user


def get_verified_user(user=Depends(get_current_user)):
    if user.role not in {"user", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user


def get_admin_user(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user


def get_admin_user_or_permission(permission_key: str):
    """
    Factory function to create a dependency that checks if user is admin
    or has a specific admin permission via group membership.

    Usage:
        @router.get("/users")
        async def get_users(user=Depends(get_admin_user_or_permission("admin.users"))):
            ...
    """
    from open_webui.config import DEFAULT_USER_PERMISSIONS
    from open_webui.utils.access_control import has_permission

    def check_permission(user=Depends(get_current_user)):
        # Admin role has full access
        if user.role == "admin":
            return user

        # Check group-based permission
        if has_permission(user.id, permission_key, DEFAULT_USER_PERMISSIONS):
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    return check_permission


def get_admin_user_or_permission_level(permission_key: str, min_level: str):
    """
    Factory function to create a dependency that checks if user is admin
    or has a specific admin permission at the given minimum level.

    Args:
        permission_key: 점 구분 권한 키 (예: "admin.users")
        min_level: 최소 요구 레벨 ("access" | "read" | "write")
    """
    from open_webui.config import DEFAULT_USER_PERMISSIONS
    from open_webui.utils.access_control import has_permission_min_level

    def check_permission(user=Depends(get_current_user)):
        if user.role == "admin":
            return user

        if has_permission_min_level(
            user.id, permission_key, min_level, DEFAULT_USER_PERMISSIONS
        ):
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    return check_permission


# Pre-built dependencies for admin panel sections (기존 호환용 - write 레벨)
get_admin_users_access = get_admin_user_or_permission("admin.users")
get_admin_evaluations_access = get_admin_user_or_permission("admin.evaluations")
get_admin_functions_access = get_admin_user_or_permission("admin.functions")
get_admin_settings_access = get_admin_user_or_permission("admin.settings")
get_admin_monitoring_access = get_admin_user_or_permission("admin.monitoring")

# read 레벨 의존성
get_admin_users_read_access = get_admin_user_or_permission_level("admin.users", "read")
get_admin_evaluations_read_access = get_admin_user_or_permission_level(
    "admin.evaluations", "read"
)
get_admin_functions_read_access = get_admin_user_or_permission_level(
    "admin.functions", "read"
)
get_admin_settings_read_access = get_admin_user_or_permission_level(
    "admin.settings", "read"
)
get_admin_monitoring_read_access = get_admin_user_or_permission_level(
    "admin.monitoring", "read"
)

# write 레벨 의존성
get_admin_users_write_access = get_admin_user_or_permission_level(
    "admin.users", "write"
)
get_admin_evaluations_write_access = get_admin_user_or_permission_level(
    "admin.evaluations", "write"
)
get_admin_functions_write_access = get_admin_user_or_permission_level(
    "admin.functions", "write"
)
get_admin_settings_write_access = get_admin_user_or_permission_level(
    "admin.settings", "write"
)
get_admin_monitoring_write_access = get_admin_user_or_permission_level(
    "admin.monitoring", "write"
)
