"""
Search Engine - Google Vertex AI Search 구현
"""

import json
import logging
from typing import TYPE_CHECKING, List, Optional

from ..base import SearchEngineBase
from ..models import (
    DocumentItem,
    IndexConfig,
    SearchQuery,
    SearchResult,
    VertexSearchConfig,
)

if TYPE_CHECKING:
    from ..embedding import EmbeddingConfig

log = logging.getLogger(__name__)


class VertexSearchEngine(SearchEngineBase):
    """
    Google Vertex AI Search 기반 검색 엔진 구현.

    Note: Vertex AI Search는 자체 임베딩을 관리하므로 외부 임베딩 설정은
    문서 삽입 시 벡터 사전 생성에만 사용됩니다.

    Args:
        config: 인덱스 설정
        engine_config: Vertex AI Search 연결 설정
        embedding_config: 임베딩 설정 (선택). Vertex는 자체 임베딩 사용.
    """

    def __init__(
        self,
        config: IndexConfig,
        engine_config: VertexSearchConfig,
        embedding_config: Optional["EmbeddingConfig"] = None,
    ):
        super().__init__(config, embedding_config)

        self.project_id = engine_config.project_id
        self.location = engine_config.location
        self.data_store_id = engine_config.data_store_id or config.index_name

        self._search_client = None
        self._document_client = None

    def _get_search_client(self):
        """Vertex AI Search 클라이언트 가져오기"""
        if self._search_client is None:
            try:
                from google.cloud import discoveryengine_v1 as discoveryengine
            except ImportError as e:
                raise RuntimeError(
                    "google-cloud-discoveryengine package required. "
                    "Install: pip install google-cloud-discoveryengine"
                ) from e

            self._search_client = discoveryengine.SearchServiceClient()

        return self._search_client

    def _get_document_client(self):
        """Vertex AI Document 클라이언트 가져오기"""
        if self._document_client is None:
            try:
                from google.cloud import discoveryengine_v1 as discoveryengine
            except ImportError as e:
                raise RuntimeError(
                    "google-cloud-discoveryengine package required. "
                    "Install: pip install google-cloud-discoveryengine"
                ) from e

            self._document_client = discoveryengine.DocumentServiceClient()

        return self._document_client

    def _get_serving_config(self) -> str:
        """Serving config 경로 생성"""
        return (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"dataStores/{self.data_store_id}/servingConfigs/default_config"
        )

    def _get_branch(self) -> str:
        """Branch 경로 생성"""
        return (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"dataStores/{self.data_store_id}/branches/default_branch"
        )

    async def close(self) -> None:
        """리소스 정리"""
        # gRPC 클라이언트는 명시적 close 불필요
        self._search_client = None
        self._document_client = None

    # === Index 관리 ===

    async def create_index(self) -> bool:
        """
        데이터 스토어 생성.

        Note: Vertex AI Search의 데이터 스토어는 일반적으로
        Google Cloud Console 또는 gcloud CLI로 생성합니다.
        프로그래밍 방식으로 생성하려면 DataStoreService 사용.
        """
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = discoveryengine.DataStoreServiceClient()

            # 데이터 스토어 존재 여부 확인
            data_store_path = (
                f"projects/{self.project_id}/locations/{self.location}/"
                f"dataStores/{self.data_store_id}"
            )

            try:
                client.get_data_store(name=data_store_path)
                return False  # 이미 존재
            except Exception:
                pass

            # 데이터 스토어 생성
            parent = f"projects/{self.project_id}/locations/{self.location}"

            data_store = discoveryengine.DataStore(
                display_name=self.index_name,
                industry_vertical=discoveryengine.IndustryVertical.GENERIC,
                solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
                content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
            )

            operation = client.create_data_store(
                parent=parent,
                data_store=data_store,
                data_store_id=self.data_store_id,
            )

            # 비동기 작업 완료 대기
            operation.result()
            log.info(f"Data store '{self.data_store_id}' created successfully.")
            return True

        except Exception as e:
            log.error(f"Failed to create data store: {e}")
            raise

    async def delete_index(self) -> bool:
        """데이터 스토어 삭제"""
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = discoveryengine.DataStoreServiceClient()

            data_store_path = (
                f"projects/{self.project_id}/locations/{self.location}/"
                f"dataStores/{self.data_store_id}"
            )

            operation = client.delete_data_store(name=data_store_path)
            operation.result()

            log.info(f"Data store '{self.data_store_id}' deleted.")
            return True

        except Exception as e:
            log.error(f"Failed to delete data store: {e}")
            return False

    async def index_exists(self) -> bool:
        """데이터 스토어 존재 여부"""
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = discoveryengine.DataStoreServiceClient()

            data_store_path = (
                f"projects/{self.project_id}/locations/{self.location}/"
                f"dataStores/{self.data_store_id}"
            )

            client.get_data_store(name=data_store_path)
            return True

        except Exception:
            return False

    # === CRUD ===

    async def insert(self, documents: List[DocumentItem]) -> int:
        """문서 삽입"""
        if not documents:
            return 0

        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = self._get_document_client()
            branch = self._get_branch()

            count = 0
            for doc in documents:
                vertex_doc = discoveryengine.Document(
                    id=doc.id,
                    json_data=json.dumps(
                        {
                            "id": doc.id,
                            "content": doc.content,
                            "metadata": doc.metadata or {},
                            "collection": doc.collection,
                        }
                    ),
                )

                client.create_document(
                    parent=branch,
                    document=vertex_doc,
                    document_id=doc.id,
                )
                count += 1

            return count

        except Exception as e:
            log.error(f"Failed to insert documents: {e}")
            raise

    async def get(self, ids: List[str]) -> List[DocumentItem]:
        """ID로 문서 조회"""
        if not ids:
            return []

        client = self._get_document_client()
        branch = self._get_branch()
        results = []

        for doc_id in ids:
            try:
                doc_path = f"{branch}/documents/{doc_id}"
                doc = client.get_document(name=doc_path)

                data = json.loads(doc.json_data) if doc.json_data else {}
                results.append(
                    DocumentItem(
                        id=doc.id,
                        content=data.get("content", ""),
                        metadata=data.get("metadata"),
                        collection=data.get("collection"),
                    )
                )
            except Exception:
                pass

        return results

    async def update(self, documents: List[DocumentItem]) -> int:
        """문서 업데이트"""
        if not documents:
            return 0

        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = self._get_document_client()
            branch = self._get_branch()

            count = 0
            for doc in documents:
                vertex_doc = discoveryengine.Document(
                    name=f"{branch}/documents/{doc.id}",
                    id=doc.id,
                    json_data=json.dumps(
                        {
                            "id": doc.id,
                            "content": doc.content,
                            "metadata": doc.metadata or {},
                            "collection": doc.collection,
                        }
                    ),
                )

                # allow_missing=True → 미존재 시 생성(true upsert). base.update 계약이
                # upsert 임을 vertex 도 충족하도록(azure merge_or_upload / pg ON CONFLICT
                # / es index-by-id 와 동일). dbsphere relationship doc 의 deterministic-id
                # 멱등 저장이 첫 추출(미존재 id)에서도 동작하려면 필수.
                client.update_document(document=vertex_doc, allow_missing=True)
                count += 1

            return count

        except Exception as e:
            log.error(f"Failed to update documents: {e}")
            raise

    async def delete(self, ids: List[str]) -> int:
        """문서 삭제"""
        if not ids:
            return 0

        client = self._get_document_client()
        branch = self._get_branch()

        count = 0
        for doc_id in ids:
            try:
                doc_path = f"{branch}/documents/{doc_id}"
                client.delete_document(name=doc_path)
                count += 1
            except Exception:
                pass

        return count

    async def delete_by_filter(self, filter_expr: str) -> int:
        """필터로 문서 삭제"""
        # Vertex AI Search는 필터 기반 대량 삭제를 직접 지원하지 않음
        # 검색 후 개별 삭제 필요
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
        검색 수행.

        Note: Vertex AI Search는 자체 임베딩을 관리하므로
        query_vector와 user_id/chat_id는 무시됩니다.
        """
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = self._get_search_client()
            serving_config = self._get_serving_config()

            query_list = [query.query] if isinstance(query.query, str) else query.query
            all_results = []

            for q in query_list:
                request = discoveryengine.SearchRequest(
                    serving_config=serving_config,
                    query=q,
                    page_size=query.top_k,
                    query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
                        condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO,
                    ),
                    spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
                        mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO,
                    ),
                )

                if query.filter:
                    request.filter = query.filter

                response = client.search(request)

                for result in response.results:
                    doc = result.document
                    data = json.loads(doc.json_data) if doc.json_data else {}

                    all_results.append(
                        {
                            "id": doc.id,
                            "content": data.get("content", ""),
                            "score": getattr(result, "relevance_score", 0.0) or 0.0,
                            "metadata": data.get("metadata"),
                        }
                    )

            # 점수 기준 정렬 및 중복 제거
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

        except Exception as e:
            log.error(f"Search failed: {e}")
            raise

    async def vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        벡터 검색.

        Note: Vertex AI Search는 자체적으로 임베딩을 관리합니다.
        외부 벡터를 직접 사용하는 검색은 지원하지 않으므로,
        텍스트 기반 검색으로 대체합니다.
        """
        raise NotImplementedError(
            "Vertex AI Search does not support direct vector search. "
            "Use search() with text query instead."
        )

    # === 필터링 ===

    async def filter_by_metadata(
        self,
        filter_expr: str,
        limit: int = 100,
    ) -> List[DocumentItem]:
        """메타데이터 기반 필터링"""
        # Vertex AI Search의 필터 표현식 사용
        query = SearchQuery(
            query="*",
            filter=filter_expr,
            top_k=limit,
        )

        results = await self.search(query)

        return [
            DocumentItem(
                id=r.id,
                content=r.content,
                metadata=r.metadata,
            )
            for r in results
        ]

    async def count(self, filter_expr: Optional[str] = None) -> int:
        """문서 수 조회"""
        # Vertex AI Search는 직접적인 count API를 제공하지 않음
        # 검색 결과의 총 개수를 사용
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine

            client = self._get_search_client()
            serving_config = self._get_serving_config()

            request = discoveryengine.SearchRequest(
                serving_config=serving_config,
                query="*",
                page_size=1,
            )

            if filter_expr:
                request.filter = filter_expr

            response = client.search(request)
            return response.total_size

        except Exception as e:
            log.error(f"Count failed: {e}")
            return 0
