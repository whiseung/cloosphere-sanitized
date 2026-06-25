"""add extraction_engine_profile table + document_profile.extension_engine_map

Revision ID: ab9c0d1e2f3a
Revises: aa8b9c0d1e2f
Create Date: 2026-05-19

문서 처리 프로파일을 "단일 엔진 + 모든 파일 동일 적용" 에서
"확장자 -> 엔진 프로파일 매핑" 으로 확장하기 위한 schema-only 마이그레이션.

- extraction_engine_profile: 엔진 자격증명(reusable). 같은 engine_type 의
  여러 자격증명(예: DI Prod / DI Dev) 보유 가능.
- document_profile.extension_engine_map: {".pdf": "<engine_id>", ".xlsx": ...}
  형태의 JSON dict. NULL/빈 dict 면 legacy 경로로 동작 (기존 동작 100% 유지).

데이터 백필은 의도적으로 안 함 — 다중 고객사 무중단을 위해 관리자가 UI 의
"확장자별 매핑으로 전환" 버튼으로 자기 시점에 옵트인. legacy 컬럼
(content_extraction_engine, config, pdf_extract_images) 은 1릴리스 유예 후
별도 마이그레이션으로 drop.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab9c0d1e2f3a"
down_revision: Union[str, None] = "aa8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. extraction_engine_profile 테이블 (멱등)
    if "extraction_engine_profile" not in set(inspector.get_table_names()):
        op.create_table(
            "extraction_engine_profile",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=True),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("engine_type", sa.Text(), nullable=True, server_default=""),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column(
                "pdf_extract_images",
                sa.Boolean(),
                nullable=True,
                server_default=sa.false(),
            ),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
        )

    # 2. document_profile.extension_engine_map 컬럼 (멱등)
    if "document_profile" in set(inspector.get_table_names()):
        existing_cols = {c["name"] for c in inspector.get_columns("document_profile")}
        if "extension_engine_map" not in existing_cols:
            op.add_column(
                "document_profile",
                sa.Column("extension_engine_map", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "document_profile" in set(inspector.get_table_names()):
        existing_cols = {c["name"] for c in inspector.get_columns("document_profile")}
        if "extension_engine_map" in existing_cols:
            op.drop_column("document_profile", "extension_engine_map")

    if "extraction_engine_profile" in set(inspector.get_table_names()):
        op.drop_table("extraction_engine_profile")
