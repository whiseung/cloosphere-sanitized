"""Unit tests for services/dbsphere_executor.py.

검사 영역:
- classifier × allow_data_modifications 토글 매트릭스 (Q6 + H2)
- READ 즉시 실행 + row cap + 타입 변환
- WRITE → pending 등록 (Redis)
- commit_pending → atomic GETDEL → audit_log SQL_COMMITTED
- commit_pending 이미 pop → 410 (라우터 차원 prior result lookup 대응 — C2)
- ownership / dbsphere mismatch
- reject_pending → discard + audit_log SQL_REJECTED
- Query timeout (asyncio.wait_for cancel — C3)

전략:
- sql_runner 는 FakeRunner 로 치환 (DataFrame canned 결과 / 인위적 sleep 가능)
- Redis 는 실제 사용 (multi-worker 안전 검증을 unit 에서도 그대로 — fakeredis 의존
  추가 회피)
- audit_log 는 monkeypatch 로 in-memory 리스트로 캡쳐
- DbSphereModel 은 직접 Pydantic 생성 (DB 불요)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pandas as pd
import pytest
from open_webui.models.audit_log import AuditAction
from open_webui.models.dbsphere import DbSphereModel

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class FakeRunner:
    """sql_runner 표준 인터페이스 흉내 — run_sql + close."""

    def __init__(
        self,
        rows: list[dict] | None = None,
        raise_exc: Exception | None = None,
        delay_s: float = 0.0,
        return_none: bool = False,
    ):
        self._rows = rows or []
        self._raise = raise_exc
        self._delay = delay_s
        # Some DB drivers return None from DML when affected_rows isn't
        # available. `return_none=True` reproduces that contract so the
        # executor's df=None branch can be exercised.
        self._return_none = return_none
        self.executed_sql: list[str] = []
        self.closed = False

    async def run_sql(self, sql: str) -> pd.DataFrame | None:
        self.executed_sql.append(sql)
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._raise:
            raise self._raise
        if self._return_none:
            return None
        return pd.DataFrame(self._rows)

    async def close(self):
        self.closed = True


def _make_dbsphere(
    allow_data_modifications: bool = False,
    name: str = "TestDB",
    id_: str | None = None,
) -> DbSphereModel:
    now = int(time.time())
    return DbSphereModel(
        id=id_ or f"db-{uuid.uuid4()}",
        user_id="u-owner",
        name=name,
        description="",
        data={
            "connection": {
                "db_type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "username": "u",
                "password": "p",
            },
            "allow_data_modifications": allow_data_modifications,
        },
        meta=None,
        access_control=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def capture_audit(monkeypatch):
    """audit_log INSERT 를 in-memory 리스트로 캡쳐. 라우터/DB 없이 검증 가능."""
    captured: list[dict] = []

    def fake_insert(form):
        captured.append(
            {
                "action": form.action,
                "resource_type": form.resource_type,
                "resource_id": form.resource_id,
                "user_id": form.user_id,
                "meta": form.meta,
            }
        )
        return None

    from open_webui.models import audit_log as audit_module

    monkeypatch.setattr(audit_module.AuditLogs, "insert_audit_log", fake_insert)
    # services 모듈이 직접 import 한 동일 객체에도 동일하게 적용 (참조 동일).
    return captured


@pytest.fixture
def patch_runner(monkeypatch):
    """services/dbsphere_executor.py 의 `_make_runner` 가 FakeRunner 를 반환하도록."""
    holder: dict[str, Any] = {"runner": None}

    def _install(runner: FakeRunner):
        from open_webui.services import dbsphere_executor

        holder["runner"] = runner
        monkeypatch.setattr(dbsphere_executor, "_make_runner", lambda _ds: runner)

    return _install


# ---------------------------------------------------------------------------
# READ path
# ---------------------------------------------------------------------------


class TestExecuteRead:
    async def test_read_success_returns_result(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import execute_sql_for_user

        runner = FakeRunner(rows=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        patch_runner(runner)
        ds = _make_dbsphere()

        result, pending = await execute_sql_for_user(ds, "SELECT * FROM t", "u-owner")

        assert pending is None
        assert result is not None
        assert result.op == "READ"
        assert result.columns == ["id", "name"]
        assert result.rows == [[1, "a"], [2, "b"]]
        assert result.row_count == 2
        assert result.total_row_count == 2
        assert result.truncated is False
        assert runner.executed_sql == ["SELECT * FROM t"]
        # READ 는 audit 안 함 — pending/commit/reject 시점에만 audit.
        assert capture_audit == []

    async def test_read_row_cap_truncates(
        self, patch_runner, capture_audit, monkeypatch
    ):
        from open_webui.services import dbsphere_executor
        from open_webui.services.dbsphere_executor import execute_sql_for_user

        # cap 을 2 로 강제.
        monkeypatch.setattr(dbsphere_executor, "DBSPHERE_RESULT_ROW_CAP", 2)
        runner = FakeRunner(rows=[{"x": i} for i in range(5)])
        patch_runner(runner)

        result, _ = await execute_sql_for_user(
            _make_dbsphere(), "SELECT x FROM t", "u-owner"
        )
        assert result.row_count == 2
        assert result.total_row_count == 5
        assert result.truncated is True

    async def test_invalid_sql_raises(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner())
        with pytest.raises(ExecutorError) as exc_info:
            await execute_sql_for_user(
                _make_dbsphere(), "   -- only comment", "u-owner"
            )
        assert exc_info.value.code == "invalid_sql"
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# WRITE path — allow toggle matrix
# ---------------------------------------------------------------------------


class TestExecuteWriteAllowToggle:
    async def test_write_blocked_when_allow_off(self, patch_runner, capture_audit):
        """H2: admin 도 토글 honor (테스트는 owner 시나리오로 동일 검증)."""
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=False)
        with pytest.raises(ExecutorError) as exc_info:
            await execute_sql_for_user(ds, "DELETE FROM t WHERE id=1", "u-owner")
        assert exc_info.value.code == "forbidden_write"
        assert exc_info.value.status_code == 403

    async def test_write_returns_pending_when_allow_on(
        self, patch_runner, capture_audit
    ):
        from open_webui.services.dbsphere_executor import execute_sql_for_user

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        result, pending = await execute_sql_for_user(
            ds, "DELETE FROM t WHERE id=1", "u-owner"
        )
        assert result is None
        assert pending is not None
        assert pending.op == "WRITE"
        assert pending.result_id.startswith("w-")
        assert pending.sql == "DELETE FROM t WHERE id=1"
        # 실제 실행은 아직 안 됨 — pending 등록만.
        # FakeRunner 가 호출되지 않아야 함 (commit 전).
        from open_webui.services.dbsphere_executor import _make_runner  # noqa: F401

    async def test_unknown_blocked_when_allow_off(self, patch_runner, capture_audit):
        """UNKNOWN 분류 + allow=off → 차단."""
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=False)
        with pytest.raises(ExecutorError) as exc_info:
            await execute_sql_for_user(ds, "PRAGMA foreign_keys = ON", "u-owner")
        assert exc_info.value.code == "unrecognized_or_multi_statement"
        assert exc_info.value.status_code == 400

    async def test_unknown_treated_as_write_when_allow_on(
        self, patch_runner, capture_audit
    ):
        """UNKNOWN + allow=on → WRITE 취급 → pending."""
        from open_webui.services.dbsphere_executor import execute_sql_for_user

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(
            ds, "PRAGMA foreign_keys = ON", "u-owner"
        )
        assert pending is not None and pending.op == "WRITE"


# ---------------------------------------------------------------------------
# Commit / reject pending
# ---------------------------------------------------------------------------


class TestCommitPending:
    async def test_commit_executes_and_audits(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import (
            commit_pending,
            execute_sql_for_user,
        )

        # 첫 phase: pending 등록.
        runner = FakeRunner(rows=[])  # DML 은 빈 DataFrame
        patch_runner(runner)
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(
            ds, "DELETE FROM t WHERE id=1", "u-owner"
        )
        assert pending is not None

        # 둘째 phase: commit.
        result = await commit_pending(ds, pending.result_id, "u-owner")
        assert result.op == "WRITE"
        assert result.result_id == pending.result_id
        # FakeRunner 가 호출됐는지.
        assert runner.executed_sql == ["DELETE FROM t WHERE id=1"]
        assert runner.closed is True
        # B10: audit 2 rows — SQL_PENDING (runner 실행 직전 evidence) → SQL_COMMITTED.
        assert len(capture_audit) == 2
        actions = [ar["action"] for ar in capture_audit]
        assert actions == [
            AuditAction.SQL_PENDING.value,
            AuditAction.SQL_COMMITTED.value,
        ]
        # 둘 다 같은 result_id / sql_preview / op 공유.
        for ar in capture_audit:
            assert ar["resource_id"] == ds.id
            assert ar["user_id"] == "u-owner"
            assert ar["meta"]["op"] == "WRITE"
            assert ar["meta"]["result_id"] == pending.result_id
            assert ar["meta"]["sql_preview"] == "DELETE FROM t WHERE id=1"
        # final row 에만 exec_ms / affected_rows.
        assert "exec_ms" in capture_audit[1]["meta"]
        assert "affected_rows" in capture_audit[1]["meta"]

    async def test_commit_gone_raises_410(self, patch_runner, capture_audit):
        """이미 confirm 됐거나 TTL 만료 → 410."""
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            commit_pending,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        # 등록 안 된 random id.
        with pytest.raises(ExecutorError) as exc_info:
            await commit_pending(ds, f"w-{uuid.uuid4()}", "u-owner")
        assert exc_info.value.code == "pending_gone"
        assert exc_info.value.status_code == 410

    async def test_commit_double_pop_second_returns_410(
        self, patch_runner, capture_audit
    ):
        """C2 — 첫 commit 성공, 둘째 commit 시점에 Redis 키 없음 → 410."""
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            commit_pending,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner(rows=[]))
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "UPDATE t SET x=1", "u-owner")
        # 첫 commit OK.
        await commit_pending(ds, pending.result_id, "u-owner")
        # 둘째 commit — 410.
        with pytest.raises(ExecutorError) as exc_info:
            await commit_pending(ds, pending.result_id, "u-owner")
        assert exc_info.value.code == "pending_gone"

    async def test_commit_ownership_mismatch_raises_403(
        self, patch_runner, capture_audit
    ):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            commit_pending,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "DELETE FROM t", "u-owner")
        with pytest.raises(ExecutorError) as exc_info:
            await commit_pending(ds, pending.result_id, "u-other")
        assert exc_info.value.code == "forbidden"
        assert exc_info.value.status_code == 403

    async def test_commit_dbsphere_mismatch_raises_400(
        self, patch_runner, capture_audit
    ):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            commit_pending,
            execute_sql_for_user,
        )

        patch_runner(FakeRunner())
        ds_a = _make_dbsphere(allow_data_modifications=True, id_="db-a")
        ds_b = _make_dbsphere(allow_data_modifications=True, id_="db-b")
        _, pending = await execute_sql_for_user(ds_a, "DELETE FROM t", "u-owner")
        with pytest.raises(ExecutorError) as exc_info:
            await commit_pending(ds_b, pending.result_id, "u-owner")
        assert exc_info.value.code == "mismatch"

    async def test_commit_failure_audits_sql_failed(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            commit_pending,
            execute_sql_for_user,
        )

        runner = FakeRunner(raise_exc=RuntimeError("connection lost"))
        patch_runner(runner)
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "DELETE FROM t", "u-owner")
        with pytest.raises(ExecutorError) as exc_info:
            await commit_pending(ds, pending.result_id, "u-owner")
        assert exc_info.value.code == "execution_failed"
        # B10: audit 2 rows — SQL_PENDING → SQL_FAILED.
        assert len(capture_audit) == 2
        actions = [ar["action"] for ar in capture_audit]
        assert actions == [AuditAction.SQL_PENDING.value, AuditAction.SQL_FAILED.value]
        assert "connection lost" in capture_audit[1]["meta"]["error"]

    async def test_commit_with_none_df_returns_empty_result(
        self, patch_runner, capture_audit
    ):
        """Drivers that return None from DML (no affected_rows) must not crash
        — regression guard for the df=None branch in commit_pending."""
        from open_webui.services.dbsphere_executor import (
            commit_pending,
            execute_sql_for_user,
        )

        runner = FakeRunner(return_none=True)
        patch_runner(runner)
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "DELETE FROM t", "u-owner")
        result = await commit_pending(ds, pending.result_id, "u-owner")
        assert result.op == "WRITE"
        assert result.columns == []
        assert result.rows == []
        assert result.row_count == 0
        assert result.affected_rows is None
        assert result.message is not None
        # SQL_PENDING + SQL_COMMITTED still recorded.
        assert len(capture_audit) == 2


class TestRejectPending:
    async def test_reject_discards_and_audits(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            execute_sql_for_user,
            reject_pending,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "DELETE FROM t", "u-owner")
        reject_pending(ds, pending.result_id, "u-owner")
        # audit row — SQL_REJECTED.
        assert len(capture_audit) == 1
        assert capture_audit[0]["action"] == AuditAction.SQL_REJECTED.value
        # 두 번 reject → 410 (이미 discard 됐음).
        with pytest.raises(ExecutorError) as exc_info:
            reject_pending(ds, pending.result_id, "u-owner")
        assert exc_info.value.code == "pending_gone"

    async def test_reject_ownership_mismatch(self, patch_runner, capture_audit):
        from open_webui.services.dbsphere_executor import (
            ExecutorError,
            execute_sql_for_user,
            reject_pending,
        )

        patch_runner(FakeRunner())
        ds = _make_dbsphere(allow_data_modifications=True)
        _, pending = await execute_sql_for_user(ds, "DELETE FROM t", "u-owner")
        with pytest.raises(ExecutorError) as exc_info:
            reject_pending(ds, pending.result_id, "u-other")
        assert exc_info.value.code == "forbidden"


# ---------------------------------------------------------------------------
# Timeout (C3)
# ---------------------------------------------------------------------------


class TestQueryTimeout:
    async def test_read_timeout_raises_408(
        self, patch_runner, capture_audit, monkeypatch
    ):
        from open_webui.services.dbsphere_executor import (
            QueryTimeoutError,
            execute_sql_for_user,
        )

        # FakeRunner 가 2초 sleep — asyncio.wait_for(timeout=0.1) 가 cancel 한다.
        runner = FakeRunner(rows=[{"x": 1}], delay_s=2.0)
        patch_runner(runner)  # _make_runner → FakeRunner 치환 강제.

        # 모듈 내부 asyncio.wait_for 를 더 짧은 timeout 으로 강제 (config 값 1 미만 불가).
        original_wait_for = asyncio.wait_for

        async def fast_wait_for(coro, timeout):
            return await original_wait_for(coro, timeout=0.1)

        monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)

        with pytest.raises(QueryTimeoutError) as exc_info:
            await execute_sql_for_user(_make_dbsphere(), "SELECT 1", "u-owner")
        assert exc_info.value.code == "query_timeout"
        assert exc_info.value.status_code == 408
        # READ timeout 도 audit (SQL_FAILED with op=READ).
        assert len(capture_audit) == 1
        assert capture_audit[0]["action"] == AuditAction.SQL_FAILED.value
        assert capture_audit[0]["meta"]["op"] == "READ"
        assert capture_audit[0]["meta"]["error"] == "timeout"


# ---------------------------------------------------------------------------
# find_prior_result (C2 router helper) — DB 의존이라 별 test 로
# ---------------------------------------------------------------------------


class TestOrphanPending:
    """B10: SQL_PENDING audit row with no final → orphan, find/mark."""

    def _insert_audit(
        self,
        action: str,
        result_id: str,
        dbsphere_id: str,
        user_id: str,
        created_at: int,
    ):
        """헬퍼: audit_log row 직접 ORM 작성. created_at 을 임의로 강제하기 위해
        AuditLogs.insert_audit_log (내부에서 time.time() 으로 덮어씀) 우회."""
        from open_webui.internal.db import get_db
        from open_webui.models.audit_log import AuditLog, AuditResourceType

        with get_db() as db:
            row = AuditLog(
                id=str(uuid.uuid4()),
                user_id=user_id,
                resource_type=AuditResourceType.DBSPHERE.value,
                resource_id=dbsphere_id,
                action=action,
                meta={
                    "result_id": result_id,
                    "op": "WRITE",
                    "sql_preview": "DELETE FROM t",
                },
                created_at=created_at,
            )
            db.add(row)
            db.commit()

    def test_find_orphan_with_pending_only(self):
        """PENDING row 만 있고 final 없으면 orphan 으로 반환."""
        from open_webui.services.dbsphere_executor import find_orphan_pending

        # 충분히 오래된 PENDING 작성.
        past = int(time.time()) - 120
        self._insert_audit("SQL_PENDING", "rid-orphan-1", "db-x", "u-1", past)

        orphans = find_orphan_pending(older_than_seconds=60)
        rids = [o["result_id"] for o in orphans]
        assert "rid-orphan-1" in rids

    def test_pending_with_matching_committed_is_not_orphan(self):
        from open_webui.services.dbsphere_executor import find_orphan_pending

        past = int(time.time()) - 120
        self._insert_audit("SQL_PENDING", "rid-resolved-1", "db-x", "u-1", past)
        self._insert_audit("SQL_COMMITTED", "rid-resolved-1", "db-x", "u-1", past + 1)

        orphans = find_orphan_pending(older_than_seconds=60)
        rids = [o["result_id"] for o in orphans]
        assert "rid-resolved-1" not in rids

    def test_recent_pending_below_threshold_not_returned(self):
        """threshold 보다 최근 PENDING 은 아직 진행 중일 수 있으므로 orphan 아님."""
        from open_webui.services.dbsphere_executor import find_orphan_pending

        now = int(time.time())
        self._insert_audit("SQL_PENDING", "rid-recent", "db-x", "u-1", now)

        orphans = find_orphan_pending(older_than_seconds=60)
        rids = [o["result_id"] for o in orphans]
        assert "rid-recent" not in rids

    def test_mark_orphan_unknown_appends_row(self):
        """mark_orphan_unknown 은 SQL_UNKNOWN append. 원본 PENDING 은 보존."""
        from open_webui.models.audit_log import AuditAction
        from open_webui.services.dbsphere_executor import (
            find_orphan_pending,
            mark_orphan_unknown,
        )

        past = int(time.time()) - 120
        self._insert_audit("SQL_PENDING", "rid-mark", "db-x", "u-1", past)
        assert "rid-mark" in [
            o["result_id"] for o in find_orphan_pending(older_than_seconds=60)
        ]

        ok = mark_orphan_unknown(
            "db-x", "u-admin", "rid-mark", reason="manual reconcile"
        )
        assert ok is True
        # 마킹 후 더이상 orphan 아님 (SQL_UNKNOWN 이 final 로 인정됨).
        assert "rid-mark" not in [
            o["result_id"] for o in find_orphan_pending(older_than_seconds=60)
        ]

        # SQL_UNKNOWN row 가 audit_log 에 존재해야 함.
        from open_webui.internal.db import get_db
        from open_webui.models.audit_log import AuditLog

        with get_db() as db:
            unknown_rows = (
                db.query(AuditLog)
                .filter(
                    AuditLog.action == AuditAction.SQL_UNKNOWN.value,
                )
                .all()
            )
            matching = [
                r for r in unknown_rows if (r.meta or {}).get("result_id") == "rid-mark"
            ]
            assert len(matching) == 1
            assert matching[0].meta["reason"] == "manual reconcile"


class TestFindPriorResult:
    def test_returns_none_when_no_audit_row(self, monkeypatch):
        """find_prior_result 는 audit_log row 없으면 None."""
        from open_webui.services import dbsphere_executor

        class _Session:
            def query(self, *_a, **_k):
                return self

            def filter(self, *_a, **_k):
                return self

            def order_by(self, *_a, **_k):
                return self

            def all(self):
                return []

        class _DB:
            def __enter__(self):
                return _Session()

            def __exit__(self, *args):
                return False

        import open_webui.internal.db as db_module

        monkeypatch.setattr(db_module, "get_db", lambda: _DB())
        # services 가 import 시점에 db 캐싱하지 않도록 — find_prior_result 는 함수 내부에서
        # `__import__("open_webui.internal.db", fromlist=["get_db"]).get_db()` 호출.
        result = dbsphere_executor.find_prior_result("db-1", "u-1", "rid-1")
        assert result is None
