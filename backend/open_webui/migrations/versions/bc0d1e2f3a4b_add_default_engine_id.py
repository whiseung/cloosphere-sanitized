"""add document_profile.default_engine_id

Revision ID: bc0d1e2f3a4b
Revises: ab9c0d1e2f3a
Create Date: 2026-05-19

문서 처리 프로파일에 "매핑에 없는 확장자의 기본 엔진" 컬럼 추가. NULL 이면
기본 내장 엔진(engine_type="") 사용 — 기존 동작과 동일. 관리자가 명시적으로
설정하면 그 엔진이 fallback 으로 동작.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bc0d1e2f3a4b"
down_revision: Union[str, None] = "ab9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "document_profile" in set(inspector.get_table_names()):
        existing_cols = {c["name"] for c in inspector.get_columns("document_profile")}
        if "default_engine_id" not in existing_cols:
            op.add_column(
                "document_profile",
                sa.Column("default_engine_id", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "document_profile" in set(inspector.get_table_names()):
        existing_cols = {c["name"] for c in inspector.get_columns("document_profile")}
        if "default_engine_id" in existing_cols:
            op.drop_column("document_profile", "default_engine_id")
