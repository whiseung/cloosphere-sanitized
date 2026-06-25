import asyncio
import json
import logging
import mimetypes
import os
import sys
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlencode, urlparse

import redis
import requests
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    applications,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from open_webui.config import (
    ADMIN_EMAIL,
    ALLOWED_FILE_EXTENSIONS,
    API_KEY_ALLOWED_ENDPOINTS,
    AUDIO_AVATAR_API_KEY,
    AUDIO_AVATAR_ENGINE,
    AUDIO_AVATAR_REGION,
    AUDIO_STT_AZURE_API_KEY,
    AUDIO_STT_AZURE_LOCALES,
    AUDIO_STT_AZURE_REGION,
    # Audio
    AUDIO_STT_ENGINE,
    AUDIO_STT_GOOGLE_LANGUAGE_CODES,
    AUDIO_STT_GOOGLE_LOCATION,
    AUDIO_STT_GOOGLE_PROJECT_ID,
    AUDIO_STT_GOOGLE_SERVICE_ACCOUNT_KEY,
    AUDIO_STT_MODEL,
    AUDIO_STT_OPENAI_API_BASE_URL,
    AUDIO_STT_OPENAI_API_KEY,
    AUDIO_TTS_API_KEY,
    AUDIO_TTS_AZURE_AVATAR_CHARACTER,
    AUDIO_TTS_AZURE_AVATAR_GREETING,
    AUDIO_TTS_AZURE_AVATAR_STYLE,
    AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT,
    AUDIO_TTS_AZURE_SPEECH_REGION,
    AUDIO_TTS_ENGINE,
    AUDIO_TTS_GEMINI_LOCATION,
    AUDIO_TTS_GEMINI_MODEL,
    AUDIO_TTS_GEMINI_SERVICE_ACCOUNT_KEY,
    AUDIO_TTS_GOOGLE_LANGUAGE_CODE,
    AUDIO_TTS_GOOGLE_SERVICE_ACCOUNT_KEY,
    AUDIO_TTS_MODEL,
    AUDIO_TTS_OPENAI_API_BASE_URL,
    AUDIO_TTS_OPENAI_API_KEY,
    AUDIO_TTS_SPLIT_ON,
    AUDIO_TTS_VOICE,
    AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH,
    AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE,
    # Image
    AUTOMATIC1111_API_AUTH,
    AUTOMATIC1111_BASE_URL,
    AUTOMATIC1111_CFG_SCALE,
    AUTOMATIC1111_SAMPLER,
    AUTOMATIC1111_SCHEDULER,
    AZURE_STORAGE_CONTAINER_NAME,
    AZURE_STORAGE_ENDPOINT,
    AZURE_STORAGE_KEY,
    BING_SEARCH_V7_ENDPOINT,
    BING_SEARCH_V7_SUBSCRIPTION_KEY,
    BOCHA_SEARCH_API_KEY,
    BRANDING_APP_NAME,
    BRANDING_BROWSER_FAVICON_URL,
    BRANDING_FAVICON_DARK_URL,
    BRANDING_FAVICON_URL,
    BRANDING_LOGO_URL,
    BRANDING_SPLASH_DARK_URL,
    BRANDING_SPLASH_URL,
    BRAVE_SEARCH_API_KEY,
    BYPASS_EMBEDDING_AND_RETRIEVAL,
    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL,
    CACHE_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CODE_EXECUTION_ENGINE,
    CODE_EXECUTION_JUPYTER_AUTH,
    CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
    CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
    CODE_EXECUTION_JUPYTER_TIMEOUT,
    CODE_EXECUTION_JUPYTER_URL,
    CODE_GATEWAY_ALLOWED_MODELS,
    CODE_GATEWAY_BLOCKED_FILE_ACTION,
    CODE_GATEWAY_BLOCKED_FILE_PATTERNS,
    CODE_GATEWAY_BLOCKED_REPOS,
    CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL,
    CODE_GATEWAY_GUARDRAIL_IDS,
    CODE_GATEWAY_MISSING_METADATA_ACTION,
    CODE_GATEWAY_PROVIDERS,
    CODE_GATEWAY_RATE_LIMIT,
    CODE_GATEWAY_REQUIRE_REPO_METADATA,
    COMFYUI_API_KEY,
    COMFYUI_BASE_URL,
    COMFYUI_WORKFLOW,
    COMFYUI_WORKFLOW_NODES,
    CONTENT_EXTRACTION_ENGINE,
    CORS_ALLOW_ORIGIN,
    DATA_RETENTION_CLEANUP_HOUR,
    DBSPHERE_TYPES,
    DEEPGRAM_API_KEY,
    DEFAULT_LOCALE,
    DEFAULT_MODELS,
    DEFAULT_PROMPT_SUGGESTIONS,
    DEFAULT_USER_ROLE,
    DOCLING_SERVER_URL,
    DOCUMENT_AI_LOCATION,
    DOCUMENT_AI_PROCESSOR_ID,
    DOCUMENT_AI_PROCESSOR_VERSION,
    DOCUMENT_AI_PROJECT_ID,
    DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
    DOCUMENT_INTELLIGENCE_ENDPOINT,
    DOCUMENT_INTELLIGENCE_KEY,
    DOCUMENT_TEMPLATE_DOCX,
    DOCUMENT_TEMPLATE_PPTX,
    DOCUMENT_TEMPLATE_XLSX,
    # Email / Notifications
    EMAIL_ENGINE,
    # Admin
    ENABLE_ADMIN_CHAT_ACCESS,
    ENABLE_ADMIN_EXPORT,
    ENABLE_API_KEY,
    ENABLE_API_KEY_ENDPOINT_RESTRICTIONS,
    ENABLE_AUTOCOMPLETE_GENERATION,
    ENABLE_CALENDAR_INTEGRATION,
    ENABLE_CHANNELS,
    # Code Execution
    ENABLE_CODE_EXECUTION,
    # Code Gateway
    ENABLE_CODE_GATEWAY,
    ENABLE_COMMUNITY_SHARING,
    # Data Retention
    ENABLE_DATA_RETENTION,
    # Direct Connections
    ENABLE_DIRECT_CONNECTIONS,
    # Google integration (Drive chat — distinct from RAG ENABLE_GOOGLE_DRIVE_INTEGRATION)
    ENABLE_DRIVE_INTEGRATION,
    # WebUI (LDAP)
    ENABLE_EMAIL_DEIDENTIFY,
    ENABLE_EVALUATION_ARENA_MODELS,
    ENABLE_FOLLOW_UP_GENERATION,
    ENABLE_GLOBAL_GUARDRAIL,
    # Google integration (Gmail / Calendar)
    ENABLE_GMAIL_INTEGRATION,
    ENABLE_GOOGLE_DRIVE_INTEGRATION,
    # HITL
    ENABLE_HITL,
    ENABLE_IMAGE_GENERATION,
    ENABLE_IMAGE_PROMPT_GENERATION,
    ENABLE_LDAP,
    ENABLE_LICENSE_ENFORCEMENT,
    ENABLE_LOGIN_FORM,
    ENABLE_MESSAGE_RATING,
    # WebUI (OAuth)
    ENABLE_OAUTH_ROLE_MANAGEMENT,
    # Ollama
    ENABLE_OLLAMA_API,
    ENABLE_ONBOARDING,
    ENABLE_ONEDRIVE_INTEGRATION,
    # OpenAI
    ENABLE_OPENAI_API,
    ENABLE_OTEL,
    ENABLE_SHAREPOINT_INTEGRATION,
    ENABLE_SIGNUP,
    ENABLE_TAGS_GENERATION,
    ENABLE_TITLE_GENERATION,
    ENABLE_USAGE_LIMIT,
    ENABLE_USER_WEBHOOKS,
    ENABLE_WEB_LOADER_SSL_VERIFICATION,
    # Retrieval (Web Search)
    ENABLE_WEB_SEARCH,
    ENABLE_WORKER_AUTO_CLEANUP,
    # Misc
    ENV,
    EVALUATION_ARENA_MODELS,
    EXA_API_KEY,
    FEATURE_KEYS,
    FILE_AZURE_STORAGE_CONTAINER_NAME,
    FILE_AZURE_STORAGE_ENDPOINT,
    FILE_AZURE_STORAGE_KEY,
    FILE_GCS_BUCKET_NAME,
    FILE_GCS_CREDENTIALS_JSON,
    FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES,
    FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES,
    FILE_GUARDRAIL_CLASSIFICATION_ENABLED,
    FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS,
    FILE_GUARDRAIL_CLASSIFICATION_MODEL,
    FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES,
    FILE_GUARDRAIL_CLASSIFICATION_PROMPT,
    FILE_GUARDRAIL_ENABLED,
    FILE_GUARDRAIL_EXIF_ENABLED,
    FILE_GUARDRAIL_IDS,
    FILE_GUARDRAIL_MACRO_ACTION,
    FILE_GUARDRAIL_MACRO_ENABLED,
    FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES,
    FILE_GUARDRAIL_NSFW_ENABLED,
    FILE_GUARDRAIL_NSFW_MODEL,
    FILE_GUARDRAIL_NSFW_PASS_EXAMPLES,
    FILE_GUARDRAIL_NSFW_PROMPT,
    FILE_GUARDRAIL_SCOPES,
    FILE_S3_ACCESS_KEY_ID,
    FILE_S3_BUCKET_NAME,
    FILE_S3_ENDPOINT_URL,
    FILE_S3_KEY_PREFIX,
    FILE_S3_REGION_NAME,
    FILE_S3_SECRET_ACCESS_KEY,
    FILE_STORAGE_PROVIDER,
    FIRECRAWL_API_BASE_URL,
    FIRECRAWL_API_KEY,
    FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
    FRONTEND_BUILD_DIR,
    GCS_BUCKET_NAME,
    GLOBAL_GUARDRAIL_IDS,
    GOOGLE_APPLICATION_CREDENTIALS_JSON,
    GOOGLE_CLOUD_ENABLED,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
    GOOGLE_DRIVE_API_KEY,
    GOOGLE_DRIVE_CLIENT_ID,
    GOOGLE_PSE_API_KEY,
    GOOGLE_PSE_ENGINE_ID,
    IMAGE_API_CONFIGS,
    IMAGE_API_KEYS,
    IMAGE_API_URLS,
    IMAGE_GENERATION_ENGINE,
    IMAGE_GENERATION_MODEL,
    IMAGE_SIZE,
    IMAGE_STEPS,
    # Storage Config
    IMAGE_UPLOAD_MODE,
    IMAGES_AZURE_OPENAI_API_BASE_URL,
    IMAGES_AZURE_OPENAI_API_KEY,
    IMAGES_AZURE_OPENAI_API_VERSION,
    IMAGES_AZURE_OPENAI_BACKGROUND,
    IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME,
    IMAGES_AZURE_OPENAI_OUTPUT_FORMAT,
    IMAGES_AZURE_OPENAI_QUALITY,
    IMAGES_GEMINI_API_BASE_URL,
    IMAGES_GEMINI_API_KEY,
    IMAGES_OPENAI_API_BASE_URL,
    IMAGES_OPENAI_API_KEY,
    IMAGES_VERTEX_AI_LOCATION,
    IMAGES_VERTEX_AI_PROJECT_ID,
    IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY,
    JINA_API_KEY,
    JWT_EXPIRES_IN,
    KAGI_SEARCH_API_KEY,
    KB_MAX_QUESTIONS_PER_CHUNK,
    KB_QUESTION_GENERATION_ENABLED,
    KB_QUESTION_GENERATION_MODEL,
    KB_QUESTION_VECTOR_WEIGHT,
    KMS_AZURE_CLIENT_ID,
    KMS_AZURE_CLIENT_SECRET,
    KMS_AZURE_KEY_VAULT_KEY_URI,
    KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED,
    KMS_AZURE_TENANT_ID,
    KMS_PROVIDER,
    KMS_ROTATION_AUTO_ENABLED,
    KMS_ROTATION_CHECK_INTERVAL_HOURS,
    KMS_ROTATION_DRY_RUN,
    KMS_ROTATION_LAST_CHECK_AT,
    KMS_ROTATION_LAST_RESULT,
    LDAP_APP_DN,
    LDAP_APP_PASSWORD,
    LDAP_ATTRIBUTE_FOR_MAIL,
    LDAP_ATTRIBUTE_FOR_USERNAME,
    LDAP_CA_CERT_FILE,
    LDAP_CIPHERS,
    LDAP_SEARCH_BASE,
    LDAP_SEARCH_FILTERS,
    LDAP_SERVER_HOST,
    LDAP_SERVER_LABEL,
    LDAP_SERVER_PORT,
    LDAP_USE_TLS,
    LICENSE_KEY,
    LICENSE_KEYS,
    # Memory extraction
    MEMORY_EXTRACTION_CONFIDENCE,
    MEMORY_EXTRACTION_MODEL,
    MISTRAL_OCR_API_KEY,
    MODEL_ORDER_LIST,
    MOJEEK_SEARCH_API_KEY,
    NOTIFICATION_EMAIL_CHANNELS,
    NOTIFICATION_EVENTS,
    NOTIFICATION_WEBHOOK_CHANNELS,
    OAUTH_ADMIN_ROLES,
    OAUTH_ALLOWED_ROLES,
    OAUTH_EMAIL_CLAIM,
    OAUTH_PICTURE_CLAIM,
    OAUTH_PROVIDERS,
    OAUTH_ROLES_CLAIM,
    OAUTH_USERNAME_CLAIM,
    OLLAMA_API_CONFIGS,
    OLLAMA_BASE_URLS,
    ONEDRIVE_CLIENT_ID,
    OPENAI_API_BASE_URLS,
    OPENAI_API_CONFIGS,
    OPENAI_API_KEYS,
    OTEL_EXPORTER_OTLP_ENDPOINT,
    PDF_CONVERT_EXTENSIONS,
    PDF_EXTRACT_IMAGES,
    PERPLEXITY_API_KEY,
    PLAYWRIGHT_TIMEOUT,
    PLAYWRIGHT_WS_URL,
    PRESENTON_BASE_URL,
    PRESENTON_DEFAULT_TEMPLATE,
    PRESENTON_ENABLED,
    PRESENTON_TIMEOUT,
    RAG_AZURE_OPENAI_API_BASE_URL,
    RAG_AZURE_OPENAI_API_KEY,
    RAG_AZURE_OPENAI_API_VERSION,
    RAG_CHUNK_MAX_TOKENS,
    RAG_CHUNK_MIN_TOKENS,
    RAG_EMBEDDING_BATCH_SIZE,
    RAG_EMBEDDING_DIMENSIONS,
    RAG_EMBEDDING_ENGINE,
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_MODEL_AUTO_UPDATE,
    RAG_FILE_MAX_COUNT,
    RAG_FILE_MAX_SIZE,
    RAG_FULL_CONTEXT,
    RAG_GEMINI_API_KEY,
    RAG_OLLAMA_API_KEY,
    RAG_OLLAMA_BASE_URL,
    RAG_OPENAI_API_BASE_URL,
    RAG_OPENAI_API_KEY,
    RAG_TEMPLATE,
    RAG_TEXT_SPLITTER,
    RAG_TOP_K,
    RAG_VERTEX_AI_LOCATION,
    RAG_VERTEX_AI_PROJECT_ID,
    RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY,
    # Reranker
    RERANKER_TYPE,
    RERANKER_VERTEX_LOCATION,
    RERANKER_VERTEX_MODEL,
    RERANKER_VERTEX_PROJECT_ID,
    RERANKER_VERTEX_SERVICE_ACCOUNT_KEY,
    RETENTION_DAYS_AUDIT_LOG,
    RETENTION_DAYS_AUTO_EVALUATION,
    RETENTION_DAYS_GUARDRAIL_LOG,
    RETENTION_DAYS_TRACE,
    RETENTION_DAYS_TRACE_ANALYSIS,
    RETENTION_DAYS_USAGE,
    S3_ACCESS_KEY_ID,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_KEY_PREFIX,
    S3_REGION_NAME,
    S3_SECRET_ACCESS_KEY,
    SEARCH_ENGINE_AZURE_API_KEY,
    SEARCH_ENGINE_AZURE_API_VERSION,
    SEARCH_ENGINE_AZURE_ENDPOINT,
    SEARCH_ENGINE_ELASTICSEARCH_API_KEY,
    SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS,
    SEARCH_ENGINE_ELASTICSEARCH_PASSWORD,
    SEARCH_ENGINE_ELASTICSEARCH_URL,
    SEARCH_ENGINE_ELASTICSEARCH_USER,
    SEARCH_ENGINE_MILVUS_HOST,
    SEARCH_ENGINE_MILVUS_PASSWORD,
    SEARCH_ENGINE_MILVUS_PORT,
    SEARCH_ENGINE_MILVUS_USER,
    SEARCH_ENGINE_PGVECTOR_DATABASE,
    SEARCH_ENGINE_PGVECTOR_HOST,
    SEARCH_ENGINE_PGVECTOR_PASSWORD,
    SEARCH_ENGINE_PGVECTOR_PORT,
    SEARCH_ENGINE_PGVECTOR_USER,
    SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED,
    SEARCH_ENGINE_RERANKER_THRESHOLD,
    SEARCH_ENGINE_RERANKER_TOP_K,
    SEARCH_ENGINE_TOP_K,
    # Search Engine
    SEARCH_ENGINE_TYPE,
    SEARCH_ENGINE_VERTEX_LOCATION,
    SEARCH_ENGINE_VERTEX_PROJECT_ID,
    SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY,
    SEARCHAPI_API_KEY,
    SEARCHAPI_ENGINE,
    SEARXNG_QUERY_URL,
    SENDGRID_API_KEY,
    SENDGRID_FROM_ADDRESS,
    SENDGRID_FROM_NAME,
    SERPAPI_API_KEY,
    SERPAPI_ENGINE,
    SERPER_API_KEY,
    SERPLY_API_KEY,
    SERPSTACK_API_KEY,
    SERPSTACK_HTTPS,
    SHAREPOINT_CLIENT_ID,
    SHAREPOINT_SITE_URL,
    SHAREPOINT_TENANT_ID,
    SHOW_ADMIN_DETAILS,
    SMTP_FROM_ADDRESS,
    SMTP_FROM_NAME,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USERNAME,
    SOUGOU_API_SID,
    SOUGOU_API_SK,
    STATIC_DIR,
    STORAGE_PROVIDER,
    TAGS_GENERATION_PROMPT_TEMPLATE,
    # Tasks
    TASK_MODEL,
    TASK_MODEL_EXTERNAL,
    TAVILY_API_KEY,
    TAVILY_EXTRACT_DEPTH,
    TEAMS_BOT_ACCENT_COLOR,
    TEAMS_BOT_APP_ID,
    TEAMS_BOT_APP_PASSWORD,
    TEAMS_BOT_COLOR_ICON,
    TEAMS_BOT_DEFAULT_GROUP_CAPABILITY,
    TEAMS_BOT_DESCRIPTION_FULL,
    TEAMS_BOT_DESCRIPTION_SHORT,
    TEAMS_BOT_DEVELOPER_NAME,
    TEAMS_BOT_DEVELOPER_WEBSITE,
    TEAMS_BOT_ENABLED,
    TEAMS_BOT_MODEL_ID,
    TEAMS_BOT_NAME,
    TEAMS_BOT_OUTLINE_ICON,
    TEAMS_BOT_SCOPES,
    TEAMS_BOT_TENANT_ID,
    TIKA_SERVER_URL,
    TIKTOKEN_ENCODING_NAME,
    TITLE_GENERATION_PROMPT_TEMPLATE,
    # Tool Server Configs
    TOOL_SERVER_CONNECTIONS,
    USAGE_LIMIT_DEFAULT_DAILY_TOKENS,
    USAGE_LIMIT_EXCEED_ACTION,
    USAGE_LIMIT_PER_MODEL,
    USER_PERMISSIONS,
    WEB_LOADER_ENGINE,
    WEB_SEARCH_CONCURRENT_REQUESTS,
    WEB_SEARCH_DOMAIN_FILTER_LIST,
    WEB_SEARCH_ENGINE,
    WEB_SEARCH_RESULT_COUNT,
    WEB_SEARCH_TRUST_ENV,
    WEBHOOK_PROVIDER,
    WEBHOOK_URL,
    WEBUI_AUTH,
    WEBUI_BANNERS,
    WEBUI_NAME,
    WEBUI_URL,
    WHISPER_MODEL,
    WHISPER_VAD_FILTER,
    WORKER_CLEANUP_INTERVAL_MINUTES,
    WORKER_STUCK_IDLE_HOURS,
    WORKER_ZOMBIE_IDLE_HOURS,
    YOUTUBE_LOADER_LANGUAGE,
    YOUTUBE_LOADER_PROXY_URL,
    AppConfig,
    reset_config,
)
from open_webui.env import (
    AUDIT_EXCLUDED_PATHS,
    AUDIT_LOG_LEVEL,
    BYPASS_MODEL_ACCESS_CONTROL,
    CHANGELOG,
    CHANGELOG_KO,
    DOCS_DIR,
    ENABLE_WEBSOCKET_SUPPORT,
    EXTERNAL_PWA_MANIFEST_URL,
    GLOBAL_LOG_LEVEL,
    MAX_BODY_LOG_SIZE,
    REDIS_SENTINEL_HOSTS,
    REDIS_SENTINEL_PORT,
    REDIS_URL,
    RESET_CONFIG_ON_START,
    SAFE_MODE,
    SRC_LOG_LEVELS,
    VERSION,
    WEBUI_AUTH_TRUSTED_EMAIL_HEADER,
    WEBUI_AUTH_TRUSTED_NAME_HEADER,
    WEBUI_BUILD_HASH,
    WEBUI_SECRET_KEY,
    WEBUI_SESSION_COOKIE_SAME_SITE,
    WEBUI_SESSION_COOKIE_SECURE,
)
from open_webui.internal.cloocus_db import is_cloocus_db_available
from open_webui.internal.db import Session, engine
from open_webui.models.agent_config import AgentConfig
from open_webui.models.chats import Chats
from open_webui.models.functions import Functions
from open_webui.models.models import Models
from open_webui.models.users import Users
from open_webui.routers import (
    admin_memory,
    agent_flows,
    audio,
    audit_logs,
    auths,
    auto_evaluations,
    bi_dashboard,
    branding,
    channels,
    chat_hitl,
    chats,
    cloocus,
    code_gateway,
    configs,
    data_retention,
    dbsphere,
    devtools,
    document_profiles,
    document_templates,
    email_integration,
    embed_widgets,
    embed_widgets_public,
    evaluations,
    extraction_engines,
    file_logs,
    files,
    folders,
    functions,
    glossary,
    google_actions,
    groups,
    guardrail_logs,
    guardrails,
    guide,
    images,
    inquiries,
    knowledge,
    knowledge_graph,
    license,
    license_permissions,
    marketplace,
    memories,
    models,
    notifications,
    ollama,
    openai,
    organizations,
    pipelines,
    projects,
    prompts,
    retrieval,
    schedules,
    sr,
    tasks,
    teams_bot,
    teams_bot_config,
    tool_connections,
    tools,
    trace_analysis,
    traces,
    trusted_audiences,
    usage,
    users,
    utils,
    workspace_tags,
)
from open_webui.routers.retrieval import (
    get_ef,
    get_embedding_function,
)
from open_webui.socket.main import (
    app as socket_app,
)
from open_webui.socket.main import (
    periodic_usage_pool_cleanup,
)
from open_webui.tasks import (
    list_task_ids_by_chat_id,
    list_tasks,
    stop_task,
)  # Import from tasks.py
from open_webui.utils import logger
from open_webui.utils.access_control import has_access
from open_webui.utils.audit import AuditLevel, AuditLoggingMiddleware
from open_webui.utils.audit_events import register_audit_events
from open_webui.utils.audit_middleware import AuditContextMiddleware
from open_webui.utils.auth import (
    decode_token,
    get_admin_user,
    get_http_authorization_cred,
    get_license_data,
    get_verified_user,
)
from open_webui.utils.chat import (
    chat_action as chat_action_handler,
)
from open_webui.utils.chat import (
    chat_completed as chat_completed_handler,
)
from open_webui.utils.chat import (
    generate_chat_completion as chat_completion_handler,
)
from open_webui.utils.license import resolve_license_status
from open_webui.utils.logger import start_logger
from open_webui.utils.middleware import process_chat_payload, process_chat_response
from open_webui.utils.models import (
    check_model_access,
    get_all_base_models,
    get_all_models,
)
from open_webui.utils.oauth import OAuthManager
from open_webui.utils.redis import get_sentinels_from_env
from open_webui.utils.security_headers import SecurityHeadersMiddleware

if SAFE_MODE:
    print("SAFE MODE ENABLED")
    Functions.deactivate_all_functions()

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as ex:
            if ex.status_code == 404:
                if path.endswith(".js"):
                    # Return 404 for javascript files
                    raise ex
                else:
                    return await super().get_response("index.html", scope)
            else:
                raise ex


print(
    rf"""
░█████╗░██╗░░░░░░█████╗░░█████╗░░██████╗██████╗░██╗░░██╗███████╗██████╗░███████╗
██╔══██╗██║░░░░░██╔══██╗██╔══██╗██╔════╝██╔══██╗██║░░██║██╔════╝██╔══██╗██╔════╝
██║░░╚═╝██║░░░░░██║░░██║██║░░██║╚█████╗░██████╔╝███████║█████╗░░██████╔╝█████╗░░
██║░░██╗██║░░░░░██║░░██║██║░░██║░╚═══██║██╔═══╝░██╔══██║██╔══╝░░██╔══██╗██╔══╝░░
╚█████╔╝███████╗╚█████╔╝╚█████╔╝██████╔╝██║░░░░░██║░░██║███████╗██║░░██║███████╗
░╚════╝░╚══════╝░╚════╝░░╚════╝░╚═════╝░╚═╝░░░░░╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝╚══════╝
              ✦ AI Platform ✦  │ Powered by Cloocus
{f"Commit: {WEBUI_BUILD_HASH}" if WEBUI_BUILD_HASH != "dev-build" else ""}
"""
)


async def _config_invalidation_subscriber():
    """
    Redis pub/sub 구독: 다른 워커가 PersistentConfig를 변경했을 때 알림 수신.

    동작:
    1. AppConfig.__setattr__가 호출되면 CONFIG_INVALIDATE_CHANNEL에 변경된 env_name 발행
       (save_config 경로는 "__ALL__" sentinel로 전체 reload 요청)
    2. 메시지 수신 시 먼저 모듈-전역 CONFIG_DATA를 DB에서 재로드(get_config).
       PersistentConfig.update() → get_config_value()가 이 dict를 읽으므로, 이 재로드
       없이는 다른 워커의 update()가 stale 값을 다시 덮어쓰는 no-op이 된다.
    3. 매칭되는 PersistentConfig 인스턴스를 찾아 update() 호출 (.value 갱신)
    4. OAuth 관련 키이면 oauth_manager.reload()로 authlib OAuth 클라이언트 재등록
       (PersistentConfig 값은 갱신되었지만 OAuth 클라이언트는 register 시점에 스냅샷한
       값으로 캡처되어 있어 명시적 재등록 필요). single-key 메시지여도
       load_oauth_providers()는 전체 OAuth 값을 읽으므로, reload 직전
       OAUTH_PROVIDER_CONFIG_KEYS 전체를 update한다 (partial-stale 재등록 방지).

    장애 복원력:
    - Redis 일시 단절/예외로 listen이 종료되면 5초 후 재시도(무한 루프).
      일회성 subscribe 후 종료되면 그 워커는 이후 모든 invalidation을 영구 miss하므로 필수.

    성능 주의:
    - get_config() / cfg.update() / oauth_manager.reload()는 sync DB I/O를 포함해
      이벤트 루프를 순간 블로킹한다. 호출 빈도가 관리자 설정 변경 수준(분 단위 이하)이라
      실전 영향 미미하여 to_thread 래핑은 생략.
    """
    import redis.asyncio as aioredis

    # CONFIG_DATA에 재할당하려면 모듈 객체 참조 필요 (from import 하면 로컬 바인딩만 바뀜)
    import open_webui.config as config_mod
    from open_webui.config import (
        CONFIG_INVALIDATE_ALL,
        CONFIG_INVALIDATE_CHANNEL,
        KMS_CONFIG_KEYS,
        MODELS_INVALIDATE_KEY,
        OAUTH_PROVIDER_CONFIG_KEYS,
        PERSISTENT_CONFIG_REGISTRY,
        get_config,
    )

    pid = os.getpid()
    backoff = 5

    while True:
        client = None
        pubsub = None
        try:
            client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(CONFIG_INVALIDATE_CHANNEL)
            log.info(
                f"[pid={pid}] Config invalidation subscriber started on "
                f"'{CONFIG_INVALIDATE_CHANNEL}'"
            )

            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                key = msg.get("data")
                if not isinstance(key, str):
                    continue

                # MODELS cache invalidation (Cloosphere-specific).
                # 다른 워커의 모델 CRUD/toggle/delete 후 publish 된 신호.
                # PersistentConfig 와 무관하므로 아래 CONFIG_DATA reload 경로를
                # 건너뛰고 즉시 처리. 자기가 publish 한 메시지도 자기 워커가
                # 받지만 빈 dict 재할당이 idempotent 라 안전.
                if key == MODELS_INVALIDATE_KEY:
                    try:
                        app.state.MODELS = {}
                        log.info(
                            f"[pid={pid}] MODELS cache invalidated by remote worker"
                        )
                    except Exception as e:
                        log.warning(f"[pid={pid}] Failed to invalidate MODELS: {e}")
                    continue

                # Step 1: 모듈-전역 CONFIG_DATA를 DB 최신값으로 교체.
                # 이후 cfg.update() → get_config_value()가 fresh dict를 읽는다.
                try:
                    config_mod.CONFIG_DATA = get_config()
                except Exception as e:
                    log.warning(
                        f"[pid={pid}] Failed to reload CONFIG_DATA on invalidation: {e}"
                    )
                    continue

                # 매 메시지마다 fresh 스냅샷 (등록이 런타임에 추가되는 경우 대비)
                registry_by_name = {
                    cfg.env_name: cfg for cfg in PERSISTENT_CONFIG_REGISTRY
                }

                # Step 2a: bulk reload (save_config 경로)
                if key == CONFIG_INVALIDATE_ALL:
                    log.info(
                        f"[pid={pid}] Bulk config invalidation received; "
                        f"reloading all PersistentConfigs"
                    )
                    for cfg in PERSISTENT_CONFIG_REGISTRY:
                        try:
                            cfg.update()
                        except Exception as e:
                            log.warning(
                                f"[pid={pid}] Failed to update '{cfg.env_name}': {e}"
                            )
                    try:
                        oauth_manager.reload()
                    except Exception as e:
                        log.warning(
                            f"[pid={pid}] Failed to reload OAuthManager on bulk invalidation: {e}"
                        )
                    continue

                # Step 2b: 단일 key reload (AppConfig.__setattr__ 경로)
                cfg = registry_by_name.get(key)
                if cfg is not None:
                    try:
                        cfg.update()
                        log.info(
                            f"[pid={pid}] PersistentConfig '{key}' reloaded from DB"
                        )
                    except Exception as e:
                        log.warning(
                            f"[pid={pid}] Failed to update PersistentConfig '{key}': {e}"
                        )

                # Step 3: OAuth 재등록이 필요한 key면, 관련 key 전체를 fresh로 맞춘 뒤 reload.
                # load_oauth_providers()가 GOOGLE_CLIENT_SECRET 등 다른 OAuth 값도 읽기 때문에
                # 해당 cfg만 update한 상태로 reload하면 partial-stale 재등록이 발생한다.
                if key in OAUTH_PROVIDER_CONFIG_KEYS:
                    for oauth_key in OAUTH_PROVIDER_CONFIG_KEYS:
                        oauth_cfg = registry_by_name.get(oauth_key)
                        if oauth_cfg is not None:
                            try:
                                oauth_cfg.update()
                            except Exception as e:
                                log.warning(
                                    f"[pid={pid}] Failed to update OAuth key '{oauth_key}': {e}"
                                )
                    try:
                        oauth_manager.reload()
                    except Exception as e:
                        log.warning(
                            f"[pid={pid}] Failed to reload OAuthManager after '{key}' change: {e}"
                        )

                # KMS provider / KEK URI / SP credentials changed on
                # another worker → drop our cached KMSRouter singleton so
                # the next encrypt/decrypt rebuilds with the now-updated
                # PersistentConfig values. Without this, a `set_kms_config`
                # or `rotate` call on worker A leaves workers B..N writing
                # under the *old* KEK until process restart — silent data
                # divergence under multi-worker uvicorn.
                if key == CONFIG_INVALIDATE_ALL or key in KMS_CONFIG_KEYS:
                    try:
                        from open_webui.utils.kms.router import (
                            reload_router as _reload_router,
                        )

                        _reload_router()
                        log.info(f"[pid={pid}] KMSRouter dropped after '{key}' change")
                    except Exception as e:
                        log.warning(
                            f"[pid={pid}] Failed to reload KMSRouter after '{key}': {e}"
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(
                f"[pid={pid}] Config invalidation subscriber error: {e}; "
                f"restarting in {backoff}s",
                exc_info=True,
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(CONFIG_INVALIDATE_CHANNEL)
                except Exception:
                    pass
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

        # CancelledError는 위에서 raise되어 여기 도달 못 함. 예외로 빠진 경우만 재시도.
        await asyncio.sleep(backoff)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_logger()

    # DB 마이그레이션 + schema 무결성 검증 (이전엔 config.py 모듈 import 시
    # 자동 실행되었으나 pytest collection 등 부작용이 있어 lifespan 으로 이동.
    # fail-loud 정책은 그대로 유지 — 실패 시 startup 즉시 중단).
    from open_webui.config import run_migrations, verify_schema_state

    run_migrations()
    verify_schema_state()

    # Suppress httpx "Event loop is closed" cleanup errors on the main loop
    import asyncio as _asyncio

    _main_loop = _asyncio.get_running_loop()
    _original_handler = _main_loop.get_exception_handler()

    def _suppress_loop_closed(loop, context):
        exc = context.get("exception")
        if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
            return
        if _original_handler:
            _original_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    _main_loop.set_exception_handler(_suppress_loop_closed)

    # Telemetry: start_logger() 이후에 초기화해야 loguru sink가 유지됨
    if _telemetry_enabled:
        from open_webui.utils.telemetry.setup import setup as setup_telemetry

        setup_telemetry(app=app, db_engine=engine)

    if RESET_CONFIG_ON_START:
        reset_config()

    if LICENSE_KEY:
        get_license_data(app, LICENSE_KEY)

    # Register audit event hooks for SQLAlchemy models
    register_audit_events()

    # Initialize Cloocus admin DB (선택적 - CLOOCUS_ADMIN_DATABASE_URL 없으면 skip)
    # 라이선스 해석 전에 초기화해야 기능 레지스트리 DB 매핑을 사용할 수 있음
    from open_webui.internal.cloocus_db import (
        run_cloocus_migrations,
        seed_feature_registry,
    )

    run_cloocus_migrations()
    seed_feature_registry()

    # Initialize Cloosphere license status
    # 개발자 모드(Cloocus DB): 기능 레지스트리 DB 기반 매핑
    # 고객사 환경: 하드코딩 TIER_INCLUDED_MODULES fallback
    from open_webui.utils.license import get_tier_modules

    app.state.LICENSE_STATUS = resolve_license_status(
        license_keys=LICENSE_KEYS.value,
        feature_keys=FEATURE_KEYS.value,
        enforcement_enabled=ENABLE_LICENSE_ENFORCEMENT.value,
        tier_modules=get_tier_modules(),
    )

    asyncio.create_task(periodic_usage_pool_cleanup())

    from open_webui.services.schedule_worker import worker_loop
    from open_webui.services.scheduler import housekeeping_loop, scheduler_loop

    asyncio.create_task(scheduler_loop(app))
    asyncio.create_task(worker_loop(app))
    asyncio.create_task(housekeeping_loop(app))

    # KG job watchdog — 2분 간격으로 stale job 감지
    from open_webui.routers.knowledge_graph import kg_job_watchdog

    async def _kg_watchdog_loop():
        await asyncio.sleep(30)  # initial delay
        while True:
            try:
                await kg_job_watchdog()
            except Exception as e:
                log.error(f"KG watchdog loop error: {e}", exc_info=True)
            await asyncio.sleep(120)  # every 2 minutes

    asyncio.create_task(_kg_watchdog_loop())

    # 백그라운드 태스크 큐 consumer (Redis 연결 시에만)
    from open_webui.services.task_queue import InProcessQueue, start_internal_consumer

    if hasattr(app.state, "task_queue") and not isinstance(
        app.state.task_queue, InProcessQueue
    ):
        asyncio.create_task(start_internal_consumer(app, app.state.config._redis))

        # 좀비 컨슈머 / stuck 메시지 자동 정리 watchdog.
        # 멀티 인스턴스 환경에서 동시 실행돼도 모든 Redis 명령이 idempotent하므로 안전.
        # cleanup_zombie_consumers: pending == 0 조건으로 작업 중 컨슈머는 절대 안 건드림.
        # reclaim_stuck_messages: idle 임계값을 작업 최대 실행 시간보다 충분히 길게 (기본 6h)
        # 잡아 진행 중 작업이 강제 종료되지 않도록 한다.
        async def _worker_cleanup_loop():
            await asyncio.sleep(300)  # 시작 후 5분 대기 (워커 안정화)
            while True:
                try:
                    if app.state.config.ENABLE_WORKER_AUTO_CLEANUP:
                        tq = app.state.task_queue
                        zombie_idle_ms = (
                            int(app.state.config.WORKER_ZOMBIE_IDLE_HOURS) * 3600_000
                        )
                        stuck_idle_ms = (
                            int(app.state.config.WORKER_STUCK_IDLE_HOURS) * 3600_000
                        )
                        deleted = await tq.cleanup_zombie_consumers(
                            idle_threshold_ms=zombie_idle_ms
                        )
                        reclaimed = await tq.reclaim_stuck_messages(
                            min_idle_ms=stuck_idle_ms
                        )
                        if deleted or reclaimed.get("reclaimed"):
                            log.info(
                                f"[worker_cleanup] zombies={deleted}, "
                                f"reclaimed={reclaimed.get('reclaimed', 0)}, "
                                f"errors={reclaimed.get('errors', 0)}"
                            )
                except Exception as e:
                    log.error(f"worker_cleanup loop error: {e}", exc_info=True)
                interval_min = max(
                    1, int(app.state.config.WORKER_CLEANUP_INTERVAL_MINUTES)
                )
                await asyncio.sleep(interval_min * 60)

        asyncio.create_task(_worker_cleanup_loop())

    # Memory governance: seed retention policies + start worker
    from open_webui.models.memory_retention_policy import RetentionPolicies

    RetentionPolicies.seed_defaults()

    from open_webui.models.memory_entity import EntityTypes

    EntityTypes.seed_defaults()

    from extension_modules.agent.memory_retention_worker import run_retention_worker

    asyncio.create_task(run_retention_worker(interval_seconds=3600))

    # 멀티워커 환경에서 PersistentConfig/OAuthManager 동기화용 invalidation subscriber.
    # AppConfig.__setattr__가 변경 발생 시 CONFIG_INVALIDATE_CHANNEL에 env_name을 publish.
    # 각 워커는 메시지 받으면 PersistentConfig.update()로 DB에서 최신값을 reload하고,
    # OAuth 관련 키이면 oauth_manager.reload()로 authlib 클라이언트를 재등록.
    # shutdown 시 태스크를 명시적으로 cancel해야 pubsub listen()이 GeneratorExit 경고
    # 없이 깔끔히 정리된다.
    config_invalidation_task: asyncio.Task | None = None
    if REDIS_URL:
        config_invalidation_task = asyncio.create_task(
            _config_invalidation_subscriber()
        )

    # Guide BM25 인덱스 백그라운드 빌드 (첫 쿼리 지연 제거).
    # 콘텐츠 hash 변경은 자동 감지·재빌드되므로 운영자 개입 불필요.
    def _warmup_guide_index():
        try:
            from extension_modules.guide_agent.bm25_retriever import warmup

            warmup()
        except Exception as e:
            log.warning(f"Guide BM25 warmup failed (non-fatal): {e}")

    asyncio.create_task(asyncio.to_thread(_warmup_guide_index))

    # LangGraph checkpointer (HITL interrupt-resume 용)
    from open_webui.internal.checkpointer import (
        close_checkpointer,
        init_checkpointer,
    )

    await init_checkpointer(app)

    try:
        yield
    finally:
        if config_invalidation_task is not None:
            config_invalidation_task.cancel()
            try:
                await config_invalidation_task
            except (asyncio.CancelledError, Exception):
                pass
        await close_checkpointer(app)


app = FastAPI(
    title="ClooSphere",
    docs_url="/docs" if ENV == "dev" else None,
    openapi_url="/openapi.json" if ENV == "dev" else None,
    redoc_url=None,
    lifespan=lifespan,
)

oauth_manager = OAuthManager(app)


# Global 500 error handler — 처리되지 않은 서버 에러 로깅
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    from starlette.responses import JSONResponse

    log.exception(f"Unhandled server error: {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.state.config = AppConfig(
    redis_url=REDIS_URL,
    redis_sentinels=get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
)

app.state.WEBUI_NAME = WEBUI_NAME
app.state.LICENSE_METADATA = None


########################################
#
# OPENTELEMETRY
#
########################################

app.state.config.ENABLE_OTEL = ENABLE_OTEL
app.state.config.OTEL_EXPORTER_OTLP_ENDPOINT = OTEL_EXPORTER_OTLP_ENDPOINT

# Telemetry: OTEL Collector 경유 또는 App Insights 직접 (둘 다 가능)
_app_insights_configured = bool(
    os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    or os.environ.get("APPINSIGHTS_INSTRUMENTATIONKEY")
)

# Telemetry setup:
# - Instrumentors: 모듈 레벨 (FastAPIInstrumentor는 app 생성 직후 필요)
# - Exporters/Loguru sink: lifespan (start_logger 이후)
_telemetry_enabled = (
    ENABLE_OTEL.value
    or os.environ.get("ENABLE_OTEL", "").lower() == "true"
    or _app_insights_configured
)

if _telemetry_enabled:
    from open_webui.utils.telemetry.setup import setup_instrumentors

    setup_instrumentors(app=app, db_engine=engine)


########################################
#
# OLLAMA
#
########################################


app.state.config.ENABLE_OLLAMA_API = ENABLE_OLLAMA_API
app.state.config.OLLAMA_BASE_URLS = OLLAMA_BASE_URLS
app.state.config.OLLAMA_API_CONFIGS = OLLAMA_API_CONFIGS

app.state.OLLAMA_MODELS = {}

########################################
#
# OPENAI
#
########################################

app.state.config.ENABLE_OPENAI_API = ENABLE_OPENAI_API
app.state.config.OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS
app.state.config.OPENAI_API_KEYS = OPENAI_API_KEYS
app.state.config.OPENAI_API_CONFIGS = OPENAI_API_CONFIGS

app.state.OPENAI_MODELS = {}

########################################
#
# TOOL SERVERS
#
########################################

app.state.config.TOOL_SERVER_CONNECTIONS = TOOL_SERVER_CONNECTIONS
app.state.TOOL_SERVERS = []

########################################
#
# STORAGE CONFIG
#
########################################

app.state.config.IMAGE_UPLOAD_MODE = IMAGE_UPLOAD_MODE
app.state.config.STORAGE_PROVIDER = STORAGE_PROVIDER
app.state.config.FILE_STORAGE_PROVIDER = FILE_STORAGE_PROVIDER
app.state.config.FILE_S3_BUCKET_NAME = FILE_S3_BUCKET_NAME
app.state.config.FILE_S3_REGION_NAME = FILE_S3_REGION_NAME
app.state.config.FILE_S3_ENDPOINT_URL = FILE_S3_ENDPOINT_URL
app.state.config.FILE_S3_ACCESS_KEY_ID = FILE_S3_ACCESS_KEY_ID
app.state.config.FILE_S3_SECRET_ACCESS_KEY = FILE_S3_SECRET_ACCESS_KEY
app.state.config.FILE_S3_KEY_PREFIX = FILE_S3_KEY_PREFIX
app.state.config.FILE_GCS_BUCKET_NAME = FILE_GCS_BUCKET_NAME
app.state.config.FILE_GCS_CREDENTIALS_JSON = FILE_GCS_CREDENTIALS_JSON
app.state.config.FILE_AZURE_STORAGE_ENDPOINT = FILE_AZURE_STORAGE_ENDPOINT
app.state.config.FILE_AZURE_STORAGE_CONTAINER_NAME = FILE_AZURE_STORAGE_CONTAINER_NAME
app.state.config.FILE_AZURE_STORAGE_KEY = FILE_AZURE_STORAGE_KEY
app.state.config.S3_BUCKET_NAME = S3_BUCKET_NAME
app.state.config.S3_REGION_NAME = S3_REGION_NAME
app.state.config.S3_ENDPOINT_URL = S3_ENDPOINT_URL
app.state.config.S3_ACCESS_KEY_ID = S3_ACCESS_KEY_ID
app.state.config.S3_SECRET_ACCESS_KEY = S3_SECRET_ACCESS_KEY
app.state.config.S3_KEY_PREFIX = S3_KEY_PREFIX
app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY = GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY
app.state.config.GOOGLE_CLOUD_ENABLED = GOOGLE_CLOUD_ENABLED

# KMS / Key Management
app.state.config.KMS_PROVIDER = KMS_PROVIDER
app.state.config.KMS_AZURE_KEY_VAULT_KEY_URI = KMS_AZURE_KEY_VAULT_KEY_URI
app.state.config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED = (
    KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED
)
app.state.config.KMS_AZURE_TENANT_ID = KMS_AZURE_TENANT_ID
app.state.config.KMS_AZURE_CLIENT_ID = KMS_AZURE_CLIENT_ID
app.state.config.KMS_AZURE_CLIENT_SECRET = KMS_AZURE_CLIENT_SECRET
# Auto-rotation (Phase 4.5)
app.state.config.KMS_ROTATION_AUTO_ENABLED = KMS_ROTATION_AUTO_ENABLED
app.state.config.KMS_ROTATION_CHECK_INTERVAL_HOURS = KMS_ROTATION_CHECK_INTERVAL_HOURS
app.state.config.KMS_ROTATION_DRY_RUN = KMS_ROTATION_DRY_RUN
app.state.config.KMS_ROTATION_LAST_CHECK_AT = KMS_ROTATION_LAST_CHECK_AT
app.state.config.KMS_ROTATION_LAST_RESULT = KMS_ROTATION_LAST_RESULT

# Bootstrap-order fix for managed-KMS deployments:
# `CONFIG_DATA = get_config()` at config.py module load runs a first
# `get_router()` which lazy-attaches the configured provider via
# `from open_webui.config import KMS_PROVIDER` — but config.py is still
# mid-import, so KMS_PROVIDER raises ImportError and the router stays on
# Fernet. azkv-env ciphertext survives un-decrypted in CONFIG_DATA and
# leaks into every PersistentConfig.value that later reads from it.
# Drop the stale router and rerun the registry refresh now that
# KMS_PROVIDER is available.
from open_webui.utils.kms.router import reload_router as _reload_kms_router

_reload_kms_router()

from open_webui.config import reload_all_persistent_configs  # noqa: E402

try:
    refreshed, failed = reload_all_persistent_configs()
    if failed:
        log.error(
            "Bootstrap reload: %d/%d PersistentConfigs failed to refresh — "
            "ciphertext may persist for: %s",
            len(failed),
            refreshed + len(failed),
            [name for name, _ in failed[:10]],
        )
    else:
        log.info("Bootstrap reload: refreshed %d PersistentConfigs post-KMS", refreshed)
except Exception as e:
    log.error(
        "Bootstrap reload aborted — encrypted configs may stay as ciphertext: %s", e
    )

app.state.config.GCS_BUCKET_NAME = GCS_BUCKET_NAME
app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON = (
    GOOGLE_APPLICATION_CREDENTIALS_JSON
)
app.state.config.AZURE_STORAGE_ENDPOINT = AZURE_STORAGE_ENDPOINT
app.state.config.AZURE_STORAGE_CONTAINER_NAME = AZURE_STORAGE_CONTAINER_NAME
app.state.config.AZURE_STORAGE_KEY = AZURE_STORAGE_KEY

########################################
#
# DIRECT CONNECTIONS
#
########################################

app.state.config.ENABLE_DIRECT_CONNECTIONS = ENABLE_DIRECT_CONNECTIONS
app.state.config.ENABLE_HITL = ENABLE_HITL

########################################
#
# WEBUI
#
########################################

app.state.config.WEBUI_URL = WEBUI_URL
app.state.config.ENABLE_SIGNUP = ENABLE_SIGNUP
app.state.config.ENABLE_ONBOARDING = ENABLE_ONBOARDING
app.state.config.ENABLE_LOGIN_FORM = ENABLE_LOGIN_FORM

app.state.config.ENABLE_API_KEY = ENABLE_API_KEY
app.state.config.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS = (
    ENABLE_API_KEY_ENDPOINT_RESTRICTIONS
)
app.state.config.API_KEY_ALLOWED_ENDPOINTS = API_KEY_ALLOWED_ENDPOINTS

app.state.config.JWT_EXPIRES_IN = JWT_EXPIRES_IN

app.state.config.SHOW_ADMIN_DETAILS = SHOW_ADMIN_DETAILS
app.state.config.ADMIN_EMAIL = ADMIN_EMAIL


app.state.config.DEFAULT_MODELS = DEFAULT_MODELS
app.state.config.DEFAULT_PROMPT_SUGGESTIONS = DEFAULT_PROMPT_SUGGESTIONS
app.state.config.DEFAULT_USER_ROLE = DEFAULT_USER_ROLE

app.state.config.USER_PERMISSIONS = USER_PERMISSIONS
app.state.config.WEBHOOK_URL = WEBHOOK_URL

# Email / Notifications
app.state.config.EMAIL_ENGINE = EMAIL_ENGINE
app.state.config.SMTP_SERVER = SMTP_SERVER
app.state.config.SMTP_PORT = SMTP_PORT
app.state.config.SMTP_USERNAME = SMTP_USERNAME
app.state.config.SMTP_PASSWORD = SMTP_PASSWORD
app.state.config.SMTP_USE_TLS = SMTP_USE_TLS
app.state.config.SMTP_USE_SSL = SMTP_USE_SSL
app.state.config.SMTP_FROM_ADDRESS = SMTP_FROM_ADDRESS
app.state.config.SMTP_FROM_NAME = SMTP_FROM_NAME
app.state.config.SENDGRID_API_KEY = SENDGRID_API_KEY
app.state.config.SENDGRID_FROM_ADDRESS = SENDGRID_FROM_ADDRESS
app.state.config.SENDGRID_FROM_NAME = SENDGRID_FROM_NAME
app.state.config.WEBHOOK_PROVIDER = WEBHOOK_PROVIDER
app.state.config.NOTIFICATION_EVENTS = NOTIFICATION_EVENTS
app.state.config.NOTIFICATION_EMAIL_CHANNELS = NOTIFICATION_EMAIL_CHANNELS
app.state.config.NOTIFICATION_WEBHOOK_CHANNELS = NOTIFICATION_WEBHOOK_CHANNELS

app.state.config.TEAMS_BOT_ENABLED = TEAMS_BOT_ENABLED
app.state.config.TEAMS_BOT_APP_ID = TEAMS_BOT_APP_ID
app.state.config.TEAMS_BOT_APP_PASSWORD = TEAMS_BOT_APP_PASSWORD
app.state.config.TEAMS_BOT_TENANT_ID = TEAMS_BOT_TENANT_ID
app.state.config.TEAMS_BOT_MODEL_ID = TEAMS_BOT_MODEL_ID
app.state.config.TEAMS_BOT_NAME = TEAMS_BOT_NAME
app.state.config.TEAMS_BOT_DESCRIPTION_SHORT = TEAMS_BOT_DESCRIPTION_SHORT
app.state.config.TEAMS_BOT_DESCRIPTION_FULL = TEAMS_BOT_DESCRIPTION_FULL
app.state.config.TEAMS_BOT_DEVELOPER_NAME = TEAMS_BOT_DEVELOPER_NAME
app.state.config.TEAMS_BOT_DEVELOPER_WEBSITE = TEAMS_BOT_DEVELOPER_WEBSITE
app.state.config.TEAMS_BOT_COLOR_ICON = TEAMS_BOT_COLOR_ICON
app.state.config.TEAMS_BOT_OUTLINE_ICON = TEAMS_BOT_OUTLINE_ICON
app.state.config.TEAMS_BOT_SCOPES = TEAMS_BOT_SCOPES
app.state.config.TEAMS_BOT_ACCENT_COLOR = TEAMS_BOT_ACCENT_COLOR
app.state.config.TEAMS_BOT_DEFAULT_GROUP_CAPABILITY = TEAMS_BOT_DEFAULT_GROUP_CAPABILITY

# Branding
app.state.config.BRANDING_APP_NAME = BRANDING_APP_NAME
if BRANDING_APP_NAME.value:
    app.state.WEBUI_NAME = BRANDING_APP_NAME.value

app.state.config.BRANDING_FAVICON_URL = BRANDING_FAVICON_URL
app.state.config.BRANDING_FAVICON_DARK_URL = BRANDING_FAVICON_DARK_URL
app.state.config.BRANDING_LOGO_URL = BRANDING_LOGO_URL
app.state.config.BRANDING_SPLASH_URL = BRANDING_SPLASH_URL
app.state.config.BRANDING_SPLASH_DARK_URL = BRANDING_SPLASH_DARK_URL
app.state.config.BRANDING_BROWSER_FAVICON_URL = BRANDING_BROWSER_FAVICON_URL

# Document Templates (admin-uploaded master files inherited by document tools)
app.state.config.DOCUMENT_TEMPLATE_PPTX = DOCUMENT_TEMPLATE_PPTX
app.state.config.DOCUMENT_TEMPLATE_DOCX = DOCUMENT_TEMPLATE_DOCX
app.state.config.DOCUMENT_TEMPLATE_XLSX = DOCUMENT_TEMPLATE_XLSX

app.state.config.PRESENTON_ENABLED = PRESENTON_ENABLED
app.state.config.PRESENTON_BASE_URL = PRESENTON_BASE_URL
app.state.config.PRESENTON_TIMEOUT = PRESENTON_TIMEOUT
app.state.config.PRESENTON_DEFAULT_TEMPLATE = PRESENTON_DEFAULT_TEMPLATE

app.state.config.BANNERS = WEBUI_BANNERS
app.state.config.MODEL_ORDER_LIST = MODEL_ORDER_LIST


app.state.config.ENABLE_CHANNELS = ENABLE_CHANNELS
app.state.config.ENABLE_COMMUNITY_SHARING = ENABLE_COMMUNITY_SHARING

# External Worker

# TaskQueue 초기화 (Redis 연결 시 Redis Streams, 아닐 시 InProcess)
from open_webui.services.task_queue import create_task_queue

app.state.task_queue = create_task_queue(app.state.config._redis)

########################################
#
# CODE GATEWAY
#
########################################

app.state.config.ENABLE_CODE_GATEWAY = ENABLE_CODE_GATEWAY
app.state.config.CODE_GATEWAY_PROVIDERS = CODE_GATEWAY_PROVIDERS
app.state.config.CODE_GATEWAY_GUARDRAIL_IDS = CODE_GATEWAY_GUARDRAIL_IDS
app.state.config.CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL = (
    CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL
)
app.state.config.CODE_GATEWAY_RATE_LIMIT = CODE_GATEWAY_RATE_LIMIT
app.state.config.CODE_GATEWAY_ALLOWED_MODELS = CODE_GATEWAY_ALLOWED_MODELS
app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS = CODE_GATEWAY_BLOCKED_FILE_PATTERNS
app.state.config.CODE_GATEWAY_BLOCKED_FILE_ACTION = CODE_GATEWAY_BLOCKED_FILE_ACTION
app.state.config.CODE_GATEWAY_BLOCKED_REPOS = CODE_GATEWAY_BLOCKED_REPOS
app.state.config.CODE_GATEWAY_REQUIRE_REPO_METADATA = CODE_GATEWAY_REQUIRE_REPO_METADATA
app.state.config.CODE_GATEWAY_MISSING_METADATA_ACTION = (
    CODE_GATEWAY_MISSING_METADATA_ACTION
)
app.state.config.ENABLE_MESSAGE_RATING = ENABLE_MESSAGE_RATING
app.state.config.ENABLE_USER_WEBHOOKS = ENABLE_USER_WEBHOOKS

app.state.config.ENABLE_USAGE_LIMIT = ENABLE_USAGE_LIMIT
app.state.config.USAGE_LIMIT_DEFAULT_DAILY_TOKENS = USAGE_LIMIT_DEFAULT_DAILY_TOKENS
app.state.config.USAGE_LIMIT_EXCEED_ACTION = USAGE_LIMIT_EXCEED_ACTION
app.state.config.USAGE_LIMIT_PER_MODEL = USAGE_LIMIT_PER_MODEL

app.state.config.ENABLE_DATA_RETENTION = ENABLE_DATA_RETENTION
app.state.config.DATA_RETENTION_CLEANUP_HOUR = DATA_RETENTION_CLEANUP_HOUR
app.state.config.RETENTION_DAYS_USAGE = RETENTION_DAYS_USAGE
app.state.config.RETENTION_DAYS_AUDIT_LOG = RETENTION_DAYS_AUDIT_LOG
app.state.config.RETENTION_DAYS_GUARDRAIL_LOG = RETENTION_DAYS_GUARDRAIL_LOG
app.state.config.RETENTION_DAYS_TRACE = RETENTION_DAYS_TRACE
app.state.config.RETENTION_DAYS_TRACE_ANALYSIS = RETENTION_DAYS_TRACE_ANALYSIS
app.state.config.RETENTION_DAYS_AUTO_EVALUATION = RETENTION_DAYS_AUTO_EVALUATION
app.state.config.ENABLE_WORKER_AUTO_CLEANUP = ENABLE_WORKER_AUTO_CLEANUP
app.state.config.WORKER_ZOMBIE_IDLE_HOURS = WORKER_ZOMBIE_IDLE_HOURS
app.state.config.WORKER_STUCK_IDLE_HOURS = WORKER_STUCK_IDLE_HOURS
app.state.config.WORKER_CLEANUP_INTERVAL_MINUTES = WORKER_CLEANUP_INTERVAL_MINUTES

app.state.config.ENABLE_EVALUATION_ARENA_MODELS = ENABLE_EVALUATION_ARENA_MODELS
app.state.config.EVALUATION_ARENA_MODELS = EVALUATION_ARENA_MODELS

app.state.config.OAUTH_USERNAME_CLAIM = OAUTH_USERNAME_CLAIM
app.state.config.OAUTH_PICTURE_CLAIM = OAUTH_PICTURE_CLAIM
app.state.config.OAUTH_EMAIL_CLAIM = OAUTH_EMAIL_CLAIM

app.state.config.ENABLE_OAUTH_ROLE_MANAGEMENT = ENABLE_OAUTH_ROLE_MANAGEMENT
app.state.config.OAUTH_ROLES_CLAIM = OAUTH_ROLES_CLAIM
app.state.config.OAUTH_ALLOWED_ROLES = OAUTH_ALLOWED_ROLES
app.state.config.OAUTH_ADMIN_ROLES = OAUTH_ADMIN_ROLES

app.state.config.ENABLE_LDAP = ENABLE_LDAP
app.state.config.LDAP_SERVER_LABEL = LDAP_SERVER_LABEL
app.state.config.LDAP_SERVER_HOST = LDAP_SERVER_HOST
app.state.config.LDAP_SERVER_PORT = LDAP_SERVER_PORT
app.state.config.LDAP_ATTRIBUTE_FOR_MAIL = LDAP_ATTRIBUTE_FOR_MAIL
app.state.config.LDAP_ATTRIBUTE_FOR_USERNAME = LDAP_ATTRIBUTE_FOR_USERNAME
app.state.config.LDAP_APP_DN = LDAP_APP_DN
app.state.config.LDAP_APP_PASSWORD = LDAP_APP_PASSWORD
app.state.config.LDAP_SEARCH_BASE = LDAP_SEARCH_BASE
app.state.config.LDAP_SEARCH_FILTERS = LDAP_SEARCH_FILTERS
app.state.config.LDAP_USE_TLS = LDAP_USE_TLS
app.state.config.LDAP_CA_CERT_FILE = LDAP_CA_CERT_FILE
app.state.config.LDAP_CIPHERS = LDAP_CIPHERS


app.state.AUTH_TRUSTED_EMAIL_HEADER = WEBUI_AUTH_TRUSTED_EMAIL_HEADER
app.state.AUTH_TRUSTED_NAME_HEADER = WEBUI_AUTH_TRUSTED_NAME_HEADER
app.state.EXTERNAL_PWA_MANIFEST_URL = EXTERNAL_PWA_MANIFEST_URL

app.state.USER_COUNT = None
app.state.TOOLS = {}
app.state.FUNCTIONS = {}

########################################
#
# RETRIEVAL
#
########################################


app.state.config.TOP_K = RAG_TOP_K
app.state.config.FILE_MAX_SIZE = RAG_FILE_MAX_SIZE
app.state.config.FILE_MAX_COUNT = RAG_FILE_MAX_COUNT
app.state.config.PDF_CONVERT_EXTENSIONS = PDF_CONVERT_EXTENSIONS
app.state.config.ALLOWED_FILE_EXTENSIONS = ALLOWED_FILE_EXTENSIONS

# Global Guardrails
app.state.config.ENABLE_GLOBAL_GUARDRAIL = ENABLE_GLOBAL_GUARDRAIL
app.state.config.GLOBAL_GUARDRAIL_IDS = GLOBAL_GUARDRAIL_IDS

# File Upload Guardrails
app.state.config.FILE_GUARDRAIL_ENABLED = FILE_GUARDRAIL_ENABLED
app.state.config.FILE_GUARDRAIL_SCOPES = FILE_GUARDRAIL_SCOPES
app.state.config.FILE_GUARDRAIL_IDS = FILE_GUARDRAIL_IDS
app.state.config.FILE_GUARDRAIL_EXIF_ENABLED = FILE_GUARDRAIL_EXIF_ENABLED
app.state.config.FILE_GUARDRAIL_MACRO_ENABLED = FILE_GUARDRAIL_MACRO_ENABLED
app.state.config.FILE_GUARDRAIL_MACRO_ACTION = FILE_GUARDRAIL_MACRO_ACTION
app.state.config.FILE_GUARDRAIL_NSFW_ENABLED = FILE_GUARDRAIL_NSFW_ENABLED
app.state.config.FILE_GUARDRAIL_NSFW_MODEL = FILE_GUARDRAIL_NSFW_MODEL
app.state.config.FILE_GUARDRAIL_NSFW_PROMPT = FILE_GUARDRAIL_NSFW_PROMPT
app.state.config.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES = FILE_GUARDRAIL_NSFW_PASS_EXAMPLES
app.state.config.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES = FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_ENABLED = (
    FILE_GUARDRAIL_CLASSIFICATION_ENABLED
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_MODEL = (
    FILE_GUARDRAIL_CLASSIFICATION_MODEL
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_PROMPT = (
    FILE_GUARDRAIL_CLASSIFICATION_PROMPT
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES = (
    FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES = (
    FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS = (
    FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS
)
app.state.config.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES = (
    FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES
)


app.state.config.RAG_FULL_CONTEXT = RAG_FULL_CONTEXT
app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL = BYPASS_EMBEDDING_AND_RETRIEVAL
app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION = ENABLE_WEB_LOADER_SSL_VERIFICATION

app.state.config.CONTENT_EXTRACTION_ENGINE = CONTENT_EXTRACTION_ENGINE
app.state.config.TIKA_SERVER_URL = TIKA_SERVER_URL
app.state.config.DOCLING_SERVER_URL = DOCLING_SERVER_URL
app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT = DOCUMENT_INTELLIGENCE_ENDPOINT
app.state.config.DOCUMENT_INTELLIGENCE_KEY = DOCUMENT_INTELLIGENCE_KEY
app.state.config.MISTRAL_OCR_API_KEY = MISTRAL_OCR_API_KEY
app.state.config.DOCUMENT_AI_PROJECT_ID = DOCUMENT_AI_PROJECT_ID
app.state.config.DOCUMENT_AI_LOCATION = DOCUMENT_AI_LOCATION
app.state.config.DOCUMENT_AI_PROCESSOR_ID = DOCUMENT_AI_PROCESSOR_ID
app.state.config.DOCUMENT_AI_PROCESSOR_VERSION = DOCUMENT_AI_PROCESSOR_VERSION
app.state.config.DOCUMENT_AI_SERVICE_ACCOUNT_KEY = DOCUMENT_AI_SERVICE_ACCOUNT_KEY

app.state.config.TEXT_SPLITTER = RAG_TEXT_SPLITTER
app.state.config.TIKTOKEN_ENCODING_NAME = TIKTOKEN_ENCODING_NAME

app.state.config.CHUNK_SIZE = CHUNK_SIZE
app.state.config.CHUNK_OVERLAP = CHUNK_OVERLAP
app.state.config.RAG_CHUNK_MAX_TOKENS = RAG_CHUNK_MAX_TOKENS
app.state.config.RAG_CHUNK_MIN_TOKENS = RAG_CHUNK_MIN_TOKENS

app.state.config.RAG_EMBEDDING_ENGINE = RAG_EMBEDDING_ENGINE
app.state.config.RAG_EMBEDDING_MODEL = RAG_EMBEDDING_MODEL
app.state.config.RAG_EMBEDDING_BATCH_SIZE = RAG_EMBEDDING_BATCH_SIZE
app.state.config.RAG_EMBEDDING_DIMENSIONS = RAG_EMBEDDING_DIMENSIONS
app.state.config.RAG_TEMPLATE = RAG_TEMPLATE

app.state.config.RAG_OPENAI_API_BASE_URL = RAG_OPENAI_API_BASE_URL
app.state.config.RAG_OPENAI_API_KEY = RAG_OPENAI_API_KEY

app.state.config.RAG_OLLAMA_BASE_URL = RAG_OLLAMA_BASE_URL
app.state.config.RAG_OLLAMA_API_KEY = RAG_OLLAMA_API_KEY

app.state.config.RAG_AZURE_OPENAI_API_BASE_URL = RAG_AZURE_OPENAI_API_BASE_URL
app.state.config.RAG_AZURE_OPENAI_API_KEY = RAG_AZURE_OPENAI_API_KEY
app.state.config.RAG_AZURE_OPENAI_API_VERSION = RAG_AZURE_OPENAI_API_VERSION

app.state.config.RAG_GEMINI_API_KEY = RAG_GEMINI_API_KEY
app.state.config.RAG_VERTEX_AI_PROJECT_ID = RAG_VERTEX_AI_PROJECT_ID
app.state.config.RAG_VERTEX_AI_LOCATION = RAG_VERTEX_AI_LOCATION
app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY = RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY

# KB Question Generation settings
app.state.config.KB_QUESTION_GENERATION_ENABLED = KB_QUESTION_GENERATION_ENABLED
app.state.config.KB_QUESTION_GENERATION_MODEL = KB_QUESTION_GENERATION_MODEL
app.state.config.KB_MAX_QUESTIONS_PER_CHUNK = KB_MAX_QUESTIONS_PER_CHUNK
app.state.config.KB_QUESTION_VECTOR_WEIGHT = KB_QUESTION_VECTOR_WEIGHT

app.state.config.PDF_EXTRACT_IMAGES = PDF_EXTRACT_IMAGES

app.state.config.YOUTUBE_LOADER_LANGUAGE = YOUTUBE_LOADER_LANGUAGE
app.state.config.YOUTUBE_LOADER_PROXY_URL = YOUTUBE_LOADER_PROXY_URL


app.state.config.ENABLE_WEB_SEARCH = ENABLE_WEB_SEARCH
app.state.config.WEB_SEARCH_ENGINE = WEB_SEARCH_ENGINE
app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST = WEB_SEARCH_DOMAIN_FILTER_LIST
app.state.config.WEB_SEARCH_RESULT_COUNT = WEB_SEARCH_RESULT_COUNT
app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS = WEB_SEARCH_CONCURRENT_REQUESTS
app.state.config.WEB_LOADER_ENGINE = WEB_LOADER_ENGINE
app.state.config.WEB_SEARCH_TRUST_ENV = WEB_SEARCH_TRUST_ENV
app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL = (
    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
)

app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION = ENABLE_GOOGLE_DRIVE_INTEGRATION
app.state.config.ENABLE_ONEDRIVE_INTEGRATION = ENABLE_ONEDRIVE_INTEGRATION
app.state.config.ENABLE_SHAREPOINT_INTEGRATION = ENABLE_SHAREPOINT_INTEGRATION

# Gmail / Calendar / Drive 채팅 통합 (admin 토글). LLM tool 5축 게이트의 1단계.
app.state.config.ENABLE_GMAIL_INTEGRATION = ENABLE_GMAIL_INTEGRATION
app.state.config.ENABLE_CALENDAR_INTEGRATION = ENABLE_CALENDAR_INTEGRATION
app.state.config.ENABLE_DRIVE_INTEGRATION = ENABLE_DRIVE_INTEGRATION

app.state.config.SEARXNG_QUERY_URL = SEARXNG_QUERY_URL
app.state.config.GOOGLE_PSE_API_KEY = GOOGLE_PSE_API_KEY
app.state.config.GOOGLE_PSE_ENGINE_ID = GOOGLE_PSE_ENGINE_ID
app.state.config.BRAVE_SEARCH_API_KEY = BRAVE_SEARCH_API_KEY
app.state.config.KAGI_SEARCH_API_KEY = KAGI_SEARCH_API_KEY
app.state.config.MOJEEK_SEARCH_API_KEY = MOJEEK_SEARCH_API_KEY
app.state.config.BOCHA_SEARCH_API_KEY = BOCHA_SEARCH_API_KEY
app.state.config.SERPSTACK_API_KEY = SERPSTACK_API_KEY
app.state.config.SERPSTACK_HTTPS = SERPSTACK_HTTPS
app.state.config.SERPER_API_KEY = SERPER_API_KEY
app.state.config.SERPLY_API_KEY = SERPLY_API_KEY
app.state.config.TAVILY_API_KEY = TAVILY_API_KEY
app.state.config.SEARCHAPI_API_KEY = SEARCHAPI_API_KEY
app.state.config.SEARCHAPI_ENGINE = SEARCHAPI_ENGINE
app.state.config.SERPAPI_API_KEY = SERPAPI_API_KEY
app.state.config.SERPAPI_ENGINE = SERPAPI_ENGINE
app.state.config.JINA_API_KEY = JINA_API_KEY
app.state.config.BING_SEARCH_V7_ENDPOINT = BING_SEARCH_V7_ENDPOINT
app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY = BING_SEARCH_V7_SUBSCRIPTION_KEY
app.state.config.EXA_API_KEY = EXA_API_KEY
app.state.config.PERPLEXITY_API_KEY = PERPLEXITY_API_KEY
app.state.config.SOUGOU_API_SID = SOUGOU_API_SID
app.state.config.SOUGOU_API_SK = SOUGOU_API_SK

# Search Engine Config (extension_modules/search_engine)
app.state.config.SEARCH_ENGINE_TYPE = SEARCH_ENGINE_TYPE
app.state.config.SEARCH_ENGINE_AZURE_ENDPOINT = SEARCH_ENGINE_AZURE_ENDPOINT
app.state.config.SEARCH_ENGINE_AZURE_API_KEY = SEARCH_ENGINE_AZURE_API_KEY
app.state.config.SEARCH_ENGINE_AZURE_API_VERSION = SEARCH_ENGINE_AZURE_API_VERSION
app.state.config.SEARCH_ENGINE_PGVECTOR_HOST = SEARCH_ENGINE_PGVECTOR_HOST
app.state.config.SEARCH_ENGINE_PGVECTOR_PORT = SEARCH_ENGINE_PGVECTOR_PORT
app.state.config.SEARCH_ENGINE_PGVECTOR_DATABASE = SEARCH_ENGINE_PGVECTOR_DATABASE
app.state.config.SEARCH_ENGINE_PGVECTOR_USER = SEARCH_ENGINE_PGVECTOR_USER
app.state.config.SEARCH_ENGINE_PGVECTOR_PASSWORD = SEARCH_ENGINE_PGVECTOR_PASSWORD
app.state.config.SEARCH_ENGINE_MILVUS_HOST = SEARCH_ENGINE_MILVUS_HOST
app.state.config.SEARCH_ENGINE_MILVUS_PORT = SEARCH_ENGINE_MILVUS_PORT
app.state.config.SEARCH_ENGINE_MILVUS_USER = SEARCH_ENGINE_MILVUS_USER
app.state.config.SEARCH_ENGINE_MILVUS_PASSWORD = SEARCH_ENGINE_MILVUS_PASSWORD
app.state.config.SEARCH_ENGINE_ELASTICSEARCH_URL = SEARCH_ENGINE_ELASTICSEARCH_URL
app.state.config.SEARCH_ENGINE_ELASTICSEARCH_API_KEY = (
    SEARCH_ENGINE_ELASTICSEARCH_API_KEY
)
app.state.config.SEARCH_ENGINE_ELASTICSEARCH_USER = SEARCH_ENGINE_ELASTICSEARCH_USER
app.state.config.SEARCH_ENGINE_ELASTICSEARCH_PASSWORD = (
    SEARCH_ENGINE_ELASTICSEARCH_PASSWORD
)
app.state.config.SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS = (
    SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS
)
app.state.config.SEARCH_ENGINE_VERTEX_PROJECT_ID = SEARCH_ENGINE_VERTEX_PROJECT_ID
app.state.config.SEARCH_ENGINE_VERTEX_LOCATION = SEARCH_ENGINE_VERTEX_LOCATION
app.state.config.SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY = (
    SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY
)

# Reranker
app.state.config.RERANKER_TYPE = RERANKER_TYPE
app.state.config.RERANKER_VERTEX_PROJECT_ID = RERANKER_VERTEX_PROJECT_ID
app.state.config.RERANKER_VERTEX_LOCATION = RERANKER_VERTEX_LOCATION
app.state.config.RERANKER_VERTEX_MODEL = RERANKER_VERTEX_MODEL
app.state.config.RERANKER_VERTEX_SERVICE_ACCOUNT_KEY = (
    RERANKER_VERTEX_SERVICE_ACCOUNT_KEY
)

# Search Engine 검색 설정
app.state.config.SEARCH_ENGINE_TOP_K = SEARCH_ENGINE_TOP_K
app.state.config.SEARCH_ENGINE_RERANKER_TOP_K = SEARCH_ENGINE_RERANKER_TOP_K
app.state.config.SEARCH_ENGINE_RERANKER_THRESHOLD = SEARCH_ENGINE_RERANKER_THRESHOLD
app.state.config.SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED = (
    SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED
)

app.state.config.PLAYWRIGHT_WS_URL = PLAYWRIGHT_WS_URL
app.state.config.PLAYWRIGHT_TIMEOUT = PLAYWRIGHT_TIMEOUT
app.state.config.FIRECRAWL_API_BASE_URL = FIRECRAWL_API_BASE_URL
app.state.config.FIRECRAWL_API_KEY = FIRECRAWL_API_KEY
app.state.config.TAVILY_EXTRACT_DEPTH = TAVILY_EXTRACT_DEPTH

# Cloosphere License - register for Redis sync across workers
app.state.config.LICENSE_KEYS = LICENSE_KEYS
app.state.config.FEATURE_KEYS = FEATURE_KEYS
app.state.config.ENABLE_LICENSE_ENFORCEMENT = ENABLE_LICENSE_ENFORCEMENT

app.state.EMBEDDING_FUNCTION = None
app.state.ef = None

app.state.YOUTUBE_LOADER_TRANSLATION = None


try:
    app.state.ef = get_ef(
        app.state.config.RAG_EMBEDDING_ENGINE,
        app.state.config.RAG_EMBEDDING_MODEL,
        RAG_EMBEDDING_MODEL_AUTO_UPDATE,
    )
except Exception as e:
    log.error(f"Error updating models: {e}")
    pass

app.state.EMBEDDING_FUNCTION = get_embedding_function(
    app.state.config.RAG_EMBEDDING_ENGINE,
    app.state.config.RAG_EMBEDDING_MODEL,
    app.state.ef,
    (
        app.state.config.RAG_AZURE_OPENAI_API_BASE_URL
        if app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
        else (
            app.state.config.RAG_OPENAI_API_BASE_URL
            if app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                ""
                if app.state.config.RAG_EMBEDDING_ENGINE in ["gemini", "vertex_ai"]
                else app.state.config.RAG_OLLAMA_BASE_URL
            )
        )
    ),
    (
        app.state.config.RAG_AZURE_OPENAI_API_KEY
        if app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
        else (
            app.state.config.RAG_OPENAI_API_KEY
            if app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                app.state.config.RAG_GEMINI_API_KEY
                if app.state.config.RAG_EMBEDDING_ENGINE == "gemini"
                else (
                    ""
                    if app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
                    else app.state.config.RAG_OLLAMA_API_KEY
                )
            )
        )
    ),
    app.state.config.RAG_EMBEDDING_BATCH_SIZE,
    azure_api_version=(
        app.state.config.RAG_AZURE_OPENAI_API_VERSION
        if app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
        else None
    ),
    vertex_ai_project_id=(
        app.state.config.RAG_VERTEX_AI_PROJECT_ID
        if app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
        else None
    ),
    vertex_ai_location=(
        app.state.config.RAG_VERTEX_AI_LOCATION
        if app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
        else None
    ),
    vertex_ai_service_account_key=(
        app.state.config.RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY
        if app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
        else None
    ),
    google_cloud_service_account_key=(
        app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY
        if app.state.config.RAG_EMBEDDING_ENGINE == "vertex_ai"
        else None
    ),
)

########################################
#
# CODE EXECUTION
#
########################################

app.state.config.ENABLE_CODE_EXECUTION = ENABLE_CODE_EXECUTION
app.state.config.CODE_EXECUTION_ENGINE = CODE_EXECUTION_ENGINE
app.state.config.CODE_EXECUTION_JUPYTER_URL = CODE_EXECUTION_JUPYTER_URL
app.state.config.CODE_EXECUTION_JUPYTER_AUTH = CODE_EXECUTION_JUPYTER_AUTH
app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN = CODE_EXECUTION_JUPYTER_AUTH_TOKEN
app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD = (
    CODE_EXECUTION_JUPYTER_AUTH_PASSWORD
)
app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT = CODE_EXECUTION_JUPYTER_TIMEOUT

########################################
#
# IMAGES
#
########################################

app.state.config.IMAGE_GENERATION_ENGINE = IMAGE_GENERATION_ENGINE
app.state.config.ENABLE_IMAGE_GENERATION = ENABLE_IMAGE_GENERATION
app.state.config.ENABLE_IMAGE_PROMPT_GENERATION = ENABLE_IMAGE_PROMPT_GENERATION

app.state.config.IMAGES_OPENAI_API_BASE_URL = IMAGES_OPENAI_API_BASE_URL
app.state.config.IMAGES_OPENAI_API_KEY = IMAGES_OPENAI_API_KEY

app.state.config.IMAGES_GEMINI_API_BASE_URL = IMAGES_GEMINI_API_BASE_URL
app.state.config.IMAGES_GEMINI_API_KEY = IMAGES_GEMINI_API_KEY

app.state.config.IMAGES_AZURE_OPENAI_API_BASE_URL = IMAGES_AZURE_OPENAI_API_BASE_URL
app.state.config.IMAGES_AZURE_OPENAI_API_KEY = IMAGES_AZURE_OPENAI_API_KEY
app.state.config.IMAGES_AZURE_OPENAI_API_VERSION = IMAGES_AZURE_OPENAI_API_VERSION
app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME = (
    IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME
)
app.state.config.IMAGES_AZURE_OPENAI_QUALITY = IMAGES_AZURE_OPENAI_QUALITY
app.state.config.IMAGES_AZURE_OPENAI_OUTPUT_FORMAT = IMAGES_AZURE_OPENAI_OUTPUT_FORMAT
app.state.config.IMAGES_AZURE_OPENAI_BACKGROUND = IMAGES_AZURE_OPENAI_BACKGROUND

app.state.config.IMAGES_VERTEX_AI_PROJECT_ID = IMAGES_VERTEX_AI_PROJECT_ID
app.state.config.IMAGES_VERTEX_AI_LOCATION = IMAGES_VERTEX_AI_LOCATION
app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY = (
    IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY
)

app.state.config.IMAGE_GENERATION_MODEL = IMAGE_GENERATION_MODEL

app.state.config.AUTOMATIC1111_BASE_URL = AUTOMATIC1111_BASE_URL
app.state.config.AUTOMATIC1111_API_AUTH = AUTOMATIC1111_API_AUTH
app.state.config.AUTOMATIC1111_CFG_SCALE = AUTOMATIC1111_CFG_SCALE
app.state.config.AUTOMATIC1111_SAMPLER = AUTOMATIC1111_SAMPLER
app.state.config.AUTOMATIC1111_SCHEDULER = AUTOMATIC1111_SCHEDULER
app.state.config.COMFYUI_BASE_URL = COMFYUI_BASE_URL
app.state.config.COMFYUI_API_KEY = COMFYUI_API_KEY
app.state.config.COMFYUI_WORKFLOW = COMFYUI_WORKFLOW
app.state.config.COMFYUI_WORKFLOW_NODES = COMFYUI_WORKFLOW_NODES

app.state.config.IMAGE_SIZE = IMAGE_SIZE
app.state.config.IMAGE_STEPS = IMAGE_STEPS
app.state.config.IMAGE_API_URLS = IMAGE_API_URLS
app.state.config.IMAGE_API_KEYS = IMAGE_API_KEYS
app.state.config.IMAGE_API_CONFIGS = IMAGE_API_CONFIGS


########################################
#
# AUDIO
#
########################################

app.state.config.STT_OPENAI_API_BASE_URL = AUDIO_STT_OPENAI_API_BASE_URL
app.state.config.STT_OPENAI_API_KEY = AUDIO_STT_OPENAI_API_KEY
app.state.config.STT_ENGINE = AUDIO_STT_ENGINE
app.state.config.STT_MODEL = AUDIO_STT_MODEL

app.state.config.WHISPER_MODEL = WHISPER_MODEL
app.state.config.WHISPER_VAD_FILTER = WHISPER_VAD_FILTER
app.state.config.DEEPGRAM_API_KEY = DEEPGRAM_API_KEY

app.state.config.AUDIO_STT_AZURE_API_KEY = AUDIO_STT_AZURE_API_KEY
app.state.config.AUDIO_STT_AZURE_REGION = AUDIO_STT_AZURE_REGION
app.state.config.AUDIO_STT_AZURE_LOCALES = AUDIO_STT_AZURE_LOCALES

app.state.config.STT_GOOGLE_PROJECT_ID = AUDIO_STT_GOOGLE_PROJECT_ID
app.state.config.STT_GOOGLE_LOCATION = AUDIO_STT_GOOGLE_LOCATION
app.state.config.STT_GOOGLE_LANGUAGE_CODES = AUDIO_STT_GOOGLE_LANGUAGE_CODES
app.state.config.STT_GOOGLE_SERVICE_ACCOUNT_KEY = AUDIO_STT_GOOGLE_SERVICE_ACCOUNT_KEY

app.state.config.TTS_OPENAI_API_BASE_URL = AUDIO_TTS_OPENAI_API_BASE_URL
app.state.config.TTS_OPENAI_API_KEY = AUDIO_TTS_OPENAI_API_KEY
app.state.config.TTS_ENGINE = AUDIO_TTS_ENGINE
app.state.config.TTS_MODEL = AUDIO_TTS_MODEL
app.state.config.TTS_VOICE = AUDIO_TTS_VOICE
app.state.config.TTS_API_KEY = AUDIO_TTS_API_KEY
app.state.config.TTS_SPLIT_ON = AUDIO_TTS_SPLIT_ON
app.state.config.AVATAR_ENGINE = AUDIO_AVATAR_ENGINE
app.state.config.AVATAR_API_KEY = AUDIO_AVATAR_API_KEY
app.state.config.AVATAR_REGION = AUDIO_AVATAR_REGION
app.state.config.TTS_AZURE_AVATAR_CHARACTER = AUDIO_TTS_AZURE_AVATAR_CHARACTER
app.state.config.TTS_AZURE_AVATAR_STYLE = AUDIO_TTS_AZURE_AVATAR_STYLE
app.state.config.TTS_AZURE_AVATAR_GREETING = AUDIO_TTS_AZURE_AVATAR_GREETING

app.state.config.TTS_AZURE_SPEECH_REGION = AUDIO_TTS_AZURE_SPEECH_REGION
app.state.config.TTS_AZURE_SPEECH_OUTPUT_FORMAT = AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT

app.state.config.TTS_GOOGLE_LANGUAGE_CODE = AUDIO_TTS_GOOGLE_LANGUAGE_CODE
app.state.config.TTS_GOOGLE_SERVICE_ACCOUNT_KEY = AUDIO_TTS_GOOGLE_SERVICE_ACCOUNT_KEY

app.state.config.TTS_GEMINI_MODEL = AUDIO_TTS_GEMINI_MODEL
app.state.config.TTS_GEMINI_LOCATION = AUDIO_TTS_GEMINI_LOCATION
app.state.config.TTS_GEMINI_SERVICE_ACCOUNT_KEY = AUDIO_TTS_GEMINI_SERVICE_ACCOUNT_KEY


app.state.faster_whisper_model = None
app.state.speech_synthesiser = None
app.state.speech_speaker_embeddings_dataset = None


########################################
#
# TASKS
#
########################################


app.state.config.TASK_MODEL = TASK_MODEL
app.state.config.TASK_MODEL_EXTERNAL = TASK_MODEL_EXTERNAL

# Memory extraction
app.state.config.MEMORY_EXTRACTION_MODEL = MEMORY_EXTRACTION_MODEL
app.state.config.MEMORY_EXTRACTION_CONFIDENCE = MEMORY_EXTRACTION_CONFIDENCE


app.state.config.ENABLE_AUTOCOMPLETE_GENERATION = ENABLE_AUTOCOMPLETE_GENERATION
app.state.config.ENABLE_TAGS_GENERATION = ENABLE_TAGS_GENERATION
app.state.config.ENABLE_TITLE_GENERATION = ENABLE_TITLE_GENERATION
app.state.config.ENABLE_FOLLOW_UP_GENERATION = ENABLE_FOLLOW_UP_GENERATION


app.state.config.TITLE_GENERATION_PROMPT_TEMPLATE = TITLE_GENERATION_PROMPT_TEMPLATE
app.state.config.TAGS_GENERATION_PROMPT_TEMPLATE = TAGS_GENERATION_PROMPT_TEMPLATE
app.state.config.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = (
    FOLLOW_UP_GENERATION_PROMPT_TEMPLATE
)

app.state.config.AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = (
    AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE
)
app.state.config.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH = (
    AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH
)


########################################
#
# WEBUI
#
########################################

app.state.MODELS = {}


class RedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Check if the request is a GET request
        if request.method == "GET":
            path = request.url.path
            query_params = dict(parse_qs(urlparse(str(request.url)).query))

            # Check for the specific watch path and the presence of 'v' parameter
            if path.endswith("/watch") and "v" in query_params:
                video_id = query_params["v"][0]  # Extract the first 'v' parameter
                encoded_video_id = urlencode({"youtube": video_id})
                redirect_url = f"/?{encoded_video_id}"
                return RedirectResponse(url=redirect_url)

        # Proceed with the normal flow of other requests
        response = await call_next(request)
        return response


# Add the middleware to the app
app.add_middleware(RedirectMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditContextMiddleware)


@app.middleware("http")
async def commit_session_after_request(request: Request, call_next):
    response = await call_next(request)
    # log.debug("Commit session after request")
    Session.commit()
    return response


@app.middleware("http")
async def check_url(request: Request, call_next):
    start_time = int(time.time())
    request.state.token = get_http_authorization_cred(
        request.headers.get("Authorization")
    )

    request.state.enable_api_key = app.state.config.ENABLE_API_KEY
    response = await call_next(request)
    process_time = int(time.time()) - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


@app.middleware("http")
async def inspect_websocket(request: Request, call_next):
    if (
        "/ws/socket.io" in request.url.path
        and request.query_params.get("transport") == "websocket"
    ):
        upgrade = (request.headers.get("Upgrade") or "").lower()
        connection = (request.headers.get("Connection") or "").lower().split(",")
        # Check that there's the correct headers for an upgrade, else reject the connection
        # This is to work around this upstream issue: https://github.com/miguelgrinberg/python-engineio/issues/367
        if upgrade != "websocket" or "upgrade" not in connection:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid WebSocket upgrade request"},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGIN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Embed widget public endpoints must be reachable from arbitrary host sites
# (the whole point of an embeddable widget). The global CORSMiddleware above
# rejects preflight requests from non-whitelisted origins, so we add an
# additional middleware that runs *before* CORSMiddleware (added later in
# code = outer in execution) and short-circuits CORS preflight + injects
# permissive CORS headers for these specific paths only.
@app.middleware("http")
async def embed_widget_cors_bypass(request: Request, call_next):
    path = request.url.path
    is_embed_public = (
        path.startswith("/api/embed/v1/id/")
        or path.startswith("/api/v1/embed-widgets/id/")
    ) and (path.endswith("/config") or "/auth/" in path)
    if not is_embed_public:
        return await call_next(request)

    # Handle CORS preflight directly — never reach CORSMiddleware
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            },
        )

    # Real request: process and ensure permissive CORS headers on response
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Vary"] = "Origin"
    return response


app.mount("/ws", socket_app)


app.include_router(ollama.router, prefix="/ollama", tags=["ollama"])
app.include_router(openai.router, prefix="/openai", tags=["openai"])


app.include_router(pipelines.router, prefix="/api/v1/pipelines", tags=["pipelines"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(teams_bot.router, prefix="/api/v1/teams", tags=["teams-bot"])
app.include_router(
    teams_bot_config.router, prefix="/api/v1/teams-bot", tags=["teams-bot-config"]
)
app.include_router(
    trusted_audiences.router,
    prefix="/api/v1/trusted-audiences",
    tags=["trusted-audiences"],
)
app.include_router(schedules.router, prefix="/api/v1/schedules", tags=["schedules"])
app.include_router(images.router, prefix="/api/v1/images", tags=["images"])

app.include_router(audio.router, prefix="/api/v1/audio", tags=["audio"])
app.include_router(retrieval.router, prefix="/api/v1/retrieval", tags=["retrieval"])
app.include_router(
    email_integration.router, prefix="/api/v1/email", tags=["email-integration"]
)
app.include_router(
    google_actions.router, prefix="/api/v1/google", tags=["google-actions"]
)

app.include_router(configs.router, prefix="/api/v1/configs", tags=["configs"])
app.include_router(
    data_retention.router,
    prefix="/api/v1/configs/data_retention",
    tags=["data_retention"],
)
app.include_router(branding.router, prefix="/api/v1/branding", tags=["branding"])
app.include_router(
    document_templates.router,
    prefix="/api/v1/document-templates",
    tags=["document-templates"],
)
app.include_router(devtools.router, prefix="/api/v1/devtools", tags=["devtools"])

app.include_router(auths.router, prefix="/api/v1/auths", tags=["auths"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])


app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])
app.include_router(chats.router, prefix="/api/v1/chats", tags=["chats"])
app.include_router(chat_hitl.router, prefix="/api/v1/chats", tags=["chats", "hitl"])

app.include_router(models.router, prefix="/api/v1/models", tags=["models"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(guardrails.router, prefix="/api/v1/guardrails", tags=["guardrails"])
app.include_router(guide.router, prefix="/api/v1/guide", tags=["guide"])
app.include_router(
    agent_flows.router, prefix="/api/v1/agent-flows", tags=["agent-flows"]
)
app.include_router(dbsphere.router, prefix="/api/v1/dbsphere", tags=["dbsphere"])
app.include_router(glossary.router, prefix="/api/v1/glossary", tags=["glossary"])
app.include_router(
    knowledge_graph.router,
    prefix="/api/v1/knowledge-graph",
    tags=["knowledge-graph"],
)
app.include_router(
    document_profiles.router,
    prefix="/api/v1/document-profiles",
    tags=["document-profiles"],
)
app.include_router(
    extraction_engines.router,
    prefix="/api/v1/extraction-engines",
    tags=["extraction-engines"],
)
app.include_router(
    workspace_tags.router,
    prefix="/api/v1/workspace-tags",
    tags=["workspace-tags"],
)
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(
    tool_connections.router,
    prefix="/api/v1/tool_connections",
    tags=["tool_connections"],
)
app.include_router(tools.router, prefix="/api/v1/tools", tags=["tools"])
app.include_router(
    marketplace.router, prefix="/api/v1/marketplace", tags=["marketplace"]
)

app.include_router(memories.router, prefix="/api/v1/memories", tags=["memories"])
app.include_router(
    admin_memory.router,
    prefix="/api/v1/admin/memory",
    tags=["admin:memory"],
)
app.include_router(folders.router, prefix="/api/v1/folders", tags=["folders"])
app.include_router(groups.router, prefix="/api/v1/groups", tags=["groups"])
app.include_router(
    organizations.router, prefix="/api/v1/organizations", tags=["organizations"]
)
app.include_router(audit_logs.router, prefix="/api/v1/audit-logs", tags=["audit-logs"])
app.include_router(
    guardrail_logs.router,
    prefix="/api/v1/guardrail-logs",
    tags=["guardrail-logs"],
)
app.include_router(
    file_logs.router,
    prefix="/api/v1/file-logs",
    tags=["file-logs"],
)
app.include_router(traces.router, prefix="/api/v1/traces", tags=["traces"])
app.include_router(
    trace_analysis.router,
    prefix="/api/v1/trace-analysis",
    tags=["trace-analysis"],
)
app.include_router(usage.router, prefix="/api/v1/usage", tags=["usage"])
app.include_router(
    bi_dashboard.router,
    prefix="/api/v1/bi-dashboards",
    tags=["bi-dashboards"],
)
app.include_router(inquiries.router, prefix="/api/v1/inquiries", tags=["inquiries"])
app.include_router(sr.router, prefix="/api/v1/sr", tags=["sr"])
app.include_router(files.router, prefix="/api/v1/files", tags=["files"])
app.include_router(functions.router, prefix="/api/v1/functions", tags=["functions"])
app.include_router(
    evaluations.router, prefix="/api/v1/evaluations", tags=["evaluations"]
)
app.include_router(
    auto_evaluations.router,
    prefix="/api/v1/auto-evaluations",
    tags=["auto-evaluations"],
)
app.include_router(utils.router, prefix="/api/v1/utils", tags=["utils"])
app.include_router(
    notifications.router, prefix="/api/v1/notifications", tags=["notifications"]
)
app.include_router(
    license_permissions.router,
    prefix="/api/v1/license_permissions",
    tags="license_permissions",
)
app.include_router(
    license.router,
    prefix="/api/v1/license",
    tags=["license"],
)
app.include_router(cloocus.router, prefix="/api/v1/cloocus", tags=["cloocus"])
app.include_router(
    code_gateway.router, prefix="/api/v1/code-gateway", tags=["code-gateway"]
)
app.include_router(
    embed_widgets.router, prefix="/api/v1/embed-widgets", tags=["embed-widgets"]
)
app.include_router(
    embed_widgets_public.router,
    prefix="/api/embed/v1",
    tags=["embed-widgets-public"],
)
# 레거시 호환: 프리빌드 프런트엔드가 여전히 구 경로를 호출할 수 있으므로
# 동일 public 라우터를 구 prefix 에도 마운트한다. 경로가 admin CRUD 와 겹치지 않아 충돌 없음.
app.include_router(
    embed_widgets_public.router,
    prefix="/api/v1/embed-widgets",
    tags=["embed-widgets-public-legacy"],
)


try:
    audit_level = AuditLevel(AUDIT_LOG_LEVEL)
except ValueError as e:
    logger.error(f"Invalid audit level: {AUDIT_LOG_LEVEL}. Error: {e}")
    audit_level = AuditLevel.NONE

if audit_level != AuditLevel.NONE:
    app.add_middleware(
        AuditLoggingMiddleware,
        audit_level=audit_level,
        excluded_paths=AUDIT_EXCLUDED_PATHS,
        max_body_size=MAX_BODY_LOG_SIZE,
    )
##################################
#
# Chat Endpoints
#
##################################


@app.get("/api/models")
async def get_models(request: Request, user=Depends(get_verified_user)):
    def get_filtered_models(models, user):
        filtered_models = []
        for model in models:
            if model.get("arena"):
                if has_access(
                    user.id,
                    type="read",
                    access_control=model.get("info", {})
                    .get("meta", {})
                    .get("access_control", {}),
                ):
                    filtered_models.append(model)
                continue

            model_info = Models.get_model_by_id(model["id"])
            if model_info:
                if user.id == model_info.user_id or has_access(
                    user.id, type="read", access_control=model_info.access_control
                ):
                    filtered_models.append(model)

        return filtered_models

    all_models = await get_all_models(request, user=user)

    models = []
    for model in all_models:
        # Filter out filter pipelines
        if "pipeline" in model and model["pipeline"].get("type", None) == "filter":
            continue

        try:
            model_tags = [
                tag.get("name")
                for tag in model.get("info", {}).get("meta", {}).get("tags", [])
            ]
            tags = [tag.get("name") for tag in model.get("tags", [])]

            tags = list(set(model_tags + tags))
            model["tags"] = [{"name": tag} for tag in tags]
        except Exception as e:
            log.debug(f"Error processing model tags: {e}")
            model["tags"] = []
            pass

        models.append(model)

    model_order_list = request.app.state.config.MODEL_ORDER_LIST
    if model_order_list:
        model_order_dict = {model_id: i for i, model_id in enumerate(model_order_list)}
        # Sort models by order list priority, with fallback for those not in the list
        models.sort(
            key=lambda x: (model_order_dict.get(x["id"], float("inf")), x["name"])
        )

    # Filter out models that the user does not have access to
    if user.role == "user" and not BYPASS_MODEL_ACCESS_CONTROL:
        models = get_filtered_models(models, user)

    log.debug(
        f"/api/models returned filtered models accessible to the user: {json.dumps([model['id'] for model in models])}"
    )
    return {"data": models}


@app.get("/api/models/base")
async def get_base_models(request: Request, user=Depends(get_admin_user)):
    models = await get_all_base_models(request, user=user)
    return {"data": models}


@app.post("/api/chat/completions")
async def chat_completion(
    request: Request,
    form_data: dict,
    user=Depends(get_verified_user),
):
    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    model_item = form_data.pop("model_item", {})
    tasks = form_data.pop("background_tasks", None)
    task = form_data.pop("task", None)

    # 외부 API 호출(외부 IDP 토큰 또는 X-Client-Type: external-api)이면 보조 작업
    # (타이틀/태그/후속질문/자동완성 생성 등) 을 강제로 off — 고객 토큰 낭비 방지.
    # 명시적으로 tasks 를 보낸 경우에도 off 로 덮어씀 (정책).
    _client_type_hdr = (request.headers.get("X-Client-Type") or "").strip().lower()
    _auth_type = getattr(request.state, "auth_type", "")
    if _client_type_hdr == "external-api" or _auth_type == "external_id_token":
        tasks = None

    enhanced_params = model_item.get("info", {}).get("params", {})

    metadata = {}
    try:
        if not model_item.get("direct", False):
            model_id = form_data.get("model", None)

            if model_id not in request.app.state.MODELS:
                # Stale cache fallback — pub/sub 신뢰성 위에 backstop.
                await get_all_models(request, user=user)
                if model_id not in request.app.state.MODELS:
                    raise Exception("Model not found")

            model = request.app.state.MODELS[model_id]
            model_info = Models.get_model_by_id(model_id)

            # Check if user has access to the model
            if not BYPASS_MODEL_ACCESS_CONTROL and user.role == "user":
                try:
                    check_model_access(user, model)
                except Exception as e:
                    raise e
        else:
            model = model_item
            model_info = None

            request.state.direct = True
            request.state.model = model

        metadata = {
            "user_id": user.id,
            "chat_id": form_data.pop("chat_id", None),
            "message_id": form_data.pop("id", None),
            "session_id": form_data.pop("session_id", None),
            "client_type": (
                form_data.pop("client_type", None)
                or request.headers.get("X-Client-Type")
                or getattr(request.state, "auth_type", "web")
            ),
            "tool_ids": form_data.get("tool_ids", None),
            "tool_servers": form_data.pop("tool_servers", None),
            "files": form_data.get("files", None),
            "features": form_data.pop("features", None),
            "variables": form_data.pop("variables", None),
            **({"task": task} if task else {}),
            "model": model,
            "enhanced_params": enhanced_params,
            "direct": model_item.get("direct", False),
            **(
                {"function_calling": "native"}
                if form_data.get("params", {}).get("function_calling") == "native"
                or (
                    model_info
                    and model_info.params.model_dump().get("function_calling")
                    == "native"
                )
                else {}
            ),
        }

        # Create unified agent configuration from model info
        if model_info:
            agent_config = AgentConfig.from_model_info(
                params=model_info.params.model_dump() if model_info.params else {},
                meta=model_info.meta.model_dump() if model_info.meta else {},
                model_id=model_info.id,
                base_model_id=model_info.base_model_id,
            )
        else:
            # Direct mode - use enhanced_params and model_item
            agent_config = AgentConfig.from_model_info(
                params=enhanced_params,
                meta=model.get("info", {}).get("meta", {}),
                model_id=model.get("id"),
            )
        # KG가 attach된 경우 KG.sources의 KB/DbSphere/Glossary를 effective set에 union
        # → 사용자가 KG만 붙여도 SQL/RAG/Glossary 도구가 자동 활성화
        # user를 넘겨서 권한 있는 리소스만 inherit (도구 호출 시점 401 회피)
        agent_config.resolve_kg_inheritance(user=user)
        metadata["agent_config"] = agent_config

        # HITL resume: chat_hitl shim 이 form_data["metadata"]["hitl_resume"] 에
        # 박은 사용자 결정 정보를 새 metadata 로 복사. 안 그러면 라우터에서
        # 새 metadata dict 만들면서 사라져 openai.py 의 hitl_resume 분기가
        # 안 걸리고 일반 run() 흐름으로 가버린다 → graph 의 dangling tool_call
        # 로 retry 무한루프 + 사용자가 본 모달이 멈춰버림.
        _existing_meta = form_data.get("metadata") or {}
        if isinstance(_existing_meta, dict) and "hitl_resume" in _existing_meta:
            metadata["hitl_resume"] = _existing_meta["hitl_resume"]

        # Data analysis project: inject project_context for code interpreter
        params = form_data.get("params", {}) or {}
        if params.get("_projectType") == "data_analysis":
            project_id = params.get("_projectId")
            if project_id:
                from open_webui.models.projects import Projects

                da_project = Projects.get_project_by_id(project_id)
                if da_project and da_project.type == "data_analysis":
                    metadata["project_context"] = {
                        "id": da_project.id,
                        "type": da_project.type,
                        "file_metadata": (da_project.data or {}).get(
                            "file_metadata", {}
                        ),
                        "jupyter_kernel_id": (da_project.data or {}).get(
                            "jupyter_kernel_id"
                        ),
                        "instructions": da_project.instructions,
                    }

        request.state.metadata = metadata
        form_data["metadata"] = metadata

        form_data, metadata, events = await process_chat_payload(
            request, form_data, user, metadata, model
        )

    except HTTPException:
        # 의도된 HTTPException(detail=dict 포함) 은 FastAPI 가 그대로 직렬화하도록 재던짐.
        raise
    except Exception as e:
        log.exception("Error processing chat payload")
        if metadata.get("chat_id") and metadata.get("message_id"):
            # Update the chat message with the error
            Chats.upsert_message_to_chat_by_id_and_message_id(
                metadata["chat_id"],
                metadata["message_id"],
                {
                    "error": {"content": str(e)},
                },
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    try:
        response = await chat_completion_handler(request, form_data, user)

        return await process_chat_response(
            request, response, form_data, user, metadata, model, events, tasks
        )
    except HTTPException:
        # 핸들러가 의도적으로 던진 HTTPException(예: 429 USAGE_LIMIT_EXCEEDED detail dict)
        # 은 그대로 재던져 FastAPI 가 status code 와 detail 구조를 보존하게 한다.
        raise
    except Exception as e:
        log.exception("Error in chat completion handler")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# Alias for chat_completion (Legacy)
generate_chat_completions = chat_completion
generate_chat_completion = chat_completion


@app.post("/api/chat/completed")
async def chat_completed(
    request: Request, form_data: dict, user=Depends(get_verified_user)
):
    try:
        model_item = form_data.pop("model_item", {})

        if model_item.get("direct", False):
            request.state.direct = True
            request.state.model = model_item

        return await chat_completed_handler(request, form_data, user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@app.post("/api/chat/actions/{action_id}")
async def chat_action(
    request: Request, action_id: str, form_data: dict, user=Depends(get_verified_user)
):
    try:
        model_item = form_data.pop("model_item", {})

        if model_item.get("direct", False):
            request.state.direct = True
            request.state.model = model_item

        return await chat_action_handler(request, action_id, form_data, user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@app.post("/api/tasks/stop/{task_id}")
async def stop_task_endpoint(task_id: str, user=Depends(get_verified_user)):
    try:
        result = await stop_task(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get("/api/tasks")
async def list_tasks_endpoint(user=Depends(get_verified_user)):
    return {"tasks": list_tasks()}


@app.get("/api/tasks/chat/{chat_id}")
async def list_tasks_by_chat_id_endpoint(chat_id: str, user=Depends(get_verified_user)):
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None or chat.user_id != user.id:
        return {"task_ids": []}

    task_ids = list_task_ids_by_chat_id(chat_id)

    print(f"Task IDs for chat {chat_id}: {task_ids}")
    return {"task_ids": task_ids}


##################################
#
# Config Endpoints
#
##################################


@app.get("/api/config")
async def get_app_config(request: Request):
    user = None
    if "token" in request.cookies:
        token = request.cookies.get("token")
        try:
            data = decode_token(token)
        except Exception as e:
            log.debug(e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        if data is not None and "id" in data:
            user = Users.get_user_by_id(data["id"])

    user_count = Users.get_num_users()
    onboarding = user is None and app.state.config.ENABLE_ONBOARDING

    # Ensure LICENSE_STATUS is fresh across workers (Redis check)
    license.ensure_license_status_fresh(app)

    return {
        **({"onboarding": True} if onboarding else {}),
        "status": True,
        "name": app.state.WEBUI_NAME,
        "version": VERSION,
        "default_locale": str(DEFAULT_LOCALE),
        "branding": {
            "favicon_url": "/api/v1/branding/favicon",
            "favicon_dark_url": "/api/v1/branding/favicon-dark",
            "logo_url": "/api/v1/branding/logo",
            "splash_url": "/api/v1/branding/splash",
            "splash_dark_url": "/api/v1/branding/splash-dark",
            "browser_favicon_url": "/api/v1/branding/browser-favicon",
        },
        "oauth": {
            "providers": {
                name: config.get("name", name)
                for name, config in OAUTH_PROVIDERS.items()
            }
        },
        "features": {
            "auth": WEBUI_AUTH,
            "auth_trusted_header": bool(app.state.AUTH_TRUSTED_EMAIL_HEADER),
            "enable_ldap": app.state.config.ENABLE_LDAP,
            "enable_api_key": app.state.config.ENABLE_API_KEY,
            "enable_signup": app.state.config.ENABLE_SIGNUP,
            "enable_login_form": app.state.config.ENABLE_LOGIN_FORM,
            "enable_email_deidentify": ENABLE_EMAIL_DEIDENTIFY,
            "enable_websocket": ENABLE_WEBSOCKET_SUPPORT,
            **(
                {
                    "enable_direct_connections": app.state.config.ENABLE_DIRECT_CONNECTIONS,
                    "enable_channels": app.state.config.ENABLE_CHANNELS,
                    "enable_web_search": app.state.config.ENABLE_WEB_SEARCH,
                    "enable_code_execution": app.state.config.ENABLE_CODE_EXECUTION,
                    "enable_image_generation": app.state.config.ENABLE_IMAGE_GENERATION,
                    # GWS 채팅 통합은 Google OAuth 자격증명 미설정이면 사용자가
                    # 연결할 방법 자체가 없으므로 admin 토글과 무관하게 숨김
                    "enable_gmail": app.state.config.ENABLE_GMAIL_INTEGRATION
                    and "google" in OAUTH_PROVIDERS,
                    "enable_calendar": app.state.config.ENABLE_CALENDAR_INTEGRATION
                    and "google" in OAUTH_PROVIDERS,
                    "enable_drive": app.state.config.ENABLE_DRIVE_INTEGRATION
                    and "google" in OAUTH_PROVIDERS,
                    "enable_autocomplete_generation": app.state.config.ENABLE_AUTOCOMPLETE_GENERATION,
                    "enable_follow_up_generation": app.state.config.ENABLE_FOLLOW_UP_GENERATION,
                    "enable_community_sharing": app.state.config.ENABLE_COMMUNITY_SHARING,
                    "enable_message_rating": app.state.config.ENABLE_MESSAGE_RATING,
                    "enable_user_webhooks": app.state.config.ENABLE_USER_WEBHOOKS,
                    "enable_usage_limit": app.state.config.ENABLE_USAGE_LIMIT,
                    "enable_admin_export": ENABLE_ADMIN_EXPORT,
                    "enable_admin_chat_access": ENABLE_ADMIN_CHAT_ACCESS,
                    "enable_google_drive_integration": app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
                    "enable_onedrive_integration": app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
                    "enable_sharepoint_integration": app.state.config.ENABLE_SHAREPOINT_INTEGRATION,
                    "developer_mode": is_cloocus_db_available(),
                }
                if user is not None
                else {}
            ),
        },
        **(
            {
                "default_models": app.state.config.DEFAULT_MODELS,
                "default_prompt_suggestions": app.state.config.DEFAULT_PROMPT_SUGGESTIONS,
                "user_count": user_count,
                "code": {
                    "engine": app.state.config.CODE_EXECUTION_ENGINE,
                },
                "audio": {
                    "tts": {
                        "engine": app.state.config.TTS_ENGINE,
                        "voice": app.state.config.TTS_VOICE,
                        "split_on": app.state.config.TTS_SPLIT_ON,
                    },
                    "stt": {
                        "engine": app.state.config.STT_ENGINE,
                    },
                },
                "file": {
                    "max_size": app.state.config.FILE_MAX_SIZE,
                    "max_count": app.state.config.FILE_MAX_COUNT,
                },
                "storage": {
                    "image_upload_mode": app.state.config.IMAGE_UPLOAD_MODE,
                    "provider": app.state.config.STORAGE_PROVIDER,
                },
                "permissions": {**app.state.config.USER_PERMISSIONS},
                "google_drive": {
                    "client_id": GOOGLE_DRIVE_CLIENT_ID.value,
                    "api_key": GOOGLE_DRIVE_API_KEY.value,
                },
                "onedrive": {"client_id": ONEDRIVE_CLIENT_ID.value},
                "sharepoint": {
                    "client_id": SHAREPOINT_CLIENT_ID.value,
                    "tenant_id": SHAREPOINT_TENANT_ID.value,
                    "site_url": SHAREPOINT_SITE_URL.value,
                },
                "dbsphere": {
                    "types": DBSPHERE_TYPES,
                },
                "license_metadata": app.state.LICENSE_METADATA,
                "license": {
                    "has_license": getattr(app.state, "LICENSE_STATUS", None)
                    and app.state.LICENSE_STATUS.has_license,
                    "tier": getattr(app.state, "LICENSE_STATUS", None)
                    and app.state.LICENSE_STATUS.tier,
                    "permissions": getattr(app.state, "LICENSE_STATUS", None)
                    and app.state.LICENSE_STATUS.permissions
                    or {},
                    "enforcement_enabled": getattr(app.state, "LICENSE_STATUS", None)
                    and app.state.LICENSE_STATUS.enforcement_enabled
                    or False,
                },
                **(
                    {
                        "active_entries": app.state.USER_COUNT,
                    }
                    if user.role == "admin"
                    else {}
                ),
            }
            if user is not None
            else {}
        ),
    }


class UrlForm(BaseModel):
    url: str


@app.get("/api/webhook")
async def get_webhook_url(user=Depends(get_admin_user)):
    return {
        "url": app.state.config.WEBHOOK_URL,
    }


@app.post("/api/webhook")
async def update_webhook_url(form_data: UrlForm, user=Depends(get_admin_user)):
    app.state.config.WEBHOOK_URL = form_data.url
    app.state.WEBHOOK_URL = app.state.config.WEBHOOK_URL
    return {"url": app.state.config.WEBHOOK_URL}


@app.get("/api/version")
async def get_app_version():
    return {
        "version": VERSION,
    }


@app.get("/api/version/updates")
async def get_app_latest_release_version(user=Depends(get_verified_user)):
    return {"current": VERSION, "latest": VERSION}
    # if OFFLINE_MODE:
    #     log.debug(
    #         "Offline mode is enabled, returning current version as latest version"
    #     )
    #     return {"current": VERSION, "latest": VERSION}
    # try:
    #     timeout = aiohttp.ClientTimeout(total=1)
    #     async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
    #         async with session.get(
    #             "https://api.github.com/repos/open-webui/open-webui/releases/latest"
    #         ) as response:
    #             response.raise_for_status()
    #             data = await response.json()
    #             latest_version = data["tag_name"]

    #             return {"current": VERSION, "latest": latest_version[1:]}
    # except Exception as e:
    #     log.debug(e)
    #     return {"current": VERSION, "latest": VERSION}


@app.get("/api/changelog")
async def get_app_changelog(lang: str = "en"):
    data = CHANGELOG_KO if lang.startswith("ko") else CHANGELOG
    return data


############################
# OAuth Login & Callback
############################

# SessionMiddleware is used by authlib for oauth
if len(OAUTH_PROVIDERS) > 0:
    app.add_middleware(
        SessionMiddleware,
        secret_key=WEBUI_SECRET_KEY,
        session_cookie="oui-session",
        same_site=WEBUI_SESSION_COOKIE_SAME_SITE,
        https_only=WEBUI_SESSION_COOKIE_SECURE,
    )


@app.get("/oauth/{provider}/login")
async def oauth_login(provider: str, request: Request):
    return await oauth_manager.handle_login(request, provider)


# OAuth login logic is as follows:
# 1. Attempt to find a user with matching subject ID, tied to the provider
# 2. If OAUTH_MERGE_ACCOUNTS_BY_EMAIL is true, find a user with the email address provided via OAuth
#    - This is considered insecure in general, as OAuth providers do not always verify email addresses
# 3. If there is no user, and ENABLE_OAUTH_SIGNUP is true, create a user
#    - Email addresses are considered unique, so we fail registration if the email address is already taken
@app.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, response: Response):
    return await oauth_manager.handle_callback(request, provider, response)


@app.get("/manifest.json")
async def get_manifest_json():
    if app.state.EXTERNAL_PWA_MANIFEST_URL:
        return requests.get(app.state.EXTERNAL_PWA_MANIFEST_URL).json()
    else:
        return {
            "name": app.state.WEBUI_NAME,
            "short_name": app.state.WEBUI_NAME,
            "description": "ClooSphere is an extensible, user-friendly interface for AI that adapts to your workflow.",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#343541",
            "orientation": "natural",
            "icons": [
                {
                    "src": "/api/v1/branding/logo",
                    "type": "image/png",
                    "sizes": "500x500",
                    "purpose": "any",
                },
                {
                    "src": "/api/v1/branding/logo",
                    "type": "image/png",
                    "sizes": "500x500",
                    "purpose": "maskable",
                },
            ],
        }


@app.get("/opensearch.xml")
async def get_opensearch_xml():
    xml_content = rf"""
    <OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" xmlns:moz="http://www.mozilla.org/2006/browser/search/">
    <ShortName>{app.state.WEBUI_NAME}</ShortName>
    <Description>Search {app.state.WEBUI_NAME}</Description>
    <InputEncoding>UTF-8</InputEncoding>
    <Image width="16" height="16" type="image/x-icon">{app.state.config.WEBUI_URL}/api/v1/branding/browser-favicon</Image>
    <Url type="text/html" method="get" template="{app.state.config.WEBUI_URL}/?q={"{searchTerms}"}"/>
    <moz:SearchForm>{app.state.config.WEBUI_URL}</moz:SearchForm>
    </OpenSearchDescription>
    """
    return Response(content=xml_content, media_type="application/xml")


@app.get("/health")
async def healthcheck():
    return {"status": True}


@app.get("/health/db")
async def healthcheck_with_db():
    try:
        Session.execute(text("SELECT 1;")).all()
        return {"status": True}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": False, "error": f"Database unavailable: {e}"},
        )


@app.get("/health/redis")
async def healthcheck_redis(request: Request):
    redis_client = getattr(getattr(request.app.state, "config", None), "_redis", None)
    if not redis_client:
        return {"status": True, "mode": "standalone", "detail": "Redis not configured"}
    try:
        redis_client.ping()
        return {"status": True, "mode": "redis"}
    except (redis.ConnectionError, redis.TimeoutError) as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": False,
                "mode": "redis",
                "error": f"Redis unavailable: {e}",
            },
        )


@app.get("/health/full")
async def healthcheck_full(request: Request):
    result = {"status": True, "components": {}}

    # DB check
    try:
        Session.execute(text("SELECT 1;")).all()
        result["components"]["db"] = {"status": True}
    except Exception as e:
        result["status"] = False
        result["components"]["db"] = {"status": False, "error": str(e)}

    # Redis check
    redis_client = getattr(getattr(request.app.state, "config", None), "_redis", None)
    if not redis_client:
        result["components"]["redis"] = {"status": True, "mode": "standalone"}
    else:
        try:
            redis_client.ping()
            result["components"]["redis"] = {"status": True, "mode": "redis"}
        except (redis.ConnectionError, redis.TimeoutError) as e:
            result["status"] = False
            result["components"]["redis"] = {
                "status": False,
                "mode": "redis",
                "error": str(e),
            }

    # Task queue check
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue and hasattr(task_queue, "health_check"):
        try:
            queue_health = await task_queue.health_check()
            result["components"]["task_queue"] = queue_health
            if queue_health.get("status") == "disconnected":
                result["status"] = False
        except Exception as e:
            result["status"] = False
            result["components"]["task_queue"] = {"status": False, "error": str(e)}

    status_code = 200 if result["status"] else 503
    return JSONResponse(status_code=status_code, content=result)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")


def swagger_ui_html(*args, **kwargs):
    return get_swagger_ui_html(
        *args,
        **kwargs,
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
        swagger_favicon_url="/static/swagger-ui/favicon.png",
    )


applications.get_swagger_ui_html = swagger_ui_html

# Documentation site (Docsify)
if os.path.exists(DOCS_DIR):
    app.mount(
        "/guide",
        SPAStaticFiles(directory=DOCS_DIR, html=True),
        name="docs-static-files",
    )
    log.info("Documentation available at /guide")
else:
    log.warning(f"Documentation directory not found at '{DOCS_DIR}'")

if os.path.exists(FRONTEND_BUILD_DIR):
    mimetypes.add_type("text/javascript", ".js")
    app.mount(
        "/",
        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),
        name="spa-static-files",
    )
else:
    log.warning(
        f"Frontend build directory not found at '{FRONTEND_BUILD_DIR}'. Serving API only."
    )
