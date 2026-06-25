"""Add guardrail table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2025-02-02

"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    # Creating the 'guardrail' table
    op.create_table(
        "guardrail",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Rule-based settings
        sa.Column("pii_types", sa.JSON(), nullable=True, default=[]),
        sa.Column("pii_strategy", sa.Text(), nullable=True, default="redact"),
        sa.Column("custom_patterns", sa.JSON(), nullable=True, default=[]),
        sa.Column("blocked_words", sa.JSON(), nullable=True, default=[]),
        # Apply scope
        sa.Column("apply_to_input", sa.Boolean(), nullable=True, default=True),
        sa.Column("apply_to_output", sa.Boolean(), nullable=True, default=False),
        # LLM-as-a-Judge settings
        sa.Column("llm_judge_enabled", sa.Boolean(), nullable=True, default=False),
        sa.Column("llm_judge_model", sa.Text(), nullable=True),
        sa.Column("llm_judge_prompt", sa.Text(), nullable=True),
        sa.Column("llm_judge_pass_examples", sa.JSON(), nullable=True, default=[]),
        sa.Column("llm_judge_block_examples", sa.JSON(), nullable=True, default=[]),
        sa.Column(
            "llm_judge_apply_to_input", sa.Boolean(), nullable=True, default=True
        ),
        sa.Column(
            "llm_judge_apply_to_output", sa.Boolean(), nullable=True, default=False
        ),
        # Access control
        sa.Column("access_control", sa.JSON(), nullable=True),
        # Metadata
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_table("guardrail")
