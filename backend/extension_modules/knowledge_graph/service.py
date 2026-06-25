"""KG 서비스 — DB CRUD wrapper + 통계 갱신.

대부분의 영속화는 `models.knowledge_graph.KnowledgeGraphTable`이 담당하고,
이 서비스는 그 위에서 통계 갱신·동기화 트리거 등 cross-cutting 동작을 묶는다.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import (
    KGNeighborhoodNode,
    KGNodeModel,
    KnowledgeGraphModel,
    KnowledgeGraphs,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class KGService:
    """KG 인스턴스 단위 동작."""

    def __init__(self, kg: KnowledgeGraphModel):
        self.kg = kg

    @classmethod
    def load(cls, kg_id: str) -> Optional["KGService"]:
        kg = KnowledgeGraphs.get_kg_by_id(kg_id)
        if not kg:
            return None
        return cls(kg)

    # ---- Stats ----

    def refresh_stats(self) -> dict:
        """노드/엣지 카운트를 다시 세서 `data.stats`에 기록."""
        node_count = KnowledgeGraphs.count_nodes(self.kg.id)
        edge_count = KnowledgeGraphs.count_edges(self.kg.id)
        data = dict(self.kg.data or {})
        stats = dict(data.get("stats") or {})
        stats.update(
            {
                "node_count": node_count,
                "edge_count": edge_count,
                "last_synced_at": int(time.time()),
            }
        )
        data["stats"] = stats
        updated = KnowledgeGraphs.update_kg_data_by_id(self.kg.id, data)
        if updated:
            self.kg = updated
        return stats

    # ---- Source config helpers ----

    @property
    def sources(self) -> dict:
        """레거시 호환 — 기존 data.sources 구조."""
        return (self.kg.data or {}).get("sources") or {}

    @property
    def knowledge_links(self) -> list:
        """지식 연결 목록 — 새 테이블 우선, legacy JSON fallback."""
        return KnowledgeGraphs.get_knowledge_links(self.kg.id)

    @property
    def glossary_ids(self) -> list[str]:
        """용어집 ID 목록 — 지식 연결(`knowledge_links`) 의 glossary_id 합집합.

        KG 에 용어집을 직접 붙이는 개념이 없어지고 모든 소스는 지식 연결을
        통해서만 편입된다. legacy 저장 경로(`data.glossary_ids` /
        `data.sources.glossary_ids`) 는 마이그레이션 전까지 fallback 으로만
        지원한다.
        """
        ids: list[str] = []
        seen: set[str] = set()
        for link in self.knowledge_links:
            gid = link.glossary_id
            if gid and gid not in seen:
                ids.append(gid)
                seen.add(gid)
        if ids:
            return ids

        # legacy fallback
        data = self.kg.data or {}
        direct = data.get("glossary_ids")
        if direct and isinstance(direct, list):
            return list(direct)
        return list(self.sources.get("glossary_ids") or [])

    @property
    def dbsphere_ids(self) -> list[str]:
        """DbSphere ID 목록 — 용어집 extraction_sources + knowledge_links 합집합.

        용어집 기반 DB 자동 sync 전환 후로는 "이 KG 에 포함되어야 할 DB" 는
        (1) 연결된 용어집의 `meta.extraction_sources` 가 가리키는 DB 와
        (2) 지식 연결(knowledge_links) 이 가리키는 DB 의 합집합이다. 레거시
        `data.sources.dbsphere_ids` 는 둘 다 비어 있을 때만 fallback 으로
        사용한다.
        """
        from extension_modules.knowledge_graph.sync.glossary_sync import (
            get_referenced_dbsphere_ids,
        )

        ids: list[str] = []
        seen: set[str] = set()

        # (1) 용어집 extraction_sources 에서 수집
        for glossary_id in self.glossary_ids:
            try:
                for db_id in get_referenced_dbsphere_ids(glossary_id):
                    if db_id and db_id not in seen:
                        ids.append(db_id)
                        seen.add(db_id)
            except Exception as e:
                log.warning(
                    f"[KGService] failed to collect dbsphere from glossary "
                    f"{glossary_id[:8]}: {e}"
                )

        # (2) 지식 연결에서 수집
        for link in self.knowledge_links:
            db_id = link.dbsphere_id
            if db_id and db_id not in seen:
                ids.append(db_id)
                seen.add(db_id)

        if ids:
            return ids
        # 레거시 fallback
        return list(self.sources.get("dbsphere_ids") or [])

    @property
    def knowledge_ids(self) -> list[str]:
        """KB ID 목록 — knowledge_links에서 수집 + 레거시 fallback."""
        ids: list[str] = []
        seen: set[str] = set()
        for link in self.knowledge_links:
            for kb_id in link.knowledge_ids or []:
                if kb_id and kb_id not in seen:
                    ids.append(kb_id)
                    seen.add(kb_id)
        if ids:
            return ids
        # 레거시 fallback
        return list(self.sources.get("knowledge_ids") or [])

    # ---- Read passthroughs ----

    def get_nodes(
        self,
        node_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KGNodeModel]:
        return KnowledgeGraphs.get_nodes(
            self.kg.id, node_type=node_type, limit=limit, offset=offset
        )

    def get_neighbors(
        self,
        node_id: str,
        hops: int = 1,
        edge_types: Optional[list[str]] = None,
        limit: int = 200,
    ) -> list[KGNeighborhoodNode]:
        return KnowledgeGraphs.get_neighbors(
            self.kg.id,
            node_id=node_id,
            hops=hops,
            edge_types=edge_types,
            limit=limit,
        )
