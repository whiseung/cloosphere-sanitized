"""Add chat_id column to schedule table

Revision ID: k2c3d4e5f6a7
Revises: j1b2c3d4e5f6
Create Date: 2026-02-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k2c3d4e5f6a7"
down_revision: Union[str, None] = "j1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("schedule")]

    if "chat_id" not in columns:
        op.add_column("schedule", sa.Column("chat_id", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("schedule", "chat_id")
