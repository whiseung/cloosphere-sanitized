"""Add dbsphere_memory_usage table

few-shot(sql_memory) 등 DbSphere 메모리가 프롬프트에 주입(참조)될 때마다 이벤트 행을
기록하는 append-only 테이블. GROUP BY 로 참조횟수/마지막참조일 집계 → 미사용 식별용.

모든 DDL 은 inspector 가드로 idempotent (고객사 부분적용 DB 재실행 안전).
verify_schema_state 에는 등록하지 않는다 — 이 테이블은 graceful-degrade(누락돼도
쿼리 흐름 영향 0)이므로 startup abort 유발 대상이 아니다.

Revision ID: bd1e2f3a4b5c
Revises: bc0d1e2f3a4b
Create Date: 2026-06-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd1e2f3a4b5c"
down_revision: Union[str, None] = "bc0d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "dbsphere_memory_usage"
INDEXES = [
    ("ix_dbsphere_memory_usage_memory_id", ["memory_id"]),
    ("ix_dbsphere_memory_usage_dbsphere_id", ["dbsphere_id"]),
    ("ix_dbsphere_memory_usage_user_id", ["user_id"]),
    ("ix_dbsphere_memory_usage_created_at", ["created_at"]),
    ("ix_dbsphere_memory_usage_dbsphere_memory", ["dbsphere_id", "memory_id"]),
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in set(inspector.get_table_names()):
        op.create_table(
            TABLE,
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("memory_id", sa.Text(), nullable=False),
            sa.Column("dbsphere_id", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.String(50), nullable=True),
            sa.Column("user_id", sa.Text(), nullable=True),
            sa.Column("chat_id", sa.Text(), nullable=True),
            sa.Column("injection_point", sa.String(30), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )

    inspector = sa.inspect(conn)  # 새 테이블 반영
    if TABLE in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes(TABLE)}
        for name, cols in INDEXES:
            if name not in existing_idx:
                op.create_index(name, TABLE, cols)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes(TABLE)}
        for name, _cols in INDEXES:
            if name in existing_idx:
                op.drop_index(name, table_name=TABLE)
        op.drop_table(TABLE)
