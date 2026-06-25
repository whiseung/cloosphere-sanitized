import logging
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from open_webui.config import DATA_DIR, STATIC_DIR
from open_webui.env import SRC_LOG_LEVELS
from open_webui.env import WEBUI_NAME as DEFAULT_WEBUI_NAME
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user
from open_webui.utils.license import require_feature

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

BRAND_DIR = DATA_DIR / "brand"
BRAND_DIR.mkdir(parents=True, exist_ok=True)

# Asset type → (config_key, static_fallback)
ASSET_MAP = {
    "favicon": ("BRANDING_FAVICON_URL", "favicon.png"),
    "favicon-dark": ("BRANDING_FAVICON_DARK_URL", "favicon-dark.png"),
    "logo": ("BRANDING_LOGO_URL", "logo.png"),
    "splash": ("BRANDING_SPLASH_URL", "splash.png"),
    "splash-dark": ("BRANDING_SPLASH_DARK_URL", "splash-dark.png"),
    "browser-favicon": ("BRANDING_BROWSER_FAVICON_URL", "favicon.png"),
}

# ICO MIME type mapping (some systems don't register it)
ICO_MIME_TYPES = {"image/x-icon", "image/vnd.microsoft.icon"}


def _get_config_value(request: Request, config_key: str) -> str:
    val = getattr(request.app.state.config, config_key, "")
    if hasattr(val, "value"):
        return val.value or ""
    return val or ""


@router.get("/config", dependencies=[Depends(require_feature("branding"))])
async def get_branding_config(request: Request, user=Depends(get_admin_user)):
    result = {
        "app_name": request.app.state.WEBUI_NAME,
    }
    for asset_type, (config_key, _) in ASSET_MAP.items():
        file_path = _get_config_value(request, config_key)
        result[asset_type] = {
            "is_custom": bool(file_path),
            "url": f"/api/v1/branding/{asset_type}",
        }
    return result


@router.post("/app-name", dependencies=[Depends(require_feature("branding"))])
async def update_app_name(request: Request, body: dict, user=Depends(get_admin_user)):
    name = (body.get("name") or "").strip()
    request.app.state.config.BRANDING_APP_NAME = name
    request.app.state.WEBUI_NAME = name if name else DEFAULT_WEBUI_NAME
    AuditLogger.log_settings_change(
        "branding/app-name", after_data={"app_name": request.app.state.WEBUI_NAME}
    )
    return {"app_name": request.app.state.WEBUI_NAME}


def _serve_static_fallback(fallback: str):
    """Serve the default static file directly."""
    static_path = str(STATIC_DIR / fallback)
    content_type, _ = mimetypes.guess_type(static_path)
    return FileResponse(
        static_path,
        media_type=content_type or "image/png",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/{asset_type}")
async def get_branding_asset(request: Request, asset_type: str):
    if asset_type not in ASSET_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown asset type: {asset_type}",
        )

    config_key, fallback = ASSET_MAP[asset_type]
    file_name = _get_config_value(request, config_key)

    if not file_name:
        return _serve_static_fallback(fallback)

    local_path = BRAND_DIR / file_name
    if not local_path.is_file():
        log.warning(f"Branding file not found: {local_path}, falling back to static")
        return _serve_static_fallback(fallback)

    content_type, _ = mimetypes.guess_type(str(local_path))
    if not content_type:
        ext = local_path.suffix.lower()
        content_type = {".ico": "image/x-icon", ".svg": "image/svg+xml"}.get(
            ext, "image/png"
        )
    return FileResponse(
        str(local_path),
        media_type=content_type,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.post(
    "/upload/{asset_type}", dependencies=[Depends(require_feature("branding"))]
)
async def upload_branding_asset(
    request: Request,
    asset_type: str,
    file: UploadFile,
    user=Depends(get_admin_user),
):
    if asset_type not in ASSET_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown asset type: {asset_type}",
        )

    config_key, _ = ASSET_MAP[asset_type]
    suffix = Path(file.filename).suffix if file.filename else ".png"
    file_name = f"{asset_type}{suffix}"

    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    local_path = BRAND_DIR / file_name
    with open(local_path, "wb") as f:
        f.write(contents)

    setattr(request.app.state.config, config_key, file_name)

    AuditLogger.log_settings_change(
        f"branding/upload/{asset_type}",
        after_data={"asset_type": asset_type, "file_name": file_name},
    )
    return {"status": "ok", "file_name": file_name}


@router.delete("/{asset_type}", dependencies=[Depends(require_feature("branding"))])
async def delete_branding_asset(
    request: Request,
    asset_type: str,
    user=Depends(get_admin_user),
):
    if asset_type not in ASSET_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown asset type: {asset_type}",
        )

    config_key, _ = ASSET_MAP[asset_type]
    file_name = _get_config_value(request, config_key)

    if file_name:
        local_path = BRAND_DIR / file_name
        if local_path.is_file():
            try:
                os.remove(local_path)
            except Exception:
                log.warning(f"Failed to delete branding file: {local_path}")

    setattr(request.app.state.config, config_key, "")

    AuditLogger.log_settings_change(
        f"branding/delete/{asset_type}",
        after_data={"asset_type": asset_type, "cleared": True},
    )
    return {"status": "ok"}
