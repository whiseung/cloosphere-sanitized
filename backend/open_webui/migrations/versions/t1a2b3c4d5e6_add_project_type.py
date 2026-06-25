"""add type column to project

Revision ID: t1a2b3c4d5e6
Revises: 9540f6a26bfd
Create Date: 2026-03-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t1a2b3c4d5e6"
down_revision: Union[str, None] = "r9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("project")]
    if "type" not in columns:
        op.add_column(
            "project",
            sa.Column("type", sa.Text(), server_default="general", nullable=True),
        )


def downgrade() -> None:
    op.drop_column("project", "type")
