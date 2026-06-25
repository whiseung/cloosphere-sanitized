"""add source column to memory

Revision ID: 9540f6a26bfd
Revises: f39910d9448c
Create Date: 2026-03-18 09:17:54.536546

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9540f6a26bfd"
down_revision: Union[str, None] = "f39910d9448c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("memory")]
    if "source" not in columns:
        op.add_column(
            "memory",
            sa.Column("source", sa.String(), server_default="manual", nullable=True),
        )


def downgrade() -> None:
    op.drop_column("memory", "source")
