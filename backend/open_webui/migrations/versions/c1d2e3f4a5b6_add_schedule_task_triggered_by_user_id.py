"""Add triggered_by_user_id column to schedule_task table

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-23

Records which user manually triggered a schedule run (via POST /{id}/run).
NULL = 정기 실행 (스케줄러), 값 있음 = 수동 트리거 사용자 id.
소유자 본인 트리거는 NULL로 기록 (자기 스케줄 실행은 audit 대상 아님).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("schedule_task")]

    if "triggered_by_user_id" not in columns:
        op.add_column(
            "schedule_task",
            sa.Column("triggered_by_user_id", sa.Text(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("schedule_task")]

    if "triggered_by_user_id" in columns:
        op.drop_column("schedule_task", "triggered_by_user_id")
