"""Add start_at and end_at columns to schedule table

Revision ID: j1b2c3d4e5f6
Revises: i0a1b2c3d4e5
Create Date: 2026-02-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j1b2c3d4e5f6"
down_revision: Union[str, None] = "i0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("schedule")]

    if "start_at" not in columns:
        op.add_column("schedule", sa.Column("start_at", sa.BigInteger(), nullable=True))
    if "end_at" not in columns:
        op.add_column("schedule", sa.Column("end_at", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("schedule", "end_at")
    op.drop_column("schedule", "start_at")
