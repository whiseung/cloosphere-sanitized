"""cleanup dangling kg extracted_from edges

Revision ID: 686ce6f4803f
Revises: d3ac1e746df4
Create Date: 2026-04-17

이전 마이그레이션 (d3ac1e746df4) 이 chunk 노드를 삭제했지만,
``extracted_from`` 엣지의 dst 가 chunk 였던 것들은 dangling 상태로
남았다. 새 sync 는 doc_extract 가 DOCUMENT 를 dst 로 만들지만, 기존
KG 의 extracted_from edges 는 여전히 사라진 chunk id 를 가리킨다.

dangling edge 가 있으면 ``_collect_file_candidates_from_graph`` 의
edge_types (카탈로그 엣지) 필터가 doc_entity → extracted_from →
DOCUMENT 경로를 못 따라가서 hit 0 이 된다.

해결: kg_node 에 존재하지 않는 dst 를 가진 extracted_from edges 일괄
삭제. 새 sync 트리거 시 doc_extract 가 DOCUMENT 를 dst 로 만들어
정상 경로 복원됨.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "686ce6f4803f"
down_revision: Union[str, None] = "d3ac1e746df4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM kg_edge"
            " WHERE edge_type='extracted_from'"
            "   AND dst_id NOT IN (SELECT id FROM kg_node)"
        )
    )


def downgrade() -> None:
    pass
