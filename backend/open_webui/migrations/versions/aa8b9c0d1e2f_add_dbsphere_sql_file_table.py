"""add dbsphere_sql_file table

Revision ID: aa8b9c0d1e2f
Revises: f0e1d2c3b4a5
Create Date: 2026-05-16

DbSphere SQL Editor 기능을 위한 사용자별 .sql 파일 영속 테이블.
- dbsphere_sql_file: 한 DbSphere 에 종속된 .sql 파일 (user_id 소유, 1차 공유 X)
- access_control 컬럼은 후방 호환으로 nullable 추가 (1차 미사용)

FK 제약은 두지 않는다 (Cloosphere 전반의 패턴 일치). 대신 인덱스로
조회 성능을 보장한다 (dbsphere_id, user_id, composite).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa8b9c0d1e2f"
down_revision: Union[str, None] = "f0e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: 다른 branch 또는 수동 SQL로 이미 적용된 환경에서도 안전.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "dbsphere_sql_file" not in existing_tables:
        op.create_table(
            "dbsphere_sql_file",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("dbsphere_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("access_control", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )

    # 새 테이블 반영을 위해 inspector 재생성
    inspector = sa.inspect(conn)
    if "dbsphere_sql_file" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("dbsphere_sql_file")
        }

        if "ix_dbsphere_sql_file_dbsphere_id" not in existing_idx:
            op.create_index(
                "ix_dbsphere_sql_file_dbsphere_id",
                "dbsphere_sql_file",
                ["dbsphere_id"],
            )

        if "ix_dbsphere_sql_file_user_id" not in existing_idx:
            op.create_index(
                "ix_dbsphere_sql_file_user_id",
                "dbsphere_sql_file",
                ["user_id"],
            )

        # 라우터의 핵심 쿼리: list by (dbsphere_id, user_id) ordered by updated_at desc
        if "ix_dbsphere_sql_file_dbsphere_user" not in existing_idx:
            op.create_index(
                "ix_dbsphere_sql_file_dbsphere_user",
                "dbsphere_sql_file",
                ["dbsphere_id", "user_id"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "dbsphere_sql_file" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("dbsphere_sql_file")
        }
        for name in (
            "ix_dbsphere_sql_file_dbsphere_user",
            "ix_dbsphere_sql_file_user_id",
            "ix_dbsphere_sql_file_dbsphere_id",
        ):
            if name in existing_idx:
                op.drop_index(name, table_name="dbsphere_sql_file")
        op.drop_table("dbsphere_sql_file")
