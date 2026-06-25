"""add kg_knowledge_link config column

Revision ID: c0d1e2f3a4b5
Revises: ee5f6a7b8c9d
Create Date: 2026-04-14

링크 단위 엣지 타입 카탈로그를 저장할 ``config`` JSON 컬럼 추가.

KG 단위가 아닌 link(글로서리 → 다중 KB) 단위로:
- ``edge_types``: 카탈로그 항목 dict ({key: {display_name, description, source, recommendation_reason, ...}})
- ``edge_types_locked``: KB 청크 추출 시 strict allow-list 강제 여부

추출 시 source_sync_worker 가 link.config 를 읽어 청크 워커에 그대로 전달한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "ee5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 일부 환경에서 컬럼이 alembic 외부 (수동 SQL / 이전 형태 마이그레이션)
    # 로 이미 추가된 경우가 있어 inspector 로 멱등 처리한다.
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("kg_knowledge_link")}
    if "config" not in cols:
        op.add_column(
            "kg_knowledge_link",
            sa.Column("config", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("kg_knowledge_link")}
    if "config" in cols:
        op.drop_column("kg_knowledge_link", "config")
