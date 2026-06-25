"""
Trace Analysis Router

트레이스 분석 API 엔드포인트.
LLM을 사용하여 트레이스 컨텍스트를 분석하고 리포트를 생성합니다.
"""

import asyncio
import logging
from typing import Set

from fastapi import APIRouter, Depends, HTTPException, Request
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.message_trace import MessageTraces
from open_webui.models.trace_analysis import (
    TraceAnalyses,
    TraceAnalysisCreateForm,
    TraceAnalysisResponse,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.license import require_feature

router = APIRouter(dependencies=[Depends(require_feature("trace"))])

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

_background_tasks: Set[asyncio.Task] = set()


############################
# Create Trace Analysis
############################


@router.post("/analyze", response_model=TraceAnalysisResponse)
async def create_trace_analysis(
    request: Request,
    form_data: TraceAnalysisCreateForm,
    user=Depends(get_verified_user),
):
    """
    트레이스 분석 시작.
    백그라운드로 LLM 분석을 실행하고 즉시 analysis_id를 반환합니다.
    """
    # 트레이스 존재 확인
    trace_tree = MessageTraces.get_trace_tree(form_data.trace_id)
    if not trace_tree:
        raise HTTPException(status_code=404, detail="Trace not found")

    # 권한 확인
    if trace_tree.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    # 분석 레코드 생성
    analysis = TraceAnalyses.insert_new_analysis(
        user_id=user.id,
        form_data=form_data,
        chat_id=trace_tree.chat_id,
        message_id=trace_tree.message_id,
    )

    if not analysis:
        raise HTTPException(status_code=400, detail="Failed to create analysis")

    # 백그라운드 분석 실행
    from extension_modules.trace_analysis.analyzer import run_trace_analysis

    task = asyncio.create_task(
        run_trace_analysis(
            app=request.app,
            analysis_id=analysis.id,
            trace_id=form_data.trace_id,
            model_id=form_data.model_id,
            user_id=user.id,
            user_description=form_data.user_description,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return TraceAnalysisResponse(**analysis.model_dump())


############################
# Get Analysis by ID
############################


@router.get("/{analysis_id}", response_model=TraceAnalysisResponse)
async def get_trace_analysis(
    analysis_id: str,
    user=Depends(get_verified_user),
):
    """분석 상태/결과 조회 (프론트엔드 폴링용)"""
    analysis = TraceAnalyses.get_analysis_by_id(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # 권한 확인
    if analysis.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    return TraceAnalysisResponse(**analysis.model_dump())


############################
# Get Analyses by Trace ID
############################


@router.get("/by-trace/{trace_id}", response_model=list[TraceAnalysisResponse])
async def get_analyses_by_trace(
    trace_id: str,
    user=Depends(get_verified_user),
):
    """특정 트레이스의 모든 분석 결과 (최신순)"""
    analyses = TraceAnalyses.get_analyses_by_trace_id(trace_id)

    # 권한 확인 — 본인 분석이거나 admin
    filtered = [
        TraceAnalysisResponse(**a.model_dump())
        for a in analyses
        if a.user_id == user.id or user.role == "admin"
    ]

    return filtered


############################
# Delete Analysis (Admin)
############################


@router.delete("/{analysis_id}", response_model=bool)
async def delete_trace_analysis(
    analysis_id: str,
    user=Depends(get_admin_user),
):
    """분석 삭제 (관리자 전용)"""
    success = TraceAnalyses.delete_analysis(analysis_id)
    if not success:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return True
