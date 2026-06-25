"""drop memory_audit_log table

Revision ID: p7b8c9d0e1f2
Revises: o6a7b8c9d0e1
Create Date: 2026-03-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p7b8c9d0e1f2"
down_revision: Union[str, None] = "o6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "memory_audit_log" in tables:
        op.drop_index("ix_memory_audit_log_created_at", "memory_audit_log")
        op.drop_index("ix_memory_audit_log_user_id", "memory_audit_log")
        op.drop_index("ix_memory_audit_log_memory_id", "memory_audit_log")
        op.drop_table("memory_audit_log")


def downgrade() -> None:
    op.create_table(
        "memory_audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_memory_audit_log_memory_id", "memory_audit_log", ["memory_id"])
    op.create_index("ix_memory_audit_log_user_id", "memory_audit_log", ["user_id"])
    op.create_index(
        "ix_memory_audit_log_created_at", "memory_audit_log", ["created_at"]
    )
