"""remove doc_type filter type and DOC_TYPE nodes/edges

Revision ID: b1c2d3e4f5a6
Revises: 686ce6f4803f
Create Date: 2026-04-20

doc_type 개념 제거 후속 데이터 정리:

1. Knowledge.meta.filter_schema 에서 type=="doc_type" 항목 제거
2. Knowledge.data.file_metadata 에서 제거된 doc_type slot 키 값 제거
3. kg_node 에서 node_type=="doc_type" 행 삭제
4. kg_edge 에서 edge_type=="has_doc_type" 행 삭제

AGE(DOC_TYPE 라벨 노드 / HAS_DOC_TYPE 라벨 엣지) 는 SQL 테이블의 보조 저장소
이므로 여기서는 건드리지 않는다. KG 재동기화/리빌드 시 정리된다.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "686ce6f4803f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_obj(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1+2. knowledge.meta.filter_schema / data.file_metadata 정리 ──
    rows = conn.execute(sa.text("SELECT id, data, meta FROM knowledge")).fetchall()

    updated = 0
    for row in rows:
        kid = row[0]
        data = _as_obj(row[1]) or {}
        meta = _as_obj(row[2]) or {}

        filter_schema = meta.get("filter_schema") or []
        if not isinstance(filter_schema, list):
            continue

        doc_type_slots = [
            f.get("slot")
            for f in filter_schema
            if isinstance(f, dict) and f.get("type") == "doc_type" and f.get("slot")
        ]
        if not doc_type_slots:
            continue

        # filter_schema 재구성 — type=="doc_type" 항목만 제거
        new_schema = [
            f
            for f in filter_schema
            if not (isinstance(f, dict) and f.get("type") == "doc_type")
        ]
        meta["filter_schema"] = new_schema

        # file_metadata 에서 해당 slot 키 제거
        file_metadata = data.get("file_metadata") or {}
        if isinstance(file_metadata, dict):
            for fid, fm in list(file_metadata.items()):
                if not isinstance(fm, dict):
                    continue
                for slot in doc_type_slots:
                    fm.pop(slot, None)
            data["file_metadata"] = file_metadata

        conn.execute(
            sa.text("UPDATE knowledge SET data = :data, meta = :meta WHERE id = :id"),
            {
                "id": kid,
                "data": json.dumps(data, ensure_ascii=False),
                "meta": json.dumps(meta, ensure_ascii=False),
            },
        )
        updated += 1

    print(f"[remove_doc_type] knowledge rows updated: {updated}")

    # ── 3. kg_edge 에서 has_doc_type 엣지 삭제 (노드 삭제 전에 먼저) ──
    edge_result = conn.execute(
        sa.text("DELETE FROM kg_edge WHERE edge_type = 'has_doc_type'")
    )
    print(f"[remove_doc_type] kg_edge has_doc_type deleted: {edge_result.rowcount}")

    # ── 4. kg_node 에서 doc_type 노드 삭제 (+ 혹시 src/dst 로 남은 엣지도 정리) ──
    doc_type_ids = [
        r[0]
        for r in conn.execute(
            sa.text("SELECT id FROM kg_node WHERE node_type = 'doc_type'")
        ).fetchall()
    ]
    if doc_type_ids:
        stmt_edge = sa.text(
            "DELETE FROM kg_edge WHERE src_id IN :ids OR dst_id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True))
        conn.execute(stmt_edge, {"ids": doc_type_ids})
        stmt_node = sa.text("DELETE FROM kg_node WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        )
        conn.execute(stmt_node, {"ids": doc_type_ids})
    print(f"[remove_doc_type] kg_node doc_type deleted: {len(doc_type_ids)}")


def downgrade() -> None:
    # 데이터 삭제 마이그레이션은 되돌릴 수 없다 (원본 값 미보존).
    pass
