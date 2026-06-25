"""Add workspace_tag and workspace_tag_assignment tables

Revision ID: r9d0e1f2a3b4
Revises: q8c9d0e1f2a3
Create Date: 2026-03-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r9d0e1f2a3b4"
down_revision: Union[str, None] = "q8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "workspace_tag" not in tables:
        op.create_table(
            "workspace_tag",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False, unique=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
        )

    if "workspace_tag_assignment" not in tables:
        op.create_table(
            "workspace_tag_assignment",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tag_id", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
        )
        op.create_index(
            "ix_wta_resource",
            "workspace_tag_assignment",
            ["resource_type", "resource_id"],
        )
        op.create_index(
            "ix_wta_tag_id",
            "workspace_tag_assignment",
            ["tag_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_wta_tag_id", table_name="workspace_tag_assignment")
    op.drop_index("ix_wta_resource", table_name="workspace_tag_assignment")
    op.drop_table("workspace_tag_assignment")
    op.drop_table("workspace_tag")
