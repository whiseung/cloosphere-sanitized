"""
Search Engine - 임베딩 모듈

비동기 임베딩 생성 및 사용량 추적을 지원합니다.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Union

if TYPE_CHECKING:
    from open_webui.utils.tracing import TraceContext

import aiohttp
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# =============================================================================
# Null Context Manager (for optional tracing)
# =============================================================================


class _NullAsyncContextManager:
    """No-op async context manager for when tracing is disabled."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


def _null_async_context():
    return _NullAsyncContextManager()


# =============================================================================
# 임베딩 설정 모델
# =============================================================================


class EmbeddingConfig(BaseModel):
    """임베딩 설정"""

    engine: Literal["openai", "azure_openai", "ollama", "gemini", "vertex_ai"] = (
        "azure_openai"
    )
    model: str = "text-embedding-3-large"
    url: str = ""  # API Base URL
    api_key: str = ""
    api_version: Optional[str] = "2024-02-15-preview"  # Azure OpenAI용
    batch_size: int = Field(default=100, ge=1, le=2048)
    dimensions: Optional[int] = None  # 모델별 자동 추론
    # Vertex AI 전용
    vertex_ai_project_id: Optional[str] = None
    vertex_ai_location: Optional[str] = "us-central1"
    vertex_ai_service_account_key: Optional[str] = None


class EmbeddingUsage(BaseModel):
    """임베딩 사용량"""

    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResult(BaseModel):
    """임베딩 결과"""

    embeddings: List[List[float]]
    usage: EmbeddingUsage


# =============================================================================
# 임베딩 차원 매핑
# =============================================================================


MODEL_DIMENSIONS: Dict[str, int] = {
    # OpenAI/Azure OpenAI
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    # Google Gemini / Vertex AI
    "gemini-embedding-001": 3072,
    "text-embedding-004": 768,
    "text-embedding-005": 768,
    "textembedding-gecko": 768,
    "textembedding-gecko-multilingual": 768,
    # Sentence-Transformers
    "sentence-transformers/all-minilm-l6-v2": 384,
    "intfloat/multilingual-e5-large": 1024,
    "intfloat/multilingual-e5-base": 768,
    "intfloat/e5-large": 1024,
    "intfloat/e5-base": 768,
    "mxbai-embed-large": 1024,
    "gte-large": 1024,
    "nomic-embed-text-v1.5": 768,
    # Ollama 기본 모델
    "nomic-embed-text": 768,
    "all-minilm": 384,
}


def get_embedding_dimension(model: str) -> int:
    """모델명으로 임베딩 네이티브 차원 조회"""
    # 정확한 매칭
    if model in MODEL_DIMENSIONS:
        return MODEL_DIMENSIONS[model]

    # 부분 매칭
    for key, dim in MODEL_DIMENSIONS.items():
        if key in model.lower():
            return dim

    # 기본값
    return 1536


def get_effective_embedding_dimension(app) -> int:
    """
    관리자 설정(RAG_EMBEDDING_DIMENSIONS) 우선, 없으면 모델 네이티브 차원 반환.

    pgvector HNSW 등 벡터 DB 테이블 생성 시 사용.
    """
    config = app.state.config
    raw_dim = _get_value(getattr(config, "RAG_EMBEDDING_DIMENSIONS", None))
    if raw_dim and int(raw_dim) > 0:
        return int(raw_dim)

    model = _get_value(getattr(config, "RAG_EMBEDDING_MODEL", None))
    if not model:
        raise RuntimeError(
            "RAG_EMBEDDING_MODEL is not configured. "
            "Set it in admin settings → Documents → Embedding model."
        )
    return get_embedding_dimension(model)


# =============================================================================
# 비동기 임베딩 생성 함수
# =============================================================================


async def generate_embeddings_async(
    texts: Union[str, List[str]],
    config: EmbeddingConfig,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    trace_context: Optional["TraceContext"] = None,
) -> EmbeddingResult:
    """
    비동기로 텍스트 임베딩을 생성합니다.

    Args:
        texts: 임베딩할 텍스트 또는 텍스트 리스트
        config: 임베딩 설정
        user_id: 사용량 추적용 사용자 ID (선택)
        chat_id: 사용량 추적용 채팅 ID (선택)
        trace_context: 트레이싱 컨텍스트 (선택)

    Returns:
        EmbeddingResult: 임베딩 벡터와 사용량 정보

    Raises:
        RuntimeError: 임베딩 생성 실패
    """
    text_list = [texts] if isinstance(texts, str) else texts

    if not text_list:
        return EmbeddingResult(embeddings=[], usage=EmbeddingUsage())

    # Setup tracing context manager
    if trace_context and trace_context.enabled:
        from open_webui.models.message_trace import RunType

        ctx_manager = trace_context.start_run_async(
            run_type=RunType.EMBEDDING.value,
            name="embedding",
            inputs={
                "text_count": len(text_list),
                "model": config.model,
                "texts": text_list,
            },
            model_id=config.model,
            push_stack=False,  # leaf 노드 — 동시 실행 시 _run_stack 오염 방지
        )
    else:
        ctx_manager = _null_async_context()

    async with ctx_manager as run:
        if config.engine == "azure_openai":
            result = await _generate_azure_openai_embeddings(text_list, config)
        elif config.engine == "openai":
            result = await _generate_openai_embeddings(text_list, config)
        elif config.engine == "ollama":
            result = await _generate_ollama_embeddings(text_list, config)
        elif config.engine == "gemini":
            result = await _generate_gemini_embeddings(text_list, config)
        elif config.engine == "vertex_ai":
            result = await _generate_vertex_ai_embeddings(text_list, config)
        else:
            raise ValueError(f"Unsupported embedding engine: {config.engine}")

        # 사용량 기록 (user_id와 chat_id가 있는 경우)
        if user_id and chat_id and result.usage.total_tokens > 0:
            await _record_embedding_usage(
                user_id=user_id,
                chat_id=chat_id,
                model=config.model,
                usage=result.usage,
            )

        # Set tracing outputs
        if run:
            run.set_outputs(
                {
                    "embedding_count": len(result.embeddings),
                    "total_tokens": result.usage.total_tokens,
                }
            )
            run.set_token_usage(
                {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "total_tokens": result.usage.total_tokens,
                }
            )

        return result


async def generate_embedding_async(
    text: str,
    config: EmbeddingConfig,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    trace_context: Optional["TraceContext"] = None,
) -> List[float]:
    """
    단일 텍스트에 대한 임베딩을 생성합니다.

    Args:
        text: 임베딩할 텍스트
        config: 임베딩 설정
        user_id: 사용량 추적용 사용자 ID (선택)
        chat_id: 사용량 추적용 채팅 ID (선택)
        trace_context: 트레이싱 컨텍스트 (선택)

    Returns:
        List[float]: 임베딩 벡터
    """
    result = await generate_embeddings_async(
        texts=text,
        config=config,
        user_id=user_id,
        chat_id=chat_id,
        trace_context=trace_context,
    )

    if not result.embeddings:
        raise RuntimeError(f"Failed to generate embedding for text: {text[:50]}...")

    return result.embeddings[0]


# =============================================================================
# 엔진별 구현
# =============================================================================


async def _generate_azure_openai_embeddings(
    texts: List[str],
    config: EmbeddingConfig,
) -> EmbeddingResult:
    """Azure OpenAI 임베딩 생성"""
    if not config.url:
        raise RuntimeError("Azure OpenAI URL is required")
    if not config.api_key:
        raise RuntimeError("Azure OpenAI API key is required")

    url = config.url.rstrip("/")
    api_version = config.api_version or "2024-02-15-preview"
    endpoint = (
        f"{url}/openai/deployments/{config.model}/embeddings?api-version={api_version}"
    )

    headers = {
        "Content-Type": "application/json",
        "api-key": config.api_key,
    }

    all_embeddings: List[List[float]] = []
    total_usage = EmbeddingUsage()

    from open_webui.retrieval.embedding_retry import (
        RETRYABLE_STATUS,
        RetryableEmbeddingError,
        embedding_retry,
    )

    @embedding_retry
    async def _post_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    # 429/5xx 는 transient → 재시도 (서버 Retry-After 존중)
                    if response.status in RETRYABLE_STATUS:
                        raise RetryableEmbeddingError(
                            response.status,
                            f"Azure OpenAI embedding error: {response.status} - {error_text}",
                            retry_after=response.headers.get("Retry-After"),
                        )
                    raise RuntimeError(
                        f"Azure OpenAI embedding error: {response.status} - {error_text}"
                    )
                return await response.json()

    # 배치 처리
    for i in range(0, len(texts), config.batch_size):
        batch = texts[i : i + config.batch_size]

        payload: Dict[str, Any] = {
            "input": batch,
        }
        if config.dimensions:
            payload["dimensions"] = config.dimensions

        data = await _post_batch(payload)

        # 임베딩 추출 (index 순서대로 정렬)
        embeddings_data = sorted(data.get("data", []), key=lambda x: x["index"])
        for item in embeddings_data:
            all_embeddings.append(item["embedding"])

        # 사용량 집계
        usage = data.get("usage", {})
        total_usage.prompt_tokens += usage.get("prompt_tokens", 0)
        total_usage.total_tokens += usage.get("total_tokens", 0)

    return EmbeddingResult(embeddings=all_embeddings, usage=total_usage)


async def _generate_openai_embeddings(
    texts: List[str],
    config: EmbeddingConfig,
) -> EmbeddingResult:
    """OpenAI 임베딩 생성"""
    url = config.url.rstrip("/") if config.url else "https://api.openai.com/v1"
    endpoint = f"{url}/embeddings"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }

    all_embeddings: List[List[float]] = []
    total_usage = EmbeddingUsage()

    from open_webui.retrieval.embedding_retry import (
        RETRYABLE_STATUS,
        RetryableEmbeddingError,
        embedding_retry,
    )

    @embedding_retry
    async def _post_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    if response.status in RETRYABLE_STATUS:
                        raise RetryableEmbeddingError(
                            response.status,
                            f"OpenAI embedding error: {response.status} - {error_text}",
                            retry_after=response.headers.get("Retry-After"),
                        )
                    raise RuntimeError(
                        f"OpenAI embedding error: {response.status} - {error_text}"
                    )
                return await response.json()

    for i in range(0, len(texts), config.batch_size):
        batch = texts[i : i + config.batch_size]

        payload: Dict[str, Any] = {
            "model": config.model,
            "input": batch,
        }
        if config.dimensions:
            payload["dimensions"] = config.dimensions

        data = await _post_batch(payload)

        embeddings_data = sorted(data.get("data", []), key=lambda x: x["index"])
        for item in embeddings_data:
            all_embeddings.append(item["embedding"])

        usage = data.get("usage", {})
        total_usage.prompt_tokens += usage.get("prompt_tokens", 0)
        total_usage.total_tokens += usage.get("total_tokens", 0)

    return EmbeddingResult(embeddings=all_embeddings, usage=total_usage)


async def _generate_ollama_embeddings(
    texts: List[str],
    config: EmbeddingConfig,
) -> EmbeddingResult:
    """Ollama 임베딩 생성"""
    url = config.url.rstrip("/") if config.url else "http://localhost:11434"
    endpoint = f"{url}/api/embed"

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    all_embeddings: List[List[float]] = []

    from open_webui.retrieval.embedding_retry import (
        RETRYABLE_STATUS,
        RetryableEmbeddingError,
        embedding_retry,
    )

    # Ollama는 배치 요청을 지원
    payload = {
        "model": config.model,
        "input": texts,
    }

    @embedding_retry
    async def _post() -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    if response.status in RETRYABLE_STATUS:
                        raise RetryableEmbeddingError(
                            response.status,
                            f"Ollama embedding error: {response.status} - {error_text}",
                            retry_after=response.headers.get("Retry-After"),
                        )
                    raise RuntimeError(
                        f"Ollama embedding error: {response.status} - {error_text}"
                    )
                return await response.json()

    data = await _post()
    all_embeddings = data.get("embeddings", [])

    # Ollama는 토큰 사용량을 제공하지 않음
    return EmbeddingResult(
        embeddings=all_embeddings,
        usage=EmbeddingUsage(),
    )


async def _generate_gemini_embeddings(
    texts: List[str],
    config: EmbeddingConfig,
) -> EmbeddingResult:
    """Gemini 임베딩 생성 (google-generativeai SDK)"""
    import asyncio

    import google.generativeai as genai

    genai.configure(api_key=config.api_key)

    def _sync_embed():
        kwargs: Dict[str, Any] = {"model": config.model, "content": texts}
        if config.dimensions:
            kwargs["output_dimensionality"] = config.dimensions
        result = genai.embed_content(**kwargs)
        return result["embedding"]

    from open_webui.retrieval.embedding_retry import embedding_retry

    @embedding_retry
    async def _embed():
        return await asyncio.get_event_loop().run_in_executor(None, _sync_embed)

    embeddings = await _embed()
    return EmbeddingResult(embeddings=embeddings, usage=EmbeddingUsage())


async def _generate_vertex_ai_embeddings(
    texts: List[str],
    config: EmbeddingConfig,
) -> EmbeddingResult:
    """Vertex AI 임베딩 생성 (vertexai SDK)"""
    import asyncio
    import json as json_module

    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    def _sync_embed():
        service_account_key = config.vertex_ai_service_account_key or ""
        project_id = config.vertex_ai_project_id or ""
        location = config.vertex_ai_location or "us-central1"

        if service_account_key:
            from google.oauth2 import service_account

            key_info = json_module.loads(service_account_key)
            resolved_project = project_id or key_info.get("project_id", "")
            credentials = service_account.Credentials.from_service_account_info(
                key_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            vertexai.init(
                project=resolved_project, location=location, credentials=credentials
            )
        else:
            vertexai.init(project=project_id or None, location=location)

        embedding_model = TextEmbeddingModel.from_pretrained(config.model)
        kwargs: Dict[str, Any] = {}
        if config.dimensions:
            kwargs["output_dimensionality"] = config.dimensions
        response = embedding_model.get_embeddings(texts, **kwargs)
        return [e.values for e in response]

    from open_webui.retrieval.embedding_retry import embedding_retry

    @embedding_retry
    async def _embed():
        return await asyncio.get_event_loop().run_in_executor(None, _sync_embed)

    embeddings = await _embed()
    return EmbeddingResult(embeddings=embeddings, usage=EmbeddingUsage())


# =============================================================================
# 사용량 기록
# =============================================================================


async def _record_embedding_usage(
    user_id: str,
    chat_id: str,
    model: str,
    usage: EmbeddingUsage,
) -> None:
    """
    임베딩 사용량을 데이터베이스에 기록합니다.
    """
    try:
        from open_webui.models.usage import UsageMessageType, Usages

        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=chat_id,
            agent_id=None,
            model_id=model,
            message_id=f"embedding:{chat_id}",
            message_type=UsageMessageType.EMBEDDING,
            total_tokens=usage.total_tokens,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "total_tokens": usage.total_tokens,
            },
        )
        log.debug(f"Embedding usage recorded: {usage.total_tokens} tokens for {model}")
    except Exception as e:
        log.warning(f"Failed to record embedding usage: {e}")


# =============================================================================
# 설정 헬퍼 함수
# =============================================================================


def _get_value(val):
    """
    PersistentConfig 또는 일반 값에서 실제 값을 추출.
    PersistentConfig는 .value 속성에 실제 값이 있음.
    """
    if val is None:
        return None

    # PersistentConfig 객체인 경우 .value 속성 직접 접근
    if hasattr(val, "value"):
        return val.value

    return val


def get_embedding_config_from_app(app) -> EmbeddingConfig:
    """
    FastAPI app.state.config에서 임베딩 설정 추출.

    관리자페이지 > 설정 > 문서 > 임베딩 설정을 사용합니다.
    """
    config = app.state.config

    # 엔진 타입 (azure_openai, openai, ollama 등)
    engine = _get_value(getattr(config, "RAG_EMBEDDING_ENGINE", None)) or ""
    if not engine:
        raise RuntimeError(
            "RAG_EMBEDDING_ENGINE is not configured. "
            "Set it in admin settings → Documents → Embedding engine."
        )

    # 모델명
    model = _get_value(getattr(config, "RAG_EMBEDDING_MODEL", None))
    if not model:
        raise RuntimeError(
            "RAG_EMBEDDING_MODEL is not configured. "
            "Set it in admin settings → Documents → Embedding model."
        )

    # 배치 사이즈
    batch_size = _get_value(getattr(config, "RAG_EMBEDDING_BATCH_SIZE", None)) or 100

    # 임베딩 차원 (관리자 설정 우선, 없으면 모델 기본값)
    raw_dim = _get_value(getattr(config, "RAG_EMBEDDING_DIMENSIONS", None))
    dimensions = int(raw_dim) if raw_dim else 0

    log.info(f"[get_embedding_config_from_app] engine={engine}")

    # 엔진 타입에 따른 URL과 API Key 선택
    if engine == "azure_openai":
        url = _get_value(getattr(config, "RAG_AZURE_OPENAI_API_BASE_URL", None)) or ""
        api_key = _get_value(getattr(config, "RAG_AZURE_OPENAI_API_KEY", None)) or ""
        api_version = (
            _get_value(getattr(config, "RAG_AZURE_OPENAI_API_VERSION", None))
            or "2024-02-15-preview"
        )
        log.info("[get_embedding_config_from_app] Using Azure OpenAI config")

    elif engine == "openai":
        url = _get_value(getattr(config, "RAG_OPENAI_API_BASE_URL", None)) or ""
        api_key = _get_value(getattr(config, "RAG_OPENAI_API_KEY", None)) or ""
        api_version = None
        log.info("[get_embedding_config_from_app] Using OpenAI config")

    elif engine == "ollama":
        url = _get_value(getattr(config, "RAG_OLLAMA_BASE_URL", None)) or ""
        if not url:
            raise RuntimeError(
                "RAG_OLLAMA_BASE_URL is not configured. "
                "Set it in admin settings → Documents → Ollama base URL."
            )
        api_key = _get_value(getattr(config, "RAG_OLLAMA_API_KEY", None)) or ""
        api_version = None
        log.info("[get_embedding_config_from_app] Using Ollama config")

    elif engine == "gemini":
        url = ""
        api_key = _get_value(getattr(config, "RAG_GEMINI_API_KEY", None)) or ""
        api_version = None
        log.info("[get_embedding_config_from_app] Using Gemini config")

        log.info(
            f"[get_embedding_config_from_app] Result: model={model}, "
            f"api_key={'SET(' + str(len(api_key)) + ' chars)' if api_key else 'EMPTY'}"
        )
        return EmbeddingConfig(
            engine=engine,
            model=model,
            url=url,
            api_key=api_key,
            api_version=api_version,
            batch_size=batch_size,
            dimensions=dimensions or None,
        )

    elif engine == "vertex_ai":
        url = ""
        api_key = ""
        api_version = None
        vertex_ai_project_id = (
            _get_value(getattr(config, "RAG_VERTEX_AI_PROJECT_ID", None)) or ""
        )
        if not vertex_ai_project_id:
            raise RuntimeError(
                "RAG_VERTEX_AI_PROJECT_ID is not configured. "
                "Set it in admin settings → Documents → Vertex AI project."
            )
        vertex_ai_location = (
            _get_value(getattr(config, "RAG_VERTEX_AI_LOCATION", None)) or ""
        )
        if not vertex_ai_location:
            raise RuntimeError(
                "RAG_VERTEX_AI_LOCATION is not configured. "
                "Set it in admin settings → Documents → Vertex AI location."
            )
        vertex_ai_service_account_key = (
            _get_value(getattr(config, "RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY", None))
            or getattr(config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", "")
            or ""
        )
        log.info("[get_embedding_config_from_app] Using Vertex AI config")

        log.info(
            f"[get_embedding_config_from_app] Result: model={model}, "
            f"project_id={vertex_ai_project_id}, location={vertex_ai_location}"
        )
        return EmbeddingConfig(
            engine=engine,
            model=model,
            url=url,
            api_key=api_key,
            api_version=api_version,
            batch_size=batch_size,
            vertex_ai_project_id=vertex_ai_project_id,
            vertex_ai_location=vertex_ai_location,
            vertex_ai_service_account_key=vertex_ai_service_account_key or None,
            dimensions=dimensions or None,
        )

    else:
        # 기타 엔진 (fallback to openai config)
        url = _get_value(getattr(config, "RAG_OPENAI_API_BASE_URL", None)) or ""
        api_key = _get_value(getattr(config, "RAG_OPENAI_API_KEY", None)) or ""
        api_version = None
        log.info(
            f"[get_embedding_config_from_app] Using fallback OpenAI config for engine={engine}"
        )

    log.info(
        f"[get_embedding_config_from_app] Result: model={model}, "
        f"url={url[:50] + '...' if url and len(url) > 50 else url}, "
        f"api_key={'SET(' + str(len(api_key)) + ' chars)' if api_key else 'EMPTY'}"
    )

    return EmbeddingConfig(
        engine=engine,
        model=model,
        url=url,
        api_key=api_key,
        api_version=api_version,
        batch_size=batch_size,
        dimensions=dimensions or None,
    )


def create_embedding_config(
    engine: str = "azure_openai",
    model: str = "text-embedding-3-large",
    url: str = "",
    api_key: str = "",
    api_version: Optional[str] = None,
    batch_size: int = 100,
) -> EmbeddingConfig:
    """임베딩 설정 생성 헬퍼"""
    return EmbeddingConfig(
        engine=engine,
        model=model,
        url=url,
        api_key=api_key,
        api_version=api_version,
        batch_size=batch_size,
    )
