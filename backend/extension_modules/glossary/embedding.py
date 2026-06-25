"""
Glossary - 임베딩 헬퍼

관리자 > 설정 > 문서의 RAG 임베딩 설정을 사용하여 임베딩을 생성합니다.
"""

import logging
from typing import TYPE_CHECKING, Optional, Union

from fastapi import FastAPI
from open_webui.env import SRC_LOG_LEVELS

if TYPE_CHECKING:
    from open_webui.utils.tracing import TraceContext

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def get_embedding_config(app: FastAPI) -> dict:
    """
    앱 설정에서 임베딩 설정 추출.

    Args:
        app: FastAPI 앱 인스턴스

    Returns:
        dict: 임베딩 설정 (engine, model, url, key, azure_api_version)
    """
    config = app.state.config

    engine = getattr(config, "RAG_EMBEDDING_ENGINE", "")
    model = getattr(config, "RAG_EMBEDDING_MODEL", "")

    # 엔진별 URL/Key 설정
    if engine == "azure_openai":
        url = getattr(config, "RAG_AZURE_OPENAI_API_BASE_URL", "")
        key = getattr(config, "RAG_AZURE_OPENAI_API_KEY", "")
        azure_api_version = getattr(config, "RAG_AZURE_OPENAI_API_VERSION", None)
    elif engine == "openai":
        url = getattr(config, "RAG_OPENAI_API_BASE_URL", "")
        key = getattr(config, "RAG_OPENAI_API_KEY", "")
        azure_api_version = None
    elif engine == "ollama":
        url = getattr(config, "RAG_OLLAMA_BASE_URL", "")
        key = getattr(config, "RAG_OLLAMA_API_KEY", "")
        azure_api_version = None
    else:
        url = ""
        key = ""
        azure_api_version = None

    return {
        "engine": engine,
        "model": model,
        "url": url,
        "key": key,
        "azure_api_version": azure_api_version,
    }


def generate_embedding(
    app: FastAPI,
    text: Union[str, list[str]],
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    trace_context: Optional["TraceContext"] = None,
) -> Union[list[float], list[list[float]]]:
    """
    텍스트 임베딩 생성.

    관리자 > 설정 > 문서의 RAG 임베딩 설정을 사용합니다.

    Args:
        app: FastAPI 앱 인스턴스
        text: 임베딩할 텍스트 (단일 또는 리스트)
        user_id: 사용량 추적용 사용자 ID (선택)
        chat_id: 사용량 추적용 채팅 ID (선택)
        trace_context: 트레이싱 컨텍스트 (선택)

    Returns:
        list[float] | list[list[float]]: 임베딩 벡터 (단일 또는 리스트)

    Raises:
        ValueError: 임베딩 설정이 없는 경우
        RuntimeError: 임베딩 생성 실패 시
    """
    from open_webui.retrieval.utils import generate_embeddings

    embedding_config = get_embedding_config(app)

    if not embedding_config["engine"] or not embedding_config["model"]:
        raise ValueError(
            "Embedding not configured. Please configure RAG embedding in Admin > Settings > Documents."
        )

    log.debug(
        f"Generating embedding with engine={embedding_config['engine']}, model={embedding_config['model']}"
    )

    # Setup tracing context manager if available
    ctx_manager = None
    if trace_context and trace_context.enabled:
        from open_webui.models.message_trace import RunType

        text_count = len(text) if isinstance(text, list) else 1
        ctx_manager = trace_context.start_run(
            run_type=RunType.EMBEDDING.value,
            name="glossary_embedding",
            inputs={"text_count": text_count},
            model_id=embedding_config["model"],
            push_stack=False,  # leaf 노드 — 동시 실행 시 _run_stack 오염 방지
        )

    try:
        if ctx_manager:
            with ctx_manager as run:
                embeddings = generate_embeddings(
                    engine=embedding_config["engine"],
                    model=embedding_config["model"],
                    text=text,
                    url=embedding_config["url"],
                    key=embedding_config["key"],
                    azure_api_version=embedding_config["azure_api_version"],
                )

                # Record usage
                _record_glossary_embedding_usage(
                    user_id=user_id,
                    chat_id=chat_id,
                    model=embedding_config["model"],
                    text=text,
                )

                # Set tracing outputs
                if run:
                    embedding_count = (
                        len(embeddings) if isinstance(embeddings[0], list) else 1
                    )
                    run.set_outputs({"embedding_count": embedding_count})

                return embeddings
        else:
            embeddings = generate_embeddings(
                engine=embedding_config["engine"],
                model=embedding_config["model"],
                text=text,
                url=embedding_config["url"],
                key=embedding_config["key"],
                azure_api_version=embedding_config["azure_api_version"],
            )

            # Record usage even without tracing
            _record_glossary_embedding_usage(
                user_id=user_id,
                chat_id=chat_id,
                model=embedding_config["model"],
                text=text,
            )

            return embeddings

    except Exception as e:
        log.error(f"Failed to generate embedding: {e}")
        raise RuntimeError(f"Failed to generate embedding: {e}") from e


def _record_glossary_embedding_usage(
    user_id: Optional[str],
    chat_id: Optional[str],
    model: str,
    text: Union[str, list[str]],
) -> None:
    """Record glossary embedding usage to database."""
    if not user_id or not chat_id:
        return

    try:
        from open_webui.models.usage import UsageMessageType, Usages

        # Estimate token count (rough approximation: 1 token ≈ 4 chars)
        if isinstance(text, list):
            total_chars = sum(len(t) for t in text)
        else:
            total_chars = len(text)
        estimated_tokens = total_chars // 4

        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=chat_id,
            agent_id=None,
            model_id=model,
            message_id=f"glossary_embedding:{chat_id}",
            message_type=UsageMessageType.EMBEDDING,
            total_tokens=estimated_tokens,
            usage={
                "prompt_tokens": estimated_tokens,
                "total_tokens": estimated_tokens,
                "source": "glossary",
            },
        )
        log.debug(
            f"Glossary embedding usage recorded: ~{estimated_tokens} tokens for model {model}"
        )
    except Exception as e:
        log.warning(f"Failed to record glossary embedding usage: {e}")


def get_vector_dimension(app: FastAPI) -> int:
    """
    현재 설정된 임베딩 모델의 벡터 차원 반환.

    Args:
        app: FastAPI 앱 인스턴스

    Returns:
        int: 벡터 차원 (기본값: 3072)
    """
    config = app.state.config
    model = getattr(config, "RAG_EMBEDDING_MODEL", "")

    # 일반적인 모델별 차원
    dimension_map = {
        # OpenAI
        "text-embedding-3-large": 3072,
        "text-embedding-3-small": 1536,
        "text-embedding-ada-002": 1536,
        # Azure OpenAI (deployment name이 모델명과 다를 수 있음)
        # Ollama
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
    }

    # 정확히 일치하는 모델명이 있으면 사용
    if model in dimension_map:
        return dimension_map[model]

    # 부분 일치 검사 (Azure deployment name 등)
    model_lower = model.lower()
    if "3-large" in model_lower or "embedding-3-large" in model_lower:
        return 3072
    if "3-small" in model_lower or "embedding-3-small" in model_lower:
        return 1536
    if "ada" in model_lower:
        return 1536

    # 기본값 (text-embedding-3-large 기준)
    return 3072
