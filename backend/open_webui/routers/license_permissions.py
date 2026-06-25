from fastapi import APIRouter, Request
from open_webui.utils.license import LicenseStatus
from pydantic import BaseModel

router = APIRouter()


class LicensePermissionResponse(BaseModel):
    enhanced_kbsphere: bool = False
    enhanced_dbsphere: bool = False
    enhanced_tool_use: bool = False


@router.get("/", response_model=LicensePermissionResponse)
async def get_license_permissions(request: Request):
    """Legacy compatibility endpoint.

    Proxies to the new license system. When enforcement is disabled
    (default), all features return True for backward compatibility.
    """
    license_status: LicenseStatus = getattr(
        request.app.state, "LICENSE_STATUS", LicenseStatus()
    )

    if not license_status.enforcement_enabled:
        return LicensePermissionResponse(
            enhanced_kbsphere=True,
            enhanced_dbsphere=True,
            enhanced_tool_use=True,
        )

    return LicensePermissionResponse(
        enhanced_kbsphere=license_status.permissions.get("kbsphere", False),
        enhanced_dbsphere=license_status.permissions.get("dbsphere", False),
        enhanced_tool_use=license_status.has_license,
    )
