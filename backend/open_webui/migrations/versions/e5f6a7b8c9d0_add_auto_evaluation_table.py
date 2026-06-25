"""Add auto_evaluation table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2025-02-02

"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auto_evaluation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("judge_model_id", sa.Text(), nullable=False),
        # Evaluation type
        sa.Column(
            "evaluation_type", sa.Text(), nullable=False
        ),  # retrieval, faithfulness, quality
        # Evaluation input (snapshot)
        sa.Column("user_query", sa.Text(), nullable=True),
        sa.Column("assistant_response", sa.Text(), nullable=True),
        sa.Column("retrieved_contexts", sa.JSON(), nullable=True),
        # Evaluation result
        sa.Column("score", sa.Float(), nullable=True),  # 0.0 ~ 1.0
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        # Status
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="pending"
        ),  # pending, completed, failed
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
    )

    # Create indexes for common query patterns
    op.create_index(
        "ix_auto_evaluation_model_id", "auto_evaluation", ["model_id"], unique=False
    )
    op.create_index(
        "ix_auto_evaluation_chat_id", "auto_evaluation", ["chat_id"], unique=False
    )
    op.create_index(
        "ix_auto_evaluation_status", "auto_evaluation", ["status"], unique=False
    )
    op.create_index(
        "ix_auto_evaluation_created_at",
        "auto_evaluation",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_auto_evaluation_created_at", table_name="auto_evaluation")
    op.drop_index("ix_auto_evaluation_status", table_name="auto_evaluation")
    op.drop_index("ix_auto_evaluation_chat_id", table_name="auto_evaluation")
    op.drop_index("ix_auto_evaluation_model_id", table_name="auto_evaluation")
    op.drop_table("auto_evaluation")
