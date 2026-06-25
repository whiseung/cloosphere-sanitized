"""Add trace analysis table

Revision ID: h9b0c1d2e3f4
Revises: g8a9b0c1d2e3
Create Date: 2026-02-26 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h9b0c1d2e3f4"
down_revision: Union[str, None] = "g8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "trace_analysis",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("user_description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("context_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
    )

    op.create_index("ix_trace_analysis_trace_id", "trace_analysis", ["trace_id"])
    op.create_index("ix_trace_analysis_user_id", "trace_analysis", ["user_id"])
    op.create_index("ix_trace_analysis_status", "trace_analysis", ["status"])


def downgrade():
    op.drop_index("ix_trace_analysis_status", table_name="trace_analysis")
    op.drop_index("ix_trace_analysis_user_id", table_name="trace_analysis")
    op.drop_index("ix_trace_analysis_trace_id", table_name="trace_analysis")
    op.drop_table("trace_analysis")
