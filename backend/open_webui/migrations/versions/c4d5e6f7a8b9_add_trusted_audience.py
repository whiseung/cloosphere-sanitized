"""add trusted_audience table

외부 IDP(Entra / Google) ID 토큰 passthrough 인증용 신뢰 audience 레지스트리.
관리자 UI 에서 등록한 audience 만 외부 API 토큰 인증을 통과한다.

Revision ID: c4d5e6f7a8b9
Revises: a8b9c0d1e2f3
Create Date: 2026-04-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "trusted_audience" not in set(inspector.get_table_names()):
        op.create_table(
            "trusted_audience",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("idp_type", sa.Text(), nullable=False),
            sa.Column("audience", sa.Text(), nullable=False),
            sa.Column("tenant_id", sa.Text(), nullable=True),
            sa.Column("issuer", sa.Text(), nullable=True),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("auto_provision", sa.Boolean(), server_default=sa.text("false")),
            sa.Column(
                "default_role",
                sa.Text(),
                server_default=sa.text("'user'"),
                nullable=False,
            ),
            sa.Column("default_group_ids", sa.JSON(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )

    inspector = sa.inspect(conn)
    if "trusted_audience" in set(inspector.get_table_names()):
        existing = {idx["name"] for idx in inspector.get_indexes("trusted_audience")}
        if "ix_trusted_audience_audience" not in existing:
            op.create_index(
                "ix_trusted_audience_audience",
                "trusted_audience",
                ["audience"],
                unique=False,
            )


def downgrade() -> None:
    op.drop_index("ix_trusted_audience_audience", table_name="trusted_audience")
    op.drop_table("trusted_audience")
