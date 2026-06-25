"""
Search Engine - 검색 엔진 추상화 레이어

Azure AI Search, pgvector, Elasticsearch, Vertex AI Search 등
다양한 벡터 DB를 통일된 인터페이스로 사용.

임베딩은 두 가지 방식으로 사용 가능:
1. 자동 임베딩: embedding_config 설정 시 검색할 때 자동으로 임베딩 생성 (사용량 추적 포함)
2. 수동 임베딩: 외부에서 임베딩을 생성하여 query_vector로 전달

Usage (자동 임베딩 - 관리자 설정 사용):
    >>> from extension_modules.search_engine import (
    ...     get_configured_search_engine,
    ...     create_knowledge_config,
    ...     SearchQuery,
    ... )
    >>>
    >>> # 관리자 설정 기반 엔진 생성 (with_embedding=True 기본값)
    >>> index_config = create_knowledge_config("kb_user123_knowledge456")
    >>> engine = get_configured_search_engine(request.app, index_config)
    >>> if engine:
    ...     async with engine:
    ...         # 자동 임베딩 사용 (user_id/chat_id로 사용량 추적)
    ...         results = await engine.search(query, user_id="user1", chat_id="chat1")

Usage (수동 임베딩 - 직접 설정):
    >>> from extension_modules.search_engine import (
    ...     get_search_engine,
    ...     create_knowledge_config,
    ...     AzureSearchConfig,
    ...     SearchQuery,
    ... )
    >>>
    >>> # 인덱스 설정 생성
    >>> config = create_knowledge_config("kb_user123_knowledge456")
    >>>
    >>> # 엔진 연결 설정
    >>> engine_config = AzureSearchConfig(
    ...     endpoint="https://xxx.search.windows.net",
    ...     api_key="xxx",
    ... )
    >>>
    >>> # 엔진 생성 및 사용 (embedding_config=None이면 수동 임베딩)
    >>> engine = get_search_engine(config, engine_config)
    >>> async with engine:
    ...     await engine.create_index()
    ...     await engine.insert([DocumentItem(id="1", content="Hello", vector=[...])])
    ...     results = await engine.search(SearchQuery(query="Hello"), query_vector=embedding)

Usage (자동 임베딩 - 직접 설정):
    >>> from extension_modules.search_engine import (
    ...     get_search_engine,
    ...     create_knowledge_config,
    ...     AzureSearchConfig,
    ...     EmbeddingConfig,
    ...     SearchQuery,
    ... )
    >>>
    >>> # 임베딩 설정 생성
    >>> embedding_config = EmbeddingConfig(
    ...     engine="azure_openai",
    ...     model="text-embedding-3-large",
    ...     url="https://xxx.openai.azure.com/",
    ...     api_key="xxx",
    ... )
    >>>
    >>> # 엔진 생성 (embedding_config 포함)
    >>> engine = get_search_engine(config, engine_config, embedding_config)
    >>> async with engine:
    ...     # 자동 임베딩 사용 (user_id/chat_id로 사용량 추적)
    ...     results = await engine.search(query, user_id="user1", chat_id="chat1")

Schema Presets:
    - create_knowledge_config(): 지식기반 (문서 RAG)
    - create_glossary_config(): 용어집 (용어/약어)
    - create_dbsphere_config(): DbSphere (DB 메타데이터)
"""

from .base import SearchEngineBase
from .connector import (
    EngineType,
    RerankerType,
    create_engine_with_index,
    get_configured_search_engine,
    get_engine_config_from_app,
    get_reranker,
    get_reranker_config_from_app,
    get_search_engine,
)
from .dbs import (
    AzureSearchEngine,
    ElasticsearchEngine,
    PgVectorEngine,
    VertexSearchEngine,
)
from .embedding import (
    MODEL_DIMENSIONS,
    EmbeddingConfig,
    EmbeddingResult,
    EmbeddingUsage,
    create_embedding_config,
    generate_embedding_async,
    generate_embeddings_async,
    get_embedding_config_from_app,
    get_embedding_dimension,
)
from .filter_translator import translate_odata_to_sql
from .models import (
    AzureSearchConfig,
    ColumnInfo,
    DocumentItem,
    ElasticsearchConfig,
    EngineConfig,
    IndexConfig,
    PgVectorConfig,
    RerankerConfig,
    SearchQuery,
    SearchResult,
    VertexRankerConfig,
    VertexSearchConfig,
)
from .reranker import NoopRanker, RerankerBase, VertexRanker
from .schemas import (
    DBSPHERE_MEMORY_COLUMNS,
    DBSPHERE_MEMORY_INDEX_NAME,
    GLOSSARY_COLUMNS,
    GLOSSARY_INDEX_NAME,
    KG_MEMORY_COLUMNS,
    KG_MEMORY_INDEX_NAME,
    KG_NODE_COLUMNS,
    KG_NODE_INDEX_NAME,
    KNOWLEDGE_COLUMNS,
    KNOWLEDGE_INDEX_NAME,
    create_dbsphere_memory_config,
    create_glossary_config,
    create_kg_memory_config,
    create_kg_node_config,
    create_knowledge_config,
    generate_index_name,
)

__all__ = [
    # Base
    "SearchEngineBase",
    # Engine Implementations
    "AzureSearchEngine",
    "PgVectorEngine",
    "ElasticsearchEngine",
    "VertexSearchEngine",
    # Models - Document & Search
    "DocumentItem",
    "SearchQuery",
    "SearchResult",
    "IndexConfig",
    "ColumnInfo",
    # Models - Engine Configs
    "EngineConfig",
    "AzureSearchConfig",
    "PgVectorConfig",
    "ElasticsearchConfig",
    "VertexSearchConfig",
    # Models - Reranker Configs
    "VertexRankerConfig",
    "RerankerConfig",
    # Reranker
    "RerankerBase",
    "VertexRanker",
    "NoopRanker",
    # Filter Translator
    "translate_odata_to_sql",
    # Factory
    "get_search_engine",
    "get_configured_search_engine",
    "get_engine_config_from_app",
    "create_engine_with_index",
    "get_reranker_config_from_app",
    "get_reranker",
    "EngineType",
    "RerankerType",
    # Schema Presets
    "create_knowledge_config",
    "create_glossary_config",
    "create_dbsphere_memory_config",
    "create_kg_node_config",
    "create_kg_memory_config",
    "generate_index_name",
    "KG_MEMORY_COLUMNS",
    "KG_MEMORY_INDEX_NAME",
    "KNOWLEDGE_COLUMNS",
    "KNOWLEDGE_INDEX_NAME",
    "GLOSSARY_COLUMNS",
    "GLOSSARY_INDEX_NAME",
    "DBSPHERE_MEMORY_COLUMNS",
    "DBSPHERE_MEMORY_INDEX_NAME",
    "KG_NODE_COLUMNS",
    "KG_NODE_INDEX_NAME",
    # Embedding
    "EmbeddingConfig",
    "EmbeddingResult",
    "EmbeddingUsage",
    "generate_embedding_async",
    "generate_embeddings_async",
    "get_embedding_config_from_app",
    "create_embedding_config",
    "get_embedding_dimension",
    "MODEL_DIMENSIONS",
]
