"""
Scheduler Loop — runs every 60 seconds on the leader instance.

Responsibilities:
1. Acquire advisory lock (PostgreSQL) or proceed (SQLite — single instance).
2. Find schedules where is_active=True and next_run_at <= now.
3. Enqueue a ScheduleTask for each due schedule.
4. Recompute next_run_at for each schedule.
5. Reset stale running tasks (>10 min).
6. Cleanup old completed/failed tasks (>30 days).
"""

import asyncio
import logging
import time

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

SCHEDULER_INTERVAL = 60  # seconds
HOUSEKEEPING_INTERVAL = 300  # seconds — retention/KMS check 주기 (자체 throttle 있음)
ADVISORY_LOCK_ID = 20260226
HOUSEKEEPING_LOCK_ID = 20260227  # scheduler 와 분리 — 동시 실행 가능
_last_retention_cleanup_date: str = ""  # YYYY-MM-DD — 하루 1회 실행 보장

# Phase 4.5 — last in-process attempt at the KMS rotation check, used to
# honor the operator-configured interval without re-reading the
# PersistentConfig last_check_at every tick. The scheduler advisory lock
# already serializes ticks across workers, so an in-process timestamp
# is safe.
_kms_rotation_last_check_ts: int = 0


def _try_advisory_lock(lock_id: int = ADVISORY_LOCK_ID) -> bool:
    """Try to acquire a PostgreSQL advisory lock. Returns True for SQLite."""
    from open_webui.internal.db import SQLALCHEMY_DATABASE_URL, get_db

    if "sqlite" in SQLALCHEMY_DATABASE_URL:
        return True

    try:
        with get_db() as db:
            from sqlalchemy import text

            result = db.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
            row = result.fetchone()
            return row[0] if row else False
    except Exception as e:
        log.warning(f"Advisory lock failed: {e}")
        return False


def _release_advisory_lock(lock_id: int = ADVISORY_LOCK_ID):
    """Release the PostgreSQL advisory lock."""
    from open_webui.internal.db import SQLALCHEMY_DATABASE_URL, get_db

    if "sqlite" in SQLALCHEMY_DATABASE_URL:
        return

    try:
        with get_db() as db:
            from sqlalchemy import text

            db.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
    except Exception:
        pass


def _update_next_run(schedule):
    """Compute and store next_run_at based on cron_expression and timezone."""
    from datetime import datetime, timezone

    from croniter import croniter

    from open_webui.models.schedules import Schedules

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


async def scheduler_loop(app):
    """Main scheduler loop — runs as an asyncio task in the lifespan.

    Tick 주기는 SCHEDULER_INTERVAL(60s) 의 분(minute) 경계에 정렬된다:
    예) 부팅이 8:30:42 여도 tick 은 8:31:00, 8:32:00, ... 에 발생.
    이렇게 하면 "0 9 * * *" cron 이 9:00:00 에 due 가 됐을 때 9:00:00.x 에
    바로 enqueue 된다 (이전 코드는 부팅 시각에 따라 0~59초 임의 지연).
    """
    log.info("Scheduler loop started")

    # Wait a bit for the app to fully start
    await asyncio.sleep(10)

    while True:
        try:
            if _try_advisory_lock():
                try:
                    await _run_scheduler_tick(app)
                finally:
                    _release_advisory_lock()
        except Exception as e:
            log.error(f"Scheduler loop error: {e}", exc_info=True)

        # Sleep until next minute boundary. tick 자체가 길어 boundary 를 지나쳤으면
        # 다음 boundary 까지 대기 (음수/0 방지). edge case: tick 이 정확히 boundary
        # 에 끝나면 (now % 60 == 0) sleep = 60s 로 다음 boundary 까지 정상 대기.
        sleep_seconds = SCHEDULER_INTERVAL - (time.time() % SCHEDULER_INTERVAL)
        await asyncio.sleep(sleep_seconds)


async def _run_scheduler_tick(app):
    """Single tick of the scheduler — due 검출/enqueue/큐 정리만 담당.

    무거운 housekeeping (data retention, KMS rotation) 은 housekeeping_loop 로
    분리되어 있어 이 tick 을 블록하지 않는다. 9시 정각 due 검출이 retention
    cleanup 의 동기 DELETE 에 가려 늦어지는 문제 방지.
    """
    from open_webui.models.schedules import Schedules, ScheduleTasks

    now = int(time.time())

    # 1. Find due schedules
    due_schedules = Schedules.get_due_schedules(now)
    if due_schedules:
        log.info(f"Found {len(due_schedules)} due schedule(s)")

    for schedule in due_schedules:
        try:
            # Enqueue task (unique constraint prevents duplicates)
            ScheduleTasks.enqueue_task(schedule, schedule.next_run_at)
            # Update next_run_at
            _update_next_run(schedule)
        except Exception as e:
            log.error(f"Error processing schedule {schedule.id}: {e}")

    # 2. Reset stale running tasks (>10 minutes)
    stale_count = ScheduleTasks.reset_stale_tasks(timeout_seconds=600)
    if stale_count > 0:
        log.info(f"Reset {stale_count} stale task(s)")

    # 3. Cancel orphaned tasks (schedule deleted but task still running/pending)
    orphaned = ScheduleTasks.cancel_orphaned_tasks()
    if orphaned > 0:
        log.info(f"Cancelled {orphaned} orphaned task(s)")

    # 4. Cleanup old tasks (>30 days)
    cleaned = ScheduleTasks.cleanup_old_tasks(days=30)
    if cleaned > 0:
        log.info(f"Cleaned up {cleaned} old task(s)")


async def housekeeping_loop(app):
    """Periodic housekeeping — retention cleanup, KMS rotation check.

    scheduler_loop 와 분리된 별도 advisory lock 으로 단일 인스턴스 보장.
    주기 5분 — 두 작업 모두 자체적으로 throttle (하루 1회 / interval_hours)
    하므로 폴링이 잦아도 실 작업은 자주 안 돌아감. blocking sync DB 작업
    (대형 DELETE) 이 들어있어도 scheduler tick 은 영향받지 않음.
    """
    log.info("Housekeeping loop started")

    # 첫 실행은 부팅 직후 잠깐 대기 (scheduler 보다 늦게 — race 회피)
    await asyncio.sleep(20)

    while True:
        try:
            if _try_advisory_lock(HOUSEKEEPING_LOCK_ID):
                try:
                    _run_data_retention_cleanup(app)
                    _run_kms_rotation_check(app)
                finally:
                    _release_advisory_lock(HOUSEKEEPING_LOCK_ID)
        except Exception as e:
            log.error(f"Housekeeping loop error: {e}", exc_info=True)

        await asyncio.sleep(HOUSEKEEPING_INTERVAL)


def _run_kms_rotation_check(app):
    """Phase 4.5 — interval-driven KMS auto-rotation check.

    Skips when:
      * ``kms.rotation.auto_enabled`` is False (operator opt-in)
      * ``kms.provider`` is not ``azkv-env``
      * Less than ``check_interval_hours`` has passed since the last attempt
        (the leader-elected scheduler tick fires every 60s; we don't want
        to hit Azure KV every minute)

    On rotation success, the rotate flow itself fires Redis pub/sub
    invalidation so other workers reload their KMSRouter — see
    ``KMS_CONFIG_KEYS`` in ``main.py``.
    """
    global _kms_rotation_last_check_ts

    config = app.state.config

    if not getattr(config, "KMS_ROTATION_AUTO_ENABLED", False):
        return

    if (str(getattr(config, "KMS_PROVIDER", "fernet") or "")).lower() != "azkv-env":
        return

    interval_hours = max(
        int(getattr(config, "KMS_ROTATION_CHECK_INTERVAL_HOURS", 24)), 1
    )
    interval_seconds = interval_hours * 3600
    now_ts = int(time.time())
    if now_ts - _kms_rotation_last_check_ts < interval_seconds:
        return

    _kms_rotation_last_check_ts = now_ts

    try:
        from open_webui.utils.kms.rotation import check_and_rotate

        result = check_and_rotate(app)
        statuses = ", ".join(
            f"{t.get('classification')}={t.get('status')}"
            for t in result.get("tiers", [])
        )
        log.info(
            f"KMS auto-rotation check: ok={result.get('ok')} dry_run={result.get('dry_run')} "
            f"tiers=[{statuses}]"
        )
    except Exception as e:
        log.error(f"KMS auto-rotation check error: {e}", exc_info=True)


def _run_data_retention_cleanup(app):
    """보존 기간 정책에 따라 오래된 로그 삭제 (하루 1회)"""
    global _last_retention_cleanup_date

    from datetime import datetime

    config = app.state.config

    if not getattr(config, "ENABLE_DATA_RETENTION", False):
        return

    now = datetime.now()
    cleanup_hour = getattr(config, "DATA_RETENTION_CLEANUP_HOUR", 3)
    today = now.strftime("%Y-%m-%d")

    # 이미 오늘 실행했으면 스킵
    if _last_retention_cleanup_date == today:
        return

    # 설정된 시간 이후에만 실행
    if now.hour < cleanup_hour:
        return

    _last_retention_cleanup_date = today

    try:
        from open_webui.routers.data_retention import execute_cleanup

        results = execute_cleanup(config)
        total = sum(r.deleted_count for r in results)
        if total > 0:
            log.info(f"Data retention cleanup completed: {total} total rows deleted")
    except Exception as e:
        log.error(f"Data retention cleanup error: {e}", exc_info=True)
