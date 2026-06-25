"""Add generated timestamp columns for PostgreSQL

Adds computed `_ts` columns (TIMESTAMP WITH TIME ZONE) that auto-convert
epoch integer timestamps via to_timestamp(). Only applies to PostgreSQL.

Revision ID: q8c9d0e1f2a3
Revises: p7b8c9d0e1f2
Create Date: 2026-03-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q8c9d0e1f2a3"
down_revision: Union[str, None] = "p7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables with epoch-seconds timestamp columns (int(time.time()))
SECONDS_TABLES = {
    "user": ["created_at", "updated_at", "last_active_at"],
    "chat": ["created_at", "updated_at"],
    "prompt": ["timestamp"],
    "knowledge": ["created_at", "updated_at"],
    "file": ["created_at", "updated_at"],
    "tool": ["created_at", "updated_at"],
    "folder": ["created_at", "updated_at"],
    "guardrail": ["created_at", "updated_at"],
    "log_usage": ["created_at", "updated_at"],
    "model": ["created_at", "updated_at"],
    "dbsphere": ["created_at", "updated_at", "last_extracted_at"],
    "glossary": ["created_at", "updated_at"],
    "schedule": ["created_at", "updated_at", "next_run_at", "start_at", "end_at"],
    "project": ["created_at", "updated_at"],
    "organization": ["created_at", "updated_at"],
    "organizational_unit": ["created_at", "updated_at"],
    "group": ["created_at", "updated_at"],
    "inquiry": ["created_at", "updated_at"],
    "log_guardrail": ["created_at"],
    "audit_log": ["created_at"],
    "feedback": ["created_at", "updated_at"],
    "function": ["created_at", "updated_at"],
    "memory": ["created_at", "updated_at", "deleted_at"],
    "tool_connection": ["created_at", "updated_at"],
    "trace_analysis": ["created_at", "completed_at"],
    "auto_evaluation": ["created_at", "completed_at"],
    "schedule_task": ["started_at", "completed_at"],
    "memory_retention_policy": ["created_at", "updated_at"],
    "memory_entity": ["created_at"],
    "memory_entity_type": ["created_at"],
}

# Tables with epoch-milliseconds timestamp columns (int(time.time() * 1000))
MILLISECONDS_TABLES = {
    "message_trace": ["created_at", "updated_at", "start_time", "end_time"],
}

# Tables with epoch-nanoseconds timestamp columns (int(time.time_ns()))
NANOSECONDS_TABLES = {
    "message": ["created_at", "updated_at"],
    "message_reaction": ["created_at"],
    "channel": ["created_at", "updated_at"],
}


def _add_generated_columns(table: str, columns: list[str], expression_template: str):
    """Add generated timestamp columns to a table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if table not in tables:
        return

    existing_columns = {c["name"] for c in inspector.get_columns(table)}

    for col in columns:
        ts_col = f"{col}_ts"
        if ts_col in existing_columns:
            continue

        expression = expression_template.format(col=col)
        op.add_column(
            table,
            sa.Column(
                ts_col,
                sa.DateTime(timezone=True),
                sa.Computed(expression),
            ),
        )


def _drop_generated_columns(table: str, columns: list[str]):
    """Drop generated timestamp columns from a table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if table not in tables:
        return

    existing_columns = {c["name"] for c in inspector.get_columns(table)}

    for col in columns:
        ts_col = f"{col}_ts"
        if ts_col not in existing_columns:
            continue
        op.drop_column(table, ts_col)


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    for table, columns in SECONDS_TABLES.items():
        _add_generated_columns(table, columns, "to_timestamp({col})")

    for table, columns in MILLISECONDS_TABLES.items():
        _add_generated_columns(
            table, columns, "to_timestamp({col}::double precision / 1000)"
        )

    for table, columns in NANOSECONDS_TABLES.items():
        _add_generated_columns(
            table, columns, "to_timestamp({col}::double precision / 1000000000)"
        )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    for table, columns in SECONDS_TABLES.items():
        _drop_generated_columns(table, columns)

    for table, columns in MILLISECONDS_TABLES.items():
        _drop_generated_columns(table, columns)

    for table, columns in NANOSECONDS_TABLES.items():
        _drop_generated_columns(table, columns)
