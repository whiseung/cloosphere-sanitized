"""cleanup kg chunk nodes and edges

Revision ID: d3ac1e746df4
Revises: 570f58580d01
Create Date: 2026-04-17

KG 구조 개편 후속 정리. KG 는 의미 그래프로 단순화되고, 청크 단위 검색은
KB 벡터스토어가 file_id 로 hit 후 자체 처리하도록 변경되었다 (kg_restructure
+ kg_agent_chunk_removal). 따라서 기존 KG 에 남은 다음 데이터를 일괄 삭제:

- ``kg_node`` 의 ``node_type='chunk'`` 노드
- ``kg_edge`` 의 ``edge_type IN ('mentioned_in', 'contains_chunk')`` 엣지

PostgreSQL 의 AGE 그래프(`graph_<kg_id>`) 안 chunk 노드/엣지는 이 마이그레이션
범위 밖. KG 재 sync 시 새 doc_extract 경로가 chunk 를 만들지 않으므로 stale
AGE 데이터는 자연스럽게 무시되며, 별도 정리는 필요할 때 KG 재생성으로 처리.

Forward-only — chunk 데이터는 sync 로 재생성 가능하지만 본 마이그레이션은
복원 책임이 없음.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3ac1e746df4"
down_revision: Union[str, None] = "570f58580d01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. chunk 관련 엣지 삭제 (mentioned_in: term→chunk, contains_chunk: doc→chunk)
    conn.execute(
        sa.text(
            "DELETE FROM kg_edge WHERE edge_type IN ('mentioned_in', 'contains_chunk')"
        )
    )

    # 2. chunk 노드 삭제
    conn.execute(sa.text("DELETE FROM kg_node WHERE node_type = 'chunk'"))


def downgrade() -> None:
    # Forward-only — chunk 데이터는 KG 재 sync 로 재생성 가능.
    pass
