"""Add message_trace table

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2025-02-05 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "message_trace",
        # Primary key
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        # Trace hierarchy
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("parent_run_id", sa.String(), nullable=True),
        sa.Column("dotted_order", sa.String(), nullable=False),
        # Context
        sa.Column("chat_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        # Run info
        sa.Column("run_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, default="pending"),
        # Input/Output
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        # Timing
        sa.Column("start_time", sa.BigInteger(), nullable=False),
        sa.Column("end_time", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        # LLM specific
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        # Metadata
        sa.Column("meta", sa.JSON(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )

    # Create indexes
    op.create_index("ix_message_trace_trace_id", "message_trace", ["trace_id"])
    op.create_index(
        "ix_message_trace_chat_message", "message_trace", ["chat_id", "message_id"]
    )
    op.create_index(
        "ix_message_trace_user_created", "message_trace", ["user_id", "created_at"]
    )
    op.create_index("ix_message_trace_status", "message_trace", ["status"])


def downgrade():
    # Drop indexes
    op.drop_index("ix_message_trace_status", table_name="message_trace")
    op.drop_index("ix_message_trace_user_created", table_name="message_trace")
    op.drop_index("ix_message_trace_chat_message", table_name="message_trace")
    op.drop_index("ix_message_trace_trace_id", table_name="message_trace")

    # Drop table
    op.drop_table("message_trace")
