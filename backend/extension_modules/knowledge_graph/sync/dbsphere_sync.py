"""DbSphere → KG 동기화.

DbSphere의 스키마(테이블/컬럼)는 `dbsphere` 테이블의 `data` 필드가 아니라
search engine memory(`SearchEngineDbSphereMemory`)에 `DDLMemory`로 저장된다.
사용자가 미리 schema extraction을 돌려뒀어야 한다. 돌리지 않은 DbSphere는
빈 결과를 반환한다.

생성되는 노드:
- `table` 노드: 각 테이블 1개
- `column` 노드: 각 컬럼 1개

생성되는 엣지:
- `belongs_to`: column → table
- `foreign_key`: column(FK) → column(target PK)

Dual-write: SQL 테이블 + AGE 그래프. AGE 실패 시 SQL만으로 정상 진행.
"""

from __future__ import annotations

import logging
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.dbsphere import DbSpheres
from open_webui.models.knowledge_graph import (
    EdgeSource,
    EdgeType,
    KnowledgeGraphs,
    NodeType,
    make_node_id,
)

from ._age_helpers import age_cleanup, age_upsert_edge, age_upsert_node, get_age_service
from ._node_ids import database_node_id

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def _table_node_id(kg_id: str, dbsphere_id: str, table_name: str) -> str:
    return make_node_id(kg_id, "dbsphere", dbsphere_id, "table", table_name)


def _column_node_id(
    kg_id: str, dbsphere_id: str, table_name: str, column_name: str
) -> str:
    return make_node_id(
        kg_id, "dbsphere", dbsphere_id, "column", table_name, column_name
    )


async def sync_dbsphere_to_kg(
    app, kg_id: str, dbsphere_id: str, user_id: str
) -> Optional[dict]:
    """단일 DbSphere의 스키마를 KG에 동기화 (SQL + AGE dual-write).

    Args:
        app: FastAPI app (search engine 설정 접근용)
        kg_id: 대상 KG ID
        dbsphere_id: 동기화할 DbSphere ID
        user_id: 노드/엣지 owner

    Returns:
        통계 dict 또는 None.
    """
    dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
    if not dbsphere:
        log.warning(f"DbSphere not found: {dbsphere_id}")
        return None

    # 메모리에서 DDL 스키마 로드
    try:
        from extension_modules.dbsphere.memory.search_memory import (
            SearchEngineDbSphereMemory,
        )

        memory = SearchEngineDbSphereMemory(
            app=app,
            dbsphere_id=dbsphere_id,
            user_id=user_id,
            embedding_func=None,
        )
        ddl_memories = await memory.get_table_schemas()
    except Exception as e:
        log.exception(f"Failed to load DDL memories for {dbsphere_id}: {e}")
        return {
            "dbsphere_id": dbsphere_id,
            "nodes_created": 0,
            "edges_created": 0,
            "error": str(e),
        }

    age = get_age_service(kg_id)

    if not ddl_memories:
        log.info(
            f"DbSphere {dbsphere_id} has no DDL memories. "
            f"Did you run schema extraction?"
        )
        KnowledgeGraphs.delete_nodes_by_source(kg_id, "dbsphere", dbsphere_id)
        if age:
            age_cleanup(age, "source_id", dbsphere_id)
        return {"dbsphere_id": dbsphere_id, "nodes_created": 0, "edges_created": 0}

    # 기존 노드 전체 제거 후 재구축 (Phase 0 단순 전략)
    KnowledgeGraphs.delete_nodes_by_source(kg_id, "dbsphere", dbsphere_id)
    if age:
        age_cleanup(age, "source_id", dbsphere_id)

    # 중복 DDL 제거 (같은 table_name이 여러 번 나오면 첫 번째만)
    seen_tables: set[str] = set()
    deduped_ddls = []
    for d in ddl_memories:
        if not d.table_name or d.table_name in seen_tables:
            continue
        seen_tables.add(d.table_name)
        deduped_ddls.append(d)
    if len(deduped_ddls) < len(ddl_memories):
        log.warning(
            f"[dbsphere_sync] dedup'd {len(ddl_memories) - len(deduped_ddls)} "
            f"duplicate DDL records for dbsphere={dbsphere_id}"
        )
    ddl_memories = deduped_ddls

    nodes_created = 0
    edges_created = 0

    # ── 컨테이너: database 노드 (Phase 2 계층 구조) ──
    db_nid = database_node_id(kg_id, dbsphere_id)
    db_props = {
        "dbsphere_id": dbsphere_id,
        "db_type": getattr(dbsphere, "db_type", None) or "",
        "description": getattr(dbsphere, "description", None) or "",
    }
    db_label = getattr(dbsphere, "name", None) or dbsphere_id
    db_node = KnowledgeGraphs.upsert_node(
        kg_id=kg_id,
        user_id=user_id,
        node_id=db_nid,
        node_type=NodeType.DATABASE,
        label=db_label,
        properties=db_props,
        source_ref={"kind": "dbsphere", "dbsphere_id": dbsphere_id},
    )
    if age:
        age_upsert_node(
            age,
            NodeType.DATABASE,
            db_nid,
            db_label,
            {**db_props, "source_kind": "dbsphere", "source_id": dbsphere_id},
            kg_id=kg_id,
        )
    if db_node:
        nodes_created += 1

    # ── Pass 1: table + column 노드 ──
    column_id_map: dict[tuple[str, str], str] = {}

    for ddl in ddl_memories:
        table_name = ddl.table_name
        if not table_name:
            continue

        table_nid = _table_node_id(kg_id, dbsphere_id, table_name)
        table_props = {
            "schema_name": ddl.schema_name,
            "description": ddl.table_description or "",
            "ddl": ddl.ddl_statement or "",
        }
        table_node = KnowledgeGraphs.upsert_node(
            kg_id=kg_id,
            user_id=user_id,
            node_id=table_nid,
            node_type=NodeType.TABLE,
            label=table_name,
            properties=table_props,
            source_ref={
                "kind": "dbsphere",
                "dbsphere_id": dbsphere_id,
                "table_name": table_name,
            },
        )
        if age:
            age_upsert_node(
                age,
                NodeType.TABLE,
                table_nid,
                table_name,
                {
                    **table_props,
                    "source_kind": "dbsphere",
                    "source_id": dbsphere_id,
                },
                kg_id=kg_id,
            )
        if not table_node:
            continue
        nodes_created += 1

        # contains_table: database → table
        ct_edge = KnowledgeGraphs.upsert_edge(
            kg_id=kg_id,
            user_id=user_id,
            src_id=db_nid,
            dst_id=table_nid,
            edge_type=EdgeType.CONTAINS_TABLE,
            source=EdgeSource.SCHEMA_EXTRACTOR,
        )
        if age:
            age_upsert_edge(
                age,
                EdgeType.CONTAINS_TABLE,
                NodeType.DATABASE,
                db_nid,
                NodeType.TABLE,
                table_nid,
                source=EdgeSource.SCHEMA_EXTRACTOR,
                kg_id=kg_id,
            )
        if ct_edge:
            edges_created += 1

        for col in ddl.columns or []:
            col_name = col.name
            if not col_name:
                continue

            col_nid = _column_node_id(kg_id, dbsphere_id, table_name, col_name)
            col_props = {
                "table_name": table_name,
                "column_name": col_name,
                "data_type": col.data_type,
                "description": col.description or "",
                "is_primary_key": col.is_primary_key,
                "is_foreign_key": col.is_foreign_key,
                "is_nullable": col.is_nullable,
                "default_value": col.default_value,
            }
            col_node = KnowledgeGraphs.upsert_node(
                kg_id=kg_id,
                user_id=user_id,
                node_id=col_nid,
                node_type=NodeType.COLUMN,
                label=f"{table_name}.{col_name}",
                properties=col_props,
                source_ref={
                    "kind": "dbsphere",
                    "dbsphere_id": dbsphere_id,
                    "table_name": table_name,
                    "column_name": col_name,
                },
            )
            if age:
                age_upsert_node(
                    age,
                    NodeType.COLUMN,
                    col_nid,
                    f"{table_name}.{col_name}",
                    {
                        **col_props,
                        "source_kind": "dbsphere",
                        "source_id": dbsphere_id,
                    },
                    kg_id=kg_id,
                )
            if not col_node:
                continue
            nodes_created += 1
            column_id_map[(table_name, col_name)] = col_nid

            # belongs_to: column → table
            edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=col_nid,
                dst_id=table_nid,
                edge_type=EdgeType.BELONGS_TO,
                source=EdgeSource.SCHEMA_EXTRACTOR,
            )
            if age:
                age_upsert_edge(
                    age,
                    EdgeType.BELONGS_TO,
                    NodeType.COLUMN,
                    col_nid,
                    NodeType.TABLE,
                    table_nid,
                    source=EdgeSource.SCHEMA_EXTRACTOR,
                    kg_id=kg_id,
                )
            if edge:
                edges_created += 1

            # contains_column: table → column (Phase 2 계층)
            cc_edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=table_nid,
                dst_id=col_nid,
                edge_type=EdgeType.CONTAINS_COLUMN,
                source=EdgeSource.SCHEMA_EXTRACTOR,
            )
            if age:
                age_upsert_edge(
                    age,
                    EdgeType.CONTAINS_COLUMN,
                    NodeType.TABLE,
                    table_nid,
                    NodeType.COLUMN,
                    col_nid,
                    source=EdgeSource.SCHEMA_EXTRACTOR,
                    kg_id=kg_id,
                )
            if cc_edge:
                edges_created += 1

    # ── Pass 2: foreign_key 엣지 ──
    for ddl in ddl_memories:
        for col in ddl.columns or []:
            if not col.is_foreign_key:
                continue
            ftable = col.foreign_table
            fcolumn = col.foreign_column
            if not ftable or not fcolumn:
                continue

            src_id = column_id_map.get((ddl.table_name, col.name))
            dst_id = column_id_map.get((ftable, fcolumn))
            if not src_id or not dst_id:
                continue

            fk_props = {
                "from": f"{ddl.table_name}.{col.name}",
                "to": f"{ftable}.{fcolumn}",
            }
            edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=src_id,
                dst_id=dst_id,
                edge_type=EdgeType.FOREIGN_KEY,
                source=EdgeSource.SCHEMA_EXTRACTOR,
                properties=fk_props,
            )
            if age:
                age_upsert_edge(
                    age,
                    EdgeType.FOREIGN_KEY,
                    NodeType.COLUMN,
                    src_id,
                    NodeType.COLUMN,
                    dst_id,
                    source=EdgeSource.SCHEMA_EXTRACTOR,
                    properties=fk_props,
                    kg_id=kg_id,
                )
            if edge:
                edges_created += 1

    log.info(
        f"Synced dbsphere {dbsphere_id} to KG {kg_id}: "
        f"{len(ddl_memories)} tables, {nodes_created} nodes, {edges_created} edges"
        f" (AGE={'enabled' if age else 'disabled'})"
    )
    return {
        "dbsphere_id": dbsphere_id,
        "tables": len(ddl_memories),
        "nodes_created": nodes_created,
        "edges_created": edges_created,
    }
