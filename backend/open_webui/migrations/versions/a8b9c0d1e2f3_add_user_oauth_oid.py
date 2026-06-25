"""add oauth_oid column to user

Entra `oid` claim 저장 필드. Teams 봇 등 외부 Entra 연동에서 Activity.from.aadObjectId
로 사용자 매칭에 사용. 기존 MS 로그인 사용자는 next login 시 자동 채움 (backfill 불필요).

Revision ID: a8b9c0d1e2f3
Revises: z7f8a9b0c1d2
Create Date: 2026-04-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
# 두 head (z7f... KG 관련, b1c2... 레거시 branch) 를 이 마이그레이션에서 merge 해
# 단일 head 로 수렴. 기능적으로는 oauth_oid 컬럼 추가만 수행.
down_revision: Union[str, Sequence[str], None] = ("z7f8a9b0c1d2", "b1c2d3e4f5a6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_columns = {col["name"] for col in inspector.get_columns("user")}
    if "oauth_oid" not in existing_columns:
        op.add_column(
            "user",
            sa.Column("oauth_oid", sa.Text(), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user")}
    if "ix_user_oauth_oid" not in existing_indexes:
        op.create_index("ix_user_oauth_oid", "user", ["oauth_oid"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_oauth_oid", table_name="user")
    op.drop_column("user", "oauth_oid")
