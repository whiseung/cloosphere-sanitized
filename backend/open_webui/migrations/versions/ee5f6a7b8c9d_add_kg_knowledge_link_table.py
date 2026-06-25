"""add kg_knowledge_link table

Revision ID: z8g9a0b1c2d3
Revises: z7f8a9b0c1d2
Create Date: 2026-04-10

지식 연결(knowledge_links)을 KnowledgeGraph.data JSON에서 독립 테이블로 분리.
동시 수정 시 데이터 유실 방지 + JSON 직렬화 비용 제거.
기존 JSON 데이터는 런타임 fallback으로 호환 유지.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee5f6a7b8c9d"
down_revision: Union[str, None] = "dd4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_knowledge_link" not in set(inspector.get_table_names()):
        op.create_table(
            "kg_knowledge_link",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column(
                "source_type", sa.Text(), nullable=False, server_default="db_column"
            ),
            sa.Column("dbsphere_id", sa.Text(), nullable=True),
            sa.Column("table_name", sa.Text(), nullable=True),
            sa.Column("label_column", sa.Text(), nullable=True),
            sa.Column("key_column", sa.Text(), nullable=True),
            sa.Column("glossary_id", sa.Text(), nullable=True),
            sa.Column(
                "target_type", sa.Text(), nullable=False, server_default="knowledge"
            ),
            sa.Column("knowledge_ids", sa.JSON(), nullable=True),
            sa.Column("target_dbsphere_id", sa.Text(), nullable=True),
            sa.Column("target_table_name", sa.Text(), nullable=True),
            sa.Column("target_column", sa.Text(), nullable=True),
            sa.Column("edge_type", sa.Text(), nullable=True),
            sa.Column("status", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )

    inspector = sa.inspect(conn)
    if "kg_knowledge_link" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("kg_knowledge_link")
        }
        if "ix_kg_knowledge_link_kg_id" not in existing_idx:
            op.create_index(
                "ix_kg_knowledge_link_kg_id", "kg_knowledge_link", ["kg_id"]
            )


def downgrade() -> None:
    op.drop_index("ix_kg_knowledge_link_kg_id")
    op.drop_table("kg_knowledge_link")
