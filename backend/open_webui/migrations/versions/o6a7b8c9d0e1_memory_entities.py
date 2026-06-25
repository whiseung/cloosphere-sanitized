"""memory entity tables

Revision ID: o6a7b8c9d0e1
Revises: n5f6a7b8c9d0
Create Date: 2026-03-19
"""

import time
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o6a7b8c9d0e1"
down_revision: Union[str, None] = "n5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "memory_entity" not in tables:
        op.create_table(
            "memory_entity",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("memory_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("org_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint(
                "name", "entity_type", "user_id", name="uq_entity_name_type_user"
            ),
        )
        op.create_index("ix_memory_entity_user_id", "memory_entity", ["user_id"])
        op.create_index("ix_memory_entity_type", "memory_entity", ["entity_type"])

    if "memory_entity_type" not in tables:
        op.create_table(
            "memory_entity_type",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("org_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint("name", "org_id", name="uq_entity_type_name_org"),
        )

    # Seed default entity types (idempotent)
    if "memory_entity_type" not in tables:
        now = int(time.time())
        defaults = [
            ("tech", "Technologies, frameworks, tools, languages"),
            ("project", "Project names and products"),
            ("person", "People names"),
            ("organization", "Companies, teams, departments"),
            ("concept", "Domain concepts and other entities"),
        ]
        for name, desc in defaults:
            op.execute(
                sa.text(
                    "INSERT INTO memory_entity_type (id, name, description, created_at) "
                    "VALUES (:id, :name, :desc, :now)"
                ).bindparams(id=str(uuid.uuid4()), name=name, desc=desc, now=now)
            )


def downgrade() -> None:
    op.drop_index("ix_memory_entity_type", "memory_entity")
    op.drop_index("ix_memory_entity_user_id", "memory_entity")
    op.drop_table("memory_entity")
    op.drop_table("memory_entity_type")
