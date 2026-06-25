"""
Search Engine - Elasticsearch 구현
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..base import SearchEngineBase
from ..filter_translator import translate_odata_to_es
from ..models import (
    DocumentItem,
    ElasticsearchConfig,
    IndexConfig,
    SearchQuery,
    SearchResult,
)

if TYPE_CHECKING:
    from ..embedding import EmbeddingConfig

log = logging.getLogger(__name__)

# Elasticsearch bulk 권장: 5-15MB / batch. ``http.max_content_length`` 기본 100MB 이나
# 실제 권장은 5-15MB 가 일반적. 16KB/doc × 500 = 8MB → 안전선.
# Azure 어댑터와 동일 상수로 운영 일관성 유지 (인덱스별 튜닝은 IndexConfig 확장 followup).
_ES_BATCH_SIZE = 500


class ElasticsearchEngine(SearchEngineBase):
    """
    Elasticsearch 기반 검색 엔진 구현.

    Args:
        config: 인덱스 설정
        engine_config: Elasticsearch 연결 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.
    """

    def __init__(
        self,
        config: IndexConfig,
        engine_config: ElasticsearchConfig,
        embedding_config: Optional["EmbeddingConfig"] = None,
    ):
        super().__init__(config, embedding_config)

        self.url = engine_config.url
        self.api_key = engine_config.api_key
        self.user = engine_config.user
        self.password = engine_config.password
        self.ca_certs = engine_config.ca_certs

        self._client = None

    def _get_client(self):
        """Elasticsearch 클라이언트 가져오기"""
        if self._client is None:
            try:
                from elasticsearch import AsyncElasticsearch
            except ImportError as e:
                raise RuntimeError(
                    "elasticsearch package required. "
                    "Install: pip install elasticsearch[async]"
                ) from e

            client_kwargs = {
                "hosts": [self.url],
            }

            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            elif self.user and self.password:
                client_kwargs["basic_auth"] = (self.user, self.password)

            if self.ca_certs:
                client_kwargs["ca_certs"] = self.ca_certs

            self._client = AsyncElasticsearch(**client_kwargs)

        return self._client

    async def close(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.close()
            self._client = None

    # === Index 관리 ===

    async def create_index(self) -> bool:
        """인덱스 생성"""
        client = self._get_client()

        # 인덱스 존재 여부 확인
        if await client.indices.exists(index=self.index_name):
            return False

        # 인덱스 매핑 정의
        mappings = {
            "properties": {
                "id": {"type": "keyword"},
                "content": {
                    "type": "text",
                    "analyzer": "korean",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "metadata": {"type": "object", "enabled": True},
                "collection": {"type": "keyword"},
                "vector": {
                    "type": "dense_vector",
                    "dims": self.config.vector_dim,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        }

        # 추가 컬럼 매핑
        if self.config.column_info:
            for col in self.config.column_info:
                mappings["properties"][col.name] = self._get_es_mapping(col)

        # 인덱스 설정
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "korean": {
                        "type": "custom",
                        "tokenizer": "nori_tokenizer",
                        "filter": ["lowercase"],
                    }
                }
            },
        }

        await client.indices.create(
            index=self.index_name,
            mappings=mappings,
            settings=settings,
        )

        log.info(f"Index '{self.index_name}' created successfully.")
        return True

    def _get_es_mapping(self, column) -> Dict[str, Any]:
        """ColumnInfo를 Elasticsearch 매핑으로 변환"""
        TYPE_MAP = {
            "string": {"type": "keyword"},
            "boolean": {"type": "boolean"},
            "int32": {"type": "integer"},
            "int64": {"type": "long"},
            "double": {"type": "double"},
            "datetimeoffset": {"type": "date"},
        }

        mapping = TYPE_MAP.get(column.type.lower(), {"type": "keyword"})

        if column.is_collection:
            # Elasticsearch는 기본적으로 배열 지원
            pass

        return mapping

    async def delete_index(self) -> bool:
        """인덱스 삭제"""
        client = self._get_client()

        if not await client.indices.exists(index=self.index_name):
            return False

        await client.indices.delete(index=self.index_name)
        log.info(f"Index '{self.index_name}' deleted.")
        return True

    async def index_exists(self) -> bool:
        """인덱스 존재 여부"""
        client = self._get_client()
        return await client.indices.exists(index=self.index_name)

    # === CRUD ===

    @staticmethod
    def _count_bulk_success(
        method: str,
        action_key: str,
        success_results: tuple,
        batch_idx: int,
        batch_size: int,
        result: Dict[str, Any],
    ) -> int:
        """Bulk 결과에서 success 카운트 + 부분 실패 시 warning 로깅.

        Azure 어댑터와 일관된 의미: ``result in ("created", "updated")`` 만 카운트.
        ``noop`` 은 제외 — ES 는 메타 동일 시 noop 반환하나 caller 의 "인덱싱됨"
        의미와 다르다 (Azure ``r.succeeded`` 와 정렬). delete 는 ``"deleted"`` 만.

        Followup: ES caller (knowledge_service.save_chunks 등) 가 동일 재색인 시
        count=0 을 "실패" 로 오인할 가능성은 noop 케이스가 흔하지 않아 위험 낮음 —
        영향도 전수조사는 별 PR.
        """
        succeeded = 0
        failed: list = []
        for item in result.get("items", []):
            entry = item.get(action_key, {})
            if entry.get("result") in success_results:
                succeeded += 1
            elif entry.get("error") and len(failed) < 10:
                failed.append(entry.get("_id"))
        if succeeded < batch_size:
            log.warning(
                "[ELASTICSEARCH] %s batch #%d partial fail: %d/%d succeeded, "
                "first failed ids=%s",
                method,
                batch_idx,
                succeeded,
                batch_size,
                failed,
            )
        return succeeded

    async def insert(self, documents: List[DocumentItem]) -> int:
        """문서 삽입 (BATCH_SIZE 단위 chunk 처리)."""
        if not documents:
            return 0

        client = self._get_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(documents), _ES_BATCH_SIZE)):
            batch = documents[i : i + _ES_BATCH_SIZE]
            operations = []
            for doc in batch:
                operations.append({"index": {"_index": self.index_name, "_id": doc.id}})
                operations.append(self._to_es_doc(doc))
            result = await client.bulk(operations=operations, refresh=True)
            total += self._count_bulk_success(
                "insert",
                "index",
                ("created", "updated"),
                batch_idx,
                len(batch),
                result,
            )
        return total

    async def get(self, ids: List[str]) -> List[DocumentItem]:
        """ID로 문서 조회"""
        if not ids:
            return []

        client = self._get_client()
        result = await client.mget(index=self.index_name, ids=ids)

        return [
            self._from_es_doc(doc["_source"], doc["_id"])
            for doc in result["docs"]
            if doc.get("found")
        ]

    async def update(self, documents: List[DocumentItem]) -> int:
        """문서 업데이트 (upsert, BATCH_SIZE 단위 chunk 처리)."""
        if not documents:
            return 0

        client = self._get_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(documents), _ES_BATCH_SIZE)):
            batch = documents[i : i + _ES_BATCH_SIZE]
            operations = []
            for doc in batch:
                operations.append({"index": {"_index": self.index_name, "_id": doc.id}})
                operations.append(self._to_es_doc(doc))
            result = await client.bulk(operations=operations, refresh=True)
            total += self._count_bulk_success(
                "update",
                "index",
                ("created", "updated"),
                batch_idx,
                len(batch),
                result,
            )
        return total

    async def delete(self, ids: List[str]) -> int:
        """문서 삭제 (BATCH_SIZE 단위 chunk 처리)."""
        if not ids:
            return 0

        client = self._get_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(ids), _ES_BATCH_SIZE)):
            batch_ids = ids[i : i + _ES_BATCH_SIZE]
            operations = [
                {"delete": {"_index": self.index_name, "_id": doc_id}}
                for doc_id in batch_ids
            ]
            result = await client.bulk(operations=operations, refresh=True)
            total += self._count_bulk_success(
                "delete",
                "delete",
                ("deleted",),
                batch_idx,
                len(batch_ids),
                result,
            )
        return total

    async def delete_by_filter(self, filter_expr: str) -> int:
        """필터로 문서 삭제"""
        client = self._get_client()

        # filter_expr을 Elasticsearch 쿼리로 변환
        query = self._parse_filter_to_query(filter_expr)

        result = await client.delete_by_query(
            index=self.index_name,
            query=query,
            refresh=True,
        )

        return result.get("deleted", 0)

    # === 검색 ===

    async def search(
        self,
        query: SearchQuery,
        query_vector: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        하이브리드 검색 (텍스트 + 벡터)

        Args:
            query: 검색 쿼리 설정
            query_vector: 사전 계산된 임베딩 벡터 (선택).
                          embedding_config 설정 시 자동 생성.
            user_id: 임베딩 사용량 추적용 사용자 ID (선택)
            chat_id: 임베딩 사용량 추적용 채팅 ID (선택)
        """
        client = self._get_client()
        query_list = [query.query] if isinstance(query.query, str) else query.query

        all_results = []

        # 벡터 확보 (외부 제공 또는 자동 생성)
        effective_vector = query_vector
        if effective_vector is None and self.embedding_config is not None:
            try:
                query_text = query_list[0] if query_list else ""
                effective_vector = await self.generate_embedding(
                    text=query_text,
                    user_id=user_id,
                    chat_id=chat_id,
                )
                log.debug(f"Generated embedding for query: {query_text[:50]}...")
            except Exception as e:
                log.warning(
                    f"Failed to generate embedding, proceeding with text only: {e}"
                )

        for q in query_list:
            # 하이브리드 검색: kNN + match
            if effective_vector:
                # 벡터가 있으면 kNN 쿼리 사용
                knn_query = {
                    "field": "vector",
                    "query_vector": effective_vector,
                    "k": query.top_k,
                    "num_candidates": query.top_k * 2,
                    "boost": 0.5,
                }

                if query.filter:
                    knn_query["filter"] = self._parse_filter_to_query(query.filter)

                search_query = {
                    "bool": {
                        "should": [
                            {
                                "match": {
                                    "content": {
                                        "query": q,
                                        "boost": 0.5,
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 0,
                    }
                }

                if query.filter:
                    search_query["bool"]["filter"] = self._parse_filter_to_query(
                        query.filter
                    )

                result = await client.search(
                    index=self.index_name,
                    query=search_query,
                    knn=knn_query,
                    size=query.top_k,
                    source=["id", "content", "metadata"],
                )
            else:
                # 벡터가 없으면 텍스트만 검색
                search_query = {
                    "bool": {
                        "should": [
                            {
                                "match": {
                                    "content": {
                                        "query": q,
                                        "boost": 1.0,
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 1,
                    }
                }

                if query.filter:
                    search_query["bool"]["filter"] = self._parse_filter_to_query(
                        query.filter
                    )

                result = await client.search(
                    index=self.index_name,
                    query=search_query,
                    size=query.top_k,
                    source=["id", "content", "metadata"],
                )

            for hit in result["hits"]["hits"]:
                all_results.append(
                    {
                        "id": hit["_id"],
                        "content": hit["_source"].get("content", ""),
                        "score": hit["_score"],
                        "metadata": hit["_source"].get("metadata"),
                    }
                )

        # 점수 정규화 (BM25 unbounded → 0~1, max 기반 상대 정규화)
        if all_results:
            max_score = max(r["score"] for r in all_results)
            if max_score > 0:
                for r in all_results:
                    r["score"] = r["score"] / max_score
            else:
                for r in all_results:
                    r["score"] = 0.0

        all_results.sort(key=lambda x: x["score"], reverse=True)

        seen = set()
        results = []
        for r in all_results[: query.top_k]:
            if r["id"] not in seen:
                seen.add(r["id"])
                results.append(
                    SearchResult(
                        id=r["id"],
                        content=r["content"],
                        score=r["score"],
                        metadata=r["metadata"],
                    )
                )

        return results

    async def vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """벡터 전용 검색 (kNN)"""
        client = self._get_client()

        knn_query = {
            "field": "vector",
            "query_vector": vector,
            "k": top_k,
            "num_candidates": top_k * 2,
        }

        if filter_expr:
            knn_query["filter"] = self._parse_filter_to_query(filter_expr)

        result = await client.search(
            index=self.index_name,
            knn=knn_query,
            source=["id", "content", "metadata"],
        )

        hits = result["hits"]["hits"]
        if not hits:
            return []

        # knn _score 정규화 (max 기반)
        max_score = max(hit["_score"] for hit in hits)
        return [
            SearchResult(
                id=hit["_id"],
                content=hit["_source"].get("content", ""),
                score=(hit["_score"] / max_score) if max_score > 0 else 0.0,
                metadata=hit["_source"].get("metadata"),
            )
            for hit in hits
        ]

    # === 필터링 ===

    async def filter_by_metadata(
        self,
        filter_expr: str,
        limit: int = 100,
    ) -> List[DocumentItem]:
        """메타데이터 기반 필터링"""
        client = self._get_client()

        query = self._parse_filter_to_query(filter_expr)

        result = await client.search(
            index=self.index_name,
            query=query,
            size=limit,
            source=["id", "content", "metadata", "collection"],
        )

        return [
            DocumentItem(
                id=hit["_id"],
                content=hit["_source"].get("content", ""),
                metadata=hit["_source"].get("metadata"),
                collection=hit["_source"].get("collection"),
            )
            for hit in result["hits"]["hits"]
        ]

    async def count(self, filter_expr: Optional[str] = None) -> int:
        """문서 수 조회"""
        client = self._get_client()

        if filter_expr:
            query = self._parse_filter_to_query(filter_expr)
            result = await client.count(index=self.index_name, query=query)
        else:
            result = await client.count(index=self.index_name)

        return result["count"]

    # === 헬퍼 메서드 ===

    def _to_es_doc(self, doc: DocumentItem) -> Dict[str, Any]:
        """DocumentItem을 Elasticsearch 문서로 변환"""
        es_doc = {
            "id": doc.id,
            "content": doc.content,
        }

        if doc.vector:
            es_doc["vector"] = doc.vector

        if doc.metadata:
            es_doc["metadata"] = doc.metadata

        if doc.collection:
            es_doc["collection"] = doc.collection

        return es_doc

    def _from_es_doc(self, source: Dict[str, Any], doc_id: str) -> DocumentItem:
        """Elasticsearch 문서를 DocumentItem으로 변환"""
        return DocumentItem(
            id=doc_id,
            content=source.get("content", ""),
            vector=source.get("vector"),
            metadata=source.get("metadata"),
            collection=source.get("collection"),
        )

    def _parse_filter_to_query(self, filter_expr: str) -> Dict[str, Any]:
        """OData 필터 표현식을 Elasticsearch 쿼리로 변환.

        and/or/괄호를 포함한 복합 필터를 bool query 로 정확히 변환한다
        (collection·entity_type 등 멀티테넌트 격리 필터 보존). 파싱 실패 시
        match_all(전체 반환)이 아니라 match_none(0건)으로 fail-safe 처리해,
        필터 누락으로 인한 cross-collection 누출을 방지한다.
        """
        if not filter_expr or not filter_expr.strip():
            return {"match_all": {}}

        try:
            es_query = translate_odata_to_es(filter_expr, self.config.column_info)
        except ValueError as e:
            log.warning(
                "Could not parse filter %r → match_none (fail-safe, no leak): %s",
                filter_expr,
                e,
            )
            return {"match_none": {}}

        return es_query if es_query is not None else {"match_all": {}}
