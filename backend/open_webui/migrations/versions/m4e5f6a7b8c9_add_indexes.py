"""Add indexes to file, log_usage, auto_evaluation tables

Revision ID: m4e5f6a7b8c9
Revises: l3d4e5f6a7b8
Create Date: 2026-03-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m4e5f6a7b8c9"
down_revision: Union[str, None] = "l3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # file table indexes
    file_indexes = {idx["name"] for idx in inspector.get_indexes("file")}
    if "ix_file_user_id" not in file_indexes:
        op.create_index("ix_file_user_id", "file", ["user_id"])
    if "ix_file_created_at" not in file_indexes:
        op.create_index("ix_file_created_at", "file", ["created_at"])

    # log_usage table indexes
    usage_indexes = {idx["name"] for idx in inspector.get_indexes("log_usage")}
    if "ix_log_usage_user_id" not in usage_indexes:
        op.create_index("ix_log_usage_user_id", "log_usage", ["user_id"])
    if "ix_log_usage_model_id" not in usage_indexes:
        op.create_index("ix_log_usage_model_id", "log_usage", ["model_id"])
    if "ix_log_usage_agent_id" not in usage_indexes:
        op.create_index("ix_log_usage_agent_id", "log_usage", ["agent_id"])
    if "ix_log_usage_created_at" not in usage_indexes:
        op.create_index("ix_log_usage_created_at", "log_usage", ["created_at"])
    if "ix_log_usage_message_type" not in usage_indexes:
        op.create_index("ix_log_usage_message_type", "log_usage", ["message_type"])

    # auto_evaluation table indexes (user_id only — others already exist from migration)
    eval_indexes = {idx["name"] for idx in inspector.get_indexes("auto_evaluation")}
    if "ix_auto_evaluation_user_id" not in eval_indexes:
        op.create_index("ix_auto_evaluation_user_id", "auto_evaluation", ["user_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    eval_indexes = {idx["name"] for idx in inspector.get_indexes("auto_evaluation")}
    if "ix_auto_evaluation_user_id" in eval_indexes:
        op.drop_index("ix_auto_evaluation_user_id", table_name="auto_evaluation")

    usage_indexes = {idx["name"] for idx in inspector.get_indexes("log_usage")}
    for name in [
        "ix_log_usage_message_type",
        "ix_log_usage_created_at",
        "ix_log_usage_agent_id",
        "ix_log_usage_model_id",
        "ix_log_usage_user_id",
    ]:
        if name in usage_indexes:
            op.drop_index(name, table_name="log_usage")

    file_indexes = {idx["name"] for idx in inspector.get_indexes("file")}
    for name in ["ix_file_created_at", "ix_file_user_id"]:
        if name in file_indexes:
            op.drop_index(name, table_name="file")
