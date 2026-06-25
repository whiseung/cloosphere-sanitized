"""AGE dual-write 공통 헬퍼.

모든 sync 모듈(glossary, dbsphere, dimension, kb)이 공유하는
AGEService wrapper 함수. AGE 미설치/실패 시 graceful fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import EdgeSource

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def get_age_service(kg_id: str):
    """AGEService 인스턴스를 반환. AGE 미설치 시 None."""
    try:
        from extension_modules.knowledge_graph.age_service import AGEService

        svc = AGEService(kg_id)
        if not svc.graph_exists():
            svc.ensure_graph()
        return svc
    except Exception as e:
        log.warning(f"[age_helpers] AGE not available, SQL-only mode: {e}")
        return None


def age_upsert_node(
    age,
    node_type: str,
    node_id: str,
    label: str,
    properties: dict,
    kg_id: Optional[str] = None,
) -> Optional[dict]:
    """AGE에 노드 upsert. 실패 시 WAL에 기록하고 None 반환."""
    try:
        props = {
            **properties,
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
        }
        return age.upsert_node(node_type, "node_id", node_id, props)
    except Exception as e:
        log.warning(f"[age_helpers] upsert_node failed ({node_id}): {e}")
        if kg_id:
            try:
                from open_webui.models.knowledge_graph import KnowledgeGraphs

                KnowledgeGraphs.add_age_pending(
                    kg_id,
                    "upsert_node",
                    {
                        "node_type": node_type,
                        "node_id": node_id,
                        "label": label,
                        "properties": properties,
                    },
                )
            except Exception:
                pass
        return None


def age_upsert_edge(
    age,
    edge_type: str,
    src_type: str,
    src_id: str,
    dst_type: str,
    dst_id: str,
    source: str = EdgeSource.GLOSSARY_SYNC,
    properties: Optional[dict] = None,
    kg_id: Optional[str] = None,
) -> Optional[dict]:
    """AGE에 엣지 upsert. 실패 시 WAL에 기록하고 None 반환."""
    try:
        props = {**(properties or {}), "source": source}
        return age.upsert_edge(
            src_label=src_type,
            src_match={"node_id": src_id},
            dst_label=dst_type,
            dst_match={"node_id": dst_id},
            edge_label=edge_type,
            properties=props,
        )
    except Exception as e:
        log.warning(f"[age_helpers] upsert_edge failed ({src_id}->{dst_id}): {e}")
        if kg_id:
            try:
                from open_webui.models.knowledge_graph import KnowledgeGraphs

                KnowledgeGraphs.add_age_pending(
                    kg_id,
                    "upsert_edge",
                    {
                        "edge_type": edge_type,
                        "src_type": src_type,
                        "src_id": src_id,
                        "dst_type": dst_type,
                        "dst_id": dst_id,
                        "source": source,
                        "properties": properties,
                    },
                )
            except Exception:
                pass
        return None


def age_bulk_upsert_nodes(
    age,
    node_type: str,
    items: list[dict],
    kg_id: Optional[str] = None,
) -> int:
    """AGE 노드 여러 개를 UNWIND 로 한 번에 upsert.

    items: ``[{"node_id": ..., "label": ..., "properties": {...}}, ...]``
        properties 는 scalar + nested dict/list 모두 허용.

    반환: 처리된 item 수. 실패 chunk 는 개별 ``age_upsert_node`` 경로로
    fallback 해 WAL 기록을 보장.
    """
    if age is None or not items:
        return 0
    payload = []
    for it in items:
        node_id = it.get("node_id")
        if not node_id:
            continue
        props = {
            **(it.get("properties") or {}),
            "node_id": node_id,
            "node_type": node_type,
            "label": it.get("label") or node_id,
        }
        payload.append(props)
    if not payload:
        return 0
    try:
        return age.bulk_upsert_nodes(node_type, "node_id", payload)
    except Exception as e:
        log.warning(
            f"[age_helpers] bulk_upsert_nodes({node_type}) failed, "
            f"falling back to per-item: {e}"
        )
        ok = 0
        for it in items:
            r = age_upsert_node(
                age,
                node_type,
                it["node_id"],
                it.get("label") or it["node_id"],
                it.get("properties") or {},
                kg_id=kg_id,
            )
            if r is not None:
                ok += 1
        return ok


def age_bulk_upsert_edges(
    age,
    edge_type: str,
    src_type: str,
    dst_type: str,
    items: list[dict],
    source: str = EdgeSource.GLOSSARY_SYNC,
    kg_id: Optional[str] = None,
) -> int:
    """AGE 엣지 여러 개를 UNWIND + MATCH + MERGE 로 한 번에 upsert.

    items: ``[{"src_id": ..., "dst_id": ..., "properties": {...}}, ...]``
        ``source`` 는 자동으로 properties 에 추가된다.

    반환: 처리된 item 수. 실패 시 개별 ``age_upsert_edge`` 로 fallback.
    """
    if age is None or not items:
        return 0
    payload = []
    for it in items:
        src_id = it.get("src_id")
        dst_id = it.get("dst_id")
        if not src_id or not dst_id or src_id == dst_id:
            continue
        props = {**(it.get("properties") or {}), "source": source}
        payload.append(
            {
                "src_node_id": src_id,
                "dst_node_id": dst_id,
                "props": props,
            }
        )
    if not payload:
        return 0
    try:
        return age.bulk_upsert_edges(
            src_label=src_type,
            dst_label=dst_type,
            edge_label=edge_type,
            items=payload,
        )
    except Exception as e:
        log.warning(
            f"[age_helpers] bulk_upsert_edges({edge_type}) failed, "
            f"falling back to per-item: {e}"
        )
        ok = 0
        for it in items:
            r = age_upsert_edge(
                age,
                edge_type,
                src_type,
                it["src_id"],
                dst_type,
                it["dst_id"],
                source=source,
                properties=it.get("properties"),
                kg_id=kg_id,
            )
            if r is not None:
                ok += 1
        return ok


def age_cleanup(age, source_key: str, source_value: Any) -> int:
    """AGE에서 특정 source 속성 값을 가진 노드 전체 삭제."""
    try:
        deleted = age.delete_nodes_by_property(None, source_key, source_value)
        log.info(
            f"[age_helpers] cleanup: {deleted} nodes deleted ({source_key}={source_value})"
        )
        return deleted
    except Exception as e:
        log.warning(f"[age_helpers] cleanup failed: {e}")
        return 0
