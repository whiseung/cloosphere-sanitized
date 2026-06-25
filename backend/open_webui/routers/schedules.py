import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.schedules import (
    ScheduleForm,
    ScheduleModel,
    Schedules,
    ScheduleShareForm,
    ScheduleTaskResponse,
    ScheduleTasks,
    ScheduleUserResponse,
)
from open_webui.models.users import Users
from open_webui.utils.access_control import (
    has_access,
    has_permission,
    has_permission_min_level,
)
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


class ScheduleShareResponse(BaseModel):
    copied_count: int
    copied_schedule_ids: list[str]


def _check_feature_permission(user, request: Request, min_level: str = "read"):
    """Check if user has the scheduled_tasks feature permission.

    2단계 체크:
    - features.scheduled_tasks (boolean): 기능 on/off 전역 스위치
    - workspace.schedules (none/access/read/write): 리소스 카테고리 접근 레벨
      - GET 엔드포인트: min_level="read"
      - POST/DELETE mutating 엔드포인트: min_level="write"
    """
    if user.role == "admin":
        return
    if not has_permission(
        user.id, "features.scheduled_tasks", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not has_permission_min_level(
        user.id,
        "workspace.schedules",
        min_level,
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _check_model_access(
    user, target_model_id: str, request: Request, target_type: str = ""
):
    """Check if user can access the target model/agent/dashboard."""
    if target_type == "dashboard":
        from open_webui.models.bi_dashboard import BiDashboards

        dashboard = BiDashboards.get_dashboard_by_id(target_model_id)
        if not dashboard:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        if user.role != "admin" and dashboard.user_id != user.id:
            if not has_access(user.id, "read", dashboard.access_control):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
                )
        return

    from open_webui.models.models import Models

    model = Models.get_model_by_id(target_model_id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if user.role != "admin" and model.user_id != user.id:
        if not has_access(user.id, "read", model.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )


############################
# GetSchedules (read access)
############################


@router.get("/", response_model=list[ScheduleUserResponse])
async def get_schedules(request: Request, user=Depends(get_verified_user)):
    _check_feature_permission(user, request)

    if user.role == "admin":
        return Schedules.get_schedules()
    return Schedules.get_schedules_by_user_id(user.id, "read")


############################
# CreateSchedule
############################


@router.post("/create", response_model=Optional[ScheduleModel])
async def create_schedule(
    request: Request, form_data: ScheduleForm, user=Depends(get_verified_user)
):
    _check_feature_permission(user, request, min_level="write")
    _check_model_access(user, form_data.target_model_id, request, form_data.target_type)

    # Validate cron expression
    try:
        from croniter import croniter

        croniter(form_data.cron_expression)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cron expression",
        )

    schedule = Schedules.insert_new_schedule(user.id, form_data)
    if schedule:
        # Compute next_run_at
        _update_next_run(schedule)
        return Schedules.get_schedule_by_id(schedule.id)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error creating schedule"),
    )


############################
# GetScheduleById
############################


@router.get("/{id}", response_model=Optional[ScheduleModel])
async def get_schedule_by_id(
    id: str, request: Request, user=Depends(get_verified_user)
):
    _check_feature_permission(user, request)

    schedule = Schedules.get_schedule_by_id(id)
    if schedule:
        if (
            user.role == "admin"
            or schedule.user_id == user.id
            or has_access(user.id, "read", schedule.access_control)
        ):
            return schedule
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateScheduleById
############################


@router.post("/{id}/update", response_model=Optional[ScheduleModel])
async def update_schedule_by_id(
    id: str,
    form_data: ScheduleForm,
    request: Request,
    user=Depends(get_verified_user),
):
    _check_feature_permission(user, request, min_level="write")

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if schedule.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", schedule.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    _check_model_access(user, form_data.target_model_id, request, form_data.target_type)

    # Validate cron expression
    try:
        from croniter import croniter

        croniter(form_data.cron_expression)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cron expression",
        )

    updated = Schedules.update_schedule_by_id(id, form_data)
    if updated:
        _update_next_run(updated)
        return Schedules.get_schedule_by_id(id)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error updating schedule"),
    )


############################
# DeleteScheduleById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_schedule_by_id(
    id: str, request: Request, user=Depends(get_verified_user)
):
    _check_feature_permission(user, request, min_level="write")

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if schedule.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", schedule.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    # 실행 중/대기 중 태스크를 cancelled로 마크 후 삭제
    ScheduleTasks.cancel_tasks_by_schedule_id(id)
    ScheduleTasks.delete_tasks_by_schedule_id(id)
    return Schedules.delete_schedule_by_id(id)


############################
# ToggleSchedule
############################


@router.post("/{id}/toggle", response_model=Optional[ScheduleModel])
async def toggle_schedule(id: str, request: Request, user=Depends(get_verified_user)):
    _check_feature_permission(user, request, min_level="write")

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if schedule.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", schedule.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    toggled = Schedules.toggle_schedule_by_id(id)
    if toggled and toggled.is_active:
        _update_next_run(toggled)
    return toggled


############################
# RunScheduleNow
############################


@router.post("/{id}/run", response_model=Optional[ScheduleTaskResponse])
async def run_schedule_now(id: str, request: Request, user=Depends(get_verified_user)):
    _check_feature_permission(user, request, min_level="write")

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if schedule.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", schedule.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    now = int(time.time())
    # 수동 트리거 감사: 원 소유자(schedule.user_id)와 다른 사용자가 트리거한 경우 기록.
    # 실행 컨텍스트는 schedule.user_id 그대로 유지 — 권한 상승 아님.
    triggered_by = user.id if user.id != schedule.user_id else None
    task = ScheduleTasks.enqueue_task(schedule, now, triggered_by_user_id=triggered_by)
    if task:
        if triggered_by:
            log.info(
                "Schedule %s manually triggered by user %s (owner=%s)",
                schedule.id,
                user.id,
                schedule.user_id,
            )
        return ScheduleTaskResponse.model_validate(
            {**task.model_dump(), "schedule_name": schedule.name}
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error enqueuing task"),
    )


############################
# ShareSchedule
############################


@router.post("/{id}/share", response_model=ScheduleShareResponse)
async def share_schedule(
    id: str,
    form_data: ScheduleShareForm,
    request: Request,
    user=Depends(get_verified_user),
):
    _check_feature_permission(user, request, min_level="write")

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if schedule.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not form_data.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No users specified"),
        )

    # Get source owner info
    owner = Users.get_user_by_id(schedule.user_id)
    owner_name = owner.name if owner else "Unknown"

    copied_schedule_ids: list[str] = []

    for target_user_id in form_data.user_ids:
        if target_user_id == schedule.user_id:
            continue

        target_user = Users.get_user_by_id(target_user_id)
        if not target_user:
            continue

        # Build copied meta
        copied_meta = dict(schedule.meta) if schedule.meta else {}
        copied_meta["copied_from"] = {
            "user_id": schedule.user_id,
            "user_name": owner_name,
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "copied_at": int(time.time()),
        }

        new_schedule = Schedules.insert_new_schedule(
            target_user_id,
            ScheduleForm(
                name=schedule.name,
                description=schedule.description,
                target_type=schedule.target_type,
                target_model_id=schedule.target_model_id,
                prompt=schedule.prompt,
                cron_expression=schedule.cron_expression,
                timezone=schedule.timezone,
                delivery=schedule.delivery,
                start_at=schedule.start_at,
                end_at=schedule.end_at,
                meta=copied_meta,
            ),
        )

        if new_schedule:
            _update_next_run(new_schedule)
            copied_schedule_ids.append(new_schedule.id)
        else:
            log.error(f"Failed to copy schedule for user {target_user_id}")

    return ScheduleShareResponse(
        copied_count=len(copied_schedule_ids),
        copied_schedule_ids=copied_schedule_ids,
    )


############################
# GetScheduleTasks
############################


@router.get("/{id}/tasks", response_model=list[ScheduleTaskResponse])
async def get_schedule_tasks(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
    limit: int = 500,
    offset: int = 0,
):
    _check_feature_permission(user, request)

    schedule = Schedules.get_schedule_by_id(id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and schedule.user_id != user.id
        and not has_access(user.id, "read", schedule.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    tasks = ScheduleTasks.get_tasks_by_schedule_id(id, limit=limit, offset=offset)
    return [
        ScheduleTaskResponse.model_validate(
            {**t.model_dump(), "schedule_name": schedule.name}
        )
        for t in tasks
    ]


############################
# GetRecentTasks
############################


@router.get("/tasks/recent", response_model=list[ScheduleTaskResponse])
async def get_recent_tasks(request: Request, user=Depends(get_verified_user)):
    _check_feature_permission(user, request)

    if user.role == "admin":
        # admin은 전체 최근 task 조회
        return ScheduleTasks.get_recent_tasks()

    # 읽기/쓰기 권한자: 접근 가능한 스케줄(소유 + access_control read 공유받은 것)에 속한 task
    accessible_schedules = Schedules.get_schedules_by_user_id(user.id, "read")
    accessible_ids = [s.id for s in accessible_schedules]
    return ScheduleTasks.get_recent_tasks(accessible_schedule_ids=accessible_ids)


############################
# Helpers
############################


def _update_next_run(schedule: ScheduleModel):
    """Compute and store next_run_at based on cron_expression and timezone."""
    from datetime import datetime, timezone

    from croniter import croniter

    try:
        import pytz

        tz = pytz.timezone(schedule.timezone or "UTC")
        now = datetime.now(tz)
    except Exception:
        now = datetime.now(timezone.utc)

    cron = croniter(schedule.cron_expression, now)
    next_dt = cron.get_next(datetime)
    next_run_at = int(next_dt.timestamp())
    Schedules.update_next_run(schedule.id, next_run_at)
