"""add kg_extract_state table

Revision ID: dd4e5f6a7b8c
Revises: cc3d4e5f6a7b
Create Date: 2026-04-10

KB 추출 상태를 KnowledgeGraph.data JSON에서 별도 테이블로 분리.
concurrent worker의 race condition 방지 + JSON bloat 해소.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd4e5f6a7b8c"
down_revision: Union[str, None] = "cc3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_extract_state" not in set(inspector.get_table_names()):
        op.create_table(
            "kg_extract_state",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("kb_id", sa.Text(), nullable=False),
            sa.Column("processed_chunks", sa.JSON(), nullable=True),
            sa.Column("last_run_at", sa.BigInteger(), nullable=True),
            sa.Column("last_model", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )

    inspector = sa.inspect(conn)
    if "kg_extract_state" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("kg_extract_state")
        }
        if "kg_extract_state_kg_kb_idx" not in existing_idx:
            op.create_index(
                "kg_extract_state_kg_kb_idx",
                "kg_extract_state",
                ["kg_id", "kb_id"],
                unique=True,
            )


def downgrade() -> None:
    op.drop_index("kg_extract_state_kg_kb_idx")
    op.drop_table("kg_extract_state")
