"""add last_heartbeat_at to kg_extract_job

Revision ID: fb6aa2011608
Revises: bb2c3d4e5f6a
Create Date: 2026-04-11 00:08:55.690740

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fb6aa2011608"
down_revision: Union[str, None] = "bb2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_extract_job" not in set(inspector.get_table_names()):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("kg_extract_job")}
    if "last_heartbeat_at" not in existing_columns:
        op.add_column(
            "kg_extract_job",
            sa.Column("last_heartbeat_at", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("kg_extract_job", "last_heartbeat_at")
