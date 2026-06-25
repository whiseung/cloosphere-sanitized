import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Schedule DB Schema
####################


class Schedule(Base):
    __tablename__ = "schedule"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False)

    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    target_type = Column(Text, nullable=False)  # "agent" | "flow"
    target_model_id = Column(Text, nullable=False)  # models.id 참조
    prompt = Column(Text, nullable=False)

    cron_expression = Column(Text, nullable=False)  # "0 9 * * 1-5"
    timezone = Column(Text, default="UTC")

    delivery = Column(
        JSON, nullable=True
    )  # {"type":"chat"} | {"type":"webhook","url":"..."}

    is_active = Column(Boolean, default=True)
    next_run_at = Column(BigInteger, nullable=True)  # 사전 계산된 다음 실행 시각 (unix)

    start_at = Column(BigInteger, nullable=True)  # 반복 시작 시각 (unix)
    end_at = Column(BigInteger, nullable=True)  # 반복 종료 시각 (unix, null=무기한)

    chat_id = Column(Text, nullable=True)

    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)

    __table_args__ = (
        Index("ix_schedule_user_id", "user_id"),
        Index("ix_schedule_active_next_run", "is_active", "next_run_at"),
    )


class ScheduleModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: Optional[str] = None

    target_type: str
    target_model_id: str
    prompt: str

    cron_expression: str
    timezone: str = "UTC"

    delivery: Optional[dict] = None

    is_active: bool = True
    next_run_at: Optional[int] = None

    start_at: Optional[int] = None
    end_at: Optional[int] = None

    chat_id: Optional[str] = None

    meta: Optional[dict] = None
    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


####################
# ScheduleTask DB Schema
####################


class ScheduleTask(Base):
    __tablename__ = "schedule_task"

    id = Column(Text, unique=True, primary_key=True)
    schedule_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)

    status = Column(Text, default="pending")  # pending | running | completed | failed
    worker_id = Column(Text, nullable=True)

    prompt = Column(Text, nullable=False)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    chat_id = Column(Text, nullable=True)

    scheduled_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger, nullable=True)
    completed_at = Column(BigInteger, nullable=True)

    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)

    # NULL = 정기 실행 (스케줄러), 값 있음 = 수동 실행 트리거한 사용자 id (owner 또는 write 권한자)
    triggered_by_user_id = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "scheduled_at", name="uq_schedule_task_schedule_scheduled"
        ),
        Index("ix_schedule_task_schedule_id", "schedule_id"),
        Index("ix_schedule_task_status", "status"),
        Index("ix_schedule_task_user_id", "user_id"),
        Index("ix_schedule_task_status_scheduled", "status", "scheduled_at"),
    )


class ScheduleTaskModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: str
    user_id: str

    status: str = "pending"
    worker_id: Optional[str] = None

    prompt: str
    result: Optional[dict] = None
    error_message: Optional[str] = None
    chat_id: Optional[str] = None

    scheduled_at: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None

    retry_count: int = 0
    max_retries: int = 2
    triggered_by_user_id: Optional[str] = None


####################
# Forms
####################


class ScheduleUserModel(ScheduleModel):
    user: Optional[UserResponse] = None


class ScheduleResponse(ScheduleModel):
    pass


class ScheduleUserResponse(ScheduleUserModel):
    pass


class ScheduleForm(BaseModel):
    name: str
    description: Optional[str] = None
    target_type: str = "agent"
    target_model_id: str
    prompt: str
    cron_expression: str
    timezone: str = "UTC"
    delivery: Optional[dict] = None
    start_at: Optional[int] = None
    end_at: Optional[int] = None
    meta: Optional[dict] = None


class ScheduleShareForm(BaseModel):
    user_ids: list[str] = []


class ScheduleTaskResponse(ScheduleTaskModel):
    schedule_name: Optional[str] = None


####################
# Schedule Table Operations
####################


class ScheduleTable:
    def insert_new_schedule(
        self, user_id: str, form_data: ScheduleForm
    ) -> Optional[ScheduleModel]:
        with get_db() as db:
            schedule = ScheduleModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "is_active": True,
                    "next_run_at": None,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Schedule(**schedule.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return ScheduleModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_schedules(self) -> list[ScheduleUserModel]:
        with get_db() as db:
            schedules = []
            for schedule in (
                db.query(Schedule).order_by(Schedule.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(schedule.user_id)
                schedules.append(
                    ScheduleUserModel.model_validate(
                        {
                            **ScheduleModel.model_validate(schedule).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return schedules

    def get_schedules_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ScheduleUserModel]:
        schedules = self.get_schedules()
        return [
            schedule
            for schedule in schedules
            if schedule.user_id == user_id
            or has_access(user_id, permission, schedule.access_control)
        ]

    def get_schedule_by_id(self, id: str) -> Optional[ScheduleModel]:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                return ScheduleModel.model_validate(schedule) if schedule else None
        except Exception:
            return None

    def update_schedule_by_id(
        self, id: str, form_data: ScheduleForm
    ) -> Optional[ScheduleModel]:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    for key, value in form_data.model_dump(exclude_none=True).items():
                        setattr(schedule, key, value)
                    schedule.updated_at = int(time.time())
                    db.commit()
                    db.refresh(schedule)
                    return ScheduleModel.model_validate(schedule)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def toggle_schedule_by_id(self, id: str) -> Optional[ScheduleModel]:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    schedule.is_active = not schedule.is_active
                    schedule.updated_at = int(time.time())
                    db.commit()
                    db.refresh(schedule)
                    return ScheduleModel.model_validate(schedule)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_next_run(self, id: str, next_run_at: int) -> bool:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    schedule.next_run_at = next_run_at
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def get_due_schedules(self, now: int) -> list[ScheduleModel]:
        from sqlalchemy import or_

        with get_db() as db:
            schedules = (
                db.query(Schedule)
                .filter(
                    Schedule.is_active == True,
                    Schedule.next_run_at <= now,
                    # start_at: null이면 즉시 시작, 아니면 now >= start_at
                    or_(Schedule.start_at == None, Schedule.start_at <= now),
                    # end_at: null이면 무기한, 아니면 now <= end_at
                    or_(Schedule.end_at == None, Schedule.end_at >= now),
                )
                .all()
            )
            return [ScheduleModel.model_validate(s) for s in schedules]

    def update_chat_id(self, id: str, chat_id: str) -> bool:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    schedule.chat_id = chat_id
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def update_access_control(
        self, id: str, access_control: Optional[dict]
    ) -> Optional[ScheduleModel]:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    schedule.access_control = access_control
                    schedule.updated_at = int(time.time())
                    db.commit()
                    db.refresh(schedule)
                    return ScheduleModel.model_validate(schedule)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_schedule_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                schedule = db.query(Schedule).filter_by(id=id).first()
                if schedule:
                    db.delete(schedule)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


Schedules = ScheduleTable()


####################
# ScheduleTask Table Operations
####################


class ScheduleTaskTable:
    def enqueue_task(
        self,
        schedule: ScheduleModel,
        scheduled_at: int,
        triggered_by_user_id: Optional[str] = None,
    ) -> Optional[ScheduleTaskModel]:
        with get_db() as db:
            task = ScheduleTaskModel(
                id=str(uuid.uuid4()),
                schedule_id=schedule.id,
                user_id=schedule.user_id,
                status="pending",
                prompt=schedule.prompt,
                scheduled_at=scheduled_at,
                retry_count=0,
                max_retries=2,
                triggered_by_user_id=triggered_by_user_id,
            )
            try:
                result = ScheduleTask(**task.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return ScheduleTaskModel.model_validate(result) if result else None
            except Exception:
                # Unique constraint violation (duplicate) — silently ignore
                db.rollback()
                return None

    def claim_pending_task(self, worker_id: str) -> Optional[ScheduleTaskModel]:
        """Claim a pending task using SELECT ... FOR UPDATE SKIP LOCKED (PostgreSQL)
        or simple UPDATE (SQLite)."""
        from open_webui.internal.db import SQLALCHEMY_DATABASE_URL

        with get_db() as db:
            try:
                if "sqlite" in SQLALCHEMY_DATABASE_URL:
                    # SQLite: simple claim (single instance)
                    task = (
                        db.query(ScheduleTask)
                        .filter(ScheduleTask.status == "pending")
                        .order_by(ScheduleTask.scheduled_at.asc())
                        .first()
                    )
                else:
                    # PostgreSQL: SKIP LOCKED for distributed workers
                    task = (
                        db.query(ScheduleTask)
                        .filter(ScheduleTask.status == "pending")
                        .order_by(ScheduleTask.scheduled_at.asc())
                        .with_for_update(skip_locked=True)
                        .first()
                    )

                if task:
                    task.status = "running"
                    task.worker_id = worker_id
                    task.started_at = int(time.time())
                    db.commit()
                    db.refresh(task)
                    return ScheduleTaskModel.model_validate(task)
                return None
            except Exception as e:
                log.exception(e)
                db.rollback()
                return None

    def update_task_status(
        self,
        task_id: str,
        status: str,
        result: Optional[dict] = None,
        error_message: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> bool:
        try:
            with get_db() as db:
                task = db.query(ScheduleTask).filter_by(id=task_id).first()
                if task:
                    task.status = status
                    if result is not None:
                        task.result = result
                    if error_message is not None:
                        task.error_message = error_message
                    if chat_id is not None:
                        task.chat_id = chat_id
                    if status in ("completed", "failed"):
                        task.completed_at = int(time.time())
                    db.commit()
                    return True
                return False
        except Exception as e:
            log.exception(e)
            return False

    def retry_task(self, task_id: str) -> bool:
        """Reset a failed/running task back to pending for retry."""
        try:
            with get_db() as db:
                task = db.query(ScheduleTask).filter_by(id=task_id).first()
                if task and task.retry_count < task.max_retries:
                    task.status = "pending"
                    task.worker_id = None
                    task.started_at = None
                    task.retry_count += 1
                    db.commit()
                    return True
                return False
        except Exception as e:
            log.exception(e)
            return False

    def get_task_by_id(self, task_id: str) -> Optional[ScheduleTaskModel]:
        with get_db() as db:
            task = db.query(ScheduleTask).filter_by(id=task_id).first()
            return ScheduleTaskModel.model_validate(task) if task else None

    def get_tasks_by_schedule_id(
        self, schedule_id: str, limit: int = 500, offset: int = 0
    ) -> list[ScheduleTaskModel]:
        """Schedule 단위 실행 이력 조회.

        - 기본 limit을 50→500으로 상향. 이전값 50은 매일 도는 장기 스케줄에서
          "옛날 이력이 안 보인다" 현상을 유발했음.
        - offset 파라미터 추가로 향후 무한 스크롤/페이지네이션 지원.
        """
        with get_db() as db:
            tasks = (
                db.query(ScheduleTask)
                .filter(ScheduleTask.schedule_id == schedule_id)
                .order_by(ScheduleTask.scheduled_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [ScheduleTaskModel.model_validate(t) for t in tasks]

    def get_recent_tasks(
        self,
        user_id: Optional[str] = None,
        accessible_schedule_ids: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[ScheduleTaskResponse]:
        """Recent tasks feed.

        - `accessible_schedule_ids`가 주어지면 해당 스케줄(소유 + access_control read 공유받은 것)에
          속한 task만 반환. read 권한 공유자가 공유받은 스케줄의 실행 이력을 볼 수 있도록 필요.
        - 레거시: `user_id`만 주어지면 ScheduleTask.user_id(= 스케줄 소유자) 일치 기준. 공유 schedule은 제외됨.
        - 둘 다 None(=admin)이면 필터 없이 전체.
        """
        with get_db() as db:
            query = db.query(ScheduleTask).order_by(ScheduleTask.scheduled_at.desc())
            if accessible_schedule_ids is not None:
                if not accessible_schedule_ids:
                    return []
                query = query.filter(
                    ScheduleTask.schedule_id.in_(accessible_schedule_ids)
                )
            elif user_id:
                query = query.filter(ScheduleTask.user_id == user_id)
            tasks = query.limit(limit).all()

            results = []
            for task in tasks:
                schedule = db.query(Schedule).filter_by(id=task.schedule_id).first()
                results.append(
                    ScheduleTaskResponse.model_validate(
                        {
                            **ScheduleTaskModel.model_validate(task).model_dump(),
                            "schedule_name": schedule.name if schedule else None,
                        }
                    )
                )
            return results

    def reset_stale_tasks(self, timeout_seconds: int = 600) -> int:
        """Reset tasks stuck in 'running' status for more than timeout_seconds."""
        cutoff = int(time.time()) - timeout_seconds
        count = 0
        with get_db() as db:
            stale_tasks = (
                db.query(ScheduleTask)
                .filter(
                    ScheduleTask.status == "running",
                    ScheduleTask.started_at < cutoff,
                )
                .all()
            )
            for task in stale_tasks:
                if task.retry_count < task.max_retries:
                    task.status = "pending"
                    task.worker_id = None
                    task.started_at = None
                    task.retry_count += 1
                else:
                    task.status = "failed"
                    task.error_message = "Task timed out after maximum retries"
                    task.completed_at = int(time.time())
                count += 1
            if count > 0:
                db.commit()
        return count

    def cleanup_old_tasks(self, days: int = 30) -> int:
        """Delete completed/failed tasks older than specified days."""
        cutoff = int(time.time()) - (days * 86400)
        with get_db() as db:
            count = (
                db.query(ScheduleTask)
                .filter(
                    ScheduleTask.status.in_(["completed", "failed"]),
                    ScheduleTask.completed_at < cutoff,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            return count

    def cancel_orphaned_tasks(self) -> int:
        """Cancel tasks whose schedule no longer exists."""
        try:
            with get_db() as db:
                orphaned = (
                    db.query(ScheduleTask)
                    .filter(
                        ScheduleTask.status.in_(["pending", "running"]),
                        ~ScheduleTask.schedule_id.in_(db.query(Schedule.id)),
                    )
                    .update(
                        {
                            "status": "cancelled",
                            "completed_at": int(time.time()),
                            "error_message": "Orphaned task (schedule deleted)",
                        },
                        synchronize_session=False,
                    )
                )
                db.commit()
                return orphaned
        except Exception:
            return 0

    def cancel_tasks_by_schedule_id(self, schedule_id: str) -> int:
        """Cancel pending/running tasks for a schedule."""
        try:
            with get_db() as db:
                count = (
                    db.query(ScheduleTask)
                    .filter(
                        ScheduleTask.schedule_id == schedule_id,
                        ScheduleTask.status.in_(["pending", "running"]),
                    )
                    .update(
                        {
                            "status": "cancelled",
                            "completed_at": int(time.time()),
                            "error_message": "Schedule deleted",
                        },
                        synchronize_session=False,
                    )
                )
                db.commit()
                return count
        except Exception:
            return 0

    def delete_tasks_by_schedule_id(self, schedule_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(ScheduleTask).filter_by(schedule_id=schedule_id).delete()
                db.commit()
                return True
        except Exception:
            return False


ScheduleTasks = ScheduleTaskTable()
