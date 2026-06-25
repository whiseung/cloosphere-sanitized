"""
Azure AI Search implementation of AgentMemory.

This implementation uses Azure Cognitive Search for vector storage of tool usage patterns.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.aio import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        ExhaustiveKnnAlgorithmConfiguration,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        VectorSearch,
        VectorSearchProfile,
    )
    from azure.search.documents.models import VectorizedQuery

    AZURE_SEARCH_AVAILABLE = True
except ImportError:
    AZURE_SEARCH_AVAILABLE = False

from vanna.capabilities.agent_memory import (
    AgentMemory,
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
)
from vanna.core.tool import ToolContext


class AzureAISearchAgentMemory(AgentMemory):
    """Azure AI Search-based implementation of AgentMemory."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str = "tool-memories",
        # OpenAI text-embedding-3-large = 3072 dims
        dimension: int = 3072,
        # Optional: use Azure OpenAI embeddings instead of the demo hash embedding
        embedding_endpoint: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        embedding_deployment: Optional[str] = None,
        embedding_api_version: Optional[str] = None,
    ):
        if not AZURE_SEARCH_AVAILABLE:
            raise ImportError(
                "Azure Search is required for AzureAISearchAgentMemory. "
                "Install with: pip install azure-search-documents"
            )

        self.endpoint = endpoint
        self.api_key = api_key
        self.index_name = index_name
        self.dimension = dimension
        self.embedding_endpoint = embedding_endpoint
        self.embedding_api_key = embedding_api_key
        self.embedding_deployment = embedding_deployment
        self.embedding_api_version = embedding_api_version
        self._credential = AzureKeyCredential(api_key)
        self._search_client = None
        self._index_client = None

    def _get_index_client(self):
        """Get or create index client."""
        if self._index_client is None:
            self._index_client = SearchIndexClient(
                endpoint=self.endpoint, credential=self._credential
            )
            self._ensure_index_exists()
        return self._index_client

    def _get_search_client(self):
        """Get or create search client."""
        if self._search_client is None:
            self._get_index_client()  # Ensure index exists
            self._search_client = SearchClient(
                endpoint=self.endpoint,
                index_name=self.index_name,
                credential=self._credential,
            )
        return self._search_client

    def _ensure_index_exists(self):
        """Create index if it doesn't exist."""
        try:
            self._index_client.get_index(self.index_name)
        except Exception:
            # Create index with vector search configuration
            fields = [
                SearchField(
                    name="memory_id", type=SearchFieldDataType.String, key=True
                ),
                SearchField(
                    name="question", type=SearchFieldDataType.String, searchable=True
                ),
                SearchField(
                    name="tool_name", type=SearchFieldDataType.String, filterable=True
                ),
                SearchField(name="args_json", type=SearchFieldDataType.String),
                SearchField(
                    name="timestamp",
                    type=SearchFieldDataType.String,
                    sortable=True,
                    filterable=True,
                ),
                SearchField(
                    name="success", type=SearchFieldDataType.Boolean, filterable=True
                ),
                SearchField(name="metadata_json", type=SearchFieldDataType.String),
                SearchField(
                    name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=self.dimension,
                    # Azure AI Search (api-version >= 2023-11-01) requires a profile name
                    # that maps to vectorSearch.profiles[].name
                    vector_search_profile_name="vector-profile",
                ),
            ]

            # Newer Azure AI Search vector schema uses:
            # - vector_search.profiles (field references profile by name)
            # - vector_search.algorithms (profile references algorithm by name)
            vector_search = VectorSearch(
                algorithms=[
                    # Exact KNN (Exhaustive) - higher latency/cost, but exact results
                    ExhaustiveKnnAlgorithmConfiguration(name="vector-algorithm"),
                ],
                profiles=[
                    VectorSearchProfile(
                        name="vector-profile",
                        algorithm_configuration_name="vector-algorithm",
                    )
                ],
            )
            semantic_search = SemanticSearch(
                default_configuration_name="default",
                configurations=[
                    SemanticConfiguration(
                        name="default",
                        prioritized_fields=SemanticPrioritizedFields(
                            title_field=None,
                            content_fields=[SemanticField(field_name="question")],
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

            self._index_client.create_index(index)

    async def _create_embedding(self, text: str) -> List[float]:
        """Create an embedding for vector search.

        - If Azure OpenAI embedding config is provided, calls embeddings API.
        - Otherwise falls back to a deterministic hash embedding (demo only).
        """
        if self.embedding_deployment:
            # Azure OpenAI embeddings
            try:
                from openai import AsyncAzureOpenAI
            except Exception as e:
                raise ImportError(
                    "openai package is required for Azure OpenAI embeddings. "
                    "Install with: pip install openai"
                ) from e

            if not self.embedding_endpoint or not self.embedding_api_key:
                raise ValueError(
                    "Azure OpenAI embeddings configured but missing embedding_endpoint or embedding_api_key"
                )

            api_version = self.embedding_api_version or "2024-10-21"
            # openai SDK 가 429/5xx 를 Retry-After 존중하며 자체 재시도.
            # 다른 임베딩 경로와 재시도 횟수를 일치시킨다.
            from open_webui.retrieval.embedding_retry import EMBEDDING_MAX_RETRIES

            client = AsyncAzureOpenAI(
                azure_endpoint=self.embedding_endpoint,
                api_key=self.embedding_api_key,
                api_version=api_version,
                max_retries=EMBEDDING_MAX_RETRIES,
            )

            resp = await client.embeddings.create(
                model=self.embedding_deployment, input=text
            )
            embedding = resp.data[0].embedding
            if self.dimension and len(embedding) != self.dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(embedding)}. "
                    "Fix dimension or embedding model/deployment."
                )
            return embedding

        # Demo fallback (NOT for production-quality retrieval)
        import hashlib

        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [(hash_val >> i) % 100 / 100.0 for i in range(self.dimension)]

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a tool usage pattern."""

        client = self._get_search_client()

        memory_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        embedding = await self._create_embedding(question)

        document = {
            "memory_id": memory_id,
            "question": question,
            "tool_name": tool_name,
            "args_json": json.dumps(args),
            "timestamp": timestamp,
            "success": success,
            "metadata_json": json.dumps(metadata or {}),
            "embedding": embedding,
        }

        await client.upload_documents(documents=[document])

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        """Search for similar tool usage patterns."""

        client = self._get_search_client()

        embedding = await self._create_embedding(question)

        # Build filter
        filter_expr = "success eq true"
        if tool_name_filter:
            filter_expr += f" and tool_name eq '{tool_name_filter}'"

        results = await client.search(
            search_text=question,
            vector_queries=[
                VectorizedQuery(
                    vector=embedding,
                    k_nearest_neighbors=limit,
                    fields="embedding",
                )
            ],
            filter=filter_expr,
            top=limit,
            query_type="semantic",
            semantic_configuration_name="default",
        )

        search_results = []
        async for doc in results:
            # Azure returns similarity score in @search.score
            similarity_score = doc.get("@search.reranker_score", 0)

            if similarity_score >= similarity_threshold:
                search_results.append(doc)

        output_results = []
        i = 0
        search_results.sort(key=lambda x: x["@search.reranker_score"], reverse=True)
        for doc in search_results:
            i += 1
            args = json.loads(doc.get("args_json", "{}"))
            metadata_dict = json.loads(doc.get("metadata_json", "{}"))

            memory = ToolMemory(
                memory_id=doc["memory_id"],
                question=doc["question"],
                tool_name=doc["tool_name"],
                args=args,
                timestamp=doc.get("timestamp"),
                success=doc.get("success", True),
                metadata=metadata_dict,
            )

            output_results.append(
                ToolMemorySearchResult(
                    memory=memory, similarity_score=similarity_score, rank=i + 1
                )
            )

        return output_results

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        """Get recently added memories."""

        client = self._get_search_client()

        results = await client.search(
            search_text="*", top=limit, order_by=["timestamp desc"]
        )

        memories = []
        async for doc in results:
            args = json.loads(doc.get("args_json", "{}"))
            metadata_dict = json.loads(doc.get("metadata_json", "{}"))

            memory = ToolMemory(
                memory_id=doc["memory_id"],
                question=doc["question"],
                tool_name=doc["tool_name"],
                args=args,
                timestamp=doc.get("timestamp"),
                success=doc.get("success", True),
                metadata=metadata_dict,
            )
            memories.append(memory)

        return memories

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a memory by its ID."""

        client = self._get_search_client()

        try:
            await client.delete_documents(documents=[{"memory_id": memory_id}])
            return True
        except Exception:
            return False

    async def save_text_memory(self, content: str, context: ToolContext) -> TextMemory:
        """Save a text memory."""

        client = self._get_search_client()

        memory_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        embedding = await self._create_embedding(content)

        document = {
            "memory_id": memory_id,
            "question": content,
            "timestamp": timestamp,
            "embedding": embedding,
        }

        await client.upload_documents(documents=[document])

        return TextMemory(memory_id=memory_id, content=content, timestamp=timestamp)

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        """Search for similar text memories."""

        client = self._get_search_client()

        embedding = await self._create_embedding(query)

        results = await client.search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(
                    vector=embedding,
                    k_nearest_neighbors=limit,
                    fields="embedding",
                )
            ],
            top=limit,
            query_type="semantic",
            semantic_configuration_name="default",
        )

        search_results = []
        async for doc in results:
            similarity_score = doc.get("@search.reranker_score", 0)

            search_results.append(doc)

        output_results = []
        i = 0
        search_results.sort(key=lambda x: x["@search.reranker_score"], reverse=True)
        for doc in search_results:
            i += 1
            if similarity_score >= similarity_threshold:
                memory = TextMemory(
                    memory_id=doc["memory_id"],
                    content=doc.get("question", ""),
                    timestamp=doc.get("timestamp"),
                )

                output_results.append(
                    TextMemorySearchResult(
                        memory=memory, similarity_score=similarity_score, rank=i + 1
                    )
                )

        return output_results

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        """Get recently added text memories."""

        client = self._get_search_client()

        results = await client.search(
            search_text="*", top=limit, order_by=["timestamp desc"]
        )

        memories = []
        async for doc in results:
            # Skip if this is a tool memory (has tool_name field)
            if "tool_name" in doc:
                continue

            memory = TextMemory(
                memory_id=doc["memory_id"],
                content=doc.get("question", ""),
                timestamp=doc.get("timestamp"),
            )
            memories.append(memory)

        return memories[:limit]

    async def delete_text_memory(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a text memory by its ID."""

        client = self._get_search_client()

        try:
            await client.delete_documents(documents=[{"memory_id": memory_id}])
            return True
        except Exception:
            return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        """Clear stored memories."""

        client = self._get_search_client()

        # Build filter
        filter_parts = []
        if tool_name:
            filter_parts.append(f"tool_name eq '{tool_name}'")
        if before_date:
            filter_parts.append(f"timestamp lt '{before_date}'")

        filter_expr = " and ".join(filter_parts) if filter_parts else None

        # Search for documents to delete
        results = await client.search(
            search_text="*", filter=filter_expr, select=["memory_id"]
        )

        docs_to_delete = [{"memory_id": doc["memory_id"]} async for doc in results]

        if docs_to_delete:
            client.delete_documents(documents=docs_to_delete)

        return len(docs_to_delete)
