"""memory governance columns and tables

Revision ID: n5f6a7b8c9d0
Revises: 9540f6a26bfd
Create Date: 2026-03-18

"""

import time
import uuid
from typing import Sequence, Union

import open_webui.internal.db
import sqlalchemy as sa
from alembic import op

revision: str = "n5f6a7b8c9d0"
down_revision: Union[str, None] = "9540f6a26bfd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("memory")]
    tables = inspector.get_table_names()

    # 1. Add governance columns to memory table (idempotent)
    if "scope" not in columns:
        op.add_column(
            "memory",
            sa.Column("scope", sa.String(), server_default="user", nullable=True),
        )
    if "org_id" not in columns:
        op.add_column(
            "memory",
            sa.Column("org_id", sa.String(), nullable=True),
        )
    if "retention_class" not in columns:
        op.add_column(
            "memory",
            sa.Column(
                "retention_class", sa.String(), server_default="standard", nullable=True
            ),
        )
    if "deleted_at" not in columns:
        op.add_column(
            "memory",
            sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        )

    # 2. Create memory_audit_log table
    if "memory_audit_log" not in tables:
        op.create_table(
            "memory_audit_log",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("memory_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("metadata", open_webui.internal.db.JSONField(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )
        op.create_index(
            "ix_memory_audit_log_memory_id", "memory_audit_log", ["memory_id"]
        )
        op.create_index("ix_memory_audit_log_user_id", "memory_audit_log", ["user_id"])
        op.create_index(
            "ix_memory_audit_log_created_at", "memory_audit_log", ["created_at"]
        )

    # 3. Create memory_retention_policy table (idempotent)
    if "memory_retention_policy" not in tables:
        op.create_table(
            "memory_retention_policy",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("retention_class", sa.String(), nullable=False),
            sa.Column("ttl_days", sa.BigInteger(), nullable=True),
            sa.Column(
                "on_expire", sa.String(), nullable=False, server_default="soft_delete"
            ),
            sa.Column("org_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint(
                "retention_class", "org_id", name="uq_retention_class_org"
            ),
        )

    # 4. Backfill existing memories
    op.execute("UPDATE memory SET scope = 'user' WHERE scope IS NULL")
    op.execute(
        "UPDATE memory SET retention_class = 'temporary' WHERE source = 'auto' AND retention_class IS NULL"
    )
    op.execute(
        "UPDATE memory SET retention_class = 'standard' WHERE source = 'manual' AND retention_class IS NULL"
    )
    op.execute(
        "UPDATE memory SET retention_class = 'permanent' WHERE source = 'profile' AND retention_class IS NULL"
    )
    op.execute(
        "UPDATE memory SET retention_class = 'standard' WHERE retention_class IS NULL"
    )

    # 5. Seed default retention policies (idempotent — skip if already seeded)
    if "memory_retention_policy" not in tables:
        now = int(time.time())
        seed_sql = sa.text(
            "INSERT INTO memory_retention_policy (id, retention_class, ttl_days, on_expire, created_at, updated_at) "
            "VALUES (:id, :cls, :ttl, :on_expire, :now, :now)"
        )
        for cls, ttl in [("temporary", 30), ("standard", 180), ("permanent", None)]:
            op.execute(
                seed_sql.bindparams(
                    id=str(uuid.uuid4()),
                    cls=cls,
                    ttl=ttl,
                    on_expire="soft_delete",
                    now=now,
                )
            )


def downgrade() -> None:
    op.drop_table("memory_retention_policy")
    op.drop_index("ix_memory_audit_log_created_at", "memory_audit_log")
    op.drop_index("ix_memory_audit_log_user_id", "memory_audit_log")
    op.drop_index("ix_memory_audit_log_memory_id", "memory_audit_log")
    op.drop_table("memory_audit_log")
    op.drop_column("memory", "deleted_at")
    op.drop_column("memory", "retention_class")
    op.drop_column("memory", "org_id")
    op.drop_column("memory", "scope")
