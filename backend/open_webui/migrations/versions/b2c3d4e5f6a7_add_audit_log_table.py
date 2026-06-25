"""Add audit_log table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-01-30 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "audit_log",
        # Primary key
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        # 누가 (Actor)
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("user_email", sa.Text(), nullable=True),
        sa.Column("user_name", sa.Text(), nullable=True),
        # 무엇을 (Resource)
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("resource_name", sa.Text(), nullable=True),
        # 어떤 액션 (Action)
        sa.Column("action", sa.String(50), nullable=False),
        # 변경 내용 (Changes)
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=True),
        # 권한 변경 상세 (Access Control Changes)
        sa.Column("access_control_changes", sa.JSON(), nullable=True),
        # 요청 컨텍스트 (Request Context)
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_path", sa.Text(), nullable=True),
        # 조직 컨텍스트 (Organization Context)
        sa.Column("organization_id", sa.Text(), nullable=True),
        # 메타데이터 (Metadata)
        sa.Column("meta", sa.JSON(), nullable=True),
        # 타임스탬프 (Timestamp)
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )

    # 인덱스 생성
    op.create_index(
        "ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"]
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_organization_id", "audit_log", ["organization_id"])


def downgrade():
    # 인덱스 삭제
    op.drop_index("ix_audit_log_organization_id", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_resource", table_name="audit_log")

    # 테이블 삭제
    op.drop_table("audit_log")
