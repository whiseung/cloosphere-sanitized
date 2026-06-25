"""Glossary → KG 동기화.

각 Glossary entry를 `term` 노드 1개로, synonyms 배열을 `synonym_of` 엣지로
변환한다. category가 있으면 `concept` 노드를 만들고 `broader_than` 엣지로
연결한다.

Dual-write: SQL 테이블 + AGE 그래프. AGE 실패 시 SQL만으로 정상 진행.
"""

from __future__ import annotations

import logging
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.glossary import Glossaries
from open_webui.models.knowledge_graph import (
    EdgeSource,
    EdgeType,
    KnowledgeGraphs,
    NodeType,
    make_node_id,
)

from ._age_helpers import age_cleanup, age_upsert_edge, age_upsert_node, get_age_service
from ._node_ids import glossary_container_node_id

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def _term_node_id(kg_id: str, glossary_id: str, entry_id: str) -> str:
    return make_node_id(kg_id, "glossary", glossary_id, "term", entry_id)


def _concept_node_id(kg_id: str, glossary_id: str, category: str) -> str:
    return make_node_id(kg_id, "glossary", glossary_id, "concept", category)


def _synonym_node_id(kg_id: str, glossary_id: str, entry_id: str, synonym: str) -> str:
    return make_node_id(kg_id, "glossary", glossary_id, "syn", entry_id, synonym)


def _column_node_id(
    kg_id: str, dbsphere_id: str, table_name: str, column_name: str
) -> str:
    """dbsphere_sync가 만드는 COLUMN 노드와 동일한 ID 규칙.

    용어집 sync에서 CONCEPT → COLUMN 엣지를 걸 때 타겟 노드 ID를 결정적으로
    계산해야 하므로 여기서 재구현한다. 두 모듈 모두 `make_node_id(kg_id,
    "dbsphere", dbsphere_id, "column", table, column)` 규칙을 따른다.
    """
    return make_node_id(
        kg_id, "dbsphere", dbsphere_id, "column", table_name, column_name
    )


def get_referenced_dbsphere_ids(glossary_id: str) -> list[str]:
    """용어집의 `meta.extraction_sources` 에서 참조되는 dbsphere id 목록.

    카테고리 추출을 통해 각 카테고리는 (dbsphere_id, table, column) 하나에
    매핑된다. 여러 카테고리가 같은 DB를 가리키면 중복 제거된다. KG sync
    경로에서 용어집 → DB 자동 동반 sync 에 사용된다.
    """
    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        return []
    sources = (glossary.meta or {}).get("extraction_sources") or {}
    ids: list[str] = []
    seen: set[str] = set()
    for src in sources.values():
        if not isinstance(src, dict):
            continue
        db_id = src.get("dbsphere_id")
        if db_id and db_id not in seen:
            ids.append(db_id)
            seen.add(db_id)
    return ids


def cleanup_glossary_nodes(kg_id: str, glossary_id: str) -> None:
    """용어집 소스의 기존 노드/엣지를 모두 제거.

    Fan-out 패턴에서 부모 태스크가 *자식을 publish 하기 전에 한 번만* 호출한다.
    자식들이 병렬로 같은 cleanup 을 돌면 서로가 만든 노드를 지울 수 있어 위험.
    """
    KnowledgeGraphs.delete_nodes_by_source(kg_id, "glossary", glossary_id)
    age = get_age_service(kg_id)
    if age:
        age_cleanup(age, "source_id", glossary_id)


def _upsert_concept_node(
    kg_id: str,
    glossary_id: str,
    user_id: str,
    category: str,
    extraction_sources: dict,
    age,
) -> tuple[str, int, int]:
    """CONCEPT 노드 1개 + (extraction_sources 있으면) MAPS_TO 엣지 upsert.

    Returns (concept_node_id, nodes_created_delta, edges_created_delta).
    결정적 id 라 여러 워커가 동시 호출해도 idempotent.
    """
    cnode_id = _concept_node_id(kg_id, glossary_id, category)
    gloss_nid = glossary_container_node_id(kg_id, glossary_id)
    nodes_delta = 0
    edges_delta = 0
    result = KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=cnode_id,
        node_type=NodeType.CONCEPT,
        label=category,
        properties={"category": category},
        source_ref={
            "kind": "glossary",
            "glossary_id": glossary_id,
            "field": "category",
        },
    )
    if age:
        age_upsert_node(
            age,
            NodeType.CONCEPT,
            cnode_id,
            category,
            {
                "category": category,
                "source_kind": "glossary",
                "source_id": glossary_id,
            },
            kg_id=kg_id,
        )
    if result:
        nodes_delta += 1

    # contains_concept: glossary → concept (Phase 2 계층)
    cc_edge = KnowledgeGraphs.upsert_edge(
        kg_id=kg_id,
        user_id=user_id,
        src_id=gloss_nid,
        dst_id=cnode_id,
        edge_type=EdgeType.CONTAINS_CONCEPT,
        source=EdgeSource.GLOSSARY_SYNC,
    )
    if age:
        age_upsert_edge(
            age,
            EdgeType.CONTAINS_CONCEPT,
            NodeType.GLOSSARY,
            gloss_nid,
            NodeType.CONCEPT,
            cnode_id,
            source=EdgeSource.GLOSSARY_SYNC,
            kg_id=kg_id,
        )
    if cc_edge:
        edges_delta += 1

    src_info = extraction_sources.get(category)
    if isinstance(src_info, dict):
        db_id = src_info.get("dbsphere_id")
        table = src_info.get("table")
        col = src_info.get("column")
        if db_id and table and col:
            col_nid = _column_node_id(kg_id, db_id, table, col)
            map_edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=cnode_id,
                dst_id=col_nid,
                edge_type=EdgeType.MAPS_TO,
                source=EdgeSource.GLOSSARY_SYNC,
                properties={
                    "dbsphere_id": db_id,
                    "table": table,
                    "column": col,
                },
            )
            if age:
                age_upsert_edge(
                    age,
                    EdgeType.MAPS_TO,
                    NodeType.CONCEPT,
                    cnode_id,
                    NodeType.COLUMN,
                    col_nid,
                    source=EdgeSource.GLOSSARY_SYNC,
                    kg_id=kg_id,
                )
            if map_edge:
                edges_delta += 1

    return cnode_id, nodes_delta, edges_delta


def _upsert_entry(
    kg_id: str,
    glossary_id: str,
    user_id: str,
    entry: dict,
    concept_node_ids: dict[str, str],
    extraction_sources: dict,
    age,
) -> tuple[int, int]:
    """단일 entry 의 TERM/SYNONYM 노드 + BROADER_THAN/SYNONYM_OF 엣지 upsert.

    이 entry 의 카테고리에 대한 CONCEPT 노드를 concept_node_ids 에서 찾는다.
    없으면 자동으로 upsert 한 뒤 캐싱한다 (청크 단위 호출에서 사용).
    Returns (nodes_delta, edges_delta).
    """
    entry_id = entry.get("id")
    term = (entry.get("term") or "").strip()
    if not entry_id or not term:
        return 0, 0

    nodes_delta = 0
    edges_delta = 0

    term_nid = _term_node_id(kg_id, glossary_id, entry_id)
    term_props = {
        "description": entry.get("description") or "",
        "example": entry.get("example") or "",
        "category": entry.get("category"),
    }
    node = KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=term_nid,
        node_type=NodeType.TERM,
        label=term,
        properties=term_props,
        source_ref={
            "kind": "glossary",
            "glossary_id": glossary_id,
            "entry_id": entry_id,
        },
    )
    if age:
        age_upsert_node(
            age,
            NodeType.TERM,
            term_nid,
            term,
            {
                **term_props,
                "source_kind": "glossary",
                "source_id": glossary_id,
                "entry_id": entry_id,
            },
            kg_id=kg_id,
        )
    if not node:
        return 0, 0
    nodes_delta += 1

    # contains_term: glossary → term (Phase 2 계층, concept 우회 경로)
    gloss_nid = glossary_container_node_id(kg_id, glossary_id)
    ct_edge = KnowledgeGraphs.upsert_edge(
        kg_id=kg_id,
        user_id=user_id,
        src_id=gloss_nid,
        dst_id=term_nid,
        edge_type=EdgeType.CONTAINS_TERM,
        source=EdgeSource.GLOSSARY_SYNC,
    )
    if age:
        age_upsert_edge(
            age,
            EdgeType.CONTAINS_TERM,
            NodeType.GLOSSARY,
            gloss_nid,
            NodeType.TERM,
            term_nid,
            source=EdgeSource.GLOSSARY_SYNC,
            kg_id=kg_id,
        )
    if ct_edge:
        edges_delta += 1

    category = entry.get("category")
    if category:
        if category not in concept_node_ids:
            cnode_id, cn_delta, ce_delta = _upsert_concept_node(
                kg_id, glossary_id, user_id, category, extraction_sources, age
            )
            concept_node_ids[category] = cnode_id
            nodes_delta += cn_delta
            edges_delta += ce_delta
        edge = KnowledgeGraphs.upsert_edge(
            kg_id=kg_id,
            user_id=user_id,
            src_id=concept_node_ids[category],
            dst_id=term_nid,
            edge_type=EdgeType.BROADER_THAN,
            source=EdgeSource.GLOSSARY_SYNC,
        )
        if age:
            age_upsert_edge(
                age,
                EdgeType.BROADER_THAN,
                NodeType.CONCEPT,
                concept_node_ids[category],
                NodeType.TERM,
                term_nid,
                source=EdgeSource.GLOSSARY_SYNC,
                kg_id=kg_id,
            )
        if edge:
            edges_delta += 1

        # contains_term: concept → term (Phase 2 계층)
        cct_edge = KnowledgeGraphs.upsert_edge(
            kg_id=kg_id,
            user_id=user_id,
            src_id=concept_node_ids[category],
            dst_id=term_nid,
            edge_type=EdgeType.CONTAINS_TERM,
            source=EdgeSource.GLOSSARY_SYNC,
        )
        if age:
            age_upsert_edge(
                age,
                EdgeType.CONTAINS_TERM,
                NodeType.CONCEPT,
                concept_node_ids[category],
                NodeType.TERM,
                term_nid,
                source=EdgeSource.GLOSSARY_SYNC,
                kg_id=kg_id,
            )
        if cct_edge:
            edges_delta += 1

    for syn in entry.get("synonyms") or []:
        syn_label = (syn or "").strip()
        if not syn_label:
            continue
        syn_nid = _synonym_node_id(kg_id, glossary_id, entry_id, syn_label)
        syn_node = KnowledgeGraphs.upsert_node(
            kg_id=kg_id,
            user_id=user_id,
            node_id=syn_nid,
            node_type=NodeType.TERM,
            label=syn_label,
            properties={"is_synonym_for": term},
            source_ref={
                "kind": "glossary",
                "glossary_id": glossary_id,
                "entry_id": entry_id,
                "field": "synonym",
            },
        )
        if age:
            age_upsert_node(
                age,
                NodeType.TERM,
                syn_nid,
                syn_label,
                {
                    "is_synonym_for": term,
                    "source_kind": "glossary",
                    "source_id": glossary_id,
                    "entry_id": entry_id,
                },
                kg_id=kg_id,
            )
        if not syn_node:
            continue
        nodes_delta += 1
        for src, dst in ((term_nid, syn_nid), (syn_nid, term_nid)):
            edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=src,
                dst_id=dst,
                edge_type=EdgeType.SYNONYM_OF,
                source=EdgeSource.GLOSSARY_SYNC,
            )
            if age:
                age_upsert_edge(
                    age,
                    EdgeType.SYNONYM_OF,
                    NodeType.TERM,
                    src,
                    NodeType.TERM,
                    dst,
                    source=EdgeSource.GLOSSARY_SYNC,
                    kg_id=kg_id,
                )
            if edge:
                edges_delta += 1

    return nodes_delta, edges_delta


def sync_glossary_entries_chunk(
    kg_id: str,
    glossary_id: str,
    user_id: str,
    entry_ids: list[str],
) -> dict:
    """지정된 entry_ids 만 upsert — fan-out 자식 워커가 호출.

    Cleanup 은 호출자(부모 태스크)가 미리 수행했다고 가정한다. 이 함수는
    오직 upsert 만 수행하므로 여러 청크 태스크가 병렬로 안전하게 돌 수 있다.
    concept 노드는 결정적 id 이므로 여러 청크가 같은 카테고리를 동시에
    upsert 해도 idempotent.
    """
    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        log.warning(f"Glossary not found: {glossary_id}")
        return {"nodes_created": 0, "edges_created": 0}

    all_entries: list[dict] = (glossary.data or {}).get("entries", []) or []
    extraction_sources: dict = (glossary.meta or {}).get("extraction_sources") or {}

    wanted = set(entry_ids or [])
    entries = [e for e in all_entries if e.get("id") in wanted]
    if not entries:
        return {"nodes_created": 0, "edges_created": 0}

    age = get_age_service(kg_id)
    nodes_created = 0
    edges_created = 0
    concept_node_ids: dict[str, str] = {}

    # ── 컨테이너: glossary 노드 (Phase 2 계층) ──
    # 결정적 id 이므로 fan-out 병렬 청크가 중복 호출해도 idempotent.
    gloss_nid = glossary_container_node_id(kg_id, glossary_id)
    gloss_props = {
        "glossary_id": glossary_id,
        "description": getattr(glossary, "description", None) or "",
    }
    gloss_label = getattr(glossary, "name", None) or glossary_id
    gloss_node = KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=gloss_nid,
        node_type=NodeType.GLOSSARY,
        label=gloss_label,
        properties=gloss_props,
        source_ref={"kind": "glossary", "glossary_id": glossary_id},
    )
    if age:
        age_upsert_node(
            age,
            NodeType.GLOSSARY,
            gloss_nid,
            gloss_label,
            {**gloss_props, "source_kind": "glossary", "source_id": glossary_id},
            kg_id=kg_id,
        )
    if gloss_node:
        nodes_created += 1

    for entry in entries:
        n, e = _upsert_entry(
            kg_id,
            glossary_id,
            user_id,
            entry,
            concept_node_ids,
            extraction_sources,
            age,
        )
        nodes_created += n
        edges_created += e

    return {
        "glossary_id": glossary_id,
        "entries_processed": len(entries),
        "nodes_created": nodes_created,
        "edges_created": edges_created,
    }


def sync_glossary_to_kg(kg_id: str, glossary_id: str, user_id: str) -> Optional[dict]:
    """단일 Glossary 전체를 KG 에 동기화 (inline 경로).

    내부적으로 cleanup 후 `sync_glossary_entries_chunk` 로 모든 entries 를
    upsert 한다. Fan-out 경로에서는 부모가 cleanup 을 수행하고 entries 를
    청크로 쪼개어 `sync_glossary_entries_chunk` 를 자식 워커에서 호출한다.
    """
    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        log.warning(f"Glossary not found: {glossary_id}")
        return None

    entries: list[dict] = (glossary.data or {}).get("entries", []) or []

    cleanup_glossary_nodes(kg_id, glossary_id)

    if not entries:
        log.info(f"Glossary {glossary_id} has no entries; skipping sync")
        return {"glossary_id": glossary_id, "nodes_created": 0, "edges_created": 0}

    entry_ids = [e.get("id") for e in entries if e.get("id")]
    result = sync_glossary_entries_chunk(kg_id, glossary_id, user_id, entry_ids)

    age = get_age_service(kg_id)
    log.info(
        f"Synced glossary {glossary_id} to KG {kg_id}: "
        f"{result.get('nodes_created', 0)} nodes, "
        f"{result.get('edges_created', 0)} edges"
        f" (AGE={'enabled' if age else 'disabled'})"
    )
    return {
        "glossary_id": glossary_id,
        "nodes_created": result.get("nodes_created", 0),
        "edges_created": result.get("edges_created", 0),
    }
