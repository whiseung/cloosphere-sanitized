"""add bi_dashboard and bi_panel tables

Revision ID: v3c4d5e6f7a8
Revises: u2b3c4d5e6f7
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3c4d5e6f7a8"
down_revision: Union[str, None] = "u2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "bi_dashboard" not in tables:
        op.create_table(
            "bi_dashboard",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text()),
            sa.Column("name", sa.Text()),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("access_control", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger()),
            sa.Column("updated_at", sa.BigInteger()),
        )

    if "bi_panel" not in tables:
        op.create_table(
            "bi_panel",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("dashboard_id", sa.Text()),
            sa.Column("user_id", sa.Text()),
            sa.Column("name", sa.Text()),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("dbsphere_id", sa.Text()),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger()),
            sa.Column("updated_at", sa.BigInteger()),
        )


def downgrade() -> None:
    op.drop_table("bi_panel")
    op.drop_table("bi_dashboard")
