"""add agent_id to usage table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2025-01-31

"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    # Add agent_id column to log_usage table
    op.add_column(
        "log_usage",
        sa.Column("agent_id", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("log_usage", "agent_id")
