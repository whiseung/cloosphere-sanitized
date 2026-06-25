"""KG 노드 검색 인덱싱 서비스.

Cloosphere `search_engine` 추상화를 그대로 사용한다. 따라서 백엔드(Azure AI
Search / Elasticsearch / pgvector / Vertex)는 관리자 페이지의 RAG 설정으로
결정되며, KG 모듈은 어떤 백엔드인지 신경쓰지 않는다.

설계 노트:
- 인덱스 이름: `{prefix}_kg_node` (글로벌 단일, KG는 `collection` 필드로 분리)
- 임베딩: Glossary 모듈의 `generate_embedding`을 그대로 재사용
- 검색 엔진 미설정 시: 모든 인덱싱·검색 호출이 graceful fallback (no-op).
  KG 그래프 구조 자체는 PG에 그대로 있으므로 read 경로는 영향 없음.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from extension_modules.glossary.embedding import (
    generate_embedding,
    get_vector_dimension,
)
from extension_modules.search_engine import (
    DocumentItem,
    create_kg_node_config,
    get_configured_search_engine,
)
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import KGNodeModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class KGNodeIndexService:
    """KG 노드를 search engine에 인덱싱/검색/삭제."""

    def __init__(self, app):
        self.app = app

    def _build_engine(self):
        """search engine 인스턴스 생성. 미설정 시 None 반환."""
        try:
            vector_dim = get_vector_dimension(self.app)
        except Exception:
            vector_dim = 3072
        index_config = create_kg_node_config(vector_dim=vector_dim)
        return get_configured_search_engine(self.app, index_config)

    @staticmethod
    def _embedding_text(node: KGNodeModel) -> str:
        """노드의 임베딩 대상 텍스트.

        label을 가장 무겁게 잡고, properties에 description이 있으면 추가.
        column 노드의 경우 table_name + column_name + data_type을 함께 줘서
        시맨틱 매칭을 강화한다.
        """
        parts: list[str] = [node.label]
        props = node.properties or {}

        # 공통 description
        desc = props.get("description")
        if desc:
            parts.append(str(desc))

        # column 특화: table.column + 데이터 타입
        if node.node_type == "column":
            table = props.get("table_name")
            data_type = props.get("data_type")
            if table:
                parts.append(f"table {table}")
            if data_type:
                parts.append(f"type {data_type}")

        # term 특화: synonym 정보가 properties에 있으면 포함
        if node.node_type == "term":
            cat = props.get("category")
            if cat:
                parts.append(f"category {cat}")
            example = props.get("example")
            if example:
                parts.append(str(example))

        return "\n".join(p for p in parts if p)

    @staticmethod
    def _source_kind(node: KGNodeModel) -> str:
        """source_ref에서 kind 추출."""
        ref = node.source_ref or {}
        return ref.get("kind") or "manual"

    def _to_document(self, kg_id: str, node: KGNodeModel) -> DocumentItem:
        text = self._embedding_text(node)
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "label": node.label,
            "node_type": node.node_type,
            "source_kind": self._source_kind(node),
            "source_ref": node.source_ref,
            "properties": node.properties,
            "user_id": node.user_id,
            "created_at": now,
        }
        return DocumentItem(
            id=node.id,
            content=text,
            metadata=metadata,
            collection=kg_id,
        )

    # ──────────────────────────────────────────────
    # Indexing
    # ──────────────────────────────────────────────

    async def index_nodes(self, kg_id: str, nodes: list[KGNodeModel]) -> int:
        """노드 리스트를 임베딩 + 인덱싱.

        Returns:
            인덱싱된 노드 수. search engine 미설정/에러 시 0.
        """
        if not nodes:
            return 0

        engine = self._build_engine()
        if not engine:
            log.info(
                "KG node indexing skipped — search engine not configured. "
                "Graph structure remains usable; only semantic search is unavailable."
            )
            return 0

        # 임베딩 텍스트 일괄 생성 → 일괄 임베딩
        texts = [self._embedding_text(n) for n in nodes]
        try:
            vectors = generate_embedding(self.app, texts)
        except ValueError as e:
            log.warning(f"KG node indexing skipped — embedding not configured: {e}")
            return 0
        except Exception as e:
            log.exception(f"KG node embedding failed: {e}")
            return 0

        # 단일 입력일 때 generate_embedding이 단일 vector를 줄 수 있음
        if vectors and not isinstance(vectors[0], list):
            vectors = [vectors]

        documents: list[DocumentItem] = []
        for node, vector in zip(nodes, vectors):
            doc = self._to_document(kg_id, node)
            doc.vector = vector
            documents.append(doc)

        try:
            async with engine:
                if not await engine.index_exists():
                    log.info("Creating KG node index")
                    await engine.create_index()
                count = await engine.update(documents)
            log.info(
                f"Indexed {count} KG nodes (kg_id={kg_id}, total submitted={len(documents)})"
            )
            return count
        except Exception as e:
            log.exception(f"KG node indexing failed: {e}")
            return 0

    # ──────────────────────────────────────────────
    # Deletion
    # ──────────────────────────────────────────────

    async def delete_by_kg(self, kg_id: str) -> int:
        """KG 인스턴스의 모든 노드 삭제. 미설정 시 0."""
        engine = self._build_engine()
        if not engine:
            return 0
        try:
            async with engine:
                if not await engine.index_exists():
                    return 0
                filter_expr = f"collection eq '{kg_id}'"
                count = await engine.delete_by_filter(filter_expr)
                log.info(f"Deleted {count} KG nodes from index (kg_id={kg_id})")
                return count
        except Exception as e:
            log.exception(f"KG node delete_by_kg failed: {e}")
            return 0

    async def delete_by_source(
        self, kg_id: str, source_kind: str, source_id: str
    ) -> int:
        """특정 소스(용어집/DbSphere)에서 온 노드만 삭제.

        prefix 기반으로 ID 필터링이 어려운 백엔드도 있어, 일단은 metadata 필터로 처리.
        """
        engine = self._build_engine()
        if not engine:
            return 0
        try:
            async with engine:
                if not await engine.index_exists():
                    return 0
                # source_ref가 metadata 안에 들어있으므로 source_kind 필터로 처리.
                # 단, 같은 KG에 같은 소스 종류가 여러 개일 수 있어 source_id로도
                # 구분이 필요하지만, 백엔드별 필터 표현력이 다르다. 안전한 전략:
                # PG 측에서 노드 삭제 후 indexing 재호출 시 자연스럽게 정리되도록 둠.
                # 여기서는 source_kind 단위 광범위 삭제만 지원.
                filter_expr = (
                    f"collection eq '{kg_id}' and source_kind eq '{source_kind}'"
                )
                count = await engine.delete_by_filter(filter_expr)
                log.info(
                    f"Deleted {count} KG nodes from index "
                    f"(kg_id={kg_id}, source_kind={source_kind}, source_id={source_id})"
                )
                return count
        except Exception as e:
            log.exception(f"KG node delete_by_source failed: {e}")
            return 0

    # ──────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────

    async def search(
        self,
        kg_id: str,
        query: str,
        top_k: int = 10,
        node_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """KG 노드 시맨틱 검색 (vector + BM25 hybrid).

        Returns:
            [{"id", "label", "node_type", "score", "source_kind", "properties"}]
            검색 엔진 미설정 시 빈 리스트.
        """
        engine = self._build_engine()
        if not engine:
            log.info("KG node search unavailable — search engine not configured")
            return []

        # 쿼리 임베딩
        try:
            vectors = generate_embedding(self.app, query)
        except Exception as e:
            log.warning(f"KG search embedding failed: {e}")
            return []
        if isinstance(vectors[0], list):
            vector = vectors[0]
        else:
            vector = vectors

        # 필터 식 구성
        filter_parts = [f"collection eq '{kg_id}'"]
        if node_types:
            type_clauses = " or ".join(f"node_type eq '{t}'" for t in node_types)
            filter_parts.append(f"({type_clauses})")
        filter_expr = " and ".join(filter_parts)

        try:
            async with engine:
                if not await engine.index_exists():
                    return []
                results = await engine.hybrid_search(
                    text=query,
                    vector=vector,
                    top_k=top_k,
                    filter_expr=filter_expr,
                )
        except Exception as e:
            log.exception(f"KG node search failed: {e}")
            return []

        output: list[dict] = []
        for r in results:
            md = r.metadata or {}
            output.append(
                {
                    "id": r.id,
                    "label": md.get("label") or "",
                    "node_type": md.get("node_type") or "",
                    "source_kind": md.get("source_kind") or "",
                    "score": r.score,
                    "properties": md.get("properties") or {},
                }
            )
        return output
