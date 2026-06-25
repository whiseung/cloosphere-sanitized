"""KG Phase 2 — KB 계층 노드(컨테이너/문서) upsert 헬퍼.

`kb_sync.match_kb_file_via_glossary`, `sync_kb_to_kg`, `kb_chunk_worker`,
`routers/knowledge_graph._extract_kb_via_queue` 에서 동일한 규칙으로
KB / document 노드와 containment 엣지를 만든다. 결정적 ID → 병렬 fan-out
에서 idempotent.

구성:
- `ensure_kb_container_node` — KB 인스턴스 노드 (KG 당 1회, 자동 dedup)
- `ensure_document_node` — KB 파일 노드 + KB→doc containment 엣지
- `upsert_kb_documents_hierarchy` — 청크 리스트 받아서 KB/document 계층
  전체 upsert (queue 경로에서 publish 전 호출)
- `add_mentions_edge` — DOCUMENT → term 매칭 엣지 (KB 필터 결과 기반)
- `add_extracted_from_edge` — doc_entity → DOCUMENT provenance 엣지

KG 는 의미 그래프이고 청크 단위 검색은 KB 벡터스토어가 file_id 로 hit
후 자체 처리한다 — CHUNK 노드는 만들지 않는다.
"""

from __future__ import annotations

import logging
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.files import Files
from open_webui.models.knowledge_graph import (
    EdgeSource,
    EdgeType,
    KnowledgeGraphs,
    NodeType,
)

from ._age_helpers import (
    age_bulk_upsert_edges,
    age_bulk_upsert_nodes,
    age_upsert_edge,
    age_upsert_node,
)
from ._node_ids import (
    document_node_id,
    knowledge_base_node_id,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def ensure_kb_container_node(
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    age,
    kb_name: Optional[str] = None,
    kb_description: Optional[str] = None,
) -> str:
    """KB 컨테이너 노드를 upsert 하고 node_id 를 반환. 결정적 id → idempotent."""
    kb_nid = knowledge_base_node_id(kg_id, knowledge_id)
    label = kb_name or knowledge_id
    props = {"knowledge_id": knowledge_id, "description": kb_description or ""}
    KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=kb_nid,
        node_type=NodeType.KNOWLEDGE_BASE,
        label=label,
        properties=props,
        source_ref={"kind": "kb", "knowledge_id": knowledge_id},
    )
    if age:
        age_upsert_node(
            age,
            NodeType.KNOWLEDGE_BASE,
            kb_nid,
            label,
            {**props, "source_kind": "kb", "source_id": knowledge_id},
            kg_id=kg_id,
        )
    return kb_nid


def ensure_document_node(
    kg_id: str,
    knowledge_id: str,
    file_id: str,
    user_id: str,
    age,
    kb_nid: Optional[str] = None,
) -> str:
    """KB 파일(문서) 노드 + KB→doc contains_document 엣지를 upsert.

    파일명은 Files.get_file_by_id 로 조회. 파일 레코드가 없으면 file_id 를 label 로.
    """
    doc_nid = document_node_id(kg_id, knowledge_id, file_id)
    if kb_nid is None:
        kb_nid = knowledge_base_node_id(kg_id, knowledge_id)

    file_name = file_id
    content_type = None
    try:
        file_row = Files.get_file_by_id(file_id)
        if file_row:
            file_name = file_row.filename or file_id
            content_type = (file_row.meta or {}).get("content_type")
    except Exception as e:
        log.warning(f"[kb_hierarchy] failed to fetch file {file_id[:8]}: {e}")

    props = {
        "kb_id": knowledge_id,
        "file_id": file_id,
        "content_type": content_type or "",
    }
    KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=doc_nid,
        node_type=NodeType.DOCUMENT,
        label=file_name,
        properties=props,
        source_ref={
            "kind": "kb",
            "knowledge_id": knowledge_id,
            "file_id": file_id,
        },
    )
    if age:
        age_upsert_node(
            age,
            NodeType.DOCUMENT,
            doc_nid,
            file_name,
            {**props, "source_kind": "kb", "source_id": knowledge_id},
            kg_id=kg_id,
        )

    KnowledgeGraphs.upsert_edge(
        kg_id=kg_id,
        user_id=user_id,
        src_id=kb_nid,
        dst_id=doc_nid,
        edge_type=EdgeType.CONTAINS_DOCUMENT,
        source=EdgeSource.KB_MATCH,
    )
    if age:
        age_upsert_edge(
            age,
            EdgeType.CONTAINS_DOCUMENT,
            NodeType.KNOWLEDGE_BASE,
            kb_nid,
            NodeType.DOCUMENT,
            doc_nid,
            source=EdgeSource.KB_MATCH,
            kg_id=kg_id,
        )

    return doc_nid


def upsert_kb_documents_hierarchy(
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    chunks: list,
    age,
) -> dict:
    """KB 컨테이너 + document(파일별 dedup) 노드를 일괄 upsert.

    Queue 경로에서 publish 전에 호출해, worker 가 나중에 ``extracted_from``
    엣지를 붙일 때 참조할 DOCUMENT 노드를 미리 만들어둔다 (provenance_node_id
    로 사용).

    Args:
        kg_id: 대상 KG
        knowledge_id: 대상 KB (= 벡터 스토어 collection 값)
        user_id: 노드 owner
        chunks: DocumentItem 리스트 (.metadata.file_id 가정 — file_id 추출용)
        age: AGE 서비스 핸들 (없으면 None)

    Returns:
        {"kb_container": str, "documents": int, "skipped_no_file_id": int}

    Idempotent.
    """
    # Lazy import — routers 에서 호출 시 순환 임포트 방지
    from open_webui.models.knowledge import Knowledges

    try:
        kb_row = Knowledges.get_knowledge_by_id(knowledge_id)
    except Exception as e:
        log.warning(
            f"[kb_hierarchy] get_knowledge_by_id failed for {knowledge_id[:8]}: {e}"
        )
        kb_row = None

    kb_nid = ensure_kb_container_node(
        kg_id=kg_id,
        knowledge_id=knowledge_id,
        user_id=user_id,
        age=age,
        kb_name=getattr(kb_row, "name", None) if kb_row else None,
        kb_description=getattr(kb_row, "description", None) if kb_row else None,
    )

    doc_nid_by_file: dict[str, str] = {}
    skipped_no_file_id = 0

    for ch in chunks:
        meta = ch.metadata if isinstance(ch.metadata, dict) else {}
        file_id = meta.get("file_id")
        if not file_id:
            skipped_no_file_id += 1
            continue
        if file_id in doc_nid_by_file:
            continue
        doc_nid_by_file[file_id] = ensure_document_node(
            kg_id=kg_id,
            knowledge_id=knowledge_id,
            file_id=file_id,
            user_id=user_id,
            age=age,
            kb_nid=kb_nid,
        )

    return {
        "kb_container": kb_nid,
        "documents": len(doc_nid_by_file),
        "skipped_no_file_id": skipped_no_file_id,
    }


def add_mentions_edge(
    kg_id: str,
    user_id: str,
    doc_nid: str,
    term_node_id: str,
    age,
    properties: Optional[dict] = None,
) -> None:
    """document → term MENTIONS 엣지 upsert (KB 필터 결과 기반)."""
    KnowledgeGraphs.upsert_edge(
        kg_id=kg_id,
        user_id=user_id,
        src_id=doc_nid,
        dst_id=term_node_id,
        edge_type=EdgeType.MENTIONS,
        source=EdgeSource.KB_MATCH,
        properties=properties,
    )
    if age:
        age_upsert_edge(
            age,
            EdgeType.MENTIONS,
            NodeType.DOCUMENT,
            doc_nid,
            NodeType.TERM,
            term_node_id,
            source=EdgeSource.KB_MATCH,
            properties=properties,
            kg_id=kg_id,
        )


def bulk_ensure_documents_and_mentions(
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    doc_entity_map: dict,
    age,
    kb_nid: str,
) -> dict:
    """Phase 2 KB 단위 — DOCUMENT/MENTIONS 를 배치로 upsert.

    doc_entity_map: ``{file_id: [{"entity_node_id", "entity_label", "category"}, ...]}``

    내부 동작:
      1. Files.get_files_by_ids 로 파일 메타 일괄 조회 (파일명/content_type)
      2. DOCUMENT 노드 specs 수집 → SQL bulk_upsert_nodes + AGE bulk_upsert_nodes
      3. CONTAINS_DOCUMENT 엣지 specs 수집 → SQL/AGE bulk_upsert_edges
      4. MENTIONS 엣지 (document → term) 배치

    KB 컨테이너 노드는 상위에서 ``ensure_kb_container_node`` 로 upsert 후
    ``kb_nid`` 를 주입받는다. 트랜잭션 한 번으로 수백 파일을 처리하므로 fan-in
    race 안전성은 상위(fan-out 부모)가 KB 단위로 job 을 분할해 보장.

    Returns: ``{"documents": N, "mentions": M, "contains_edges": C}``.
    """
    if not doc_entity_map:
        return {
            "documents": 0,
            "mentions": 0,
            "contains_edges": 0,
        }

    file_ids = list(doc_entity_map.keys())

    # 1. 파일 메타 일괄 조회
    file_meta_by_id: dict[str, dict] = {}
    try:
        rows = Files.get_files_by_ids(file_ids)
    except Exception as e:
        log.warning(f"[kb_hierarchy bulk] get_files_by_ids failed: {e}")
        rows = []
    for r in rows or []:
        file_meta_by_id[r.id] = {
            "filename": r.filename or r.id,
            "content_type": (r.meta or {}).get("content_type") or "",
        }

    doc_node_specs: list[dict] = []
    doc_node_age_items: list[dict] = []
    contains_sql_specs: list[dict] = []
    contains_age_items: list[dict] = []

    mentions_sql: list[dict] = []
    mentions_age: list[dict] = []

    for file_id, matches in doc_entity_map.items():
        meta = file_meta_by_id.get(file_id) or {}
        file_name = meta.get("filename") or file_id
        content_type = meta.get("content_type") or ""

        doc_nid = document_node_id(kg_id, knowledge_id, file_id)

        props = {
            "kb_id": knowledge_id,
            "file_id": file_id,
            "content_type": content_type,
        }
        source_ref = {
            "kind": "kb",
            "knowledge_id": knowledge_id,
            "file_id": file_id,
        }

        doc_node_specs.append(
            {
                "id": doc_nid,
                "kg_id": kg_id,
                "user_id": user_id,
                "node_type": NodeType.DOCUMENT,
                "label": file_name,
                "properties": props,
                "source_ref": source_ref,
            }
        )
        doc_node_age_items.append(
            {
                "node_id": doc_nid,
                "label": file_name,
                "properties": {
                    **props,
                    "source_kind": "kb",
                    "source_id": knowledge_id,
                },
            }
        )

        contains_sql_specs.append(
            {
                "kg_id": kg_id,
                "user_id": user_id,
                "src_id": kb_nid,
                "dst_id": doc_nid,
                "edge_type": EdgeType.CONTAINS_DOCUMENT,
                "source": EdgeSource.KB_MATCH,
            }
        )
        contains_age_items.append(
            {"src_id": kb_nid, "dst_id": doc_nid, "properties": None}
        )

        for m in matches or []:
            term_nid = m.get("entity_node_id")
            if not term_nid:
                continue
            category = m.get("category")
            props_edge = {"category": category} if category else None
            mentions_sql.append(
                {
                    "kg_id": kg_id,
                    "user_id": user_id,
                    "src_id": doc_nid,
                    "dst_id": term_nid,
                    "edge_type": EdgeType.MENTIONS,
                    "source": EdgeSource.KB_MATCH,
                    "properties": props_edge,
                }
            )
            mentions_age.append(
                {
                    "src_id": doc_nid,
                    "dst_id": term_nid,
                    "properties": props_edge,
                }
            )

    stats = {
        "documents": 0,
        "mentions": 0,
        "contains_edges": 0,
    }

    # SQL 배치 — 노드 먼저, 엣지는 뒤
    if doc_node_specs:
        stats["documents"] = KnowledgeGraphs.bulk_upsert_nodes(doc_node_specs)
    if contains_sql_specs:
        stats["contains_edges"] = KnowledgeGraphs.bulk_upsert_edges(contains_sql_specs)
    if mentions_sql:
        stats["mentions"] = KnowledgeGraphs.bulk_upsert_edges(mentions_sql)

    # AGE — 노드 먼저, 엣지는 뒤 (MATCH 성공 보장)
    if age:
        if doc_node_age_items:
            age_bulk_upsert_nodes(
                age, NodeType.DOCUMENT, doc_node_age_items, kg_id=kg_id
            )
        if contains_age_items:
            age_bulk_upsert_edges(
                age,
                EdgeType.CONTAINS_DOCUMENT,
                NodeType.KNOWLEDGE_BASE,
                NodeType.DOCUMENT,
                contains_age_items,
                source=EdgeSource.KB_MATCH,
                kg_id=kg_id,
            )
        if mentions_age:
            age_bulk_upsert_edges(
                age,
                EdgeType.MENTIONS,
                NodeType.DOCUMENT,
                NodeType.TERM,
                mentions_age,
                source=EdgeSource.KB_MATCH,
                kg_id=kg_id,
            )

    return stats


def bulk_upsert_filter_attrs(
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    filter_attr_map: dict,
    age,
) -> dict:
    """KB 필터 값 → doc_attr 노드 + document --has_{slot}--> attr 엣지 배치 upsert.

    filter_attr_map (from ``kb_sync.build_filter_attr_map``):
        ``{file_id: [{node_id, label, slot, edge_type, is_term, category}, ...]}``

    동작:
    - ``is_term=False`` 인 항목: DOC_ENTITY 노드를 slot namespace 로 생성
    - ``is_term=True``: glossary term 노드 재사용 (이미 존재 — 여기서 노드 생성 X)
    - edge_type 별로 SQL/AGE 엣지 배치. 한 엣지 타입당 SQL 1회, AGE 1회.
    - 문서 노드 (DOCUMENT) 는 이미 ``bulk_ensure_documents_and_mentions`` 에서 생성됨 (전제).

    Returns: ``{"attr_nodes": N, "attr_edges": E, "edge_types": [...]}``.
    """
    if not filter_attr_map:
        return {"attr_nodes": 0, "attr_edges": 0, "edge_types": []}

    # 1) 노드 specs (doc_attr 만 — is_term 은 기존 term 노드 재사용)
    attr_node_specs: list[dict] = []
    attr_node_age_items: list[dict] = []
    seen_attr_node_ids: set[str] = set()

    # 2) edge_type 별 그룹핑 (SQL/AGE 각각 배치)
    edges_by_type_sql: dict[str, list[dict]] = {}
    edges_by_type_age: dict[str, list[dict]] = {}

    for file_id, rows in filter_attr_map.items():
        doc_nid = document_node_id(kg_id, knowledge_id, file_id)
        for row in rows or []:
            node_id = row.get("node_id")
            edge_type = row.get("edge_type")
            label = row.get("label") or ""
            slot = row.get("slot") or ""
            if not node_id or not edge_type:
                continue

            if not row.get("is_term") and node_id not in seen_attr_node_ids:
                seen_attr_node_ids.add(node_id)
                props = {"slot": slot, "source_kind": "filter"}
                attr_node_specs.append(
                    {
                        "id": node_id,
                        "kg_id": kg_id,
                        "user_id": user_id,
                        "node_type": NodeType.DOC_ATTR,
                        "label": label,
                        "properties": props,
                        "source_ref": {
                            "kind": "kb",
                            "knowledge_id": knowledge_id,
                            "slot": slot,
                        },
                    }
                )
                attr_node_age_items.append(
                    {
                        "node_id": node_id,
                        "label": label,
                        "properties": {
                            **props,
                            "source_kind": "kb",
                            "source_id": knowledge_id,
                        },
                    }
                )

            edge_props = {"slot": slot}
            if row.get("category"):
                edge_props["category"] = row["category"]
            edges_by_type_sql.setdefault(edge_type, []).append(
                {
                    "kg_id": kg_id,
                    "user_id": user_id,
                    "src_id": doc_nid,
                    "dst_id": node_id,
                    "edge_type": edge_type,
                    "source": EdgeSource.KB_MATCH,
                    "properties": edge_props,
                }
            )
            edges_by_type_age.setdefault(edge_type, []).append(
                {"src_id": doc_nid, "dst_id": node_id, "properties": edge_props}
            )

    # SQL 배치 — 노드 먼저, 엣지는 뒤
    attr_nodes_upserted = 0
    if attr_node_specs:
        attr_nodes_upserted = KnowledgeGraphs.bulk_upsert_nodes(attr_node_specs)

    attr_edges_upserted = 0
    for et, specs in edges_by_type_sql.items():
        try:
            attr_edges_upserted += KnowledgeGraphs.bulk_upsert_edges(specs)
        except Exception as e:
            log.warning(f"[filter→attr bulk] edge bulk failed ({et}): {e}")

    # AGE 배치 — 노드 먼저, 엣지는 뒤. 엣지 dst 는 필터 기원이므로 DOC_ATTR,
    # glossary term 재사용 경우도 포함되지만 AGE 는 라벨 기반 MATCH 이므로
    # src=document, dst=doc_attr 로 선언. term 재사용 엣지는 SQL 쪽에서만
    # 기록되고 AGE 에서는 라벨 불일치로 drop — 이 부분은 후속 개선 여지.
    if age:
        if attr_node_age_items:
            age_bulk_upsert_nodes(
                age, NodeType.DOC_ATTR, attr_node_age_items, kg_id=kg_id
            )
        for et, items in edges_by_type_age.items():
            try:
                age_bulk_upsert_edges(
                    age,
                    et,
                    NodeType.DOCUMENT,
                    NodeType.DOC_ATTR,
                    items,
                    source=EdgeSource.KB_MATCH,
                    kg_id=kg_id,
                )
            except Exception as e:
                log.warning(f"[filter→attr bulk] AGE edge failed ({et}): {e}")

    return {
        "attr_nodes": attr_nodes_upserted,
        "attr_edges": attr_edges_upserted,
        "edge_types": sorted(edges_by_type_sql.keys()),
    }


def add_extracted_from_edge(
    kg_id: str,
    user_id: str,
    doc_entity_node_id: str,
    doc_nid: str,
    age,
) -> None:
    """doc_entity → DOCUMENT EXTRACTED_FROM 엣지 upsert (provenance)."""
    KnowledgeGraphs.upsert_edge(
        kg_id=kg_id,
        user_id=user_id,
        src_id=doc_entity_node_id,
        dst_id=doc_nid,
        edge_type=EdgeType.EXTRACTED_FROM,
        source=EdgeSource.LLM_EXTRACT,
    )
    if age:
        age_upsert_edge(
            age,
            EdgeType.EXTRACTED_FROM,
            NodeType.DOC_ENTITY,
            doc_entity_node_id,
            NodeType.DOCUMENT,
            doc_nid,
            source=EdgeSource.LLM_EXTRACT,
            kg_id=kg_id,
        )
