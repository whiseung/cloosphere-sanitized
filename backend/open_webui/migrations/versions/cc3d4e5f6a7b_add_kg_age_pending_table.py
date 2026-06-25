"""add kg_age_pending table

Revision ID: cc3d4e5f6a7b
Revises: fb6aa2011608
Create Date: 2026-04-10

AGE dual-write WAL(Write-Ahead Log) 테이블.
SQL 성공 후 AGE 쓰기에 실패한 작업을 기록하여 이후 retry로
AGE 그래프 일관성을 복구한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc3d4e5f6a7b"
down_revision: Union[str, None] = "fb6aa2011608"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_age_pending" not in set(inspector.get_table_names()):
        op.create_table(
            "kg_age_pending",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("operation", sa.Text(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("retries", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("last_retry_at", sa.BigInteger(), nullable=True),
        )

    inspector = sa.inspect(conn)
    if "kg_age_pending" in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes("kg_age_pending")}
        if "ix_kg_age_pending_kg_id" not in existing_idx:
            op.create_index("ix_kg_age_pending_kg_id", "kg_age_pending", ["kg_id"])


def downgrade() -> None:
    op.drop_index("ix_kg_age_pending_kg_id", table_name="kg_age_pending")
    op.drop_table("kg_age_pending")
