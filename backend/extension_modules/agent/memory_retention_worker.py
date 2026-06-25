# backend/extension_modules/agent/memory_retention_worker.py
"""Memory retention worker — periodic TTL enforcement.

Runs as an asyncio background task. Each cycle:
1. Soft-delete memories whose TTL has expired
2. Hard-delete memories that were soft-deleted >30 days ago
"""

import asyncio
import logging
import time

from open_webui.internal.db import get_db
from open_webui.models.memories import Memory
from open_webui.models.memory_retention_policy import MemoryRetentionPolicy
from open_webui.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
HARD_DELETE_GRACE_DAYS = 30


async def run_retention_worker(interval_seconds: int = 3600) -> None:
    """Periodic retention enforcement. Fire-and-forget from lifespan."""
    logger.info(f"[RetentionWorker] Started (interval={interval_seconds}s)")
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            expired = await _process_expirations()
            purged = await _process_hard_deletes()
            if expired or purged:
                logger.info(
                    f"[RetentionWorker] Cycle complete: "
                    f"expired={expired}, purged={purged}"
                )
        except Exception as e:
            logger.warning(f"[RetentionWorker] Cycle failed: {e}")


async def _process_expirations() -> int:
    """Soft-delete memories whose TTL has expired. Returns count."""
    total = 0
    now = int(time.time())

    while True:
        batch_count = _expire_batch(now)
        total += batch_count
        if batch_count < BATCH_SIZE:
            break
        await asyncio.sleep(0.1)

    return total


def _expire_batch(now: int) -> int:
    """Process one batch of expired memories. Returns count processed."""
    from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

    with get_db() as db:
        try:
            rows = (
                db.query(Memory)
                .join(
                    MemoryRetentionPolicy,
                    Memory.retention_class == MemoryRetentionPolicy.retention_class,
                )
                .filter(
                    Memory.deleted_at.is_(None),
                    MemoryRetentionPolicy.ttl_days.isnot(None),
                    MemoryRetentionPolicy.org_id.is_(None),
                    Memory.created_at + MemoryRetentionPolicy.ttl_days * 86400 < now,
                )
                .limit(BATCH_SIZE)
                .all()
            )

            if not rows:
                return 0

            ids = [r.id for r in rows]

            db.query(Memory).filter(Memory.id.in_(ids)).update({"deleted_at": now})
            db.commit()

            for row in rows:
                try:
                    VECTOR_DB_CLIENT.delete(
                        collection_name=f"user-memory-{row.user_id}",
                        ids=[row.id],
                    )
                except Exception:
                    pass

                AuditLogger.log_delete(
                    resource_type="memory",
                    resource_id=row.id,
                    data={"retention_class": row.retention_class},
                    meta={
                        "actor": "system:retention",
                        "reason": "expired",
                        "user_id": row.user_id,
                    },
                )

            return len(ids)

        except Exception as e:
            logger.warning(f"[RetentionWorker] Expire batch failed: {e}")
            return 0


async def _process_hard_deletes() -> int:
    """Hard-delete memories soft-deleted >30 days ago. Returns count."""
    total = 0
    now = int(time.time())
    cutoff = now - (HARD_DELETE_GRACE_DAYS * 86400)

    while True:
        batch_count = _hard_delete_batch(cutoff)
        total += batch_count
        if batch_count < BATCH_SIZE:
            break
        await asyncio.sleep(0.1)

    return total


def _hard_delete_batch(cutoff: int) -> int:
    """Process one batch of hard deletes. Returns count processed."""
    with get_db() as db:
        try:
            ids = [
                row.id
                for row in (
                    db.query(Memory.id)
                    .filter(
                        Memory.deleted_at.isnot(None),
                        Memory.deleted_at < cutoff,
                    )
                    .limit(BATCH_SIZE)
                    .all()
                )
            ]

            if not ids:
                return 0

            db.query(Memory).filter(Memory.id.in_(ids)).delete(
                synchronize_session=False
            )
            db.commit()

            return len(ids)

        except Exception as e:
            logger.warning(f"[RetentionWorker] Hard delete batch failed: {e}")
            return 0
