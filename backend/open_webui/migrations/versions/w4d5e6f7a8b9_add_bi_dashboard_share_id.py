"""add share_id to bi_dashboard

Revision ID: w4d5e6f7a8b9
Revises: v3c4d5e6f7a8
Create Date: 2026-04-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.1
revision: str = "w4d5e6f7a8b9"
down_revision: Union[str, None] = "v3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = [c["name"] for c in inspector.get_columns("bi_dashboard")]
    if "share_id" not in columns:
        op.add_column(
            "bi_dashboard",
            sa.Column("share_id", sa.Text(), nullable=True, unique=True),
        )


def downgrade() -> None:
    op.drop_column("bi_dashboard", "share_id")
