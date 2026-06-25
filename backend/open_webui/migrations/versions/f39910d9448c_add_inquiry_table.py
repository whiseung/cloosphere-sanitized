"""add inquiry table

Revision ID: f39910d9448c
Revises: m4e5f6a7b8c9
Create Date: 2026-03-09 09:45:27.813985

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f39910d9448c"
down_revision: Union[str, None] = "m4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "inquiry" not in tables:
        op.create_table(
            "inquiry",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String()),
            sa.Column("title", sa.String()),
            sa.Column("type", sa.String()),
            sa.Column("subtype", sa.String()),
            sa.Column("content", sa.Text()),
            sa.Column("status", sa.String()),
            sa.Column("admin_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger()),
            sa.Column("updated_at", sa.BigInteger()),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("inquiry")}

    if "ix_inquiry_user_id" not in indexes:
        op.create_index("ix_inquiry_user_id", "inquiry", ["user_id"])
    if "ix_inquiry_status" not in indexes:
        op.create_index("ix_inquiry_status", "inquiry", ["status"])
    if "ix_inquiry_type" not in indexes:
        op.create_index("ix_inquiry_type", "inquiry", ["type"])
    if "ix_inquiry_created_at" not in indexes:
        op.create_index("ix_inquiry_created_at", "inquiry", ["created_at"])


def downgrade():
    op.drop_index("ix_inquiry_created_at", table_name="inquiry")
    op.drop_index("ix_inquiry_type", table_name="inquiry")
    op.drop_index("ix_inquiry_status", table_name="inquiry")
    op.drop_index("ix_inquiry_user_id", table_name="inquiry")
    op.drop_table("inquiry")
