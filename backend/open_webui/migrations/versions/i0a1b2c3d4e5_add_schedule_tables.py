"""Add schedule tables

Revision ID: i0a1b2c3d4e5
Revises: h9b0c1d2e3f4
Create Date: 2026-02-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i0a1b2c3d4e5"
down_revision: Union[str, None] = "h9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # Creating the 'schedule' table
    if "schedule" not in tables:
        op.create_table(
            "schedule",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("target_type", sa.Text(), nullable=False),
            sa.Column("target_model_id", sa.Text(), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("cron_expression", sa.Text(), nullable=False),
            sa.Column("timezone", sa.Text(), server_default="UTC"),
            sa.Column("delivery", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("next_run_at", sa.BigInteger(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("access_control", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
        )
        op.create_index("ix_schedule_user_id", "schedule", ["user_id"])
        op.create_index(
            "ix_schedule_active_next_run", "schedule", ["is_active", "next_run_at"]
        )

    # Creating the 'schedule_task' table
    if "schedule_task" not in tables:
        op.create_table(
            "schedule_task",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("schedule_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), server_default="pending"),
            sa.Column("worker_id", sa.Text(), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("chat_id", sa.Text(), nullable=True),
            sa.Column("scheduled_at", sa.BigInteger(), nullable=False),
            sa.Column("started_at", sa.BigInteger(), nullable=True),
            sa.Column("completed_at", sa.BigInteger(), nullable=True),
            sa.Column("retry_count", sa.Integer(), server_default="0"),
            sa.Column("max_retries", sa.Integer(), server_default="2"),
            sa.UniqueConstraint(
                "schedule_id",
                "scheduled_at",
                name="uq_schedule_task_schedule_scheduled",
            ),
        )
        op.create_index(
            "ix_schedule_task_schedule_id", "schedule_task", ["schedule_id"]
        )
        op.create_index("ix_schedule_task_status", "schedule_task", ["status"])
        op.create_index("ix_schedule_task_user_id", "schedule_task", ["user_id"])
        op.create_index(
            "ix_schedule_task_status_scheduled",
            "schedule_task",
            ["status", "scheduled_at"],
        )


def downgrade():
    op.drop_table("schedule_task")
    op.drop_table("schedule")
