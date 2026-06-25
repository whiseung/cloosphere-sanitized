"""KMS Phase 4.2 — tamper-evident audit log tests.

These tests cover the hash-chain semantics in
``backend/open_webui/models/kms_audit_log.py``:

  * Genesis anchor (first row chains from "0" * 64).
  * Each row's ``row_hash`` is SHA-256 of canonical(payload + prev_hash).
  * Tampering with any column on any row is detected by ``verify_chain``.
  * Reentrancy guard: a nested ``insert`` (e.g. from a SQLAlchemy listener
    triggered by audit-table writes) is dropped, never deadlocks.
  * Sub-range verification anchors on the row immediately before
    ``from_id`` so partial walks still detect tampering.
  * The audit shim's ``record_op`` swallows DB errors but never breaks
    the data path.

The DB session uses the same configuration as the application — these
tests run against the dev Postgres so they exercise BigInteger
auto-increment + index behavior. Each test cleans up its own rows via
the ``_test/...`` ``config_path`` prefix.
"""

import os

# Ensure WEBUI_SECRET_KEY is set before any open_webui imports — env reads it
# at import time.
os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-audit")

import pytest
from sqlalchemy import text

from open_webui.internal.db import get_db
from open_webui.models.kms_audit_log import (
    GENESIS_HASH,
    KmsAuditLog,
    KmsAuditLogs,
    KmsAuditOperation,
    _in_audit_write,
    compute_row_hash,
    reset_request_context,
    set_request_context,
)

_TEST_PREFIX = "_test/audit/"


def _cleanup_test_rows():
    """Wipe any rows authored by these tests so the chain stays clean for
    other tests that walk the full table. We can't reuse the production
    chain across tests because each test asserts specific hashes."""
    with get_db() as db:
        db.execute(
            text("DELETE FROM kms_audit_log WHERE config_path LIKE :p"),
            {"p": f"{_TEST_PREFIX}%"},
        )
        db.commit()


@pytest.fixture(autouse=True)
def _isolate_test_rows():
    _cleanup_test_rows()
    yield
    _cleanup_test_rows()


def test_genesis_chain_anchor():
    """The first row in an empty table chains from GENESIS_HASH."""
    # Pre-condition: there may be other (production) rows. We only assert
    # behavior for our test rows — fetch the latest before insert and
    # then compare our row's prev_hash to it.
    with get_db() as db:
        last_before = (
            db.query(KmsAuditLog.row_hash).order_by(KmsAuditLog.id.desc()).first()
        )
    expected_prev = last_before.row_hash if last_before else GENESIS_HASH

    row = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}genesis",
    )
    assert row is not None
    assert row.prev_hash == expected_prev
    # row_hash is recomputable from canonical payload + prev_hash.
    payload = {
        "timestamp_ms": row.timestamp_ms,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "org_id": row.org_id,
        "operation": row.operation,
        "config_path": row.config_path,
        "kek_uri": row.kek_uri,
        "kek_version": row.kek_version,
        "classification": row.classification,
        "success": row.success,
        "error_code": row.error_code,
        "request_id": row.request_id,
        "client_ip": row.client_ip,
    }
    assert row.row_hash == compute_row_hash(payload, row.prev_hash)


def test_chain_links_consecutive_rows():
    """Each new row's prev_hash equals the previous row's row_hash."""
    r1 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}link1",
    )
    r2 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}link2",
    )
    r3 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=False,
        config_path=f"{_TEST_PREFIX}link1",
        error_code="GCM_TAG_FAIL",
    )
    assert r2.prev_hash == r1.row_hash
    assert r3.prev_hash == r2.row_hash
    assert r1.id < r2.id < r3.id


def test_verify_passes_on_clean_chain():
    """verify_chain over our test rows reports ok=True."""
    r1 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}clean1",
    )
    r2 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}clean2",
    )
    result = KmsAuditLogs.verify_chain(from_id=r1.id, to_id=r2.id)
    assert result["ok"] is True
    assert result["checked"] == 2
    assert result["first_break_id"] is None


def test_verify_detects_tampered_payload():
    """Mutating a column outside the logger breaks row_hash recompute."""
    r1 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}tamper-me",
    )
    r2 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}downstream",
    )
    # Tamper r1.config_path WITHOUT updating row_hash.
    with get_db() as db:
        row = db.query(KmsAuditLog).filter_by(id=r1.id).first()
        row.config_path = f"{_TEST_PREFIX}TAMPERED"
        db.commit()

    result = KmsAuditLogs.verify_chain(from_id=r1.id, to_id=r2.id)
    assert result["ok"] is False
    assert result["first_break_id"] == r1.id
    assert "row_hash" in (result["first_break_reason"] or "")


def test_verify_detects_broken_prev_hash_link():
    """Mutating r2.prev_hash to point at the wrong row breaks the link."""
    r1 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}link-a",
    )
    r2 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}link-b",
    )
    # Replace r2.prev_hash with garbage. Don't recompute row_hash —
    # because row_hash includes prev_hash, that's already inconsistent;
    # what we want to assert is the prev_hash mismatch is detected.
    with get_db() as db:
        row = db.query(KmsAuditLog).filter_by(id=r2.id).first()
        row.prev_hash = "f" * 64
        db.commit()

    result = KmsAuditLogs.verify_chain(from_id=r1.id, to_id=r2.id)
    assert result["ok"] is False
    # The first row of the sub-range (r1) is still anchored OK, but r2's
    # prev_hash no longer matches r1.row_hash.
    assert result["first_break_id"] == r2.id
    assert "prev_hash" in (result["first_break_reason"] or "")


def test_subrange_verify_anchors_on_prior_row():
    """Sub-range walk picks up the row before from_id as the anchor —
    a clean sub-range that follows untouched history must verify True."""
    r1 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}anchor-a",
    )
    r2 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}anchor-b",
    )
    r3 = KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=False,
        config_path=f"{_TEST_PREFIX}anchor-c",
        error_code="GCM_TAG_FAIL",
    )
    # Verify only [r2, r3] — the verifier must look up r1 to anchor.
    result = KmsAuditLogs.verify_chain(from_id=r2.id, to_id=r3.id)
    assert result["ok"] is True
    assert result["checked"] == 2


def test_reentrancy_guard_drops_nested_insert():
    """If insert() is called while another insert() is already running on
    the same task, the inner call returns None instead of recursing.

    Simulated here by setting the ContextVar manually — production hits
    this when SQLAlchemy listeners fire on the audit insert itself."""
    token = _in_audit_write.set(True)
    try:
        nested = KmsAuditLogs.insert(
            operation=KmsAuditOperation.WRAP.value,
            success=True,
            config_path=f"{_TEST_PREFIX}reentrant",
        )
        assert nested is None
    finally:
        _in_audit_write.reset(token)


def test_request_context_propagates_to_row():
    """set_request_context fills in actor_id / client_ip on subsequent
    rows. We use the canonical context API rather than the middleware
    to keep the test self-contained."""
    token = set_request_context(
        actor_id="test-user-42",
        actor_type="user",
        org_id="test-org-7",
        client_ip="10.20.30.40",
        request_id="req-abc",
    )
    try:
        row = KmsAuditLogs.insert(
            operation=KmsAuditOperation.WRAP.value,
            success=True,
            actor_type="user",  # explicit > context fallback
            config_path=f"{_TEST_PREFIX}with-ctx",
        )
    finally:
        reset_request_context(token)

    assert row is not None
    assert row.actor_id == "test-user-42"
    assert row.client_ip == "10.20.30.40"
    assert row.org_id == "test-org-7"
    assert row.request_id == "req-abc"


def test_explicit_kwargs_override_context():
    """Explicit insert() kwargs win over ContextVar values."""
    token = set_request_context(
        actor_id="ctx-actor",
        client_ip="1.1.1.1",
    )
    try:
        row = KmsAuditLogs.insert(
            operation=KmsAuditOperation.MIGRATE.value,
            success=True,
            actor_id="explicit-actor",
            client_ip="2.2.2.2",
            config_path=f"{_TEST_PREFIX}override",
        )
    finally:
        reset_request_context(token)

    assert row.actor_id == "explicit-actor"
    assert row.client_ip == "2.2.2.2"


def test_list_filters_by_operation_and_success():
    KmsAuditLogs.insert(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}list-wrap",
    )
    KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=True,
        config_path=f"{_TEST_PREFIX}list-unwrap-ok",
    )
    KmsAuditLogs.insert(
        operation=KmsAuditOperation.UNWRAP.value,
        success=False,
        config_path=f"{_TEST_PREFIX}list-unwrap-fail",
        error_code="GCM_TAG_FAIL",
    )

    rows, _total = KmsAuditLogs.list(
        operation="unwrap",
        success=False,
        config_path=_TEST_PREFIX,
        limit=10,
    )
    test_paths = [r.config_path for r in rows if r.config_path.startswith(_TEST_PREFIX)]
    assert any("unwrap-fail" in p for p in test_paths)
    assert all(
        r.operation == "unwrap" and r.success is False
        for r in rows
        if r.config_path.startswith(_TEST_PREFIX)
    )


def test_audit_shim_record_op_swallows_errors(monkeypatch):
    """The audit shim must never let a broken audit DB break the data
    path — an exception inside KmsAuditLogs.insert is caught and logged."""
    from open_webui.utils.kms import audit as audit_shim

    def boom(**kwargs):
        raise RuntimeError("simulated audit DB failure")

    # Force the shim's lazy logs reference to a stub that raises.
    monkeypatch.setattr(
        audit_shim, "_logs", type("Stub", (), {"insert": staticmethod(boom)})
    )

    # Calling record_op must not raise — it logs and returns.
    audit_shim.record_op(
        operation=KmsAuditOperation.WRAP.value,
        success=True,
        kek_uri="test://kek",
    )
    # Reset for other tests.
    monkeypatch.setattr(audit_shim, "_logs", None)


def test_parse_kek_version():
    from open_webui.utils.kms.audit import parse_kek_version

    assert (
        parse_kek_version("https://vault.vault.azure.net/keys/cloosphere-kek/abc123")
        == "abc123"
    )
    assert parse_kek_version("") is None
    assert parse_kek_version(None) is None
    assert parse_kek_version("https://vault/key") == "key"
