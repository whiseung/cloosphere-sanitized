"""merge kg heads

Revision ID: 570f58580d01
Revises: b9c0d1e2f3a4, c0d1e2f3a4b5
Create Date: 2026-04-15 17:33:18.227110

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "570f58580d01"
down_revision: Union[str, None] = ("b9c0d1e2f3a4", "c0d1e2f3a4b5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
