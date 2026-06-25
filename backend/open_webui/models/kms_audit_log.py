"""
KMS Audit Log — tamper-evident hash-chained record of every KMS operation.

Each row carries the SHA-256 of the *previous* row (`prev_hash`) and the
SHA-256 of its own canonical payload + prev_hash (`row_hash`). Tampering
with any historic row breaks the chain on `verify_chain()`.

Privacy: rows NEVER contain plaintext, ciphertext, DEKs, or AAD raw —
only the operation, the config_path identifier (e.g. ``openai.api_key``),
and the actor/request context.

Phase 4.2 — see ``.claude/work/kms_design.md`` §11.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from contextvars import ContextVar
from enum import Enum
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Index, String, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# Genesis hash for the very first audit row — there is no prior row to
# chain against, so we anchor on a deterministic constant. Must never
# change once any row is written, or every chain verification breaks.
GENESIS_HASH = "0" * 64


class KmsAuditOperation(str, Enum):
    WRAP = "wrap"  # encrypt called
    UNWRAP = "unwrap"  # decrypt called
    ROTATE = "rotate"  # re-encrypt with newer KEK (Phase 4.3)
    REVOKE = "revoke"  # KEK marked revoked
    HEALTH_CHECK = "health_check"  # admin "Test Connection"
    PROVIDER_CHANGE = "provider_change"  # KMS provider switched
    MIGRATE = "migrate"  # bulk re-encryption migration
    AUDIT_EXPORT = "audit_export"  # audit log export (sensitive op itself)


class KmsAuditActorType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    SCHEDULED = "scheduled"


####################
# DB Schema
####################


class KmsAuditLog(Base):
    __tablename__ = "kms_audit_log"

    # Auto-incrementing PK doubles as chain order — the verifier walks rows
    # in id-asc order and recomputes hashes.
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Unix epoch milliseconds — sub-second precision matters when hot paths
    # (every DbSphere query hits unwrap) burst-fire audit rows.
    timestamp_ms = Column(BigInteger, nullable=False)

    actor_type = Column(String(32), nullable=False)
    actor_id = Column(Text, nullable=True)
    org_id = Column(Text, nullable=True)

    operation = Column(String(32), nullable=False)

    # Identifier of the field/value (e.g. ``openai.api_key``,
    # ``users.api_key``, ``dbsphere:<id>:password``). NEVER the value itself.
    config_path = Column(Text, nullable=True)
    kek_uri = Column(Text, nullable=True)
    kek_version = Column(Text, nullable=True)
    classification = Column(String(32), nullable=True)

    success = Column(Boolean, nullable=False)
    error_code = Column(Text, nullable=True)

    request_id = Column(Text, nullable=True)
    client_ip = Column(String(45), nullable=True)  # IPv6 max length

    # Hash chain.
    prev_hash = Column(String(64), nullable=False)
    row_hash = Column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_kms_audit_log_timestamp", "timestamp_ms"),
        Index("ix_kms_audit_log_org_ts", "org_id", "timestamp_ms"),
        Index("ix_kms_audit_log_operation", "operation"),
    )


####################
# Pydantic
####################


class KmsAuditLogModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp_ms: int
    actor_type: str
    actor_id: Optional[str] = None
    org_id: Optional[str] = None
    operation: str
    config_path: Optional[str] = None
    kek_uri: Optional[str] = None
    kek_version: Optional[str] = None
    classification: Optional[str] = None
    success: bool
    error_code: Optional[str] = None
    request_id: Optional[str] = None
    client_ip: Optional[str] = None
    prev_hash: str
    row_hash: str


####################
# Request context (ContextVar) — propagation
####################
#
# KMS encrypt/decrypt is called deep inside the data layer that doesn't
# know which user / request triggered it. The auth middleware pushes the
# (actor_id, org_id, request_id, client_ip) tuple into a ContextVar at
# request entry; the audit logger reads it at write time.
#
# We use ContextVar (not threading.local) so each async task has its own
# slot — FastAPI handlers run on threadpool or the asyncio loop depending
# on the path.

_audit_request_context: ContextVar[Optional[dict]] = ContextVar(
    "kms_audit_request_context", default=None
)

# Reentrancy guard — if writing an audit row itself triggers another KMS
# call (e.g. via SQLAlchemy session listeners), we MUST drop the nested
# audit attempt. Otherwise the chain order breaks and we may deadlock.
_in_audit_write: ContextVar[bool] = ContextVar("kms_audit_in_write", default=False)


def set_request_context(
    *,
    actor_id: Optional[str] = None,
    actor_type: Optional[str] = None,
    org_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_ip: Optional[str] = None,
):
    """Push the current request's audit context. Returns the prior token —
    callers must call ``reset_request_context(token)`` on teardown
    (typically via a FastAPI middleware ``finally``)."""
    return _audit_request_context.set(
        {
            "actor_id": actor_id,
            "actor_type": actor_type,
            "org_id": org_id,
            "request_id": request_id,
            "client_ip": client_ip,
        }
    )


def reset_request_context(token):
    if token is not None:
        _audit_request_context.reset(token)


def get_request_context() -> dict:
    return _audit_request_context.get() or {}


####################
# Hash chain
####################


def _payload_for_hash(row_dict: dict) -> dict:
    """Hash input — every column except id (assigned post-insert) and
    row_hash (the output we're computing)."""
    return {
        "timestamp_ms": row_dict["timestamp_ms"],
        "actor_type": row_dict["actor_type"],
        "actor_id": row_dict.get("actor_id"),
        "org_id": row_dict.get("org_id"),
        "operation": row_dict["operation"],
        "config_path": row_dict.get("config_path"),
        "kek_uri": row_dict.get("kek_uri"),
        "kek_version": row_dict.get("kek_version"),
        "classification": row_dict.get("classification"),
        "success": row_dict["success"],
        "error_code": row_dict.get("error_code"),
        "request_id": row_dict.get("request_id"),
        "client_ip": row_dict.get("client_ip"),
    }


def compute_row_hash(payload: dict, prev_hash: str) -> str:
    """SHA-256 over canonical JSON of (payload + prev_hash). Used at write
    time and re-used at verify time so any drift in the canonical form
    surfaces as a verification failure rather than silent corruption."""
    canonical = json.dumps(
        {**payload, "prev_hash": prev_hash},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_to_payload(row: KmsAuditLog) -> dict:
    return {
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


####################
# Table operations
####################

# Process-local lock — serializes two threads inside the *same* worker so
# they don't both fetch the same prev_hash and write divergent rows.
_write_lock = threading.Lock()

# PostgreSQL advisory lock id — held inside the audit insert transaction
# to serialize chain appends across uvicorn workers. Without this, two
# workers running on the same DB can fetch identical prev_hash values
# concurrently and emit a broken chain (id N+1 whose prev_hash != id N's
# row_hash). The lock is released automatically when the transaction
# commits or rolls back. Distinct from the scheduler's 20260226.
_AUDIT_CHAIN_LOCK_ID = 20260301


class KmsAuditLogTable:
    def insert(
        self,
        *,
        operation: str,
        success: bool,
        actor_type: str = KmsAuditActorType.SYSTEM.value,
        actor_id: Optional[str] = None,
        org_id: Optional[str] = None,
        config_path: Optional[str] = None,
        kek_uri: Optional[str] = None,
        kek_version: Optional[str] = None,
        classification: Optional[str] = None,
        error_code: Optional[str] = None,
        request_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[KmsAuditLogModel]:
        """Append a chained audit row.

        Failures are swallowed (logged) so a broken audit DB never breaks
        the data path — but they are loud in logs because a permanent
        audit failure is itself a compliance incident.
        """
        if _in_audit_write.get():
            # Reentrant call — silently drop. See _in_audit_write docstring.
            return None

        token = _in_audit_write.set(True)
        try:
            ctx = get_request_context()
            row_data = {
                "timestamp_ms": int(time.time() * 1000),
                "actor_type": actor_type or ctx.get("actor_type") or "system",
                "actor_id": actor_id or ctx.get("actor_id"),
                "org_id": org_id or ctx.get("org_id"),
                "operation": operation,
                "config_path": config_path,
                "kek_uri": kek_uri,
                "kek_version": kek_version,
                "classification": classification,
                "success": success,
                "error_code": error_code,
                "request_id": request_id or ctx.get("request_id"),
                "client_ip": client_ip or ctx.get("client_ip"),
            }

            with _write_lock:
                with get_db() as db:
                    # Multi-worker safety: hold a transaction-scoped
                    # PostgreSQL advisory lock so concurrent workers can't
                    # both read the same `last.row_hash` and emit a
                    # broken chain. SQLite's writer lock provides the
                    # same serialization implicitly, so we skip the call
                    # there.
                    from open_webui.internal.db import SQLALCHEMY_DATABASE_URL
                    from sqlalchemy import text

                    if "sqlite" not in SQLALCHEMY_DATABASE_URL:
                        try:
                            db.execute(
                                text(
                                    "SELECT pg_advisory_xact_lock("
                                    f"{_AUDIT_CHAIN_LOCK_ID})"
                                )
                            )
                        except Exception as e:
                            log.warning(
                                "KMS audit advisory lock failed (%s) — "
                                "falling back to in-process serialization only",
                                e,
                            )

                    last = (
                        db.query(KmsAuditLog.row_hash)
                        .order_by(KmsAuditLog.id.desc())
                        .first()
                    )
                    prev_hash = last.row_hash if last else GENESIS_HASH

                    row_data["prev_hash"] = prev_hash
                    row_data["row_hash"] = compute_row_hash(
                        _payload_for_hash(row_data), prev_hash
                    )

                    try:
                        record = KmsAuditLog(**row_data)
                        db.add(record)
                        db.commit()
                        db.refresh(record)
                        return KmsAuditLogModel.model_validate(record)
                    except Exception as e:
                        db.rollback()
                        log.error(
                            "KMS audit log insert failed (operation=%s): %s",
                            operation,
                            e,
                        )
                        return None
        finally:
            _in_audit_write.reset(token)

    def list(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        operation: Optional[str] = None,
        success: Optional[bool] = None,
        actor_id: Optional[str] = None,
        org_id: Optional[str] = None,
        config_path: Optional[str] = None,
        from_ts_ms: Optional[int] = None,
        to_ts_ms: Optional[int] = None,
    ) -> tuple[list[KmsAuditLogModel], int]:
        with get_db() as db:
            query = db.query(KmsAuditLog)
            if operation:
                ops = [o.strip() for o in operation.split(",") if o.strip()]
                if len(ops) == 1:
                    query = query.filter(KmsAuditLog.operation == ops[0])
                elif ops:
                    query = query.filter(KmsAuditLog.operation.in_(ops))
            if success is not None:
                query = query.filter(KmsAuditLog.success == success)
            if actor_id:
                query = query.filter(KmsAuditLog.actor_id == actor_id)
            if org_id:
                query = query.filter(KmsAuditLog.org_id == org_id)
            if config_path:
                query = query.filter(KmsAuditLog.config_path.ilike(f"%{config_path}%"))
            if from_ts_ms:
                query = query.filter(KmsAuditLog.timestamp_ms >= from_ts_ms)
            if to_ts_ms:
                query = query.filter(KmsAuditLog.timestamp_ms <= to_ts_ms)

            total = query.count()
            offset = max(page - 1, 0) * limit
            rows = (
                query.order_by(KmsAuditLog.id.desc()).offset(offset).limit(limit).all()
            )
            return [KmsAuditLogModel.model_validate(r) for r in rows], total

    def verify_chain(
        self,
        *,
        from_id: Optional[int] = None,
        to_id: Optional[int] = None,
        max_rows: int = 100_000,
    ) -> dict:
        """Walk the chain in id-asc and recompute every row_hash.

        Returns:
            {
              "checked": int,
              "ok": bool,
              "first_break_id": Optional[int],
              "first_break_reason": Optional[str],
              "from_id": Optional[int],
              "to_id": Optional[int],
            }
        """
        with get_db() as db:
            query = db.query(KmsAuditLog)
            if from_id:
                query = query.filter(KmsAuditLog.id >= from_id)
            if to_id:
                query = query.filter(KmsAuditLog.id <= to_id)
            rows = query.order_by(KmsAuditLog.id.asc()).limit(max_rows).all()

            if not rows:
                return {
                    "checked": 0,
                    "ok": True,
                    "first_break_id": None,
                    "first_break_reason": None,
                    "from_id": from_id,
                    "to_id": to_id,
                }

            # Anchor — for sub-range checks the chain expectation is the
            # row immediately before the first checked row; for full-range
            # it's GENESIS_HASH.
            if from_id and rows[0].id > 1:
                anchor = (
                    db.query(KmsAuditLog.row_hash)
                    .filter(KmsAuditLog.id < rows[0].id)
                    .order_by(KmsAuditLog.id.desc())
                    .first()
                )
                expected_prev = anchor.row_hash if anchor else GENESIS_HASH
            else:
                expected_prev = GENESIS_HASH

            for idx, row in enumerate(rows, start=1):
                if row.prev_hash != expected_prev:
                    return {
                        "checked": idx,
                        "ok": False,
                        "first_break_id": row.id,
                        "first_break_reason": "prev_hash mismatch",
                        "from_id": from_id,
                        "to_id": to_id,
                    }
                recomputed = compute_row_hash(_row_to_payload(row), row.prev_hash)
                if row.row_hash != recomputed:
                    return {
                        "checked": idx,
                        "ok": False,
                        "first_break_id": row.id,
                        "first_break_reason": "row_hash mismatch (data tampered)",
                        "from_id": from_id,
                        "to_id": to_id,
                    }
                expected_prev = row.row_hash

            return {
                "checked": len(rows),
                "ok": True,
                "first_break_id": None,
                "first_break_reason": None,
                "from_id": from_id,
                "to_id": to_id,
            }


KmsAuditLogs = KmsAuditLogTable()
