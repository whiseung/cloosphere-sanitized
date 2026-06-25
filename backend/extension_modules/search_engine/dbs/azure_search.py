"""
Search Engine - Azure AI Search 구현
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..base import SearchEngineBase
from ..models import (
    AzureSearchConfig,
    ColumnInfo,
    DocumentItem,
    IndexConfig,
    SearchQuery,
    SearchResult,
)

if TYPE_CHECKING:
    from ..embedding import EmbeddingConfig

log = logging.getLogger(__name__)

# Azure AI Search 한도: 1000 docs / 16MB per batch (둘 다 hard limit).
# 주의: "16KB/doc" 가정은 지나치게 낙관적이다. JSON 직렬화된 벡터(3072-dim)에
# secondary_vector(멀티벡터), 청크 텍스트, metadata 까지 더하면 doc 당 수십 KB 이상이
# 되어 500개 batch 가 16MB 를 넘기면 SDK(11.6.0)의 broken recursive split path 가
# 터진다(update() docstring 참조). 멀티벡터/enrichment-heavy 인덱스에서도 안전하도록
# 보수적으로 100 으로 낮춘다 (100 × ~110KB ≈ 11MB < 16MB). delete 는 payload 가 id
# 뿐이라 size 무관(count limit)하지만 같은 상수를 공유한다.
# 동적 size-aware batching(byte 예산)은 followup.
_AZURE_BATCH_SIZE = 100

# =============================================================================
# Azure AI Search 점수 정규화
# =============================================================================
# 공식 문서 기준 @search.score 범위:
#   - Full-text (BM25): unbounded (상한 없음)
#   - Vector (Cosine):  0.333 ~ 1.0
#   - Hybrid (RRF):     ~0.01 ~ 0.05 (k=60 기준, 매우 작음)
# @search.rerankerScore: 0.0 ~ 4.0 (시맨틱 리랭커)
#
# SearchResult.score는 항상 0~1로 정규화하여 반환해야 함.
# 상위 호출자(DbSphere memory, Glossary 등)가 similarity_threshold=0.3~0.5로 필터링.

RERANKER_MAX = 4.0


def _normalize_scores(
    results: List[Dict[str, Any]],
    has_reranker: bool,
) -> None:
    """
    Azure AI Search 결과의 점수를 0~1로 in-place 정규화.

    Args:
        results: Azure Search 결과 리스트 (dict)
        has_reranker: 시맨틱 리랭커가 적용된 결과인지 여부
    """
    if has_reranker:
        # rerankerScore: 0~4 → 0~1
        for r in results:
            raw = float(r.get("@search.reranker_score", 0) or 0)
            r["_normalized_score"] = min(max(raw / RERANKER_MAX, 0.0), 1.0)
    else:
        # RRF/BM25/Vector: 결과 내 max score 기반 상대 정규화
        if not results:
            return
        max_score = max(float(r.get("@search.score", 0) or 0) for r in results)
        for r in results:
            raw = float(r.get("@search.score", 0) or 0)
            r["_normalized_score"] = (raw / max_score) if max_score > 0 else 0.0


def _require_sdk():
    """Azure SDK 의존성 확인"""
    try:
        import azure.search.documents  # noqa: F401
        import azure.search.documents.indexes  # noqa: F401

        return True
    except ImportError as e:
        raise RuntimeError(
            "azure-search-documents package required. "
            "Install: pip install azure-search-documents"
        ) from e


class AzureSearchEngine(SearchEngineBase):
    """
    Azure AI Search 기반 검색 엔진 구현.

    임베딩은 외부에서 생성하여 전달하거나, embedding_config 설정 시 자동 생성.

    Args:
        config: 인덱스 설정
        engine_config: Azure Search 연결 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.
    """

    def __init__(
        self,
        config: IndexConfig,
        engine_config: AzureSearchConfig,
        embedding_config: Optional["EmbeddingConfig"] = None,
    ):
        _require_sdk()
        super().__init__(config, embedding_config)

        from azure.core.credentials import AzureKeyCredential

        # Azure Search 설정
        self.endpoint = engine_config.endpoint
        self.api_key = engine_config.api_key
        self.api_version = engine_config.api_version
        self._credential = AzureKeyCredential(self.api_key)

        # 벡터 차원 설정 (config에서 명시적으로 설정하거나 기본값 사용)
        self.vector_dim = config.vector_dim or 1536

        # 클라이언트 캐시
        self._search_client = None
        self._index_client = None
        self.semantic_config_name = config.semantic_config_name

    def _get_index_client(self):
        """동기 인덱스 클라이언트 (인덱스 관리용)"""
        if self._index_client is None:
            from azure.search.documents.indexes import SearchIndexClient

            self._index_client = SearchIndexClient(
                endpoint=self.endpoint,
                credential=self._credential,
            )
        return self._index_client

    def _get_search_client(self):
        """비동기 검색 클라이언트"""
        if self._search_client is None:
            from azure.search.documents.aio import SearchClient

            self._search_client = SearchClient(
                endpoint=self.endpoint,
                index_name=self.index_name,
                credential=self._credential,
            )
        return self._search_client

    async def close(self) -> None:
        """리소스 정리"""
        if self._search_client:
            try:
                await self._search_client.close()
            except Exception:
                pass
            self._search_client = None

    # === Index 관리 ===

    async def create_index(self) -> bool:
        """인덱스 생성 또는 업데이트 (벡터기 없음 - 외부 임베딩 사용)"""
        from azure.search.documents.indexes.models import (
            ExhaustiveKnnAlgorithmConfiguration,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SemanticConfiguration,
            SemanticField,
            SemanticPrioritizedFields,
            SemanticSearch,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        # 기본 필드 정의
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(
                name="collection",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=False,
            ),
            SearchField(
                name="content",
                type=SearchFieldDataType.String,
                searchable=True,
                analyzer_name="ko.lucene",
            ),
            SimpleField(
                name="metadata",
                type=SearchFieldDataType.String,
                filterable=False,
                facetable=False,
            ),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.vector_dim,
                vector_search_profile_name="vector_profile",
            ),
        ]

        # 추가 컬럼 정의
        if self.config.column_info:
            for col in self.config.column_info:
                fields.append(self._create_field(col))

        # Secondary vector 필드 추가 (config에 지정된 경우)
        if self.config.secondary_vector_field:
            fields.append(
                SearchField(
                    name=self.config.secondary_vector_field,
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=self.vector_dim,
                    vector_search_profile_name="vector_profile",
                )
            )

        # 벡터 검색 설정 (벡터기 없음 - VectorizedQuery로 직접 벡터 전달)
        vector_search = VectorSearch(
            algorithms=[
                ExhaustiveKnnAlgorithmConfiguration(name="eknn_algo"),
            ],
            profiles=[
                VectorSearchProfile(
                    name="vector_profile",
                    algorithm_configuration_name="eknn_algo",
                ),
            ],
        )

        # 시맨틱 검색 설정 — config 기반 동적 구성
        semantic_title = None
        if self.config.semantic_title_field:
            semantic_title = SemanticField(field_name=self.config.semantic_title_field)

        content_names = self.config.semantic_content_fields or ["content"]
        semantic_content_fields = [SemanticField(field_name=fn) for fn in content_names]
        # sample_questions 호환: column_info에 정의되어 있고 content_fields에 없으면 추가
        if self.config.column_info:
            defined_columns = {col.name for col in self.config.column_info}
            if (
                "sample_questions" in defined_columns
                and "sample_questions" not in content_names
            ):
                semantic_content_fields.append(
                    SemanticField(field_name="sample_questions")
                )

        semantic_keywords = None
        if self.config.semantic_keywords_fields:
            semantic_keywords = [
                SemanticField(field_name=fn)
                for fn in self.config.semantic_keywords_fields
            ]

        semantic_search = SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name=self.semantic_config_name,
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=semantic_title,
                        content_fields=semantic_content_fields,
                        keywords_fields=semantic_keywords,
                    ),
                ),
            ],
        )

        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )

        self._get_index_client().create_or_update_index(index)
        log.info(f"Index '{self.index_name}' created/updated successfully.")
        return True

    def _create_field(self, column: ColumnInfo):
        """ColumnInfo를 SearchField로 변환"""
        from azure.search.documents.indexes.models import (
            SearchField,
            SearchFieldDataType,
        )

        TYPE_MAP = {
            "string": SearchFieldDataType.String,
            "boolean": SearchFieldDataType.Boolean,
            "int32": SearchFieldDataType.Int32,
            "int64": SearchFieldDataType.Int64,
            "double": SearchFieldDataType.Double,
            "datetimeoffset": SearchFieldDataType.DateTimeOffset,
        }

        field_type = TYPE_MAP.get(column.type.lower())
        if field_type is None:
            raise ValueError(f"Unknown column type: {column.type}")

        if column.is_collection:
            field_type = SearchFieldDataType.Collection(field_type)

        return SearchField(
            name=column.name,
            type=field_type,
            filterable=True,
            facetable=True,
            sortable=not column.is_collection,
            searchable=(column.type.lower() == "string"),
            analyzer_name="ko.lucene" if column.type.lower() == "string" else None,
        )

    def ensure_filter_slots(self) -> bool:
        """
        기존 인덱스에 필터 슬롯 필드가 없으면 PATCH(create_or_update)로 추가.

        Azure AI Search는 필드 추가는 허용하지만 수정/삭제는 불가.
        앱 시작 시 또는 첫 번째 인덱스 접근 시 호출하여 기존 인덱스를 마이그레이션.

        Returns:
            True if fields were added, False if already up to date or failed.
        """
        FILTER_SLOT_PREFIXES = ("f_str_", "f_int_", "f_date_", "f_col_")
        slot_columns = [
            col
            for col in (self.config.column_info or [])
            if col.name.startswith(FILTER_SLOT_PREFIXES)
        ]
        if not slot_columns:
            return False

        try:
            index = self._get_index_client().get_index(self.index_name)
            existing_names = {f.name for f in index.fields}

            missing_columns = [
                col for col in slot_columns if col.name not in existing_names
            ]
            if not missing_columns:
                return False

            new_fields = [self._create_field(col) for col in missing_columns]
            index.fields.extend(new_fields)
            self._get_index_client().create_or_update_index(index)
            log.info(
                f"Added {len(new_fields)} filter slot fields to index '{self.index_name}': "
                f"{[col.name for col in missing_columns]}"
            )
            return True
        except Exception as e:
            log.error(
                f"Failed to ensure filter slots in index '{self.index_name}': {e}"
            )
            return False

    async def delete_index(self) -> bool:
        """인덱스 삭제"""
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._get_index_client().delete_index(self.index_name)
            log.info(f"Index '{self.index_name}' deleted.")
            return True
        except ResourceNotFoundError:
            return False

    async def index_exists(self) -> bool:
        """인덱스 존재 여부"""
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._get_index_client().get_index(self.index_name)
            return True
        except ResourceNotFoundError:
            return False

    # === CRUD ===

    @staticmethod
    def _log_partial_failure(
        method: str, batch_idx: int, batch_size: int, result
    ) -> int:
        """Batch 결과에서 succeeded 카운트 + 부분 실패 시 warning 로깅.

        Azure SDK 가 RequestEntityTooLargeError 시 broken recursive split 으로
        TypeError 를 일으키지만, 그 외 (스키마 위반, 인덱스 없음 등) 는 batch 내
        일부 doc 만 ``r.succeeded=False`` 로 돌아온다. 호출자는 count 만 받으므로
        adapter 단에서 가시화 필요.
        """
        succeeded = sum(1 for r in result if r.succeeded)
        if succeeded < batch_size:
            # SDK minor bump 시 r.key 가 None 으로 올 수 있음 (server-side missing) — defensive
            failed = [
                getattr(r, "key", None) or "<unknown>"
                for r in result
                if not r.succeeded
            ][:10]
            log.warning(
                "[AZURE_SEARCH] %s batch #%d partial fail: %d/%d succeeded, "
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

        client = self._get_search_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(documents), _AZURE_BATCH_SIZE)):
            batch = documents[i : i + _AZURE_BATCH_SIZE]
            docs = [self._to_azure_doc(d) for d in batch]
            result = await client.upload_documents(documents=docs)
            total += self._log_partial_failure("insert", batch_idx, len(batch), result)
        return total

    async def get(self, ids: List[str]) -> List[DocumentItem]:
        """ID로 문서 조회"""
        if not ids:
            return []

        client = self._get_search_client()
        results = []

        for doc_id in ids:
            try:
                doc = await client.get_document(key=doc_id)
                results.append(self._from_azure_doc(doc))
            except Exception:
                pass

        return results

    async def update(self, documents: List[DocumentItem]) -> int:
        """문서 업데이트 (upsert, BATCH_SIZE 단위 chunk 처리).

        Azure 16MB payload 한도 초과 시 SDK 의 broken recursive split path 가
        ``TypeError: index() got multiple values for keyword argument 'error_map'``
        를 발생시킨다 (azure-search-documents==11.6.0). chunking 으로 한도 안에서
        호출하면 그 경로를 우회한다. 16MB 한도 자체가 SDK 와 무관한 server-side
        제약이므로 SDK fix 후에도 chunking 은 유효하다.
        """
        if not documents:
            return 0

        client = self._get_search_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(documents), _AZURE_BATCH_SIZE)):
            batch = documents[i : i + _AZURE_BATCH_SIZE]
            docs = [self._to_azure_doc(d) for d in batch]
            result = await client.merge_or_upload_documents(documents=docs)
            total += self._log_partial_failure("update", batch_idx, len(batch), result)
        return total

    async def delete(self, ids: List[str]) -> int:
        """문서 삭제 (BATCH_SIZE 단위 chunk 처리).

        payload 자체는 id 만 담아 작지만 Azure 의 1000 docs/batch count limit
        은 동일하게 적용된다.
        """
        if not ids:
            return 0

        client = self._get_search_client()
        total = 0
        for batch_idx, i in enumerate(range(0, len(ids), _AZURE_BATCH_SIZE)):
            batch_ids = ids[i : i + _AZURE_BATCH_SIZE]
            docs = [{"id": doc_id} for doc_id in batch_ids]
            result = await client.delete_documents(documents=docs)
            total += self._log_partial_failure(
                "delete", batch_idx, len(batch_ids), result
            )
        return total

    async def delete_by_filter(self, filter_expr: str) -> int:
        """필터로 문서 삭제"""
        # 먼저 필터로 문서 조회
        docs = await self.filter_by_metadata(filter_expr, limit=10000)
        if not docs:
            return 0

        ids = [doc.id for doc in docs]
        return await self.delete(ids)

    # === 검색 ===

    async def search(
        self,
        query: SearchQuery,
        query_vector: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        하이브리드 검색 (벡터 + 키워드 + 시맨틱 리랭킹)

        Args:
            query: 검색 쿼리 설정
            query_vector: 사전 계산된 임베딩 벡터 (선택).
                          embedding_config 설정 시 자동 생성.
            user_id: 임베딩 사용량 추적용 사용자 ID (선택)
            chat_id: 임베딩 사용량 추적용 채팅 ID (선택)
        """
        from azure.search.documents.models import VectorizedQuery

        client = self._get_search_client()
        query_text = query.query if isinstance(query.query, str) else query.query[0]

        all_results: List[Dict[str, Any]] = []

        # 벡터 쿼리 (외부 제공 또는 자동 생성)
        vector_queries = []
        effective_vector = query_vector

        # query_vector가 없고 embedding_config가 있으면 자동 생성
        if effective_vector is None and self.embedding_config is not None:
            try:
                effective_vector = await self.generate_embedding(
                    text=query_text,
                    user_id=user_id,
                    chat_id=chat_id,
                )
                log.debug(f"Generated embedding for query: {query_text[:50]}...")
            except Exception as e:
                log.warning(
                    f"Failed to generate embedding, proceeding without vector: {e}"
                )

        if effective_vector:
            vector_queries.append(
                VectorizedQuery(
                    vector=effective_vector,
                    k_nearest_neighbors=query.top_k_vector,
                    fields="vector",
                    exhaustive=True,
                )
            )

        has_reranker = False
        try:
            results = await client.search(
                search_text=query_text,
                filter=query.filter,
                top=query.top_k,
                vector_queries=vector_queries if vector_queries else None,
                select=["id", "content", "metadata"],
                query_type="semantic",
                semantic_configuration_name=self.semantic_config_name,
            )
            async for r in results:
                all_results.append(r)
            has_reranker = True
        except Exception as e:
            if "semantic" in str(e).lower():
                log.warning(
                    f"Semantic search failed, falling back to vector search: {e}"
                )
                results = await client.search(
                    search_text=query_text,
                    filter=query.filter,
                    top=query.top_k,
                    vector_queries=vector_queries if vector_queries else None,
                    select=["id", "content", "metadata"],
                )
                async for r in results:
                    all_results.append(r)
            else:
                raise

        # 점수 정규화 (0~1) 및 필터링
        _normalize_scores(all_results, has_reranker=has_reranker)

        filtered = [
            r for r in all_results if r["_normalized_score"] >= query.reranker_threshold
        ]
        filtered.sort(key=lambda x: x["_normalized_score"], reverse=True)

        # 중복 제거 및 변환
        seen = set()
        results = []
        for r in filtered[: query.top_k]:
            if r["id"] not in seen:
                seen.add(r["id"])
                results.append(
                    SearchResult(
                        id=r["id"],
                        content=r.get("content", ""),
                        score=r["_normalized_score"],
                        metadata=self._parse_metadata(r.get("metadata")),
                    )
                )

        return results

    async def vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """벡터 전용 검색"""
        from azure.search.documents.models import VectorizedQuery

        client = self._get_search_client()

        vector_query = VectorizedQuery(
            vector=vector,
            k_nearest_neighbors=top_k,
            fields="vector",
        )

        results = await client.search(
            search_text=None,
            vector_queries=[vector_query],
            filter=filter_expr,
            top=top_k,
            select=["id", "content", "metadata"],
        )

        all_results = []
        async for r in results:
            all_results.append(r)

        # 벡터 전용: cosine similarity (0.33~1.0) → max 기반 정규화
        _normalize_scores(all_results, has_reranker=False)

        search_results = []
        for r in all_results:
            search_results.append(
                SearchResult(
                    id=r["id"],
                    content=r.get("content", ""),
                    score=r["_normalized_score"],
                    metadata=self._parse_metadata(r.get("metadata")),
                )
            )

        return search_results

    # === 필터링 ===

    async def filter_by_metadata(
        self,
        filter_expr: str,
        limit: int = 100,
    ) -> List[DocumentItem]:
        """메타데이터 기반 필터링"""
        client = self._get_search_client()

        results = await client.search(
            search_text="*",
            filter=filter_expr,
            top=limit,
            select=["id", "content", "metadata", "collection"],
        )

        docs = []
        async for r in results:
            docs.append(
                DocumentItem(
                    id=r["id"],
                    content=r.get("content", ""),
                    metadata=self._parse_metadata(r.get("metadata")),
                    collection=r.get("collection"),
                )
            )

        return docs

    async def count(self, filter_expr: Optional[str] = None) -> int:
        """문서 수 조회"""
        client = self._get_search_client()

        results = await client.search(
            search_text="*",
            filter=filter_expr,
            top=0,
            include_total_count=True,
        )

        result = await results.get_count()
        return result or 0

    # === 헬퍼 메서드 ===

    def _to_azure_doc(self, doc: DocumentItem) -> Dict[str, Any]:
        """DocumentItem을 Azure 문서로 변환"""
        azure_doc = {
            "id": doc.id,
            "content": doc.content,
        }

        if doc.vector:
            azure_doc["vector"] = doc.vector

        # Secondary vector 추가
        if doc.secondary_vector and self.config.secondary_vector_field:
            azure_doc[self.config.secondary_vector_field] = doc.secondary_vector

        if doc.metadata:
            azure_doc["metadata"] = json.dumps(doc.metadata, ensure_ascii=False)

            # Map metadata fields to individual columns defined in config
            if self.config and self.config.column_info:
                defined_columns = {col.name for col in self.config.column_info}
                for key, value in doc.metadata.items():
                    if key in defined_columns and value is not None:
                        azure_doc[key] = value

        if doc.collection:
            azure_doc["collection"] = doc.collection

        return azure_doc

    def _from_azure_doc(self, doc: Dict[str, Any]) -> DocumentItem:
        """Azure 문서를 DocumentItem으로 변환"""
        return DocumentItem(
            id=doc["id"],
            content=doc.get("content", ""),
            vector=doc.get("vector"),
            metadata=self._parse_metadata(doc.get("metadata")),
            collection=doc.get("collection"),
        )

    def _parse_metadata(self, metadata: Optional[str]) -> Optional[Dict[str, Any]]:
        """JSON 문자열을 dict로 파싱"""
        if not metadata:
            return None
        try:
            return json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            return None

    async def multi_vector_search(
        self,
        text: str,
        vector: Optional[List[float]] = None,
        secondary_vector: Optional[List[float]] = None,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
        primary_weight: float = 0.5,
        secondary_weight: float = 0.5,
        reranker_threshold: float = 0.0,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Multi-vector 검색: vector + vector_question 앙상블"""
        from azure.search.documents.models import VectorizedQuery

        client = self._get_search_client()
        vector_queries = []

        # 가중치 변환: Azure Search weight 범위 0 < weight <= 4
        # 입력 범위 자동 감지:
        #   - 0~1 범위 (normalized): 4배 스케일링 (예: 0.5 → 2.0)
        #   - 1 초과 (Azure 범위): 그대로 사용 (예: 2.0 → 2.0)
        AZURE_WEIGHT_MAX = 4.0

        def normalize_weight(weight: float) -> float:
            """가중치를 Azure Search 범위(0~4)로 정규화"""
            if weight <= 1.0:
                # 0~1 범위로 가정하고 스케일링
                return max(0.01, weight * AZURE_WEIGHT_MAX)
            else:
                # 이미 Azure 범위 (1 초과)
                return min(weight, AZURE_WEIGHT_MAX)

        azure_primary_weight = normalize_weight(primary_weight)
        azure_secondary_weight = normalize_weight(secondary_weight)

        log.debug(
            f"Multi-vector search weights: input({primary_weight:.2f}, {secondary_weight:.2f}) "
            f"-> azure({azure_primary_weight:.2f}, {azure_secondary_weight:.2f})"
        )

        # 자동 임베딩 생성 (필요한 경우)
        effective_vector = vector
        effective_secondary = secondary_vector

        if effective_vector is None and self.embedding_config is not None:
            try:
                effective_vector = await self.generate_embedding(text, user_id, chat_id)
            except Exception as e:
                log.warning(f"Failed to generate primary embedding: {e}")

        if effective_secondary is None and self.embedding_config is not None:
            try:
                effective_secondary = await self.generate_embedding(
                    text, user_id, chat_id
                )
            except Exception as e:
                log.warning(f"Failed to generate secondary embedding: {e}")

        # 기본 벡터 쿼리
        if effective_vector:
            vector_queries.append(
                VectorizedQuery(
                    vector=effective_vector,
                    k_nearest_neighbors=top_k * 2,
                    fields="vector",
                    weight=azure_primary_weight,
                )
            )

        # 보조 벡터 쿼리
        if effective_secondary and self.config.secondary_vector_field:
            vector_queries.append(
                VectorizedQuery(
                    vector=effective_secondary,
                    k_nearest_neighbors=top_k * 2,
                    fields=self.config.secondary_vector_field,
                    weight=azure_secondary_weight,
                )
            )

        # 하이브리드 검색 (BM25 + 멀티벡터 + 시맨틱 리랭킹)
        all_results: List[Dict[str, Any]] = []
        has_reranker = False
        try:
            results = await client.search(
                search_text=text,
                filter=filter_expr,
                top=top_k,
                vector_queries=vector_queries if vector_queries else None,
                select=["id", "content", "metadata"],
                query_type="semantic",
                semantic_configuration_name=self.semantic_config_name,
            )
            async for r in results:
                all_results.append(r)
            has_reranker = True
        except Exception as e:
            if "semantic" in str(e).lower():
                log.warning(
                    f"Semantic search failed, falling back to vector search: {e}"
                )
                results = await client.search(
                    search_text=text,
                    filter=filter_expr,
                    top=top_k,
                    vector_queries=vector_queries if vector_queries else None,
                    select=["id", "content", "metadata"],
                )
                async for r in results:
                    all_results.append(r)
            else:
                raise

        # 점수 정규화 (0~1) 및 필터링
        _normalize_scores(all_results, has_reranker=has_reranker)

        filtered = [
            r for r in all_results if r["_normalized_score"] >= reranker_threshold
        ]
        filtered.sort(key=lambda x: x["_normalized_score"], reverse=True)

        search_results = []
        for r in filtered[:top_k]:
            search_results.append(
                SearchResult(
                    id=r["id"],
                    content=r.get("content", ""),
                    score=r["_normalized_score"],
                    metadata=self._parse_metadata(r.get("metadata")),
                )
            )

        return search_results
