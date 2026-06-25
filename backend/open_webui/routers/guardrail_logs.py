"""
Guardrail Logs Router

가드레일 감지 로그 조회 API 엔드포인트.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.guardrail_log import (
    GuardrailLogModel,
    GuardrailLogQueryParams,
    GuardrailLogs,
)
from open_webui.utils.auth import (
    get_admin_monitoring_read_access as get_admin_monitoring_access,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


####################
# Response Models
####################


class GuardrailLogListResponse(BaseModel):
    """가드레일 로그 목록 응답"""

    items: list[GuardrailLogModel]
    total: int
    page: int
    limit: int
    total_pages: int


####################
# Endpoints
####################


@router.get("/", response_model=GuardrailLogListResponse)
async def get_guardrail_logs(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(50, ge=1, le=100, description="페이지당 항목 수"),
    action: Optional[str] = Query(None, description="액션 필터 (콤마 구분)"),
    detection_source: Optional[str] = Query(
        None, description="감지 소스 필터 (콤마 구분)"
    ),
    user_search: Optional[str] = Query(
        None, description="사용자 검색 (ID, 이메일, 이름)"
    ),
    chat_id: Optional[str] = Query(None, description="채팅 ID 필터"),
    source: Optional[str] = Query(
        None, description="소스 필터 (meta.source 기준, 예: code_gateway)"
    ),
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    user=Depends(get_admin_monitoring_access),
):
    """
    가드레일 로그 목록 조회 (관리자 전용)
    """
    params = GuardrailLogQueryParams(
        page=page,
        limit=limit,
        action=action,
        detection_source=detection_source,
        user_search=user_search,
        chat_id=chat_id,
        source=source,
        from_date=from_date,
        to_date=to_date,
    )

    items, total = GuardrailLogs.get_guardrail_logs(params)
    total_pages = (total + limit - 1) // limit

    # Resolve missing user_name/user_email from users table
    missing_user_ids = {
        item.user_id
        for item in items
        if item.user_id and (not item.user_name or not item.user_email)
    }
    if missing_user_ids:
        from open_webui.models.users import Users

        user_map = {}
        for uid in missing_user_ids:
            u = Users.get_user_by_id(uid)
            if u:
                user_map[uid] = u

        resolved_items = []
        for item in items:
            if item.user_id in user_map:
                u = user_map[item.user_id]
                item = item.model_copy(
                    update={
                        "user_name": item.user_name or u.name,
                        "user_email": item.user_email or u.email,
                    }
                )
            resolved_items.append(item)
        items = resolved_items

    return GuardrailLogListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/actions", response_model=list[str])
async def get_available_actions(
    detection_source: Optional[str] = Query(None, description="감지 소스 필터"),
    source: Optional[str] = Query(None, description="소스 필터"),
    user_search: Optional[str] = Query(None, description="사용자 검색"),
    user=Depends(get_admin_monitoring_access),
):
    """
    실제 데이터가 존재하는 가드레일 액션 목록 조회 (cascading)
    """
    return GuardrailLogs.get_distinct_actions(detection_source, source, user_search)


@router.get("/detection-sources", response_model=list[str])
async def get_available_detection_sources(
    action: Optional[str] = Query(None, description="액션 필터"),
    source: Optional[str] = Query(None, description="소스 필터"),
    user_search: Optional[str] = Query(None, description="사용자 검색"),
    user=Depends(get_admin_monitoring_access),
):
    """
    실제 데이터가 존재하는 감지 소스 목록 조회 (cascading)
    """
    return GuardrailLogs.get_distinct_detection_sources(action, source, user_search)


@router.get("/{guardrail_log_id}", response_model=GuardrailLogModel)
async def get_guardrail_log_by_id(
    guardrail_log_id: str,
    user=Depends(get_admin_monitoring_access),
):
    """
    특정 가드레일 로그 상세 조회 (관리자 전용)
    """
    guardrail_log = GuardrailLogs.get_guardrail_log_by_id(guardrail_log_id)
    if not guardrail_log:
        raise HTTPException(status_code=404, detail="Guardrail log not found")

    return guardrail_log
