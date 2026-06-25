"""drop unused embedding_profile table

Revision ID: y6e7f8a9b0c1
Revises: x5d6e7f8a9b0
Create Date: 2026-04-09

임베딩 프로필 기능은 단일 글로벌 RAG 설정으로 통합되어 더 이상 사용하지
않는다. 테이블이 남아있으면 이전 코드 잔재가 stale 데이터를 fallback으로
읽어와 글로벌 설정을 덮어쓰는 문제가 있어 안전하게 제거한다.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "y6e7f8a9b0c1"
down_revision: Union[str, None] = "x5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "embedding_profile" in inspector.get_table_names():
        op.drop_table("embedding_profile")


def downgrade() -> None:
    op.create_table(
        "embedding_profile",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("embedding_engine", sa.Text(), server_default=""),
        sa.Column("embedding_model", sa.Text(), server_default=""),
        sa.Column("embedding_batch_size", sa.Integer(), server_default="1"),
        sa.Column("embedding_dimensions", sa.Integer(), server_default="0"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger()),
        sa.Column("updated_at", sa.BigInteger()),
    )
