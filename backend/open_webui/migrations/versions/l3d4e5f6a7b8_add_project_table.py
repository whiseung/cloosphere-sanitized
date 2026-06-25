"""Add project table

Revision ID: l3d4e5f6a7b8
Revises: k2c3d4e5f6a7
Create Date: 2026-02-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l3d4e5f6a7b8"
down_revision: Union[str, None] = "k2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "project" not in tables:
        op.create_table(
            "project",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("knowledge_id", sa.Text(), nullable=True),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("access_control", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )
        op.create_index("ix_project_user_id", "project", ["user_id"])
        op.create_index("ix_project_knowledge_id", "project", ["knowledge_id"])


def downgrade():
    op.drop_index("ix_project_knowledge_id", table_name="project")
    op.drop_index("ix_project_user_id", table_name="project")
    op.drop_table("project")
