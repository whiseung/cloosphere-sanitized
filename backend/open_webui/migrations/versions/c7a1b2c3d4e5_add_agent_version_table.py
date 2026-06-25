"""add agent_version table

워크스페이스 에이전트(Model 행 중 base_model_id 보유) 설정 전체의 버전 스냅샷 보관.

Revision ID: c7a1b2c3d4e5
Revises: bd1e2f3a4b5c
Create Date: 2026-06-22

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7a1b2c3d4e5"
down_revision = "bd1e2f3a4b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "agent_version" not in set(inspector.get_table_names()):
        op.create_table(
            "agent_version",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("agent_id", sa.Text(), nullable=True),
            sa.Column("version_number", sa.BigInteger(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=True),
            sa.Column("label", sa.Text(), nullable=True),
            sa.Column("user_id", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    # 새 테이블 반영 후 인덱스 가드
    inspector = sa.inspect(conn)
    if "agent_version" in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes("agent_version")}
        if "ix_agent_version_agent_id" not in existing_idx:
            op.create_index("ix_agent_version_agent_id", "agent_version", ["agent_id"])
        # (agent_id, version_number) 유니크 — 동시 생성 시 중복 시퀀스 방지
        if "uq_agent_version_agent_id_version" not in existing_idx:
            op.create_index(
                "uq_agent_version_agent_id_version",
                "agent_version",
                ["agent_id", "version_number"],
                unique=True,
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "agent_version" in set(inspector.get_table_names()):
        op.drop_table("agent_version")
