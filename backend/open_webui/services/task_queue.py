"""
Background Task Queue Service.

Redis Streams 기반 태스크 큐 + 내부 consumer.
Redis 미연결 시 InProcess 폴백 (기존 ThreadPoolExecutor).
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import redis

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

STREAM_NAME = "cloosphere:tasks"
CONSUMER_GROUP = "workers"
CONSUMER_NAME = f"consumer-{socket.gethostname()}-{os.getpid()}"
CONCURRENT_TASKS = int(os.environ.get("WORKER_CONCURRENT_TASKS", "4"))
# Redis xreadgroup 블로킹 시간(ms). 짧을수록 빈 큐 → 새 메시지 반응속도 빠름.
# 너무 짧으면 CPU 낭비이지만 100ms는 안전한 절충값.
XREAD_BLOCK_MS = int(os.environ.get("WORKER_XREAD_BLOCK_MS", "100"))

# Redis 폴링 전용 executor (파일 처리 스레드와 분리)
_redis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="redis_poll")


# ---------------------------------------------------------------------------
# Task Message
# ---------------------------------------------------------------------------


class TaskMessage:
    """큐에 발행되는 태스크 메시지.

    retry_count / max_retries: 핸들러 예외 시 컨슈머가 자동 재발행.
    기본 0/0 → 재시도 없음 (기존 file_processing 등 호환).
    """

    def __init__(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: int = 5,
        task_id: str | None = None,
        retry_count: int = 0,
        max_retries: int = 0,
    ):
        self.task_id = task_id or str(uuid.uuid4())
        self.task_type = task_type
        self.payload = payload
        self.priority = priority
        self.created_at = int(time.time())
        self.retry_count = retry_count
        self.max_retries = max_retries

    def to_dict(self) -> dict[str, str]:
        """Redis Stream 필드용 직렬화."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": json.dumps(self.payload, ensure_ascii=False),
            "priority": str(self.priority),
            "created_at": str(self.created_at),
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "TaskMessage":
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            payload=json.loads(data["payload"]),
            priority=int(data.get("priority", "5")),
            retry_count=int(data.get("retry_count", "0")),
            max_retries=int(data.get("max_retries", "0")),
        )


# ---------------------------------------------------------------------------
# Abstract TaskQueue
# ---------------------------------------------------------------------------


class TaskQueue(ABC):
    @abstractmethod
    async def publish(self, message: TaskMessage) -> str:
        """태스크를 큐에 발행. task_id 반환."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """큐 상태 확인."""

    @abstractmethod
    async def get_queue_stats(self) -> dict[str, Any]:
        """큐 통계."""

    @abstractmethod
    async def list_tasks(self, count: int = 50) -> list[dict[str, Any]]:
        """큐에 있는 태스크 목록 조회."""

    @abstractmethod
    async def delete_task(self, msg_id: str) -> bool:
        """특정 메시지 삭제."""

    @abstractmethod
    async def clear_queue(self) -> int:
        """큐 전체 비우기."""

    async def list_consumers(self) -> list[dict[str, Any]]:
        """Consumer group 내 consumer 목록. 기본 구현은 빈 리스트."""
        return []

    async def list_pending_messages(
        self, count: int = 100, min_idle_ms: int = 0
    ) -> list[dict[str, Any]]:
        """Pending 메시지 상세 목록. 기본 구현은 빈 리스트."""
        return []

    async def delete_consumer(
        self, consumer_name: str, reclaim_pending: bool = False
    ) -> dict[str, Any]:
        """특정 consumer 삭제. 기본 구현은 no-op."""
        return {
            "success": False,
            "reclaimed": 0,
            "pending_before": 0,
            "error": "not_supported",
        }

    async def cleanup_zombie_consumers(self, idle_threshold_ms: int = 3_600_000) -> int:
        """좀비 consumer 일괄 정리. 기본 구현은 no-op."""
        return 0

    async def reclaim_stuck_messages(
        self, min_idle_ms: int = 300_000
    ) -> dict[str, Any]:
        """stuck된 pending 메시지 강제 ack. 기본 구현은 no-op."""
        return {"reclaimed": 0, "errors": 0}

    async def ack_and_delete_message(self, msg_id: str) -> dict[str, Any]:
        """단일 pending 메시지 강제 ack + delete. 기본 구현은 no-op."""
        return {"success": False, "error": "not_supported"}

    # 배치 워커에서 job-단위 원자적 카운터 / finalize claim 을 쓰기 위한
    # helper. RedisStreamQueue 가 실제 구현을 제공하고, InProcess 모드는
    # 싱글 프로세스라 finalize 레이스가 없으므로 기본 구현은 no-op 반환.
    async def batch_counter_incr(self, key: str, ttl_seconds: int = 3600) -> int:
        return 0

    async def batch_counter_get(self, key: str) -> int:
        return 0

    async def batch_claim_once(self, key: str, ttl_seconds: int = 3600) -> bool:
        """첫 호출자만 True 반환 (원자적 SETNX). 기본은 항상 True (single-worker)."""
        return True


# ---------------------------------------------------------------------------
# Redis Streams Implementation
# ---------------------------------------------------------------------------


class RedisStreamQueue(TaskQueue):
    """Redis Streams 기반 태스크 큐."""

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._ensure_consumer_group()

    def _ensure_consumer_group(self):
        try:
            self._redis.xgroup_create(
                STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True
            )
            log.info(f"Created consumer group '{CONSUMER_GROUP}' on '{STREAM_NAME}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def publish(self, message: TaskMessage) -> str:
        try:
            self._redis.xadd(STREAM_NAME, message.to_dict())
            log.info(f"Published task {message.task_id} ({message.task_type}) to queue")
            return message.task_id
        except Exception as e:
            log.error(f"Failed to publish task: {e}")
            raise

    async def health_check(self) -> dict[str, Any]:
        try:
            self._redis.ping()
            return {"status": "connected", "stream": STREAM_NAME}
        except Exception as e:
            return {"status": "disconnected", "error": str(e)}

    async def get_queue_stats(self) -> dict[str, Any]:
        try:
            stream_len = self._redis.xlen(STREAM_NAME)
            groups = self._redis.xinfo_groups(STREAM_NAME)
            pending = 0
            total_consumers = 0
            for g in groups:
                if g.get("name") == CONSUMER_GROUP:
                    pending = g.get("pending", 0)
                    total_consumers = g.get("consumers", 0)
                    break
            return {
                "total": stream_len,
                "pending": pending,
                "consumers": total_consumers,
            }
        except Exception:
            return {"total": 0, "pending": 0, "consumers": 0}

    async def list_tasks(self, count: int = 50) -> list[dict[str, Any]]:
        try:
            entries = self._redis.xrange(STREAM_NAME, count=count)
            tasks = []
            for msg_id, data in entries:
                task = {
                    "msg_id": msg_id,
                    "task_id": data.get("task_id", ""),
                    "task_type": data.get("task_type", ""),
                    "priority": data.get("priority", "5"),
                    "created_at": int(data.get("created_at", "0")),
                }
                try:
                    payload = json.loads(data.get("payload", "{}"))
                    task["file_id"] = payload.get("file_id", "")
                    task["user_id"] = payload.get("user_id", "")
                except Exception:
                    pass
                tasks.append(task)
            return tasks
        except Exception:
            return []

    async def delete_task(self, msg_id: str) -> bool:
        try:
            self._redis.xdel(STREAM_NAME, msg_id)
            return True
        except Exception:
            return False

    async def clear_queue(self) -> int:
        try:
            length = self._redis.xlen(STREAM_NAME)
            self._redis.xtrim(STREAM_NAME, maxlen=0)
            return length
        except Exception:
            return 0

    # ── Batch job helpers ──────────────────────────────────────────────
    async def batch_counter_incr(self, key: str, ttl_seconds: int = 3600) -> int:
        def _run():
            val = self._redis.incr(key)
            self._redis.expire(key, ttl_seconds)
            return int(val)

        return await asyncio.to_thread(_run)

    async def batch_counter_get(self, key: str) -> int:
        def _run():
            raw = self._redis.get(key)
            return int(raw) if raw else 0

        return await asyncio.to_thread(_run)

    async def batch_claim_once(self, key: str, ttl_seconds: int = 3600) -> bool:
        def _run():
            return bool(self._redis.set(key, "1", ex=ttl_seconds, nx=True))

        return await asyncio.to_thread(_run)

    # ─────────────────────────────────
    # Consumer / Pending 관리 (좀비 정리용)
    # ─────────────────────────────────

    async def list_consumers(self) -> list[dict[str, Any]]:
        """Consumer group의 모든 consumer 정보 반환.

        반환 항목별:
        - name: consumer 이름
        - pending: 처리 중(미ack) 메시지 수
        - idle_ms: 마지막 활동 이후 경과 시간(ms)
        - is_zombie: idle 1시간 이상 + pending 0
        """
        try:
            consumers = self._redis.xinfo_consumers(STREAM_NAME, CONSUMER_GROUP)
            result = []
            for c in consumers:
                idle = int(c.get("idle", 0))
                pending = int(c.get("pending", 0))
                result.append(
                    {
                        "name": c.get("name", ""),
                        "pending": pending,
                        "idle_ms": idle,
                        "is_zombie": idle > 3_600_000 and pending == 0,
                    }
                )
            # idle 내림차순 → 가장 오래 idle인 것부터 (좀비 우선)
            result.sort(key=lambda x: x["idle_ms"], reverse=True)
            return result
        except Exception as e:
            log.warning(f"list_consumers failed: {e}")
            return []

    async def list_pending_messages(
        self, count: int = 20, min_idle_ms: int = 0
    ) -> list[dict[str, Any]]:
        """가장 오래된 미처리(pending) 메시지 목록.

        XPENDING은 msg_id 순(= 발행 순서)으로 반환하므로
        앞쪽이 가장 오래된 메시지다. UI용 샘플 20개 반환.

        - count: 최대 반환 개수 (기본 20)
        - min_idle_ms: 이 시간 이상 stuck된 것만 (0이면 전체)
        """
        try:
            details = self._redis.xpending_range(
                STREAM_NAME,
                CONSUMER_GROUP,
                min="-",
                max="+",
                count=count,
            )
            result = []
            for d in details:
                idle = int(d.get("time_since_delivered", 0))
                if idle < min_idle_ms:
                    continue
                result.append(
                    {
                        "msg_id": d.get("message_id", ""),
                        "consumer": d.get("consumer", ""),
                        "idle_ms": idle,
                        "deliveries": int(d.get("times_delivered", 0)),
                    }
                )
            return result
        except Exception as e:
            log.warning(f"list_pending_messages failed: {e}")
            return []

    async def delete_consumer(
        self, consumer_name: str, reclaim_pending: bool = False
    ) -> dict[str, Any]:
        """특정 consumer 삭제.

        ⚠ Redis XGROUP DELCONSUMER는 pending 메시지가 있어도 그냥 삭제하며,
        그 메시지들은 XPENDING 목록에서 완전히 사라진다.
        (group.last-delivered-id는 그대로라서 > 배달로는 다시 안 옴 → 유실)

        따라서 안전한 사용을 위해 기본 동작은:
        - pending == 0 → 바로 삭제
        - pending > 0 → **실패 반환** (호출자가 명시적으로 처리해야 함)

        reclaim_pending=True인 경우:
        - pending 메시지를 먼저 ack + xdel로 정리한 뒤 consumer 삭제
        - 반환값에 reclaimed 개수 포함

        반환:
          { success: bool, reclaimed: int, pending_before: int, error?: str }
        """
        try:
            consumers = self._redis.xinfo_consumers(STREAM_NAME, CONSUMER_GROUP)
            target = next(
                (c for c in consumers if c.get("name") == consumer_name), None
            )
            if target is None:
                return {
                    "success": False,
                    "reclaimed": 0,
                    "pending_before": 0,
                    "error": "consumer_not_found",
                }

            pending_before = int(target.get("pending", 0))

            if pending_before > 0 and not reclaim_pending:
                # 안전장치: pending이 있으면 reclaim_pending 없이는 거부
                return {
                    "success": False,
                    "reclaimed": 0,
                    "pending_before": pending_before,
                    "error": "has_pending",
                }

            # reclaim: 해당 consumer의 pending 메시지를 ack + delete
            reclaimed = 0
            if pending_before > 0:
                details = self._redis.xpending_range(
                    STREAM_NAME,
                    CONSUMER_GROUP,
                    min="-",
                    max="+",
                    count=1000,
                    consumername=consumer_name,
                )
                for d in details:
                    msg_id = d.get("message_id", "")
                    if not msg_id:
                        continue
                    try:
                        self._redis.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                        self._redis.xdel(STREAM_NAME, msg_id)
                        reclaimed += 1
                    except Exception as e:
                        log.warning(f"failed to reclaim {msg_id}: {e}")

            # consumer 삭제
            self._redis.xgroup_delconsumer(STREAM_NAME, CONSUMER_GROUP, consumer_name)
            return {
                "success": True,
                "reclaimed": reclaimed,
                "pending_before": pending_before,
            }
        except Exception as e:
            log.warning(f"delete_consumer({consumer_name}) failed: {e}")
            return {
                "success": False,
                "reclaimed": 0,
                "pending_before": 0,
                "error": str(e),
            }

    async def cleanup_zombie_consumers(self, idle_threshold_ms: int = 3_600_000) -> int:
        """좀비 consumer 일괄 정리.

        조건: idle > threshold AND pending == 0
        반환: 삭제된 consumer 수
        """
        deleted = 0
        try:
            consumers = self._redis.xinfo_consumers(STREAM_NAME, CONSUMER_GROUP)
            for c in consumers:
                idle = int(c.get("idle", 0))
                pending = int(c.get("pending", 0))
                if idle > idle_threshold_ms and pending == 0:
                    name = c.get("name", "")
                    if name:
                        try:
                            self._redis.xgroup_delconsumer(
                                STREAM_NAME, CONSUMER_GROUP, name
                            )
                            deleted += 1
                        except Exception as e:
                            log.warning(f"failed to delete zombie {name}: {e}")
            return deleted
        except Exception as e:
            log.warning(f"cleanup_zombie_consumers failed: {e}")
            return deleted

    async def ack_and_delete_message(self, msg_id: str) -> dict[str, Any]:
        """단일 pending 메시지를 강제 ack + delete.

        pending 메시지를 XDEL만 하면 PEL에 남아 consumer pending 카운트가
        꼬이므로, 반드시 XACK → XDEL 순서로 같이 수행한다.

        반환: { success: bool, consumer?: str, error?: str }
        """
        try:
            details = self._redis.xpending_range(
                STREAM_NAME,
                CONSUMER_GROUP,
                min=msg_id,
                max=msg_id,
                count=1,
            )
            if not details:
                return {"success": False, "error": "not_pending"}
            consumer = details[0].get("consumer", "")
            self._redis.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            self._redis.xdel(STREAM_NAME, msg_id)
            return {"success": True, "consumer": consumer}
        except Exception as e:
            log.warning(f"ack_and_delete_message({msg_id}) failed: {e}")
            return {"success": False, "error": str(e)}

    async def reclaim_stuck_messages(
        self, min_idle_ms: int = 300_000
    ) -> dict[str, Any]:
        """stuck된 pending 메시지를 강제로 ack + delete.

        오래된(min_idle_ms 이상) pending 메시지는 보통 crash된 워커가
        들고 있던 것이므로 ack 처리하여 큐에서 제거한다.

        - min_idle_ms: 이 시간 이상 stuck된 것만 정리 (기본 5분)
        반환: { reclaimed: int, errors: int }
        """
        reclaimed = 0
        errors = 0
        try:
            details = self._redis.xpending_range(
                STREAM_NAME,
                CONSUMER_GROUP,
                min="-",
                max="+",
                count=1000,
            )
            for d in details:
                idle = int(d.get("time_since_delivered", 0))
                if idle < min_idle_ms:
                    continue
                msg_id = d.get("message_id", "")
                if not msg_id:
                    continue
                try:
                    self._redis.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                    self._redis.xdel(STREAM_NAME, msg_id)
                    reclaimed += 1
                except Exception as e:
                    errors += 1
                    log.warning(f"failed to reclaim {msg_id}: {e}")
            return {"reclaimed": reclaimed, "errors": errors}
        except Exception as e:
            log.warning(f"reclaim_stuck_messages failed: {e}")
            return {"reclaimed": reclaimed, "errors": errors + 1}


# ---------------------------------------------------------------------------
# InProcess Fallback
# ---------------------------------------------------------------------------


class InProcessQueue(TaskQueue):
    """Redis 미연결 시 폴백."""

    async def publish(self, message: TaskMessage) -> str:
        log.debug(f"InProcessQueue: task {message.task_id} not queued (fallback mode)")
        return message.task_id

    async def health_check(self) -> dict[str, Any]:
        return {"status": "in_process", "stream": "none"}

    async def get_queue_stats(self) -> dict[str, Any]:
        return {"total": 0, "pending": 0, "consumers": 0}

    async def list_tasks(self, count: int = 50) -> list[dict[str, Any]]:
        return []

    async def delete_task(self, msg_id: str) -> bool:
        return False

    async def clear_queue(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_task_queue(redis_client: Optional[redis.Redis] = None) -> TaskQueue:
    """Redis 연결 상태에 따라 적절한 큐 구현 반환."""
    if redis_client:
        try:
            redis_client.ping()
            queue = RedisStreamQueue(redis_client)
            log.info("TaskQueue: Using Redis Streams")
            return queue
        except Exception as e:
            log.warning(
                f"TaskQueue: Redis unavailable ({e}), falling back to InProcess"
            )

    log.info("TaskQueue: Using InProcess fallback")
    return InProcessQueue()


# ---------------------------------------------------------------------------
# Internal Consumer (메인 서버 내부에서 실행)
# ---------------------------------------------------------------------------


async def _process_task(app, task_data: dict):
    """태스크를 파싱하고 처리."""
    task_type = task_data.get("task_type")
    task_id = task_data.get("task_id")
    payload = json.loads(task_data.get("payload", "{}"))

    log.info(f"Processing task {task_id} (type={task_type})")

    if task_type == "file_processing":
        await _process_file_task(app, task_id, payload)
    elif task_type == "kg_kb_chunk":
        from extension_modules.knowledge_graph.kb_chunk_worker import (
            process_kb_chunk_task,
        )

        await process_kb_chunk_task(app, task_id, payload)
    elif task_type == "glossary_extract_values":
        from extension_modules.glossary.extract_worker import (
            process_glossary_extract_task,
        )

        await process_glossary_extract_task(app, task_id, payload)
    elif task_type == "kg_link_sync":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_link_sync_task,
        )

        await process_kg_link_sync_task(app, task_id, payload)
    elif task_type == "kg_dbsphere_sync_one":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_dbsphere_sync_one_task,
        )

        await process_kg_dbsphere_sync_one_task(app, task_id, payload)
    elif task_type == "kg_glossary_entries_chunk":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_glossary_entries_chunk_task,
        )

        await process_kg_glossary_entries_chunk_task(app, task_id, payload)
    elif task_type == "kg_link_match_phase":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_link_match_phase_task,
        )

        await process_kg_link_match_phase_task(app, task_id, payload)
    elif task_type == "kg_link_match_kb":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_link_match_kb_task,
        )

        await process_kg_link_match_kb_task(app, task_id, payload)
    elif task_type == "kg_link_db_derivation":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_link_db_derivation_task,
        )

        await process_kg_link_db_derivation_task(app, task_id, payload)
    elif task_type == "kg_link_doc_extract":
        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_doc_extract_task,
        )

        await process_kg_doc_extract_task(app, task_id, payload)
    elif task_type == "kb_filter_extract":
        from open_webui.retrieval.filter_extract_worker import (
            process_filter_extract_task,
        )

        await process_filter_extract_task(app, task_id, payload)
    elif task_type == "knowledge_file_delete":
        from open_webui.services.knowledge_file_delete_worker import (
            process_knowledge_file_delete_task,
        )

        await process_knowledge_file_delete_task(app, task_id, payload)
    elif task_type == "kb_clone":
        from open_webui.services.kb_clone_worker import process_kb_clone_task

        await process_kb_clone_task(app, task_id, payload)
    else:
        log.warning(f"Unknown task type: {task_type}")


async def _handle_permanent_failure(app, task_data: dict, error: str) -> None:
    """재시도 한도 초과 시 호출. task_type 별로 fan-in/parent-job 갱신 등."""
    task_type = task_data.get("task_type")
    task_id = task_data.get("task_id")
    try:
        payload = json.loads(task_data.get("payload", "{}"))
    except Exception:
        payload = {}

    if task_type == "kg_kb_chunk":
        try:
            from extension_modules.knowledge_graph.kb_chunk_worker import (
                handle_chunk_permanent_failure,
            )

            await handle_chunk_permanent_failure(app, task_id, payload, error)
        except Exception as e:
            log.exception(f"kg_kb_chunk permanent failure handler crashed: {e}")


def _mark_file_processing_failed(file_id: str, error: str) -> str:
    """processing_job 을 failed 로 강제 기록하고 filename 을 돌려준다."""
    from open_webui.models.files import Files

    filename = "Unknown"
    try:
        file = Files.get_file_by_id(file_id)
        if file:
            filename = file.filename or "Unknown"
            current_data = file.data or {}
            current_data["processing_job"] = {
                **current_data.get("processing_job", {}),
                "status": "failed",
                "error": error,
                "completed_at": int(time.time()),
            }
            Files.update_file_data_by_id(file_id, current_data)
    except Exception as e:
        log.error(f"Failed to mark file {file_id} as failed: {e}")
    return filename


async def _notify_file_processing_failed(
    user_id, file_id, filename, error, batch_id, client_session_id
):
    """파일 처리 실패를 프론트에 알려 무한 스피너를 방지한다."""
    from open_webui.socket.main import send_notification_to_user

    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type="file-processing-failed",
            data={
                "file_id": file_id,
                "filename": filename,
                "error": error,
                "message": f"'{filename}' 파일 처리가 실패했습니다: {error}",
                "batch_id": batch_id,
                "client_session_id": client_session_id,
            },
        )
    except Exception as e:
        log.warning(f"Failed to send failure notification: {e}")


async def _process_file_task(app, task_id: str, payload: dict):
    """파일 처리 — 기존 _run_file_processing_background 재사용."""
    from open_webui.routers.retrieval import (
        _file_processing_executor,
        _run_file_processing_sync,
    )
    from open_webui.socket.main import send_notification_to_user

    file_id = payload["file_id"]
    user_id = payload.get("user_id", "")
    collection_name = payload.get("collection_name")
    content = payload.get("content")
    # 배치 업로드 추적 — 알림에 echo (벨 전용 진행률 집계 + 발신 세션 식별)
    batch_id = payload.get("batch_id")
    client_session_id = payload.get("client_session_id")

    # 파일 처리 timeout: 기본은 각 로더가 작업 특성에 맞게 내부적으로 관리한다.
    # (llm_vision 은 aload 의 페이지 수 기반 backstop = max(600, pages*20)s 으로 동적 제어).
    # 고정 wall-clock cap 은 대용량 PDF (수백 페이지) 를 추출 완료 직전에 폐기시키므로
    # 기본값을 두지 않고, 운영상 강제 상한이 필요할 때만 FILE_PROCESSING_TIMEOUT 으로 지정.
    _timeout_env = os.environ.get("FILE_PROCESSING_TIMEOUT", "").strip()
    OVERALL_TIMEOUT = int(_timeout_env) if _timeout_env else None

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                _file_processing_executor,
                _run_file_processing_sync,
                app,
                file_id,
                user_id,
                collection_name,
                content,
            ),
            timeout=OVERALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        err_msg = f"Processing timed out after {OVERALL_TIMEOUT}s"
        log.error(f"Task {task_id} timed out after {OVERALL_TIMEOUT}s")
        filename = _mark_file_processing_failed(file_id, err_msg)
        await _notify_file_processing_failed(
            user_id, file_id, filename, err_msg, batch_id, client_session_id
        )
        return
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        log.error(f"Task {task_id} failed: {err_msg}", exc_info=True)
        # _run_file_processing_sync 는 내부 try/except 로 대부분의 오류를 self-report
        # 하지만, 여기까지 전파된 예외(executor 실패 등)는 status 가 비종료로 남아
        # UI 가 무한 스피너에 빠진다 → 강제로 failed 기록 + 실패 이벤트 발송.
        filename = _mark_file_processing_failed(file_id, err_msg)
        await _notify_file_processing_failed(
            user_id, file_id, filename, err_msg, batch_id, client_session_id
        )
        return

    # Socket.IO 알림 (같은 프로세스이므로 직접 발송 가능)
    if result.get("success"):
        knowledge_id = result.get("pending_knowledge_id")
        filename = result.get("filename", "Unknown")
        message = f"'{filename}' 파일 처리가 완료되었습니다."
        if knowledge_id:
            message = f"'{filename}' 파일이 지식기반에 추가되었습니다."

        try:
            await send_notification_to_user(
                user_id=user_id,
                event_type="file-processing-completed",
                data={
                    "file_id": file_id,
                    "filename": filename,
                    "collection_name": result.get("collection_name"),
                    "knowledge_id": knowledge_id,
                    "message": message,
                    "batch_id": batch_id,
                    "client_session_id": client_session_id,
                },
            )
        except Exception as e:
            log.warning(f"Failed to send notification: {e}")

        # 필터 추출 자동 체이닝: KB에 추출 가능한 필터가 있으면 큐에 등록
        if knowledge_id:
            await _chain_filter_extract(app, knowledge_id, file_id, user_id)
    else:
        filename = result.get("filename", "Unknown")
        error = result.get("error", "Unknown error")
        try:
            await send_notification_to_user(
                user_id=user_id,
                event_type="file-processing-failed",
                data={
                    "file_id": file_id,
                    "filename": filename,
                    "error": error,
                    "message": f"'{filename}' 파일 처리가 실패했습니다: {error}",
                    "batch_id": batch_id,
                    "client_session_id": client_session_id,
                },
            )
        except Exception as e:
            log.warning(f"Failed to send failure notification: {e}")

    log.info(f"Task {task_id} done: success={result.get('success', False)}")


async def _chain_filter_extract(app, knowledge_id: str, file_id: str, user_id: str):
    """파일 처리 완료 후 필터 추출 자동 체이닝."""
    try:
        from open_webui.models.knowledge import Knowledges

        kb = Knowledges.get_knowledge_by_id(knowledge_id)
        if not kb or not kb.meta:
            return

        filter_schema = kb.meta.get("filter_schema", [])
        if not filter_schema:
            return

        # 추출 가능한 필드가 하나라도 있는지 확인
        has_extractable = any(
            f.get("extraction_prompt", "").strip()
            or (f.get("type") == "glossary" and f.get("glossary_id"))
            for f in filter_schema
        )
        if not has_extractable:
            return

        # LLM 모델 config resolve (Model Not Found 방지)
        pre_resolved = None
        has_llm_fields = any(
            f.get("extraction_prompt", "").strip() for f in filter_schema
        )
        if has_llm_fields:
            model_id = kb.meta.get("filter_extraction_model", "")
            if model_id:
                from extension_modules.utils.llm import get_model_config_from_app

                pre_resolved = get_model_config_from_app(app, model_id)

        task_queue = getattr(app.state, "task_queue", None)
        if not task_queue:
            return

        await task_queue.publish(
            TaskMessage(
                task_type="kb_filter_extract",
                payload={
                    "kb_id": knowledge_id,
                    "file_id": file_id,
                    "user_id": user_id,
                    "filter_schema": filter_schema,
                    "pre_resolved_model_config": pre_resolved,
                },
            )
        )
        log.info(f"Chained filter extract for file {file_id} in KB {knowledge_id}")
    except Exception as e:
        log.warning(f"Failed to chain filter extract: {e}")


async def start_internal_consumer(app, redis_client: redis.Redis):
    """메인 서버 내부 consumer 루프 시작."""
    log.info(
        f"Internal consumer '{CONSUMER_NAME}' started, concurrency={CONCURRENT_TASKS}"
    )

    semaphore = asyncio.Semaphore(CONCURRENT_TASKS)
    loop = asyncio.get_event_loop()

    async def handle_message(msg_id, data):
        async with semaphore:
            try:
                await _process_task(app, data)
                redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                redis_client.xdel(STREAM_NAME, msg_id)
            except Exception as e:
                # 재시도 정책: max_retries가 양수면 retry_count++ 후 republish
                retry_count = int(data.get("retry_count", "0") or 0)
                max_retries = int(data.get("max_retries", "0") or 0)
                task_id = data.get("task_id", "?")
                task_type = data.get("task_type", "?")

                if max_retries > 0 and retry_count < max_retries:
                    # 새 retry_count로 republish
                    try:
                        retry_data = dict(data)
                        retry_data["retry_count"] = str(retry_count + 1)
                        # 백오프: 0.5s × 2^attempt
                        backoff = 0.5 * (2**retry_count)
                        await asyncio.sleep(backoff)
                        redis_client.xadd(STREAM_NAME, retry_data)
                        log.warning(
                            f"Retry {retry_count + 1}/{max_retries} for "
                            f"{task_type}/{task_id}: {e}"
                        )
                    except Exception as re:
                        log.exception(f"Failed to republish retry: {re}")
                    finally:
                        try:
                            redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                            redis_client.xdel(STREAM_NAME, msg_id)
                        except Exception:
                            pass
                else:
                    # 재시도 없음 또는 한도 초과 → 최종 실패
                    if max_retries > 0:
                        log.error(
                            f"Permanent failure after {retry_count} retries for "
                            f"{task_type}/{task_id}: {e}"
                        )
                        # 최종 실패 핸들러 호출 (있으면)
                        try:
                            await _handle_permanent_failure(app, data, str(e))
                        except Exception as fhe:
                            log.exception(f"permanent-failure handler error: {fhe}")
                    else:
                        log.exception(f"Failed to process message {msg_id}: {e}")
                    try:
                        redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                        redis_client.xdel(STREAM_NAME, msg_id)
                    except Exception:
                        pass

    while True:
        try:
            messages = await loop.run_in_executor(
                _redis_executor,
                lambda: redis_client.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {STREAM_NAME: ">"},
                    count=CONCURRENT_TASKS,
                    block=XREAD_BLOCK_MS,
                ),
            )

            if not messages:
                continue

            tasks = []
            for stream, entries in messages:
                for msg_id, data in entries:
                    tasks.append(asyncio.create_task(handle_message(msg_id, data)))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except redis.ResponseError as e:
            # Redis 재시작 / FLUSHDB / 외부 XGROUP DESTROY 등으로 group 이 사라진 경우
            # 자동 복구. 미복구 시 영구 dead loop 가 되어 publish 된 메시지가 처리 안 됨.
            if "NOGROUP" in str(e):
                log.warning(
                    f"Consumer group missing on '{STREAM_NAME}', recreating: {e}"
                )
                try:
                    await loop.run_in_executor(
                        _redis_executor,
                        lambda: redis_client.xgroup_create(
                            STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True
                        ),
                    )
                    log.info(
                        f"Recreated consumer group '{CONSUMER_GROUP}' on '{STREAM_NAME}'"
                    )
                except redis.ResponseError as ge:
                    # 멀티 인스턴스 환경에서 다른 워커가 먼저 만든 경우
                    if "BUSYGROUP" not in str(ge):
                        log.exception(f"Failed to recreate consumer group: {ge}")
                await asyncio.sleep(1)
                continue
            log.exception(f"Consumer loop response error: {e}")
            await asyncio.sleep(1)
        except redis.ConnectionError:
            log.warning("Redis connection lost, reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            log.exception(f"Consumer loop error: {e}")
            await asyncio.sleep(1)
