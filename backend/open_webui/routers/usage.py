"""
Usage Statistics Router

사용량 통계 API 엔드포인트.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.usage import Usages
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


class UsageStatsResponse(BaseModel):
    """사용량 요약 통계 응답"""

    total_tokens: int
    total_requests: int
    unique_users: int
    unique_chats: int
    unique_models: int
    avg_tokens_per_request: float


class UsageTrendItem(BaseModel):
    """시계열 데이터 항목"""

    date: str
    tokens: int
    requests: int


class UsageByModelItem(BaseModel):
    """모델별 사용량 항목"""

    model_id: str
    total_tokens: int
    request_count: int


class UsageByUserItem(BaseModel):
    """사용자별 사용량 항목"""

    user_id: str
    user_name: str
    user_email: str
    total_tokens: int
    request_count: int


class UsageByGroupItem(BaseModel):
    """그룹별 사용량 항목"""

    group_id: str
    group_name: str
    total_tokens: int
    request_count: int
    user_count: int


class UsageByOrganizationItem(BaseModel):
    """조직별 사용량 항목"""

    organization_id: str
    organization_name: str
    total_tokens: int
    request_count: int
    user_count: int


class UsageByTypeItem(BaseModel):
    """메시지 타입별 사용량 항목"""

    message_type: str
    total_tokens: int
    request_count: int


class UsageByAgentItem(BaseModel):
    """에이전트별 사용량 항목"""

    agent_id: str
    agent_name: str
    total_tokens: int
    request_count: int


class FilterOptionItem(BaseModel):
    """필터 옵션 항목"""

    id: str
    name: str


####################
# Filter Endpoints
####################


@router.get("/filters/models", response_model=list[FilterOptionItem])
async def get_available_models(
    user=Depends(get_admin_monitoring_access),
):
    """사용된 모델 목록 조회"""
    return Usages.get_available_models()


@router.get("/filters/users", response_model=list[FilterOptionItem])
async def get_available_users(
    user=Depends(get_admin_monitoring_access),
):
    """사용량이 있는 사용자 목록 조회"""
    return Usages.get_available_users()


@router.get("/filters/groups", response_model=list[FilterOptionItem])
async def get_available_groups(
    user=Depends(get_admin_monitoring_access),
):
    """그룹 목록 조회"""
    return Usages.get_available_groups()


@router.get("/filters/organizations", response_model=list[FilterOptionItem])
async def get_available_organizations(
    user=Depends(get_admin_monitoring_access),
):
    """조직 목록 조회"""
    return Usages.get_available_organizations()


@router.get("/filters/agents", response_model=list[FilterOptionItem])
async def get_available_agents(
    user=Depends(get_admin_monitoring_access),
):
    """사용된 에이전트 목록 조회"""
    return Usages.get_available_agents()


####################
# Real-time Endpoints
####################


class OnlineUsersResponse(BaseModel):
    """실시간 접속자 응답"""

    count: int
    user_ids: list[str]


@router.get("/online-users", response_model=OnlineUsersResponse)
async def get_online_users(
    user=Depends(get_admin_monitoring_access),
):
    """현재 접속 중인 사용자 수 조회"""
    try:
        # Lazy import to avoid circular dependency
        from open_webui.socket.main import USER_POOL

        user_ids = list(USER_POOL.keys())
        return OnlineUsersResponse(
            count=len(user_ids),
            user_ids=user_ids,
        )
    except Exception as e:
        log.error(f"Failed to get online users: {e}")
        return OnlineUsersResponse(count=0, user_ids=[])


####################
# Statistics Endpoints
####################


@router.get("/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    사용량 요약 통계 조회 (관리자 전용)
    """
    stats = Usages.get_usage_stats(
        from_date=from_date,
        to_date=to_date,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return UsageStatsResponse(**stats)


@router.get("/trends", response_model=list[UsageTrendItem])
async def get_usage_trends(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    granularity: str = Query("day", description="집계 단위 (day, hour)"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    시계열 사용량 데이터 조회 (관리자 전용)
    """
    trends = Usages.get_usage_trends(
        from_date=from_date,
        to_date=to_date,
        granularity=granularity,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return trends


@router.get("/by-model", response_model=list[UsageByModelItem])
async def get_usage_by_model(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    모델별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_model(
        from_date=from_date,
        to_date=to_date,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data


@router.get("/by-user", response_model=list[UsageByUserItem])
async def get_usage_by_user(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    limit: int = Query(20, ge=1, le=100, description="최대 항목 수"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    사용자별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_user(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data


@router.get("/by-group", response_model=list[UsageByGroupItem])
async def get_usage_by_group(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    limit: int = Query(10, ge=1, le=100, description="최대 항목 수"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    그룹별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_group(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data


@router.get("/by-organization", response_model=list[UsageByOrganizationItem])
async def get_usage_by_organization(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    limit: int = Query(10, ge=1, le=100, description="최대 항목 수"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    조직별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_organization(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data


@router.get("/by-type", response_model=list[UsageByTypeItem])
async def get_usage_by_type(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    메시지 타입별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_type(
        from_date=from_date,
        to_date=to_date,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data


####################
# Conversation Logs Endpoints
####################


@router.get("/conversation-logs")
async def get_conversation_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[str] = Query(None),
    user_search: Optional[str] = Query(None, description="사용자 이름/이메일 검색"),
    model_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, description="chat / code_gateway"),
    from_date: Optional[int] = Query(None),
    to_date: Optional[int] = Query(None),
    user=Depends(get_admin_monitoring_access),
):
    """대화 로그 조회 (채팅 + 코드게이트웨이)"""
    return Usages.get_conversation_logs(
        page=page,
        limit=limit,
        user_id=user_id,
        user_search=user_search,
        model_id=model_id,
        source_type=source_type,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/conversation-logs/stats")
async def get_conversation_log_stats(
    from_date: Optional[int] = Query(None),
    to_date: Optional[int] = Query(None),
    source_type: Optional[str] = Query(None),
    user=Depends(get_admin_monitoring_access),
):
    """대화 로그 통계"""
    return Usages.get_conversation_log_stats(
        from_date=from_date,
        to_date=to_date,
        source_type=source_type,
    )


@router.get("/conversation-logs/filters/models")
async def get_conversation_log_filter_models(
    source_type: Optional[str] = Query(None),
    user=Depends(get_admin_monitoring_access),
):
    """대화 로그 모델 필터 목록"""
    return Usages.get_conversation_log_filter_models(source_type=source_type)


@router.get("/conversation-logs/filters/users")
async def get_conversation_log_filter_users(
    source_type: Optional[str] = Query(None),
    user=Depends(get_admin_monitoring_access),
):
    """대화 로그 사용자 필터 목록"""
    return Usages.get_conversation_log_filter_users(source_type=source_type)


####################
# Agent Usage Endpoints
####################


@router.get("/by-agent", response_model=list[UsageByAgentItem])
async def get_usage_by_agent(
    from_date: Optional[int] = Query(None, description="시작 날짜 (Unix timestamp)"),
    to_date: Optional[int] = Query(None, description="종료 날짜 (Unix timestamp)"),
    limit: int = Query(10, ge=1, le=100, description="최대 항목 수"),
    model_id: Optional[str] = Query(None, description="모델 ID 필터"),
    user_id: Optional[str] = Query(None, description="사용자 ID 필터"),
    group_id: Optional[str] = Query(None, description="그룹 ID 필터"),
    organization_id: Optional[str] = Query(None, description="조직 ID 필터"),
    agent_id: Optional[str] = Query(None, description="에이전트 ID 필터"),
    user=Depends(get_admin_monitoring_access),
):
    """
    에이전트별 사용량 집계 조회 (관리자 전용)
    """
    data = Usages.get_usage_by_agent(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        model_id=model_id,
        user_id=user_id,
        group_id=group_id,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    return data
