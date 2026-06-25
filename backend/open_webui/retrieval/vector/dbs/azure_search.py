import json
import logging
import os
from typing import Any, Dict, List, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.retrieval.vector.main import GetResult, SearchResult, VectorItem

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


def _require_sdk():
    try:
        import azure.search.documents  # noqa: F401
        import azure.search.documents.indexes  # noqa: F401

        return True
    except Exception as e:
        raise RuntimeError(
            "azure-search-documents package required. Install: pip install azure-search-documents"
        ) from e


class AzureSearchClient:
    """
    Azure AI Search based vector store implementation for Open WebUI 0.6.5

    Environment variables:
    - AZURE_SEARCH_ENDPOINT: e.g. https://<service>.search.windows.net
    - AZURE_SEARCH_API_KEY: Admin key
    - AZURE_SEARCH_INDEX: Index name (acts as collection)
    - AZURE_SEARCH_VECTOR_DIM: Vector dimension (default: 1536)
    """

    def __init__(self):
        _require_sdk()
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
        from azure.search.documents.indexes import SearchIndexClient

        self.endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "")
        self.api_key = os.getenv("AZURE_SEARCH_API_KEY", "")
        self.index_name = os.getenv("AZURE_SEARCH_INDEX", "openwebui")

        # Vector configuration
        self.vector_field = "vector"
        self.text_field = "content"
        self.metadata_field = "metadata"
        # KB 질의예시 생성 기능용 필드
        self.sample_questions_field = "sample_questions"
        self.vector_question_field = "vector_question"
        self.vector_dim = self._infer_vector_dim()

        try:
            self.batch_size = int(os.getenv("AZURE_SEARCH_BATCH_SIZE", "500"))
        except ValueError:
            self.batch_size = 500
        self.batch_size = max(1, min(self.batch_size, 1000))

        if not (self.endpoint and self.api_key):
            raise RuntimeError(
                "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY environment variables required."
            )

        self.credential = AzureKeyCredential(self.api_key)
        self.index_client = SearchIndexClient(
            endpoint=self.endpoint, credential=self.credential
        )
        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential,
        )

        # Ensure index exists
        self._ensure_index()

    def _infer_vector_dim(self) -> int:
        """Infer vector dimension from environment or PersistentConfig"""
        explicit = os.getenv("AZURE_SEARCH_VECTOR_DIM")
        if explicit and str(explicit).strip().isdigit():
            try:
                return int(str(explicit).strip())
            except Exception:
                pass

        # PersistentConfig(DB 설정) 우선, env fallback
        model = ""
        try:
            from open_webui.config import RAG_EMBEDDING_MODEL

            model = (RAG_EMBEDDING_MODEL.value or "").strip()
        except (ImportError, AttributeError):
            pass
        if not model:
            model = (
                os.getenv("AZURE_OPENAI_EMBEDDING_MODEL")
                or os.getenv("RAG_EMBEDDING_MODEL")
                or ""
            )
        model = model.lower()

        # Common model dimension mappings
        model_dims = {
            "text-embedding-3-large": 3072,
            "text-embedding-3-small": 1536,
            "text-embedding-ada-002": 1536,
            "sentence-transformers/all-minilm-l6-v2": 384,
            "intfloat/multilingual-e5-large": 1024,
            "intfloat/multilingual-e5-base": 768,
            "mxbai-embed-large": 1024,
            "nomic-embed-text-v1.5": 768,
        }

        for key, dim in model_dims.items():
            if key in model:
                return dim

        return 1536  # Default

    def _ensure_index(self) -> None:
        """Create index if it doesn't exist"""
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        try:
            existing = self.index_client.get_index(self.index_name)
            # Verify vector dimension and check for new fields
            has_question_fields = False
            for f in existing.fields:
                if getattr(f, "name", None) == self.vector_field:
                    existing_dim = getattr(f, "vector_search_dimensions", None)
                    if existing_dim and int(existing_dim) != int(self.vector_dim):
                        log.warning(
                            f"Index vector dim {existing_dim} != expected {self.vector_dim}. Recreating."
                        )
                        self.index_client.delete_index(self.index_name)
                        break
                if getattr(f, "name", None) == self.vector_question_field:
                    has_question_fields = True
            else:
                # Index exists - check if we need to add new fields
                if not has_question_fields:
                    log.info(
                        "Index exists but missing question fields. Will update on next insert."
                    )
                return  # Index exists and is valid
        except Exception:
            pass  # Index doesn't exist, create it

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(
                name="collection",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name=self.text_field,
                type=SearchFieldDataType.String,
                searchable=True,
            ),
            SimpleField(
                name=self.metadata_field,
                type=SearchFieldDataType.String,
                filterable=False,
                sortable=False,
                facetable=False,
            ),
            SearchField(
                name=self.vector_field,
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.vector_dim,
                vector_search_profile_name="hnsw_profile",
            ),
            # KB 질의예시 생성 기능용 필드
            SimpleField(
                name=self.sample_questions_field,
                type=SearchFieldDataType.String,
                searchable=True,  # BM25 하이브리드 검색용
            ),
            SearchField(
                name=self.vector_question_field,
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.vector_dim,
                vector_search_profile_name="hnsw_profile_question",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw_algo",
                    parameters={
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine",
                    },
                ),
                HnswAlgorithmConfiguration(
                    name="hnsw_algo_question",
                    parameters={
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine",
                    },
                ),
            ],
            profiles=[
                VectorSearchProfile(
                    name="hnsw_profile",
                    algorithm_configuration_name="hnsw_algo",
                ),
                VectorSearchProfile(
                    name="hnsw_profile_question",
                    algorithm_configuration_name="hnsw_algo_question",
                ),
            ],
        )

        index = SearchIndex(
            name=self.index_name, fields=fields, vector_search=vector_search
        )
        self.index_client.create_index(index)
        log.info(f"Created Azure Search index: {self.index_name}")

    def _chunk(self, items: List[Any], size: int):
        """Split items into chunks"""
        for i in range(0, len(items), size):
            yield items[i : i + size]

    def _result_to_get_result(self, results: List[Dict]) -> Optional[GetResult]:
        """Convert Azure Search results to GetResult format"""
        if not results:
            return None

        ids = []
        documents = []
        metadatas = []

        for doc in results:
            ids.append(doc.get("id"))
            documents.append(doc.get(self.text_field))
            metadata_str = doc.get(self.metadata_field, "{}")
            try:
                metadata = (
                    json.loads(metadata_str)
                    if isinstance(metadata_str, str)
                    else metadata_str
                )
            except Exception:
                metadata = {}
            metadatas.append(metadata)

        return GetResult(
            ids=[ids],
            documents=[documents],
            metadatas=[metadatas],
        )

    def _result_to_search_result(self, results: List[Dict]) -> Optional[SearchResult]:
        """Convert Azure Search results to SearchResult format"""
        if not results:
            return None

        ids = []
        distances = []
        documents = []
        metadatas = []

        for doc in results:
            ids.append(doc.get("id"))
            # Azure Search returns similarity score (higher is better)
            # Convert to distance (lower is better) by inverting
            score = doc.get("@search.score", 0)
            distances.append(1.0 - score if score else 1.0)
            documents.append(doc.get(self.text_field))
            metadata_str = doc.get(self.metadata_field, "{}")
            try:
                metadata = (
                    json.loads(metadata_str)
                    if isinstance(metadata_str, str)
                    else metadata_str
                )
            except Exception:
                metadata = {}
            metadatas.append(metadata)

        return SearchResult(
            ids=[ids],
            distances=[distances],
            documents=[documents],
            metadatas=[metadatas],
        )

    def has_collection(self, collection_name: str) -> bool:
        """Check if collection has any documents"""
        try:
            results = self.search_client.search(
                search_text="*",
                filter=f"collection eq '{collection_name}'",
                top=1,
            )
            return any(results)
        except Exception as e:
            log.exception(f"Error checking collection: {e}")
            return False

    def delete_collection(self, collection_name: str):
        """Delete all documents in a collection"""
        try:
            # Collect all document IDs in collection
            all_ids = []
            results = self.search_client.search(
                search_text="*",
                filter=f"collection eq '{collection_name}'",
                select=["id"],
                top=10000,
            )
            for doc in results:
                all_ids.append({"id": doc["id"]})

            if not all_ids:
                log.info(f"No documents found in collection {collection_name}")
                return

            # Batch delete
            for chunk in self._chunk(all_ids, self.batch_size):
                self.search_client.delete_documents(chunk)

            log.info(
                f"Deleted {len(all_ids)} documents from collection {collection_name}"
            )
        except Exception as e:
            log.exception(f"Error deleting collection {collection_name}: {e}")
            raise

    def search(
        self,
        collection_name: str,
        vectors: List[List[float]],
        limit: int,
        use_multi_vector: bool = False,
        question_vector_weight: float = 0.5,
    ) -> Optional[SearchResult]:
        """
        Vector similarity search.

        Args:
            collection_name: Collection to search in
            vectors: Query vectors (first vector is used)
            limit: Maximum number of results
            use_multi_vector: Whether to also search vector_question field
            question_vector_weight: Weight for vector_question results (0.0-1.0)

        Returns:
            SearchResult or None
        """
        if not vectors:
            return None

        try:
            from azure.search.documents.models import VectorizedQuery

            query_vector = vectors[0]  # Use first vector for search

            vector_queries = [
                VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=limit,
                    fields=self.vector_field,
                )
            ]

            # 멀티 벡터 검색: vector_question 필드도 검색
            if use_multi_vector:
                vector_queries.append(
                    VectorizedQuery(
                        vector=query_vector,
                        k_nearest_neighbors=limit,
                        fields=self.vector_question_field,
                        weight=question_vector_weight,
                    )
                )
                # 기본 벡터의 가중치 조정
                vector_queries[0] = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=limit,
                    fields=self.vector_field,
                    weight=1.0 - question_vector_weight,
                )

            results = list(
                self.search_client.search(
                    search_text=None,
                    vector_queries=vector_queries,
                    filter=f"collection eq '{collection_name}'",
                    top=limit,
                )
            )

            return self._result_to_search_result(results)
        except Exception as e:
            log.exception(f"Error searching: {e}")
            return None

    def search_multi_vector(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int,
        content_weight: float = 0.5,
        question_weight: float = 0.5,
    ) -> Optional[SearchResult]:
        """
        Multi-vector search combining content and question vectors.

        Args:
            collection_name: Collection to search in
            query_vector: Query embedding vector
            limit: Maximum number of results
            content_weight: Weight for content vector (default 0.5)
            question_weight: Weight for question vector (default 0.5)

        Returns:
            SearchResult or None
        """
        return self.search(
            collection_name=collection_name,
            vectors=[query_vector],
            limit=limit,
            use_multi_vector=True,
            question_vector_weight=question_weight,
        )

    def get(self, collection_name: str) -> Optional[GetResult]:
        """Get all documents in a collection"""
        try:
            results = list(
                self.search_client.search(
                    search_text="*",
                    filter=f"collection eq '{collection_name}'",
                    top=10000,
                )
            )
            return self._result_to_get_result(results)
        except Exception as e:
            log.exception(f"Error getting documents: {e}")
            return None

    def query(
        self, collection_name: str, filter: Dict, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        """Query documents with metadata filter"""
        if not self.has_collection(collection_name):
            return None

        try:
            # Build filter string: collection eq 'name' and metadata contains filter conditions
            filter_parts = [f"collection eq '{collection_name}'"]

            # Note: Azure Search stores metadata as JSON string, so filtering is limited
            # For proper metadata filtering, consider restructuring metadata as separate fields

            results = list(
                self.search_client.search(
                    search_text="*",
                    filter=" and ".join(filter_parts),
                    top=limit if limit else 10000,
                )
            )

            # Post-filter by metadata in Python since metadata is stored as JSON string
            if filter:
                filtered_results = []
                for doc in results:
                    metadata_str = doc.get(self.metadata_field, "{}")
                    try:
                        metadata = (
                            json.loads(metadata_str)
                            if isinstance(metadata_str, str)
                            else metadata_str
                        )
                        # Check if all filter conditions match
                        if all(metadata.get(k) == v for k, v in filter.items()):
                            filtered_results.append(doc)
                    except Exception:
                        continue
                results = filtered_results

            return self._result_to_get_result(results)
        except Exception as e:
            log.exception(f"Error querying documents: {e}")
            return None

    def insert(self, collection_name: str, items: List[VectorItem]):
        """Insert new documents"""
        try:
            documents = []
            for item in items:
                doc = {
                    "id": item["id"],
                    "collection": collection_name,
                    self.vector_field: item["vector"],
                    self.text_field: item["text"],
                    self.metadata_field: json.dumps(item.get("metadata", {})),
                }
                # KB 질의예시 생성 기능용 필드 추가
                sample_questions = item.get("sample_questions")
                if sample_questions:
                    doc[self.sample_questions_field] = sample_questions
                vector_question = item.get("vector_question")
                if vector_question:
                    doc[self.vector_question_field] = vector_question
                documents.append(doc)

            failed_docs = []
            for chunk in self._chunk(documents, self.batch_size):
                result = self.search_client.upload_documents(chunk)
                for r in result:
                    if not r.succeeded:
                        failed_docs.append(f"{r.key}: {r.error_message}")

            if failed_docs:
                error_msg = f"Failed to upload {len(failed_docs)} document(s): {'; '.join(failed_docs[:3])}"
                if len(failed_docs) > 3:
                    error_msg += f" ... and {len(failed_docs) - 3} more"
                raise RuntimeError(error_msg)

            log.info(f"Inserted {len(items)} documents to {collection_name}")
        except Exception as e:
            log.exception(f"Error inserting documents: {e}")
            raise

    def upsert(self, collection_name: str, items: List[VectorItem]):
        """Insert or update documents"""
        try:
            documents = []
            for item in items:
                doc = {
                    "id": item["id"],
                    "collection": collection_name,
                    self.vector_field: item["vector"],
                    self.text_field: item["text"],
                    self.metadata_field: json.dumps(item.get("metadata", {})),
                }
                # KB 질의예시 생성 기능용 필드 추가
                sample_questions = item.get("sample_questions")
                if sample_questions:
                    doc[self.sample_questions_field] = sample_questions
                vector_question = item.get("vector_question")
                if vector_question:
                    doc[self.vector_question_field] = vector_question
                documents.append(doc)

            failed_docs = []
            for chunk in self._chunk(documents, self.batch_size):
                result = self.search_client.merge_or_upload_documents(chunk)
                for r in result:
                    if not r.succeeded:
                        failed_docs.append(f"{r.key}: {r.error_message}")

            if failed_docs:
                error_msg = f"Failed to upsert {len(failed_docs)} document(s): {'; '.join(failed_docs[:3])}"
                if len(failed_docs) > 3:
                    error_msg += f" ... and {len(failed_docs) - 3} more"
                raise RuntimeError(error_msg)

            log.info(f"Upserted {len(items)} documents to {collection_name}")
        except Exception as e:
            log.exception(f"Error upserting documents: {e}")
            raise

    def delete(
        self,
        collection_name: str,
        ids: Optional[list[str]] = None,
        filter: Optional[dict] = None,
    ):
        try:
            if ids:
                self.search_client.delete_documents([{"id": _id} for _id in ids])
                log.info(f"Deleted {len(ids)} documents by ids from {collection_name}")
            elif filter and "id" in filter:
                v = filter["id"]
                id_list = v if isinstance(v, list) else [v]
                self.search_client.delete_documents(
                    [{"id": str(_id)} for _id in id_list]
                )
                log.info(
                    f"Deleted {len(id_list)} documents by id filter from {collection_name}"
                )
            elif filter and "file_id" in filter:
                file_id = filter["file_id"]
                # Collect all matching document IDs first
                docs_to_delete = []
                results = self.search_client.search(
                    search_text="*",
                    filter=f"collection eq '{collection_name}'",
                    select=["id", self.metadata_field],
                    top=10000,
                )
                for doc in results:
                    metadata = json.loads(doc.get(self.metadata_field, "{}"))
                    if metadata.get("file_id") == file_id:
                        docs_to_delete.append({"id": doc.get("id")})

                if docs_to_delete:
                    # Batch delete
                    for chunk in self._chunk(docs_to_delete, self.batch_size):
                        self.search_client.delete_documents(chunk)
                    log.info(
                        f"Deleted {len(docs_to_delete)} documents with file_id={file_id} from {collection_name}"
                    )
                else:
                    log.warning(
                        f"No documents found with file_id={file_id} in {collection_name}"
                    )
        except Exception as e:
            log.exception(f"Error deleting documents from {collection_name}: {e}")
            raise

    def reset(self):
        try:
            self.index_client.delete_index(self.index_name)
            log.info(f"Deleted index {self.index_name}")
        except Exception as e:
            # Index might not exist, which is fine
            log.debug(f"Could not delete index {self.index_name}: {e}")
        self._ensure_index()
