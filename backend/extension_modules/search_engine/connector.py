"""
Search Engine - 팩토리 커넥터
"""

import logging
from typing import TYPE_CHECKING, Literal, Optional, Tuple

from .base import SearchEngineBase
from .models import (
    AzureSearchConfig,
    ElasticsearchConfig,
    EngineConfig,
    IndexConfig,
    PgVectorConfig,
    RerankerConfig,
    VertexRankerConfig,
    VertexSearchConfig,
)

if TYPE_CHECKING:
    from .embedding import EmbeddingConfig
    from .reranker.base import RerankerBase

log = logging.getLogger(__name__)

# 지원하는 검색 엔진 타입
EngineType = Literal["azure_search", "pgvector", "elasticsearch", "vertex_search"]

# 지원하는 리랭커 타입
RerankerType = Literal["vertex"]


def get_engine_config_from_app(
    app,
) -> Tuple[Optional[EngineType], Optional[EngineConfig]]:
    """
    FastAPI app.state.config에서 검색 엔진 설정 추출.

    Args:
        app: FastAPI 애플리케이션 인스턴스

    Returns:
        Tuple[Optional[EngineType], Optional[EngineConfig]]:
            (엔진 타입, 엔진 설정) 또는 설정되지 않은 경우 (None, None)

    Example:
        >>> from fastapi import Request
        >>> engine_type, engine_config = get_engine_config_from_app(request.app)
        >>> if engine_config:
        ...     engine = get_search_engine(index_config, engine_config)
    """
    config = app.state.config
    engine_type = getattr(config, "SEARCH_ENGINE_TYPE", None)

    if not engine_type:
        return None, None

    if engine_type == "azure_search":
        return engine_type, AzureSearchConfig(
            endpoint=getattr(config, "SEARCH_ENGINE_AZURE_ENDPOINT", ""),
            api_key=getattr(config, "SEARCH_ENGINE_AZURE_API_KEY", ""),
            api_version=getattr(
                config, "SEARCH_ENGINE_AZURE_API_VERSION", "2024-07-01"
            ),
        )

    elif engine_type == "pgvector":
        return engine_type, PgVectorConfig(
            host=getattr(config, "SEARCH_ENGINE_PGVECTOR_HOST", "localhost"),
            port=getattr(config, "SEARCH_ENGINE_PGVECTOR_PORT", 5432),
            database=getattr(config, "SEARCH_ENGINE_PGVECTOR_DATABASE", "postgres"),
            user=getattr(config, "SEARCH_ENGINE_PGVECTOR_USER", "postgres"),
            password=getattr(config, "SEARCH_ENGINE_PGVECTOR_PASSWORD", ""),
        )

    elif engine_type == "elasticsearch":
        return engine_type, ElasticsearchConfig(
            url=getattr(
                config, "SEARCH_ENGINE_ELASTICSEARCH_URL", "http://localhost:9200"
            ),
            api_key=getattr(config, "SEARCH_ENGINE_ELASTICSEARCH_API_KEY", "") or None,
            user=getattr(config, "SEARCH_ENGINE_ELASTICSEARCH_USER", "") or None,
            password=getattr(config, "SEARCH_ENGINE_ELASTICSEARCH_PASSWORD", "")
            or None,
            ca_certs=getattr(config, "SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS", "")
            or None,
        )

    elif engine_type == "vertex_search":
        return engine_type, VertexSearchConfig(
            project_id=getattr(config, "SEARCH_ENGINE_VERTEX_PROJECT_ID", ""),
            location=getattr(config, "SEARCH_ENGINE_VERTEX_LOCATION", "us-central1"),
            service_account_key=getattr(
                config, "SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY", ""
            )
            or getattr(config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", "")
            or None,
        )

    return None, None


def get_reranker_config_from_app(
    app,
) -> Tuple[Optional[RerankerType], Optional[RerankerConfig]]:
    """
    FastAPI app.state.config에서 Reranker 설정 추출.

    Args:
        app: FastAPI 애플리케이션 인스턴스

    Returns:
        Tuple[Optional[RerankerType], Optional[RerankerConfig]]:
            (리랭커 타입, 리랭커 설정) 또는 설정되지 않은 경우 (None, None)
    """
    config = app.state.config
    reranker_type = getattr(config, "RERANKER_TYPE", None)

    if not reranker_type:
        return None, None

    if reranker_type == "vertex":
        return "vertex", VertexRankerConfig(
            project_id=getattr(config, "RERANKER_VERTEX_PROJECT_ID", "") or None,
            location=getattr(config, "RERANKER_VERTEX_LOCATION", "global"),
            model=getattr(
                config,
                "RERANKER_VERTEX_MODEL",
                "semantic-ranker-default@latest",
            ),
            service_account_key=getattr(
                config, "RERANKER_VERTEX_SERVICE_ACCOUNT_KEY", ""
            )
            or getattr(config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", "")
            or None,
        )

    return None, None


def get_reranker(reranker_config: RerankerConfig) -> "RerankerBase":
    """
    RerankerConfig → RerankerBase 인스턴스 생성.

    Args:
        reranker_config: 리랭커 설정

    Returns:
        RerankerBase: 리랭커 인스턴스
    """
    if isinstance(reranker_config, VertexRankerConfig):
        from .reranker.vertex_ranker import VertexRanker

        return VertexRanker(
            project_id=reranker_config.project_id,
            location=reranker_config.location,
            model=reranker_config.model,
            service_account_key=reranker_config.service_account_key,
        )

    # fallback
    from .reranker.noop_ranker import NoopRanker

    return NoopRanker()


def get_configured_search_engine(
    app,
    index_config: IndexConfig,
    with_embedding: bool = True,
) -> Optional[SearchEngineBase]:
    """
    app.state.config 설정을 기반으로 검색 엔진 인스턴스 생성.

    Args:
        app: FastAPI 애플리케이션 인스턴스
        index_config: 인덱스 설정
        with_embedding: 임베딩 설정 포함 여부 (기본값: True)

    Returns:
        Optional[SearchEngineBase]: 검색 엔진 인스턴스 또는 None (설정되지 않은 경우)

    Example:
        >>> from extension_modules.search_engine import (
        ...     get_configured_search_engine,
        ...     create_knowledge_config,
        ... )
        >>>
        >>> index_config = create_knowledge_config("kb_user123_knowledge456")
        >>> engine = get_configured_search_engine(request.app, index_config)
        >>> if engine:
        ...     async with engine:
        ...         # 자동 임베딩 사용
        ...         results = await engine.search(query, user_id="user1", chat_id="chat1")
    """
    engine_type, engine_config = get_engine_config_from_app(app)

    if not engine_config:
        return None

    # 임베딩 설정 추출
    embedding_config = None
    if with_embedding:
        from .embedding import get_embedding_config_from_app

        try:
            embedding_config = get_embedding_config_from_app(app)
        except Exception:
            pass  # 임베딩 설정 없으면 None 유지

    # pgvector일 때만 reranker 생성
    reranker = None
    if engine_type == "pgvector":
        _, reranker_config = get_reranker_config_from_app(app)
        if reranker_config:
            reranker = get_reranker(reranker_config)

    return get_search_engine(index_config, engine_config, embedding_config, reranker)


def get_search_engine(
    config: IndexConfig,
    engine_config: EngineConfig,
    embedding_config: Optional["EmbeddingConfig"] = None,
    reranker: Optional["RerankerBase"] = None,
) -> SearchEngineBase:
    """
    검색 엔진 인스턴스 생성 팩토리.

    Args:
        config: 인덱스 설정
        engine_config: 엔진별 연결 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.
        reranker: 리랭커 인스턴스 (선택). pgvector 엔진에서 사용.

    Returns:
        SearchEngineBase: 검색 엔진 인스턴스

    Raises:
        ValueError: 지원하지 않는 엔진 설정 타입
        RuntimeError: 엔진 초기화 실패

    Example:
        >>> from extension_modules.search_engine import (
        ...     get_search_engine,
        ...     IndexConfig,
        ...     AzureSearchConfig,
        ...     EmbeddingConfig,
        ... )
        >>>
        >>> config = IndexConfig(index_name="my_knowledge")
        >>> engine_config = AzureSearchConfig(
        ...     endpoint="https://xxx.search.windows.net",
        ...     api_key="xxx",
        ... )
        >>> embedding_config = EmbeddingConfig(
        ...     engine="azure_openai",
        ...     model="text-embedding-3-large",
        ...     url="https://xxx.openai.azure.com/",
        ...     api_key="xxx",
        ... )
        >>> engine = get_search_engine(config, engine_config, embedding_config)
        >>> async with engine:
        ...     # 자동 임베딩 사용 (user_id, chat_id로 사용량 추적)
        ...     results = await engine.search(query, user_id="user1", chat_id="chat1")
    """
    if isinstance(engine_config, AzureSearchConfig):
        from .dbs.azure_search import AzureSearchEngine

        return AzureSearchEngine(config, engine_config, embedding_config)

    elif isinstance(engine_config, PgVectorConfig):
        from .dbs.pgvector import PgVectorEngine

        return PgVectorEngine(config, engine_config, embedding_config, reranker)

    elif isinstance(engine_config, ElasticsearchConfig):
        from .dbs.elasticsearch import ElasticsearchEngine

        return ElasticsearchEngine(config, engine_config, embedding_config)

    elif isinstance(engine_config, VertexSearchConfig):
        from .dbs.vertex_search import VertexSearchEngine

        return VertexSearchEngine(config, engine_config, embedding_config)

    else:
        raise ValueError(
            f"Unsupported engine config type: {type(engine_config).__name__}. "
            f"Supported configs: AzureSearchConfig, PgVectorConfig, "
            f"ElasticsearchConfig, VertexSearchConfig"
        )


async def create_engine_with_index(
    config: IndexConfig,
    engine_config: EngineConfig,
    embedding_config: Optional["EmbeddingConfig"] = None,
) -> SearchEngineBase:
    """
    검색 엔진 생성 및 인덱스 초기화.

    Args:
        config: 인덱스 설정
        engine_config: 엔진별 연결 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.

    Returns:
        SearchEngineBase: 인덱스가 생성된 검색 엔진 인스턴스
    """
    engine = get_search_engine(config, engine_config, embedding_config)
    await engine.create_index()
    return engine
