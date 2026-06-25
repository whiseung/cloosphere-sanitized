"""drop legacy db_column knowledge links

Revision ID: a8f9b0c1d2e3
Revises: z7f8a9b0c1d2
Create Date: 2026-04-13

지식 연결(`kg_knowledge_link`) 구조 단순화 — source 는 항상 용어집,
target 은 항상 KB(복수) 로 좁힌다. 기존에 존재하던
`source_type='db_column'` 혹은 `target_type='db_column'` 레코드는 더 이상
지원되지 않는 조합이므로 제거하고, 함께 남아 있을 수 있는 dimension 기반
노드/엣지도 source_ref 접두사(`{kg_id}__dimension__{link_id}__`)로 cleanup.

테이블 컬럼 자체는 legacy 호환을 위해 nullable 상태로 그대로 둔다 — 신규
레코드는 모두 null 로 생성되며, drop 하려면 다음 마이그레이션에서 처리한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f9b0c1d2e3"
down_revision: Union[str, None] = "z7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. dimension 노드/엣지 cleanup — 이전 디멘전 기반 sync 가 만든 노드
    #    (`{kg_id}__dimension__{link_id}__...`) 와 관련 엣지 제거.
    conn.execute(
        sa.text(
            r"DELETE FROM kg_edge"
            r" WHERE src_id LIKE '%\_\_dimension\_\_%' ESCAPE '\'"
            r" OR dst_id LIKE '%\_\_dimension\_\_%' ESCAPE '\'"
        )
    )
    conn.execute(
        sa.text(
            r"DELETE FROM kg_node"
            r" WHERE id LIKE '%\_\_dimension\_\_%' ESCAPE '\'"
        )
    )

    # 2. db_column 기반 링크 레코드 삭제
    conn.execute(
        sa.text(
            "DELETE FROM kg_knowledge_link"
            " WHERE source_type = 'db_column' OR target_type = 'db_column'"
        )
    )

    # 3. link_sync 잡 기록 정리 (신규 UI 에서는 조회 경로 없음)
    conn.execute(sa.text("DELETE FROM kg_extract_job WHERE kind = 'link_sync'"))


def downgrade() -> None:
    # Forward-only migration — legacy 데이터 복구 불가.
    pass
