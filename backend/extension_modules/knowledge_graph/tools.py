"""KG LangChain Tools — UnifiedAgent에 노출되는 도구들.

도구 목록:
1. **kg_resolve_term**: 비즈니스 용어를 컬럼/테이블로 해소 (Slice 4 maps_to 매핑 활용).
   가장 중요한 도구. NL-to-SQL 정확도의 핵심.
2. **kg_search_concepts**: 시맨틱 노드 검색 (Slice 3 검색 인덱스 활용).
3. **kg_neighbors**: 노드 1~N hop 이웃 트래버설.
4. **kg_find_related_tables**: 특정 테이블에서 FK로 연결된 테이블 발견 (JOIN 후보).

설계 노트:
- 단일 manager 클래스가 여러 KG ID를 들고 있다가 도구 호출 시 통합 처리.
- LangChain `StructuredTool.from_function` 패턴 (ToolConnectionManager 동일).
- 결과는 LLM이 읽기 좋은 markdown 또는 간결한 JSON 문자열.
- 검색 엔진 미설정 시: kg_search_concepts는 빈 결과 + 안내. 다른 도구들은 정상 동작.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from extension_modules.knowledge_graph.index_service import KGNodeIndexService
from langchain_core.tools import StructuredTool
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import (
    EdgeType,
    KGNodeModel,
    KnowledgeGraphs,
    NodeType,
)
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# ─────────────────────────────────────────────
# Phase 2 semantic layer filters
# ─────────────────────────────────────────────
#
# KG 에는 컨테이너 (database/kb/glossary), DOCUMENT 같은 구조 노드/엣지가
# 있다. 이들은 계층 / 프로비넌스용이라 semantic 트래버설에 섞이면 LLM
# 결과가 오염된다.
#
# - `_CONTAINMENT_EDGE_TYPES`: 계층 포함 관계. BFS 에서 기본 제외
# - `_CONTAINER_NODE_TYPES`: 구조 컨테이너 노드. 결과에서 기본 제외
# - `_STRUCTURAL_NODE_TYPES`: 구조 노드 전체 (BFS 결과 post-filter)
#
# 동적 도메인 엣지 (도메인별 has_*, 관계형 동사 등) 는 KG 의
# `get_distinct_edge_types` 로 자동 노출되며 화이트리스트에 등록할 필요 없다.

_CONTAINMENT_EDGE_TYPES: frozenset[str] = frozenset(
    {
        EdgeType.CONTAINS_TABLE,
        EdgeType.CONTAINS_COLUMN,
        EdgeType.CONTAINS_DOCUMENT,
        EdgeType.CONTAINS_CONCEPT,
        EdgeType.CONTAINS_TERM,
    }
)

_CONTAINER_NODE_TYPES: frozenset[str] = frozenset(
    {
        NodeType.DATABASE,
        NodeType.KNOWLEDGE_BASE,
        NodeType.GLOSSARY,
    }
)

# 기본 semantic BFS 에서 제외할 노드 타입 (컨테이너 + 구조 문서)
_STRUCTURAL_NODE_TYPES: frozenset[str] = _CONTAINER_NODE_TYPES | frozenset(
    {
        NodeType.DOCUMENT,
    }
)

# ─────────────────────────────────────────────
# Tool input schemas (Pydantic)
# ─────────────────────────────────────────────


class ResolveTermInput(BaseModel):
    term: str = Field(
        ...,
        description="Business term in natural language (e.g. 'VIP customer', '강남 지점')",
    )


class SearchConceptsInput(BaseModel):
    query: str = Field(..., description="Natural language search query")
    top_k: int = Field(default=10, description="Maximum number of results", ge=1, le=50)
    node_types: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional filter. Semantic types: term, concept, table, column, "
            "doc_entity (LLM-extracted attribute values), doc_attr (KB filter "
            "values lifted to nodes — e.g. country, department, doc_type). "
            "Structural types (usually not useful for LLM context, excluded by "
            "default when this field is omitted): document, database, "
            "knowledge_base, glossary. Pass explicit list to include structural nodes."
        ),
    )


class NeighborsInput(BaseModel):
    node_id: str = Field(
        ..., description="Source node ID (use kg_search_concepts to find IDs)"
    )
    hops: int = Field(default=1, description="Traversal depth 1-3", ge=1, le=3)
    edge_types: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional edge-type whitelist. Semantic: synonym_of, broader_than, "
            "narrower_than, related_to, maps_to, foreign_key, belongs_to, "
            "has_feature, plus any domain-specific catalog edge "
            "(has_<attr>, <verb>_<object>, etc — discoverable via "
            "kg_explore_context). "
            "Document linkage: mentions (DOCUMENT→term), "
            "extracted_from (doc_entity→DOCUMENT). "
            "When omitted, all non-containment edges are traversed "
            "(contains_table/column/document/concept/term are "
            "always excluded to avoid structure explosion)."
        ),
    )


class ExploreContextInput(BaseModel):
    seed: str = Field(
        ...,
        description="Entity name or natural language topic to explore (e.g. '갤럭시S26', 'VIP customers', '매출 분석')",
    )
    hops: int = Field(
        default=2,
        description="Traversal depth 1-3 (more hops = broader context)",
        ge=1,
        le=3,
    )
    max_nodes: int = Field(
        default=30, description="Maximum neighbor nodes to include", ge=5, le=100
    )


class FindRelatedTablesInput(BaseModel):
    table_name: str = Field(..., description="Table name (e.g. 'orders')")
    hops: int = Field(default=1, description="Traversal depth 1-2", ge=1, le=2)


class FetchDataInput(BaseModel):
    sql: str = Field(
        ...,
        description=(
            "SELECT SQL query to execute against the database linked to this "
            "knowledge graph. Write the SQL based on table/column info from "
            "kg_explore_context or kg_resolve_term. "
            "Only SELECT statements allowed; results limited to 100 rows."
        ),
    )
    doc_query: Optional[str] = Field(
        default=None,
        description=(
            "Optional: also search knowledge base documents for this query. "
            "Provide this when the user asks for BOTH data AND qualitative "
            "context (policies, strategies, definitions, guidelines). "
            "If omitted and the SQL returns 0 rows, the tool automatically "
            "searches documents using keywords extracted from the SQL."
        ),
    )
    dbsphere_id: Optional[str] = Field(
        default=None,
        description="DbSphere ID. If omitted, uses the first database linked to the KG.",
    )
    knowledge_id: Optional[str] = Field(
        default=None,
        description=(
            "Knowledge base ID to search for doc_query. "
            "If omitted, searches all KBs linked to the KG."
        ),
    )


class FetchDocumentInput(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description=(
            "Semantic search keywords. When `seed` is also provided, this "
            "re-ranks chunks inside the graph-discovered candidate set. "
            "When used alone (no seed), performs pure vector search across "
            "the linked KB."
        ),
    )
    seed: Optional[str] = Field(
        default=None,
        description=(
            "Entity name, term, or attribute value used as the graph seed. "
            "The tool resolves it to KG term/doc_entity nodes (label CI match "
            "with synonym fallback, then semantic search) and collects "
            "candidate file_ids via graph traversal: "
            "(A) DOCUMENT --mentions--> seed(TERM), "
            "(B) DOCUMENT --mentions--> synonym <--synonym_of-- seed. "
            "Results are vector-searched in the KB scoped to those file_ids "
            "— no fabrication, only files actually linked in the graph."
        ),
    )
    edge_types: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional filter by domain catalog edges. Documents are kept "
            "only if any doc_entity extracted from them has an outgoing edge "
            "of one of the listed types. Used together with `seed` to find "
            "documents that mention the seed AND contain specific information "
            "categories.\n"
            "Tip: prefer the actual edge type names from kg_explore_context "
            "or kg_neighbors output (typically has_<attr> or <verb>_<object>). "
            "Short aliases without prefix are also accepted via fuzzy matching "
            "(bare '<attr>' resolves to 'has_<attr>' when unambiguous)."
        ),
    )
    knowledge_id: Optional[str] = Field(
        default=None,
        description=(
            "Knowledge base ID to search. If omitted, searches all KBs "
            "linked to the KG(s)."
        ),
    )
    top_k: int = Field(
        default=5,
        description="Maximum document chunks to return",
        ge=1,
        le=20,
    )


class KGCypherInput(BaseModel):
    question: str = Field(
        ...,
        description=(
            "The user's question in natural language (Korean or English). "
            "Used by the tool's semantic memory layer to retrieve relevant "
            "schema docs, prior cypher examples, and patterns — these are "
            "automatically injected as few-shot context."
        ),
    )
    cypher: str = Field(
        ...,
        description=(
            "A read-only AGE Cypher query that answers the question. Use only "
            "MATCH / OPTIONAL MATCH / WITH / RETURN / UNWIND / WHERE / ORDER BY / "
            "LIMIT / SKIP. Write/CALL/CREATE/MERGE/DELETE/SET/REMOVE/DROP are "
            "rejected. AGE does NOT support edge alternation `[:A|B]` — use "
            "`[r]` + `WHERE type(r) IN [...]` instead. "
            "Prefer projecting explicit fields (e.g. `RETURN n.label AS label`) "
            "to avoid agtype parsing issues. Default LIMIT 100 auto-injected if "
            "not present and the RETURN is not a pure aggregate."
        ),
    )
    kg_id: Optional[str] = Field(
        default=None,
        description=(
            "KG to query. Omit when only one KG is connected — the tool will "
            "default to it. Required when multiple KGs are connected."
        ),
    )
    max_rows: int = Field(
        default=100,
        description="Result row cap (1-500). Default 100.",
        ge=1,
        le=500,
    )


# ─────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────


class KGToolManager:
    """KG 도구 관리자.

    여러 KG가 연결돼 있으면 모든 KG에 걸쳐 동작한다.
    AGE Cypher로 그래프 트래버설을 수행한다.
    """

    def __init__(
        self,
        app,
        kg_ids: list[str],
        user_id: str = "",
        chat_id: Optional[str] = None,
        user_question: Optional[str] = None,
    ):
        self.app = app
        self.kg_ids = [kid for kid in kg_ids if kid]
        self.user_id = user_id
        self.chat_id = chat_id
        # Original natural-language question for this turn.
        # Used to persist successful Question-SQL pairs to DbSphere memory
        # (mirrors dbsphere_agent.save_sql_memory behavior) so that subsequent
        # runs can retrieve similar past queries via search_all_context.
        self.user_question = (user_question or "").strip()
        self._index_service: Optional[KGNodeIndexService] = None
        self._age_cache: dict = {}  # kg_id → AGEService
        # in-turn last-failure tracker for kg_cypher.
        # Same question fails first, then succeeds on retry → cypher_negative pair saved.
        self._kg_cypher_failures: dict[str, dict] = {}

    def _get_index_service(self) -> KGNodeIndexService:
        if self._index_service is None:
            self._index_service = KGNodeIndexService(self.app)
        return self._index_service

    def _get_age(self, kg_id: str):
        """AGEService 인스턴스 반환 (캐시)."""
        if kg_id not in self._age_cache:
            from extension_modules.knowledge_graph.age_service import AGEService

            svc = AGEService(kg_id)
            svc.ensure_graph()
            self._age_cache[kg_id] = svc
        return self._age_cache[kg_id]

    # ─────────────────────────────────
    # Source Helpers (DbSphere / KB)
    # ─────────────────────────────────

    def _get_linked_dbsphere_ids(self) -> list[str]:
        """KG에 연결된 모든 DbSphere ID를 수집한다."""
        from extension_modules.knowledge_graph.service import KGService

        ids: list[str] = []
        seen: set[str] = set()
        for kg_id in self.kg_ids:
            svc = KGService.load(kg_id)
            if svc:
                for db_id in svc.dbsphere_ids:
                    if db_id and db_id not in seen:
                        ids.append(db_id)
                        seen.add(db_id)
        return ids

    def _get_linked_knowledge_ids(self) -> list[str]:
        """KG에 연결된 모든 KB ID를 수집한다."""
        from extension_modules.knowledge_graph.service import KGService

        ids: list[str] = []
        seen: set[str] = set()
        for kg_id in self.kg_ids:
            svc = KGService.load(kg_id)
            if svc:
                for kb_id in svc.knowledge_ids:
                    if kb_id and kb_id not in seen:
                        ids.append(kb_id)
                        seen.add(kb_id)
        return ids

    def _create_sql_runner(self, dbsphere_id: str):
        """DbSphere ID로부터 SQL runner를 생성한다. (runner, db_name) 반환.

        DbSphere의 공유 팩토리(create_sql_runner)를 사용하여
        DB 타입 추가 시 한 곳만 수정하면 된다.
        """
        import copy

        from extension_modules.dbsphere.dbsphere_state import DBConfig
        from extension_modules.dbsphere.sql_runners import create_sql_runner
        from open_webui.models.dbsphere import DbSpheres
        from open_webui.routers.dbsphere import decrypt_connection_password

        dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
        if not dbsphere or not dbsphere.data:
            return None, f"DbSphere {dbsphere_id[:8]} not found."

        data = decrypt_connection_password(copy.deepcopy(dbsphere.data))
        db_config = DBConfig.from_dbsphere_data(data)

        runner = create_sql_runner(db_config)
        if not runner:
            return None, f"Unsupported database type: {db_config.get_db_type_enum()}"
        return runner, dbsphere.name or dbsphere_id[:8]

    # ─────────────────────────────────
    # Helpers
    # ─────────────────────────────────

    @staticmethod
    def _format_node_brief(node: KGNodeModel) -> str:
        props = node.properties or {}
        parts = [f"[{node.node_type}] {node.label}"]
        if node.node_type == "column":
            tn = props.get("table_name")
            dt = props.get("data_type")
            extras = []
            if dt:
                extras.append(dt)
            if props.get("is_primary_key"):
                extras.append("PK")
            if props.get("is_foreign_key"):
                extras.append("FK")
            if extras:
                parts.append(f"({', '.join(extras)})")
            if tn:
                parts.append(f"@{tn}")
        if props.get("description"):
            parts.append(f"— {props['description']}")
        return " ".join(parts)

    def _find_term_nodes_by_label(self, term: str) -> list[KGNodeModel]:
        """주어진 용어와 일치하는 term/concept 노드 검색.

        1) 정확 매칭 (case-insensitive) — `(kg_id, label)` 인덱스를 활용한 SQL 푸시
        2) 매칭 없으면 시맨틱 검색으로 fallback (호출자가 처리)
        """
        results: list[KGNodeModel] = []
        for kg_id in self.kg_ids:
            results.extend(
                KnowledgeGraphs.find_nodes_by_label_ci(
                    kg_id=kg_id,
                    label=term,
                    node_types=[
                        NodeType.TERM,
                        NodeType.CONCEPT,
                    ],
                    limit=20,
                )
            )
        return results

    # ─────────────────────────────────
    # Tool implementations
    # ─────────────────────────────────

    async def _resolve_term(self, term: str) -> str:
        """비즈니스 용어를 컬럼/테이블 매핑으로 해소 (AGE Cypher).

        흐름:
        1. SQL 인덱스로 term/concept 노드 정확 매칭 (또는 시맨틱 검색)
        2. AGE Cypher: 매칭 노드 + synonym 확장 → maps_to/has_feature 엣지 한 번에 수집
        """
        log.info(f"[kg_resolve_term] term='{term}'")
        if not self.kg_ids:
            return "No knowledge graph connected to this agent."

        # 1) 정확 매칭
        matched = self._find_term_nodes_by_label(term)

        # 2) Fallback: 시맨틱 검색
        if not matched:
            for kg_id in self.kg_ids:
                try:
                    sem_results = await self._get_index_service().search(
                        kg_id=kg_id,
                        query=term,
                        top_k=5,
                        node_types=[
                            NodeType.TERM,
                            NodeType.CONCEPT,
                        ],
                    )
                except Exception as e:
                    log.warning(f"Semantic fallback failed for kg={kg_id}: {e}")
                    continue
                for r in sem_results:
                    node = KnowledgeGraphs.get_node_by_id(r["id"])
                    if node:
                        matched.append(node)

        if not matched:
            return f'No term matching "{term}" found in knowledge graph(s).'

        # 3) AGE Cypher: 매칭 노드 → (직접 + synonym 확장) maps_to/has_feature
        import json as _json

        output_blocks: list[str] = []
        seen_labels: set[str] = set()

        for src_node in matched:
            age = self._get_age(src_node.kg_id)
            nid_json = _json.dumps(src_node.id, ensure_ascii=False)

            # 직접 maps_to/has_feature + synonym 확장 (2-hop: synonym → maps_to)
            # AGE는 edge type alternation (|) 미지원 → 4개 UNION으로 분리
            cypher = (
                f"MATCH (s {{node_id: {nid_json}}})-[:{EdgeType.MAPS_TO}]->(dst) "
                f"RETURN dst "
                f"UNION "
                f"MATCH (s {{node_id: {nid_json}}})-[:{EdgeType.HAS_FEATURE}]->(dst) "
                f"RETURN dst "
                f"UNION "
                f"MATCH (s {{node_id: {nid_json}}})-[:{EdgeType.SYNONYM_OF}]-(syn)"
                f"-[:{EdgeType.MAPS_TO}]->(dst) "
                f"RETURN dst "
                f"UNION "
                f"MATCH (s {{node_id: {nid_json}}})-[:{EdgeType.SYNONYM_OF}]-(syn)"
                f"-[:{EdgeType.HAS_FEATURE}]->(dst) "
                f"RETURN dst"
            )
            try:
                rows = age.execute_cypher(cypher)
            except Exception as e:
                log.warning(f"[kg_resolve_term] Cypher failed: {e}")
                rows = []

            mappings_text: list[str] = []
            for row in rows:
                dst = row[0] if row else None
                if not dst or not isinstance(dst, dict):
                    continue
                props = dst.get("properties", {})
                label = props.get("label", "?")
                if label in seen_labels:
                    continue
                seen_labels.add(label)
                ntype = props.get("node_type", "?")
                desc = props.get("description", "")
                line = f"  → [{ntype}] {label}"
                if ntype == "column":
                    tn = props.get("table_name", "")
                    dt = props.get("data_type", "")
                    extras = []
                    if dt:
                        extras.append(dt)
                    if props.get("is_primary_key"):
                        extras.append("PK")
                    if props.get("is_foreign_key"):
                        extras.append("FK")
                    if extras:
                        line += f" ({', '.join(extras)})"
                    if tn:
                        line += f" @{tn}"
                if desc:
                    line += f" — {desc}"
                filter_expr = props.get("filter")
                if filter_expr:
                    line += f"  WHERE {filter_expr}"
                mappings_text.append(line)

            block = f'Term "{src_node.label}" ({src_node.node_type}):'
            if mappings_text:
                block += "\n" + "\n".join(mappings_text)
            else:
                block += "\n  (no mappings curated yet)"
            output_blocks.append(block)

        return "\n\n".join(output_blocks)

    async def _search_concepts(
        self,
        query: str,
        top_k: int = 10,
        node_types: Optional[list[str]] = None,
    ) -> str:
        """Vector + Graph 하이브리드 검색.

        검색 엔진(vector+BM25)으로 시맨틱 매칭한 뒤, 상위 결과에 대해
        1-hop 그래프 이웃을 확장해서 "evidence sub-graph"를 반환한다.
        단순히 "이 노드를 찾았다"가 아니라 "이 노드는 이런 것들과 연결돼 있다"까지.
        """
        if not self.kg_ids:
            return "No knowledge graph connected to this agent."

        # 사용자가 명시적으로 node_types 를 지정하지 않았으면 구조 노드
        # (database/kb/glossary/document) 를 semantic 검색 결과에서 제외한다.
        # 명시하면 (예: ['document']) 그대로 따른다.
        all_results: list[dict] = []
        for kg_id in self.kg_ids:
            try:
                results = await self._get_index_service().search(
                    kg_id=kg_id,
                    query=query,
                    top_k=top_k,
                    node_types=node_types,
                )
                for r in results:
                    r["kg_id"] = kg_id
                all_results.extend(results)
            except Exception as e:
                log.warning(f"search failed for kg={kg_id}: {e}")

        if not node_types:
            all_results = [
                r
                for r in all_results
                if r.get("node_type") not in _STRUCTURAL_NODE_TYPES
            ]

        if not all_results:
            return (
                f'No nodes matching "{query}".'
                " (If unexpected, the search engine may not be configured.)"
            )

        # 점수 기준 정렬, top_k 자르기
        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
        all_results = all_results[:top_k]

        lines = [f'Top {len(all_results)} results for "{query}":']
        for i, r in enumerate(all_results, start=1):
            score = r.get("score", 0)
            label = r.get("label", "")
            ntype = r.get("node_type", "")
            nid = r.get("id", "")
            lines.append(f"{i}. [{ntype}] {label}  (score={score:.3f}, id={nid})")

            # ── Graph expansion: 상위 5개 결과에 대해 1-hop 이웃 요약 ──
            #   containment 엣지 및 구조 노드는 기본 제외 (Phase 2)
            if i <= 5:
                try:
                    kg_id = r.get("kg_id", "")
                    edges = KnowledgeGraphs.get_edges_for_node(kg_id, nid)
                    if edges:
                        edge_summaries: list[str] = []
                        seen: set[str] = set()
                        for edge in edges:
                            if edge.edge_type in _CONTAINMENT_EDGE_TYPES:
                                continue
                            other_id = (
                                edge.dst_id if edge.src_id == nid else edge.src_id
                            )
                            if other_id in seen:
                                continue
                            seen.add(other_id)
                            other = KnowledgeGraphs.get_node_by_id(other_id)
                            if not other:
                                continue
                            if other.node_type in _STRUCTURAL_NODE_TYPES:
                                continue
                            if len(edge_summaries) >= 10:
                                break
                            e_type = edge.edge_type.replace("_", " ")
                            filter_expr = (
                                (edge.properties or {}).get("filter")
                                if edge.properties
                                else None
                            )
                            summary = (
                                f"     ─{e_type}→ [{other.node_type}] {other.label}"
                            )
                            if filter_expr:
                                summary += f" WHERE {filter_expr}"
                            edge_summaries.append(summary)
                        if edge_summaries:
                            lines.extend(edge_summaries)
                except Exception as e:
                    log.warning(
                        f"[kg_search] graph expansion failed for {nid[:8]}: {e}"
                    )

        return "\n".join(lines)

    async def _neighbors(
        self,
        node_id: str,
        hops: int = 1,
        edge_types: Optional[list[str]] = None,
    ) -> str:
        """N-hop 이웃 트래버설 (AGE Cypher)."""
        node = KnowledgeGraphs.get_node_by_id(node_id)
        if not node:
            return f"Node not found: {node_id}"
        if node.kg_id not in self.kg_ids:
            return f"Node not in any connected KG: {node_id}"

        # 사용자가 edge_types 를 명시하지 않으면 containment 엣지 (contains_*)
        # 를 제외한 모든 실제 엣지 타입을 whitelist 로 사용한다 (Phase 2).
        effective_edge_types = edge_types
        if not effective_edge_types:
            distinct = KnowledgeGraphs.get_distinct_edge_types(node.kg_id)
            effective_edge_types = [
                t for t, _ in distinct if t not in _CONTAINMENT_EDGE_TYPES
            ]
            if not effective_edge_types:
                return f'Node "{node.label}" has no neighbors within {hops} hop(s).'

        age = self._get_age(node.kg_id)
        neighbors = age.get_neighbors(
            label=node.node_type,
            match={"node_id": node_id},
            hops=hops,
            edge_labels=effective_edge_types,
            limit=50,
        )
        if not neighbors:
            return f'Node "{node.label}" has no neighbors within {hops} hop(s).'

        # 결과 post-filter: 기본은 컨테이너 노드 (database/kb/glossary) 제외.
        # 사용자가 edge_types 를 명시했으면 의도적 traversal 이라 그대로 노출.
        explicit_struct = bool(edge_types)

        lines = [
            f'Neighbors of "{node.label}" ({node.node_type}) within {hops} hop(s):'
        ]
        for nb in neighbors:
            props = nb.get("properties", {})
            ntype = props.get("node_type", "?")
            if not explicit_struct and ntype in _CONTAINER_NODE_TYPES:
                continue
            label = props.get("label", "?")
            nid = props.get("node_id", "")
            suffix = ""
            if ntype == NodeType.DOCUMENT:
                file_id = props.get("file_id", "")
                if file_id:
                    suffix = f"  [file_id={file_id[:8]} for kg_fetch_document]"
            lines.append(f"  [{ntype}] {label}  (id={nid}){suffix}")

        if len(lines) == 1:
            return (
                f'Node "{node.label}" has no semantic neighbors within {hops} hop(s).'
            )
        return "\n".join(lines)

    async def _find_related_tables(self, table_name: str, hops: int = 1) -> str:
        """FK로 연결된 테이블 발견 (AGE Cypher)."""
        if not self.kg_ids:
            return "No knowledge graph connected to this agent."

        output_blocks: list[str] = []
        # Cypher injection 방지: 작은따옴표 이스케이프
        safe_name = table_name.replace("\\", "\\\\").replace("'", "\\'")
        for kg_id in self.kg_ids:
            age = self._get_age(kg_id)
            # Cypher: table → belongs_to ← column → foreign_key → column → belongs_to → table
            cypher = (
                f"MATCH (t:{NodeType.TABLE} {{label: '{safe_name}'}})"
                f"<-[:{EdgeType.BELONGS_TO}]-(c:{NodeType.COLUMN})"
                f"-[:{EdgeType.FOREIGN_KEY}]->(fc:{NodeType.COLUMN})"
                f"-[:{EdgeType.BELONGS_TO}]->(ft:{NodeType.TABLE}) "
                f"WHERE ft.label <> '{safe_name}' "
                f"RETURN c.label, fc.label, ft.label"
            )
            try:
                rows = age.execute_cypher(cypher)
            except Exception as e:
                log.warning(
                    f"[kg_find_related_tables] Cypher failed for kg={kg_id}: {e}"
                )
                continue

            if not rows:
                continue

            related: dict[str, list[str]] = {}
            for row in rows:
                src_col = str(row[0]) if row[0] else "?"
                dst_col = str(row[1]) if row[1] else "?"
                dst_table = str(row[2]) if row[2] else "?"
                hint = f"{src_col} = {dst_col}"
                related.setdefault(dst_table, []).append(hint)

            block = f"Table {table_name}:"
            if related:
                for tbl, hints in related.items():
                    block += f"\n  → {tbl}  ({'; '.join(hints)})"
            else:
                block += "\n  (no FK relationships found)"
            output_blocks.append(block)

        if not output_blocks:
            return f'Table "{table_name}" not found in knowledge graph(s).'
        return "\n\n".join(output_blocks)

    async def _explore_context(
        self, seed: str, hops: int = 2, max_nodes: int = 30
    ) -> str:
        """Graph-RAG: 시드 엔티티 주변 sub-graph (AGE Cypher).

        시드 찾기: SQL 인덱스 (정확 매칭 → 시맨틱 검색)
        트래버설: AGE Cypher N-hop + 엣지/이웃 수집
        """
        log.info(f"[kg_explore_context] seed='{seed}', hops={hops}")
        if not self.kg_ids:
            return "No knowledge graph connected to this agent."

        # 1) 시드 노드 찾기 — 정확 매칭 → 시맨틱 검색 fallback
        seed_nodes: list[KGNodeModel] = []
        for kg_id in self.kg_ids:
            seed_nodes.extend(
                KnowledgeGraphs.find_nodes_by_label_ci(
                    kg_id=kg_id,
                    label=seed,
                    node_types=[
                        NodeType.TERM,
                        NodeType.CONCEPT,
                        NodeType.DOC_ENTITY,
                        NodeType.TABLE,
                    ],
                    limit=5,
                )
            )
        if not seed_nodes:
            for kg_id in self.kg_ids:
                try:
                    results = await self._get_index_service().search(
                        kg_id=kg_id, query=seed, top_k=3
                    )
                    for r in results:
                        node = KnowledgeGraphs.get_node_by_id(r["id"])
                        if node:
                            seed_nodes.append(node)
                except Exception as e:
                    log.warning(f"[kg_explore_context] search failed: {e}")
        if not seed_nodes:
            return f'No nodes matching "{seed}" found in knowledge graph(s).'

        seed_nodes = seed_nodes[:3]
        output_blocks: list[str] = []

        for seed_node in seed_nodes:
            age = self._get_age(seed_node.kg_id)

            # 2) AGE Cypher: 시드 → N-hop 이웃 + 엣지 타입 수집
            import json as _json

            node_id_json = _json.dumps(seed_node.id, ensure_ascii=False)

            # Containment 엣지 (contains_*) 를 BFS 에서 제외한다.
            # AGE 는 edge alternation `[:A|B]` 를 지원하지 않으므로:
            # - var-length traverse 는 alternation 없이 (모든 엣지) 수행하고
            #   결과 노드를 post-filter (DISTINCT 로 충분)
            # - 1-hop edge 그룹핑은 `WHERE type(r) IN [...]` 로 필터
            distinct_types = KnowledgeGraphs.get_distinct_edge_types(seed_node.kg_id)
            allowed_types = [
                t for t, _ in distinct_types if t not in _CONTAINMENT_EDGE_TYPES
            ]

            rows: list = []
            edge_rows: list = []
            if allowed_types:
                # var-length traverse — alternation 없이 모든 엣지 순회
                # (containment 는 _CONTAINMENT_EDGE_TYPES 가 갯수 적어서 별도
                # 필터 안 걸어도 LIMIT 안에서 충분히 의미 노드 노출됨)
                cypher = (
                    f"MATCH (s {{node_id: {node_id_json}}})"
                    f"-[*1..{hops}]-(n) "
                    f"RETURN DISTINCT n "
                    f"LIMIT {max_nodes}"
                )
                try:
                    rows = age.execute_cypher(cypher)
                except Exception as e:
                    log.warning(f"[kg_explore_context] Cypher failed: {e}")

                # 3) 시드의 직접 엣지 (1-hop) — 엣지 타입별 그룹핑
                # AGE 는 type(r) IN [...] 술어 지원
                allowed_list = ", ".join(f"'{t}'" for t in allowed_types)
                cypher_edges = (
                    f"MATCH (s {{node_id: {node_id_json}}})-[r]-(n) "
                    f"WHERE type(r) IN [{allowed_list}] "
                    f"RETURN type(r), n"
                )
                try:
                    edge_rows = age.execute_cypher(cypher_edges)
                except Exception as e:
                    log.warning(f"[kg_explore_context] edge query failed: {e}")

            group_labels = {
                EdgeType.HAS_FEATURE: "Features (from documents)",
                EdgeType.MAPS_TO: "Database mappings",
                EdgeType.BELONGS_TO: "Belongs to",
                EdgeType.FOREIGN_KEY: "Related tables (FK)",
                EdgeType.SYNONYM_OF: "Synonyms",
                EdgeType.BROADER_THAN: "Broader concepts",
                EdgeType.NARROWER_THAN: "Narrower concepts",
                EdgeType.RELATED_TO: "Related",
                EdgeType.DEFINED_AS: "Defined as",
                EdgeType.COMPUTED_FROM: "Computed from",
                EdgeType.MENTIONS: "Mentioned in documents",
                EdgeType.EXTRACTED_FROM: "Extracted from",
            }

            groups: dict[str, list[str]] = {}
            seen_labels: set[str] = set()
            for row in edge_rows:
                edge_type = str(row[0]) if row[0] else "related_to"
                nb = row[1] if len(row) > 1 else None
                if not nb or not isinstance(nb, dict):
                    continue
                nb_props = nb.get("properties", {})
                nb_label = nb_props.get("label", "?")
                nb_type = nb_props.get("node_type", "?")
                # 구조 컨테이너 (database/kb/glossary) 는 semantic 결과에서 제외.
                # DOCUMENT 는 mentions/extracted_from 프로비넌스로 도달할 때
                # 의미가 있으므로 유지한다.
                if nb_type in _CONTAINER_NODE_TYPES:
                    continue
                if nb_label in seen_labels:
                    continue
                seen_labels.add(nb_label)

                group_key = group_labels.get(edge_type, f"Related ({edge_type})")
                desc = nb_props.get("description", "")
                line = f"  - [{nb_type}] {nb_label}"
                if desc:
                    line += f" — {desc}"
                filter_expr = nb_props.get("filter")
                if filter_expr:
                    line += f"  WHERE {filter_expr}"
                groups.setdefault(group_key, []).append(line)

            # 4) 간접 이웃 (2-hop+, 직접 엣지 없는 것)
            indirect: list[str] = []
            for row in rows:
                nb = row[0] if row else None
                if not nb or not isinstance(nb, dict):
                    continue
                nb_props = nb.get("properties", {})
                nb_label = nb_props.get("label", "?")
                nb_type = nb_props.get("node_type", "?")
                if nb_type in _CONTAINER_NODE_TYPES:
                    continue
                if nb_label not in seen_labels:
                    indirect.append(f"  - [{nb_type}] {nb_label}")
                    seen_labels.add(nb_label)

            # 5) 포맷
            block = f"### {seed_node.label} ({seed_node.node_type})"
            desc = (seed_node.properties or {}).get("description")
            if desc:
                block += f"\n{desc}"

            for group_name, lines in groups.items():
                block += f"\n\n**{group_name}:**"
                for line in lines[:15]:
                    block += f"\n{line}"
                if len(lines) > 15:
                    block += f"\n  ... ({len(lines) - 15} more)"

            if indirect:
                block += "\n\n**Indirectly connected:**"
                for line in indirect[:10]:
                    block += f"\n{line}"

            output_blocks.append(block)

        return "\n\n---\n\n".join(output_blocks)

    # ─────────────────────────────────
    # Data access tools (ontology → actual data)
    # ─────────────────────────────────

    # ─────────────────────────────────
    # Document search helper (shared)
    # ─────────────────────────────────

    async def _collect_file_candidates_for_doc_query(
        self,
        sql_result_columns: list[str],
        sql_result_data: list[dict],
    ) -> list[str]:
        """SQL 결과 + user_question 의 entity 로 KG 트래버설 → file_id 후보.

        seed 후보:
          - user_question 전체 (라벨 CI 매칭이면 hit, 아니면 semantic fallback)
          - SQL 결과 첫 컬럼 값 (보통 식별자/자연키 — 이름/코드/식별번호 등) — 처음 10행

        seed 가 KG 에 없거나 그래프에 mentions/extracted_from 이 없으면 빈
        리스트 반환 → 호출자는 단순 벡터 검색으로 fallback.
        """
        seed_strings: list[str] = []
        if self.user_question and len(self.user_question) >= 2:
            seed_strings.append(self.user_question)
        if sql_result_columns and sql_result_data:
            first_col = sql_result_columns[0]
            for row in sql_result_data[:10]:
                v = row.get(first_col)
                if v and isinstance(v, str) and len(v.strip()) >= 2:
                    seed_strings.append(v.strip())

        if not seed_strings:
            return []

        seed_nodes: list[KGNodeModel] = []
        seen_ids: set[str] = set()
        for s in seed_strings:
            try:
                nodes = await self._resolve_seed_to_nodes(s)
            except Exception as e:
                log.warning(f"[kg_fetch_data] seed resolve failed for '{s[:30]}': {e}")
                continue
            for n in nodes:
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    seed_nodes.append(n)

        if not seed_nodes:
            return []

        return self._collect_file_candidates_from_graph(seed_nodes)

    async def _search_documents(
        self,
        query: str,
        knowledge_id: Optional[str] = None,
        top_k: int = 5,
        file_ids: Optional[list[str]] = None,
    ) -> tuple[str, list[dict]]:
        """문서 검색 공통 로직. _fetch_data와 _fetch_document 양쪽에서 사용.

        Args:
            file_ids: KG 그래프 트래버설로 좁혀진 file_id 목록. 지정 시
                ``file_id eq '...'`` OData 필터를 추가하여 검색 범위를 좁힌다.

        Returns:
            (text, source_events): LLM 컨텍스트 텍스트와 프론트엔드 소스 이벤트 리스트.
            검색 실패 또는 결과 없으면 ("", []).
        """
        from extension_modules.search_engine.connector import (
            get_configured_search_engine,
        )
        from extension_modules.search_engine.embedding import (
            generate_embedding_async,
            get_embedding_config_from_app,
        )
        from extension_modules.search_engine.models import SearchQuery
        from extension_modules.search_engine.schemas import create_knowledge_config

        # 대상 KB 결정
        if knowledge_id:
            target_ids = [knowledge_id]
        else:
            target_ids = self._get_linked_knowledge_ids()
        if not target_ids:
            return "", []

        # 검색엔진 + 임베딩
        embedding_config = get_embedding_config_from_app(self.app)
        index_config = create_knowledge_config(
            vector_dim=embedding_config.dimensions or 3072,
        )
        engine = get_configured_search_engine(
            self.app, index_config, with_embedding=False
        )
        if not engine:
            return "", []

        # 컬렉션 필터
        if len(target_ids) == 1:
            filter_expr = f"collection eq '{target_ids[0]}'"
        else:
            parts = " or ".join(f"collection eq '{kid}'" for kid in target_ids)
            filter_expr = f"({parts})"

        # file_id 필터 (KG 그래프 트래버설 결과)
        if file_ids:
            escaped = [fid.replace("'", "''") for fid in file_ids]
            if len(escaped) == 1:
                file_filter = f"file_id eq '{escaped[0]}'"
            else:
                file_parts = " or ".join(f"file_id eq '{fid}'" for fid in escaped)
                file_filter = f"({file_parts})"
            filter_expr = f"{filter_expr} and {file_filter}"

        try:
            query_vector = await generate_embedding_async(
                text=query, config=embedding_config
            )

            search_query = SearchQuery(
                query=query,
                filter=filter_expr,
                top_k=top_k,
                top_k_vector=top_k * 3,
            )

            results = await engine.search(query=search_query, query_vector=query_vector)

            if not results:
                return "", []

            # LLM 컨텍스트 + 프론트엔드 소스 — file 단위로 그룹핑한다.
            # 한 파일에서 여러 청크가 매칭돼도 출처는 파일 1건으로 묶어,
            # 시스템 프롬프트의 [N] 라벨 / aggregated_sources / 프론트 dedup 결과를
            # 모두 파일 단위로 일치시킨다 (그렇지 않으면 LLM 인용 마커와 출처가 어긋난다).
            file_groups: dict[str, dict[str, Any]] = {}
            file_order: list[str] = []

            for r in results:
                content = r.content or ""
                meta = r.metadata or {}
                score = r.score

                file_key = (
                    meta.get("source")
                    or meta.get("file_id")
                    or meta.get("name")
                    or meta.get("file_name")
                    or f"unknown-{len(file_order)}"
                )
                file_name = meta.get("name") or meta.get("file_name") or str(file_key)

                if file_key not in file_groups:
                    file_order.append(file_key)
                    file_groups[file_key] = {
                        "name": file_name,
                        "documents": [],
                        "metadata": [],
                        "distances": [],
                    }

                file_groups[file_key]["documents"].append(content)
                file_groups[file_key]["metadata"].append(meta)
                file_groups[file_key]["distances"].append(score)

            text_parts = [
                f"Found {len(results)} document chunk(s) "
                f"across {len(file_order)} file(s):"
            ]
            source_events: list[dict] = []

            for idx, key in enumerate(file_order, start=1):
                g = file_groups[key]
                text_parts.append(f"\n[{idx}] {g['name']}")
                for j, (doc, dist) in enumerate(
                    zip(g["documents"], g["distances"]), start=1
                ):
                    text_parts.append(f"  (chunk {j}, score={dist:.3f}) {doc[:800]}")

                source_events.append(
                    {
                        "source": {
                            "name": g["name"],
                            "type": "knowledge",
                            "id": str(key),
                        },
                        "document": list(g["documents"]),
                        "metadata": list(g["metadata"]),
                        "distances": list(g["distances"]),
                    }
                )

            return "\n".join(text_parts), source_events

        except Exception as e:
            log.warning(f"[_search_documents] error: {e}")
            return "", []

    @staticmethod
    def _extract_query_from_sql(sql: str) -> str:
        """SQL에서 테이블명과 조건 값을 추출하여 문서 검색 쿼리를 생성한다."""
        import re as _re

        tables = _re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, _re.IGNORECASE)
        conditions = _re.findall(r"=\s*'([^']+)'", sql)
        keywords = tables + conditions
        return " ".join(keywords) if keywords else ""

    async def _get_ddl_context(self, dbsphere_id: str, sql: str) -> str:
        """SQL에서 참조하는 테이블의 DDL 메모리를 가져온다.

        DbSphere의 SearchEngineDbSphereMemory를 사용하여 정확한 컬럼명,
        데이터 타입, 설명을 반환한다.  검색엔진 미설정 또는 DDL 없으면 빈 문자열.
        """
        import re as _re

        try:
            from extension_modules.dbsphere.memory.search_memory import (
                SearchEngineDbSphereMemory,
            )

            mem = SearchEngineDbSphereMemory(dbsphere_id)
            tables = _re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, _re.IGNORECASE)
            if not tables:
                return ""

            ddl_memories = await mem.get_table_schemas(table_names=tables)
            if not ddl_memories:
                return ""

            parts: list[str] = []
            for ddl in ddl_memories:
                cols = ", ".join(
                    f"{c.name} {c.data_type}"
                    + (" PK" if c.is_primary_key else "")
                    + (" FK" if c.is_foreign_key else "")
                    for c in (ddl.columns or [])
                )
                parts.append(f"{ddl.table_name}({cols})")
            return "Available DDL: " + "; ".join(parts)
        except Exception as e:
            log.debug(f"[_get_ddl_context] skipped: {e}")
            return ""

    async def _fetch_data(
        self,
        sql: str,
        doc_query: Optional[str] = None,
        dbsphere_id: Optional[str] = None,
        knowledge_id: Optional[str] = None,
    ) -> str:
        """KG에 연결된 DB에서 SQL을 실행하고 실제 데이터를 반환한다.

        doc_query가 제공되면 문서도 함께 검색한다.
        SQL 결과가 0행이고 doc_query가 없으면 SQL 키워드로 자동 문서 검색한다.
        """
        import json as _json

        log.info(f"[kg_fetch_data] sql='{sql[:80]}...', doc_query={doc_query}")
        if not self.kg_ids:
            return "No knowledge graph connected."

        # SELECT/WITH만 허용
        cleaned = sql.strip()
        first_word = cleaned.split()[0].upper() if cleaned else ""
        if first_word not in ("SELECT", "WITH"):
            return "Only SELECT queries are allowed."

        # DbSphere 결정
        if not dbsphere_id:
            linked = self._get_linked_dbsphere_ids()
            if not linked:
                return "No database (DbSphere) linked to this knowledge graph."
            dbsphere_id = linked[0]

        runner, name_or_err = self._create_sql_runner(dbsphere_id)
        if runner is None:
            return name_or_err

        # LIMIT 주입
        if "LIMIT" not in sql.upper():
            sql = sql.rstrip(";").strip() + " LIMIT 100"

        try:
            df = await runner.run_sql(sql)
        except Exception as e:
            log.error(f"[kg_fetch_data] SQL error: {e}")
            # SQL 에러 시 DDL 컨텍스트를 포함하여 LLM이 올바른 컬럼명으로 재시도하도록 유도
            ddl_hint = await self._get_ddl_context(dbsphere_id, sql)
            error_msg = f"SQL execution error: {e}"
            if ddl_hint:
                error_msg += f"\n\n{ddl_hint}\nPlease retry with correct column names from the DDL above."
            return error_msg

        columns = list(df.columns)
        # 프론트엔드 QueryExecutionModal이 row[col] 형태를 기대하므로
        # array of arrays가 아닌 array of objects로 변환
        data = df.head(100).to_dict(orient="records")
        total_rows = len(df)

        # CSV 저장 — visualize_data 도구가 이 파일을 읽어 차트를 생성한다
        import os
        import uuid

        _csv_dir = "data/cache/unified_agent"
        os.makedirs(_csv_dir, exist_ok=True)
        _csv_filename = f"query_results_{uuid.uuid4().hex[:8]}.csv"
        _csv_path = os.path.join(_csv_dir, _csv_filename)
        df.head(100).to_csv(_csv_path, index=False)

        # LLM 컨텍스트용 텍스트
        text = f"Query returned {total_rows} row(s), {len(columns)} column(s).\n"
        text += f"Columns: {', '.join(columns)}\n"
        text += f"FOR VISUALIZE_DATA USE FILENAME: {_csv_filename}\n"
        if data:
            text += "| " + " | ".join(str(c) for c in columns) + " |\n"
            text += "| " + " | ".join("---" for _ in columns) + " |\n"
            for row in data[:20]:
                text += "| " + " | ".join(str(row.get(c, "")) for c in columns) + " |\n"
            if total_rows > 20:
                text += f"... ({total_rows - 20} more rows)\n"

        sql_source = {
            "type": "query_execution",
            "id": "kg-query-0",
            "name": f"KG SQL: {name_or_err}",
            "sql": sql,
            "result": {
                "columns": columns,
                "data": data,
                "total_rows": total_rows,
            },
        }

        all_sources: list[dict] = [sql_source]

        # ── 문서 검색: 명시적 doc_query 또는 0행 자동 fallback ──
        effective_doc_query = doc_query
        if not effective_doc_query and total_rows == 0:
            effective_doc_query = self._extract_query_from_sql(sql)
            if effective_doc_query:
                log.info(
                    f"[kg_fetch_data] 0 rows → auto doc search: "
                    f"'{effective_doc_query[:60]}'"
                )

        if effective_doc_query:
            # KG-grounded: SQL 결과 + user_question 에서 entity 추출 →
            # KG seed 노드 → file_id 후보 좁히기. 좁히기 실패 시 단순 벡터.
            candidate_file_ids = await self._collect_file_candidates_for_doc_query(
                sql_result_columns=columns,
                sql_result_data=data,
            )
            doc_text, doc_sources = await self._search_documents(
                effective_doc_query,
                knowledge_id,
                top_k=3,
                file_ids=candidate_file_ids if candidate_file_ids else None,
            )
            if doc_text:
                grounding_note = (
                    f" (KG-grounded: {len(candidate_file_ids)} files)"
                    if candidate_file_ids
                    else ""
                )
                text += f"\n\n--- Document Results{grounding_note} ---\n" + doc_text
                all_sources.extend(doc_sources)

        # DbSphere memory 연동 — 기존 DbSphere agent 와 동일한 save+search 싸이클.
        # (1) 이전 유사 질문의 Q-SQL 쌍을 조회해 LLM 이 다음 턴에서 참고할 수 있게
        #     응답에 포함 (2) 현재 성공한 SQL 을 memory 에 저장.
        past_queries_text = await self._search_dbsphere_memory(dbsphere_id=dbsphere_id)
        if past_queries_text:
            text += "\n\n--- Similar Past Queries (for reference) ---\n"
            text += past_queries_text
        await self._save_sql_to_dbsphere_memory(dbsphere_id=dbsphere_id, sql=sql)

        return _json.dumps(
            {"text": text, "sources": all_sources},
            ensure_ascii=False,
            default=str,
        )

    def _build_dbsphere_memory(self, dbsphere_id: str):
        """DbSphere agent 와 동일한 embedding_func 주입 패턴으로 메모리 인스턴스 생성."""
        from extension_modules.dbsphere.memory.search_memory import (
            SearchEngineDbSphereMemory,
        )
        from extension_modules.search_engine import (
            generate_embedding_async,
            get_embedding_config_from_app,
        )

        embedding_config = get_embedding_config_from_app(self.app)

        async def create_embedding(text: str):
            try:
                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=self.user_id or "",
                    chat_id=self.chat_id,
                )
            except Exception as e:
                log.warning(f"[kg_fetch_data] embedding failed: {e}")
                return None

        return SearchEngineDbSphereMemory(
            app=self.app,
            dbsphere_id=dbsphere_id,
            user_id=self.user_id or "",
            embedding_func=create_embedding,
        )

    async def _search_dbsphere_memory(self, dbsphere_id: str) -> Optional[str]:
        """user_question 으로 DbSphere memory 를 조회해 참고용 컨텍스트 문자열 반환.

        sql_memory / ddl_schema / documentation / sql_example 4 타입을 통합 조회,
        None 리턴 시 응답에 붙이지 않음. 실패는 삼킨다.
        """
        if not self.user_question or len(self.user_question) < 5 or not dbsphere_id:
            return None
        try:
            from extension_modules.dbsphere.memory.models import MemoryType

            mem = self._build_dbsphere_memory(dbsphere_id)
            result = await mem.search_all_context(
                question=self.user_question,
                include_types=[
                    MemoryType.SQL_MEMORY,
                    MemoryType.DDL_SCHEMA,
                    MemoryType.DOCUMENTATION,
                    MemoryType.SQL_EXAMPLE,
                ],
                limit_per_type=3,
                similarity_threshold=0.4,
            )

            parts: list[str] = []
            sql_block = mem.format_similar_queries_for_prompt(result.sql_memories)
            if result.sql_memories:
                parts.append(sql_block)
                # few-shot 참조(주입) 로깅 — KG kg_fetch_data 경로. 비차단·실패무시.
                from extension_modules.dbsphere.memory.usage_logger import (
                    record_memory_references,
                )

                record_memory_references(
                    dbsphere_id=dbsphere_id,
                    memory_ids=[r.memory.memory_id for r in result.sql_memories],
                    user_id=self.user_id or None,
                    chat_id=self.chat_id,
                    injection_point="kg_fetch_data",
                )
            if result.ddl_memories:
                parts.append(mem.format_ddl_context_for_prompt(result.ddl_memories))
            if result.documentation:
                parts.append(mem.format_documentation_for_prompt(result.documentation))
            if result.sql_examples:
                parts.append(mem.format_sql_examples_for_prompt(result.sql_examples))
            if not parts:
                return None
            return "\n".join(parts)
        except Exception as e:
            log.warning(f"[kg_fetch_data] search_dbsphere_memory failed: {e}")
            return None

    async def _save_sql_to_dbsphere_memory(self, dbsphere_id: str, sql: str) -> None:
        """성공한 Question-SQL pair 를 DbSphere memory 에 저장.

        ``user_question`` 이 없거나 (5자 미만) dbsphere_id 가 없으면 skip.
        에러는 삼키고 로깅만 — memory 저장 실패가 SQL 결과 반환을 막으면 안 됨.
        """
        if not self.user_question or len(self.user_question) < 5:
            return
        if not dbsphere_id:
            return
        try:
            mem = self._build_dbsphere_memory(dbsphere_id)
            saved = await mem.save_sql_memory(
                question=self.user_question,
                sql=sql,
                success=True,
                metadata={
                    "user_id": self.user_id or None,
                    "chat_id": self.chat_id,
                    "origin": "llm_auto",  # KG kg_fetch_data 자동저장
                },
            )
            if saved:
                log.info(
                    f"[kg_fetch_data] saved sql_memory for dbsphere={dbsphere_id[:8]} "
                    f"q='{self.user_question[:40]}'"
                )
        except Exception as e:
            log.warning(f"[kg_fetch_data] save_sql_memory failed: {e}")

    # ─────────────────────────────────
    # Graph-first candidate collection (Phase 2 Graph-RAG)
    # ─────────────────────────────────

    async def _resolve_seed_to_nodes(self, seed: str) -> list[KGNodeModel]:
        """seed 문자열 → 후보 term/doc_entity 노드 리스트.

        1) 정확 label CI 매칭 (term, doc_entity)
        2) 안 나오면 시맨틱 검색 fallback
        """
        results: list[KGNodeModel] = []
        seen_ids: set[str] = set()
        for kg_id in self.kg_ids:
            for n in KnowledgeGraphs.find_nodes_by_label_ci(
                kg_id=kg_id,
                label=seed,
                node_types=[NodeType.TERM, NodeType.DOC_ENTITY],
                limit=10,
            ):
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    results.append(n)

        if results:
            return results

        # Fallback: semantic search
        for kg_id in self.kg_ids:
            try:
                sem = await self._get_index_service().search(
                    kg_id=kg_id,
                    query=seed,
                    top_k=5,
                    node_types=[NodeType.TERM, NodeType.DOC_ENTITY],
                )
            except Exception as e:
                log.warning(f"[_resolve_seed_to_nodes] semantic failed: {e}")
                continue
            for r in sem:
                nid = r.get("id")
                if not nid or nid in seen_ids:
                    continue
                n = KnowledgeGraphs.get_node_by_id(nid)
                if n:
                    seen_ids.add(n.id)
                    results.append(n)
        return results

    def _collect_file_candidates_from_graph(
        self,
        seed_nodes: list[KGNodeModel],
        edge_types: Optional[list[str]] = None,
    ) -> list[str]:
        """seed 노드(들)에서 출발해 후보 file_id 수집 (문서 단위).

        경로 union (dedup, 순서 보존):
          A. seed(TERM) ← mentions ← DOCUMENT → file_id
          B. seed → synonym_of → syn ← mentions ← DOCUMENT → file_id

        edge_types 필터: DOCUMENT 에 속한 doc_entity (extracted_from 으로 연결)
        중 어느 하나라도 edge_types 카탈로그 엣지를 outgoing 으로 가진 경우만
        통과. 예: edge_types=["has_requirement"] → has_requirement 엣지가 추출된
        문서만 남김.
        """
        file_ids: list[str] = []
        seen: set[str] = set()
        # LLM 이 정확한 엣지 이름 (`has_<attr>`) 대신 짧은 별칭 (`<attr>`)
        # 만 줘도 매칭되도록 KG 의 실제 엣지 카탈로그를 resolve 한다.
        # 매칭 우선순위: exact → has_<x> → endswith → contains.
        resolved_edge_types: Optional[set[str]] = None
        if edge_types:
            resolved_edge_types = set()
            # 입력된 모든 KG 의 distinct edge type union
            actual_types: set[str] = set()
            for sn in seed_nodes:
                for et, _ in KnowledgeGraphs.get_distinct_edge_types(sn.kg_id):
                    actual_types.add(et)
            for req in edge_types:
                req_l = req.strip().lower()
                if not req_l:
                    continue
                # 1) exact
                exact = {t for t in actual_types if t.lower() == req_l}
                if exact:
                    resolved_edge_types |= exact
                    continue
                # 2) has_<req> (매우 흔한 카탈로그 패턴)
                has_form = {t for t in actual_types if t.lower() == f"has_{req_l}"}
                if has_form:
                    resolved_edge_types |= has_form
                    continue
                # 3) endswith — `<prefix>_<attr>` → `<attr>` 같은 suffix 매칭
                endsw = {t for t in actual_types if t.lower().endswith("_" + req_l)}
                if endsw:
                    resolved_edge_types |= endsw
                    continue
                # 4) contains — 마지막 fallback
                contains = {t for t in actual_types if req_l in t.lower()}
                if contains:
                    resolved_edge_types |= contains

        def _doc_has_catalog_edge(doc_node_id: str, kg_id: str) -> bool:
            """doc_entity --extracted_from--> DOCUMENT 역방향으로 doc_entity 수집,
            그 doc_entity 들의 outgoing 엣지 중 resolved edge_types 에 해당하는
            게 있는지."""
            if not resolved_edge_types:
                return False
            ext_edges = KnowledgeGraphs.get_edges_for_node(
                kg_id, doc_node_id, edge_types=[EdgeType.EXTRACTED_FROM]
            )
            for ee in ext_edges:
                if ee.dst_id != doc_node_id:
                    continue
                de_id = ee.src_id
                cat_edges = KnowledgeGraphs.get_edges_for_node(
                    kg_id, de_id, edge_types=list(resolved_edge_types)
                )
                for ce in cat_edges:
                    if ce.src_id == de_id:
                        return True
            return False

        def _add_from_doc(doc_node_id: str, kg_id: str) -> None:
            doc_node = KnowledgeGraphs.get_node_by_id(doc_node_id)
            if not doc_node or doc_node.node_type != NodeType.DOCUMENT:
                return
            fid = (doc_node.properties or {}).get("file_id")
            if not fid or fid in seen:
                return
            # edge_types (카탈로그 엣지) 필터
            if resolved_edge_types and not _doc_has_catalog_edge(doc_node_id, kg_id):
                return
            seen.add(fid)
            file_ids.append(fid)

        for sn in seed_nodes:
            kg_id = sn.kg_id
            sid = sn.id

            # Path A: DOCUMENT → mentions → seed(TERM)
            for e in KnowledgeGraphs.get_edges_for_node(
                kg_id, sid, edge_types=[EdgeType.MENTIONS]
            ):
                if e.dst_id == sid:
                    _add_from_doc(e.src_id, kg_id)

            # Path B: seed → synonym_of → syn ← mentions ← DOCUMENT
            syn_edges = KnowledgeGraphs.get_edges_for_node(
                kg_id, sid, edge_types=[EdgeType.SYNONYM_OF]
            )
            for e in syn_edges:
                other = e.dst_id if e.src_id == sid else e.src_id
                if other == sid:
                    continue
                for me in KnowledgeGraphs.get_edges_for_node(
                    kg_id, other, edge_types=[EdgeType.MENTIONS]
                ):
                    if me.dst_id == other:
                        _add_from_doc(me.src_id, kg_id)

        return file_ids

    async def _fetch_document(
        self,
        query: Optional[str] = None,
        seed: Optional[str] = None,
        edge_types: Optional[list[str]] = None,
        knowledge_id: Optional[str] = None,
        top_k: int = 5,
    ) -> str:
        """KG 안 문서를 Graph-RAG 로 조회한다.

        우선순위:
          1. seed (+선택 edge_types) 그래프 트래버설 → file_id 수집
             - query 있으면: file_id 로 좁혀서 KB 벡터 검색
             - query 없으면: file_id 후보 목록만 반환
          2. seed 없고 query 만 → 기존 semantic 검색 (KB scope)
        """
        import json as _json

        log.info(
            f"[kg_fetch_document] seed='{(seed or '')[:40]}', "
            f"edge_types={edge_types}, "
            f"query='{(query or '')[:60]}', kb={knowledge_id}"
        )
        if not self.kg_ids:
            return "No knowledge graph connected."

        # Path 1: seed 기반 graph-first (file_id 필터)
        if seed:
            seed_nodes = await self._resolve_seed_to_nodes(seed)
            if not seed_nodes:
                return (
                    f'Seed "{seed}" not found in knowledge graph '
                    "(no matching term or doc_entity node)."
                )

            candidate_file_ids = self._collect_file_candidates_from_graph(
                seed_nodes, edge_types=edge_types
            )

            if not candidate_file_ids:
                et_note = f" with edge_types={edge_types}" if edge_types else ""
                return (
                    f'Seed "{seed}" matched {len(seed_nodes)} node(s) but no '
                    f"documents are linked in the graph{et_note} "
                    "(no mentions edges found)."
                )

            if query:
                text, source_events = await self._search_documents(
                    query=query,
                    top_k=top_k,
                    file_ids=candidate_file_ids,
                )
                if text:
                    return _json.dumps(
                        {"text": text, "sources": source_events},
                        ensure_ascii=False,
                        default=str,
                    )
                return (
                    f'Seed "{seed}" resolved to {len(candidate_file_ids)} '
                    "file(s) but the vector store returned no content."
                )

            return _json.dumps(
                {
                    "text": (
                        f'Seed "{seed}" → {len(candidate_file_ids)} candidate '
                        "file(s). Provide `query` to fetch document content."
                    ),
                    "file_ids": candidate_file_ids,
                    "sources": [],
                },
                ensure_ascii=False,
                default=str,
            )

        # Path 2: pure semantic (no seed)
        if query:
            text, source_events = await self._search_documents(
                query, knowledge_id, top_k
            )
            if not text:
                return f'No document chunks found for "{query}".'
            return _json.dumps(
                {"text": text, "sources": source_events},
                ensure_ascii=False,
                default=str,
            )

        return "Nothing to search: provide at least one of `seed` or `query`."

    # ─────────────────────────────────
    # kg_cypher escape hatch (read-only Cypher with semantic memory layer)
    # ─────────────────────────────────

    def _build_kg_memory(self, kg_id: str):
        """SearchEngineKGMemory 인스턴스 (DbSphere 패턴 동일 — embedding_func 주입)."""
        from extension_modules.knowledge_graph.memory import SearchEngineKGMemory
        from extension_modules.search_engine import (
            generate_embedding_async,
            get_embedding_config_from_app,
        )

        embedding_config = get_embedding_config_from_app(self.app)

        async def create_embedding(text: str):
            try:
                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=self.user_id or "",
                    chat_id=self.chat_id,
                )
            except Exception as e:
                log.warning(f"[kg_cypher] embedding failed: {e}")
                return None

        return SearchEngineKGMemory(
            app=self.app,
            kg_id=kg_id,
            user_id=self.user_id or "",
            embedding_func=create_embedding,
        )

    def _kg_options_llm_model_id(self, kg_id: str) -> Optional[str]:
        """KG 의 options.llm_model_id (judge / schema_extractor 가 사용)."""
        from open_webui.models.knowledge_graph import KnowledgeGraphs

        kg = KnowledgeGraphs.get_kg_by_id(id=kg_id)
        if not kg:
            return None
        opts = (kg.data or {}).get("options") or {}
        return opts.get("llm_model_id")

    def _resolve_kg_id(self, kg_id: Optional[str]) -> Optional[str]:
        if kg_id and kg_id in self.kg_ids:
            return kg_id
        if not kg_id and len(self.kg_ids) == 1:
            return self.kg_ids[0]
        return None

    async def _kg_cypher(
        self,
        question: str,
        cypher: str,
        kg_id: Optional[str] = None,
        max_rows: int = 100,
    ) -> str:
        """LLM 이 짠 read-only Cypher 를 안전하게 실행 + 시맨틱 메모리 layer 활용.

        흐름:
          1) memory.search_all_context(question) — schema docs / domain rules /
             cypher_example / cypher_negative / cypher_pattern 5종 통합 검색
          2) safe_execute_cypher 호출 (validation → LIMIT 자동 주입 → AGE 실행 +
             timeout)
          3) 실행 성공 + LLM judge 통과 → save_cypher_example (dedup or hit++)
             직전 같은 turn 의 실패 cypher 가 있으면 save_negative
          4) 결과를 LLM 친화적 텍스트로 직렬화 + retrieved memory 를 hint 로 첨부
             (다음 turn 에 LLM 이 더 정확한 cypher 짜도록)
        """
        import json as _json

        from extension_modules.knowledge_graph.cypher_safety import (
            CypherSafetyError,
            friendly_error,
        )
        from extension_modules.knowledge_graph.memory import (
            SearchEngineKGMemory,
            judge_cypher_result,
        )

        target_kg_id = self._resolve_kg_id(kg_id)
        if not target_kg_id:
            avail = ", ".join(self.kg_ids) if self.kg_ids else "(none)"
            return _json.dumps(
                {
                    "error": "kg_id_required",
                    "message": (
                        f"This agent has multiple KGs connected; pass kg_id "
                        f"explicitly. Available: {avail}"
                    ),
                },
                ensure_ascii=False,
            )

        question = (question or self.user_question or "").strip()
        cypher = (cypher or "").strip()
        if not cypher:
            return _json.dumps(
                {"error": "empty_cypher", "message": "cypher is required."},
                ensure_ascii=False,
            )

        memory = self._build_kg_memory(target_kg_id)
        llm_model_id = self._kg_options_llm_model_id(target_kg_id)

        # 1) 메모리 RAG — 한 번의 호출로 5종 모두 검색
        retrieved_blocks: dict = {}
        retrieved_source_events: list = []
        unified = None
        try:
            unified = await memory.search_all_context(question or cypher)
            retrieved_blocks = SearchEngineKGMemory.format_for_prompt(unified)
            retrieved_source_events = SearchEngineKGMemory.to_source_events(unified)
        except Exception as e:
            log.warning(f"[kg_cypher] memory retrieve failed: {e}")

        # 2) 실행
        age = self._get_age(target_kg_id)

        validation_error: Optional[str] = None
        execution_error: Optional[str] = None
        run_result: dict = {}
        try:
            run_result = age.safe_execute_cypher(
                cypher,
                max_rows=max_rows,
                timeout_ms=5000,
            )
        except CypherSafetyError as e:
            validation_error = str(e)
        except Exception as e:
            execution_error = friendly_error(str(e))

        # 3) 성공 시 judge → save
        executed_cypher = run_result.get("executed_cypher") or cypher
        rows = run_result.get("rows") or []
        row_count = run_result.get("row_count", 0)
        truncated = bool(run_result.get("truncated", False))
        ref_n = run_result.get("referenced_node_types") or []
        ref_e = run_result.get("referenced_edge_types") or []

        judge_meta: Optional[dict] = None
        memory_save_status: Optional[str] = None

        if validation_error is None and execution_error is None and rows:
            verdict = None
            if llm_model_id and len(question) >= 5:
                try:
                    verdict = await judge_cypher_result(
                        self.app,
                        question=question,
                        cypher=executed_cypher,
                        rows=rows,
                        total_rows=row_count,
                        llm_model_id=llm_model_id,
                    )
                except Exception as e:
                    log.warning(f"[kg_cypher] judge failed: {e}")
            if verdict:
                judge_meta = {
                    "answers_question": verdict.answers_question,
                    "confidence": verdict.confidence,
                    "reason": verdict.reason,
                }
                if verdict.answers_question and verdict.confidence >= 0.7:
                    try:
                        async with memory.session():
                            await memory.save_cypher_example(
                                question=question,
                                cypher=executed_cypher,
                                confidence=verdict.confidence,
                                normalized_question=question,
                                referenced_node_types=ref_n,
                                referenced_edge_types=ref_e,
                                chat_id=self.chat_id,
                            )
                            # in-turn negative pairing: 같은 turn 의 직전 실패가 있다면 페어 저장
                            prev = self._kg_cypher_failures.pop(question, None)
                            if prev and prev.get("kg_id") == target_kg_id:
                                await memory.save_negative(
                                    question=question,
                                    bad_cypher=prev.get("cypher", ""),
                                    error_excerpt=prev.get("error", "")[:1000],
                                    fix_cypher=executed_cypher,
                                    fix_explanation=verdict.reason,
                                    chat_id=self.chat_id,
                                )
                        memory_save_status = "saved"
                    except Exception as e:
                        log.warning(f"[kg_cypher] save failed: {e}")
                        memory_save_status = f"save_error: {e}"
                else:
                    memory_save_status = "skipped_low_confidence"
            else:
                memory_save_status = "no_judge"

        # 4) 실패 추적 (in-turn) — 다음 호출이 같은 question 으로 들어오면 negative pair
        if validation_error is not None or execution_error is not None:
            self._kg_cypher_failures[question] = {
                "kg_id": target_kg_id,
                "cypher": cypher,
                "error": validation_error or execution_error or "",
            }

        # 5) 응답 직렬화
        response: dict = {
            "kg_id": target_kg_id,
            "executed_cypher": executed_cypher,
            "row_count": row_count,
            "truncated": truncated,
            "rows": rows,
            "referenced_node_types": ref_n,
            "referenced_edge_types": ref_e,
        }
        if validation_error is not None:
            response["validation_error"] = validation_error
            response["hint"] = (
                "Fix the Cypher to comply with kg_cypher safety rules and call again."
            )
        if execution_error is not None:
            response["execution_error"] = execution_error
            response["hint"] = (
                "Use the friendly error hint to revise your Cypher and call again."
            )
        if judge_meta is not None:
            response["judge"] = judge_meta
        if memory_save_status:
            response["memory_save"] = memory_save_status
        if retrieved_blocks:
            response["semantic_context"] = retrieved_blocks

        sources: list = []
        # 실행 결과 자체는 "데이터" 이지 출처 문서가 아니므로 frontend source 로
        # 표시하지 않는다 (LLM 컨텍스트로만 사용). retrieved memory 는 audit
        # 추적이 가치 있어 source_event 로 노출한다.
        if retrieved_source_events:
            sources.extend(retrieved_source_events)

        return _json.dumps(
            {
                "text": _json.dumps(response, ensure_ascii=False, default=str),
                "sources": sources,
            },
            ensure_ascii=False,
            default=str,
        )

    # ─────────────────────────────────
    # Tool factory
    # ─────────────────────────────────

    def get_tools(self) -> list[StructuredTool]:
        """LangChain StructuredTool 리스트 반환."""
        if not self.kg_ids:
            return []

        resolve_tool = StructuredTool.from_function(
            coroutine=self._resolve_term,
            name="kg_resolve_term",
            description=(
                "Look up a business term in the knowledge graph and return its "
                "exact database column mappings with WHERE filter expressions. "
                "Call this first whenever the user's question contains a business "
                "term, customer segment, region name, KPI, metric, or any "
                "domain-specific noun (e.g. 'VIP customer', '우수 고객', "
                "'강남 지점', '월 매출', 'active subscriber'). "
                "The returned mapping tells you the correct table, column, and "
                "filter to use in your SQL — do not guess column names when this "
                "tool is available. If the term is not yet mapped, the response "
                "says 'no mappings curated yet' and you should fall back to "
                "kg_search_concepts."
            ),
            args_schema=ResolveTermInput,
        )

        search_tool = StructuredTool.from_function(
            coroutine=self._search_concepts,
            name="kg_search_concepts",
            description=(
                "Hybrid vector+graph search across the knowledge graph. "
                "Finds top-k nodes by semantic similarity (vector+BM25) and "
                "expands top results with their 1-hop graph neighbors — showing "
                "connected features, database mappings, and relationships. "
                "Call this to discover which tables, columns, entities, or "
                "business concepts exist for a given topic. "
                "Use the optional node_types filter to narrow results: "
                "['term','concept'] for business vocabulary, "
                "['table','column'] for database schema, "
                "['doc_entity'] for LLM-extracted document entities, "
                "['doc_attr'] for KB filter-derived document attribute nodes "
                "— each carries a filter slot id (properties.slot) and a "
                "value; the actual slots and values are domain-specific and "
                "discoverable via kg_explore_context or by inspecting "
                "outgoing edges of a DOCUMENT node with kg_neighbors. "
                "Both doc_entity and doc_attr are semantic nodes and returned "
                "by default. Structural nodes (document, database, "
                "knowledge_base, glossary) are excluded unless explicitly "
                "listed in node_types. "
                "Prefer kg_resolve_term first for exact business-term lookup; "
                "use this tool when kg_resolve_term returns no mapping."
            ),
            args_schema=SearchConceptsInput,
        )

        neighbors_tool = StructuredTool.from_function(
            coroutine=self._neighbors,
            name="kg_neighbors",
            description=(
                "Traverse the N-hop neighborhood of a knowledge graph node and "
                "return all directly or indirectly connected nodes. "
                "Containment edges (contains_*) are always excluded to prevent "
                "structural explosion. "
                "Call this after finding a node id via kg_search_concepts when "
                "you need to explore related concepts, columns, or tables. "
                "Use the optional edge_types filter to focus traversal: "
                "['foreign_key'] for joinable tables/columns, "
                "['synonym_of'] for terminology relationships, "
                "['maps_to'] for term-to-data mappings, "
                "['broader_than','narrower_than'] for concept hierarchies, "
                "['mentions'] to find DOCUMENT nodes that mention a term "
                "(use kg_fetch_document with seed=term to read text), "
                "['extracted_from'] for doc_entity→DOCUMENT provenance, "
                "[domain-specific catalog edges like 'has_<attr>' or "
                "'<verb>_<object>'] for attribute-style relationships. "
                "These include KB filter-derived edges that connect DOCUMENT "
                "nodes to doc_attr values — useful to keep only documents "
                "matching a specific filter value. The exact edge names are "
                "domain-specific; discover them via kg_explore_context or by "
                "listing edges on a document with kg_neighbors first. "
                "Default hops=1; use hops=2 to also find indirect relationships."
            ),
            args_schema=NeighborsInput,
        )

        related_tables_tool = StructuredTool.from_function(
            coroutine=self._find_related_tables,
            name="kg_find_related_tables",
            description=(
                "Discover tables joinable to a given table via foreign-key "
                "relationships and return ready-to-use JOIN hints "
                "(e.g. 'orders.user_id = users.id'). "
                "Call this whenever you are about to write a multi-table SQL "
                "query and need to find the correct JOIN path between tables. "
                "Saves you from guessing column names or join keys. "
                "Input is the bare table name (e.g. 'orders'), not a fully "
                "qualified id."
            ),
            args_schema=FindRelatedTablesInput,
        )

        explore_tool = StructuredTool.from_function(
            coroutine=self._explore_context,
            name="kg_explore_context",
            description=(
                "Discover table names, column names, and relationships from the "
                "knowledge graph. Returns ONLY metadata (schema info, term "
                "definitions, relationships) — NOT actual data. "
                "After calling this tool, you MUST call kg_fetch_data to "
                "execute SQL and retrieve real data. Never answer with SQL "
                "examples alone — the user expects executed results."
            ),
            args_schema=ExploreContextInput,
        )

        fetch_data_tool = StructuredTool.from_function(
            coroutine=self._fetch_data,
            name="kg_fetch_data",
            description=(
                "Execute a SELECT SQL query against the live database linked "
                "to the knowledge graph and return real rows. This is the "
                "ONLY way to get actual structured data — other kg_* tools "
                "return metadata, relationships, or documents, not rows.\n\n"
                "**MUST call this tool whenever the user asks for any "
                "attribute-of-an-entity, count, ranking, comparison, or "
                "filtered list.** Patterns include (not exhaustive):\n"
                "- attribute of a named entity (e.g. <attr> of <entity>)\n"
                "- counts / totals / averages / sums / aggregations\n"
                "- top-N / ranking / sort by\n"
                "- date / time-based filtering (latest, recent, between dates)\n"
                "- code / id / classification / category lookup\n"
                "- comparison between groups\n"
                "- 'list of X where Y' style queries\n\n"
                "If the user's question contains ANY column-style attribute "
                "(price, manufacturer, type, code, count, etc.) about an "
                "entity surfaced by kg_search_concepts or kg_explore_context, "
                "DO NOT answer from graph metadata alone — those return only "
                "labels and edges, not real values. Build SQL using table/"
                "column names from kg_explore_context and call this tool.\n\n"
                "Before writing the SQL: call kg_explore_context (or "
                "kg_resolve_term if a precise column mapping exists) to "
                "discover table/column names. Use the discovered column as "
                "the filter / projection target. When a semantic column "
                "mapping exists (via maps_to), prefer the mapped column over "
                "string LIKE on a different label column.\n"
                "SELECT list: when the user asks for named items, include "
                "the human-readable label column, not just surrogate keys.\n"
                "Pass `doc_query` to ALSO search knowledge base documents "
                "in the same call when the question mixes structured data "
                "with qualitative context. If the SQL returns 0 rows and "
                "doc_query is omitted, documents are searched automatically "
                "as fallback.\n"
                "SELECT only. Results limited to 100 rows."
            ),
            args_schema=FetchDataInput,
        )

        fetch_doc_tool = StructuredTool.from_function(
            coroutine=self._fetch_document,
            name="kg_fetch_document",
            description=(
                "Graph-RAG document fetch from the knowledge graph's linked "
                "knowledge base(s). Unlike a plain vector search, this tool "
                "uses the graph structure to narrow candidates BEFORE reading "
                "text from the vector store.\n\n"
                "Prefer `seed` over `query` whenever the user's question is "
                "anchored on a specific entity, attribute, or value. The tool "
                "will:\n"
                "  (A) resolve seed → graph TERM/DOC_ENTITY node(s),\n"
                "  (B) walk DOCUMENT --mentions--> seed (and synonym fallback) "
                "to collect candidate file_ids,\n"
                "  (C) optionally filter by `edge_types` — catalog edges "
                "attached to either the documents themselves (KB filter-"
                "derived, pattern 'has_<attr>', used to keep only documents "
                "whose filter value matches) OR edges that doc_entities "
                "extracted from the documents have outgoing (domain verbs "
                "like '<verb>_<object>'). Discover the actual edge names in "
                "this KG via kg_explore_context before choosing values here,\n"
                "  (D) vector-search the KB scoped to those file_ids "
                "with the optional `query`.\n\n"
                "Combine `seed` with `query` when the user wants a specific "
                "aspect of the entity — the query is used for vector search "
                "inside the graph-filtered file set.\n"
                "Use `query` alone only for pure semantic lookups with no "
                "known entity (definitions, general how-to, policies).\n\n"
                "For questions that also need structured data, use "
                "kg_fetch_data with its `doc_query` parameter."
            ),
            args_schema=FetchDocumentInput,
        )

        cypher_tool = StructuredTool.from_function(
            coroutine=self._kg_cypher,
            name="kg_cypher",
            description=(
                "Read-only AGE Cypher escape hatch — run a Cypher query you "
                "compose yourself when the other kg_* tools cannot answer the "
                "question (set intersection of two doc_entity slots, multi-hop "
                "traversal, anti-joins, label pattern aggregations, etc).\n\n"
                "## Schema (this KG)\n"
                "Node types include: `term` (vocabulary, may have synonyms), "
                "`concept` (broader categories), `doc_entity` "
                "(LLM-extracted attribute values from documents — slot in "
                "properties.slot, e.g. has_precaution / has_adverse_effect), "
                "`document` (`*.md` source files), `table` / `column` "
                "(DbSphere-derived schema), `database`, `knowledge_base`, "
                "`glossary`. Slot edges (has_precaution / has_indication / "
                "has_adverse_effect / has_active_ingredient / "
                "has_dosage_and_administration / has_storage_handling / etc.) "
                "originate from `document` nodes (or terms for "
                "has_active_ingredient on glossary-derived data), NOT from "
                "medication term nodes — to find medications mentioned by a "
                "document, traverse `(document)-[:mentions]->(term)`.\n\n"
                "## ID convention\n"
                "Composite ids like "
                "`kg__kb__<KBID>__entity__<SLOT_HASH>` and "
                "`kg__glossary__<GID>__term__<TID>`. Match on `n.label` for "
                "human-readable strings; match on `n.id` only when the id "
                "was returned by another kg_* tool.\n\n"
                "## AGE caveats — the tool will reject these\n"
                "- Edge alternation `[:A|B]` — REWRITE as `[r]` + "
                "`WHERE type(r) IN ['A','B']`.\n"
                "- Write clauses (CREATE / MERGE / DELETE / SET / REMOVE / "
                "DROP / DETACH / CALL) — read-only only.\n"
                "- Procedure calls (`apoc.*`) — unsupported by AGE.\n"
                "- Multiple statements separated by `;` — submit one at a time.\n"
                "- Complex `RETURN` expressions can yield unparseable agtype — "
                "prefer explicit aliases like `RETURN n.label AS label`.\n"
                "- **ORDER BY cannot reference RETURN aliases** "
                "(AGE error `could not find rte for <alias>`). "
                "Use the underlying expression — write "
                "`ORDER BY n.label` not `ORDER BY medication`. "
                "Or rebind first: "
                "`WITH n.label AS x ... RETURN x ORDER BY x`.\n\n"
                "## Auto-applied\n"
                "- `LIMIT 100` is auto-injected when missing on a non-aggregate "
                "RETURN. Override via `max_rows` (≤ 500). Pure `count()/sum()/"
                "avg()/min()/max()/collect()` is left untouched.\n"
                "- Statement timeout 5s.\n\n"
                "## Semantic memory layer\n"
                "Each call retrieves prior `cypher_example`, `kg_schema_doc`, "
                "`kg_domain_doc`, `cypher_pattern`, and `cypher_negative` "
                "memories relevant to the question and includes them in the "
                "response under `semantic_context` — read these to refine your "
                "next attempt. Successful queries are auto-saved (after an LLM "
                "judge gates on `confidence >= 0.7`); future calls will surface "
                "them as few-shot context. Same-turn retries that fix an AGE "
                "error are also paired and saved as negative examples."
            ),
            args_schema=KGCypherInput,
        )

        return [
            resolve_tool,
            search_tool,
            neighbors_tool,
            related_tables_tool,
            explore_tool,
            fetch_data_tool,
            fetch_doc_tool,
            cypher_tool,
        ]
