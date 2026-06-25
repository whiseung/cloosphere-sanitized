"""langgraph_checkpoint_marker

Revision ID: e7dacd03eeb6
Revises: b3c4d5e6f7a8
Create Date: 2026-05-04 11:17:12.677851

HITL (Human-in-the-Loop) interrupt-resume 인프라용 마커 마이그레이션.

이 시점부터 lifespan 의 init_checkpointer() 가 langgraph
AsyncPostgresSaver / AsyncSqliteSaver 를 setup 한다. setup() 은 다음 4개
테이블을 idempotent 하게 자가 생성하며 그 schema 책임은 langgraph 가 진다:

    - checkpoints
    - checkpoint_blobs
    - checkpoint_writes
    - checkpoint_migrations  (langgraph 자체 마이그레이션 추적)

따라서 이 alembic 마이그레이션은 의도적으로 no-op. langgraph 가 schema 를
변경/추가하면 그쪽 자체 마이그레이션 시스템이 따라간다. 우리 alembic 에서
이 테이블을 다시 추적하면 drift 위험만 커진다.

운영자에게 "이 시점부터 checkpoint 테이블이 DB 에 자동 생성된다"는 사실을
히스토리에 남기는 것이 이 revision 의 유일한 목적.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e7dacd03eeb6"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op marker. langgraph self-managed:
    # checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations
    pass


def downgrade() -> None:
    # No-op. checkpoint 테이블 정리는 운영자가 수동으로 결정 (HITL 비활성화
    # 시에도 과거 thread state 를 보존하고 싶을 수 있음).
    pass
