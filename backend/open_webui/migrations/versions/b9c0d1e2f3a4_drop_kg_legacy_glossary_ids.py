"""drop legacy KG.data glossary_ids fields

Revision ID: b9c0d1e2f3a4
Revises: a8f9b0c1d2e3
Create Date: 2026-04-13

KG 편집 페이지가 용어집/KB 연결을 지식 연결(`kg_knowledge_link`) 테이블로만
관리하도록 통합되면서, KG.data 의 다음 legacy 필드는 더 이상 의미가 없다:

- ``data.glossary_ids``
- ``data.sources.glossary_ids``
- ``data.sources.knowledge_ids``
- ``data.sources.dbsphere_ids``

이 마이그레이션은 모든 KnowledgeGraph row 의 data JSON 에서 위 필드를 제거한다.
연결 정보 자체는 ``kg_knowledge_link`` 테이블에 들어 있으므로 손실 없음. KG 의
노드/엣지는 다음 sync 시점에 cleanup → upsert 로 자연스럽게 재구축된다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8f9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import json

    conn = op.get_bind()

    # 모든 KG row 를 읽어 data JSON 에서 legacy 필드 제거
    rows = conn.execute(sa.text("SELECT id, data FROM knowledge_graph")).fetchall()
    for row_id, raw in rows:
        if not raw:
            continue
        # data 는 JSON column 이라 driver 마다 반환 형태가 다름 (text 또는 dict)
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                continue
        else:
            data = dict(raw)

        changed = False
        if "glossary_ids" in data:
            data.pop("glossary_ids", None)
            changed = True
        sources = data.get("sources")
        if isinstance(sources, dict):
            for key in ("glossary_ids", "knowledge_ids", "dbsphere_ids"):
                if key in sources:
                    sources.pop(key, None)
                    changed = True
            # sources 가 비면 통째로 제거
            if not sources:
                data.pop("sources", None)
                changed = True
            else:
                data["sources"] = sources

        if changed:
            new_json = json.dumps(data, ensure_ascii=False)
            conn.execute(
                sa.text("UPDATE knowledge_graph SET data = :d WHERE id = :id"),
                {"d": new_json, "id": row_id},
            )


def downgrade() -> None:
    # Forward-only — legacy 데이터는 복원 불가.
    pass
