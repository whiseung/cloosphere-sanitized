"""Add dbsphere schema extraction fields

Revision ID: f7a8b9c0d1e2
Revises: d5e6f7a8b9c0
Create Date: 2026-02-05 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add schema extraction fields to dbsphere table
    print("Adding schema extraction fields to dbsphere table")

    # auto_extract_model - Model ID for LLM-based schema extraction
    op.add_column(
        "dbsphere",
        sa.Column("auto_extract_model", sa.Text(), nullable=True),
    )

    # sample_row_count - Number of sample rows for schema extraction
    op.add_column(
        "dbsphere",
        sa.Column(
            "sample_row_count", sa.BigInteger(), nullable=True, server_default="5"
        ),
    )

    # last_extracted_at - Timestamp of last schema extraction
    op.add_column(
        "dbsphere",
        sa.Column("last_extracted_at", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dbsphere", "last_extracted_at")
    op.drop_column("dbsphere", "sample_row_count")
    op.drop_column("dbsphere", "auto_extract_model")
