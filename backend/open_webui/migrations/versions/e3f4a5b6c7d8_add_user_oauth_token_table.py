"""add user_oauth_token table

사용자별 OAuth provider(microsoft/google) 토큰 보관 테이블. Outlook/Gmail 등
Graph/Gmail API 호출에서 사용. (user_id, provider) unique — 한 사용자당 provider
별 단일 활성 토큰만 유지.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "user_oauth_token" not in existing_tables:
        op.create_table(
            "user_oauth_token",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("refresh_token", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
            sa.Column("scopes", sa.Text(), nullable=True),
            sa.Column("account_email", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
            sa.UniqueConstraint(
                "user_id",
                "provider",
                name="uq_user_oauth_token_user_provider",
            ),
        )

    inspector = sa.inspect(conn)
    if "user_oauth_token" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("user_oauth_token")
        }
        if "ix_user_oauth_token_user_id" not in existing_idx:
            op.create_index(
                "ix_user_oauth_token_user_id",
                "user_oauth_token",
                ["user_id"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "user_oauth_token" in set(inspector.get_table_names()):
        existing_idx = {
            idx["name"] for idx in inspector.get_indexes("user_oauth_token")
        }
        if "ix_user_oauth_token_user_id" in existing_idx:
            op.drop_index("ix_user_oauth_token_user_id", table_name="user_oauth_token")
        op.drop_table("user_oauth_token")
