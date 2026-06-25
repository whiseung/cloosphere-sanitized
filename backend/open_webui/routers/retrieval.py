import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

import tiktoken
from extension_modules.search_engine.embedding import get_effective_embedding_dimension
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)
from open_webui.config import (
    DEFAULT_LOCALE,
    ENV,
    RAG_EMBEDDING_CONTENT_PREFIX,
    RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
    RAG_EMBEDDING_QUERY_PREFIX,
    UPLOAD_DIR,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    DEVICE_TYPE,
    SRC_LOG_LEVELS,
)
from open_webui.models.files import FileModel, Files
from open_webui.models.knowledge import Knowledges
from open_webui.retrieval.knowledge_service import (
    SearchEngineKnowledge,
    check_duplicate_hash,
    query_by_metadata_sync,
    reset_knowledge_index,
)

# Document loaders
from open_webui.retrieval.loaders.main import Loader
from open_webui.retrieval.loaders.youtube import YoutubeLoader
from open_webui.retrieval.question_generator import generate_chunk_questions
from open_webui.retrieval.utils import (
    get_embedding_function,
    get_model_path,
    query_collection,
    query_doc,
)
from open_webui.retrieval.web.bing import search_bing
from open_webui.retrieval.web.bocha import search_bocha
from open_webui.retrieval.web.brave import search_brave

# from open_webui.retrieval.web.duckduckgo import search_duckduckgo
from open_webui.retrieval.web.exa import search_exa
from open_webui.retrieval.web.google_pse import search_google_pse
from open_webui.retrieval.web.jina_search import search_jina
from open_webui.retrieval.web.kagi import search_kagi

# Web search engines
from open_webui.retrieval.web.main import SearchResult
from open_webui.retrieval.web.mojeek import search_mojeek
from open_webui.retrieval.web.perplexity import search_perplexity
from open_webui.retrieval.web.searchapi import search_searchapi
from open_webui.retrieval.web.searxng import search_searxng
from open_webui.retrieval.web.serpapi import search_serpapi
from open_webui.retrieval.web.serper import search_serper
from open_webui.retrieval.web.serply import search_serply
from open_webui.retrieval.web.serpstack import search_serpstack
from open_webui.retrieval.web.sougou import search_sougou
from open_webui.retrieval.web.tavily import search_tavily
from open_webui.retrieval.web.utils import get_web_loader
from open_webui.services.task_queue import InProcessQueue
from open_webui.storage.provider import Storage
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.crypto import mask_config_dict, resolve_sensitive_value
from open_webui.utils.file_guardrails import run_classification, run_text_guardrails
from open_webui.utils.license import is_feature_enabled
from open_webui.utils.misc import (
    calculate_sha256_string,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

##########################################
#
# Utility functions
#
##########################################


def get_ef(
    engine: str,
    embedding_model: str,
    auto_update: bool = False,
):
    ef = None
    if embedding_model and engine == "":
        from sentence_transformers import SentenceTransformer

        try:
            ef = SentenceTransformer(
                get_model_path(embedding_model, auto_update),
                device=DEVICE_TYPE,
                trust_remote_code=RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
            )
        except Exception as e:
            log.debug(f"Error loading SentenceTransformer: {e}")

    return ef


##########################################
#
# API routes
#
##########################################


router = APIRouter()

# Keep references to background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task] = set()

# Thread pool for background file processing
_file_processing_executor = ThreadPoolExecutor(
    max_workers=int(os.environ.get("FILE_PROCESSING_WORKERS", "4")),
    thread_name_prefix="file_processor",
)


class CollectionNameForm(BaseModel):
    collection_name: Optional[str] = None


class ProcessUrlForm(CollectionNameForm):
    url: str


class SearchForm(BaseModel):
    query: str


@router.get("/")
async def get_status(request: Request):
    return {
        "status": True,
        "chunk_size": request.app.state.config.CHUNK_SIZE,
        "chunk_overlap": request.app.state.config.CHUNK_OVERLAP,
        "template": request.app.state.config.RAG_TEMPLATE,
        "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
        "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
        "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
    }


@router.get("/embedding")
async def get_embedding_config(request: Request, user=Depends(get_admin_user)):
    return mask_config_dict(
        {
            "status": True,
            "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
            "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
            "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            "embedding_dimensions": getattr(
                request.app.state.config, "RAG_EMBEDDING_DIMENSIONS", 0
            )
            or 0,
            "openai_config": {
                "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
                "key": request.app.state.config.RAG_OPENAI_API_KEY,
            },
            "ollama_config": {
                "url": request.app.state.config.RAG_OLLAMA_BASE_URL,
                "key": request.app.state.config.RAG_OLLAMA_API_KEY,
            },
            "azure_openai_config": {
                "url": request.app.state.config.RAG_AZURE_OPENAI_API_BASE_URL,
                "key": request.app.state.config.RAG_AZURE_OPENAI_API_KEY,
                "version": request.app.state.config.RAG_AZURE_OPENAI_API_VERSION,
            },
            "gemini_config": {
                "key": request.app.state.config.RAG_GEMINI_API_KEY,
            },
            "vertex_ai_config": {
                "project_id": request.app.state.config.RAG_VERTEX_AI_PROJECT_ID,
                "location": request.app.state.config.RAG_VERTEX_AI_LOCATION,
                "service_account_key": request.app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY,
            },
        }
    )


class OpenAIConfigForm(BaseModel):
    url: str
    key: str


class OllamaConfigForm(BaseModel):
    url: str
    key: str


class AzureOpenAIConfigForm(BaseModel):
    url: str
    key: str
    version: str


class GeminiConfigForm(BaseModel):
    key: str


class VertexAIConfigForm(BaseModel):
    project_id: str
    location: str
    service_account_key: str


class EmbeddingModelUpdateForm(BaseModel):
    openai_config: Optional[OpenAIConfigForm] = None
    ollama_config: Optional[OllamaConfigForm] = None
    azure_openai_config: Optional[AzureOpenAIConfigForm] = None
    gemini_config: Optional[GeminiConfigForm] = None
    vertex_ai_config: Optional[VertexAIConfigForm] = None
    embedding_engine: str
    embedding_model: str
    embedding_batch_size: Optional[int] = 1
    embedding_dimensions: Optional[int] = 0


@router.post("/embedding/update")
async def update_embedding_config(
    request: Request, form_data: EmbeddingModelUpdateForm, user=Depends(get_admin_user)
):
    log.info(
        f"Updating embedding model: {request.app.state.config.RAG_EMBEDDING_MODEL} to {form_data.embedding_model}"
    )
    try:
        request.app.state.config.RAG_EMBEDDING_ENGINE = form_data.embedding_engine
        request.app.state.config.RAG_EMBEDDING_MODEL = form_data.embedding_model

        if request.app.state.config.RAG_EMBEDDING_ENGINE in [
            "ollama",
            "openai",
            "azure_openai",
            "gemini",
            "vertex_ai",
        ]:
            if form_data.openai_config is not None:
                request.app.state.config.RAG_OPENAI_API_BASE_URL = (
                    form_data.openai_config.url
                )
                request.app.state.config.RAG_OPENAI_API_KEY = resolve_sensitive_value(
                    form_data.openai_config.key,
                    request.app.state.config.RAG_OPENAI_API_KEY,
                )

            if form_data.ollama_config is not None:
                request.app.state.config.RAG_OLLAMA_BASE_URL = (
                    form_data.ollama_config.url
                )
                request.app.state.config.RAG_OLLAMA_API_KEY = resolve_sensitive_value(
                    form_data.ollama_config.key,
                    request.app.state.config.RAG_OLLAMA_API_KEY,
                )

            if form_data.azure_openai_config is not None:
                request.app.state.config.RAG_AZURE_OPENAI_API_BASE_URL = (
                    form_data.azure_openai_config.url
                )
                request.app.state.config.RAG_AZURE_OPENAI_API_KEY = (
                    resolve_sensitive_value(
                        form_data.azure_openai_config.key,
                        request.app.state.config.RAG_AZURE_OPENAI_API_KEY,
                    )
                )
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION = (
                    form_data.azure_openai_config.version
                )

            if form_data.gemini_config is not None:
                request.app.state.config.RAG_GEMINI_API_KEY = resolve_sensitive_value(
                    form_data.gemini_config.key,
                    request.app.state.config.RAG_GEMINI_API_KEY,
                )

            if form_data.vertex_ai_config is not None:
                request.app.state.config.RAG_VERTEX_AI_PROJECT_ID = (
                    form_data.vertex_ai_config.project_id
                )
                request.app.state.config.RAG_VERTEX_AI_LOCATION = (
                    form_data.vertex_ai_config.location
                )
                request.app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY = (
                    resolve_sensitive_value(
                        form_data.vertex_ai_config.service_account_key,
                        request.app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY,
                    )
                )

            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE = (
                form_data.embedding_batch_size
            )
            request.app.state.config.RAG_EMBEDDING_DIMENSIONS = (
                form_data.embedding_dimensions or 0
            )

        request.app.state.ef = get_ef(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
        )

        request.app.state.EMBEDDING_FUNCTION = get_embedding_function(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
            request.app.state.ef,
            (
                request.app.state.config.RAG_AZURE_OPENAI_API_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
                else (
                    request.app.state.config.RAG_OPENAI_API_BASE_URL
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                    else (
                        ""
                        if request.app.state.config.RAG_EMBEDDING_ENGINE
                        in ["gemini", "vertex_ai"]
                        else request.app.state.config.RAG_OLLAMA_BASE_URL
                    )
                )
            ),
            (
                request.app.state.config.RAG_AZURE_OPENAI_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
                else (
                    request.app.state.config.RAG_OPENAI_API_KEY
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                    else (
                        request.app.state.config.RAG_GEMINI_API_KEY
                        if request.app.state.config.RAG_EMBEDDING_ENGINE == "gemini"
                        else (
                            ""
                            if request.app.state.config.RAG_EMBEDDING_ENGINE
                            == "vertex_ai"
                            else request.app.state.config.RAG_OLLAMA_API_KEY
                        )
                    )
                )
            ),
            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            azure_api_version=(
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
                else None
            ),
            vertex_ai_project_id=(
                request.app.state.config.RAG_VERTEX_AI_PROJECT_ID
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
                else None
            ),
            vertex_ai_location=(
                request.app.state.config.RAG_VERTEX_AI_LOCATION
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
                else None
            ),
            vertex_ai_service_account_key=(
                request.app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
                else None
            ),
            google_cloud_service_account_key=(
                request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
                else None
            ),
        )

        AuditLogger.log_settings_change(
            "documents/embedding", after_data=form_data.model_dump()
        )
        return mask_config_dict(
            {
                "status": True,
                "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
                "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
                "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
                "openai_config": {
                    "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
                    "key": request.app.state.config.RAG_OPENAI_API_KEY,
                },
                "ollama_config": {
                    "url": request.app.state.config.RAG_OLLAMA_BASE_URL,
                    "key": request.app.state.config.RAG_OLLAMA_API_KEY,
                },
                "azure_openai_config": {
                    "url": getattr(
                        request.app.state.config, "RAG_AZURE_OPENAI_API_BASE_URL", ""
                    ),
                    "key": getattr(
                        request.app.state.config, "RAG_AZURE_OPENAI_API_KEY", ""
                    ),
                    "version": getattr(
                        request.app.state.config, "RAG_AZURE_OPENAI_API_VERSION", ""
                    ),
                },
                "gemini_config": {
                    "key": request.app.state.config.RAG_GEMINI_API_KEY,
                },
                "vertex_ai_config": {
                    "project_id": request.app.state.config.RAG_VERTEX_AI_PROJECT_ID,
                    "location": request.app.state.config.RAG_VERTEX_AI_LOCATION,
                    "service_account_key": request.app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY,
                },
            }
        )
    except Exception as e:
        log.exception(f"Problem updating embedding model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


@router.get("/config")
async def get_rag_config(request: Request, user=Depends(get_admin_user)):
    return mask_config_dict(
        {
            "status": True,
            # RAG settings
            "RAG_TEMPLATE": request.app.state.config.RAG_TEMPLATE,
            "BYPASS_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL,
            # Content extraction settings
            "CONTENT_EXTRACTION_ENGINE": request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            "PDF_EXTRACT_IMAGES": request.app.state.config.PDF_EXTRACT_IMAGES,
            "TIKA_SERVER_URL": request.app.state.config.TIKA_SERVER_URL,
            "DOCLING_SERVER_URL": request.app.state.config.DOCLING_SERVER_URL,
            "DOCUMENT_INTELLIGENCE_ENDPOINT": request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
            "DOCUMENT_INTELLIGENCE_KEY": request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
            "MISTRAL_OCR_API_KEY": request.app.state.config.MISTRAL_OCR_API_KEY,
            "DOCUMENT_AI_PROJECT_ID": request.app.state.config.DOCUMENT_AI_PROJECT_ID,
            "DOCUMENT_AI_LOCATION": request.app.state.config.DOCUMENT_AI_LOCATION,
            "DOCUMENT_AI_PROCESSOR_ID": request.app.state.config.DOCUMENT_AI_PROCESSOR_ID,
            "DOCUMENT_AI_PROCESSOR_VERSION": request.app.state.config.DOCUMENT_AI_PROCESSOR_VERSION,
            "DOCUMENT_AI_SERVICE_ACCOUNT_KEY": request.app.state.config.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
            # Chunking settings
            "TEXT_SPLITTER": request.app.state.config.TEXT_SPLITTER,
            "CHUNK_SIZE": request.app.state.config.CHUNK_SIZE,
            "CHUNK_OVERLAP": request.app.state.config.CHUNK_OVERLAP,
            # File upload settings
            "FILE_MAX_SIZE": request.app.state.config.FILE_MAX_SIZE,
            "FILE_MAX_COUNT": request.app.state.config.FILE_MAX_COUNT,
            "PDF_CONVERT_EXTENSIONS": request.app.state.config.PDF_CONVERT_EXTENSIONS,
            "ALLOWED_FILE_EXTENSIONS": request.app.state.config.ALLOWED_FILE_EXTENSIONS,
            # KB Question Generation settings
            "kb_question_generation": {
                "KB_QUESTION_GENERATION_ENABLED": getattr(
                    request.app.state.config, "KB_QUESTION_GENERATION_ENABLED", False
                ),
                "KB_QUESTION_GENERATION_MODEL": getattr(
                    request.app.state.config, "KB_QUESTION_GENERATION_MODEL", ""
                ),
                "KB_MAX_QUESTIONS_PER_CHUNK": getattr(
                    request.app.state.config, "KB_MAX_QUESTIONS_PER_CHUNK", 10
                ),
                "KB_QUESTION_VECTOR_WEIGHT": getattr(
                    request.app.state.config, "KB_QUESTION_VECTOR_WEIGHT", 0.5
                ),
            },
            # Global Guardrails
            "global_guardrail": {
                "ENABLE_GLOBAL_GUARDRAIL": getattr(
                    request.app.state.config, "ENABLE_GLOBAL_GUARDRAIL", False
                ),
                "GLOBAL_GUARDRAIL_IDS": getattr(
                    request.app.state.config, "GLOBAL_GUARDRAIL_IDS", []
                ),
            },
            # File Upload Guardrails
            "file_guardrail": {
                "FILE_GUARDRAIL_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_ENABLED", False
                ),
                "FILE_GUARDRAIL_SCOPES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_SCOPES",
                    ["chat", "knowledge", "project"],
                ),
                "FILE_GUARDRAIL_IDS": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_IDS", []
                ),
                "FILE_GUARDRAIL_EXIF_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_EXIF_ENABLED", False
                ),
                "FILE_GUARDRAIL_MACRO_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_MACRO_ENABLED", False
                ),
                "FILE_GUARDRAIL_MACRO_ACTION": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_MACRO_ACTION", "block"
                ),
                "FILE_GUARDRAIL_NSFW_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_ENABLED", False
                ),
                "FILE_GUARDRAIL_NSFW_MODEL": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_MODEL", ""
                ),
                "FILE_GUARDRAIL_NSFW_PROMPT": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_PROMPT", ""
                ),
                "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES", []
                ),
                "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES", []
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_ENABLED": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_ENABLED",
                    False,
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_MODEL": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_MODEL", ""
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_PROMPT": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_PROMPT", ""
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES",
                    [],
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES",
                    [],
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS",
                    8000,
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES",
                    [],
                ),
            },
            # Integration settings
            "ENABLE_GOOGLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
            "ENABLE_ONEDRIVE_INTEGRATION": request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
            "ENABLE_SHAREPOINT_INTEGRATION": request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION,
            # Web search settings
            "web": {
                "ENABLE_WEB_SEARCH": request.app.state.config.ENABLE_WEB_SEARCH,
                "WEB_SEARCH_ENGINE": request.app.state.config.WEB_SEARCH_ENGINE,
                "WEB_SEARCH_TRUST_ENV": request.app.state.config.WEB_SEARCH_TRUST_ENV,
                "WEB_SEARCH_RESULT_COUNT": request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                "WEB_SEARCH_CONCURRENT_REQUESTS": request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
                "WEB_SEARCH_DOMAIN_FILTER_LIST": request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
                "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL,
                "SEARXNG_QUERY_URL": request.app.state.config.SEARXNG_QUERY_URL,
                "GOOGLE_PSE_API_KEY": request.app.state.config.GOOGLE_PSE_API_KEY,
                "GOOGLE_PSE_ENGINE_ID": request.app.state.config.GOOGLE_PSE_ENGINE_ID,
                "BRAVE_SEARCH_API_KEY": request.app.state.config.BRAVE_SEARCH_API_KEY,
                "KAGI_SEARCH_API_KEY": request.app.state.config.KAGI_SEARCH_API_KEY,
                "MOJEEK_SEARCH_API_KEY": request.app.state.config.MOJEEK_SEARCH_API_KEY,
                "BOCHA_SEARCH_API_KEY": request.app.state.config.BOCHA_SEARCH_API_KEY,
                "SERPSTACK_API_KEY": request.app.state.config.SERPSTACK_API_KEY,
                "SERPSTACK_HTTPS": request.app.state.config.SERPSTACK_HTTPS,
                "SERPER_API_KEY": request.app.state.config.SERPER_API_KEY,
                "SERPLY_API_KEY": request.app.state.config.SERPLY_API_KEY,
                "TAVILY_API_KEY": request.app.state.config.TAVILY_API_KEY,
                "SEARCHAPI_API_KEY": request.app.state.config.SEARCHAPI_API_KEY,
                "SEARCHAPI_ENGINE": request.app.state.config.SEARCHAPI_ENGINE,
                "SERPAPI_API_KEY": request.app.state.config.SERPAPI_API_KEY,
                "SERPAPI_ENGINE": request.app.state.config.SERPAPI_ENGINE,
                "JINA_API_KEY": request.app.state.config.JINA_API_KEY,
                "BING_SEARCH_V7_ENDPOINT": request.app.state.config.BING_SEARCH_V7_ENDPOINT,
                "BING_SEARCH_V7_SUBSCRIPTION_KEY": request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
                "EXA_API_KEY": request.app.state.config.EXA_API_KEY,
                "PERPLEXITY_API_KEY": request.app.state.config.PERPLEXITY_API_KEY,
                "SOUGOU_API_SID": request.app.state.config.SOUGOU_API_SID,
                "SOUGOU_API_SK": request.app.state.config.SOUGOU_API_SK,
                "WEB_LOADER_ENGINE": request.app.state.config.WEB_LOADER_ENGINE,
                "ENABLE_WEB_LOADER_SSL_VERIFICATION": request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
                "PLAYWRIGHT_WS_URL": request.app.state.config.PLAYWRIGHT_WS_URL,
                "PLAYWRIGHT_TIMEOUT": request.app.state.config.PLAYWRIGHT_TIMEOUT,
                "FIRECRAWL_API_KEY": request.app.state.config.FIRECRAWL_API_KEY,
                "FIRECRAWL_API_BASE_URL": request.app.state.config.FIRECRAWL_API_BASE_URL,
                "TAVILY_EXTRACT_DEPTH": request.app.state.config.TAVILY_EXTRACT_DEPTH,
                "YOUTUBE_LOADER_LANGUAGE": request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
                "YOUTUBE_LOADER_PROXY_URL": request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
                "YOUTUBE_LOADER_TRANSLATION": request.app.state.YOUTUBE_LOADER_TRANSLATION,
            },
        }
    )


class WebConfig(BaseModel):
    ENABLE_WEB_SEARCH: Optional[bool] = None
    WEB_SEARCH_ENGINE: Optional[str] = None
    WEB_SEARCH_TRUST_ENV: Optional[bool] = None
    WEB_SEARCH_RESULT_COUNT: Optional[int] = None
    WEB_SEARCH_CONCURRENT_REQUESTS: Optional[int] = None
    WEB_SEARCH_DOMAIN_FILTER_LIST: Optional[List[str]] = []
    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL: Optional[bool] = None
    SEARXNG_QUERY_URL: Optional[str] = None
    GOOGLE_PSE_API_KEY: Optional[str] = None
    GOOGLE_PSE_ENGINE_ID: Optional[str] = None
    BRAVE_SEARCH_API_KEY: Optional[str] = None
    KAGI_SEARCH_API_KEY: Optional[str] = None
    MOJEEK_SEARCH_API_KEY: Optional[str] = None
    BOCHA_SEARCH_API_KEY: Optional[str] = None
    SERPSTACK_API_KEY: Optional[str] = None
    SERPSTACK_HTTPS: Optional[bool] = None
    SERPER_API_KEY: Optional[str] = None
    SERPLY_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None
    SEARCHAPI_API_KEY: Optional[str] = None
    SEARCHAPI_ENGINE: Optional[str] = None
    SERPAPI_API_KEY: Optional[str] = None
    SERPAPI_ENGINE: Optional[str] = None
    JINA_API_KEY: Optional[str] = None
    BING_SEARCH_V7_ENDPOINT: Optional[str] = None
    BING_SEARCH_V7_SUBSCRIPTION_KEY: Optional[str] = None
    EXA_API_KEY: Optional[str] = None
    PERPLEXITY_API_KEY: Optional[str] = None
    SOUGOU_API_SID: Optional[str] = None
    SOUGOU_API_SK: Optional[str] = None
    WEB_LOADER_ENGINE: Optional[str] = None
    ENABLE_WEB_LOADER_SSL_VERIFICATION: Optional[bool] = None
    PLAYWRIGHT_WS_URL: Optional[str] = None
    PLAYWRIGHT_TIMEOUT: Optional[int] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    FIRECRAWL_API_BASE_URL: Optional[str] = None
    TAVILY_EXTRACT_DEPTH: Optional[str] = None
    YOUTUBE_LOADER_LANGUAGE: Optional[List[str]] = None
    YOUTUBE_LOADER_PROXY_URL: Optional[str] = None
    YOUTUBE_LOADER_TRANSLATION: Optional[str] = None


class ConfigForm(BaseModel):
    # RAG settings
    RAG_TEMPLATE: Optional[str] = None
    BYPASS_EMBEDDING_AND_RETRIEVAL: Optional[bool] = None

    # Content extraction settings
    CONTENT_EXTRACTION_ENGINE: Optional[str] = None
    PDF_EXTRACT_IMAGES: Optional[bool] = None
    TIKA_SERVER_URL: Optional[str] = None
    DOCLING_SERVER_URL: Optional[str] = None
    DOCUMENT_INTELLIGENCE_ENDPOINT: Optional[str] = None
    DOCUMENT_INTELLIGENCE_KEY: Optional[str] = None
    MISTRAL_OCR_API_KEY: Optional[str] = None
    DOCUMENT_AI_PROJECT_ID: Optional[str] = None
    DOCUMENT_AI_LOCATION: Optional[str] = None
    DOCUMENT_AI_PROCESSOR_ID: Optional[str] = None
    DOCUMENT_AI_PROCESSOR_VERSION: Optional[str] = None
    DOCUMENT_AI_SERVICE_ACCOUNT_KEY: Optional[str] = None

    # Chunking settings
    TEXT_SPLITTER: Optional[str] = None
    CHUNK_SIZE: Optional[int] = None
    CHUNK_OVERLAP: Optional[int] = None

    # File upload settings
    FILE_MAX_SIZE: Optional[int] = None
    FILE_MAX_COUNT: Optional[int] = None
    PDF_CONVERT_EXTENSIONS: Optional[list[str]] = None
    ALLOWED_FILE_EXTENSIONS: Optional[list[str]] = None

    # Integration settings
    ENABLE_GOOGLE_DRIVE_INTEGRATION: Optional[bool] = None
    ENABLE_ONEDRIVE_INTEGRATION: Optional[bool] = None
    ENABLE_SHAREPOINT_INTEGRATION: Optional[bool] = None

    # Global Guardrails
    global_guardrail: Optional[dict] = None

    # File Upload Guardrails
    file_guardrail: Optional[dict] = None

    # KB Question Generation settings
    kb_question_generation: Optional[dict] = None

    # Web search settings
    web: Optional[WebConfig] = None


@router.post("/config/update")
async def update_rag_config(
    request: Request, form_data: ConfigForm, user=Depends(get_admin_user)
):
    # RAG settings
    request.app.state.config.RAG_TEMPLATE = (
        form_data.RAG_TEMPLATE
        if form_data.RAG_TEMPLATE is not None
        else request.app.state.config.RAG_TEMPLATE
    )
    request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL = (
        form_data.BYPASS_EMBEDDING_AND_RETRIEVAL
        if form_data.BYPASS_EMBEDDING_AND_RETRIEVAL is not None
        else request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
    )

    # Content extraction settings
    request.app.state.config.CONTENT_EXTRACTION_ENGINE = (
        form_data.CONTENT_EXTRACTION_ENGINE
        if form_data.CONTENT_EXTRACTION_ENGINE is not None
        else request.app.state.config.CONTENT_EXTRACTION_ENGINE
    )
    request.app.state.config.PDF_EXTRACT_IMAGES = (
        form_data.PDF_EXTRACT_IMAGES
        if form_data.PDF_EXTRACT_IMAGES is not None
        else request.app.state.config.PDF_EXTRACT_IMAGES
    )
    request.app.state.config.TIKA_SERVER_URL = (
        form_data.TIKA_SERVER_URL
        if form_data.TIKA_SERVER_URL is not None
        else request.app.state.config.TIKA_SERVER_URL
    )
    request.app.state.config.DOCLING_SERVER_URL = (
        form_data.DOCLING_SERVER_URL
        if form_data.DOCLING_SERVER_URL is not None
        else request.app.state.config.DOCLING_SERVER_URL
    )
    request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT = (
        form_data.DOCUMENT_INTELLIGENCE_ENDPOINT
        if form_data.DOCUMENT_INTELLIGENCE_ENDPOINT is not None
        else request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT
    )
    request.app.state.config.DOCUMENT_INTELLIGENCE_KEY = resolve_sensitive_value(
        form_data.DOCUMENT_INTELLIGENCE_KEY
        if form_data.DOCUMENT_INTELLIGENCE_KEY is not None
        else request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
        request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
    )
    request.app.state.config.MISTRAL_OCR_API_KEY = resolve_sensitive_value(
        form_data.MISTRAL_OCR_API_KEY
        if form_data.MISTRAL_OCR_API_KEY is not None
        else request.app.state.config.MISTRAL_OCR_API_KEY,
        request.app.state.config.MISTRAL_OCR_API_KEY,
    )
    request.app.state.config.DOCUMENT_AI_PROJECT_ID = (
        form_data.DOCUMENT_AI_PROJECT_ID
        if form_data.DOCUMENT_AI_PROJECT_ID is not None
        else request.app.state.config.DOCUMENT_AI_PROJECT_ID
    )
    request.app.state.config.DOCUMENT_AI_LOCATION = (
        form_data.DOCUMENT_AI_LOCATION
        if form_data.DOCUMENT_AI_LOCATION is not None
        else request.app.state.config.DOCUMENT_AI_LOCATION
    )
    request.app.state.config.DOCUMENT_AI_PROCESSOR_ID = (
        form_data.DOCUMENT_AI_PROCESSOR_ID
        if form_data.DOCUMENT_AI_PROCESSOR_ID is not None
        else request.app.state.config.DOCUMENT_AI_PROCESSOR_ID
    )
    request.app.state.config.DOCUMENT_AI_PROCESSOR_VERSION = (
        form_data.DOCUMENT_AI_PROCESSOR_VERSION
        if form_data.DOCUMENT_AI_PROCESSOR_VERSION is not None
        else request.app.state.config.DOCUMENT_AI_PROCESSOR_VERSION
    )
    if form_data.DOCUMENT_AI_SERVICE_ACCOUNT_KEY is not None:
        request.app.state.config.DOCUMENT_AI_SERVICE_ACCOUNT_KEY = (
            resolve_sensitive_value(
                form_data.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
                request.app.state.config.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
            )
        )

    # Chunking settings
    request.app.state.config.TEXT_SPLITTER = (
        form_data.TEXT_SPLITTER
        if form_data.TEXT_SPLITTER is not None
        else request.app.state.config.TEXT_SPLITTER
    )
    request.app.state.config.CHUNK_SIZE = (
        form_data.CHUNK_SIZE
        if form_data.CHUNK_SIZE is not None
        else request.app.state.config.CHUNK_SIZE
    )
    request.app.state.config.CHUNK_OVERLAP = (
        form_data.CHUNK_OVERLAP
        if form_data.CHUNK_OVERLAP is not None
        else request.app.state.config.CHUNK_OVERLAP
    )

    # File upload settings
    request.app.state.config.FILE_MAX_SIZE = (
        form_data.FILE_MAX_SIZE
        if form_data.FILE_MAX_SIZE is not None
        else request.app.state.config.FILE_MAX_SIZE
    )
    request.app.state.config.FILE_MAX_COUNT = (
        form_data.FILE_MAX_COUNT
        if form_data.FILE_MAX_COUNT is not None
        else request.app.state.config.FILE_MAX_COUNT
    )
    request.app.state.config.PDF_CONVERT_EXTENSIONS = (
        form_data.PDF_CONVERT_EXTENSIONS
        if form_data.PDF_CONVERT_EXTENSIONS is not None
        else request.app.state.config.PDF_CONVERT_EXTENSIONS
    )
    request.app.state.config.ALLOWED_FILE_EXTENSIONS = (
        form_data.ALLOWED_FILE_EXTENSIONS
        if form_data.ALLOWED_FILE_EXTENSIONS is not None
        else request.app.state.config.ALLOWED_FILE_EXTENSIONS
    )

    # Global Guardrails
    if form_data.global_guardrail is not None:
        gg = form_data.global_guardrail
        if "ENABLE_GLOBAL_GUARDRAIL" in gg:
            request.app.state.config.ENABLE_GLOBAL_GUARDRAIL = gg[
                "ENABLE_GLOBAL_GUARDRAIL"
            ]
        if "GLOBAL_GUARDRAIL_IDS" in gg:
            request.app.state.config.GLOBAL_GUARDRAIL_IDS = gg["GLOBAL_GUARDRAIL_IDS"]

    # File Upload Guardrails (license-gated)
    if form_data.file_guardrail is not None:
        if not is_feature_enabled(request.app, "file_guardrail"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature requires a valid license. Module 'file_guardrail' is not enabled.",
            )
        fg = form_data.file_guardrail
        if "FILE_GUARDRAIL_ENABLED" in fg:
            request.app.state.config.FILE_GUARDRAIL_ENABLED = fg[
                "FILE_GUARDRAIL_ENABLED"
            ]
        if "FILE_GUARDRAIL_SCOPES" in fg:
            request.app.state.config.FILE_GUARDRAIL_SCOPES = fg["FILE_GUARDRAIL_SCOPES"]
        if "FILE_GUARDRAIL_IDS" in fg:
            request.app.state.config.FILE_GUARDRAIL_IDS = fg["FILE_GUARDRAIL_IDS"]
        if "FILE_GUARDRAIL_EXIF_ENABLED" in fg:
            request.app.state.config.FILE_GUARDRAIL_EXIF_ENABLED = fg[
                "FILE_GUARDRAIL_EXIF_ENABLED"
            ]
        if "FILE_GUARDRAIL_MACRO_ENABLED" in fg:
            request.app.state.config.FILE_GUARDRAIL_MACRO_ENABLED = fg[
                "FILE_GUARDRAIL_MACRO_ENABLED"
            ]
        if "FILE_GUARDRAIL_MACRO_ACTION" in fg:
            request.app.state.config.FILE_GUARDRAIL_MACRO_ACTION = fg[
                "FILE_GUARDRAIL_MACRO_ACTION"
            ]
        if "FILE_GUARDRAIL_NSFW_ENABLED" in fg:
            request.app.state.config.FILE_GUARDRAIL_NSFW_ENABLED = fg[
                "FILE_GUARDRAIL_NSFW_ENABLED"
            ]
        if "FILE_GUARDRAIL_NSFW_MODEL" in fg:
            request.app.state.config.FILE_GUARDRAIL_NSFW_MODEL = fg[
                "FILE_GUARDRAIL_NSFW_MODEL"
            ]
        if "FILE_GUARDRAIL_NSFW_PROMPT" in fg:
            request.app.state.config.FILE_GUARDRAIL_NSFW_PROMPT = fg[
                "FILE_GUARDRAIL_NSFW_PROMPT"
            ]
        if "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES" in fg:
            request.app.state.config.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES = fg[
                "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES"
            ]
        if "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES" in fg:
            request.app.state.config.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES = fg[
                "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_ENABLED" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_ENABLED = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_ENABLED"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_MODEL" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_MODEL = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_MODEL"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_PROMPT" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_PROMPT = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_PROMPT"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS"
            ]
        if "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES" in fg:
            request.app.state.config.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES = fg[
                "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES"
            ]

    # Integration settings
    request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION = (
        form_data.ENABLE_GOOGLE_DRIVE_INTEGRATION
        if form_data.ENABLE_GOOGLE_DRIVE_INTEGRATION is not None
        else request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION
    )
    request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION = (
        form_data.ENABLE_ONEDRIVE_INTEGRATION
        if form_data.ENABLE_ONEDRIVE_INTEGRATION is not None
        else request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION
    )
    request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION = (
        form_data.ENABLE_SHAREPOINT_INTEGRATION
        if form_data.ENABLE_SHAREPOINT_INTEGRATION is not None
        else request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION
    )

    # KB Question Generation settings
    if form_data.kb_question_generation is not None:
        kb_config = form_data.kb_question_generation
        if "KB_QUESTION_GENERATION_ENABLED" in kb_config:
            request.app.state.config.KB_QUESTION_GENERATION_ENABLED = kb_config[
                "KB_QUESTION_GENERATION_ENABLED"
            ]
        if "KB_QUESTION_GENERATION_MODEL" in kb_config:
            request.app.state.config.KB_QUESTION_GENERATION_MODEL = kb_config[
                "KB_QUESTION_GENERATION_MODEL"
            ]
        if "KB_MAX_QUESTIONS_PER_CHUNK" in kb_config:
            request.app.state.config.KB_MAX_QUESTIONS_PER_CHUNK = kb_config[
                "KB_MAX_QUESTIONS_PER_CHUNK"
            ]
        if "KB_QUESTION_VECTOR_WEIGHT" in kb_config:
            request.app.state.config.KB_QUESTION_VECTOR_WEIGHT = kb_config[
                "KB_QUESTION_VECTOR_WEIGHT"
            ]

    if form_data.web is not None:
        # Web search settings
        request.app.state.config.ENABLE_WEB_SEARCH = form_data.web.ENABLE_WEB_SEARCH
        request.app.state.config.WEB_SEARCH_ENGINE = form_data.web.WEB_SEARCH_ENGINE
        request.app.state.config.WEB_SEARCH_TRUST_ENV = (
            form_data.web.WEB_SEARCH_TRUST_ENV
        )
        request.app.state.config.WEB_SEARCH_RESULT_COUNT = (
            form_data.web.WEB_SEARCH_RESULT_COUNT
        )
        request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS = (
            form_data.web.WEB_SEARCH_CONCURRENT_REQUESTS
        )
        request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST = (
            form_data.web.WEB_SEARCH_DOMAIN_FILTER_LIST
        )
        request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL = (
            form_data.web.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
        )
        request.app.state.config.SEARXNG_QUERY_URL = form_data.web.SEARXNG_QUERY_URL
        request.app.state.config.GOOGLE_PSE_API_KEY = resolve_sensitive_value(
            form_data.web.GOOGLE_PSE_API_KEY,
            request.app.state.config.GOOGLE_PSE_API_KEY,
        )
        request.app.state.config.GOOGLE_PSE_ENGINE_ID = (
            form_data.web.GOOGLE_PSE_ENGINE_ID
        )
        request.app.state.config.BRAVE_SEARCH_API_KEY = resolve_sensitive_value(
            form_data.web.BRAVE_SEARCH_API_KEY,
            request.app.state.config.BRAVE_SEARCH_API_KEY,
        )
        request.app.state.config.KAGI_SEARCH_API_KEY = resolve_sensitive_value(
            form_data.web.KAGI_SEARCH_API_KEY,
            request.app.state.config.KAGI_SEARCH_API_KEY,
        )
        request.app.state.config.MOJEEK_SEARCH_API_KEY = resolve_sensitive_value(
            form_data.web.MOJEEK_SEARCH_API_KEY,
            request.app.state.config.MOJEEK_SEARCH_API_KEY,
        )
        request.app.state.config.BOCHA_SEARCH_API_KEY = resolve_sensitive_value(
            form_data.web.BOCHA_SEARCH_API_KEY,
            request.app.state.config.BOCHA_SEARCH_API_KEY,
        )
        request.app.state.config.SERPSTACK_API_KEY = resolve_sensitive_value(
            form_data.web.SERPSTACK_API_KEY,
            request.app.state.config.SERPSTACK_API_KEY,
        )
        request.app.state.config.SERPSTACK_HTTPS = form_data.web.SERPSTACK_HTTPS
        request.app.state.config.SERPER_API_KEY = resolve_sensitive_value(
            form_data.web.SERPER_API_KEY,
            request.app.state.config.SERPER_API_KEY,
        )
        request.app.state.config.SERPLY_API_KEY = resolve_sensitive_value(
            form_data.web.SERPLY_API_KEY,
            request.app.state.config.SERPLY_API_KEY,
        )
        request.app.state.config.TAVILY_API_KEY = resolve_sensitive_value(
            form_data.web.TAVILY_API_KEY,
            request.app.state.config.TAVILY_API_KEY,
        )
        request.app.state.config.SEARCHAPI_API_KEY = resolve_sensitive_value(
            form_data.web.SEARCHAPI_API_KEY,
            request.app.state.config.SEARCHAPI_API_KEY,
        )
        request.app.state.config.SEARCHAPI_ENGINE = form_data.web.SEARCHAPI_ENGINE
        request.app.state.config.SERPAPI_API_KEY = resolve_sensitive_value(
            form_data.web.SERPAPI_API_KEY,
            request.app.state.config.SERPAPI_API_KEY,
        )
        request.app.state.config.SERPAPI_ENGINE = form_data.web.SERPAPI_ENGINE
        request.app.state.config.JINA_API_KEY = resolve_sensitive_value(
            form_data.web.JINA_API_KEY,
            request.app.state.config.JINA_API_KEY,
        )
        request.app.state.config.BING_SEARCH_V7_ENDPOINT = (
            form_data.web.BING_SEARCH_V7_ENDPOINT
        )
        request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY = (
            resolve_sensitive_value(
                form_data.web.BING_SEARCH_V7_SUBSCRIPTION_KEY,
                request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
            )
        )
        request.app.state.config.EXA_API_KEY = resolve_sensitive_value(
            form_data.web.EXA_API_KEY,
            request.app.state.config.EXA_API_KEY,
        )
        request.app.state.config.PERPLEXITY_API_KEY = resolve_sensitive_value(
            form_data.web.PERPLEXITY_API_KEY,
            request.app.state.config.PERPLEXITY_API_KEY,
        )
        request.app.state.config.SOUGOU_API_SID = form_data.web.SOUGOU_API_SID
        request.app.state.config.SOUGOU_API_SK = form_data.web.SOUGOU_API_SK

        # Web loader settings
        request.app.state.config.WEB_LOADER_ENGINE = form_data.web.WEB_LOADER_ENGINE
        request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION = (
            form_data.web.ENABLE_WEB_LOADER_SSL_VERIFICATION
        )
        request.app.state.config.PLAYWRIGHT_WS_URL = form_data.web.PLAYWRIGHT_WS_URL
        request.app.state.config.PLAYWRIGHT_TIMEOUT = form_data.web.PLAYWRIGHT_TIMEOUT
        request.app.state.config.FIRECRAWL_API_KEY = resolve_sensitive_value(
            form_data.web.FIRECRAWL_API_KEY,
            request.app.state.config.FIRECRAWL_API_KEY,
        )
        request.app.state.config.FIRECRAWL_API_BASE_URL = (
            form_data.web.FIRECRAWL_API_BASE_URL
        )
        request.app.state.config.TAVILY_EXTRACT_DEPTH = (
            form_data.web.TAVILY_EXTRACT_DEPTH
        )
        request.app.state.config.YOUTUBE_LOADER_LANGUAGE = (
            form_data.web.YOUTUBE_LOADER_LANGUAGE
        )
        request.app.state.config.YOUTUBE_LOADER_PROXY_URL = (
            form_data.web.YOUTUBE_LOADER_PROXY_URL
        )
        request.app.state.YOUTUBE_LOADER_TRANSLATION = (
            form_data.web.YOUTUBE_LOADER_TRANSLATION
        )

    AuditLogger.log_settings_change("documents/rag", after_data=form_data.model_dump())
    return mask_config_dict(
        {
            "status": True,
            # RAG settings
            "RAG_TEMPLATE": request.app.state.config.RAG_TEMPLATE,
            "BYPASS_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL,
            # Content extraction settings
            "CONTENT_EXTRACTION_ENGINE": request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            "PDF_EXTRACT_IMAGES": request.app.state.config.PDF_EXTRACT_IMAGES,
            "TIKA_SERVER_URL": request.app.state.config.TIKA_SERVER_URL,
            "DOCLING_SERVER_URL": request.app.state.config.DOCLING_SERVER_URL,
            "DOCUMENT_INTELLIGENCE_ENDPOINT": request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
            "DOCUMENT_INTELLIGENCE_KEY": request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
            "MISTRAL_OCR_API_KEY": request.app.state.config.MISTRAL_OCR_API_KEY,
            "DOCUMENT_AI_PROJECT_ID": request.app.state.config.DOCUMENT_AI_PROJECT_ID,
            "DOCUMENT_AI_LOCATION": request.app.state.config.DOCUMENT_AI_LOCATION,
            "DOCUMENT_AI_PROCESSOR_ID": request.app.state.config.DOCUMENT_AI_PROCESSOR_ID,
            "DOCUMENT_AI_PROCESSOR_VERSION": request.app.state.config.DOCUMENT_AI_PROCESSOR_VERSION,
            "DOCUMENT_AI_SERVICE_ACCOUNT_KEY": request.app.state.config.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
            # Chunking settings
            "TEXT_SPLITTER": request.app.state.config.TEXT_SPLITTER,
            "CHUNK_SIZE": request.app.state.config.CHUNK_SIZE,
            "CHUNK_OVERLAP": request.app.state.config.CHUNK_OVERLAP,
            # File upload settings
            "FILE_MAX_SIZE": request.app.state.config.FILE_MAX_SIZE,
            "FILE_MAX_COUNT": request.app.state.config.FILE_MAX_COUNT,
            "PDF_CONVERT_EXTENSIONS": request.app.state.config.PDF_CONVERT_EXTENSIONS,
            "ALLOWED_FILE_EXTENSIONS": request.app.state.config.ALLOWED_FILE_EXTENSIONS,
            # Global Guardrails
            "global_guardrail": {
                "ENABLE_GLOBAL_GUARDRAIL": getattr(
                    request.app.state.config, "ENABLE_GLOBAL_GUARDRAIL", False
                ),
                "GLOBAL_GUARDRAIL_IDS": getattr(
                    request.app.state.config, "GLOBAL_GUARDRAIL_IDS", []
                ),
            },
            # File Upload Guardrails
            "file_guardrail": {
                "FILE_GUARDRAIL_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_ENABLED", False
                ),
                "FILE_GUARDRAIL_SCOPES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_SCOPES",
                    ["chat", "knowledge", "project"],
                ),
                "FILE_GUARDRAIL_IDS": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_IDS", []
                ),
                "FILE_GUARDRAIL_EXIF_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_EXIF_ENABLED", False
                ),
                "FILE_GUARDRAIL_MACRO_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_MACRO_ENABLED", False
                ),
                "FILE_GUARDRAIL_MACRO_ACTION": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_MACRO_ACTION", "block"
                ),
                "FILE_GUARDRAIL_NSFW_ENABLED": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_ENABLED", False
                ),
                "FILE_GUARDRAIL_NSFW_MODEL": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_MODEL", ""
                ),
                "FILE_GUARDRAIL_NSFW_PROMPT": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_PROMPT", ""
                ),
                "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES", []
                ),
                "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES", []
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_ENABLED": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_ENABLED",
                    False,
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_MODEL": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_MODEL", ""
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_PROMPT": getattr(
                    request.app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_PROMPT", ""
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES",
                    [],
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES",
                    [],
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS",
                    8000,
                ),
                "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES": getattr(
                    request.app.state.config,
                    "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES",
                    [],
                ),
            },
            # Integration settings
            "ENABLE_GOOGLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
            "ENABLE_ONEDRIVE_INTEGRATION": request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
            "ENABLE_SHAREPOINT_INTEGRATION": request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION,
            # KB Question Generation settings
            "kb_question_generation": {
                "KB_QUESTION_GENERATION_ENABLED": getattr(
                    request.app.state.config, "KB_QUESTION_GENERATION_ENABLED", False
                ),
                "KB_QUESTION_GENERATION_MODEL": getattr(
                    request.app.state.config, "KB_QUESTION_GENERATION_MODEL", ""
                ),
                "KB_MAX_QUESTIONS_PER_CHUNK": getattr(
                    request.app.state.config, "KB_MAX_QUESTIONS_PER_CHUNK", 10
                ),
                "KB_QUESTION_VECTOR_WEIGHT": getattr(
                    request.app.state.config, "KB_QUESTION_VECTOR_WEIGHT", 0.5
                ),
            },
            # Web search settings
            "web": {
                "ENABLE_WEB_SEARCH": request.app.state.config.ENABLE_WEB_SEARCH,
                "WEB_SEARCH_ENGINE": request.app.state.config.WEB_SEARCH_ENGINE,
                "WEB_SEARCH_TRUST_ENV": request.app.state.config.WEB_SEARCH_TRUST_ENV,
                "WEB_SEARCH_RESULT_COUNT": request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                "WEB_SEARCH_CONCURRENT_REQUESTS": request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
                "WEB_SEARCH_DOMAIN_FILTER_LIST": request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
                "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL,
                "SEARXNG_QUERY_URL": request.app.state.config.SEARXNG_QUERY_URL,
                "GOOGLE_PSE_API_KEY": request.app.state.config.GOOGLE_PSE_API_KEY,
                "GOOGLE_PSE_ENGINE_ID": request.app.state.config.GOOGLE_PSE_ENGINE_ID,
                "BRAVE_SEARCH_API_KEY": request.app.state.config.BRAVE_SEARCH_API_KEY,
                "KAGI_SEARCH_API_KEY": request.app.state.config.KAGI_SEARCH_API_KEY,
                "MOJEEK_SEARCH_API_KEY": request.app.state.config.MOJEEK_SEARCH_API_KEY,
                "BOCHA_SEARCH_API_KEY": request.app.state.config.BOCHA_SEARCH_API_KEY,
                "SERPSTACK_API_KEY": request.app.state.config.SERPSTACK_API_KEY,
                "SERPSTACK_HTTPS": request.app.state.config.SERPSTACK_HTTPS,
                "SERPER_API_KEY": request.app.state.config.SERPER_API_KEY,
                "SERPLY_API_KEY": request.app.state.config.SERPLY_API_KEY,
                "TAVILY_API_KEY": request.app.state.config.TAVILY_API_KEY,
                "SEARCHAPI_API_KEY": request.app.state.config.SEARCHAPI_API_KEY,
                "SEARCHAPI_ENGINE": request.app.state.config.SEARCHAPI_ENGINE,
                "SERPAPI_API_KEY": request.app.state.config.SERPAPI_API_KEY,
                "SERPAPI_ENGINE": request.app.state.config.SERPAPI_ENGINE,
                "JINA_API_KEY": request.app.state.config.JINA_API_KEY,
                "BING_SEARCH_V7_ENDPOINT": request.app.state.config.BING_SEARCH_V7_ENDPOINT,
                "BING_SEARCH_V7_SUBSCRIPTION_KEY": request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
                "EXA_API_KEY": request.app.state.config.EXA_API_KEY,
                "PERPLEXITY_API_KEY": request.app.state.config.PERPLEXITY_API_KEY,
                "SOUGOU_API_SID": request.app.state.config.SOUGOU_API_SID,
                "SOUGOU_API_SK": request.app.state.config.SOUGOU_API_SK,
                "WEB_LOADER_ENGINE": request.app.state.config.WEB_LOADER_ENGINE,
                "ENABLE_WEB_LOADER_SSL_VERIFICATION": request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
                "PLAYWRIGHT_WS_URL": request.app.state.config.PLAYWRIGHT_WS_URL,
                "PLAYWRIGHT_TIMEOUT": request.app.state.config.PLAYWRIGHT_TIMEOUT,
                "FIRECRAWL_API_KEY": request.app.state.config.FIRECRAWL_API_KEY,
                "FIRECRAWL_API_BASE_URL": request.app.state.config.FIRECRAWL_API_BASE_URL,
                "TAVILY_EXTRACT_DEPTH": request.app.state.config.TAVILY_EXTRACT_DEPTH,
                "YOUTUBE_LOADER_LANGUAGE": request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
                "YOUTUBE_LOADER_PROXY_URL": request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
                "YOUTUBE_LOADER_TRANSLATION": request.app.state.YOUTUBE_LOADER_TRANSLATION,
            },
        }
    )


####################################
#
# Debug endpoints for Vector DB
#
####################################


####################################
#
# Document process and retrieval
#
####################################


def _collection_is_persistent_kb(collection_name: Optional[str]) -> bool:
    """컬렉션이 영속 Knowledge Base 인지(=LLM enrichment 대상인지) 판정.

    contextual chunking·질의예시 생성은 청크마다 chat LLM 을 fan-out 호출하는 무거운
    enrichment 라 큐레이션된 KB 인제스트에서만 비용을 지불해야 한다. 채팅 첨부는
    ``f"file-{file.id}"`` 임시 컬렉션(또는 collection_name 미지정)으로 처리되며,
    동기 업로드 경로(``upload_file`` → ``process_file``)에서 enrichment 가 돌면
    429 누적으로 요청이 수 분간 블록돼 프론트/프록시 타임아웃 → 첨부 소실을 유발한다.
    라우터 전반에 산재한 ``file-`` 접두 컨벤션(``_sync_knowledge_id`` 계산, KB chunk
    정리 분기 등)과 동일한 판정을 명시적 술어로 만든 것 — 기존 산재 사용처 치환은
    이번 변경 범위 밖(후속 정리 대상). background 경로는 ``pending_knowledge_id``
    fallback 이 있어 helper 대신 resolve 된 ``knowledge_id`` 로 직접 판정한다.
    """
    return bool(collection_name) and not collection_name.startswith("file-")


async def save_docs_to_vector_db(
    request: Request,
    docs,
    collection_name,
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    split: bool = True,
    add: bool = False,
    user=None,
    extra_metadata: Optional[dict] = None,
    knowledge_id: Optional[str] = None,
    doc_profile=None,
    enable_enrichment: bool = True,
) -> bool:
    def _get_docs_info(docs: list[Document]) -> str:
        docs_info = set()

        # Trying to select relevant metadata identifying the document.
        for doc in docs:
            metadata = getattr(doc, "metadata", {})
            doc_name = metadata.get("name", "")
            if not doc_name:
                doc_name = metadata.get("title", "")
            if not doc_name:
                doc_name = metadata.get("source", "")
            if doc_name:
                docs_info.add(doc_name)

        return ", ".join(docs_info)

    log.info(
        f"save_docs_to_vector_db: document {_get_docs_info(docs)} {collection_name}"
    )

    # Check if entries with the same hash (metadata.hash) already exist
    if metadata and "hash" in metadata:
        log.debug(
            f"Checking duplicate for collection={collection_name}, hash={metadata['hash']}"
        )
        is_duplicate = await check_duplicate_hash(
            app=request.app,
            collection_name=collection_name,
            content_hash=metadata["hash"],
            exclude_file_id=metadata.get("file_id"),
        )
        log.debug(f"Duplicate check result: {is_duplicate}")

        if is_duplicate:
            if overwrite:
                # Delete existing chunks with the same hash, then re-insert
                log.info(
                    f"Overwriting duplicate in collection={collection_name}, hash={metadata['hash']}"
                )
                try:
                    knowledge_svc = SearchEngineKnowledge(
                        app=request.app, collection_name=collection_name
                    )
                    deleted = await knowledge_svc.delete_by_metadata(
                        {"hash": metadata["hash"]}
                    )
                    log.info(
                        f"Deleted {deleted} existing chunks for hash={metadata['hash']}"
                    )
                except Exception as e:
                    log.error(f"Failed to delete existing chunks for overwrite: {e}")
            else:
                log.warning(
                    f"Duplicate detected in collection={collection_name}, hash={metadata['hash']}"
                )
                raise ValueError(ERROR_MESSAGES.DUPLICATE_CONTENT)

    if split:
        _text_splitter = (
            doc_profile.text_splitter if doc_profile else None
        ) or request.app.state.config.TEXT_SPLITTER
        _chunk_size = (
            doc_profile.chunk_size if doc_profile else None
        ) or request.app.state.config.CHUNK_SIZE
        _chunk_overlap = (
            doc_profile.chunk_overlap if doc_profile else None
        ) or request.app.state.config.CHUNK_OVERLAP

        if _text_splitter in ["", "character"]:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=_chunk_size,
                chunk_overlap=_chunk_overlap,
                add_start_index=True,
            )
        elif _text_splitter == "token":
            log.info(
                f"Using token text splitter: {request.app.state.config.TIKTOKEN_ENCODING_NAME}"
            )

            tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
            text_splitter = TokenTextSplitter(
                encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
                chunk_size=_chunk_size,
                chunk_overlap=_chunk_overlap,
                add_start_index=True,
            )
        elif _text_splitter == "semantic":
            from langchain_experimental.text_splitter import SemanticChunker

            _doc_config = (doc_profile.config or {}) if doc_profile else {}
            _threshold_type = _doc_config.get("semantic_threshold_type", "percentile")
            _threshold = _doc_config.get("semantic_threshold", 95)
            # 최소 청크 크기는 splitter 무관 통합 토큰 기반 후처리(enforce_token_bounds)로
            # 일원화됨 — SemanticChunker 의 문자 기반 min_chunk_size 는 더 이상 사용하지 않는다.

            # Build LangChain Embeddings object for SemanticChunker
            _sem_embeddings = request.app.state.ef  # SentenceTransformer (local)
            if _sem_embeddings is None:
                _sem_engine = request.app.state.config.RAG_EMBEDDING_ENGINE
                _sem_model = request.app.state.config.RAG_EMBEDDING_MODEL
                if _sem_engine == "openai":
                    from langchain_openai import OpenAIEmbeddings

                    _sem_embeddings = OpenAIEmbeddings(
                        model=_sem_model,
                        openai_api_key=request.app.state.config.RAG_OPENAI_API_KEY,
                        openai_api_base=request.app.state.config.RAG_OPENAI_API_BASE_URL,
                    )
                elif _sem_engine == "azure_openai":
                    from langchain_openai import AzureOpenAIEmbeddings

                    _sem_embeddings = AzureOpenAIEmbeddings(
                        model=_sem_model,
                        azure_endpoint=request.app.state.config.RAG_AZURE_OPENAI_API_BASE_URL,
                        api_key=request.app.state.config.RAG_AZURE_OPENAI_API_KEY,
                        api_version=request.app.state.config.RAG_AZURE_OPENAI_API_VERSION,
                    )
                elif _sem_engine == "ollama":
                    from langchain_community.embeddings import OllamaEmbeddings

                    _sem_embeddings = OllamaEmbeddings(
                        model=_sem_model,
                        base_url=request.app.state.config.RAG_OLLAMA_BASE_URL,
                    )
                elif _sem_engine == "gemini":
                    from langchain_google_genai import GoogleGenerativeAIEmbeddings

                    _sem_embeddings = GoogleGenerativeAIEmbeddings(
                        model=_sem_model,
                        google_api_key=request.app.state.config.RAG_GEMINI_API_KEY,
                    )
                elif _sem_engine == "vertex_ai":
                    from langchain_google_vertexai import VertexAIEmbeddings

                    _sem_embeddings = VertexAIEmbeddings(
                        model_name=_sem_model,
                        project=request.app.state.config.RAG_VERTEX_AI_PROJECT_ID,
                        location=request.app.state.config.RAG_VERTEX_AI_LOCATION,
                    )

            if _sem_embeddings is None:
                raise ValueError(
                    ERROR_MESSAGES.DEFAULT(
                        "Semantic chunking requires an embedding model. Current engine not supported for semantic chunking."
                    )
                )

            text_splitter = SemanticChunker(
                embeddings=_sem_embeddings,
                breakpoint_threshold_type=_threshold_type,
                breakpoint_threshold_amount=_threshold,
            )
        else:
            raise ValueError(ERROR_MESSAGES.DEFAULT("Invalid text splitter"))

        _preserve_tables = (
            (doc_profile.config or {}).get("preserve_tables", True)
            if doc_profile
            else True
        )

        if _preserve_tables:
            from open_webui.retrieval.table_preserving_chunker import (
                split_preserving_tables,
            )

            docs = split_preserving_tables(docs, text_splitter, _chunk_size)
        else:
            docs = text_splitter.split_documents(docs)

        # Semantic chunker는 오버랩을 자체 지원하지 않으므로 후처리로 적용
        if _text_splitter == "semantic" and _chunk_overlap > 0:
            from open_webui.retrieval.table_preserving_chunker import (
                apply_chunk_overlap,
            )

            docs = apply_chunk_overlap(docs, _chunk_overlap)

    if len(docs) == 0:
        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

    # Contextual Chunking (선택적 후처리)
    _ctx_config = (doc_profile.config or {}) if doc_profile else {}
    _ctx_enabled = _ctx_config.get("contextual_chunking_enabled", False)
    _ctx_model = _ctx_config.get("contextual_chunking_model", "")

    if _ctx_enabled and _ctx_model and enable_enrichment:
        from open_webui.retrieval.contextual_chunking import apply_contextual_chunking

        full_text = " ".join([d.page_content for d in docs])
        docs = await apply_contextual_chunking(
            app=request.app,
            docs=docs,
            full_text=full_text,
            model_id=_ctx_model,
        )
    elif _ctx_enabled and _ctx_model:
        # 프로파일은 contextual chunking 을 켰지만 휘발성 첨부(채팅 등)라 skip —
        # 청크당 chat LLM fan-out 을 피해 embed-only 로 빠르게 처리한다.
        log.info(
            "Skipping contextual chunking for ephemeral upload (collection=%s)",
            collection_name,
        )

    # 토큰 단위 크기 안전망 (모든 splitter 공통, 임베딩 직전).
    # semantic chunker 는 최대 상한이 없고 overlap/contextual 후처리가 청크를 더
    # 키우므로, 임베딩 모델 토큰 한도를 넘는 청크는 여기서 토큰 경계로 재분할한다.
    # doc_profile.config 에 chunk_max_tokens/chunk_min_tokens 가 있으면 전역 설정을 override.
    _bounds_config = (doc_profile.config or {}) if doc_profile else {}
    _max_tokens = _bounds_config.get("chunk_max_tokens", None)
    if _max_tokens is None:
        _max_tokens = request.app.state.config.RAG_CHUNK_MAX_TOKENS
    _min_tokens = _bounds_config.get("chunk_min_tokens", None)
    if _min_tokens is None:
        _min_tokens = request.app.state.config.RAG_CHUNK_MIN_TOKENS

    try:
        _max_tokens = int(_max_tokens or 0)
        _min_tokens = int(_min_tokens or 0)
    except (TypeError, ValueError):
        _max_tokens, _min_tokens = 0, 0

    if _max_tokens > 0 or _min_tokens > 0:
        from open_webui.retrieval.table_preserving_chunker import enforce_token_bounds

        docs = enforce_token_bounds(
            docs,
            max_tokens=_max_tokens,
            min_tokens=_min_tokens,
            encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
        )

    texts = [doc.page_content for doc in docs]

    # Filter metadata to keep only essential fields
    # (DocumentIntelligence returns huge metadata with result.as_dict())
    ALLOWED_METADATA_KEYS = {
        "file_id",
        "name",
        "hash",
        "page",
        "start_index",
        "created_by",
        "source",
        "title",
        "Content-Type",
    }

    def filter_metadata(doc_meta: dict, extra_meta: dict | None) -> dict:
        """Filter metadata to keep only allowed keys."""
        filtered = {}
        for key in ALLOWED_METADATA_KEYS:
            if key in doc_meta:
                filtered[key] = doc_meta[key]
        if extra_meta:
            for key, value in extra_meta.items():
                if key in ALLOWED_METADATA_KEYS:
                    filtered[key] = value
        return filtered

    metadatas = [filter_metadata(doc.metadata, metadata) for doc in docs]

    # 검색엔진 스키마 필드 매핑: page → page_num, chunk_index 추가
    for idx, meta in enumerate(metadatas):
        if "page" in meta:
            meta["page_num"] = meta.pop("page")
        meta["chunk_index"] = idx

    # ChromaDB does not like datetime formats
    # for meta-data so convert them to string.
    for metadata in metadatas:
        for key, value in metadata.items():
            if (
                isinstance(value, datetime)
                or isinstance(value, list)
                or isinstance(value, dict)
            ):
                metadata[key] = str(value)

    try:
        # SearchEngineKnowledge 인스턴스 생성
        enable_question_vector = getattr(
            request.app.state.config, "KB_QUESTION_GENERATION_ENABLED", False
        )
        knowledge_service = SearchEngineKnowledge(
            app=request.app,
            collection_name=collection_name,
            vector_dim=get_effective_embedding_dimension(request.app),
            enable_question_vector=enable_question_vector,
        )

        # overwrite 의미: "이 file_id의 이전 청크만" 교체.
        # 과거에는 컬렉션 전체를 wipe 했는데, 파일별 컬렉션(file-{id})
        # 시대의 잔재였음. KB 공용 컬렉션에서 이 동작은 병렬 처리 중
        # 다른 파일들의 청크까지 삭제해 버리므로 file_id 스코프로 축소한다.
        _file_id = (metadata or {}).get("file_id") if metadata else None

        if overwrite:
            if _file_id:
                deleted = await knowledge_service.delete_by_file_id(_file_id)
                if deleted:
                    log.info(
                        f"overwrite: deleted {deleted} prior chunks for "
                        f"file_id={_file_id} in collection {collection_name}"
                    )
            else:
                # 레거시 경로: metadata에 file_id가 없을 때만 전체 wipe 허용
                # (file-{id} 단일 파일 컬렉션용)
                if await knowledge_service.has_documents():
                    await knowledge_service.delete_by_collection()
                    log.info(f"overwrite: wiped legacy collection {collection_name}")
        elif add is False:
            if await knowledge_service.has_documents():
                log.info(
                    f"collection {collection_name} already exists, overwrite is False and add is False"
                )
                return True

        log.info(f"adding to collection {collection_name}")

        # Use global RAG embedding config
        cfg = request.app.state.config
        _emb_engine = cfg.RAG_EMBEDDING_ENGINE

        embedding_function = get_embedding_function(
            _emb_engine,
            cfg.RAG_EMBEDDING_MODEL,
            request.app.state.ef,
            (
                cfg.RAG_AZURE_OPENAI_API_BASE_URL
                if _emb_engine == "azure_openai"
                else (
                    cfg.RAG_OPENAI_API_BASE_URL
                    if _emb_engine == "openai"
                    else (
                        ""
                        if _emb_engine in ["gemini", "vertex_ai"]
                        else cfg.RAG_OLLAMA_BASE_URL
                    )
                )
            ),
            (
                cfg.RAG_AZURE_OPENAI_API_KEY
                if _emb_engine == "azure_openai"
                else (
                    cfg.RAG_OPENAI_API_KEY
                    if _emb_engine == "openai"
                    else (
                        cfg.RAG_GEMINI_API_KEY
                        if _emb_engine == "gemini"
                        else (
                            "" if _emb_engine == "vertex_ai" else cfg.RAG_OLLAMA_API_KEY
                        )
                    )
                )
            ),
            cfg.RAG_EMBEDDING_BATCH_SIZE,
            azure_api_version=(
                cfg.RAG_AZURE_OPENAI_API_VERSION
                if _emb_engine == "azure_openai"
                else None
            ),
            vertex_ai_project_id=(
                cfg.RAG_VERTEX_AI_PROJECT_ID if _emb_engine == "vertex_ai" else None
            ),
            vertex_ai_location=(
                cfg.RAG_VERTEX_AI_LOCATION if _emb_engine == "vertex_ai" else None
            ),
            vertex_ai_service_account_key=(
                cfg.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY
                if _emb_engine == "vertex_ai"
                else None
            ),
            google_cloud_service_account_key=(
                cfg.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY
                if _emb_engine == "vertex_ai"
                else None
            ),
        )

        # 빈 청크 필터링: extraction 단계에서 일부 페이지가 빈 문자열로
        # 돌아올 수 있다 (예: 이미지 기반 PDF, LLM Vision 추출 실패 fallback).
        # 빈 입력은 OpenAI/Azure 임베딩 API가 거부하므로 사전에 제거한다.
        cleaned_texts = [t.replace("\n", " ").strip() for t in texts]
        non_empty_pairs = [(i, t) for i, t in enumerate(cleaned_texts) if t]

        if not non_empty_pairs:
            # Stable English key — frontend i18n maps this to the localized
            # message. See `Document extraction returned empty content` in
            # src/lib/i18n/locales/{ko-KR,en-US}/translation.json.
            log.error(
                f"Document extraction returned empty content "
                f"({len(cleaned_texts)} empty chunks) for collection {collection_name}"
            )
            raise ValueError(ERROR_MESSAGES.DOCUMENT_EXTRACTION_EMPTY)

        if len(non_empty_pairs) < len(cleaned_texts):
            log.warning(
                f"Filtered {len(cleaned_texts) - len(non_empty_pairs)}/"
                f"{len(cleaned_texts)} empty chunks before embedding"
            )
            kept_indices = [i for i, _ in non_empty_pairs]
            texts = [texts[i] for i in kept_indices]
            metadatas = [metadatas[i] for i in kept_indices]

        filtered_texts_for_embedding = [t for _, t in non_empty_pairs]

        embeddings = await embedding_function(
            filtered_texts_for_embedding,
            prefix=RAG_EMBEDDING_CONTENT_PREFIX,
            user=user,
        )

        # KB 질의예시 생성 기능
        sample_questions_list = None
        question_embeddings = None

        # Per-knowledge search settings override
        kb_question_enabled = getattr(
            request.app.state.config, "KB_QUESTION_GENERATION_ENABLED", False
        )
        kb_max_questions = getattr(
            request.app.state.config, "KB_MAX_QUESTIONS_PER_CHUNK", 10
        )
        kb_question_model: Optional[str] = None
        kb_overridden = False
        if knowledge_id:
            from open_webui.models.knowledge import Knowledges

            kb = Knowledges.get_knowledge_by_id(knowledge_id)
            if kb and kb.meta:
                ss = kb.meta.get("search_settings") or {}
                if ss.get("enable_question_generation") is not None:
                    kb_question_enabled = ss["enable_question_generation"]
                    kb_overridden = True
                if ss.get("max_questions_per_chunk") is not None:
                    kb_max_questions = ss["max_questions_per_chunk"]
                # Per-KB 질의예시 모델 — 빈 문자열/None 은 글로벌 fallback.
                kb_model = ss.get("question_generation_model")
                if kb_model:
                    kb_question_model = kb_model

        if kb_question_enabled and enable_enrichment:
            # 파일명 추출
            filename = ""
            if metadata:
                filename = metadata.get("name", "") or metadata.get("title", "")

            log.info(f"Generating sample questions for {len(texts)} chunks...")
            try:
                sample_questions_list = await generate_chunk_questions(
                    app=request.app,
                    chunks=texts,
                    filename=filename,
                    model_id=kb_question_model,
                    max_questions=kb_max_questions,
                    skip_enabled_check=kb_overridden,
                )

                # 질의예시가 있는 청크들의 임베딩 생성
                questions_to_embed = [q for q in sample_questions_list if q]
                if questions_to_embed:
                    log.info(
                        f"Generating embeddings for {len(questions_to_embed)} question sets..."
                    )
                    # 모든 질의예시에 대해 임베딩 생성
                    question_embeddings_raw = await embedding_function(
                        [q.replace("\n", " ") for q in sample_questions_list if q],
                        prefix=RAG_EMBEDDING_CONTENT_PREFIX,
                        user=user,
                    )
                    # 원래 인덱스에 매핑
                    question_embeddings = []
                    embed_idx = 0
                    for q in sample_questions_list:
                        if q:
                            question_embeddings.append(
                                question_embeddings_raw[embed_idx]
                            )
                            embed_idx += 1
                        else:
                            question_embeddings.append(None)
                    log.info(
                        f"Generated {len(question_embeddings_raw)} question embeddings"
                    )
            except Exception as e:
                log.exception(f"Error generating sample questions: {e}")
                # 에러 시 기본값으로 계속 진행
                sample_questions_list = None
                question_embeddings = None
        elif kb_question_enabled:
            # 질의예시 생성이 켜져 있지만 휘발성 첨부라 skip (청크당 fan-out 비용 회피)
            log.info(
                "Skipping sample-question generation for ephemeral upload (collection=%s)",
                collection_name,
            )

        # chunks 생성 (SearchEngineKnowledge용)
        chunks = [
            {"text": text, "metadata": metadatas[idx]} for idx, text in enumerate(texts)
        ]

        # SearchEngineKnowledge.save_chunks() 호출
        saved_count = await knowledge_service.save_chunks(
            chunks=chunks,
            vectors=embeddings,
            sample_questions_list=sample_questions_list,
            question_vectors=question_embeddings,
            extra_metadata=extra_metadata,
        )

        log.info(f"Saved {saved_count} chunks to collection {collection_name}")
        return True
    except Exception as e:
        log.exception(e)
        raise e


def _pc_get(pc: dict, key: str, fallback):
    """Get value from profile config, falling back if empty/None."""
    v = pc.get(key)
    return v if v else fallback


def _run_async_safe(coro, timeout=300):
    """Run async coroutine in sync thread with timeout, suppressing httpx cleanup errors."""

    async def _wrapped():
        loop = asyncio.get_running_loop()

        def _suppress(loop, context):
            exc = context.get("exception")
            if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
                return
            loop.default_exception_handler(context)

        loop.set_exception_handler(_suppress)
        return await asyncio.wait_for(coro, timeout=timeout)

    return asyncio.run(_wrapped())


def get_doc_profile_for_knowledge(
    app,
    knowledge_id: Optional[str],
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
):
    """
    Resolve document profile for a knowledge base.

    Dual-path: extension_engine_map 이 비어있으면 legacy 경로 (단일 엔진 +
    미지원 확장자 내장 fallback). 매핑이 있으면 filename 의 확장자로 엔진을
    찾아 그 엔진 설정(content_extraction_engine + config + pdf_extract_images)
    을 doc_profile 위에 overlay 한 사본을 반환. 모든 downstream 코드 (text
    splitter / chunk / engine 사용처) 가 동일 인터페이스로 동작한다.

    extension_engine_map 에 없는 확장자는 HTTPException 400 으로 차단.

    Args:
        app: FastAPI app (현재 미사용, 향후 cfg 의존성 위해 시그니처 유지).
        knowledge_id: KB id 또는 None (단일 파일 처리).
        filename: 파일명 (.확장자 추출용). None 이면 매핑 강제 차단을 적용하지
            않고 legacy 경로로 떨어짐 — 호환성 유지.
        content_type: MIME 타입 (현재 미사용, 향후 확장자 없는 파일 대응).
    """
    from open_webui.models.document_profile import (
        DocumentProfiles,
        ExtractionEngineProfiles,
    )
    from open_webui.models.knowledge import Knowledges

    doc_profile = None

    if knowledge_id:
        kb = Knowledges.get_knowledge_by_id(knowledge_id)
        if kb and kb.meta:
            ss = kb.meta.get("search_settings") or {}
            doc_profile_id = ss.get("document_profile_id")
            if doc_profile_id:
                doc_profile = DocumentProfiles.get_profile_by_id(doc_profile_id)

    if not doc_profile:
        doc_profile = DocumentProfiles.get_default_profile()

    if not doc_profile:
        return None

    # 신규 경로: extension_engine_map 이 채워진 프로파일은 매핑된 확장자만
    # 그 엔진으로, 매핑에 없는 확장자는 default_engine_id 가 있으면 그 엔진으로,
    # 둘 다 없으면 기본 내장 엔진으로 fallback.
    # 매핑 값이 "native" sentinel 이면 default 무시하고 즉시 내장 엔진 사용.
    mapping = doc_profile.extension_engine_map or {}
    has_default = bool(doc_profile.default_engine_id)
    if (mapping or has_default) and filename:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_key = f".{ext}" if ext else ""
        engine_id = mapping.get(ext_key) if ext_key else None

        builtin = doc_profile.model_copy(
            update={
                "content_extraction_engine": "",
                "config": dict(doc_profile.config or {}),
                "pdf_extract_images": doc_profile.pdf_extract_images or False,
            }
        )

        # 명시적 "native" 매핑 → default 무시하고 내장 엔진.
        if engine_id == "native":
            return builtin

        if not engine_id and has_default:
            engine_id = doc_profile.default_engine_id

        if not engine_id:
            return builtin

        engine = ExtractionEngineProfiles.get_engine_by_id(engine_id)
        if not engine:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Engine profile {engine_id!r} no longer exists "
                    f"(referenced by '{ext_key or 'default'}')."
                ),
            )

        merged_config = {**(doc_profile.config or {}), **(engine.config or {})}

        return doc_profile.model_copy(
            update={
                "content_extraction_engine": engine.engine_type,
                "config": merged_config,
                "pdf_extract_images": engine.pdf_extract_images or False,
            }
        )

    return doc_profile


class ProcessFileForm(BaseModel):
    file_id: str
    content: Optional[str] = None
    collection_name: Optional[str] = None
    background: bool = False  # Run processing in background
    # 배치 업로드 추적용 — file-processing 알림에 그대로 echo 된다. 프론트는 이를 근거로
    # (a) 배치 진행률을 알림센터(벨) 엔트리에만 집계하고 (b) 발신 세션(client_session_id)만
    # 목록을 reload 하여 타 세션 reload 폭주를 막는다.
    batch_id: Optional[str] = None
    client_session_id: Optional[str] = None


class FileProcessingStatus(BaseModel):
    """Status of file processing job."""

    status: str  # "pending", "processing", "completed", "failed"
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    stage: Optional[str] = None  # "loading", "chunking", "embedding"
    progress: int = 0  # 0-100
    error: Optional[str] = None
    collection_name: Optional[str] = None


def _load_file_content_sync(
    app,
    file_id: str,
    collection_name: Optional[str],
    content: Optional[str],
    doc_profile=None,
):
    """
    Synchronous blocking function to load file content.
    Run this in a thread pool to avoid blocking the event loop.
    """
    from open_webui.models.files import Files
    from open_webui.retrieval.loaders.main import Loader
    from open_webui.storage.provider import Storage

    file = Files.get_file_by_id(file_id)
    if not file:
        return None, None, "File not found"

    actual_collection_name = collection_name or f"file-{file.id}"

    docs = None
    text_content = None

    if content:
        # Content provided directly
        docs = [
            Document(
                page_content=content.replace("<br/>", "\n"),
                metadata={
                    **file.meta,
                    "name": file.filename,
                    "created_by": file.user_id,
                    "file_id": file.id,
                    "source": file.filename,
                },
            )
        ]
        text_content = content
    elif collection_name:
        # If KB has a custom document profile with a non-default engine,
        # force re-extraction instead of using cached content
        _force_reextract = (
            doc_profile
            and doc_profile.content_extraction_engine
            and doc_profile.content_extraction_engine
            != (app.state.config.CONTENT_EXTRACTION_ENGINE or "")
        )

        if not _force_reextract:
            # Use cached content
            existing_docs = query_by_metadata_sync(
                app=app,
                collection_name=f"file-{file.id}",
                filter_dict={"file_id": file.id},
            )

            if existing_docs:
                docs = [
                    Document(
                        page_content=doc.content,
                        metadata=doc.metadata or {},
                    )
                    for doc in existing_docs
                ]
            else:
                _cached_content = file.data.get("content", "") if file.data else ""
                if _cached_content:
                    docs = [
                        Document(
                            page_content=_cached_content,
                            metadata={
                                **file.meta,
                                "name": file.filename,
                                "created_by": file.user_id,
                                "file_id": file.id,
                                "source": file.filename,
                            },
                        )
                    ]
                else:
                    # Content is empty (e.g. uploaded with process=false),
                    # fall through to file loading below
                    docs = None
            text_content = file.data.get("content", "") if file.data else ""
        else:
            # Re-extract with the KB's document profile engine
            log.info(
                f"Re-extracting file {file.id} with engine "
                f"{doc_profile.content_extraction_engine}"
            )
            docs, text_content = None, None

    if docs is None:
        # Load and process file (or re-extract with custom profile)
        file_path = file.path
        if file_path:
            file_path = Storage.get_file(file_path)
            # Use doc_profile if available, fallback to global config
            pc = (doc_profile.config or {}) if doc_profile else {}
            cfg = app.state.config
            _engine = (
                doc_profile.content_extraction_engine
                if doc_profile
                else cfg.CONTENT_EXTRACTION_ENGINE
            )

            if _engine == "llm_vision":
                from open_webui.retrieval.loaders.llm_vision import LLMVisionLoader

                vision_loader = LLMVisionLoader(
                    app=app,
                    model_id=pc.get("llm_vision_model", ""),
                    prompt=pc.get("llm_vision_prompt", ""),
                    normalize_headings=pc.get("llm_vision_normalize_headings", True),
                )
                # timeout=None: 대용량 PDF 는 정상적으로 수십 분 걸릴 수 있으므로
                # 고정 wall-clock cap 을 두지 않는다. 로더 내부 per-call timeout 이 제어.
                docs = _run_async_safe(
                    vision_loader.aload(
                        file.filename,
                        file.meta.get("content_type"),
                        file_path,
                    ),
                    timeout=None,
                )
            else:
                loader = Loader(
                    engine=_engine,
                    TIKA_SERVER_URL=_pc_get(pc, "tika_server_url", cfg.TIKA_SERVER_URL),
                    DOCLING_SERVER_URL=_pc_get(
                        pc, "docling_server_url", cfg.DOCLING_SERVER_URL
                    ),
                    PDF_EXTRACT_IMAGES=doc_profile.pdf_extract_images
                    if doc_profile
                    else cfg.PDF_EXTRACT_IMAGES,
                    DOCUMENT_INTELLIGENCE_ENDPOINT=_pc_get(
                        pc,
                        "document_intelligence_endpoint",
                        cfg.DOCUMENT_INTELLIGENCE_ENDPOINT,
                    ),
                    DOCUMENT_INTELLIGENCE_KEY=_pc_get(
                        pc, "document_intelligence_key", cfg.DOCUMENT_INTELLIGENCE_KEY
                    ),
                    DOCUMENT_INTELLIGENCE_HIGH_RESOLUTION=_pc_get(
                        pc, "document_intelligence_high_resolution", False
                    ),
                    MISTRAL_OCR_API_KEY=_pc_get(
                        pc, "mistral_ocr_api_key", cfg.MISTRAL_OCR_API_KEY
                    ),
                    DOCUMENT_AI_PROJECT_ID=_pc_get(
                        pc, "document_ai_project_id", cfg.DOCUMENT_AI_PROJECT_ID
                    ),
                    DOCUMENT_AI_LOCATION=_pc_get(
                        pc, "document_ai_location", cfg.DOCUMENT_AI_LOCATION
                    ),
                    DOCUMENT_AI_PROCESSOR_ID=_pc_get(
                        pc, "document_ai_processor_id", cfg.DOCUMENT_AI_PROCESSOR_ID
                    ),
                    DOCUMENT_AI_PROCESSOR_VERSION=_pc_get(
                        pc,
                        "document_ai_processor_version",
                        cfg.DOCUMENT_AI_PROCESSOR_VERSION,
                    ),
                    DOCUMENT_AI_SERVICE_ACCOUNT_KEY=_pc_get(
                        pc,
                        "document_ai_service_account_key",
                        cfg.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
                    ),
                    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY=cfg.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
                )
                docs = loader.load(
                    file.filename, file.meta.get("content_type"), file_path
                )
            docs = [
                Document(
                    page_content=doc.page_content,
                    metadata={
                        **doc.metadata,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
                for doc in docs
            ]
        else:
            docs = [
                Document(
                    page_content=file.data.get("content", ""),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
            ]
        text_content = "\n\n".join([doc.page_content for doc in docs])

    # Clean extraction artifacts from all engines
    if docs:
        import re

        _artifact_pattern = re.compile(
            r"<!--\s*(?:PageBreak|PageNumber|PageHeader|PageFooter)"
            r'(?:="[^"]*")?\s*-->\s*',
            re.IGNORECASE,
        )
        for doc in docs:
            doc.page_content = _artifact_pattern.sub("", doc.page_content).strip()
        if text_content:
            text_content = _artifact_pattern.sub("", text_content).strip()

    return docs, text_content, None


def _generate_file_summary_sync(
    app, text_content: str, filename: str, model_override: Optional[str] = None
) -> Optional[str]:
    """
    파일 내용으로 요약 생성 (적응형 청크 샘플링).

    - 6,000자 이하: 전체 내용 직접 사용
    - 초과 시: 앞/중간/뒤 섹션에서 균등 샘플링 후 합산 8,000자 이내로 제한
    - Task Model이 설정되지 않은 경우 None 반환
    - model_override: KB별 요약 모델 오버라이드
    """
    MAX_DIRECT_CHARS = 6000
    MAX_SAMPLE_CHARS = 8000
    CHUNK_SIZE_CHARS = 1500  # 샘플링 단위 (토큰 기준 ~375 토큰)
    CHUNKS_PER_SECTION = 2  # 앞/중/뒤 각 섹션당 샘플 수

    try:
        # Task Model 결정.
        # 주의: app.state.MODELS 는 request 핸들러에서 lazy 로딩되므로 백그라운드
        # 파일 처리 시점엔 비어있을 수 있다. 따라서 'in models' 로 게이트하지 않고
        # 설정값(또는 override) 의 존재만 확인한 뒤 create_llm_from_app 에 위임한다
        # (해당 함수는 MODELS 가 비어도 OPENAI_API_CONFIGS 로 모델을 resolve 하는
        # fallback 을 가진다 — utils/llm.py:get_model_config_from_app).
        models = getattr(app.state, "MODELS", {})

        task_model_id = None
        if model_override and (not models or model_override in models):
            task_model_id = model_override
        else:
            task_model = app.state.config.TASK_MODEL
            task_model_external = app.state.config.TASK_MODEL_EXTERNAL
            # external 우선, 그다음 내부 task model. MODELS 가 채워져 있으면 검증에
            # 활용하되, 비어있으면 설정값을 그대로 신뢰한다.
            if task_model_external and (not models or task_model_external in models):
                task_model_id = task_model_external
            elif task_model and (not models or task_model in models):
                task_model_id = task_model

        if not task_model_id:
            log.info("Task model not configured — skipping file summary generation")
            return None

        # 적응형 샘플링
        if len(text_content) <= MAX_DIRECT_CHARS:
            text_for_summary = text_content
            is_partial = False
        else:
            chunks = [
                text_content[i : i + CHUNK_SIZE_CHARS]
                for i in range(0, len(text_content), CHUNK_SIZE_CHARS)
            ]
            n = len(chunks)
            if n <= CHUNKS_PER_SECTION * 3:
                sampled = chunks
            else:
                front = list(range(CHUNKS_PER_SECTION))
                mid_start = max(CHUNKS_PER_SECTION, n // 2 - CHUNKS_PER_SECTION // 2)
                middle = list(
                    range(
                        mid_start,
                        min(mid_start + CHUNKS_PER_SECTION, n - CHUNKS_PER_SECTION),
                    )
                )
                back = list(range(n - CHUNKS_PER_SECTION, n))
                indices = sorted(set(front + middle + back))
                sampled = [chunks[i] for i in indices]
            text_for_summary = "\n---\n".join(sampled)[:MAX_SAMPLE_CHARS]
            is_partial = True

        partial_note = (
            "\n(아래는 문서의 주요 발췌 내용입니다)\n\n" if is_partial else "\n\n"
        )
        prompt = (
            f"파일명: {filename}{partial_note}"
            f"{text_for_summary}\n\n"
            "위 내용을 바탕으로 이 문서의 핵심 내용을 한국어로 3~5문장으로 요약해주세요. "
            "요약만 출력하고 다른 텍스트는 포함하지 마세요."
        )

        from extension_modules.utils.llm import create_llm_from_app
        from langchain_core.messages import HumanMessage

        llm = create_llm_from_app(app, task_model_id, temperature=0.3)
        if not llm:
            return None

        response = _run_async_safe(
            llm.ainvoke([HumanMessage(content=prompt)]),
            timeout=120,
        )
        summary = (response.content or "").strip()
        log.info(
            f"Generated summary for {filename} ({len(text_content):,} chars): {summary[:80]}…"
        )
        return summary

    except asyncio.TimeoutError:
        log.warning(
            f"File summary generation timed out for {filename} (120s) — skipping summary"
        )
        return None

    except Exception as e:
        log.error(
            f"Failed to generate file summary for {filename}: "
            f"[{type(e).__name__}] {e or repr(e)}"
        )
        return None


def _run_file_processing_sync(
    app,
    file_id: str,
    user_id: str,
    collection_name: Optional[str],
    content: Optional[str],
):
    """
    Synchronous file processing function.
    Runs entirely in a separate thread to avoid blocking the event loop.
    """
    import time

    from open_webui.models.files import Files

    def update_processing_status(status_update: dict):
        """Update processing status in file.data."""
        try:
            file = Files.get_file_by_id(file_id)
            if file:
                current_data = file.data or {}
                current_job = current_data.get("processing_job", {})
                current_job.update(status_update)
                current_data["processing_job"] = current_job
                Files.update_file_data_by_id(file_id, current_data)
        except Exception as e:
            log.error(f"Failed to update processing status: {e}")

    result_data = {
        "success": False,
        "file_id": file_id,
        "filename": None,
        "collection_name": None,
        "error": None,
    }

    try:
        file = Files.get_file_by_id(file_id)
        if not file:
            update_processing_status(
                {
                    "status": "failed",
                    "error": "File not found",
                    "completed_at": int(time.time()),
                }
            )
            result_data["error"] = "File not found"
            return result_data

        result_data["filename"] = file.filename

        update_processing_status(
            {
                "status": "processing",
                "stage": "loading",
                "progress": 10,
            }
        )

        actual_collection_name = collection_name or f"file-{file.id}"

        # Resolve profiles for this knowledge base
        knowledge_id = (
            collection_name
            if collection_name and not collection_name.startswith("file-")
            else None
        )
        if not knowledge_id:
            # Background processing: check pending_knowledge_id
            knowledge_id = (
                file.meta.get("pending_knowledge_id") if file and file.meta else None
            )
        doc_profile = get_doc_profile_for_knowledge(
            app,
            knowledge_id,
            filename=file.filename if file else None,
            content_type=(file.meta or {}).get("content_type") if file else None,
        )
        log.info(
            f"[background] knowledge_id={knowledge_id}, "
            f"doc_profile={doc_profile.name if doc_profile else None}, "
            f"engine={doc_profile.content_extraction_engine if doc_profile else None}"
        )

        # Load file content (blocking operation)
        docs, text_content, error = _load_file_content_sync(
            app,
            file_id,
            collection_name,
            content,
            doc_profile=doc_profile,
        )

        if error:
            update_processing_status(
                {
                    "status": "failed",
                    "error": error,
                    "completed_at": int(time.time()),
                }
            )
            result_data["error"] = error
            return result_data

        update_processing_status(
            {
                "stage": "chunking",
                "progress": 40,
            }
        )

        # Save content to file
        Files.update_file_data_by_id(
            file.id,
            {"content": text_content},
        )

        hash = calculate_sha256_string(text_content)
        Files.update_file_hash_by_id(file.id, hash)

        # === Stage 3: Text Guardrails (block-only) ===
        file_source = file.meta.get("source", "") if file.meta else ""
        guardrail_scopes = getattr(
            app.state.config,
            "FILE_GUARDRAIL_SCOPES",
            ["chat", "knowledge", "project"],
        )
        guardrail_applicable = (
            is_feature_enabled(app, "file_guardrail")
            and getattr(app.state.config, "FILE_GUARDRAIL_ENABLED", False)
            and (not file_source or file_source in guardrail_scopes)
        )

        if guardrail_applicable:
            guardrail_ids = getattr(app.state.config, "FILE_GUARDRAIL_IDS", [])
            if guardrail_ids and text_content:
                text_result = _run_async_safe(
                    run_text_guardrails(app, text_content, guardrail_ids)
                )
                if text_result.action == "block":
                    from open_webui.utils.file_guardrails import format_guardrail_error

                    error_msg = format_guardrail_error(text_result.details)
                    Files.update_file_metadata_by_id(
                        file.id,
                        {
                            "guardrail_blocked": True,
                            "guardrail_details": text_result.details,
                            "pending_knowledge_id": None,
                        },
                    )
                    update_processing_status(
                        {
                            "status": "failed",
                            "error": error_msg,
                            "completed_at": int(time.time()),
                        }
                    )
                    result_data["error"] = error_msg
                    return result_data

        # === Stage 4: Document Classification (non-fatal) ===
        if (
            guardrail_applicable
            and getattr(
                app.state.config,
                "FILE_GUARDRAIL_CLASSIFICATION_ENABLED",
                False,
            )
            and text_content
        ):
            try:
                cls_result = _run_async_safe(run_classification(app, text_content))
                Files.update_file_metadata_by_id(
                    file.id, {"classification": cls_result.details}
                )
                if cls_result.action == "block":
                    category = (
                        cls_result.details.get("category", "UNKNOWN")
                        if cls_result.details
                        else "UNKNOWN"
                    )
                    Files.update_file_metadata_by_id(
                        file.id, {"pending_knowledge_id": None}
                    )
                    update_processing_status(
                        {
                            "status": "failed",
                            "error": f"File classified as {category}: upload blocked",
                            "completed_at": int(time.time()),
                        }
                    )
                    result_data["error"] = (
                        f"File classified as {category}: upload blocked"
                    )
                    return result_data
            except Exception as e:
                log.warning(f"Document classification failed (background): {e}")
                Files.update_file_metadata_by_id(
                    file.id,
                    {
                        "classification": {
                            "category": "UNCLASSIFIED",
                            "error": str(e),
                        }
                    },
                )

        update_processing_status(
            {
                "stage": "embedding",
                "progress": 60,
            }
        )

        if not app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            # Create a mock request object for save_docs_to_vector_db
            class MockRequest:
                def __init__(self, app):
                    self.app = app

            mock_request = MockRequest(app)

            # Create mock user
            from open_webui.models.users import Users

            user = Users.get_user_by_id(user_id)

            # timeout=None: 대용량 문서(수백 페이지)는 청킹+임베딩+벡터저장에
            # 수 분 이상 걸릴 수 있다. 고정 300초 cap 은 추출까지 끝낸 작업을 저장
            # 단계에서 폐기시키므로 두지 않는다 (task_queue wrapper 가 상위 안전망).
            result = _run_async_safe(
                save_docs_to_vector_db(
                    mock_request,
                    docs=docs,
                    collection_name=actual_collection_name,
                    metadata={
                        "file_id": file.id,
                        "name": file.filename,
                        "hash": hash,
                    },
                    overwrite=True,
                    add=(True if collection_name else False),
                    user=user,
                    doc_profile=doc_profile,
                    # sync 경로와 동일 게이트: 영속 KB(직접 collection 또는
                    # pending_knowledge_id)만 enrichment. knowledge_id 가 None 으로
                    # 풀리는 휘발성 background 업로드는 skip (청크당 fan-out 비용 회피).
                    enable_enrichment=knowledge_id is not None,
                ),
                timeout=None,
            )

            if result:
                Files.update_file_metadata_by_id(
                    file.id,
                    {"collection_name": actual_collection_name},
                )

        # ── 파일 요약 생성 (적응형 청크 샘플링) ────────────────────────────────
        # KB별 설정에서 enable_file_summary 확인
        _enable_file_summary = True  # 기본값: 활성화
        _file_summary_model = None
        # deep_summary_mode: "off" | "ingest"(즉시 생성) | "on_demand"(질의 시 캐시)
        _deep_summary_mode = "on_demand"
        if knowledge_id:
            from open_webui.models.knowledge import Knowledges as _KnowledgesForSummary

            _kb = _KnowledgesForSummary.get_knowledge_by_id(knowledge_id)
            if _kb and _kb.meta:
                _ss = _kb.meta.get("search_settings") or {}
                if _ss.get("enable_file_summary") is not None:
                    _enable_file_summary = _ss["enable_file_summary"]
                if _ss.get("file_summary_model"):
                    _file_summary_model = _ss["file_summary_model"]
                if _ss.get("deep_summary_mode"):
                    _deep_summary_mode = _ss["deep_summary_mode"]

        if text_content and _enable_file_summary:
            update_processing_status({"stage": "summarizing", "progress": 90})
            summary = _generate_file_summary_sync(
                app, text_content, file.filename, model_override=_file_summary_model
            )
            if summary:
                Files.update_file_metadata_by_id(file.id, {"summary": summary})

        # ── 심층 요약 (deep summary) — 전문 map-reduce, 무손실 ────────────────
        # mode=="ingest" 일 때만 인제스트 시점에 생성(전체 text_content 사용).
        # "on_demand" 는 질의 시 summarize_document 도구가 생성·캐시한다.
        if text_content and _deep_summary_mode == "ingest":
            update_processing_status({"stage": "deep_summarizing", "progress": 93})
            try:
                from open_webui.retrieval.deep_summary import generate_deep_summary

                deep = _run_async_safe(
                    generate_deep_summary(
                        app,
                        text_content,
                        file.filename,
                        model_override=_file_summary_model,
                    ),
                    timeout=1800,
                )
                if deep:
                    Files.update_file_metadata_by_id(file.id, {"deep_summary": deep})
            except Exception as e:
                log.warning(
                    f"Deep summary generation failed for {file.filename}: "
                    f"[{type(e).__name__}] {e}"
                )

        update_processing_status(
            {
                "status": "completed",
                "stage": None,
                "progress": 100,
                "completed_at": int(time.time()),
                "collection_name": actual_collection_name,
            }
        )

        log.info(f"Background file processing completed for {file_id}")

        # Check if file should be auto-added to a knowledge base
        file = Files.get_file_by_id(file_id)
        log.debug(f"File meta after processing: {file.meta if file else None}")
        pending_knowledge_id = (
            file.meta.get("pending_knowledge_id") if file and file.meta else None
        )

        # Case 1 (신규 흐름): collection_name이 이미 KB id로 전달된 경우
        # 처리는 KB 컬렉션에 직접 완료됨 → file_ids 업데이트만 수행
        if actual_collection_name and not actual_collection_name.startswith("file-"):
            try:
                from open_webui.models.knowledge import Knowledges

                Knowledges.add_file_id_to_knowledge(
                    id=actual_collection_name, file_id=file_id
                )
                # pending_knowledge_id 클리어 (혹시 set되어 있을 경우)
                Files.update_file_metadata_by_id(
                    file_id, {"pending_knowledge_id": None}
                )
                log.info(
                    f"File {file_id} added to knowledge base {actual_collection_name} (direct)"
                )
            except Exception as e:
                log.error(f"Failed to add file to knowledge base file_ids: {e}")
                raise

        # Case 2 (레거시): 이미 처리 중인 파일을 KB에 추가한 엣지 케이스
        # file-{id} 컬렉션에 처리된 후 KB 컬렉션에 재처리 필요
        elif pending_knowledge_id:
            log.info(
                f"Auto-adding file {file_id} to knowledge base {pending_knowledge_id} (legacy)"
            )
            try:
                from open_webui.models.knowledge import Knowledges

                knowledge = Knowledges.get_knowledge_by_id(pending_knowledge_id)
                if knowledge:
                    # First, save to knowledge collection (vector DB)
                    # Only add to file_ids after successful vector DB insertion
                    if (
                        actual_collection_name != pending_knowledge_id
                        and not app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
                    ):
                        # Delete existing chunks then save new ones
                        # in a single asyncio.run() to avoid event loop cleanup issues
                        class MockRequest:
                            def __init__(self, app):
                                self.app = app

                        mock_request = MockRequest(app)
                        from open_webui.models.users import Users

                        user = Users.get_user_by_id(user_id)

                        async def _delete_and_save():
                            knowledge_svc = SearchEngineKnowledge(
                                app=app,
                                collection_name=pending_knowledge_id,
                                vector_dim=get_effective_embedding_dimension(app),
                            )
                            await knowledge_svc.delete_by_file_id(file.id)
                            await save_docs_to_vector_db(
                                mock_request,
                                docs=docs,
                                collection_name=pending_knowledge_id,
                                metadata={
                                    "file_id": file.id,
                                    "name": file.filename,
                                    "hash": hash,
                                },
                                overwrite=False,
                                add=True,
                                user=user,
                                knowledge_id=pending_knowledge_id,
                                doc_profile=doc_profile,
                            )

                        # timeout=None: legacy auto-add 의 KB 저장도 대용량 문서에서는
                        # 청킹+(contextual chunking LLM)+임베딩+벡터저장에 5분 이상 걸린다.
                        # 고정 300초 cap 은 추출까지 끝낸 작업을 폐기시킨다 (task_queue 안전망).
                        _run_async_safe(_delete_and_save(), timeout=None)
                        log.info(
                            f"Saved docs to knowledge collection {pending_knowledge_id}"
                        )

                    # Add to knowledge's file_ids atomically (prevents race condition)
                    Knowledges.add_file_id_to_knowledge(
                        id=pending_knowledge_id, file_id=file_id
                    )

                    # Clear pending_knowledge_id
                    Files.update_file_metadata_by_id(
                        file_id, {"pending_knowledge_id": None}
                    )
                    log.info(
                        f"File {file_id} auto-added to knowledge base {pending_knowledge_id}"
                    )

            except Exception as e:
                log.error(f"Failed to auto-add file to knowledge base: {e}")
                raise  # Re-raise to mark the overall process as failed

        result_data["success"] = True
        result_data["collection_name"] = actual_collection_name
        # KB id를 알림에 전달 (직접 처리 또는 legacy 자동 추가 둘 다)
        if actual_collection_name and not actual_collection_name.startswith("file-"):
            result_data["pending_knowledge_id"] = actual_collection_name
        else:
            result_data["pending_knowledge_id"] = pending_knowledge_id
        return result_data

    except Exception as e:
        # str(e) 가 빈 예외(예: asyncio.TimeoutError)도 진단 가능하도록 타입명 + traceback 기록
        err_msg = str(e) or type(e).__name__
        log.error(f"Background file processing failed: {err_msg}", exc_info=True)
        update_processing_status(
            {
                "status": "failed",
                "error": err_msg,
                "completed_at": int(time.time()),
            }
        )

        # 실패해도 KB에 파일 연결 (UI에서 실패 상태 표시 + 재시도/삭제 가능)
        try:
            file_meta = Files.get_file_by_id(file_id)
            pending_kb_id = (
                file_meta.meta.get("pending_knowledge_id")
                if file_meta and file_meta.meta
                else None
            )
            if pending_kb_id:
                Knowledges.add_file_id_to_knowledge(id=pending_kb_id, file_id=file_id)
            Files.update_file_metadata_by_id(file_id, {"pending_knowledge_id": None})
        except Exception:
            pass

        file = Files.get_file_by_id(file_id)
        result_data["error"] = str(e)
        result_data["filename"] = file.filename if file else "Unknown"
        return result_data

    finally:
        # 안전망: 정상/예외 경로는 위에서 이미 completed/failed 를 기록하지만,
        # 혹시 비종료 상태로 try 블록을 빠져나가는 경로가 남더라도 UI 스피너가
        # 영원히 도는 것을 막는다. (단, loader.load() 등에서 스레드가 완전히
        # 블록되는 '진짜 hang' 은 finally 도 실행되지 않으므로 워커 타임아웃/
        # 무진전 워치독으로 별도 차단해야 한다.)
        try:
            _f = Files.get_file_by_id(file_id)
            _job = (_f.data or {}).get("processing_job", {}) if _f else {}
            if _job.get("status") not in ("completed", "failed"):
                update_processing_status(
                    {
                        "status": "failed",
                        "error": _job.get("error")
                        or "Processing ended without a terminal status",
                        "completed_at": int(time.time()),
                    }
                )
        except Exception as _e:
            log.error(f"Failed to finalize processing status: {_e}")


async def _run_file_processing_background(
    app,
    file_id: str,
    user_id: str,
    collection_name: Optional[str],
    content: Optional[str],
    batch_id: Optional[str] = None,
    client_session_id: Optional[str] = None,
):
    """
    Async wrapper that runs sync processing in thread pool and sends notifications.
    Overall 10-minute timeout ensures workers are never stuck indefinitely.
    """
    import time

    from open_webui.models.files import Files
    from open_webui.socket.main import send_notification_to_user

    OVERALL_TIMEOUT = int(os.environ.get("FILE_PROCESSING_TIMEOUT", "600"))  # 10분

    # Run the sync processing in thread pool executor with overall timeout
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                _file_processing_executor,
                _run_file_processing_sync,
                app,
                file_id,
                user_id,
                collection_name,
                content,
            ),
            timeout=OVERALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error(f"File processing timed out after {OVERALL_TIMEOUT}s for {file_id}")
        # Mark the job as failed in DB so UI reflects the timeout
        try:
            file = Files.get_file_by_id(file_id)
            if file:
                current_data = file.data or {}
                current_data["processing_job"] = {
                    **current_data.get("processing_job", {}),
                    "status": "failed",
                    "error": f"Processing timed out after {OVERALL_TIMEOUT}s",
                    "completed_at": int(time.time()),
                }
                Files.update_file_data_by_id(file_id, current_data)
                Files.update_file_metadata_by_id(
                    file_id, {"pending_knowledge_id": None}
                )
        except Exception:
            log.exception(f"Failed to update timeout status for {file_id}")

        result = {
            "success": False,
            "file_id": file_id,
            "filename": (file.filename if file else "Unknown"),
            "collection_name": None,
            "error": f"Processing timed out after {OVERALL_TIMEOUT}s",
        }

    # Send notification based on result
    if result["success"]:
        knowledge_id = result.get("pending_knowledge_id")
        message = f"'{result['filename']}' 파일 처리가 완료되었습니다."
        if knowledge_id:
            message = f"'{result['filename']}' 파일이 지식기반에 추가되었습니다."

        await send_notification_to_user(
            user_id=user_id,
            event_type="file-processing-completed",
            data={
                "file_id": result["file_id"],
                "filename": result["filename"],
                "collection_name": result["collection_name"],
                "knowledge_id": knowledge_id,
                "message": message,
                "batch_id": batch_id,
                "client_session_id": client_session_id,
            },
        )
    else:
        await send_notification_to_user(
            user_id=user_id,
            event_type="file-processing-failed",
            data={
                "file_id": result["file_id"],
                "filename": result["filename"] or "Unknown",
                "error": result["error"],
                "message": f"'{result['filename'] or 'Unknown'}' 파일 처리가 실패했습니다: {result['error']}",
                "batch_id": batch_id,
                "client_session_id": client_session_id,
            },
        )


@router.post("/process/file")
async def process_file(
    request: Request,
    form_data: ProcessFileForm,
    user=Depends(get_verified_user),
):
    import time

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # Check if processing is already running
    current_job = (file.data or {}).get("processing_job", {})
    if current_job.get("status") == "processing":
        return {
            "status": False,
            "message": "File processing is already running",
            "background": True,
            "processing_status": FileProcessingStatus(**current_job).model_dump(),
        }

    if form_data.background:
        # Initialize job status
        job_status = {
            "status": "pending",
            "started_at": int(time.time()),
            "completed_at": None,
            "stage": None,
            "progress": 0,
            "error": None,
            "collection_name": None,
        }

        # Save initial status
        Files.update_file_data_by_id(
            file.id,
            {**(file.data or {}), "processing_job": job_status},
        )

        # Redis 큐가 있으면 큐에 발행 (내부 consumer가 소비)
        task_queue = getattr(request.app.state, "task_queue", None)

        if task_queue and not isinstance(task_queue, InProcessQueue):
            from open_webui.services.task_queue import TaskMessage

            await task_queue.publish(
                TaskMessage(
                    task_type="file_processing",
                    payload={
                        "file_id": form_data.file_id,
                        "collection_name": form_data.collection_name,
                        "user_id": user.id,
                        "content": form_data.content,
                        "batch_id": form_data.batch_id,
                        "client_session_id": form_data.client_session_id,
                    },
                )
            )
            job_status["status"] = "queued"
            Files.update_file_data_by_id(
                file.id,
                {**(file.data or {}), "processing_job": job_status},
            )
            return {
                "status": True,
                "message": "파일 처리가 백그라운드 큐에 등록되었습니다.",
                "background": True,
                "processing_status": FileProcessingStatus(**job_status).model_dump(),
            }

        # Redis 없으면 기존 ThreadPoolExecutor 폴백
        task = asyncio.create_task(
            _run_file_processing_background(
                app=request.app,
                file_id=form_data.file_id,
                user_id=user.id,
                collection_name=form_data.collection_name,
                content=form_data.content,
                batch_id=form_data.batch_id,
                client_session_id=form_data.client_session_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return {
            "status": True,
            "message": "파일 처리가 백그라운드에서 시작되었습니다.",
            "background": True,
            "processing_status": FileProcessingStatus(**job_status).model_dump(),
        }

    # Synchronous processing (original logic)
    try:
        collection_name = form_data.collection_name

        if collection_name is None:
            collection_name = f"file-{file.id}"

        # Resolve profiles for this knowledge base
        _sync_knowledge_id = (
            form_data.collection_name
            if form_data.collection_name
            and not form_data.collection_name.startswith("file-")
            else None
        )
        doc_profile = get_doc_profile_for_knowledge(
            request.app,
            _sync_knowledge_id,
            filename=file.filename if file else None,
            content_type=(file.meta or {}).get("content_type") if file else None,
        )

        # Look up file-level filter metadata from knowledge base
        extra_metadata = None
        if form_data.collection_name and not form_data.collection_name.startswith(
            "file-"
        ):
            kb = Knowledges.get_knowledge_by_id(form_data.collection_name)
            if kb and kb.data:
                file_metadata_map = kb.data.get("file_metadata", {})
                extra_metadata = file_metadata_map.get(form_data.file_id) or None

        docs = None
        text_content = None

        if form_data.content:
            # Update the content in the file
            # Usage: /files/{file_id}/data/content/update, /files/ (audio file upload pipeline)

            try:
                # /files/{file_id}/data/content/update
                file_knowledge = SearchEngineKnowledge(
                    app=request.app,
                    collection_name=f"file-{file.id}",
                    vector_dim=get_effective_embedding_dimension(request.app),
                )
                await file_knowledge.delete_by_collection()
            except Exception:
                # Audio file upload pipeline
                pass

            docs = [
                Document(
                    page_content=form_data.content.replace("<br/>", "\n"),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
            ]

            text_content = form_data.content
        elif form_data.collection_name:
            # Check if KB has a custom document profile requiring re-extraction
            _force_reextract = (
                doc_profile
                and doc_profile.content_extraction_engine
                and doc_profile.content_extraction_engine
                != (request.app.state.config.CONTENT_EXTRACTION_ENGINE or "")
            )
            log.info(
                f"[process_file sync] collection={form_data.collection_name}, "
                f"doc_profile={doc_profile.name if doc_profile else None}, "
                f"engine={doc_profile.content_extraction_engine if doc_profile else None}, "
                f"global_engine={request.app.state.config.CONTENT_EXTRACTION_ENGINE}, "
                f"force_reextract={_force_reextract}"
            )

            if not _force_reextract:
                # Use cached content
                file_knowledge = SearchEngineKnowledge(
                    app=request.app,
                    collection_name=f"file-{file.id}",
                    vector_dim=get_effective_embedding_dimension(request.app),
                )
                existing_docs = await file_knowledge.query_by_metadata(
                    {"file_id": file.id}
                )

                if existing_docs:
                    docs = [
                        Document(
                            page_content=doc.content,
                            metadata=doc.metadata or {},
                        )
                        for doc in existing_docs
                    ]
                else:
                    docs = [
                        Document(
                            page_content=file.data.get("content", ""),
                            metadata={
                                **file.meta,
                                "name": file.filename,
                                "created_by": file.user_id,
                                "file_id": file.id,
                                "source": file.filename,
                            },
                        )
                    ]

                text_content = file.data.get("content", "")
            else:
                log.info(
                    f"Re-extracting file {file.id} with engine "
                    f"{doc_profile.content_extraction_engine}"
                )
                docs = None
                text_content = None

        if docs is None:
            # Process the file and save the content
            # Usage: /files/
            file_path = file.path
            if file_path:
                file_path = Storage.get_file(file_path)
                # Use doc_profile if available, fallback to global config
                _pc = (doc_profile.config or {}) if doc_profile else {}
                _cfg = request.app.state.config
                _engine = (
                    doc_profile.content_extraction_engine
                    if doc_profile
                    else _cfg.CONTENT_EXTRACTION_ENGINE
                )

                if _engine == "llm_vision":
                    from open_webui.retrieval.loaders.llm_vision import LLMVisionLoader

                    vision_loader = LLMVisionLoader(
                        app=request.app,
                        model_id=_pc.get("llm_vision_model", ""),
                        prompt=_pc.get("llm_vision_prompt", ""),
                        normalize_headings=_pc.get(
                            "llm_vision_normalize_headings", True
                        ),
                    )
                    docs = await vision_loader.aload(
                        file.filename,
                        file.meta.get("content_type"),
                        file_path,
                    )
                else:
                    loader = Loader(
                        engine=_engine,
                        TIKA_SERVER_URL=_pc_get(
                            _pc, "tika_server_url", _cfg.TIKA_SERVER_URL
                        ),
                        DOCLING_SERVER_URL=_pc_get(
                            _pc, "docling_server_url", _cfg.DOCLING_SERVER_URL
                        ),
                        PDF_EXTRACT_IMAGES=doc_profile.pdf_extract_images
                        if doc_profile
                        else _cfg.PDF_EXTRACT_IMAGES,
                        DOCUMENT_INTELLIGENCE_ENDPOINT=_pc_get(
                            _pc,
                            "document_intelligence_endpoint",
                            _cfg.DOCUMENT_INTELLIGENCE_ENDPOINT,
                        ),
                        DOCUMENT_INTELLIGENCE_KEY=_pc_get(
                            _pc,
                            "document_intelligence_key",
                            _cfg.DOCUMENT_INTELLIGENCE_KEY,
                        ),
                        DOCUMENT_INTELLIGENCE_HIGH_RESOLUTION=_pc_get(
                            _pc, "document_intelligence_high_resolution", False
                        ),
                        MISTRAL_OCR_API_KEY=_pc_get(
                            _pc, "mistral_ocr_api_key", _cfg.MISTRAL_OCR_API_KEY
                        ),
                        DOCUMENT_AI_PROJECT_ID=_pc_get(
                            _pc, "document_ai_project_id", _cfg.DOCUMENT_AI_PROJECT_ID
                        ),
                        DOCUMENT_AI_LOCATION=_pc_get(
                            _pc, "document_ai_location", _cfg.DOCUMENT_AI_LOCATION
                        ),
                        DOCUMENT_AI_PROCESSOR_ID=_pc_get(
                            _pc,
                            "document_ai_processor_id",
                            _cfg.DOCUMENT_AI_PROCESSOR_ID,
                        ),
                        DOCUMENT_AI_PROCESSOR_VERSION=_pc_get(
                            _pc,
                            "document_ai_processor_version",
                            _cfg.DOCUMENT_AI_PROCESSOR_VERSION,
                        ),
                        DOCUMENT_AI_SERVICE_ACCOUNT_KEY=_pc_get(
                            _pc,
                            "document_ai_service_account_key",
                            _cfg.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
                        ),
                        GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY=_cfg.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
                    )
                    # Offload synchronous extraction to a worker thread so it
                    # does not block the event loop. Without this, concurrent
                    # chat-file uploads serialize at extraction and the later
                    # requests can hit a proxy/gateway timeout.
                    docs = await asyncio.to_thread(
                        loader.load,
                        file.filename,
                        file.meta.get("content_type"),
                        file_path,
                    )

                docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={
                            **doc.metadata,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                    for doc in docs
                ]
            else:
                docs = [
                    Document(
                        page_content=file.data.get("content", ""),
                        metadata={
                            **file.meta,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                ]
            text_content = "\n\n".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {text_content}")
        Files.update_file_data_by_id(
            file.id,
            {"content": text_content},
        )

        hash = calculate_sha256_string(text_content)
        Files.update_file_hash_by_id(file.id, hash)

        # === Stage 3: Text Guardrails (block-only) ===
        file_source = file.meta.get("source", "") if file.meta else ""
        guardrail_scopes = getattr(
            request.app.state.config,
            "FILE_GUARDRAIL_SCOPES",
            ["chat", "knowledge", "project"],
        )
        guardrail_applicable = (
            is_feature_enabled(request.app, "file_guardrail")
            and getattr(request.app.state.config, "FILE_GUARDRAIL_ENABLED", False)
            and (not file_source or file_source in guardrail_scopes)
        )
        if guardrail_applicable:
            guardrail_ids = getattr(request.app.state.config, "FILE_GUARDRAIL_IDS", [])
            if guardrail_ids and text_content:
                text_result = await run_text_guardrails(
                    request.app, text_content, guardrail_ids
                )
                if text_result.action == "block":
                    from open_webui.utils.file_guardrails import format_guardrail_error

                    error_msg = format_guardrail_error(text_result.details)

                    # 파일 삭제 (스토리지 + DB)
                    try:
                        if file.path:
                            Storage.delete_file(file.path)
                    except Exception as del_err:
                        log.warning(
                            f"Failed to delete blocked file from storage: {del_err}"
                        )
                    Files.delete_file_by_id(file.id)
                    log.info(
                        f"File {file.id} blocked and deleted by text guardrail: {error_msg}"
                    )

                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=ERROR_MESSAGES.DEFAULT(error_msg),
                    )

        # === Stage 4: Document Classification (non-fatal) ===
        if (
            guardrail_applicable
            and getattr(
                request.app.state.config,
                "FILE_GUARDRAIL_CLASSIFICATION_ENABLED",
                False,
            )
            and text_content
        ):
            try:
                cls_result = await run_classification(request.app, text_content)
                Files.update_file_metadata_by_id(
                    file.id, {"classification": cls_result.details}
                )
                if cls_result.action == "block":
                    category = (
                        cls_result.details.get("category", "UNKNOWN")
                        if cls_result.details
                        else "UNKNOWN"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=ERROR_MESSAGES.DEFAULT(
                            f"File classified as {category}: upload blocked"
                        ),
                    )
            except HTTPException:
                raise
            except Exception as e:
                log.warning(f"Document classification failed: {e}")
                Files.update_file_metadata_by_id(
                    file.id,
                    {
                        "classification": {
                            "category": "UNCLASSIFIED",
                            "error": str(e),
                        }
                    },
                )

        if not request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            # KB 컬렉션에 추가하는 경우, 해당 file_id의 기존 chunk를 먼저 삭제
            # (재처리/재업로드 시 orphan chunk 방지)
            if form_data.collection_name and not form_data.collection_name.startswith(
                "file-"
            ):
                try:
                    kb_knowledge = SearchEngineKnowledge(
                        app=request.app,
                        collection_name=collection_name,
                        vector_dim=get_effective_embedding_dimension(request.app),
                    )
                    await kb_knowledge.delete_by_file_id(file.id)
                except Exception as e:
                    log.warning(
                        f"Failed to clean existing chunks for file {file.id}: {e}"
                    )

            try:
                result = await save_docs_to_vector_db(
                    request,
                    docs=docs,
                    collection_name=collection_name,
                    metadata={
                        "file_id": file.id,
                        "name": file.filename,
                        "hash": hash,
                    },
                    add=(True if form_data.collection_name else False),
                    user=user,
                    extra_metadata=extra_metadata,
                    knowledge_id=form_data.collection_name
                    if form_data.collection_name
                    else None,
                    doc_profile=doc_profile,
                    # 휘발성 채팅 첨부(file-{id})는 enrichment skip — 청크당 chat LLM
                    # fan-out 으로 동기 업로드가 수 분 블록돼 첨부가 소실되던 문제 방지.
                    enable_enrichment=_collection_is_persistent_kb(
                        form_data.collection_name
                    ),
                )

                if result:
                    Files.update_file_metadata_by_id(
                        file.id,
                        {
                            "collection_name": collection_name,
                        },
                    )

                    return {
                        "status": True,
                        "collection_name": collection_name,
                        "filename": file.filename,
                        "content": text_content,
                    }
            except Exception as e:
                raise e
        else:
            return {
                "status": True,
                "collection_name": None,
                "filename": file.filename,
                "content": text_content,
            }

    except Exception as e:
        log.exception(e)
        if "No pandoc was found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.PANDOC_NOT_INSTALLED,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )


@router.get("/process/file/{file_id}/status")
def get_file_processing_status(
    file_id: str,
    user=Depends(get_verified_user),
):
    """Get the status of file processing job."""
    import time

    file = Files.get_file_by_id(file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    job_status = (file.data or {}).get("processing_job", {})
    if not job_status:
        return FileProcessingStatus(status="none")

    # Detect stale processing jobs (e.g. backend restarted during processing)
    if job_status.get("status") == "processing":
        started_at = job_status.get("started_at")
        if started_at and (int(time.time()) - started_at > 600):
            # Processing for over 10 minutes — mark as failed
            job_status["status"] = "failed"
            job_status["error"] = "Processing timed out (backend may have restarted)"
            job_status["completed_at"] = int(time.time())
            Files.update_file_data_by_id(
                file_id, {**(file.data or {}), "processing_job": job_status}
            )

    return FileProcessingStatus(**job_status)


class ProcessTextForm(BaseModel):
    name: str
    content: str
    collection_name: Optional[str] = None


@router.post("/process/text")
async def process_text(
    request: Request,
    form_data: ProcessTextForm,
    user=Depends(get_verified_user),
):
    collection_name = form_data.collection_name
    if collection_name is None:
        collection_name = calculate_sha256_string(form_data.content)

    docs = [
        Document(
            page_content=form_data.content,
            metadata={"name": form_data.name, "created_by": user.id},
        )
    ]
    text_content = form_data.content
    log.debug(f"text_content: {text_content}")

    result = await save_docs_to_vector_db(request, docs, collection_name, user=user)
    if result:
        return {
            "status": True,
            "collection_name": collection_name,
            "content": text_content,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(),
        )


@router.post("/process/youtube")
async def process_youtube_video(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = YoutubeLoader(
            form_data.url,
            language=request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            proxy_url=request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
        )

        docs = loader.load()
        content = "\n\n".join([doc.page_content for doc in docs])
        log.debug(f"text_content: {content}")

        await save_docs_to_vector_db(
            request,
            docs,
            collection_name,
            overwrite=True,
            user=user,
        )

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


@router.post("/process/web")
async def process_web(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = get_web_loader(
            form_data.url,
            verify_ssl=request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
        )
        docs = await loader.aload()
        content = "\n\n".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {content}")

        if not request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL:
            await save_docs_to_vector_db(
                request, docs, collection_name, overwrite=True, user=user
            )
        else:
            collection_name = None

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                    "source": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def search_web(
    request: Request,
    engine: str,
    query: str,
    result_count: Optional[int] = None,
    domain_filter_list: Optional[list] = None,
) -> list[SearchResult]:
    """Search the web using a search engine and return the results as a list of SearchResult objects.
    Will look for a search engine API key in environment variables in the following order:
    - SEARXNG_QUERY_URL
    - GOOGLE_PSE_API_KEY + GOOGLE_PSE_ENGINE_ID
    - BRAVE_SEARCH_API_KEY
    - KAGI_SEARCH_API_KEY
    - MOJEEK_SEARCH_API_KEY
    - BOCHA_SEARCH_API_KEY
    - SERPSTACK_API_KEY
    - SERPER_API_KEY
    - SERPLY_API_KEY
    - TAVILY_API_KEY
    - EXA_API_KEY
    - PERPLEXITY_API_KEY
    - SOUGOU_API_SID + SOUGOU_API_SK
    - SEARCHAPI_API_KEY + SEARCHAPI_ENGINE (by default `google`)
    - SERPAPI_API_KEY + SERPAPI_ENGINE (by default `google`)
    Args:
        query (str): The query to search for
        result_count (int, optional): Override for number of results. Defaults to admin config.
        domain_filter_list (list, optional): Override for domain filters. Defaults to admin config.
    """
    _result_count = (
        result_count
        if result_count is not None
        else request.app.state.config.WEB_SEARCH_RESULT_COUNT
    )
    _domain_filter = (
        domain_filter_list
        if domain_filter_list is not None
        else request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST
    )

    # TODO: add playwright to search the web
    if engine == "searxng":
        if request.app.state.config.SEARXNG_QUERY_URL:
            return search_searxng(
                request.app.state.config.SEARXNG_QUERY_URL,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No SEARXNG_QUERY_URL found in environment variables")
    elif engine == "google_pse":
        if (
            request.app.state.config.GOOGLE_PSE_API_KEY
            and request.app.state.config.GOOGLE_PSE_ENGINE_ID
        ):
            return search_google_pse(
                request.app.state.config.GOOGLE_PSE_API_KEY,
                request.app.state.config.GOOGLE_PSE_ENGINE_ID,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception(
                "No GOOGLE_PSE_API_KEY or GOOGLE_PSE_ENGINE_ID found in environment variables"
            )
    elif engine == "brave":
        if request.app.state.config.BRAVE_SEARCH_API_KEY:
            return search_brave(
                request.app.state.config.BRAVE_SEARCH_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No BRAVE_SEARCH_API_KEY found in environment variables")
    elif engine == "kagi":
        if request.app.state.config.KAGI_SEARCH_API_KEY:
            return search_kagi(
                request.app.state.config.KAGI_SEARCH_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No KAGI_SEARCH_API_KEY found in environment variables")
    elif engine == "mojeek":
        if request.app.state.config.MOJEEK_SEARCH_API_KEY:
            return search_mojeek(
                request.app.state.config.MOJEEK_SEARCH_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No MOJEEK_SEARCH_API_KEY found in environment variables")
    elif engine == "bocha":
        if request.app.state.config.BOCHA_SEARCH_API_KEY:
            return search_bocha(
                request.app.state.config.BOCHA_SEARCH_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No BOCHA_SEARCH_API_KEY found in environment variables")
    elif engine == "serpstack":
        if request.app.state.config.SERPSTACK_API_KEY:
            return search_serpstack(
                request.app.state.config.SERPSTACK_API_KEY,
                query,
                _result_count,
                _domain_filter,
                https_enabled=request.app.state.config.SERPSTACK_HTTPS,
            )
        else:
            raise Exception("No SERPSTACK_API_KEY found in environment variables")
    elif engine == "serper":
        if request.app.state.config.SERPER_API_KEY:
            return search_serper(
                request.app.state.config.SERPER_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No SERPER_API_KEY found in environment variables")
    elif engine == "serply":
        if request.app.state.config.SERPLY_API_KEY:
            return search_serply(
                request.app.state.config.SERPLY_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No SERPLY_API_KEY found in environment variables")
    # elif engine == "duckduckgo":
    #     return search_duckduckgo(
    #         query,
    #         request.app.state.config.WEB_SEARCH_RESULT_COUNT,
    #         request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
    #     )
    elif engine == "tavily":
        if request.app.state.config.TAVILY_API_KEY:
            return search_tavily(
                request.app.state.config.TAVILY_API_KEY,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No TAVILY_API_KEY found in environment variables")
    elif engine == "searchapi":
        if request.app.state.config.SEARCHAPI_API_KEY:
            return search_searchapi(
                request.app.state.config.SEARCHAPI_API_KEY,
                request.app.state.config.SEARCHAPI_ENGINE,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No SEARCHAPI_API_KEY found in environment variables")
    elif engine == "serpapi":
        if request.app.state.config.SERPAPI_API_KEY:
            return search_serpapi(
                request.app.state.config.SERPAPI_API_KEY,
                request.app.state.config.SERPAPI_ENGINE,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception("No SERPAPI_API_KEY found in environment variables")
    elif engine == "jina":
        return search_jina(
            request.app.state.config.JINA_API_KEY,
            query,
            _result_count,
        )
    elif engine == "bing":
        return search_bing(
            request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
            request.app.state.config.BING_SEARCH_V7_ENDPOINT,
            str(DEFAULT_LOCALE),
            query,
            _result_count,
            _domain_filter,
        )
    elif engine == "exa":
        return search_exa(
            request.app.state.config.EXA_API_KEY,
            query,
            _result_count,
            _domain_filter,
        )
    elif engine == "perplexity":
        return search_perplexity(
            request.app.state.config.PERPLEXITY_API_KEY,
            query,
            _result_count,
            _domain_filter,
        )
    elif engine == "sougou":
        if (
            request.app.state.config.SOUGOU_API_SID
            and request.app.state.config.SOUGOU_API_SK
        ):
            return search_sougou(
                request.app.state.config.SOUGOU_API_SID,
                request.app.state.config.SOUGOU_API_SK,
                query,
                _result_count,
                _domain_filter,
            )
        else:
            raise Exception(
                "No SOUGOU_API_SID or SOUGOU_API_SK found in environment variables"
            )
    else:
        raise Exception("No search engine API key found in environment variables")


@router.post("/process/web/search")
async def process_web_search(
    request: Request, form_data: SearchForm, user=Depends(get_verified_user)
):
    try:
        logging.info(
            f"trying to web search with {request.app.state.config.WEB_SEARCH_ENGINE, form_data.query}"
        )
        web_results = search_web(
            request, request.app.state.config.WEB_SEARCH_ENGINE, form_data.query
        )
    except Exception as e:
        log.exception(e)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.WEB_SEARCH_ERROR(e),
        )

    log.debug(f"web_results: {web_results}")

    try:
        urls = [result.link for result in web_results]
        loader = get_web_loader(
            urls,
            verify_ssl=request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
            trust_env=request.app.state.config.WEB_SEARCH_TRUST_ENV,
        )
        docs = await loader.aload()
        urls = [
            doc.metadata["source"] for doc in docs
        ]  # only keep URLs which could be retrieved

        if request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL:
            return {
                "status": True,
                "collection_name": None,
                "filenames": urls,
                "docs": [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                    }
                    for doc in docs
                ],
                "loaded_count": len(docs),
            }
        else:
            collection_names = []
            for doc_idx, doc in enumerate(docs):
                if doc and doc.page_content:
                    collection_name = f"web-search-{calculate_sha256_string(form_data.query + '-' + urls[doc_idx])}"[
                        :63
                    ]

                    collection_names.append(collection_name)
                    await save_docs_to_vector_db(
                        request,
                        [doc],
                        collection_name,
                        overwrite=True,
                        user=user,
                    )

            return {
                "status": True,
                "collection_names": collection_names,
                "filenames": urls,
                "loaded_count": len(docs),
            }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryDocForm(BaseModel):
    collection_name: str
    query: str
    k: Optional[int] = None


@router.post("/query/doc")
async def query_doc_handler(
    request: Request,
    form_data: QueryDocForm,
    user=Depends(get_verified_user),
):
    try:
        query_embedding = await request.app.state.EMBEDDING_FUNCTION(
            form_data.query, prefix=RAG_EMBEDDING_QUERY_PREFIX, user=user
        )
        return query_doc(
            collection_name=form_data.collection_name,
            query_embedding=query_embedding,
            k=form_data.k if form_data.k else request.app.state.config.TOP_K,
            user=user,
        )
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryCollectionsForm(BaseModel):
    collection_names: list[str]
    query: str
    k: Optional[int] = None


@router.post("/query/collection")
async def query_collection_handler(
    request: Request,
    form_data: QueryCollectionsForm,
    user=Depends(get_verified_user),
):
    try:
        return await query_collection(
            collection_names=form_data.collection_names,
            queries=[form_data.query],
            embedding_function=lambda query,
            prefix: request.app.state.EMBEDDING_FUNCTION(
                query, prefix=prefix, user=user
            ),
            k=form_data.k if form_data.k else request.app.state.config.TOP_K,
        )

    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


####################################
#
# Vector DB operations
#
####################################


class DeleteForm(BaseModel):
    collection_name: str
    file_id: str


@router.post("/delete")
async def delete_entries_from_collection(
    request: Request, form_data: DeleteForm, user=Depends(get_admin_user)
):
    try:
        knowledge = SearchEngineKnowledge(
            app=request.app,
            collection_name=form_data.collection_name,
            vector_dim=get_effective_embedding_dimension(request.app),
        )

        if await knowledge.has_documents():
            file = Files.get_file_by_id(form_data.file_id)
            content_hash = file.hash

            deleted = await knowledge.delete_by_metadata({"hash": content_hash})
            log.info(f"Deleted {deleted} entries from {form_data.collection_name}")
            return {"status": True}
        else:
            return {"status": False}
    except Exception as e:
        log.exception(e)
        return {"status": False}


@router.post("/reset/db")
async def reset_vector_db(request: Request, user=Depends(get_admin_user)):
    await reset_knowledge_index(request.app)
    Knowledges.delete_all_knowledge()


@router.post("/reset/uploads")
def reset_upload_dir(user=Depends(get_admin_user)) -> bool:
    folder = f"{UPLOAD_DIR}"
    try:
        # Check if the directory exists
        if os.path.exists(folder):
            # Iterate over all the files and directories in the specified directory
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)  # Remove the file or link
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Remove the directory
                except Exception as e:
                    log.exception(f"Failed to delete {file_path}. Reason: {e}")
        else:
            log.warning(f"The directory {folder} does not exist")
    except Exception as e:
        log.exception(f"Failed to process the directory {folder}. Reason: {e}")
    return True


if ENV == "dev":

    @router.get("/ef/{text}")
    async def get_embeddings(request: Request, text: Optional[str] = "Hello World!"):
        return {
            "result": await request.app.state.EMBEDDING_FUNCTION(
                text, prefix=RAG_EMBEDDING_QUERY_PREFIX
            )
        }


class BatchProcessFilesForm(BaseModel):
    files: List[FileModel]
    collection_name: str


class BatchProcessFilesResult(BaseModel):
    file_id: str
    status: str
    error: Optional[str] = None


class BatchProcessFilesResponse(BaseModel):
    results: List[BatchProcessFilesResult]
    errors: List[BatchProcessFilesResult]


@router.post("/process/files/batch")
async def process_files_batch(
    request: Request,
    form_data: BatchProcessFilesForm,
    user=Depends(get_verified_user),
) -> BatchProcessFilesResponse:
    """
    Process a batch of files and save them to the vector database.
    """
    results: List[BatchProcessFilesResult] = []
    errors: List[BatchProcessFilesResult] = []
    collection_name = form_data.collection_name

    # Prepare all documents first
    all_docs: List[Document] = []
    for file in form_data.files:
        try:
            text_content = file.data.get("content", "")

            docs: List[Document] = [
                Document(
                    page_content=text_content.replace("<br/>", "\n"),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
            ]

            hash = calculate_sha256_string(text_content)
            Files.update_file_hash_by_id(file.id, hash)
            Files.update_file_data_by_id(file.id, {"content": text_content})

            all_docs.extend(docs)
            results.append(BatchProcessFilesResult(file_id=file.id, status="prepared"))

        except Exception as e:
            log.error(f"process_files_batch: Error processing file {file.id}: {str(e)}")
            errors.append(
                BatchProcessFilesResult(file_id=file.id, status="failed", error=str(e))
            )

    # Save all documents in one batch
    if all_docs:
        try:
            await save_docs_to_vector_db(
                request=request,
                docs=all_docs,
                collection_name=collection_name,
                add=True,
                user=user,
                knowledge_id=collection_name,
            )

            # Update all files with collection name
            for result in results:
                Files.update_file_metadata_by_id(
                    result.file_id, {"collection_name": collection_name}
                )
                result.status = "completed"

        except Exception as e:
            log.error(
                f"process_files_batch: Error saving documents to vector DB: {str(e)}"
            )
            for result in results:
                result.status = "failed"
                errors.append(
                    BatchProcessFilesResult(file_id=result.file_id, error=str(e))
                )

    return BatchProcessFilesResponse(results=results, errors=errors)


####################################
#
# Search Engine Configuration APIs
# (extension_modules/search_engine 용)
#
####################################


class SearchEngineConfigForm(BaseModel):
    """검색 엔진 설정 폼"""

    engine_type: Optional[str] = None

    # Azure AI Search
    azure_endpoint: Optional[str] = None
    azure_api_key: Optional[str] = None
    azure_api_version: Optional[str] = None

    # pgvector
    pgvector_host: Optional[str] = None
    pgvector_port: Optional[int] = None
    pgvector_database: Optional[str] = None
    pgvector_user: Optional[str] = None
    pgvector_password: Optional[str] = None

    # Milvus
    milvus_host: Optional[str] = None
    milvus_port: Optional[int] = None
    milvus_user: Optional[str] = None
    milvus_password: Optional[str] = None

    # Elasticsearch
    elasticsearch_url: Optional[str] = None
    elasticsearch_api_key: Optional[str] = None
    elasticsearch_user: Optional[str] = None
    elasticsearch_password: Optional[str] = None
    elasticsearch_ca_certs: Optional[str] = None

    # Vertex AI Search
    vertex_project_id: Optional[str] = None
    vertex_location: Optional[str] = None
    vertex_service_account_key: Optional[str] = None

    # Search settings
    top_k: Optional[int] = None
    reranker_top_k: Optional[int] = None
    reranker_threshold: Optional[float] = None

    # Reranker
    reranker_type: Optional[str] = None
    reranker_vertex_project_id: Optional[str] = None
    reranker_vertex_location: Optional[str] = None
    reranker_vertex_model: Optional[str] = None
    reranker_vertex_service_account_key: Optional[str] = None


@router.get("/search-engine/config")
async def get_search_engine_config(request: Request, user=Depends(get_admin_user)):
    """검색 엔진 설정 조회"""
    return mask_config_dict(
        {
            "status": True,
            "engine_type": request.app.state.config.SEARCH_ENGINE_TYPE,
            # Search settings
            "top_k": request.app.state.config.SEARCH_ENGINE_TOP_K,
            "reranker_top_k": request.app.state.config.SEARCH_ENGINE_RERANKER_TOP_K,
            "reranker_threshold": request.app.state.config.SEARCH_ENGINE_RERANKER_THRESHOLD,
            # Azure AI Search
            "azure_endpoint": request.app.state.config.SEARCH_ENGINE_AZURE_ENDPOINT,
            "azure_api_key": request.app.state.config.SEARCH_ENGINE_AZURE_API_KEY,
            "azure_api_version": request.app.state.config.SEARCH_ENGINE_AZURE_API_VERSION,
            # pgvector
            "pgvector_host": request.app.state.config.SEARCH_ENGINE_PGVECTOR_HOST,
            "pgvector_port": request.app.state.config.SEARCH_ENGINE_PGVECTOR_PORT,
            "pgvector_database": request.app.state.config.SEARCH_ENGINE_PGVECTOR_DATABASE,
            "pgvector_user": request.app.state.config.SEARCH_ENGINE_PGVECTOR_USER,
            "pgvector_password": request.app.state.config.SEARCH_ENGINE_PGVECTOR_PASSWORD,
            # Milvus
            "milvus_host": request.app.state.config.SEARCH_ENGINE_MILVUS_HOST,
            "milvus_port": request.app.state.config.SEARCH_ENGINE_MILVUS_PORT,
            "milvus_user": request.app.state.config.SEARCH_ENGINE_MILVUS_USER,
            "milvus_password": request.app.state.config.SEARCH_ENGINE_MILVUS_PASSWORD,
            # Elasticsearch
            "elasticsearch_url": request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_URL,
            "elasticsearch_api_key": request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_API_KEY,
            "elasticsearch_user": request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_USER,
            "elasticsearch_password": request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_PASSWORD,
            "elasticsearch_ca_certs": request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS,
            # Vertex AI Search
            "vertex_project_id": request.app.state.config.SEARCH_ENGINE_VERTEX_PROJECT_ID,
            "vertex_location": request.app.state.config.SEARCH_ENGINE_VERTEX_LOCATION,
            "vertex_service_account_key": request.app.state.config.SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY,
            # Reranker
            "reranker_type": request.app.state.config.RERANKER_TYPE,
            "reranker_vertex_project_id": request.app.state.config.RERANKER_VERTEX_PROJECT_ID,
            "reranker_vertex_location": request.app.state.config.RERANKER_VERTEX_LOCATION,
            "reranker_vertex_model": request.app.state.config.RERANKER_VERTEX_MODEL,
            "reranker_vertex_service_account_key": request.app.state.config.RERANKER_VERTEX_SERVICE_ACCOUNT_KEY,
        }
    )


@router.post("/search-engine/config/update")
async def update_search_engine_config(
    request: Request, form_data: SearchEngineConfigForm, user=Depends(get_admin_user)
):
    """검색 엔진 설정 업데이트"""
    # Engine type
    if form_data.engine_type is not None:
        request.app.state.config.SEARCH_ENGINE_TYPE = form_data.engine_type

    # Search settings
    if form_data.top_k is not None:
        request.app.state.config.SEARCH_ENGINE_TOP_K = form_data.top_k
    if form_data.reranker_top_k is not None:
        request.app.state.config.SEARCH_ENGINE_RERANKER_TOP_K = form_data.reranker_top_k
    if form_data.reranker_threshold is not None:
        request.app.state.config.SEARCH_ENGINE_RERANKER_THRESHOLD = (
            form_data.reranker_threshold
        )

    # Azure AI Search
    if form_data.azure_endpoint is not None:
        request.app.state.config.SEARCH_ENGINE_AZURE_ENDPOINT = form_data.azure_endpoint
    if form_data.azure_api_key is not None:
        request.app.state.config.SEARCH_ENGINE_AZURE_API_KEY = resolve_sensitive_value(
            form_data.azure_api_key,
            request.app.state.config.SEARCH_ENGINE_AZURE_API_KEY,
        )
    if form_data.azure_api_version is not None:
        request.app.state.config.SEARCH_ENGINE_AZURE_API_VERSION = (
            form_data.azure_api_version
        )

    # pgvector
    if form_data.pgvector_host is not None:
        request.app.state.config.SEARCH_ENGINE_PGVECTOR_HOST = form_data.pgvector_host
    if form_data.pgvector_port is not None:
        request.app.state.config.SEARCH_ENGINE_PGVECTOR_PORT = form_data.pgvector_port
    if form_data.pgvector_database is not None:
        request.app.state.config.SEARCH_ENGINE_PGVECTOR_DATABASE = (
            form_data.pgvector_database
        )
    if form_data.pgvector_user is not None:
        request.app.state.config.SEARCH_ENGINE_PGVECTOR_USER = form_data.pgvector_user
    if form_data.pgvector_password is not None:
        request.app.state.config.SEARCH_ENGINE_PGVECTOR_PASSWORD = (
            resolve_sensitive_value(
                form_data.pgvector_password,
                request.app.state.config.SEARCH_ENGINE_PGVECTOR_PASSWORD,
            )
        )

    # Milvus
    if form_data.milvus_host is not None:
        request.app.state.config.SEARCH_ENGINE_MILVUS_HOST = form_data.milvus_host
    if form_data.milvus_port is not None:
        request.app.state.config.SEARCH_ENGINE_MILVUS_PORT = form_data.milvus_port
    if form_data.milvus_user is not None:
        request.app.state.config.SEARCH_ENGINE_MILVUS_USER = form_data.milvus_user
    if form_data.milvus_password is not None:
        request.app.state.config.SEARCH_ENGINE_MILVUS_PASSWORD = (
            resolve_sensitive_value(
                form_data.milvus_password,
                request.app.state.config.SEARCH_ENGINE_MILVUS_PASSWORD,
            )
        )

    # Elasticsearch
    if form_data.elasticsearch_url is not None:
        request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_URL = (
            form_data.elasticsearch_url
        )
    if form_data.elasticsearch_api_key is not None:
        request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_API_KEY = (
            resolve_sensitive_value(
                form_data.elasticsearch_api_key,
                request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_API_KEY,
            )
        )
    if form_data.elasticsearch_user is not None:
        request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_USER = (
            form_data.elasticsearch_user
        )
    if form_data.elasticsearch_password is not None:
        request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_PASSWORD = (
            resolve_sensitive_value(
                form_data.elasticsearch_password,
                request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_PASSWORD,
            )
        )
    if form_data.elasticsearch_ca_certs is not None:
        request.app.state.config.SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS = (
            form_data.elasticsearch_ca_certs
        )

    # Vertex AI Search
    if form_data.vertex_project_id is not None:
        request.app.state.config.SEARCH_ENGINE_VERTEX_PROJECT_ID = (
            form_data.vertex_project_id
        )
    if form_data.vertex_location is not None:
        request.app.state.config.SEARCH_ENGINE_VERTEX_LOCATION = (
            form_data.vertex_location
        )
    if form_data.vertex_service_account_key is not None:
        request.app.state.config.SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY = (
            resolve_sensitive_value(
                form_data.vertex_service_account_key,
                request.app.state.config.SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY,
            )
        )

    # Reranker
    if form_data.reranker_type is not None:
        request.app.state.config.RERANKER_TYPE = form_data.reranker_type
    if form_data.reranker_vertex_project_id is not None:
        request.app.state.config.RERANKER_VERTEX_PROJECT_ID = (
            form_data.reranker_vertex_project_id
        )
    if form_data.reranker_vertex_location is not None:
        request.app.state.config.RERANKER_VERTEX_LOCATION = (
            form_data.reranker_vertex_location
        )
    if form_data.reranker_vertex_model is not None:
        request.app.state.config.RERANKER_VERTEX_MODEL = form_data.reranker_vertex_model
    if form_data.reranker_vertex_service_account_key is not None:
        request.app.state.config.RERANKER_VERTEX_SERVICE_ACCOUNT_KEY = (
            resolve_sensitive_value(
                form_data.reranker_vertex_service_account_key,
                request.app.state.config.RERANKER_VERTEX_SERVICE_ACCOUNT_KEY,
            )
        )

    AuditLogger.log_settings_change("search_engine", after_data=form_data.model_dump())
    return {"status": True, "message": "Search engine configuration updated"}


@router.post("/search-engine/pgvector/test")
async def test_pgvector_connection(
    request: Request,
    form_data: SearchEngineConfigForm,
    user=Depends(get_admin_user),
):
    """pgvector(PostgreSQL) 연결 테스트.

    저장 전에 호스트/포트/DB/계정 도달 여부와 pgvector 확장 설치 여부를
    확인한다. DbSphere 연결 테스트와 동일한 UX. 마스킹된 비밀번호는
    저장된 값으로 복원해 사용한다.
    """
    import asyncio

    try:
        import asyncpg
    except ImportError:
        return {
            "success": False,
            "message": "asyncpg is not installed on the server.",
            "pgvector_available": False,
        }

    cfg = request.app.state.config
    host = form_data.pgvector_host or cfg.SEARCH_ENGINE_PGVECTOR_HOST
    port = form_data.pgvector_port or cfg.SEARCH_ENGINE_PGVECTOR_PORT
    database = form_data.pgvector_database or cfg.SEARCH_ENGINE_PGVECTOR_DATABASE
    db_user = form_data.pgvector_user or cfg.SEARCH_ENGINE_PGVECTOR_USER
    # Masked password (unchanged in the form) → fall back to the saved secret.
    password = resolve_sensitive_value(
        form_data.pgvector_password, cfg.SEARCH_ENGINE_PGVECTOR_PASSWORD
    )

    if not host or not database or not db_user:
        return {
            "success": False,
            "message": "Host, database, and user are required.",
            "pgvector_available": False,
        }

    conn = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host,
                port=int(port) if port else 5432,
                database=database,
                user=db_user,
                password=password or None,
            ),
            timeout=10,
        )
        await conn.fetchval("SELECT 1")

        # pgvector 확장: 설치됨 여부 + (미설치 시) 설치 가능 여부
        installed = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        available = bool(installed) or bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
            )
        )

        if installed:
            message = "Connected. pgvector extension is installed."
        elif available:
            message = (
                "Connected, but the pgvector extension is not installed yet "
                "(it will be created on first use)."
            )
        else:
            message = (
                "Connected, but the pgvector extension is not available on this "
                "server. Install the 'vector' extension."
            )

        return {
            "success": True,
            "message": message,
            "pgvector_available": available,
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": (
                f"Connection timed out after 10s. Check that the server can reach "
                f"{host}:{port} (VPC egress is required for private IPs on Cloud Run)."
            ),
            "pgvector_available": False,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {e}",
            "pgvector_available": False,
        }
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
