import importlib.metadata
import json
import logging
import os
import pkgutil
import shutil
import sys
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

from open_webui.constants import ERROR_MESSAGES

####################################
# Load .env file
####################################

OPEN_WEBUI_DIR = Path(__file__).parent  # the path containing this file
print(OPEN_WEBUI_DIR)

BACKEND_DIR = OPEN_WEBUI_DIR.parent  # the path containing this file
BASE_DIR = BACKEND_DIR.parent  # the path containing the backend/
DOCS_DIR = BASE_DIR / "guide"  # documentation directory

print(BACKEND_DIR)
print(BASE_DIR)

try:
    from dotenv import load_dotenv

    # Load from project root .env (BASE_DIR), using absolute path
    # to avoid find_dotenv picking up backend/.env instead.
    _dotenv_path = BASE_DIR / ".env"
    if _dotenv_path.is_file():
        load_dotenv(str(_dotenv_path))
except ImportError:
    print("dotenv not installed, skipping...")

DOCKER = os.environ.get("DOCKER", "False").lower() == "true"

# device type embedding models - "cpu" (default), "cuda" (nvidia gpu required) or "mps" (apple silicon) - choosing this right can lead to better performance
USE_CUDA = os.environ.get("USE_CUDA_DOCKER", "false")

if USE_CUDA.lower() == "true":
    try:
        import torch

        assert torch.cuda.is_available(), "CUDA not available"
        DEVICE_TYPE = "cuda"
    except Exception as e:
        cuda_error = (
            "Error when testing CUDA but USE_CUDA_DOCKER is true. "
            f"Resetting USE_CUDA_DOCKER to false: {e}"
        )
        os.environ["USE_CUDA_DOCKER"] = "false"
        USE_CUDA = "false"
        DEVICE_TYPE = "cpu"
else:
    DEVICE_TYPE = "cpu"

try:
    import torch

    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        DEVICE_TYPE = "mps"
except Exception:
    pass

####################################
# LOGGING
####################################

GLOBAL_LOG_LEVEL = os.environ.get("GLOBAL_LOG_LEVEL", "").upper()
if GLOBAL_LOG_LEVEL in logging.getLevelNamesMapping():
    logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL, force=True)
else:
    GLOBAL_LOG_LEVEL = "INFO"

log = logging.getLogger(__name__)
log.info(f"GLOBAL_LOG_LEVEL: {GLOBAL_LOG_LEVEL}")

if "cuda_error" in locals():
    log.exception(cuda_error)
    del cuda_error

log_sources = [
    "AUDIO",
    "COMFYUI",
    "CONFIG",
    "DB",
    "IMAGES",
    "MAIN",
    "MODELS",
    "OLLAMA",
    "OPENAI",
    "RAG",
    "WEBHOOK",
    "SOCKET",
    "OAUTH",
]

SRC_LOG_LEVELS = {}

for source in log_sources:
    log_env_var = source + "_LOG_LEVEL"
    SRC_LOG_LEVELS[source] = os.environ.get(log_env_var, "").upper()
    if SRC_LOG_LEVELS[source] not in logging.getLevelNamesMapping():
        SRC_LOG_LEVELS[source] = GLOBAL_LOG_LEVEL
    log.info(f"{log_env_var}: {SRC_LOG_LEVELS[source]}")

# Suppress noisy third-party library loggers
for noisy_logger in [
    "aiocache",
    "httpx",
    "httpcore",
    "openai",
    "azure",
    "langchain",
    "urllib3",
    "aiohttp",
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

log.setLevel(SRC_LOG_LEVELS["CONFIG"])

WEBUI_NAME = os.environ.get("WEBUI_NAME", "ClooSphere")

WEBUI_FAVICON_URL = "/static/favicon.png"

TRUSTED_SIGNATURE_KEY = os.environ.get("TRUSTED_SIGNATURE_KEY", "")

####################################
# ENV (dev,test,prod)
####################################

ENV = os.environ.get("ENV", "dev")

FROM_INIT_PY = os.environ.get("FROM_INIT_PY", "False").lower() == "true"

if FROM_INIT_PY:
    PACKAGE_DATA = {"version": importlib.metadata.version("open-webui")}
else:
    try:
        PACKAGE_DATA = json.loads((BASE_DIR / "package.json").read_text())
    except Exception:
        PACKAGE_DATA = {"version": "0.0.0"}

VERSION = PACKAGE_DATA["version"]


# Function to parse each section
def parse_section(section):
    items = []
    for li in section.find_all("li"):
        # Extract raw HTML string
        raw_html = str(li)

        # Extract text without HTML tags
        text = li.get_text(separator=" ", strip=True)

        # Split into title and content
        parts = text.split(": ", 1)
        title = parts[0].strip() if len(parts) > 1 else ""
        content = parts[1].strip() if len(parts) > 1 else text

        items.append({"title": title, "content": content, "raw": raw_html})
    return items


def _parse_changelog_md(content: str) -> dict:
    html = markdown.markdown(content)
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for version in soup.find_all("h2"):
        try:
            version_number = version.get_text().strip().split(" - ")[0][1:-1]
            date = version.get_text().strip().split(" - ")[1]
        except IndexError:
            continue
        version_data: dict = {"date": date}
        current = version.find_next_sibling()
        while current and current.name != "h2":
            if current.name == "h3":
                section_title = current.get_text().lower()
                next_ul = current.find_next_sibling("ul")
                if next_ul:
                    version_data[section_title] = parse_section(next_ul)
            current = current.find_next_sibling()
        result[version_number] = version_data
    return result


try:
    changelog_path = BASE_DIR / "CHANGELOG.md"
    with open(str(changelog_path.absolute()), "r", encoding="utf8") as file:
        changelog_content = file.read()
except Exception:
    changelog_content = (pkgutil.get_data("open_webui", "CHANGELOG.md") or b"").decode()

try:
    changelog_ko_path = BASE_DIR / "CHANGELOG.ko.md"
    with open(str(changelog_ko_path.absolute()), "r", encoding="utf8") as file:
        changelog_ko_content = file.read()
except Exception:
    changelog_ko_content = changelog_content

CHANGELOG = _parse_changelog_md(changelog_content)
CHANGELOG_KO = _parse_changelog_md(changelog_ko_content)

####################################
# SAFE_MODE
####################################

SAFE_MODE = os.environ.get("SAFE_MODE", "false").lower() == "true"

####################################
# ENABLE_FORWARD_USER_INFO_HEADERS
####################################

ENABLE_FORWARD_USER_INFO_HEADERS = (
    os.environ.get("ENABLE_FORWARD_USER_INFO_HEADERS", "False").lower() == "true"
)

####################################
# WEBUI_BUILD_HASH
####################################

WEBUI_BUILD_HASH = os.environ.get("WEBUI_BUILD_HASH", "dev-build")

####################################
# DATA/FRONTEND BUILD DIR
####################################

DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data")).resolve()

if FROM_INIT_PY:
    NEW_DATA_DIR = Path(os.getenv("DATA_DIR", OPEN_WEBUI_DIR / "data")).resolve()
    NEW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check if the data directory exists in the package directory
    if DATA_DIR.exists() and DATA_DIR != NEW_DATA_DIR:
        log.info(f"Moving {DATA_DIR} to {NEW_DATA_DIR}")
        for item in DATA_DIR.iterdir():
            dest = NEW_DATA_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        # Zip the data directory
        shutil.make_archive(DATA_DIR.parent / "open_webui_data", "zip", DATA_DIR)

        # Remove the old data directory
        shutil.rmtree(DATA_DIR)

    DATA_DIR = Path(os.getenv("DATA_DIR", OPEN_WEBUI_DIR / "data"))

STATIC_DIR = Path(os.getenv("STATIC_DIR", OPEN_WEBUI_DIR / "static"))

FONTS_DIR = Path(os.getenv("FONTS_DIR", OPEN_WEBUI_DIR / "static" / "fonts"))

FRONTEND_BUILD_DIR = Path(os.getenv("FRONTEND_BUILD_DIR", BASE_DIR / "build")).resolve()

if FROM_INIT_PY:
    FRONTEND_BUILD_DIR = Path(
        os.getenv("FRONTEND_BUILD_DIR", OPEN_WEBUI_DIR / "frontend")
    ).resolve()

####################################
# Database
####################################

# Check if the file exists
if os.path.exists(f"{DATA_DIR}/ollama.db"):
    # Rename the file
    os.rename(f"{DATA_DIR}/ollama.db", f"{DATA_DIR}/webui.db")
    log.info("Database migrated from Ollama-WebUI successfully.")
else:
    pass

####################################
# Database URL 구성
####################################

_database_url_from_env = os.environ.get("DATABASE_URL", "")

if _database_url_from_env:
    DATABASE_URL = _database_url_from_env
else:
    DATABASE_TYPE = os.environ.get("DATABASE_TYPE", "sqlite").lower()

    if DATABASE_TYPE == "postgresql":
        from urllib.parse import quote_plus

        DATABASE_HOST = os.environ.get("DATABASE_HOST", "localhost")
        DATABASE_PORT = os.environ.get("DATABASE_PORT", "5432")
        DATABASE_NAME = os.environ.get("DATABASE_NAME", "openwebui")
        DATABASE_USER = os.environ.get("DATABASE_USER", "postgres")
        DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "")
        DATABASE_SSLMODE = os.environ.get("DATABASE_SSLMODE", "prefer")

        encoded_password = quote_plus(DATABASE_PASSWORD) if DATABASE_PASSWORD else ""

        if encoded_password:
            DATABASE_URL = f"postgresql://{DATABASE_USER}:{encoded_password}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}?sslmode={DATABASE_SSLMODE}"
        else:
            DATABASE_URL = f"postgresql://{DATABASE_USER}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}?sslmode={DATABASE_SSLMODE}"

        log.info(f"Using PostgreSQL: {DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}")
    else:
        DATABASE_URL = f"sqlite:///{DATA_DIR}/webui.db"

# Replace the postgres:// with postgresql://
if "postgres://" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")

# TCP keepalives 를 모든 postgres 연결에 강제한다. Azure Load Balancer(idle ~4분)·
# 관리형 PostgreSQL 이 idle 커넥션을 server-side 에서 끊어 발생하는 stale-connection
# 오류("consuming input failed: SSL error: unexpected eof while reading")를 예방.
# 이 URL 을 checkpointer(psycopg3 풀)·AGE(psycopg2 풀)·SQLAlchemy 가 공통 상속하므로
# 한 곳에서 일괄 적용된다. env/URL 에 이미 명시돼 있으면 덮어쓰지 않는다(idempotent).
if DATABASE_URL.startswith("postgresql") and "keepalives" not in DATABASE_URL:
    _ka_sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL += (
        f"{_ka_sep}keepalives=1&keepalives_idle=30"
        "&keepalives_interval=10&keepalives_count=5"
    )

DATABASE_SCHEMA = os.environ.get("DATABASE_SCHEMA", None)

DATABASE_POOL_SIZE = os.environ.get("DATABASE_POOL_SIZE", 0)

if DATABASE_POOL_SIZE == "":
    DATABASE_POOL_SIZE = 0
else:
    try:
        DATABASE_POOL_SIZE = int(DATABASE_POOL_SIZE)
    except Exception:
        DATABASE_POOL_SIZE = 0

DATABASE_POOL_MAX_OVERFLOW = os.environ.get("DATABASE_POOL_MAX_OVERFLOW", 0)

if DATABASE_POOL_MAX_OVERFLOW == "":
    DATABASE_POOL_MAX_OVERFLOW = 0
else:
    try:
        DATABASE_POOL_MAX_OVERFLOW = int(DATABASE_POOL_MAX_OVERFLOW)
    except Exception:
        DATABASE_POOL_MAX_OVERFLOW = 0

DATABASE_POOL_TIMEOUT = os.environ.get("DATABASE_POOL_TIMEOUT", 30)

if DATABASE_POOL_TIMEOUT == "":
    DATABASE_POOL_TIMEOUT = 30
else:
    try:
        DATABASE_POOL_TIMEOUT = int(DATABASE_POOL_TIMEOUT)
    except Exception:
        DATABASE_POOL_TIMEOUT = 30

DATABASE_POOL_RECYCLE = os.environ.get("DATABASE_POOL_RECYCLE", 3600)

if DATABASE_POOL_RECYCLE == "":
    DATABASE_POOL_RECYCLE = 3600
else:
    try:
        DATABASE_POOL_RECYCLE = int(DATABASE_POOL_RECYCLE)
    except Exception:
        DATABASE_POOL_RECYCLE = 3600

RESET_CONFIG_ON_START = (
    os.environ.get("RESET_CONFIG_ON_START", "False").lower() == "true"
)

ENABLE_REALTIME_CHAT_SAVE = (
    os.environ.get("ENABLE_REALTIME_CHAT_SAVE", "False").lower() == "true"
)

####################################
# REDIS
####################################

REDIS_URL = os.environ.get("REDIS_URL", "")
REDIS_SENTINEL_HOSTS = os.environ.get("REDIS_SENTINEL_HOSTS", "")
REDIS_SENTINEL_PORT = os.environ.get("REDIS_SENTINEL_PORT", "26379")

####################################
# UVICORN WORKERS
####################################

# Number of uvicorn worker processes for handling requests
UVICORN_WORKERS = os.environ.get("UVICORN_WORKERS", "1")
try:
    UVICORN_WORKERS = int(UVICORN_WORKERS)
    if UVICORN_WORKERS < 1:
        UVICORN_WORKERS = 1
except ValueError:
    UVICORN_WORKERS = 1
    log.info(f"Invalid UVICORN_WORKERS value, defaulting to {UVICORN_WORKERS}")

####################################
# WEBUI_AUTH (Required for security)
####################################

WEBUI_AUTH = os.environ.get("WEBUI_AUTH", "True").lower() == "true"
WEBUI_AUTH_TRUSTED_EMAIL_HEADER = os.environ.get(
    "WEBUI_AUTH_TRUSTED_EMAIL_HEADER", None
)
WEBUI_AUTH_TRUSTED_NAME_HEADER = os.environ.get("WEBUI_AUTH_TRUSTED_NAME_HEADER", None)

BYPASS_MODEL_ACCESS_CONTROL = (
    os.environ.get("BYPASS_MODEL_ACCESS_CONTROL", "False").lower() == "true"
)

####################################
# WEBUI_SECRET_KEY
####################################

WEBUI_SECRET_KEY = os.environ.get(
    "WEBUI_SECRET_KEY",
    os.environ.get(
        "WEBUI_JWT_SECRET_KEY", "t0p-s3cr3t"
    ),  # DEPRECATED: remove at next major version
)

WEBUI_SESSION_COOKIE_SAME_SITE = os.environ.get("WEBUI_SESSION_COOKIE_SAME_SITE", "lax")

WEBUI_SESSION_COOKIE_SECURE = (
    os.environ.get("WEBUI_SESSION_COOKIE_SECURE", "false").lower() == "true"
)

WEBUI_AUTH_COOKIE_SAME_SITE = os.environ.get(
    "WEBUI_AUTH_COOKIE_SAME_SITE", WEBUI_SESSION_COOKIE_SAME_SITE
)

WEBUI_AUTH_COOKIE_SECURE = (
    os.environ.get(
        "WEBUI_AUTH_COOKIE_SECURE",
        os.environ.get("WEBUI_SESSION_COOKIE_SECURE", "false"),
    ).lower()
    == "true"
)

if WEBUI_AUTH and WEBUI_SECRET_KEY == "":
    raise ValueError(ERROR_MESSAGES.ENV_VAR_NOT_FOUND)

####################################
# SR (Service Request)
####################################

SR_KEY = os.environ.get("SR_KEY", "")

ENABLE_WEBSOCKET_SUPPORT = (
    os.environ.get("ENABLE_WEBSOCKET_SUPPORT", "True").lower() == "true"
)

WEBSOCKET_MANAGER = os.environ.get("WEBSOCKET_MANAGER", "")

WEBSOCKET_REDIS_URL = os.environ.get("WEBSOCKET_REDIS_URL", REDIS_URL)
WEBSOCKET_REDIS_LOCK_TIMEOUT = os.environ.get("WEBSOCKET_REDIS_LOCK_TIMEOUT", 60)

WEBSOCKET_SENTINEL_HOSTS = os.environ.get("WEBSOCKET_SENTINEL_HOSTS", "")

WEBSOCKET_SENTINEL_PORT = os.environ.get("WEBSOCKET_SENTINEL_PORT", "26379")

WEBSOCKET_PING_INTERVAL = int(os.environ.get("WEBSOCKET_PING_INTERVAL", "25"))
WEBSOCKET_PING_TIMEOUT = int(os.environ.get("WEBSOCKET_PING_TIMEOUT", "120"))

AIOHTTP_CLIENT_TIMEOUT = os.environ.get("AIOHTTP_CLIENT_TIMEOUT", "")

if AIOHTTP_CLIENT_TIMEOUT == "":
    AIOHTTP_CLIENT_TIMEOUT = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT = int(AIOHTTP_CLIENT_TIMEOUT)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT = 300

AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = os.environ.get(
    "AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST",
    os.environ.get("AIOHTTP_CLIENT_TIMEOUT_OPENAI_MODEL_LIST", "10"),
)

if AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST == "":
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = int(AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = 10


AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = os.environ.get(
    "AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA", "10"
)

if AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA == "":
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = int(
            AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA
        )
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = 10

####################################
# OFFLINE_MODE
####################################

OFFLINE_MODE = os.environ.get("OFFLINE_MODE", "false").lower() == "true"

if OFFLINE_MODE:
    os.environ["HF_HUB_OFFLINE"] = "1"

####################################
# AUDIT LOGGING
####################################
# Where to store log file
AUDIT_LOGS_FILE_PATH = f"{DATA_DIR}/audit.log"
# Maximum size of a file before rotating into a new log file
AUDIT_LOG_FILE_ROTATION_SIZE = os.getenv("AUDIT_LOG_FILE_ROTATION_SIZE", "10MB")
# METADATA | REQUEST | REQUEST_RESPONSE
AUDIT_LOG_LEVEL = os.getenv("AUDIT_LOG_LEVEL", "NONE").upper()
try:
    MAX_BODY_LOG_SIZE = int(os.environ.get("MAX_BODY_LOG_SIZE") or 2048)
except ValueError:
    MAX_BODY_LOG_SIZE = 2048

# Comma separated list for urls to exclude from audit
AUDIT_EXCLUDED_PATHS = os.getenv("AUDIT_EXCLUDED_PATHS", "/chats,/chat,/folders").split(
    ","
)
AUDIT_EXCLUDED_PATHS = [path.strip() for path in AUDIT_EXCLUDED_PATHS]
AUDIT_EXCLUDED_PATHS = [path.lstrip("/") for path in AUDIT_EXCLUDED_PATHS]

####################################
# OPENTELEMETRY
####################################

ENABLE_OTEL = os.environ.get("ENABLE_OTEL", "False").lower() == "true"
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
)
OTEL_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "cloosphere")
OTEL_RESOURCE_ATTRIBUTES = os.environ.get(
    "OTEL_RESOURCE_ATTRIBUTES", ""
)  # e.g. key1=val1,key2=val2
OTEL_TRACES_SAMPLER = os.environ.get(
    "OTEL_TRACES_SAMPLER", "parentbased_always_on"
).lower()

####################################
# TOOLS/FUNCTIONS PIP OPTIONS
####################################

PIP_OPTIONS = os.getenv("PIP_OPTIONS", "").split()
PIP_PACKAGE_INDEX_OPTIONS = os.getenv("PIP_PACKAGE_INDEX_OPTIONS", "").split()


####################################
# PROGRESSIVE WEB APP OPTIONS
####################################

EXTERNAL_PWA_MANIFEST_URL = os.environ.get("EXTERNAL_PWA_MANIFEST_URL")


####################################
# GLOSSARY BULK IMPORT
####################################

# 일괄 import 시 받는 파일의 최대 크기. XLSX/CSV/MD 공통. DoS 가드.
try:
    GLOSSARY_IMPORT_MAX_BYTES = int(
        os.environ.get("GLOSSARY_IMPORT_MAX_BYTES", str(10 * 1024 * 1024))
    )
except ValueError:
    GLOSSARY_IMPORT_MAX_BYTES = 10 * 1024 * 1024

# Preview 단계에서 발급된 upload token 의 TTL (초). 만료된 토큰은 commit 거절.
try:
    GLOSSARY_IMPORT_TOKEN_TTL = int(os.environ.get("GLOSSARY_IMPORT_TOKEN_TTL", "900"))
except ValueError:
    GLOSSARY_IMPORT_TOKEN_TTL = 900


####################################
# DBSPHERE SQL EDITOR
####################################

# 사용자가 직접 실행하는 SQL 의 최대 실행 시간 (초). asyncio.wait_for + DB-native
# session timeout 으로 둘 다 적용. 초과 시 cancel + 사용자에게 "Query cancelled (timeout)".
# 너무 짧으면 정상 BI 쿼리도 끊김; 너무 길면 워커 freeze 위험.
try:
    DBSPHERE_EXECUTE_TIMEOUT_S = int(os.environ.get("DBSPHERE_EXECUTE_TIMEOUT_S", "30"))
except ValueError:
    DBSPHERE_EXECUTE_TIMEOUT_S = 30

# 한 번의 /sql/execute 응답에 포함할 최대 row 수. 초과분은 잘리고 응답에 `truncated:true`.
# 1000 은 웹 그리드가 즉시 렌더할 수 있는 안전한 상한 (네트워크 + 메모리 + 사용자가
# 한 화면에서 의미 있게 훑어볼 수 있는 양 기준). 더 큰 결과를 보려면 사용자가
# LIMIT/페이지네이션을 명시적으로 추가하거나 CSV export를 사용. 운영팀이 늘려야 하면 env 로 조정.
try:
    DBSPHERE_RESULT_ROW_CAP = int(os.environ.get("DBSPHERE_RESULT_ROW_CAP", "1000"))
except ValueError:
    DBSPHERE_RESULT_ROW_CAP = 1000

# DML/DDL 의 pending 승인 키 TTL (초). 이 시간이 지나면 confirm 호출 시 410 Gone.
# 사용자가 검토 후 결정하는 합리적 상한 — 너무 짧으면 사용자 짜증, 너무 길면 stale 의도 위험.
try:
    DBSPHERE_PENDING_EXEC_TTL_S = int(
        os.environ.get("DBSPHERE_PENDING_EXEC_TTL_S", "300")
    )
except ValueError:
    DBSPHERE_PENDING_EXEC_TTL_S = 300

# Tool Description LLM 자동 생성의 user-당-dbsphere 쿨다운 (초). 무한 클릭 방지.
try:
    DBSPHERE_TOOL_DESC_COOLDOWN_S = int(
        os.environ.get("DBSPHERE_TOOL_DESC_COOLDOWN_S", "60")
    )
except ValueError:
    DBSPHERE_TOOL_DESC_COOLDOWN_S = 60
