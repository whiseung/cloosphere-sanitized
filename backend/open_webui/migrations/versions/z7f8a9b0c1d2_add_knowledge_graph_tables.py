"""add knowledge graph tables

Revision ID: z7f8a9b0c1d2
Revises: y6e7f8a9b0c1
Create Date: 2026-04-09

KG(지식그래프) Phase 0 슬라이스: 워크스페이스 리소스 1개 +
노드/엣지 테이블 2개를 추가한다.

설계는 backend/open_webui/models/knowledge_graph.py 참고.
- knowledge_graph: 워크스페이스 리소스 (Glossary와 동일 패턴)
- kg_node: 그래프 노드 (term/concept/table/column/metric/doc_entity)
- kg_edge: 그래프 엣지 (synonym/maps_to/foreign_key/...)

FK 제약은 두지 않는다 (Cloosphere 전반의 패턴 일치). 대신
인덱스로 트래버설 성능을 보장한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z7f8a9b0c1d2"
down_revision: Union[str, None] = "y6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: 다른 branch 또는 수동 SQL로 이미 적용된 환경에서도 안전.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    def _ensure_index(table: str, name: str, columns: list[str]) -> None:
        if table not in set(inspector.get_table_names()):
            return
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, columns)

    if "knowledge_graph" not in existing_tables:
        op.create_table(
            "knowledge_graph",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("access_control", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )

    if "kg_node" not in existing_tables:
        op.create_table(
            "kg_node",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("node_type", sa.Text(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("properties", sa.JSON(), nullable=True),
            sa.Column("source_ref", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )
    _ensure_index("kg_node", "ix_kg_node_kg_id", ["kg_id"])
    _ensure_index("kg_node", "kg_node_kg_type_idx", ["kg_id", "node_type"])
    _ensure_index("kg_node", "kg_node_kg_label_idx", ["kg_id", "label"])

    if "kg_edge" not in existing_tables:
        op.create_table(
            "kg_edge",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("src_id", sa.Text(), nullable=False),
            sa.Column("dst_id", sa.Text(), nullable=False),
            sa.Column("edge_type", sa.Text(), nullable=False),
            sa.Column("weight", sa.Float(), nullable=True),
            sa.Column("properties", sa.JSON(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )
    _ensure_index("kg_edge", "ix_kg_edge_kg_id", ["kg_id"])
    _ensure_index("kg_edge", "kg_edge_kg_src_idx", ["kg_id", "src_id", "edge_type"])
    _ensure_index("kg_edge", "kg_edge_kg_dst_idx", ["kg_id", "dst_id", "edge_type"])


def downgrade() -> None:
    op.drop_index("kg_edge_kg_dst_idx", table_name="kg_edge")
    op.drop_index("kg_edge_kg_src_idx", table_name="kg_edge")
    op.drop_index("ix_kg_edge_kg_id", table_name="kg_edge")
    op.drop_table("kg_edge")

    op.drop_index("kg_node_kg_label_idx", table_name="kg_node")
    op.drop_index("kg_node_kg_type_idx", table_name="kg_node")
    op.drop_index("ix_kg_node_kg_id", table_name="kg_node")
    op.drop_table("kg_node")

    op.drop_table("knowledge_graph")
