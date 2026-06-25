"""마켓플레이스 카탈로그 라우터 — 워크스페이스 > 마켓플레이스 생성 페이지의 서비스 picker.

실제 연결 CRUD 는 tool_connections 라우터가 담당한다(meta.source="marketplace"). 이 라우터는
카탈로그 메타데이터(GET /)만 노출하며, workspace.marketplace 권한으로 게이팅된다.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.access_control import has_permission_min_level
from open_webui.utils.auth import get_verified_user
from open_webui.utils.marketplace import MARKETPLACE_SERVICES

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


@router.get("/")
async def get_marketplace_services(request: Request, user=Depends(get_verified_user)):
    """마켓플레이스 카탈로그(서비스 매니페스트). 생성 페이지 picker 가 사용한다.

    실제 연결 상태/도구 목록은 생성된 tool_connection 의 `/{id}/tools` 로 확인한다.
    """
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.marketplace",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    return MARKETPLACE_SERVICES
