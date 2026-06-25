"""merge schedule and trusted_audience branches

c1d2e3f4a5b6 (schedule.triggered_by_user_id) 과 c4d5e6f7a8b9 (trusted_audience)
가 동일 시점(2026-04-23)에 병렬 작성되어 alembic head 가 두 개로 갈라진 상태.
단일 head 로 수렴시키는 빈 merge 마이그레이션.

선행 마이그레이션들은 모두 idempotent 하게 작성되어 있으므로 alembic 이
어느 branch 를 walk 하든 안전하다 (재실행에서도 DDL 충돌 발생 X).

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6, c4d5e6f7a8b9
Create Date: 2026-04-27
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = ("c1d2e3f4a5b6", "c4d5e6f7a8b9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
