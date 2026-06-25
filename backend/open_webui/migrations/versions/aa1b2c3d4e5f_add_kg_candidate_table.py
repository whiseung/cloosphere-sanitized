"""add kg_candidate table

Revision ID: aa1b2c3d4e5f
Revises: z7f8a9b0c1d2
Create Date: 2026-04-09

KG(지식그래프) Slice 6: LLM이 추출한 용어집 용어 후보를 저장하는
검수 큐 테이블 추가.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "z7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_candidate" not in set(inspector.get_table_names()):
        op.create_table(
            "kg_candidate",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("candidate_type", sa.Text(), nullable=False),
            sa.Column("suggested_label", sa.Text(), nullable=False),
            sa.Column("target_node_id", sa.Text(), nullable=True),
            sa.Column("properties", sa.JSON(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("resolved_glossary_id", sa.Text(), nullable=True),
            sa.Column("resolved_entry_id", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        )

    inspector = sa.inspect(conn)
    if "kg_candidate" in set(inspector.get_table_names()):
        existing = {idx["name"] for idx in inspector.get_indexes("kg_candidate")}
        if "ix_kg_candidate_kg_id" not in existing:
            op.create_index("ix_kg_candidate_kg_id", "kg_candidate", ["kg_id"])
        if "kg_candidate_kg_status_idx" not in existing:
            op.create_index(
                "kg_candidate_kg_status_idx", "kg_candidate", ["kg_id", "status"]
            )


def downgrade() -> None:
    op.drop_index("kg_candidate_kg_status_idx", table_name="kg_candidate")
    op.drop_index("ix_kg_candidate_kg_id", table_name="kg_candidate")
    op.drop_table("kg_candidate")
