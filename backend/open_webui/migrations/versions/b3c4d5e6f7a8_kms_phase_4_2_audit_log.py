"""kms phase 4.2 audit log

Adds the ``kms_audit_log`` table for tamper-evident hash-chained audit of
every KMS wrap/unwrap/rotate/revoke/health_check/migrate operation.

Why: Phase 4.2 of the KMS rollout — design §11. Each row carries
``prev_hash`` (SHA-256 of prior row) and ``row_hash`` (SHA-256 of its own
canonical payload + prev_hash) so historic tampering breaks the chain.

Privacy: this table NEVER stores plaintext, ciphertext, DEKs, or AAD raw
— only the operation, the config_path identifier, and request context.

Revision ID: b3c4d5e6f7a8
Revises: 5f9605dd422a
Create Date: 2026-04-29 19:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "5f9605dd422a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create kms_audit_log + supporting indexes. All DDL idempotent so
    re-running against a partially-applied DB succeeds."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kms_audit_log" not in set(inspector.get_table_names()):
        op.create_table(
            "kms_audit_log",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
            sa.Column("actor_type", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.Text(), nullable=True),
            sa.Column("org_id", sa.Text(), nullable=True),
            sa.Column("operation", sa.String(length=32), nullable=False),
            sa.Column("config_path", sa.Text(), nullable=True),
            sa.Column("kek_uri", sa.Text(), nullable=True),
            sa.Column("kek_version", sa.Text(), nullable=True),
            sa.Column("classification", sa.String(length=32), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("error_code", sa.Text(), nullable=True),
            sa.Column("request_id", sa.Text(), nullable=True),
            sa.Column("client_ip", sa.String(length=45), nullable=True),
            sa.Column("prev_hash", sa.String(length=64), nullable=False),
            sa.Column("row_hash", sa.String(length=64), nullable=False),
        )

    inspector = sa.inspect(conn)
    if "kms_audit_log" in set(inspector.get_table_names()):
        existing_indexes = {
            idx["name"] for idx in inspector.get_indexes("kms_audit_log")
        }
        if "ix_kms_audit_log_timestamp" not in existing_indexes:
            op.create_index(
                "ix_kms_audit_log_timestamp", "kms_audit_log", ["timestamp_ms"]
            )
        if "ix_kms_audit_log_org_ts" not in existing_indexes:
            op.create_index(
                "ix_kms_audit_log_org_ts",
                "kms_audit_log",
                ["org_id", "timestamp_ms"],
            )
        if "ix_kms_audit_log_operation" not in existing_indexes:
            op.create_index(
                "ix_kms_audit_log_operation", "kms_audit_log", ["operation"]
            )


def downgrade() -> None:
    """Drop indexes + table. Idempotent — survives partial-apply state."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kms_audit_log" in set(inspector.get_table_names()):
        existing_indexes = {
            idx["name"] for idx in inspector.get_indexes("kms_audit_log")
        }
        for idx_name in (
            "ix_kms_audit_log_operation",
            "ix_kms_audit_log_org_ts",
            "ix_kms_audit_log_timestamp",
        ):
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name="kms_audit_log")
        op.drop_table("kms_audit_log")
