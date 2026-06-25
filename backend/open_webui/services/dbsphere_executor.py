"""DbSphere SQL Editor — 직접 실행 서비스.

`POST /api/v1/dbsphere/{id}/sql/execute` 등 신규 라우터가 위임하는 서비스.

핵심 책임:
- DbSphere connection 으로부터 sql_runner 인스턴스화 (factory 재사용)
- SQL classifier 호출 → READ/WRITE/UNKNOWN/INVALID 분류
- READ: 즉시 실행 + 결과 grid + row cap 적용
- WRITE: pending Redis 키 등록 → result_id 반환 (실행은 confirm 시점)
- commit_write: pending pop → 실제 실행 + audit_log (SQL_COMMITTED) 또는 SQL_FAILED
- reject_write: pending discard + audit_log (SQL_REJECTED)

C1 안전 시퀀싱:
1. /execute (WRITE): classify → pending_exec Redis SET EX 300 → return result_id+preview
2. /confirm: pop_pending (atomic GETDEL) → 없으면 410 → 있으면 sql_runner 실행 (asyncio
   timeout) → audit_log INSERT (SQL_COMMITTED 또는 SQL_FAILED)
3. /reject: discard_pending → audit_log INSERT (SQL_REJECTED)

C3 query timeout:
- asyncio.wait_for(sql_runner.run_sql(...), timeout=DBSPHERE_EXECUTE_TIMEOUT_S).
- DB-native session timeout (PG: `SET statement_timeout`, MSSQL: query hint, ...)
  은 sql_runner 별 후속 작업으로 분리 — 1차는 asyncio wait_for 단독으로도 워커
  프리징 방지에는 충분 (await 가 cancel 되면 connection 도 close).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from extension_modules.dbsphere.sql_classifier import StmtClass, classify_statement
from extension_modules.dbsphere.sql_runners import create_sql_runner
from extension_modules.dbsphere.sql_runners.base import SqlRunnerBase

from open_webui.env import (
    DBSPHERE_EXECUTE_TIMEOUT_S,
    DBSPHERE_PENDING_EXEC_TTL_S,
    DBSPHERE_RESULT_ROW_CAP,  # 동적 module attr lookup 으로 monkeypatch 호환 — noqa
    SRC_LOG_LEVELS,
)

# `DBSPHERE_RESULT_ROW_CAP` 은 직접 코드 참조 없이 `_data_frame_to_result` 안의
# 동적 module attribute lookup 으로만 사용된다. ruff 가 unused 로 잘못 제거하지
# 않도록 명시적 re-export.
__all__ = [
    "DBSPHERE_RESULT_ROW_CAP",
    "DBSPHERE_EXECUTE_TIMEOUT_S",
    "DBSPHERE_PENDING_EXEC_TTL_S",
    "QueryResult",
    "PendingExec",
    "ExecutorError",
    "QueryTimeoutError",
    "execute_sql_for_user",
    "commit_pending",
    "reject_pending",
    "find_prior_result",
    "find_orphan_pending",
    "mark_orphan_unknown",
]
from open_webui.models.audit_log import (
    AuditAction,
    AuditLogCreateForm,
    AuditLogs,
    AuditResourceType,
)
from open_webui.models.dbsphere import DbSphereModel
from open_webui.utils.dbsphere_approval import (
    discard_pending,
    peek_pending,
    pop_pending,
    set_pending,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", "INFO"))


####################
# Result types
####################


@dataclass
class QueryResult:
    """READ 결과 또는 WRITE commit 결과."""

    result_id: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int  # 응답에 포함된 row 수 (cap 이후)
    total_row_count: int  # 실제 총 row 수 (cap 무시)
    truncated: bool
    exec_ms: int
    op: str  # 'READ' / 'WRITE'
    affected_rows: Optional[int] = None  # WRITE 만. driver 가 못 주면 None
    message: Optional[str] = None  # "0 rows" 같은 비-결과 메시지


@dataclass
class PendingExec:
    """WRITE 분류된 SQL 이 pending 으로 등록된 상태."""

    result_id: str
    op: str  # 'WRITE'
    sql: str
    affected_preview: Optional[int]  # 1차는 None (EXPLAIN 안 함)
    expires_in_s: int


####################
# Exceptions
####################


class ExecutorError(Exception):
    """Generic executor error → router 가 적절한 HTTP status 로 매핑."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code  # 'invalid_sql' / 'forbidden_write' / 'not_supported_db' / ...
        self.message = message
        self.status_code = status_code


class QueryTimeoutError(ExecutorError):
    def __init__(self, timeout_s: int):
        super().__init__(
            "query_timeout",
            f"Query cancelled after {timeout_s}s — increase DBSPHERE_EXECUTE_TIMEOUT_S or simplify the query",
            status_code=408,
        )


####################
# Public API
####################


def _make_runner(dbsphere: DbSphereModel) -> SqlRunnerBase:
    """DbSphere 모델로부터 sql_runner 인스턴스 생성. password 는 decrypt.

    Lazy import — `decrypt_connection_password` 는 `routers/dbsphere.py` 에 정의되어
    있어 module-level 임포트하면 라우터가 본 서비스를 임포트할 때 순환 의존이 된다.
    추후 `utils/dbsphere_credentials.py` 로 추출 권장.
    """
    from extension_modules.dbsphere.dbsphere_state import DBConfig

    from open_webui.routers.dbsphere import decrypt_connection_password

    if not dbsphere.data:
        raise ExecutorError(
            "no_connection",
            "DbSphere is missing connection configuration",
            status_code=400,
        )
    data = decrypt_connection_password(dict(dbsphere.data))
    db_config = DBConfig.from_dbsphere_data(data)
    runner = create_sql_runner(db_config)
    if runner is None:
        raise ExecutorError(
            "not_supported_db",
            f"Unsupported database type: {db_config.db_type}",
            status_code=400,
        )
    return runner


def _data_frame_to_result(
    df, result_id: str, exec_ms: int, op: str, row_cap: Optional[int] = None
) -> QueryResult:
    """pandas DataFrame → QueryResult (JSON serialisable). row cap 적용.

    row_cap=None 이면 module-level `DBSPHERE_RESULT_ROW_CAP` 을 **call time** 에 읽음
    (monkeypatch / 운영 중 config 재로드 가능하도록 — 함수 default arg early-binding 우회).
    """
    if row_cap is None:
        # M3: admin-tunable. 모듈 attribute 동적 조회로 monkeypatch / 운영 재로드 호환.
        from open_webui.services import dbsphere_executor as _self

        row_cap = _self.DBSPHERE_RESULT_ROW_CAP
    total = len(df)
    truncated = total > row_cap
    if truncated:
        df = df.head(row_cap)
    columns = list(df.columns) if total else []
    # `.values.tolist()` 로 nested list. NumPy 스칼라는 Python 원시로 캐스팅.
    rows = [
        [_to_python(v) for v in row] for row in df.itertuples(index=False, name=None)
    ]
    return QueryResult(
        result_id=result_id,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        total_row_count=total,
        truncated=truncated,
        exec_ms=exec_ms,
        op=op,
    )


def _to_python(v: Any) -> Any:
    """NumPy/Decimal/datetime 등 JSON 직렬화 가능한 원시 타입으로 변환."""
    if v is None:
        return None
    # numpy scalar
    if hasattr(v, "item") and not isinstance(v, (str, bytes, dict, list, tuple)):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.hex()
    # datetime / Decimal — str 로 안전 변환
    if hasattr(v, "isoformat"):
        return v.isoformat()
    try:
        # Decimal etc.
        return float(v) if hasattr(v, "__float__") else v
    except Exception:
        return str(v)


async def execute_sql_for_user(
    dbsphere: DbSphereModel,
    sql: str,
    user_id: str,
    is_admin: bool = False,
) -> tuple[Optional[QueryResult], Optional[PendingExec]]:
    """라우터 진입점 — READ 면 (QueryResult, None), WRITE 면 (None, PendingExec) 반환.

    호출 측은 둘 중 채워진 쪽을 응답으로 직렬화.

    예외: ExecutorError (invalid sql / forbidden / not_supported_db / timeout / runner failure).

    `allow_data_modifications` 토글 검사:
    - dbsphere.data["allow_data_modifications"] is True 인 경우만 WRITE 진행
    - admin 도 토글 honor (H2 — admin 이 ACL 은 bypass 하지만 safety toggle 은 honor)
    - UNKNOWN 분류는 보수적: allow=True 면 WRITE 취급, allow=False 면 차단
    """
    cls = classify_statement(sql)
    if cls == StmtClass.INVALID:
        raise ExecutorError("invalid_sql", "Empty or comment-only SQL", status_code=400)
    if cls == StmtClass.UNKNOWN:
        # multi-statement 또는 알 수 없는 첫 키워드. allow=on 이면 WRITE 취급, 아니면 차단.
        allow = bool((dbsphere.data or {}).get("allow_data_modifications", False))
        if not allow:
            raise ExecutorError(
                "unrecognized_or_multi_statement",
                "Cannot classify this statement (or multi-statement). "
                "Enable 'Allow data modifications' to run as WRITE, or split into single statements.",
                status_code=400,
            )
        # Fall through as WRITE.
        cls = StmtClass.WRITE

    if cls == StmtClass.READ:
        result = await _execute_read(dbsphere, sql, user_id)
        return result, None

    # WRITE
    allow = bool((dbsphere.data or {}).get("allow_data_modifications", False))
    if not allow:
        raise ExecutorError(
            "forbidden_write",
            "Data modifications are disabled for this database. "
            "Toggle 'Allow data modifications' in DB Configure to enable.",
            status_code=403,
        )

    pending = _register_pending(dbsphere, sql, user_id)
    return None, pending


async def _execute_read(dbsphere: DbSphereModel, sql: str, user_id: str) -> QueryResult:
    runner = _make_runner(dbsphere)
    result_id = f"r-{uuid.uuid4()}"
    started = time.monotonic()
    try:
        df = await asyncio.wait_for(
            runner.run_sql(sql), timeout=DBSPHERE_EXECUTE_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        await _audit_failure(dbsphere, user_id, sql, "READ", result_id, "timeout")
        raise QueryTimeoutError(DBSPHERE_EXECUTE_TIMEOUT_S)
    except Exception as e:
        log.exception("READ execution failed: %s", e)
        await _audit_failure(dbsphere, user_id, sql, "READ", result_id, str(e)[:500])
        raise ExecutorError(
            "execution_failed", f"SQL execution error: {str(e)[:200]}", status_code=400
        )
    finally:
        await _safe_close(runner)
    exec_ms = int((time.monotonic() - started) * 1000)
    return _data_frame_to_result(df, result_id, exec_ms, "READ")


def _register_pending(dbsphere: DbSphereModel, sql: str, user_id: str) -> PendingExec:
    result_id = f"w-{uuid.uuid4()}"
    payload = {
        "sql": sql,
        "op": "WRITE",
        "user_id": user_id,
        "dbsphere_id": dbsphere.id,
        "created_at": int(time.time()),
    }
    set_pending(result_id, payload, ttl_seconds=DBSPHERE_PENDING_EXEC_TTL_S)
    return PendingExec(
        result_id=result_id,
        op="WRITE",
        sql=sql,
        affected_preview=None,
        expires_in_s=DBSPHERE_PENDING_EXEC_TTL_S,
    )


async def commit_pending(
    dbsphere: DbSphereModel, result_id: str, user_id: str
) -> QueryResult:
    """Confirm path — atomic pop pending → audit PENDING → execute → audit final.

    Raises ExecutorError("gone", ..., 410) when pending 키 없음 (이미 confirm 됐거나
    TTL 만료). 호출 측은 410 을 잡아 audit_log 에서 prior result 를 조회한다 (C2).

    Audit 시퀀스 (B10 production-ready safety):
    1. pop_pending (Redis atomic GETDEL — 단 한 워커만 성공)
    2. ownership/dbsphere 검증
    3. **SQL_PENDING audit row** (evidence: 이 워커가 runner.run_sql 직전까지 도달)
    4. runner.run_sql + asyncio.wait_for timeout
    5. 성공 → SQL_COMMITTED / 실패 → SQL_FAILED

    워커가 (3)~(5) 사이에 죽으면 SQL_PENDING 만 남고 final row 없음 → orphan.
    `find_orphan_pending()` 으로 admin 이 감지 + SQL_UNKNOWN 으로 마킹 가능.
    """
    pending = pop_pending(result_id)
    if pending is None:
        raise ExecutorError(
            "pending_gone",
            "Pending execution not found — already confirmed or expired",
            status_code=410,
        )
    # 소유자 / DbSphere 일치 검증 — 이 검사 전엔 PENDING 작성 X (orphan 노이즈 방지).
    if pending.get("user_id") != user_id:
        raise ExecutorError(
            "forbidden",
            "Pending execution belongs to another user",
            status_code=403,
        )
    if pending.get("dbsphere_id") != dbsphere.id:
        raise ExecutorError(
            "mismatch",
            "Pending execution belongs to a different DbSphere",
            status_code=400,
        )

    sql = pending["sql"]
    op = pending.get("op", "WRITE")

    # 3. SQL_PENDING audit row — runner 실행 직전 evidence. 워커가 여기 후 죽어도
    #    audit 에는 흔적이 남는다 (orphan 으로 감지).
    _audit_pending(dbsphere, user_id, sql, op, result_id)

    runner = _make_runner(dbsphere)
    started = time.monotonic()
    try:
        df = await asyncio.wait_for(
            runner.run_sql(sql), timeout=DBSPHERE_EXECUTE_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        await _audit_failure(dbsphere, user_id, sql, op, result_id, "timeout")
        raise QueryTimeoutError(DBSPHERE_EXECUTE_TIMEOUT_S)
    except Exception as e:
        log.exception("WRITE commit failed: %s", e)
        await _audit_failure(dbsphere, user_id, sql, op, result_id, str(e)[:500])
        raise ExecutorError(
            "execution_failed", f"SQL execution error: {str(e)[:200]}", status_code=400
        )
    finally:
        await _safe_close(runner)

    exec_ms = int((time.monotonic() - started) * 1000)
    if df is None:
        # Some drivers return None for DML when affected_rows is unavailable.
        # Build an empty result so the response model stays consistent.
        affected = None
        result = QueryResult(
            result_id=result_id,
            columns=[],
            rows=[],
            row_count=0,
            total_row_count=0,
            truncated=False,
            exec_ms=exec_ms,
            op=op,
        )
    else:
        affected = len(df)
        result = _data_frame_to_result(df, result_id, exec_ms, op)
    result.affected_rows = affected
    if df is None or len(df) == 0:
        result.message = (
            "Statement executed successfully. "
            "(Driver did not return affected row count; verify with a SELECT.)"
        )

    _audit_success(dbsphere, user_id, sql, op, result_id, exec_ms, affected)
    return result


def reject_pending(dbsphere: DbSphereModel, result_id: str, user_id: str) -> None:
    """Reject path — peek + ownership check + discard + audit."""
    pending = peek_pending(result_id)
    if pending is None:
        raise ExecutorError(
            "pending_gone",
            "Pending execution not found — already resolved or expired",
            status_code=410,
        )
    if pending.get("user_id") != user_id:
        raise ExecutorError(
            "forbidden",
            "Pending execution belongs to another user",
            status_code=403,
        )
    if pending.get("dbsphere_id") != dbsphere.id:
        raise ExecutorError(
            "mismatch",
            "Pending execution belongs to a different DbSphere",
            status_code=400,
        )
    discard_pending(result_id)
    _audit_reject(
        dbsphere, user_id, pending["sql"], pending.get("op", "WRITE"), result_id
    )


####################
# Audit helpers
####################


def _audit_meta(sql: str, op: str, result_id: str, **extra) -> dict:
    """audit_log.meta JSON. SQL 본문 첫 2000자 + op + result_id + 확장."""
    base = {
        "result_id": result_id,
        "op": op,
        "sql_preview": sql[:2000],
        "sql_truncated": len(sql) > 2000,
    }
    base.update(extra)
    return base


def _insert_audit(
    dbsphere: DbSphereModel,
    user_id: str,
    action: str,
    meta: dict,
) -> None:
    try:
        form = AuditLogCreateForm(
            user_id=user_id,
            resource_type=AuditResourceType.DBSPHERE.value,
            resource_id=dbsphere.id,
            resource_name=dbsphere.name,
            action=action,
            meta=meta,
        )
        AuditLogs.insert_audit_log(form)
    except Exception as e:
        # audit 실패는 호출 흐름을 끊지 않음 — log 만 남김.
        log.error("audit_log insert failed: %s", e)


def _audit_pending(
    dbsphere: DbSphereModel,
    user_id: str,
    sql: str,
    op: str,
    result_id: str,
) -> None:
    """B10: runner 실행 직전 evidence row. 워커가 여기 후 죽으면 orphan 으로 감지."""
    _insert_audit(
        dbsphere,
        user_id,
        AuditAction.SQL_PENDING.value,
        _audit_meta(sql, op, result_id),
    )


def _audit_success(
    dbsphere: DbSphereModel,
    user_id: str,
    sql: str,
    op: str,
    result_id: str,
    exec_ms: int,
    affected: Optional[int],
) -> None:
    _insert_audit(
        dbsphere,
        user_id,
        AuditAction.SQL_COMMITTED.value,
        _audit_meta(sql, op, result_id, exec_ms=exec_ms, affected_rows=affected),
    )


def _audit_reject(
    dbsphere: DbSphereModel,
    user_id: str,
    sql: str,
    op: str,
    result_id: str,
) -> None:
    _insert_audit(
        dbsphere,
        user_id,
        AuditAction.SQL_REJECTED.value,
        _audit_meta(sql, op, result_id),
    )


async def _audit_failure(
    dbsphere: DbSphereModel,
    user_id: str,
    sql: str,
    op: str,
    result_id: str,
    error_message: str,
) -> None:
    _insert_audit(
        dbsphere,
        user_id,
        AuditAction.SQL_FAILED.value,
        _audit_meta(sql, op, result_id, error=error_message),
    )


async def _safe_close(runner: SqlRunnerBase) -> None:
    """sql_runner 가 close 메서드를 가지면 호출. 없는 dialect 도 있음 (BigQuery 등)."""
    close = getattr(runner, "close", None)
    if close is None:
        return
    try:
        if asyncio.iscoroutinefunction(close):
            await close()
        else:
            close()
    except Exception as e:
        log.warning("sql_runner close failed: %s", e)


####################
# Audit lookup (for C2: confirm 410 → prior result 200)
####################


def find_orphan_pending(older_than_seconds: int = 60, limit: int = 200) -> list[dict]:
    """B10: SQL_PENDING audit rows whose `result_id` has no matching SQL_COMMITTED /
    SQL_FAILED / SQL_REJECTED / SQL_UNKNOWN row.

    워커가 SQL_PENDING 작성 후 final row 작성 전에 죽으면 orphan. admin 이 호출해서
    audit 갭을 가시화한다.

    Returns list of {result_id, dbsphere_id, user_id, sql_preview, op, created_at, age_s}.
    """
    try:
        from open_webui.internal.db import get_db
        from open_webui.models.audit_log import AuditLog

        cutoff = int(time.time()) - max(0, older_than_seconds)
        final_actions = {
            AuditAction.SQL_COMMITTED.value,
            AuditAction.SQL_FAILED.value,
            AuditAction.SQL_REJECTED.value,
            AuditAction.SQL_UNKNOWN.value,
        }
        with get_db() as db:
            # 시간 cutoff 적용해 PENDING row 후보를 좁힌 뒤, result_id 매칭 final 존재
            # 여부를 메모리에서 set 차집합으로 처리 (SQL 측 NOT EXISTS 는 dialect 차이로 회피).
            pending_rows = (
                db.query(AuditLog)
                .filter(
                    AuditLog.resource_type == AuditResourceType.DBSPHERE.value,
                    AuditLog.action == AuditAction.SQL_PENDING.value,
                    AuditLog.created_at <= cutoff,
                )
                .order_by(AuditLog.created_at.desc())
                .limit(limit * 4)  # final 있는 것 제외 후 limit 만족하도록 여유.
                .all()
            )
            if not pending_rows:
                return []

            # 후보 PENDING 의 result_id 만 모아 최근 final row 들 일괄 조회.
            candidate_rids = {
                (r.meta or {}).get("result_id")
                for r in pending_rows
                if (r.meta or {}).get("result_id")
            }
            if not candidate_rids:
                return []

            final_rows = (
                db.query(AuditLog)
                .filter(
                    AuditLog.resource_type == AuditResourceType.DBSPHERE.value,
                    AuditLog.action.in_(final_actions),
                )
                .all()
            )
            resolved_rids = {
                (r.meta or {}).get("result_id")
                for r in final_rows
                if (r.meta or {}).get("result_id") in candidate_rids
            }

            now = int(time.time())
            orphans: list[dict] = []
            for r in pending_rows:
                rid = (r.meta or {}).get("result_id")
                if not rid or rid in resolved_rids:
                    continue
                orphans.append(
                    {
                        "result_id": rid,
                        "dbsphere_id": r.resource_id,
                        "user_id": r.user_id,
                        "sql_preview": (r.meta or {}).get("sql_preview", ""),
                        "op": (r.meta or {}).get("op", "WRITE"),
                        "created_at": r.created_at,
                        "age_s": now - r.created_at,
                    }
                )
                if len(orphans) >= limit:
                    break
            return orphans
    except Exception as e:
        log.error("find_orphan_pending failed: %s", e)
        return []


def mark_orphan_unknown(
    dbsphere_id: str, user_id: str, result_id: str, reason: str = "orphan"
) -> bool:
    """Admin 이 orphan SQL_PENDING 을 SQL_UNKNOWN 으로 명시 마킹 (audit 갭 해소).

    SQL_UNKNOWN append-only — 원래 SQL_PENDING row 는 그대로 보존 (감사 기록 무손실).
    """
    try:
        from open_webui.models.audit_log import (
            AuditLogCreateForm,
            AuditLogs,
        )

        form = AuditLogCreateForm(
            user_id=user_id,
            resource_type=AuditResourceType.DBSPHERE.value,
            resource_id=dbsphere_id,
            action=AuditAction.SQL_UNKNOWN.value,
            meta={
                "result_id": result_id,
                "reason": reason,
                "reconciled_at": int(time.time()),
            },
        )
        AuditLogs.insert_audit_log(form)
        return True
    except Exception as e:
        log.error("mark_orphan_unknown failed: %s", e)
        return False


def find_prior_result(dbsphere_id: str, user_id: str, result_id: str) -> Optional[dict]:
    """audit_log 에서 (dbsphere_id, user_id, result_id) 매칭 SQL_COMMITTED row 1개 조회.

    라우터의 confirm 가 410 (pending gone) 받았을 때 호출 — 이미 confirm 된 경우라면
    audit_log 에 row 가 있으므로 prior result preview 를 반환할 수 있다.

    완전한 result rows 는 audit 에 저장하지 않음 (페이로드 비대화 방지) — 사용자는
    `affected_rows` / `exec_ms` 등 메타 정보를 받아 "이미 실행됨" 확인이 가능하다.
    """
    try:
        with __import__("open_webui.internal.db", fromlist=["get_db"]).get_db() as db:
            from open_webui.models.audit_log import AuditLog

            row = (
                db.query(AuditLog)
                .filter(
                    AuditLog.resource_type == AuditResourceType.DBSPHERE.value,
                    AuditLog.resource_id == dbsphere_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action.in_(
                        [
                            AuditAction.SQL_COMMITTED.value,
                            AuditAction.SQL_REJECTED.value,
                        ]
                    ),
                )
                .order_by(AuditLog.created_at.desc())
                .all()
            )
            for r in row:
                meta = r.meta or {}
                if meta.get("result_id") == result_id:
                    return {
                        "action": r.action,
                        "result_id": result_id,
                        "affected_rows": meta.get("affected_rows"),
                        "exec_ms": meta.get("exec_ms"),
                        "executed_at": r.created_at,
                    }
            return None
    except Exception as e:
        log.error("find_prior_result failed: %s", e)
        return None
