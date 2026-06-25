import logging
import time
from typing import Optional

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.config import (
    ENABLE_LICENSE_ENFORCEMENT,
    FEATURE_KEYS,
    LICENSE_KEYS,
)
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.license import (
    LicenseStatus,
    _decode_any_key,
    decode_feature_key,
    decode_license_key,
    get_tier_modules,
    resolve_license_status,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


####################################
# Request / Response Models
####################################


class RegisterKeyForm(BaseModel):
    key: str


class RegisterKeyResponse(BaseModel):
    success: bool
    type: Optional[str] = None
    payload: Optional[dict] = None
    error: Optional[str] = None


class DeleteKeyForm(BaseModel):
    key: str


####################################
# Helpers
####################################


_LICENSE_STATUS_VERSION_KEY = "open-webui:license:status_version"


def _refresh_license_status(app):
    """Re-resolve license status and update app state.

    Also publishes a version marker to Redis so other workers
    can detect the change and lazy-refresh their own LICENSE_STATUS.
    Reads config through AppConfig to get Redis-synced values.
    """
    # Read through AppConfig (Redis-synced) when available, fallback to module-level
    config = getattr(app.state, "config", None)
    license_keys = getattr(config, "LICENSE_KEYS", None) if config else None
    feature_keys = getattr(config, "FEATURE_KEYS", None) if config else None
    enforcement = (
        getattr(config, "ENABLE_LICENSE_ENFORCEMENT", None) if config else None
    )

    license_status = resolve_license_status(
        license_keys=license_keys if license_keys is not None else LICENSE_KEYS.value,
        feature_keys=feature_keys if feature_keys is not None else FEATURE_KEYS.value,
        enforcement_enabled=enforcement
        if enforcement is not None
        else ENABLE_LICENSE_ENFORCEMENT.value,
        tier_modules=get_tier_modules(),
    )
    app.state.LICENSE_STATUS = license_status

    # Notify other workers via Redis version bump
    redis_client = getattr(getattr(app.state, "config", None), "_redis", None)
    if redis_client:
        try:
            version = str(int(time.time() * 1000))
            redis_client.set(_LICENSE_STATUS_VERSION_KEY, version)
            app.state._license_status_version = version
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, skipping license version bump: {e}")

    return license_status


def ensure_license_status_fresh(app):
    """Check Redis for license config changes from other workers and refresh if stale.

    Called before reading app.state.LICENSE_STATUS in multi-worker deployments.
    No-op when Redis is not configured (single-worker mode).
    """
    redis_client = getattr(getattr(app.state, "config", None), "_redis", None)
    if not redis_client:
        return

    try:
        redis_version = redis_client.get(_LICENSE_STATUS_VERSION_KEY)
    except (redis.ConnectionError, redis.TimeoutError) as e:
        log.warning(f"Redis unavailable, skipping license freshness check: {e}")
        return

    local_version = getattr(app.state, "_license_status_version", None)

    if redis_version and redis_version != local_version:
        # Read latest values through AppConfig (Redis-synced)
        license_keys = app.state.config.LICENSE_KEYS
        feature_keys = app.state.config.FEATURE_KEYS
        enforcement_enabled = app.state.config.ENABLE_LICENSE_ENFORCEMENT

        license_status = resolve_license_status(
            license_keys=license_keys,
            feature_keys=feature_keys,
            enforcement_enabled=enforcement_enabled,
            tier_modules=get_tier_modules(),
        )
        app.state.LICENSE_STATUS = license_status
        app.state._license_status_version = redis_version


####################################
# Endpoints
####################################


@router.get("/status", response_model=LicenseStatus)
async def get_license_status(request: Request, user=Depends(get_admin_user)):
    """Get full license status including key details (admin only)."""
    ensure_license_status_fresh(request.app)
    return getattr(request.app.state, "LICENSE_STATUS", LicenseStatus())


@router.get("/permissions")
async def get_license_permissions(request: Request, user=Depends(get_verified_user)):
    """Get feature permissions for the current license (all authenticated users).

    Returns a flat dict of module → enabled boolean, plus legacy compat fields.
    """
    ensure_license_status_fresh(request.app)
    license_status: LicenseStatus = getattr(
        request.app.state, "LICENSE_STATUS", LicenseStatus()
    )

    return {
        "permissions": license_status.permissions,
        "has_license": license_status.has_license,
        "tier": license_status.tier,
        "enforcement_enabled": license_status.enforcement_enabled,
        # Legacy compat fields (for license_permissions API)
        "enhanced_kbsphere": license_status.permissions.get("kbsphere", False)
        or not license_status.enforcement_enabled,
        "enhanced_dbsphere": license_status.permissions.get("dbsphere", False)
        or not license_status.enforcement_enabled,
        "enhanced_tool_use": not license_status.enforcement_enabled
        or license_status.has_license,
    }


@router.post("/register", response_model=RegisterKeyResponse)
async def register_key(
    request: Request,
    form_data: RegisterKeyForm,
    user=Depends(get_admin_user),
):
    """Register a license or feature key.

    Automatically determines key type by decoding the JWT payload.
    """
    token = form_data.key.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key cannot be empty",
        )

    # Decode to determine type
    data, error = _decode_any_key(token)
    if error:
        return RegisterKeyResponse(success=False, error=error)

    key_type = data.get("type")

    if key_type == "license":
        payload, err = decode_license_key(token)
        if err:
            return RegisterKeyResponse(success=False, error=err)

        # Check for duplicate
        current_keys = request.app.state.config.LICENSE_KEYS
        if token in current_keys:
            return RegisterKeyResponse(
                success=False, error="This license key is already registered"
            )

        request.app.state.config.LICENSE_KEYS = current_keys + [token]

        _refresh_license_status(request.app)

        return RegisterKeyResponse(
            success=True,
            type="license",
            payload=payload.model_dump(),
        )

    elif key_type == "feature":
        payload, err = decode_feature_key(token)
        if err:
            return RegisterKeyResponse(success=False, error=err)

        # Check for duplicate
        current_fkeys = request.app.state.config.FEATURE_KEYS
        if token in current_fkeys:
            return RegisterKeyResponse(
                success=False, error="This feature key is already registered"
            )

        request.app.state.config.FEATURE_KEYS = current_fkeys + [token]

        _refresh_license_status(request.app)

        return RegisterKeyResponse(
            success=True,
            type="feature",
            payload=payload.model_dump(),
        )

    else:
        return RegisterKeyResponse(
            success=False,
            error=f"Unknown key type: {key_type}",
        )


@router.delete("/key")
async def delete_key(
    request: Request,
    form_data: DeleteKeyForm,
    user=Depends(get_admin_user),
):
    """Delete a registered license or feature key."""
    token = form_data.key.strip()
    deleted = False

    current_lkeys = request.app.state.config.LICENSE_KEYS
    if token in current_lkeys:
        request.app.state.config.LICENSE_KEYS = [k for k in current_lkeys if k != token]
        deleted = True

    current_fkeys = request.app.state.config.FEATURE_KEYS
    if token in current_fkeys:
        request.app.state.config.FEATURE_KEYS = [k for k in current_fkeys if k != token]
        deleted = True

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Key not found",
        )

    _refresh_license_status(request.app)

    return {"success": True}


@router.post("/enforcement")
async def set_enforcement(
    request: Request,
    user=Depends(get_admin_user),
):
    """Toggle license enforcement on/off."""

    class EnforcementForm(BaseModel):
        enabled: bool

    # Re-parse from request body
    body = await request.json()
    form = EnforcementForm(**body)

    request.app.state.config.ENABLE_LICENSE_ENFORCEMENT = form.enabled

    _refresh_license_status(request.app)

    return {"success": True, "enforcement_enabled": form.enabled}
