"""Add guardrail log table

Revision ID: g8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2025-02-10 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g8a9b0c1d2e3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "log_guardrail",
        # Primary key
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        # 누가 (Actor)
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("user_email", sa.Text(), nullable=True),
        sa.Column("user_name", sa.Text(), nullable=True),
        # 채팅 컨텍스트 (Chat Context)
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        # 가드레일 정보 (Guardrail Info)
        sa.Column("guardrail_id", sa.Text(), nullable=True),
        sa.Column("guardrail_name", sa.Text(), nullable=True),
        # 감지 결과 (Detection Result)
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("detection_source", sa.String(50), nullable=False),
        sa.Column("detection_detail", sa.Text(), nullable=True),
        # 콘텐츠 (Content)
        sa.Column("original_content", sa.Text(), nullable=True),
        sa.Column("processed_content", sa.Text(), nullable=True),
        # 메타데이터 (Metadata)
        sa.Column("meta", sa.JSON(), nullable=True),
        # 타임스탬프 (Timestamp)
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )

    # 인덱스 생성
    op.create_index("ix_log_guardrail_user_id", "log_guardrail", ["user_id"])
    op.create_index("ix_log_guardrail_chat_id", "log_guardrail", ["chat_id"])
    op.create_index("ix_log_guardrail_action", "log_guardrail", ["action"])
    op.create_index(
        "ix_log_guardrail_detection_source",
        "log_guardrail",
        ["detection_source"],
    )
    op.create_index("ix_log_guardrail_created_at", "log_guardrail", ["created_at"])


def downgrade():
    # 인덱스 삭제
    op.drop_index("ix_log_guardrail_created_at", table_name="log_guardrail")
    op.drop_index("ix_log_guardrail_detection_source", table_name="log_guardrail")
    op.drop_index("ix_log_guardrail_action", table_name="log_guardrail")
    op.drop_index("ix_log_guardrail_chat_id", table_name="log_guardrail")
    op.drop_index("ix_log_guardrail_user_id", table_name="log_guardrail")

    # 테이블 삭제
    op.drop_table("log_guardrail")
