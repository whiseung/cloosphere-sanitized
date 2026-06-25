"""
Audit Logs Router

감사 로그 조회 API 엔드포인트.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.audit_log import (
    AuditLogModel,
    AuditLogQueryParams,
    AuditLogs,
    AuditResourceType,
)
from open_webui.utils.auth import (
    get_admin_monitoring_read_access as get_admin_monitoring_access,
)
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter(dependencies=[Depends(require_feature("audit_log"))])


####################
# Response Models
####################


class AuditLogListResponse(BaseModel):
    """감사 로그 목록 응답"""

    items: list[AuditLogModel]
    total: int
    page: int
    limit: int
    total_pages: int


class AuditLogStatsResponse(BaseModel):
    """감사 로그 통계 응답"""

    by_action: dict[str, int]
    by_resource_type: dict[str, int]
    total: int


####################
# Endpoints
####################


@router.get("/", response_model=AuditLogListResponse)
async def get_audit_logs(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(50, ge=1, le=100, description="페이지당 항목 수"),
    resource_type: Optional[str] = Query(None, description="리소스 타입 필터"),
    resource_id: Optional[str] = Query(None, description="리소스 ID 필터"),
    action: Optional[str] = Query(None, description="액션 타입 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    user=Depends(get_admin_monitoring_access),
):
    """
    감사 로그 목록 조회 (관리자 전용)
    """
    params = AuditLogQueryParams(
        page=page,
        limit=limit,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        user_id=user_id,
        organization_id=organization_id,
        from_date=from_date,
        to_date=to_date,
    )

    items, total = AuditLogs.get_audit_logs(params)
    total_pages = (total + limit - 1) // limit

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get(
    "/resources/{resource_type}/{resource_id}", response_model=list[AuditLogModel]
)
async def get_resource_audit_logs(
    resource_type: str,
    resource_id: str,
    limit: int = Query(100, ge=1, le=500, description="최대 항목 수"),
    user=Depends(get_admin_monitoring_access),
):
    """
    특정 리소스의 감사 로그 히스토리 조회 (관리자 전용)
    """
    # 유효한 리소스 타입인지 확인
    valid_types = [t.value for t in AuditResourceType]
    if resource_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resource_type. Must be one of: {valid_types}",
        )

    return AuditLogs.get_audit_logs_by_resource(resource_type, resource_id, limit)


@router.get("/users/{target_user_id}", response_model=list[AuditLogModel])
async def get_user_audit_logs(
    target_user_id: str,
    limit: int = Query(100, ge=1, le=500, description="최대 항목 수"),
    user=Depends(get_admin_monitoring_access),
):
    """
    특정 사용자의 활동 로그 조회 (관리자 전용)
    """
    return AuditLogs.get_audit_logs_by_user(target_user_id, limit)


@router.get("/access-control-changes", response_model=list[AuditLogModel])
async def get_access_control_changes(
    resource_type: Optional[str] = Query(None, description="리소스 타입 필터"),
    limit: int = Query(100, ge=1, le=500, description="최대 항목 수"),
    user=Depends(get_admin_monitoring_access),
):
    """
    권한 변경 로그 조회 (관리자 전용)
    """
    if resource_type:
        valid_types = [t.value for t in AuditResourceType]
        if resource_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid resource_type. Must be one of: {valid_types}",
            )

    return AuditLogs.get_access_control_changes(resource_type, limit)


@router.get("/auth", response_model=list[AuditLogModel])
async def get_auth_logs(
    target_user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    limit: int = Query(100, ge=1, le=500, description="최대 항목 수"),
    user=Depends(get_admin_monitoring_access),
):
    """
    인증 관련 로그 조회 (관리자 전용)
    """
    return AuditLogs.get_auth_logs(target_user_id, limit)


@router.get("/stats", response_model=AuditLogStatsResponse)
async def get_audit_log_stats(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    resource_type: Optional[str] = Query(None, description="리소스 타입 필터"),
    action: Optional[str] = Query(None, description="액션 타입 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID/이름 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    감사 로그 통계 조회 (관리자 전용)
    """
    stats = AuditLogs.get_audit_log_stats(
        from_date, to_date, resource_type, action, user_id
    )
    return AuditLogStatsResponse(**stats)


@router.get("/actions", response_model=list[str])
async def get_available_actions(
    resource_type: Optional[str] = Query(None, description="리소스 타입 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    실제 데이터가 존재하는 액션 타입 목록 조회 (resource_type으로 cascading)
    """
    return AuditLogs.get_distinct_actions(resource_type)


@router.get("/resource-types", response_model=list[str])
async def get_available_resource_types(
    action: Optional[str] = Query(None, description="액션 타입 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    실제 데이터가 존재하는 리소스 타입 목록 조회 (action으로 cascading)
    """
    return AuditLogs.get_distinct_resource_types(action)


@router.get("/{audit_log_id}", response_model=AuditLogModel)
async def get_audit_log_by_id(
    audit_log_id: str,
    user=Depends(get_admin_monitoring_access),
):
    """
    특정 감사 로그 상세 조회 (관리자 전용)
    """
    audit_log = AuditLogs.get_audit_log_by_id(audit_log_id)
    if not audit_log:
        raise HTTPException(status_code=404, detail="Audit log not found")

    return audit_log
