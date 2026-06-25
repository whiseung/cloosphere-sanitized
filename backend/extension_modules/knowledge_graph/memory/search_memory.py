"""KG 시맨틱 메모리 — search_engine 추상화 위에 5개 메모리 타입 운영.

DbSphere `SearchEngineDbSphereMemory` 의 사이블링 — API 표면도 의도적으로
유사하게 맞춰 `tools.py` 에서 두 모듈을 비슷한 모양으로 호출할 수 있게 한다.
다만 DbSphere 의 `delete_memories_by_table_name` 같은 SQL-스키마 특유 quirk 는
가져오지 않고, 대신 KG 특유의 두 기능을 추가:

  1. `dedup_or_increment` — 기존 cypher_example 과 question similarity ≥ 0.92
     + Cypher token Jaccard ≥ 0.8 면 신규 insert 대신 hit_count++ & last_used
     갱신. 메모리 폭증 방지 + "자주 등장하는 질의" 가 자연스럽게 가중치를 갖게.
  2. `mark_stale_by_referenced_types` — KG sync 시 사라진 node_type/edge_type
     참조 메모리를 stale=true 마킹. retrieval 에서 자동 제외.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from extension_modules.knowledge_graph.memory.models import (
    CypherExampleMemory,
    CypherExampleSearchResult,
    CypherNegativeMemory,
    CypherNegativeSearchResult,
    CypherPatternMemory,
    CypherPatternSearchResult,
    KGDomainDocMemory,
    KGDomainDocSearchResult,
    KGSchemaDocMemory,
    KGSchemaDocSearchResult,
    KGUnifiedSearchResult,
    MemoryType,
)
from extension_modules.search_engine import (
    DocumentItem,
    IndexConfig,
    SearchEngineBase,
    create_kg_memory_config,
    get_configured_search_engine,
)

logger = logging.getLogger(__name__)

# Dedup threshold: question similarity AND token Jaccard 둘 다 통과해야 dedup.
# 0.92 / 0.8 은 plan agent 권고. 너무 낮으면 의도적으로 다른 패턴이 합쳐지고
# 너무 높으면 거의 모든 example 이 별개로 누적됨.
_DEDUP_QUESTION_SIM = 0.92
_DEDUP_CYPHER_JACCARD = 0.80


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cypher_tokens(cypher: str) -> set[str]:
    """Cypher 의 단어/연산 토큰을 lowercase set 으로. Jaccard 계산용."""
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[<>]?[-=]+>?", cypher.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _final_score(similarity: float, confidence: float, hit_count: int) -> float:
    """cypher_example 재정렬 score: 의도적으로 hit_count 항이 self-improving 시그널."""
    sim = max(0.0, min(1.0, float(similarity or 0.0)))
    conf = max(0.0, min(1.0, float(confidence or 0.0)))
    hits = max(0, int(hit_count or 0))
    return 0.6 * sim + 0.25 * conf + 0.15 * math.log(1 + hits)


class SearchEngineKGMemory:
    """KG 인스턴스(`kg_id`)별 시맨틱 메모리 게이트웨이."""

    def __init__(
        self,
        app,
        kg_id: str,
        user_id: str = "",
        embedding_func: Optional[Callable[[str], Any]] = None,
        vector_dim: int = 3072,
    ):
        self.app = app
        self.kg_id = kg_id
        self.user_id = user_id
        self.embedding_func = embedding_func
        self.vector_dim = vector_dim
        self.index_config: IndexConfig = create_kg_memory_config(vector_dim=vector_dim)

        self._engine: Optional[SearchEngineBase] = None
        self._session_active: bool = False

    # ── 엔진/세션 ────────────────────────────────────────────────────────

    def _get_engine(self) -> Optional[SearchEngineBase]:
        if self._engine is None:
            self._engine = get_configured_search_engine(self.app, self.index_config)
        return self._engine

    @asynccontextmanager
    async def session(self):
        """여러 save/search 호출 간 engine 을 열어둔다 (DbSphere 동일 패턴)."""
        engine = self._get_engine()
        if engine is None or self._session_active:
            yield
            return
        self._session_active = True
        try:
            async with engine:
                yield
        finally:
            self._session_active = False

    @asynccontextmanager
    async def _engine_ctx(self, engine: SearchEngineBase):
        if self._session_active:
            yield
        else:
            async with engine:
                yield

    async def _create_embedding(self, text: str) -> Optional[List[float]]:
        if not self.embedding_func or not text:
            return None
        try:
            return await self.embedding_func(text)
        except Exception as e:
            logger.warning(f"[kg_memory] embedding failed: {e}")
            return None

    async def _ensure_index(self, engine: SearchEngineBase) -> bool:
        try:
            if not await engine.index_exists():
                await engine.create_index()
            return True
        except Exception as e:
            logger.error(f"[kg_memory] ensure index failed: {e}")
            return False

    # ── 공통 검색 헬퍼 ───────────────────────────────────────────────────

    def _base_filter(
        self, entity_type: MemoryType, *, include_stale: bool = False
    ) -> str:
        """collection + entity_type + (stale 필터)."""
        parts = [
            f"collection eq '{self.kg_id}'",
            f"entity_type eq '{entity_type.value}'",
        ]
        if not include_stale:
            # stale 필드는 boolean. False 또는 null 모두 제외하지 않음 — null 도 stale 로 간주하지 않음.
            parts.append("(stale eq false or stale eq null)")
        return " and ".join(parts)

    async def _search_one_type(
        self,
        engine: SearchEngineBase,
        entity_type: MemoryType,
        question_vector: List[float],
        limit: int,
        extra_filter: Optional[str] = None,
    ) -> List[Any]:
        from extension_modules.search_engine.models import SearchQuery

        filter_expr = self._base_filter(entity_type)
        if extra_filter:
            filter_expr += f" and ({extra_filter})"
        query = SearchQuery(
            query="",  # 검색 텍스트는 안 씀, vector 만
            filter=filter_expr,
            top_k=limit,
            top_k_vector=limit * 3,
        )
        try:
            return await engine.search(query=query, query_vector=question_vector)
        except Exception as e:
            logger.warning(f"[kg_memory] search {entity_type.value} failed: {e}")
            return []

    # =========================================================================
    # cypher_example: positive 학습 게이트
    # =========================================================================

    async def save_cypher_example(
        self,
        question: str,
        cypher: str,
        *,
        confidence: float,
        normalized_question: Optional[str] = None,
        referenced_node_types: Optional[List[str]] = None,
        referenced_edge_types: Optional[List[str]] = None,
        chat_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CypherExampleMemory]:
        """성공 + judge 통과한 Question-Cypher 페어 저장.

        dedup 통과 시 hit_count++ 갱신, 미통과 시 신규 insert. confidence 는
        호출자(judge 결과)가 0..1 로 넘겨야 함. 호출 시점에 retrieval 가중치
        결정에 사용된다.
        """
        engine = self._get_engine()
        if not engine:
            return None

        norm = (normalized_question or question).strip()
        emb_text = f"{norm}\n{cypher}"
        vector = await self._create_embedding(emb_text)
        if not vector:
            return None

        async with self._engine_ctx(engine):
            await self._ensure_index(engine)

            # Dedup 검사: 기존 top-1 example 과 question similarity + Cypher Jaccard
            existing = await self._search_one_type(
                engine, MemoryType.CYPHER_EXAMPLE, vector, limit=1
            )
            if existing:
                top = existing[0]
                top_sim = float(getattr(top, "score", 0.0) or 0.0)
                top_meta = getattr(top, "metadata", {}) or {}
                top_cypher = top_meta.get("cypher") or ""
                if (
                    top_sim >= _DEDUP_QUESTION_SIM
                    and _jaccard(_cypher_tokens(top_cypher), _cypher_tokens(cypher))
                    >= _DEDUP_CYPHER_JACCARD
                ):
                    # 기존 row 의 hit_count 증가
                    new_hit = int(top_meta.get("hit_count", 1)) + 1
                    new_meta = dict(top_meta)
                    new_meta["hit_count"] = new_hit
                    new_meta["last_used"] = _now_iso()
                    try:
                        await engine.update(
                            doc_id=top.id,
                            content=norm,
                            vector=vector,
                            metadata=new_meta,
                        )
                    except Exception as e:
                        logger.warning(f"[kg_memory] hit_count update failed: {e}")
                    return CypherExampleMemory(
                        memory_id=top.id,
                        question=question,
                        cypher=cypher,
                        confidence=float(top_meta.get("confidence", confidence)),
                        hit_count=new_hit,
                        last_used=new_meta["last_used"],
                        normalized_question=norm,
                        referenced_node_types=top_meta.get("referenced_node_types")
                        or [],
                        referenced_edge_types=top_meta.get("referenced_edge_types")
                        or [],
                        timestamp=top_meta.get("created_at"),
                        stale=False,
                        metadata=top_meta,
                    )

            # 신규 insert
            mid = str(uuid.uuid4())
            now = _now_iso()
            doc_meta = {
                "entity_type": MemoryType.CYPHER_EXAMPLE.value,
                "stale": False,
                "cypher": cypher,
                "question": question,
                "normalized_question": norm,
                "confidence": float(confidence),
                "hit_count": 1,
                "last_used": now,
                "referenced_node_types": referenced_node_types or [],
                "referenced_edge_types": referenced_edge_types or [],
                "user_id": self.user_id,
                "chat_id": chat_id,
                "created_at": now,
                **(metadata or {}),
            }
            doc = DocumentItem(
                id=mid,
                content=norm,
                vector=vector,
                collection=self.kg_id,
                metadata=doc_meta,
            )
            try:
                await engine.insert([doc])
            except Exception as e:
                logger.error(f"[kg_memory] insert cypher_example failed: {e}")
                return None
            return CypherExampleMemory(
                memory_id=mid,
                question=question,
                cypher=cypher,
                confidence=float(confidence),
                hit_count=1,
                last_used=now,
                normalized_question=norm,
                referenced_node_types=referenced_node_types or [],
                referenced_edge_types=referenced_edge_types or [],
                timestamp=now,
                stale=False,
                metadata=doc_meta,
            )

    async def search_cypher_examples(
        self,
        question: str,
        limit: int = 3,
        question_vector: Optional[List[float]] = None,
    ) -> List[CypherExampleSearchResult]:
        """top-K cypher_example. final_score 기준 재정렬.

        retrieval 시 stale=true 인 row 는 _base_filter 단계에서 자동 제외.
        """
        engine = self._get_engine()
        if not engine:
            return []

        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return []

        async with self._engine_ctx(engine):
            raw = await self._search_one_type(
                engine, MemoryType.CYPHER_EXAMPLE, vec, limit=max(limit * 2, limit)
            )

        scored: List[CypherExampleSearchResult] = []
        for r in raw:
            meta = r.metadata or {}
            mem = CypherExampleMemory(
                memory_id=r.id,
                question=meta.get("question", ""),
                cypher=meta.get("cypher", ""),
                confidence=float(meta.get("confidence", 0.0)),
                hit_count=int(meta.get("hit_count", 1)),
                last_used=meta.get("last_used"),
                normalized_question=meta.get("normalized_question"),
                referenced_node_types=meta.get("referenced_node_types") or [],
                referenced_edge_types=meta.get("referenced_edge_types") or [],
                timestamp=meta.get("created_at"),
                stale=bool(meta.get("stale", False)),
                metadata=meta,
            )
            sim = float(r.score or 0.0)
            scored.append(
                CypherExampleSearchResult(
                    memory=mem,
                    similarity_score=sim,
                    final_score=_final_score(sim, mem.confidence, mem.hit_count),
                    rank=0,
                )
            )

        scored.sort(key=lambda x: x.final_score, reverse=True)
        scored = scored[:limit]
        for i, s in enumerate(scored):
            s.rank = i + 1
        return scored

    # =========================================================================
    # kg_schema_doc: 노드/엣지 타입 LLM 설명
    # =========================================================================

    async def upsert_schema_doc(
        self,
        type_name: str,
        schema_role: str,
        description: str,
        sample_labels: Optional[List[str]] = None,
        sample_props: Optional[List[str]] = None,
        degree_stats: Optional[Dict[str, Any]] = None,
        source_hash: Optional[str] = None,
    ) -> Optional[KGSchemaDocMemory]:
        """KGSchemaExtractor 가 호출. (kg_id, type_name, schema_role) 키로 upsert.

        source_hash 로 재생성 dedup — 동일 hash 이면 skip.
        """
        engine = self._get_engine()
        if not engine:
            return None

        emb_text = (
            f"{schema_role} {type_name}: {description}\n"
            f"sample labels: {', '.join((sample_labels or [])[:5])}"
        )
        vector = await self._create_embedding(emb_text)
        if not vector:
            return None

        async with self._engine_ctx(engine):
            await self._ensure_index(engine)

            # 기존 동일 (type_name, schema_role) row 검색 후 source_hash 비교
            existing = await self._search_one_type(
                engine,
                MemoryType.KG_SCHEMA_DOC,
                vector,
                limit=5,
                extra_filter=f"schema_role eq '{schema_role}'",
            )
            for r in existing or []:
                meta = r.metadata or {}
                if meta.get("type_name") == type_name:
                    if source_hash and meta.get("source_hash") == source_hash:
                        # 동일 hash → 갱신 불필요
                        return None
                    # type_name 동일하지만 hash 다름 → 갱신
                    new_meta = dict(meta)
                    new_meta.update(
                        {
                            "description": description,
                            "sample_labels": sample_labels or [],
                            "sample_props": sample_props or [],
                            "degree_stats": degree_stats or {},
                            "source_hash": source_hash,
                            "updated_at": _now_iso(),
                            "stale": False,
                        }
                    )
                    try:
                        await engine.update(
                            doc_id=r.id,
                            content=emb_text,
                            vector=vector,
                            metadata=new_meta,
                        )
                    except Exception as e:
                        logger.warning(f"[kg_memory] schema_doc update failed: {e}")
                        return None
                    return KGSchemaDocMemory(
                        memory_id=r.id,
                        type_name=type_name,
                        schema_role=schema_role,
                        description=description,
                        sample_labels=sample_labels or [],
                        sample_props=sample_props or [],
                        degree_stats=degree_stats or {},
                        source_hash=source_hash,
                        timestamp=meta.get("created_at"),
                        stale=False,
                        metadata=new_meta,
                    )

            # 신규
            mid = str(uuid.uuid4())
            now = _now_iso()
            doc_meta = {
                "entity_type": MemoryType.KG_SCHEMA_DOC.value,
                "schema_role": schema_role,
                "stale": False,
                "type_name": type_name,
                "description": description,
                "sample_labels": sample_labels or [],
                "sample_props": sample_props or [],
                "degree_stats": degree_stats or {},
                "source_hash": source_hash,
                "created_at": now,
            }
            doc = DocumentItem(
                id=mid,
                content=emb_text,
                vector=vector,
                collection=self.kg_id,
                metadata=doc_meta,
            )
            try:
                await engine.insert([doc])
            except Exception as e:
                logger.error(f"[kg_memory] insert schema_doc failed: {e}")
                return None
            return KGSchemaDocMemory(
                memory_id=mid,
                type_name=type_name,
                schema_role=schema_role,
                description=description,
                sample_labels=sample_labels or [],
                sample_props=sample_props or [],
                degree_stats=degree_stats or {},
                source_hash=source_hash,
                timestamp=now,
                stale=False,
                metadata=doc_meta,
            )

    async def search_schema_docs(
        self,
        question: str,
        limit: int = 3,
        question_vector: Optional[List[float]] = None,
    ) -> List[KGSchemaDocSearchResult]:
        engine = self._get_engine()
        if not engine:
            return []
        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return []
        async with self._engine_ctx(engine):
            raw = await self._search_one_type(
                engine, MemoryType.KG_SCHEMA_DOC, vec, limit
            )
        results = []
        for i, r in enumerate(raw):
            meta = r.metadata or {}
            mem = KGSchemaDocMemory(
                memory_id=r.id,
                type_name=meta.get("type_name", ""),
                schema_role=meta.get("schema_role", ""),
                description=meta.get("description", ""),
                sample_labels=meta.get("sample_labels") or [],
                sample_props=meta.get("sample_props") or [],
                degree_stats=meta.get("degree_stats") or {},
                source_hash=meta.get("source_hash"),
                timestamp=meta.get("created_at"),
                stale=bool(meta.get("stale", False)),
                metadata=meta,
            )
            results.append(
                KGSchemaDocSearchResult(
                    memory=mem, similarity_score=float(r.score or 0.0), rank=i + 1
                )
            )
        return results

    # =========================================================================
    # kg_domain_doc: 비즈니스 규칙 / AGE caveat
    # =========================================================================

    async def save_domain_doc(
        self,
        title: str,
        content: str,
        doc_type: str,
        related_node_types: Optional[List[str]] = None,
        related_edge_types: Optional[List[str]] = None,
        author: Optional[str] = None,
    ) -> Optional[KGDomainDocMemory]:
        engine = self._get_engine()
        if not engine:
            return None
        emb_text = f"{title}\n{content}"
        vector = await self._create_embedding(emb_text)
        if not vector:
            return None

        async with self._engine_ctx(engine):
            await self._ensure_index(engine)
            mid = str(uuid.uuid4())
            now = _now_iso()
            doc_meta = {
                "entity_type": MemoryType.KG_DOMAIN_DOC.value,
                "doc_type": doc_type,
                "stale": False,
                "title": title,
                "content": content,
                "related_node_types": related_node_types or [],
                "related_edge_types": related_edge_types or [],
                "author": author or self.user_id or "system",
                "created_at": now,
            }
            doc = DocumentItem(
                id=mid,
                content=emb_text,
                vector=vector,
                collection=self.kg_id,
                metadata=doc_meta,
            )
            try:
                await engine.insert([doc])
            except Exception as e:
                logger.error(f"[kg_memory] insert domain_doc failed: {e}")
                return None
            return KGDomainDocMemory(
                memory_id=mid,
                title=title,
                content=content,
                doc_type=doc_type,
                related_node_types=related_node_types or [],
                related_edge_types=related_edge_types or [],
                author=doc_meta["author"],
                timestamp=now,
                stale=False,
                metadata=doc_meta,
            )

    async def search_domain_docs(
        self,
        question: str,
        limit: int = 3,
        question_vector: Optional[List[float]] = None,
    ) -> List[KGDomainDocSearchResult]:
        engine = self._get_engine()
        if not engine:
            return []
        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return []
        async with self._engine_ctx(engine):
            raw = await self._search_one_type(
                engine, MemoryType.KG_DOMAIN_DOC, vec, limit
            )
        results = []
        for i, r in enumerate(raw):
            meta = r.metadata or {}
            mem = KGDomainDocMemory(
                memory_id=r.id,
                title=meta.get("title", ""),
                content=meta.get("content", ""),
                doc_type=meta.get("doc_type", ""),
                related_node_types=meta.get("related_node_types") or [],
                related_edge_types=meta.get("related_edge_types") or [],
                author=meta.get("author"),
                timestamp=meta.get("created_at"),
                stale=bool(meta.get("stale", False)),
                metadata=meta,
            )
            results.append(
                KGDomainDocSearchResult(
                    memory=mem, similarity_score=float(r.score or 0.0), rank=i + 1
                )
            )
        return results

    # =========================================================================
    # cypher_pattern: 정형 트래버설 템플릿
    # =========================================================================

    async def save_pattern(
        self,
        name: str,
        description: str,
        template_cypher: str,
        slots: Optional[List[str]] = None,
        use_case: Optional[str] = None,
        candidate_id: Optional[str] = None,
        promoted_from_examples: Optional[List[str]] = None,
    ) -> Optional[CypherPatternMemory]:
        engine = self._get_engine()
        if not engine:
            return None
        emb_text = f"{name}\n{description}\n{use_case or ''}"
        vector = await self._create_embedding(emb_text)
        if not vector:
            return None

        async with self._engine_ctx(engine):
            await self._ensure_index(engine)
            mid = str(uuid.uuid4())
            now = _now_iso()
            doc_meta = {
                "entity_type": MemoryType.CYPHER_PATTERN.value,
                "stale": False,
                "name": name,
                "description": description,
                "template_cypher": template_cypher,
                "slots": slots or [],
                "use_case": use_case,
                "candidate_id": candidate_id,
                "promoted_from_examples": promoted_from_examples or [],
                "created_at": now,
            }
            doc = DocumentItem(
                id=mid,
                content=emb_text,
                vector=vector,
                collection=self.kg_id,
                metadata=doc_meta,
            )
            try:
                await engine.insert([doc])
            except Exception as e:
                logger.error(f"[kg_memory] insert pattern failed: {e}")
                return None
            return CypherPatternMemory(
                memory_id=mid,
                name=name,
                description=description,
                template_cypher=template_cypher,
                slots=slots or [],
                use_case=use_case,
                candidate_id=candidate_id,
                promoted_from_examples=promoted_from_examples or [],
                timestamp=now,
                stale=False,
                metadata=doc_meta,
            )

    async def search_patterns(
        self,
        question: str,
        limit: int = 3,
        question_vector: Optional[List[float]] = None,
    ) -> List[CypherPatternSearchResult]:
        engine = self._get_engine()
        if not engine:
            return []
        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return []
        async with self._engine_ctx(engine):
            raw = await self._search_one_type(
                engine, MemoryType.CYPHER_PATTERN, vec, limit
            )
        results = []
        for i, r in enumerate(raw):
            meta = r.metadata or {}
            mem = CypherPatternMemory(
                memory_id=r.id,
                name=meta.get("name", ""),
                description=meta.get("description", ""),
                template_cypher=meta.get("template_cypher", ""),
                slots=meta.get("slots") or [],
                use_case=meta.get("use_case"),
                candidate_id=meta.get("candidate_id"),
                promoted_from_examples=meta.get("promoted_from_examples") or [],
                timestamp=meta.get("created_at"),
                stale=bool(meta.get("stale", False)),
                metadata=meta,
            )
            results.append(
                CypherPatternSearchResult(
                    memory=mem, similarity_score=float(r.score or 0.0), rank=i + 1
                )
            )
        return results

    # =========================================================================
    # cypher_negative: 실패 → fix 페어
    # =========================================================================

    async def save_negative(
        self,
        question: str,
        bad_cypher: str,
        error_excerpt: str,
        fix_cypher: str,
        fix_explanation: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> Optional[CypherNegativeMemory]:
        engine = self._get_engine()
        if not engine:
            return None
        emb_text = f"{question}\n{error_excerpt}\nFIX: {fix_cypher}"
        vector = await self._create_embedding(emb_text)
        if not vector:
            return None

        async with self._engine_ctx(engine):
            await self._ensure_index(engine)
            mid = str(uuid.uuid4())
            now = _now_iso()
            doc_meta = {
                "entity_type": MemoryType.CYPHER_NEGATIVE.value,
                "stale": False,
                "question": question,
                "bad_cypher": bad_cypher,
                "error_excerpt": (error_excerpt or "")[:1000],
                "fix_cypher": fix_cypher,
                "fix_explanation": fix_explanation,
                "chat_id": chat_id,
                "created_at": now,
            }
            doc = DocumentItem(
                id=mid,
                content=emb_text,
                vector=vector,
                collection=self.kg_id,
                metadata=doc_meta,
            )
            try:
                await engine.insert([doc])
            except Exception as e:
                logger.error(f"[kg_memory] insert negative failed: {e}")
                return None
            return CypherNegativeMemory(
                memory_id=mid,
                question=question,
                bad_cypher=bad_cypher,
                error_excerpt=error_excerpt,
                fix_cypher=fix_cypher,
                fix_explanation=fix_explanation,
                chat_id=chat_id,
                timestamp=now,
                stale=False,
                metadata=doc_meta,
            )

    async def search_negatives(
        self,
        question: str,
        limit: int = 2,
        question_vector: Optional[List[float]] = None,
    ) -> List[CypherNegativeSearchResult]:
        engine = self._get_engine()
        if not engine:
            return []
        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return []
        async with self._engine_ctx(engine):
            raw = await self._search_one_type(
                engine, MemoryType.CYPHER_NEGATIVE, vec, limit
            )
        results = []
        for i, r in enumerate(raw):
            meta = r.metadata or {}
            mem = CypherNegativeMemory(
                memory_id=r.id,
                question=meta.get("question", ""),
                bad_cypher=meta.get("bad_cypher", ""),
                error_excerpt=meta.get("error_excerpt", ""),
                fix_cypher=meta.get("fix_cypher", ""),
                fix_explanation=meta.get("fix_explanation"),
                chat_id=meta.get("chat_id"),
                timestamp=meta.get("created_at"),
                stale=bool(meta.get("stale", False)),
                metadata=meta,
            )
            results.append(
                CypherNegativeSearchResult(
                    memory=mem, similarity_score=float(r.score or 0.0), rank=i + 1
                )
            )
        return results

    # =========================================================================
    # 통합 검색 — kg_cypher 도구가 매 호출 시 호출
    # =========================================================================

    async def search_all_context(
        self,
        question: str,
        question_vector: Optional[List[float]] = None,
        cypher_example_limit: int = 3,
        schema_doc_limit: int = 3,
        domain_doc_limit: int = 3,
        pattern_limit: int = 3,
        negative_limit: int = 2,
    ) -> KGUnifiedSearchResult:
        """5종 메모리를 병렬 검색하여 통합 반환. kg_cypher 의 RAG 컨텍스트 빌드 진입점."""
        engine = self._get_engine()
        if not engine:
            return KGUnifiedSearchResult()

        vec = question_vector or await self._create_embedding(question)
        if not vec:
            return KGUnifiedSearchResult()

        async with self.session():
            examples = await self.search_cypher_examples(
                question, limit=cypher_example_limit, question_vector=vec
            )
            schemas = await self.search_schema_docs(
                question, limit=schema_doc_limit, question_vector=vec
            )
            domains = await self.search_domain_docs(
                question, limit=domain_doc_limit, question_vector=vec
            )
            patterns = await self.search_patterns(
                question, limit=pattern_limit, question_vector=vec
            )
            negatives = await self.search_negatives(
                question, limit=negative_limit, question_vector=vec
            )

        return KGUnifiedSearchResult(
            cypher_examples=examples,
            schema_docs=schemas,
            domain_docs=domains,
            patterns=patterns,
            negatives=negatives,
        )

    # =========================================================================
    # Drift handling
    # =========================================================================

    async def mark_stale_by_referenced_types(
        self,
        removed_node_types: Optional[List[str]] = None,
        removed_edge_types: Optional[List[str]] = None,
    ) -> int:
        """KG sync 후 사라진 타입을 참조하는 메모리를 stale=true 마킹.

        검색 인덱스가 정확한 array-contains 필터를 지원하지 않을 수 있어
        보수적 구현: 해당 타입을 metadata 에 가지는 row 를 ID 기반으로 fetch
        해서 update. 호출 빈도가 sync finalize 마다 1회로 낮으므로 충분.

        Returns: stale 마킹된 row 수.
        """
        engine = self._get_engine()
        if not engine or (not removed_node_types and not removed_edge_types):
            return 0

        removed_n = set(removed_node_types or [])
        removed_e = set(removed_edge_types or [])
        marked = 0

        async with self._engine_ctx(engine):
            # cypher_example / cypher_pattern 만 referenced_*types 보유.
            for et in (MemoryType.CYPHER_EXAMPLE, MemoryType.CYPHER_PATTERN):
                # filter 로 entity_type + collection. 임베딩 검색 대신 list 가
                # 가능하면 좋지만 SearchEngineBase 인터페이스상 search 만 있음.
                # zero vector 로는 적절치 않으므로 list_by_collection 같은 헬퍼 부재 시
                # large top_k 로 우회. 메모리가 폭증하면 별도 page-list API 필요.
                try:
                    from extension_modules.search_engine.models import SearchQuery

                    rows = await engine.search(
                        query=SearchQuery(
                            query="",
                            filter=self._base_filter(et, include_stale=False),
                            top_k=200,
                            top_k_vector=200,
                        ),
                        query_vector=[0.0] * self.vector_dim,
                    )
                except Exception as e:
                    logger.warning(f"[kg_memory] drift list {et.value} failed: {e}")
                    continue
                for r in rows or []:
                    meta = r.metadata or {}
                    refs_n = set(meta.get("referenced_node_types") or [])
                    refs_e = set(meta.get("referenced_edge_types") or [])
                    if (refs_n & removed_n) or (refs_e & removed_e):
                        new_meta = dict(meta)
                        new_meta["stale"] = True
                        new_meta["staled_at"] = _now_iso()
                        try:
                            await engine.update(
                                doc_id=r.id,
                                content=getattr(r, "content", "")
                                or meta.get("question")
                                or "",
                                vector=None,
                                metadata=new_meta,
                            )
                            marked += 1
                        except Exception as e:
                            logger.warning(f"[kg_memory] drift mark {r.id} failed: {e}")

            # kg_schema_doc: type_name 자체가 사라진 경우
            try:
                from extension_modules.search_engine.models import SearchQuery

                rows = await engine.search(
                    query=SearchQuery(
                        query="",
                        filter=self._base_filter(
                            MemoryType.KG_SCHEMA_DOC, include_stale=False
                        ),
                        top_k=500,
                        top_k_vector=500,
                    ),
                    query_vector=[0.0] * self.vector_dim,
                )
            except Exception as e:
                logger.warning(f"[kg_memory] drift list schema_doc failed: {e}")
                rows = []
            for r in rows or []:
                meta = r.metadata or {}
                tname = meta.get("type_name")
                role = meta.get("schema_role")
                if (role == "node" and tname in removed_n) or (
                    role == "edge" and tname in removed_e
                ):
                    new_meta = dict(meta)
                    new_meta["stale"] = True
                    new_meta["staled_at"] = _now_iso()
                    try:
                        await engine.update(
                            doc_id=r.id,
                            content=getattr(r, "content", "")
                            or meta.get("description")
                            or "",
                            vector=None,
                            metadata=new_meta,
                        )
                        marked += 1
                    except Exception as e:
                        logger.warning(
                            f"[kg_memory] drift mark schema {r.id} failed: {e}"
                        )

        if marked:
            logger.info(
                f"[kg_memory] kg={self.kg_id} drift marked {marked} memories stale"
            )
        return marked

    # =========================================================================
    # Prompt context formatting
    # =========================================================================

    @staticmethod
    def format_for_prompt(unified: KGUnifiedSearchResult) -> Dict[str, str]:
        """5섹션 prompt block 을 dict 으로 반환. 호출자가 token 예산에 맞춰 결합."""
        out: Dict[str, str] = {}

        if unified.schema_docs:
            lines = ["## Schema (this KG)"]
            for r in unified.schema_docs:
                m = r.memory
                samples = ", ".join((m.sample_labels or [])[:3])
                lines.append(
                    f"- [{m.schema_role}] `{m.type_name}`: {m.description}"
                    + (f" — e.g. {samples}" if samples else "")
                )
            out["schema_docs"] = "\n".join(lines)

        if unified.domain_docs:
            lines = ["## Domain rules / AGE caveats"]
            for r in unified.domain_docs:
                m = r.memory
                lines.append(f"- ({m.doc_type}) **{m.title}** — {m.content}")
            out["domain_docs"] = "\n".join(lines)

        if unified.negatives:
            lines = ["## Avoid these mistakes (prior failures)"]
            for r in unified.negatives:
                m = r.memory
                lines.append(
                    f"- Q: {m.question}\n  ❌ {m.bad_cypher}\n  ✅ {m.fix_cypher}"
                    + (f"\n  why: {m.fix_explanation}" if m.fix_explanation else "")
                )
            out["negatives"] = "\n".join(lines)

        if unified.patterns:
            lines = ["## Reusable traversal patterns"]
            for r in unified.patterns:
                m = r.memory
                lines.append(
                    f"- **{m.name}**: {m.description}\n  ```\n  {m.template_cypher}\n  ```"
                )
            out["patterns"] = "\n".join(lines)

        if unified.cypher_examples:
            lines = ["## Recent successful examples (top score)"]
            for r in unified.cypher_examples:
                m = r.memory
                lines.append(
                    f"- Q: {m.question} (hits={m.hit_count}, conf={m.confidence:.2f})\n"
                    f"  ```cypher\n  {m.cypher}\n  ```"
                )
            out["cypher_examples"] = "\n".join(lines)

        return out

    @staticmethod
    def to_source_events(unified: KGUnifiedSearchResult) -> List[Dict[str, Any]]:
        """retrieved 메모리를 프론트 source 이벤트 형식으로 변환 (감사 추적용)."""
        events: List[Dict[str, Any]] = []
        for r in unified.cypher_examples:
            m = r.memory
            events.append(
                {
                    "source": {
                        "name": "Prior cypher example",
                        "type": MemoryType.CYPHER_EXAMPLE.value,
                        "id": m.memory_id,
                    },
                    "document": [m.cypher],
                    "metadata": [
                        {
                            "question": m.question,
                            "hit_count": m.hit_count,
                            "confidence": m.confidence,
                            "final_score": r.final_score,
                        }
                    ],
                    "distances": [r.similarity_score],
                }
            )
        return events

    # =========================================================================
    # 유지보수 — 패턴 promotion candidate 가 사용할 enumerator
    # =========================================================================

    async def list_recent_examples(self, limit: int = 200) -> List[CypherExampleMemory]:
        """최근 cypher_example 을 일괄 fetch (pattern clusterer 입력용).

        검색 인덱스에 페이지네이션 list API 가 없으므로 zero-vector + large
        top_k 로 우회. 50 ~ 수백 개 수준에서 동작.
        """
        engine = self._get_engine()
        if not engine:
            return []
        async with self._engine_ctx(engine):
            try:
                from extension_modules.search_engine.models import SearchQuery

                rows = await engine.search(
                    query=SearchQuery(
                        query="",
                        filter=self._base_filter(
                            MemoryType.CYPHER_EXAMPLE, include_stale=False
                        ),
                        top_k=limit,
                        top_k_vector=limit,
                    ),
                    query_vector=[0.0] * self.vector_dim,
                )
            except Exception as e:
                logger.warning(f"[kg_memory] list_recent_examples failed: {e}")
                return []

        out: List[CypherExampleMemory] = []
        for r in rows or []:
            meta = r.metadata or {}
            out.append(
                CypherExampleMemory(
                    memory_id=r.id,
                    question=meta.get("question", ""),
                    cypher=meta.get("cypher", ""),
                    confidence=float(meta.get("confidence", 0.0)),
                    hit_count=int(meta.get("hit_count", 1)),
                    last_used=meta.get("last_used"),
                    normalized_question=meta.get("normalized_question"),
                    referenced_node_types=meta.get("referenced_node_types") or [],
                    referenced_edge_types=meta.get("referenced_edge_types") or [],
                    timestamp=meta.get("created_at"),
                    stale=bool(meta.get("stale", False)),
                    metadata=meta,
                )
            )
        return out


__all__ = [
    "SearchEngineKGMemory",
]
