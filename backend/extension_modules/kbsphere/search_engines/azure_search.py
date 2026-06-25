import logging
import os
from typing import Any, Dict, List, Optional, Union

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
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
from azure.search.documents.models import VectorizableTextQuery
from pydantic import BaseModel

log = logging.getLogger(__name__)
# log.setLevel(SRC_LOG_LEVELS["CUSTOM"])


class KnowledgeForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    knowledge_type: Optional[str] = "general"
    column_info: Optional[dict | list] = None
    index_name: Optional[str] = None

    data: Optional[dict] = None
    access_control: Optional[dict] = None


class KnowledgeSearchConfig(BaseModel):
    index_name: str
    column_info: Optional[dict | list] = None


class KnowledgeSearchClient:
    """
    Azure AI Search 비동기 검색 전용 클라이언트.

    - 다양한 인덱스 스키마 정규화를 위해 normalizer를 주입
    - 컬렉션/쿼리 다건을 비동기 병렬 처리 후 score 기준 상위 limit 반환
    """

    def __init__(
        self,
        *,
        config: KnowledgeForm,
    ) -> None:
        self.endpoint = os.getenv("AZURE_SEARCH_ENDPOINT") or ""
        self.api_key = os.getenv("AZURE_SEARCH_API_KEY") or ""
        if not (self.endpoint and self.api_key):
            raise RuntimeError("Azure Search 환경변수(endpoint/key)가 필요합니다.")

        self._client_cache: Dict[str, SearchClient] = {}
        self._credential = AzureKeyCredential(self.api_key)
        self.index_name = config.index_name
        self.config = config

        self.aoai_embedding_model = (
            os.getenv("AZURE_OPENAI_EMBEDDING_MODEL") or "text-embedding-3-large"
        )
        self.aoai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.aoai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.aoai_api_version = (
            os.getenv("AZURE_OPENAI_API_VERSION") or "2025-04-01-preview"
        )

        self._create_index()

    async def aclose(self) -> None:
        for c in list(self._client_cache.values()):
            try:
                await c.close()
            except Exception:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    @staticmethod
    def _infer_vector_dim(model_name: str) -> int:
        mapping: Dict[str, int] = {
            # OpenAI/Azure OpenAI
            "text-embedding-3-large": 3072,
            "text-embedding-3-large-v1": 3072,
            "text-embedding-3-small": 1536,
            "text-embedding-3-small-v1": 1536,
            "text-embedding-ada-002": 1536,
            # Sentence-Transformers popular defaults
            "sentence-transformers/all-minilm-l6-v2": 384,
            "intfloat/multilingual-e5-large": 1024,
            "intfloat/multilingual-e5-base": 768,
            "intfloat/e5-large": 1024,
            "intfloat/e5-base": 768,
            "mxbai-embed-large": 1024,
            "gte-large": 1024,
            "nomic-embed-text-v1.5": 768,
        }

        for key, dim in mapping.items():
            if key in model_name:
                return dim

        # Fallback
        return 1536

    def _get_client(self, index_name: str):
        from azure.search.documents.aio import SearchClient

        cli = self._client_cache.get(index_name)
        if cli is None:
            cli = SearchClient(
                endpoint=self.endpoint,
                index_name=index_name,
                credential=self._credential,
            )
            self._client_cache[index_name] = cli
        return cli

    def _get_field_type(self, column_info: dict) -> SearchField:
        SEARCH_FIELD_DATA_TYPES = [
            ("string", SearchFieldDataType.String),
            ("boolean", SearchFieldDataType.Boolean),
            ("int32", SearchFieldDataType.Int32),
            ("int64", SearchFieldDataType.Int64),
            ("double", SearchFieldDataType.Double),
            ("datetimeoffset", SearchFieldDataType.DateTimeOffset),
        ]

        field_data_type = None
        analyzer_name = None
        sortable = True
        searchable = False

        is_collection = column_info.get("is_collection", False)
        for data_type in SEARCH_FIELD_DATA_TYPES:
            if data_type[0] == column_info["type"].lower():
                if data_type[0] == "string":
                    analyzer_name = "ko.lucene"
                    searchable = True
                if is_collection:
                    field_data_type = SearchFieldDataType.Collection(data_type[1])
                    sortable = False
                else:
                    field_data_type = data_type[1]

        if field_data_type is None:
            raise ValueError(f"Invalid column type: {column_info['type']}")

        return SearchField(
            name=column_info["name"],
            type=field_data_type,
            analyzer_name=analyzer_name,
            filterable=True,
            facetable=True,
            sortable=sortable,
            searchable=searchable,
        )

    def _create_index(self) -> None:
        index_client = SearchIndexClient(
            endpoint=self.endpoint,
            credential=self._credential,
        )

        try:
            index_client.get_index(self.index_name)
            existing = True
        except ResourceNotFoundError:
            existing = False

        if existing:
            return

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(
                name="collection",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=False,
            ),
            SimpleField(
                name="content", type=SearchFieldDataType.String, searchable=True
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
                vector_search_dimensions=self._infer_vector_dim(
                    self.aoai_embedding_model
                ),
                vector_search_profile_name="eknn_profile",
            ),
        ]

        if self.config.column_info:
            for column in self.config.column_info:
                fields.append(self._get_field_type(column))

        vector_search = VectorSearch(
            algorithms=[
                ExhaustiveKnnAlgorithmConfiguration(
                    name="eknn_algo",
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="eknn_profile",
                    algorithm_configuration_name="eknn_algo",
                    vectorizer_name="aoai_vectorizer",
                )
            ],
            vectorizers=[
                AzureOpenAIVectorizer(
                    vectorizer_name="aoai_vectorizer",
                    kind="azureOpenAI",
                    parameters=AzureOpenAIVectorizerParameters(
                        resource_url=self.aoai_endpoint,
                        deployment_name=self.aoai_embedding_model,
                        api_key=self.aoai_api_key,
                        model_name=self.aoai_embedding_model,
                    ),
                )
            ],
        )
        semantic_search = SemanticSearch(
            default_configuration_name="my-semantic-config",
            configurations=[
                SemanticConfiguration(
                    name="my-semantic-config",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=None,
                        content_fields=[SemanticField(field_name="content")],
                        keywords_fields=None,
                    ),
                )
            ],
        )

        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )
        index_client.create_index(index)

    async def insert_documents(self, documents: List[Dict[str, Any]]) -> None:
        client = self._get_client(self.index_name)
        await client.upload_documents(documents=documents)

    async def _search_documents(
        self,
        query: str,
        filter: Optional[str] = None,
        top_k: int = 10,
        top_k_vector: int = 30,
    ) -> List[Dict[str, Any]]:
        client = self._get_client(self.index_name)
        vector_query = VectorizableTextQuery(
            text=query,
            k_nearest_neighbors=top_k_vector,
            fields="vector",
            kind="text",
            exhaustive=True,
        )

        results = await client.search(
            search_text=query,
            filter=filter,
            top=top_k,
            vector_queries=[vector_query],
            select=["id", "content", "metadata"],
            query_type="semantic",
            semantic_configuration_name="my-semantic-config",
        )
        return results

    async def search_documents(
        self,
        filter: Optional[str] = None,
        queries: Union[str, List[str]] = None,
        top_k: int = 10,
        top_k_vector: int = 30,
        reranker_threshold: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """
        쿼리를 리스트로 받을 수 있으며 쿼리가 여러개인 경우 모든 쿼리의 결과를 합침
        쿼리의 결과를 reranker_threshold 이상의 score를 가지는 결과만 top_k 개 반환
        """
        all_results: List[Dict[str, Any]] = []
        query_list = [queries] if isinstance(queries, str) else queries

        for query in query_list:
            paged = await self._search_documents(
                query=query,
                filter=filter,
                top_k=top_k,
                top_k_vector=top_k_vector,
            )

            async for r in paged:
                all_results.append(r)

        filtered_results = [
            r
            for r in all_results
            if r.get("@search.reranker_score", 0) >= reranker_threshold
        ]

        filtered_results.sort(key=lambda x: x["@search.reranker_score"], reverse=True)
        return filtered_results[:top_k]
