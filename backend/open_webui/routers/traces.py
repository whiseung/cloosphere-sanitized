"""
Traces Router

메시지 트레이싱 API 엔드포인트.
LangSmith 스타일의 트레이스 트리 조회를 지원합니다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.message_trace import (
    MessageTraceModel,
    MessageTraces,
    TraceQueryParams,
    TraceTreeResponse,
)
from open_webui.utils.auth import (
    get_admin_monitoring_write_access,
    get_verified_user,
)
from open_webui.utils.license import require_feature

router = APIRouter(dependencies=[Depends(require_feature("trace"))])

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


############################
# Get Trace by ID
############################


@router.get("/{trace_id}", response_model=TraceTreeResponse)
async def get_trace_by_id(trace_id: str, user=Depends(get_verified_user)):
    """
    특정 trace_id의 전체 트레이스 트리 조회

    - **trace_id**: 조회할 트레이스 ID
    """
    trace_tree = MessageTraces.get_trace_tree(trace_id)

    if not trace_tree:
        raise HTTPException(status_code=404, detail="Trace not found")

    # 사용자 권한 확인 (자신의 트레이스 또는 admin)
    if trace_tree.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    return trace_tree


############################
# Get Trace by Chat and Message
############################


@router.get("/chat/{chat_id}/message/{message_id}", response_model=TraceTreeResponse)
async def get_trace_by_message(
    chat_id: str, message_id: str, user=Depends(get_verified_user)
):
    """
    특정 채팅의 특정 메시지에 대한 트레이스 트리 조회

    - **chat_id**: 채팅 ID
    - **message_id**: 메시지 ID
    """
    trace_tree = MessageTraces.get_trace_tree_by_message(chat_id, message_id)

    if not trace_tree:
        raise HTTPException(status_code=404, detail="Trace not found for this message")

    # 사용자 권한 확인
    if trace_tree.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    return trace_tree


############################
# List Traces by Chat
############################


@router.get("/chat/{chat_id}", response_model=list[MessageTraceModel])
async def list_traces_by_chat(
    chat_id: str,
    limit: int = Query(default=100, le=500),
    user=Depends(get_verified_user),
):
    """
    특정 채팅의 트레이스 목록 조회 (최상위 Run만)

    - **chat_id**: 채팅 ID
    - **limit**: 최대 조회 개수 (기본 100, 최대 500)
    """
    traces = MessageTraces.get_traces_by_chat(chat_id, limit=limit)

    if traces:
        # 첫 번째 트레이스로 권한 확인
        first_trace = traces[0]
        if first_trace.user_id != user.id and user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied")

    return traces


############################
# List Traces (Admin)
############################


@router.get("/", response_model=dict)
async def list_traces(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=100),
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    run_type: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user=Depends(get_verified_user),
):
    """
    트레이스 목록 조회 (페이지네이션)

    - 일반 사용자: 자신의 트레이스만 조회 가능
    - Admin: 모든 트레이스 조회 가능
    """
    params = TraceQueryParams(
        page=page,
        limit=limit,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id if user.role == "admin" else None,
        run_type=run_type,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )

    # 일반 사용자는 자신의 트레이스만
    filter_user_id = None if user.role == "admin" else user.id

    traces, total = MessageTraces.get_traces(params, user_id=filter_user_id)

    return {
        "traces": traces,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    }


############################
# Get Trace Statistics (Admin)
############################


@router.get("/stats/summary", response_model=dict)
async def get_trace_stats(
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user_id: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """
    트레이스 통계 조회

    - 일반 사용자: 자신의 통계만 조회 가능
    - Admin: 전체 또는 특정 사용자 통계 조회 가능
    """
    filter_user_id = user_id if user.role == "admin" else user.id

    stats = MessageTraces.get_trace_stats(
        from_date=from_date,
        to_date=to_date,
        user_id=filter_user_id,
    )

    return stats


############################
# Delete Old Traces (Admin)
############################


@router.delete("/cleanup", response_model=dict)
async def cleanup_old_traces(
    before_timestamp_ms: int = Query(..., description="밀리초 단위 타임스탬프"),
    user=Depends(get_admin_monitoring_write_access),
):
    """
    특정 시점 이전의 트레이스 삭제

    - **before_timestamp_ms**: 이 시점 이전의 트레이스 삭제 (밀리초)
    """
    deleted_count = MessageTraces.delete_traces_before(before_timestamp_ms)

    return {
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} traces before timestamp {before_timestamp_ms}",
    }
