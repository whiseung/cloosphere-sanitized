"""
File Logs Router

가드레일 결과가 있는 파일 로그 조회 API 엔드포인트.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.files import (
    FileLogListResponse,
    FileLogQueryParams,
    Files,
)
from open_webui.utils.auth import (
    get_admin_monitoring_read_access as get_admin_monitoring_access,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


####################
# Endpoints
####################


@router.get("/", response_model=FileLogListResponse)
async def get_file_logs(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    source: Optional[str] = Query(
        None, description="출처 필터 (chat, knowledge, project)"
    ),
    category: Optional[str] = Query(
        None,
        description="분류 카테고리 필터 (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED)",
    ),
    status: Optional[str] = Query(None, description="상태 필터 (blocked, flagged)"),
    search: Optional[str] = Query(None, description="파일명/사용자 검색"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    user=Depends(get_admin_monitoring_access),
):
    """
    파일 로그 목록 조회 (관리자 전용)
    가드레일 결과가 있는 파일만 반환합니다.
    """
    params = FileLogQueryParams(
        page=page,
        limit=limit,
        source=source,
        category=category,
        status=status,
        search=search,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
    )

    items, total = Files.get_file_logs(params)
    total_pages = (total + limit - 1) // limit

    return FileLogListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
