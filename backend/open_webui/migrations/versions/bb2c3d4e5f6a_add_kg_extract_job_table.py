"""add kg_extract_job table

Revision ID: bb2c3d4e5f6a
Revises: aa1b2c3d4e5f
Create Date: 2026-04-10

KG(지식그래프) Slice 9: 백그라운드 추출/동기화 잡 추적 테이블.
사용자가 long-running LLM 추출의 진행 상황을 알 수 있게 하기 위함.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb2c3d4e5f6a"
down_revision: Union[str, None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "kg_extract_job" not in set(inspector.get_table_names()):
        op.create_table(
            "kg_extract_job",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("kg_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            # kind: 'kb_extract', 'kb_cleanup', 'candidate_extract', 'sync_all'
            sa.Column("kind", sa.Text(), nullable=False),
            # status: 'pending', 'running', 'completed', 'failed'
            sa.Column("status", sa.Text(), nullable=False),
            # 옵션: target 리소스 ID (예: knowledge_id, dbsphere_id)
            sa.Column("target_id", sa.Text(), nullable=True),
            # 호출 시 form data — 재실행/디버깅용
            sa.Column("params", sa.JSON(), nullable=True),
            sa.Column(
                "progress_current", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "progress_total", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("progress_label", sa.Text(), nullable=True),
            # 최종 통계 (entities_created, edges_created, ...)
            sa.Column("stats", sa.JSON(), nullable=True),
            # 에러 메시지 리스트
            sa.Column("errors", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("started_at", sa.BigInteger(), nullable=True),
            sa.Column("finished_at", sa.BigInteger(), nullable=True),
        )

    inspector = sa.inspect(conn)
    if "kg_extract_job" in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes("kg_extract_job")}
        if "kg_extract_job_kg_idx" not in existing_idx:
            op.create_index(
                "kg_extract_job_kg_idx", "kg_extract_job", ["kg_id", "created_at"]
            )
        if "kg_extract_job_status_idx" not in existing_idx:
            op.create_index("kg_extract_job_status_idx", "kg_extract_job", ["status"])


def downgrade() -> None:
    op.drop_index("kg_extract_job_status_idx", table_name="kg_extract_job")
    op.drop_index("kg_extract_job_kg_idx", table_name="kg_extract_job")
    op.drop_table("kg_extract_job")
