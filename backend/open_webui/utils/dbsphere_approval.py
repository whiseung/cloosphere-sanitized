"""DbSphere SQL Editor approval gate — Redis-backed pending exec state.

Multi-worker safe: pending state stored in Redis with native TTL. confirm/reject
calls perform atomic GETDEL so only one worker can pop the same pending exec.

Audit trail goes to `audit_log` table (append-only) at the decision point —
commit/reject — not during pending. 사용자 결정 전의 임시 상태는 Redis 만 보유.

설계 결정:
- pending 키 TTL=5분 (사용자가 confirm/reject 결정할 충분한 시간).
- result_id 는 idempotency key 역할 — 같은 id 로 다시 confirm 호출하면 GETDEL 이
  `None` 반환 → 라우터가 audit_log 조회해 prior result 200 반환 (Stage 1 C2).
- Redis 가 unreachable 이면 set/pop 호출이 RedisError → 라우터가 503 반환.
"""

import json
import logging
from typing import Any, Optional

from open_webui.env import (
    REDIS_SENTINEL_HOSTS,
    REDIS_SENTINEL_PORT,
    REDIS_URL,
    SRC_LOG_LEVELS,
)
from open_webui.utils.redis import get_redis_connection, get_sentinels_from_env

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("UTILS", "INFO"))


PENDING_KEY_PREFIX = "dbsphere:pending_exec:"
DEFAULT_TTL_SECONDS = 300  # 5 minutes


def _redis_client():
    """Get a redis connection using the project's standard helper.

    Raises redis.RedisError (or subclass) if unreachable — caller converts
    to HTTPException(503) at the router layer.
    """
    if not REDIS_URL:
        raise RuntimeError(
            "REDIS_URL is not configured — DbSphere SQL Editor approval gate "
            "requires Redis (multi-worker safe state). Set REDIS_URL or disable "
            "DbSphere SQL Editor."
        )
    return get_redis_connection(
        REDIS_URL,
        get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
    )


def redis_health_check() -> bool:
    """PING Redis. Returns True if reachable; False otherwise (no exception)."""
    try:
        return bool(_redis_client().ping())
    except Exception as e:  # noqa: BLE001 — health check returns bool
        log.warning("DbSphere approval gate: redis_health_check failed: %s", e)
        return False


def set_pending(
    result_id: str,
    payload: dict[str, Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """SET key with TTL. JSON-serialize payload.

    Payload should include at minimum: sql, op (READ/WRITE), user_id,
    dbsphere_id, affected_preview, created_at.
    """
    key = PENDING_KEY_PREFIX + result_id
    _redis_client().set(key, json.dumps(payload), ex=ttl_seconds)


def pop_pending(result_id: str) -> Optional[dict[str, Any]]:
    """GETDEL — atomic read+delete. Returns None if key absent or expired.

    `None` return means: pending already consumed (double-confirm) or TTL
    expired. Router differentiates via audit_log lookup.
    """
    key = PENDING_KEY_PREFIX + result_id
    raw = _redis_client().getdel(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(
            "DbSphere approval gate: malformed pending payload %s: %s", result_id, e
        )
        return None


def peek_pending(result_id: str) -> Optional[dict[str, Any]]:
    """GET without delete — used by /reject to verify ownership before discard."""
    key = PENDING_KEY_PREFIX + result_id
    raw = _redis_client().get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(
            "DbSphere approval gate: malformed pending payload %s: %s", result_id, e
        )
        return None


def discard_pending(result_id: str) -> bool:
    """DEL — for reject flow. Returns True if a key was deleted."""
    key = PENDING_KEY_PREFIX + result_id
    return bool(_redis_client().delete(key))
