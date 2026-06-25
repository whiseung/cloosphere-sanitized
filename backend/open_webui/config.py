import copy
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Generic, Optional, TypeVar
from urllib.parse import urlparse

import redis
import requests
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Integer, func

from open_webui.env import (
    DATA_DIR,
    DATABASE_URL,
    ENV,
    FRONTEND_BUILD_DIR,
    OFFLINE_MODE,
    OPEN_WEBUI_DIR,
    WEBUI_AUTH,
    WEBUI_FAVICON_URL,
    WEBUI_NAME,
    log,
)
from open_webui.internal.db import Base, get_db
from open_webui.utils.redis import get_redis_connection


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/health") == -1


# Filter out /endpoint
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

####################################
# Config helpers
####################################


# Function to run the alembic migrations
def run_migrations():
    """Run alembic upgrade to head.

    Fail-loud policy: 마이그레이션이 실패하면 startup 을 중단한다.
    이전 버전은 "Can't locate revision" 에러 시 alembic_version 을 silent
    하게 head 로 강제 stamp 했는데, 이것이 실제 DDL 누락(좀비 schema) 을
    마스킹하는 원인이었다 (oauth_oid, trusted_audience 등 누락 사례).

    이제는 모든 마이그레이션이 idempotent 하게 작성되어 있으므로 어떤
    출발 상태에서도 성공해야 한다. 실패는 운영 개입이 필요한 비정상
    상태이며 startup 단계에서 즉시 노출되어야 한다.
    """
    log.info("Running migrations")

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from open_webui.internal.db import engine

    alembic_cfg = Config(OPEN_WEBUI_DIR / "alembic.ini")

    migrations_path = OPEN_WEBUI_DIR / "migrations"
    alembic_cfg.set_main_option("script_location", str(migrations_path))

    is_postgres = "postgresql" in str(engine.url)

    with engine.connect() as lock_conn:
        if is_postgres:
            # Blocking advisory lock — 멀티워커 환경에서 비-리더 워커가
            # 리더의 마이그레이션 완료를 **기다린 뒤** 자기 차례에 락을 잡는다.
            # 락 획득 시점에는 alembic_version 이 head 이므로 command.upgrade 는
            # no-op 으로 즉시 리턴. 이후 verify_schema_state 가 일관된 schema 를
            # 본다.
            #
            # 이전 try_advisory_lock + early return 패턴은 비-리더가 리더 완료를
            # 기다리지 않고 verify_schema_state 로 직행해 race condition 발생
            # ("Missing tables" 으로 fail-loud) — 첫 부팅마다 워커 4개 중 3개가
            # 죽는 원인이었다.
            lock_conn.execute(text("SELECT pg_advisory_lock(7329001)"))

        try:
            command.upgrade(alembic_cfg, "head")
        except Exception as e:
            log.error(
                "===================================================\n"
                "DB MIGRATION FAILED — startup aborted.\n"
                "Inspect the alembic_version table and recent schema state, "
                "apply missing DDL manually if needed, then restart.\n"
                "===================================================\n"
                f"Error: {e}",
                exc_info=True,
            )
            raise
        finally:
            if is_postgres:
                lock_conn.execute(text("SELECT pg_advisory_unlock(7329001)"))
                lock_conn.commit()


def verify_schema_state():
    """Schema 무결성 점검 — 마이그레이션이 silent 하게 일부만 적용된 좀비
    상태를 startup 단계에서 잡는다.

    핵심 컬럼/테이블 N개의 존재 여부를 확인. 누락된 항목이 있으면 명확한
    에러 메시지로 fail-loud — 운영팀이 즉시 인지할 수 있도록.

    검사 대상은 "최근 추가되어 누락 가능성이 있는" 항목으로 한정. 모든
    스키마를 검사하지는 않는다 (그건 alembic 의 역할).
    """
    from sqlalchemy import inspect

    from open_webui.env import DATABASE_SCHEMA
    from open_webui.internal.db import engine

    required_tables = [
        "knowledge_graph",
        "kg_node",
        "kg_edge",
        "kg_candidate",
        "trusted_audience",
        "user_oauth_token",
        "extraction_engine_profile",
    ]
    required_columns = {
        "user": ["oauth_oid", "oauth_sub"],
        "document_profile": ["extension_engine_map", "default_engine_id"],
    }

    # ACME 등 custom schema (DATABASE_SCHEMA=custom_schema) 환경에서는 inspector
    # 가 schema 인자 없이 호출되면 public 만 검사해 false negative 발생.
    # alembic / engine / metadata 모두 DATABASE_SCHEMA 를 사용하므로 여기서도
    # 동일하게 적용. None 이면 기본 schema (public).
    schema = DATABASE_SCHEMA or None

    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema=schema))
    except Exception as e:
        log.warning(f"Schema verification skipped (DB not ready): {e}")
        return

    missing_tables = [t for t in required_tables if t not in existing_tables]
    missing_columns: list[str] = []
    for table, cols in required_columns.items():
        if table not in existing_tables:
            missing_columns.extend(f"{table}.{c}" for c in cols)
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table, schema=schema)}
        missing_columns.extend(f"{table}.{c}" for c in cols if c not in existing_cols)

    if missing_tables or missing_columns:
        msg = (
            "===================================================\n"
            "SCHEMA VERIFICATION FAILED — startup aborted.\n"
            "Migrations reported success but expected schema is missing.\n"
            "This is a 'zombie' state — likely caused by older silent-stamp\n"
            "auto-recovery. Apply missing DDL manually and restart.\n"
            "===================================================\n"
            f"Missing tables: {missing_tables}\n"
            f"Missing columns: {missing_columns}"
        )
        log.error(msg)
        raise RuntimeError(msg)

    log.info("Schema verification passed")


class Config(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())


####################################
# Config encryption & versioning
####################################


class ConfigVersionConflict(Exception):
    """Raised when config version doesn't match expected version (optimistic locking)."""

    def __init__(self, current_version: int, expected_version: int):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__(
            f"Config version conflict: expected {expected_version}, "
            f"but current is {current_version}"
        )


# Patterns for auto-detecting sensitive config paths
SENSITIVE_CONFIG_PATTERNS = {
    "secret",
    "password",
    "api_key",
    "api_keys",
    "credentials",
    "access_key",
    "credentials_json",
    "subscription_key",
    "service_account_key",
    "auth_token",
    "auth_password",
}

# Suffix patterns: any config path ending with these is likely sensitive
SENSITIVE_CONFIG_SUFFIXES = {"_key", "_keys", "_secret", "_password", "_token"}


def is_sensitive_path(path: str) -> bool:
    """Check if a config path points to a sensitive value based on naming pattern or suffix."""
    key = path.split(".")[-1].lower()
    if any(p in key for p in SENSITIVE_CONFIG_PATTERNS):
        return True
    return any(key.endswith(s) for s in SENSITIVE_CONFIG_SUFFIXES)


def get_sensitive_paths() -> set:
    """
    Return all config paths that should be encrypted.
    Resolution order: explicit sensitive=True > explicit sensitive=False > auto-detect by pattern.
    """
    paths = set()
    for item in PERSISTENT_CONFIG_REGISTRY:
        if item.sensitive is True:
            paths.add(item.config_path)
        elif item.sensitive is None and is_sensitive_path(item.config_path):
            paths.add(item.config_path)
        # sensitive=False explicitly excludes
    return paths


def get_sensitive_paths_with_meta() -> dict:
    """
    Return all sensitive config paths with their KMS Phase 2 metadata.

    Maps config_path → {
        "classification": Classification,
        "pii": bool,
        "retention_days": int | None,
        "local_only": bool,
    }

    Resolution order for each metadata field: explicit > name-based inference
    > default. Used by `_encrypt_at_path` to build the AAD context per value
    so envelope providers can bind ciphertexts to (config_path, classification,
    tenant_id, written_at).
    """
    from open_webui.utils.kms import Classification, infer_classification

    meta: dict[str, dict] = {}
    explicit_by_path: dict[str, "PersistentConfig"] = {}

    # Tolerate calls during module bootstrap (CONFIG_DATA = get_config() runs
    # before PERSISTENT_CONFIG_REGISTRY is declared). Fernet provider ignores
    # the context, so an empty registry just means "no AAD" — safe.
    registry = globals().get("PERSISTENT_CONFIG_REGISTRY", [])
    for item in registry:
        is_sensitive = item.sensitive is True or (
            item.sensitive is None and is_sensitive_path(item.config_path)
        )
        if not is_sensitive:
            continue
        # If multiple PersistentConfig entries share a path (rare but legal),
        # last-explicit wins so a registry update can override an earlier
        # auto-detected entry.
        explicit_by_path[item.config_path] = item

    for path, item in explicit_by_path.items():
        inferred = infer_classification(path.split(".")[-1])
        if item.classification is not None:
            classification = Classification.from_value(item.classification)
        else:
            classification = inferred.classification
        pii = item.pii if item.pii is not None else inferred.pii
        meta[path] = {
            "classification": classification,
            "pii": pii,
            "retention_days": item.retention_days,
            "local_only": bool(item.local_only),
        }
    return meta


def get_path_meta(config_path: str) -> dict:
    """Return KMS metadata for a single path. Falls back to inferred values
    so callers (config.py encrypt/decrypt path, dbsphere.py) can build AAD
    context even for paths not registered as PersistentConfig (e.g. nested
    DbSphere connection passwords stored under a parent config).
    """
    from open_webui.utils.kms import infer_classification

    registered = get_sensitive_paths_with_meta().get(config_path)
    if registered is not None:
        return registered
    inferred = infer_classification(config_path.split(".")[-1] if config_path else "")
    return {
        "classification": inferred.classification,
        "pii": inferred.pii,
        "retention_days": None,
        "local_only": False,
    }


def _encrypt_at_path(data: dict, path: str, meta: dict | None = None):
    """Navigate to a config path and encrypt the value in-place.

    `meta` carries the KMS Phase 2 metadata for this path (classification,
    pii, retention_days, local_only) — used to build an AAD context bound
    to the (config_path, classification) pair. Phase 3 envelope providers
    will validate that the same context is supplied at decrypt time.

    `local_only=True` paths bypass the configured KMS provider entirely
    and use the local Fernet provider directly. This is required for KMS
    bootstrap secrets (e.g. KMS_AZURE_CLIENT_SECRET) — encrypting them
    with the very KMS they authenticate to creates a chicken-and-egg
    deadlock at decrypt time.
    """
    from open_webui.utils.crypto import encrypt_value, is_encrypted
    from open_webui.utils.kms import build_aad_context
    from open_webui.utils.kms.fernet import FernetProvider

    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]

    key = parts[-1]
    if key not in current:
        return

    meta = meta or {}
    classification = meta.get("classification")
    local_only = bool(meta.get("local_only"))
    context: dict | None = None
    if classification is not None and not local_only:
        context = build_aad_context(
            config_path=path,
            classification=classification,
            tenant_id="",  # system-wide config; per-tenant config arrives Phase 5
        )

    # local_only → Fernet always; otherwise the configured router default.
    fernet_provider = FernetProvider() if local_only else None

    def _enc(v: str) -> str:
        if local_only:
            return fernet_provider.encrypt(v)
        return encrypt_value(v, context=context)

    value = current[key]
    if isinstance(value, str) and value and not is_encrypted(value):
        current[key] = _enc(value)
    elif isinstance(value, list):
        current[key] = [
            _enc(v) if isinstance(v, str) and v and not is_encrypted(v) else v
            for v in value
        ]


def _encrypt_config_data(data: dict) -> dict:
    """Deep copy config data and encrypt all sensitive values before DB storage."""
    encrypted = copy.deepcopy(data)
    paths_meta = get_sensitive_paths_with_meta()

    for path, meta in paths_meta.items():
        _encrypt_at_path(encrypted, path, meta)

    return encrypted


def _decrypt_config_data(data, _path: str = ""):
    """
    Recursively walk config data and decrypt any KMS-tagged or legacy
    Fernet-encrypted values. Tag prefix detection means no path registry
    is needed for decryption — values that are already plaintext pass
    through unchanged for backward compatibility.

    `_path` is the dotted config path of the current sub-tree, used to
    rebuild the AAD context for Phase 3+ envelope providers. The Fernet
    provider ignores the context so legacy data keeps decrypting.
    """
    from open_webui.utils.crypto import decrypt_value, is_encrypted

    if isinstance(data, dict):
        decrypted = {}
        for key, value in data.items():
            sub_path = f"{_path}.{key}" if _path else key
            if isinstance(value, dict):
                decrypted[key] = _decrypt_config_data(value, sub_path)
            elif isinstance(value, str) and is_encrypted(value):
                try:
                    decrypted[key] = decrypt_value(
                        value, context=_context_for_path(sub_path)
                    )
                except ValueError:
                    log.warning(
                        f"Failed to decrypt config key '{key}', keeping encrypted value"
                    )
                    decrypted[key] = value
            elif isinstance(value, list):
                decrypted[key] = _decrypt_config_data(value, sub_path)
            else:
                decrypted[key] = value
        return decrypted
    elif isinstance(data, list):
        return [
            _decrypt_config_data(item, _path)
            if isinstance(item, (dict, list))
            else (_try_decrypt(item, _path) if isinstance(item, str) else item)
            for item in data
        ]
    return data


def _context_for_path(path: str) -> dict | None:
    """Build the AAD context for a given config path, or None if not sensitive."""
    from open_webui.utils.kms import build_aad_context

    meta = get_path_meta(path)
    classification = meta.get("classification")
    if classification is None:
        return None
    return build_aad_context(
        config_path=path,
        classification=classification,
        tenant_id="",
    )


def _try_decrypt(value: str, path: str = "") -> str:
    """Try to decrypt a string value, returning original if not encrypted or on failure."""
    from open_webui.utils.crypto import decrypt_value, is_encrypted

    if is_encrypted(value):
        try:
            return decrypt_value(value, context=_context_for_path(path))
        except ValueError:
            log.warning("Failed to decrypt a config list item, keeping as-is")
    return value


def load_json_config():
    with open(f"{DATA_DIR}/config.json", "r") as file:
        return json.load(file)


def save_to_db(data, expected_version=None):
    """
    Save config data to database with encryption and optional optimistic locking.

    Args:
        data: Config data dict (plaintext, will be encrypted before storage)
        expected_version: If provided, checks version match before saving (optimistic lock).
                         If None, saves unconditionally (used by PersistentConfig.save).

    Returns:
        Current version number after save.

    Raises:
        ConfigVersionConflict: If expected_version doesn't match current version.
    """
    encrypted_data = _encrypt_config_data(data)
    with get_db() as db:
        existing_config = db.query(Config).order_by(Config.id.desc()).first()
        if not existing_config:
            new_config = Config(data=encrypted_data, version=0)
            db.add(new_config)
            db.commit()
            return 0
        else:
            if (
                expected_version is not None
                and existing_config.version != expected_version
            ):
                raise ConfigVersionConflict(existing_config.version, expected_version)
            existing_config.data = encrypted_data
            existing_config.version = (existing_config.version or 0) + 1
            existing_config.updated_at = datetime.now()
            db.add(existing_config)
            db.commit()
            return existing_config.version


def reset_config():
    with get_db() as db:
        db.query(Config).delete()
        db.commit()


# When initializing, check if config.json exists and migrate it to the database
if os.path.exists(f"{DATA_DIR}/config.json"):
    data = load_json_config()
    save_to_db(data)
    os.rename(f"{DATA_DIR}/config.json", f"{DATA_DIR}/old_config.json")

DEFAULT_CONFIG = {
    "version": 0,
    "ui": {
        "default_locale": "",
        "prompt_suggestions": [
            {
                "title": [
                    "Help me study",
                    "vocabulary for a college entrance exam",
                ],
                "content": "Help me study vocabulary: write a sentence for me to fill in the blank, and I'll try to pick the correct option.",
            },
            {
                "title": [
                    "Give me ideas",
                    "for what to do with my kids' art",
                ],
                "content": "What are 5 creative things I could do with my kids' art? I don't want to throw them away, but it's also so much clutter.",
            },
            {
                "title": ["Tell me a fun fact", "about the Roman Empire"],
                "content": "Tell me a random fun fact about the Roman Empire",
            },
            {
                "title": [
                    "Show me a code snippet",
                    "of a website's sticky header",
                ],
                "content": "Show me a code snippet of a website's sticky header in CSS and JavaScript.",
            },
            {
                "title": [
                    "Explain options trading",
                    "if I'm familiar with buying and selling stocks",
                ],
                "content": "Explain options trading in simple terms if I'm familiar with buying and selling stocks.",
            },
            {
                "title": ["Overcome procrastination", "give me tips"],
                "content": "Could you start by asking me about instances when I procrastinate the most and then give me some suggestions to overcome it?",
            },
            {
                "title": [
                    "Grammar check",
                    "rewrite it for better readability ",
                ],
                "content": 'Check the following sentence for grammar and clarity: "[sentence]". Rewrite it for better readability while maintaining its original meaning.',
            },
        ],
    },
}


def get_config():
    # 모듈 import 시점(`CONFIG_DATA = get_config()`)에 호출되며, 이때는 아직
    # main.py lifespan 의 run_migrations 가 돌기 전이라 빈 DB 에서는
    # `config` 테이블이 없을 수 있다. 빈/미마이그레이션 DB 에서 부팅을 막지
    # 않도록 DB 오류는 fallback 처리한다 (마이그레이션 후 reset/save_config
    # 시점에 정상 갱신됨).
    try:
        with get_db() as db:
            config_entry = db.query(Config).order_by(Config.id.desc()).first()
            if config_entry:
                return _decrypt_config_data(config_entry.data)
    except Exception as e:
        log.warning(
            "Config 테이블 조회 실패 — DEFAULT_CONFIG 로 부팅을 계속함 "
            "(빈 DB 또는 마이그레이션 전 상태로 추정): %s",
            e,
        )
    return DEFAULT_CONFIG


def get_config_with_version() -> tuple[dict, int]:
    """Get config data and version in a single DB query for atomic read-modify-write."""
    with get_db() as db:
        config_entry = db.query(Config).order_by(Config.id.desc()).first()
        if config_entry:
            return _decrypt_config_data(config_entry.data), config_entry.version
        return DEFAULT_CONFIG.copy(), 0


def get_config_version() -> int:
    """Get the current config version for optimistic locking."""
    with get_db() as db:
        config_entry = db.query(Config).order_by(Config.id.desc()).first()
        return config_entry.version if config_entry else 0


CONFIG_DATA = get_config()


def reload_all_persistent_configs() -> tuple[int, list[tuple[str, str]]]:
    """Refetch CONFIG_DATA from DB and refresh every registered PersistentConfig.

    Used by:
      1. main.py bootstrap — heals the fernet→azkv-env cold-start race where
         CONFIG_DATA was decrypted before KMS_PROVIDER existed (TODO: the
         cleaner fix is moving KMS_PROVIDER definition above this function;
         that requires verifying KMS_PROVIDER has no upstream PersistentConfig
         dependency).
      2. Redis pub/sub CONFIG_INVALIDATE_ALL — keeps multi-worker deployments
         in sync after admin saves config.

    Returns:
        (refreshed_count, failed: list of (env_name, error_str)).

    Honors ENABLE_PERSISTENT_CONFIG=False — no-op in that mode so env-vars
    stay authoritative.
    """
    global CONFIG_DATA
    if not ENABLE_PERSISTENT_CONFIG:
        return 0, []
    CONFIG_DATA = get_config()
    failed: list[tuple[str, str]] = []
    for cfg in PERSISTENT_CONFIG_REGISTRY:
        try:
            cfg.update()
        except Exception as e:
            failed.append((cfg.env_name, str(e)))
    return len(PERSISTENT_CONFIG_REGISTRY) - len(failed), failed


def get_config_value(config_path: str):
    path_parts = config_path.split(".")
    cur_config = CONFIG_DATA
    for key in path_parts:
        if key in cur_config:
            cur_config = cur_config[key]
        else:
            return None
    return cur_config


PERSISTENT_CONFIG_REGISTRY = []


def save_config(config, expected_version=None):
    """
    Save full config and update all PersistentConfig entries.

    Args:
        config: Full config dict to save.
        expected_version: Optional version for optimistic locking (used by import endpoint).

    Raises:
        ConfigVersionConflict: If expected_version doesn't match.
    """
    global CONFIG_DATA
    global PERSISTENT_CONFIG_REGISTRY
    try:
        save_to_db(config, expected_version=expected_version)
        CONFIG_DATA = config

        # Trigger updates on all registered PersistentConfig entries
        for config_item in PERSISTENT_CONFIG_REGISTRY:
            config_item.update()

        # Bulk-import 경로는 AppConfig.__setattr__를 거치지 않아 기본 publish 경로가
        # 없음. 다른 워커에 "전체 reload"를 지시하는 sentinel 메시지를 발사한다.
        # OAuth 자격증명(GOOGLE_CLIENT_ID 등)을 런타임에 바꿀 수 있는 실질 유일
        # 경로가 이 import 엔드포인트이므로, 누락 시 멀티워커 동기화가 아예 안 됨.
        try:
            from open_webui.env import (
                REDIS_SENTINEL_HOSTS,
                REDIS_SENTINEL_PORT,
                REDIS_URL,
            )
            from open_webui.utils.redis import get_sentinels_from_env

            if REDIS_URL:
                r = get_redis_connection(
                    REDIS_URL,
                    get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
                    decode_responses=True,
                )
                r.publish(CONFIG_INVALIDATE_CHANNEL, CONFIG_INVALIDATE_ALL)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, skipping bulk config invalidation: {e}")
        except Exception as e:
            log.warning(f"Failed to publish bulk config invalidation: {e}")
    except ConfigVersionConflict:
        raise
    except Exception as e:
        log.exception(e)
        return False
    return True


T = TypeVar("T")

ENABLE_PERSISTENT_CONFIG = (
    os.environ.get("ENABLE_PERSISTENT_CONFIG", "True").lower() == "true"
)


class PersistentConfig(Generic[T]):
    def __init__(
        self,
        env_name: str,
        config_path: str,
        env_value: T,
        sensitive: bool = None,
        *,
        classification: object = None,
        pii: bool = None,
        retention_days: int = None,
        local_only: bool = False,
    ):
        # KMS Phase 2 metadata. All fields keyword-only and default to None
        # so existing PersistentConfig() call sites stay unchanged.
        #   classification — explicit Classification (or str) overriding the
        #       name-based auto-inference. None = infer from config_path.
        #   pii — explicit override for PII flag. None = infer.
        #   retention_days — None = unlimited (system secrets); positive int
        #       triggers crypto-shredding when exceeded (Phase 4+).
        #   local_only — True forces this value to always use the local
        #       Fernet provider, even when KMS_PROVIDER is azkv/awskms/etc.
        #       Used for KMS bootstrap secrets (vault auth tokens, etc.).
        self.env_name = env_name
        self.config_path = config_path
        self.env_value = env_value
        self.sensitive = (
            sensitive  # None=auto-detect, True=force encrypt, False=exclude
        )
        self.classification = classification
        self.pii = pii
        self.retention_days = retention_days
        self.local_only = local_only
        self.config_value = get_config_value(config_path)
        if self.config_value is not None and ENABLE_PERSISTENT_CONFIG:
            log.info(f"'{env_name}' loaded from the latest database entry")
            self.value = self.config_value
        else:
            self.value = env_value

        PERSISTENT_CONFIG_REGISTRY.append(self)

    def __str__(self):
        return str(self.value)

    @property
    def __dict__(self):
        raise TypeError(
            "PersistentConfig object cannot be converted to dict, use config_get or .value instead."
        )

    def __getattribute__(self, item):
        if item == "__dict__":
            raise TypeError(
                "PersistentConfig object cannot be converted to dict, use config_get or .value instead."
            )
        return super().__getattribute__(item)

    def update(self):
        new_value = get_config_value(self.config_path)
        if new_value is not None:
            self.value = new_value
            log.info(f"Updated {self.env_name} to new value {self.value}")

    def save(self):
        """
        Save this config to the database using read-modify-write with optimistic locking.

        Instead of blindly overwriting the entire CONFIG_DATA (which may be stale in
        multi-worker deployments), this reads the latest config from the DB, applies
        only this key's change, and saves with version checking. On conflict, retries
        with fresh data.
        """
        global CONFIG_DATA
        log.info(f"Saving '{self.env_name}' to the database")

        max_retries = 3
        for attempt in range(max_retries):
            # 1) Read latest config + version from DB
            fresh_config, version = get_config_with_version()

            # 2) Apply only this key's value to the fresh config
            path_parts = self.config_path.split(".")
            sub_config = fresh_config
            for key in path_parts[:-1]:
                if key not in sub_config:
                    sub_config[key] = {}
                sub_config = sub_config[key]
            sub_config[path_parts[-1]] = self.value

            # 3) Save with optimistic locking
            try:
                save_to_db(fresh_config, expected_version=version)
                # 4) Update local CONFIG_DATA with fresh state
                CONFIG_DATA = fresh_config
                self.config_value = self.value
                return
            except ConfigVersionConflict:
                if attempt < max_retries - 1:
                    log.warning(
                        f"Config version conflict while saving '{self.env_name}', "
                        f"retrying ({attempt + 1}/{max_retries})"
                    )
                    continue
                log.error(
                    f"Config version conflict persisted after {max_retries} retries "
                    f"for '{self.env_name}', saving without version check"
                )

        # Fallback: save without version check to avoid data loss
        fresh_config, _ = get_config_with_version()
        path_parts = self.config_path.split(".")
        sub_config = fresh_config
        for key in path_parts[:-1]:
            if key not in sub_config:
                sub_config[key] = {}
            sub_config = sub_config[key]
        sub_config[path_parts[-1]] = self.value
        save_to_db(fresh_config)
        CONFIG_DATA = fresh_config
        self.config_value = self.value


class AppConfig:
    _state: dict[str, PersistentConfig]
    _redis: Optional[redis.Redis] = None

    def __init__(
        self, redis_url: Optional[str] = None, redis_sentinels: Optional[list] = []
    ):
        super().__setattr__("_state", {})
        if redis_url:
            super().__setattr__(
                "_redis",
                get_redis_connection(redis_url, redis_sentinels, decode_responses=True),
            )

    def __setattr__(self, key, value):
        if isinstance(value, PersistentConfig):
            self._state[key] = value
        else:
            self._state[key].value = value
            self._state[key].save()

            if self._redis:
                try:
                    redis_key = f"open-webui:config:{key}"
                    self._redis.set(redis_key, json.dumps(self._state[key].value))
                    # 다른 워커에 변경 알림 (key의 env_name을 페이로드로 전송).
                    # 메시지에는 식별용 env_name만 싣고, 값 자체는 위 SET을 통해
                    # 동일 키로 caching 되어 다른 워커가 읽을 수 있다.
                    self._redis.publish(CONFIG_INVALIDATE_CHANNEL, key)
                except (redis.ConnectionError, redis.TimeoutError) as e:
                    log.warning(
                        f"Redis unavailable, skipping config sync for {key}: {e}"
                    )

    def __getattr__(self, key):
        if key not in self._state:
            raise AttributeError(f"Config key '{key}' not found")

        # If Redis is available, check for an updated value
        if self._redis:
            try:
                redis_key = f"open-webui:config:{key}"
                redis_value = self._redis.get(redis_key)

                if redis_value is not None:
                    try:
                        decoded_value = json.loads(redis_value)

                        # Update the in-memory value if different
                        if self._state[key].value != decoded_value:
                            self._state[key].value = decoded_value
                            log.info(f"Updated {key} from Redis: {decoded_value}")

                    except json.JSONDecodeError:
                        log.error(
                            f"Invalid JSON format in Redis for {key}: {redis_value}"
                        )
            except (redis.ConnectionError, redis.TimeoutError) as e:
                log.warning(f"Redis unavailable, using in-memory config for {key}: {e}")

        return self._state[key].value


####################################
# KMS / Key Management
####################################
#
# Selects the backend that encrypts sensitive PersistentConfig values
# and DbSphere connection passwords. ``fernet`` (default) is the
# self-managed mode using WEBUI_SECRET_KEY and requires no external
# infrastructure. ``azkv-env`` enables Azure Key Vault envelope mode —
# data encrypted locally with AES-256-GCM, the per-message DEK wrapped
# by an RSA KEK that lives in Azure Key Vault.
#
# Switching the provider does not require a data migration: legacy and
# tagged ciphertexts coexist and are auto-routed by tag prefix.
#
# These config keys themselves are sensitive=False — they describe how
# to reach the KMS, not secrets. The vault URI / key id are public,
# and authentication uses Managed Identity by default (no token to
# store). When a client secret is unavoidable, store it as a separate
# PersistentConfig with local_only=True so it never recurses through
# the very KMS it's used to authenticate to.

KMS_PROVIDER = PersistentConfig(
    "KMS_PROVIDER",
    "kms.provider",
    os.environ.get("KMS_PROVIDER", "fernet").strip().lower(),
    sensitive=False,
)

KMS_AZURE_KEY_VAULT_KEY_URI = PersistentConfig(
    "KMS_AZURE_KEY_VAULT_KEY_URI",
    "kms.azure.key_vault.key_uri",
    os.environ.get("KMS_AZURE_KEY_VAULT_KEY_URI", ""),
    sensitive=False,
)

# Phase 4.4 — optional Restricted-tier KEK separation. When set, values
# whose AAD context carries ``classification=='restricted'`` (PII, account
# numbers, etc.) get wrapped under this KEK instead of the default one
# above. The two KEKs can sit in different vaults — common pattern is
# Standard vault for `confidential` data + Premium / Managed HSM vault
# for `restricted` PII so PII can be crypto-shredded independently.
# Empty value → all classifications share the default KEK.

KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED = PersistentConfig(
    "KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED",
    "kms.azure.key_vault.key_uri_restricted",
    os.environ.get("KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED", ""),
    sensitive=False,
)

# Optional Service Principal for Key Vault access. Use when the Key Vault
# lives in a *different* tenant than the existing MICROSOFT_CLIENT_* OAuth
# app — common when identity is centralised in one tenant but workload
# resources sit in another. When unset, CryptoClientFactory falls back to
# MICROSOFT_CLIENT_* (re-using the existing OAuth credentials), and finally
# to DefaultAzureCredential (Managed Identity / az login).
#
# The secret is local_only=True so it never recurses through the KMS it is
# used to authenticate to — chicken-and-egg avoidance.

KMS_AZURE_TENANT_ID = PersistentConfig(
    "KMS_AZURE_TENANT_ID",
    "kms.azure.tenant_id",
    os.environ.get("KMS_AZURE_TENANT_ID", ""),
    sensitive=False,
)

KMS_AZURE_CLIENT_ID = PersistentConfig(
    "KMS_AZURE_CLIENT_ID",
    "kms.azure.client_id",
    os.environ.get("KMS_AZURE_CLIENT_ID", ""),
    sensitive=False,
)

KMS_AZURE_CLIENT_SECRET = PersistentConfig(
    "KMS_AZURE_CLIENT_SECRET",
    "kms.azure.client_secret",
    os.environ.get("KMS_AZURE_CLIENT_SECRET", ""),
    sensitive=True,
    local_only=True,
    classification="confidential",
)

# Phase 4.5 — automatic KEK rotation. The scheduler runs a lightweight
# check every interval; if Azure KV has a newer KEK version (typically
# created by KV's own ``rotation_policy``), the rotate flow fires.
# ``dry_run`` mode records the would-rotate decision to the audit log
# without touching the configured URI — useful for the first activation
# period to build operator trust.

KMS_ROTATION_AUTO_ENABLED = PersistentConfig(
    "KMS_ROTATION_AUTO_ENABLED",
    "kms.rotation.auto_enabled",
    str(os.environ.get("KMS_ROTATION_AUTO_ENABLED", "False")).lower() == "true",
    sensitive=False,
)

KMS_ROTATION_CHECK_INTERVAL_HOURS = PersistentConfig(
    "KMS_ROTATION_CHECK_INTERVAL_HOURS",
    "kms.rotation.check_interval_hours",
    int(os.environ.get("KMS_ROTATION_CHECK_INTERVAL_HOURS", "24")),
    sensitive=False,
)

KMS_ROTATION_DRY_RUN = PersistentConfig(
    "KMS_ROTATION_DRY_RUN",
    "kms.rotation.dry_run",
    str(os.environ.get("KMS_ROTATION_DRY_RUN", "False")).lower() == "true",
    sensitive=False,
)

# Last check / last rotation summary, written by the scheduler tick so
# the admin UI can surface "last check" / "last rotation result" without
# polling the audit log directly.
KMS_ROTATION_LAST_CHECK_AT = PersistentConfig(
    "KMS_ROTATION_LAST_CHECK_AT",
    "kms.rotation.last_check_at",
    int(os.environ.get("KMS_ROTATION_LAST_CHECK_AT", "0")),
    sensitive=False,
)

KMS_ROTATION_LAST_RESULT = PersistentConfig(
    "KMS_ROTATION_LAST_RESULT",
    "kms.rotation.last_result",
    os.environ.get("KMS_ROTATION_LAST_RESULT", ""),
    sensitive=False,
)


####################################
# WEBUI_AUTH (Required for security)
####################################

ENABLE_API_KEY = PersistentConfig(
    "ENABLE_API_KEY",
    "auth.api_key.enable",
    os.environ.get("ENABLE_API_KEY", "True").lower() == "true",
    sensitive=False,  # boolean flag, not a secret
)

ENABLE_API_KEY_ENDPOINT_RESTRICTIONS = PersistentConfig(
    "ENABLE_API_KEY_ENDPOINT_RESTRICTIONS",
    "auth.api_key.endpoint_restrictions",
    os.environ.get("ENABLE_API_KEY_ENDPOINT_RESTRICTIONS", "False").lower() == "true",
    sensitive=False,  # boolean flag, not a secret
)

API_KEY_ALLOWED_ENDPOINTS = PersistentConfig(
    "API_KEY_ALLOWED_ENDPOINTS",
    "auth.api_key.allowed_endpoints",
    os.environ.get("API_KEY_ALLOWED_ENDPOINTS", ""),
    sensitive=False,  # endpoint list, not a secret
)


JWT_EXPIRES_IN = PersistentConfig(
    "JWT_EXPIRES_IN", "auth.jwt_expiry", os.environ.get("JWT_EXPIRES_IN", "-1")
)

####################################
# OAuth config
####################################


ENABLE_OAUTH_SIGNUP = PersistentConfig(
    "ENABLE_OAUTH_SIGNUP",
    "oauth.enable_signup",
    os.environ.get("ENABLE_OAUTH_SIGNUP", "False").lower() == "true",
)


OAUTH_MERGE_ACCOUNTS_BY_EMAIL = PersistentConfig(
    "OAUTH_MERGE_ACCOUNTS_BY_EMAIL",
    "oauth.merge_accounts_by_email",
    os.environ.get("OAUTH_MERGE_ACCOUNTS_BY_EMAIL", "False").lower() == "true",
)

# Email 비식별화: True이면 email의 @ 앞부분(계정명)만 DB에 저장
# SSO 전용 환경에서 개인정보(full email) 저장을 피하기 위해 사용
ENABLE_EMAIL_DEIDENTIFY = (
    os.environ.get("ENABLE_EMAIL_DEIDENTIFY", "False").lower() == "true"
)

OAUTH_PROVIDERS = {}

# 이메일/캘린더 연동 활성화 시 OAuth 로그인 scope 에 추가되는 위임 권한 목록.
# 토글이 켜진 provider 한해 load_oauth_providers() 가 동적으로 base scope 와 결합한다.
# 추가 시 Azure / Google Cloud Console 의 앱 등록에도 동일 권한이 부여돼 있어야 한다.
GRAPH_DELEGATED_SCOPES = [
    # Mail
    "Mail.Read",
    "Mail.ReadBasic.Shared",  # 공유 mailbox 메일 읽기
    "Mail.Send",
    # Calendar
    "Calendars.ReadWrite",  # 본인 캘린더 read + 일정 생성/수정
    "Calendars.Read.Shared",  # 회의실/동료 캘린더 가용성 조회
    # Files (OneDrive / SharePoint)
    "Files.Read.All",
    "Sites.Read.All",  # Microsoft 365 Search / SharePoint 문서
    # Productivity
    "Contacts.Read",
    "Tasks.ReadWrite",
    "Notes.ReadWrite",
    # Directory
    "User.ReadBasic.All",  # 동료 자동완성·조직도 lookup (민감 필드 제외)
    # OAuth
    "offline_access",  # refresh_token 발급에 필수 — 빠지면 1시간 뒤 재로그인 필요
]

# Google Workspace 마켓플레이스 MCP(taylorwilsdon/google_workspace_mcp@1.21.0, --tools
# gmail calendar drive docs sheets slides forms tasks contacts chat)로 OAuth passthrough
# 하기 위한 위임 스코프. 사용자의 Google 로그인 토큰이 이 스코프들을 보유해야 MCP 가
# 사용자 대신 각 API 를 호출할 수 있다. 스코프는 위 서버 auth/scopes.py 의 SCOPE_GROUPS 기준.
# 서비스 추가/제거 시 services/GoogleWorkspaceMCP/Dockerfile 의 --tools 목록과 함께 갱신.
# prompt=consent(load_oauth_providers) 덕분에 스코프 변경 시 기존 사용자도 재로그인 1회로 재동의.
# 주의: drive(full)는 Google "restricted scope" — 외부 게시 앱은 별도 검증(CASA) 필요(내부 org 앱은 면제).
GMAIL_DELEGATED_SCOPES = [
    # Gmail (읽기 + 발송)
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    # Calendar (이벤트)
    "https://www.googleapis.com/auth/calendar.events",
    # Drive (전체 읽기/쓰기 — docs/sheets/slides 의 Drive 접근도 포함)
    "https://www.googleapis.com/auth/drive",
    # Docs
    "https://www.googleapis.com/auth/documents",
    # Sheets
    "https://www.googleapis.com/auth/spreadsheets",
    # Slides
    "https://www.googleapis.com/auth/presentations",
    # Forms (양식 본문 read/write + 응답 읽기)
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    # Tasks
    "https://www.googleapis.com/auth/tasks",
    # Contacts (People API)
    "https://www.googleapis.com/auth/contacts",
    # Chat (메시지 read/write + 스페이스)
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.spaces",
]

# 채팅 통합 기능(gmail/calendar/drive)별로 사용자 토큰이 보유해야 하는 최소 scope.
# GMAIL_DELEGATED_SCOPES 도입 이전에 SSO 로그인한 사용자는 토큰 row 는 있지만
# 이 scope 들이 빠져 있어 실행 시점에 Google 403 이 난다 — UI 토글 게이트
# (routers/email_integration.py)와 UnifiedAgent 5축 게이트가 이 상수로
# scope 충족 여부를 fail-closed 판정한다. 도구가 쓰는 scope 변경 시 함께 갱신.
GWS_FEATURE_REQUIRED_SCOPES: dict[str, set[str]] = {
    "gmail": {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    },
    "calendar": {"https://www.googleapis.com/auth/calendar.events"},
    "drive": {
        "https://www.googleapis.com/auth/drive",
        # drive_create_doc 은 Drive files.create + Docs batchUpdate 2-call
        "https://www.googleapis.com/auth/documents",
    },
}

# Gmail / Calendar 채팅 통합 admin 토글. 4단계 게이트 (admin enable → group permission
# → user OAuth token → per-conversation toggle) 의 1단계.  기본 False 로 안전 시작.
# OAuth scope 동의는 위 GMAIL_DELEGATED_SCOPES 로 SSO 시 결합되며, 이 토글은 채팅에서
# 실제로 도구를 LLM 에 노출할지 여부만 제어한다.
ENABLE_GMAIL_INTEGRATION = PersistentConfig(
    "ENABLE_GMAIL_INTEGRATION",
    "google.integration.gmail.enable",
    os.getenv("ENABLE_GMAIL_INTEGRATION", "False").lower() == "true",
)

ENABLE_CALENDAR_INTEGRATION = PersistentConfig(
    "ENABLE_CALENDAR_INTEGRATION",
    "google.integration.calendar.enable",
    os.getenv("ENABLE_CALENDAR_INTEGRATION", "False").lower() == "true",
)

# Drive 채팅 통합 admin 토글. ENABLE_GMAIL_INTEGRATION / ENABLE_CALENDAR_INTEGRATION
# 과 동일한 5축 게이트의 1단계. 기본 False 로 안전 시작.
# ⚠️ 기존 RAG 파일 업로드 피커 플래그 ENABLE_GOOGLE_DRIVE_INTEGRATION 과 별개 —
# 후자는 건드리지 않는다 (이름 충돌 방지). OAuth scope 변경 없음: drive_create_doc 의
# 2-call (Drive files.create + Docs batchUpdate) 은 GMAIL_DELEGATED_SCOPES 의
# auth/drive + auth/documents 로 이미 충족된다.
ENABLE_DRIVE_INTEGRATION = PersistentConfig(
    "ENABLE_DRIVE_INTEGRATION",
    "google.integration.drive.enable",
    os.getenv("ENABLE_DRIVE_INTEGRATION", "False").lower() == "true",
)

# Redis pub/sub channel for cross-worker config invalidation.
# Published by AppConfig.__setattr__ on every PersistentConfig change.
CONFIG_INVALIDATE_CHANNEL = "open-webui:config:invalidate"

# Special payload that instructs all workers to reload the ENTIRE PersistentConfig
# registry + OAuthManager. Used by bulk write paths (e.g. save_config via
# /api/v1/configs/import) where per-key publishing is impractical.
CONFIG_INVALIDATE_ALL = "__ALL__"

# Special payload that instructs all workers to drop their in-memory
# ``app.state.MODELS`` cache so the next chat request fetches a fresh list
# from DB + external APIs. Used by routers/models.py after model CRUD /
# toggle / delete to propagate registry changes across uvicorn worker
# processes (each worker holds its own in-memory MODELS dict, distinct
# from PersistentConfig which already syncs via this channel).
MODELS_INVALIDATE_KEY = "__MODELS__"


def publish_models_invalidate() -> None:
    """워커 간 in-memory ``app.state.MODELS`` 캐시 무효화 신호 발행.

    ``routers/models.py`` 의 모델 CRUD / toggle / delete 직후 호출해 다른
    워커 프로세스의 stale 캐시로 인한 간헐 ``Model not found`` 에러를
    예방한다. Subscriber 는 ``main.py`` 의 invalidation listener.

    Redis 미구성 환경에서는 no-op (단일 워커 가정).
    """
    try:
        from open_webui.env import (
            REDIS_SENTINEL_HOSTS,
            REDIS_SENTINEL_PORT,
            REDIS_URL,
        )
        from open_webui.utils.redis import get_sentinels_from_env

        if not REDIS_URL:
            return
        r = get_redis_connection(
            REDIS_URL,
            get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
            decode_responses=True,
        )
        r.publish(CONFIG_INVALIDATE_CHANNEL, MODELS_INVALIDATE_KEY)
    except (redis.ConnectionError, redis.TimeoutError) as e:
        log.warning(f"Redis unavailable, skipping MODELS invalidation: {e}")
    except Exception as e:
        log.warning(f"Failed to publish MODELS invalidation: {e}")


# PersistentConfig env_names whose change requires OAuthManager re-registration
# (authlib client closures snapshot these at register time).
OAUTH_PROVIDER_CONFIG_KEYS: set[str] = {
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_OAUTH_SCOPE",
    "GOOGLE_REDIRECT_URI",
    "MICROSOFT_CLIENT_ID",
    "MICROSOFT_CLIENT_SECRET",
    "MICROSOFT_CLIENT_TENANT_ID",
    "MICROSOFT_OAUTH_SCOPE",
    "MICROSOFT_REDIRECT_URI",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GITHUB_CLIENT_SCOPE",
    "GITHUB_CLIENT_REDIRECT_URI",
    "OAUTH_CLIENT_ID",
    "OAUTH_CLIENT_SECRET",
    "OPENID_PROVIDER_URL",
    "OPENID_REDIRECT_URI",
    "OAUTH_SCOPES",
    "OAUTH_CODE_CHALLENGE_METHOD",
    "OAUTH_PROVIDER_NAME",
}

# PersistentConfig env_names whose change must drop the per-process
# KMSRouter singleton. The singleton caches the active provider's KEK
# bindings, so a `set_kms_config` / `rotate_kms` on worker A invalidates
# every other worker's cached router. Without this list, workers B..N
# keep wrapping data under the *old* KEK after a rotation, producing
# silent ciphertext divergence.
KMS_CONFIG_KEYS: set[str] = {
    "KMS_PROVIDER",
    "KMS_AZURE_KEY_VAULT_KEY_URI",
    "KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED",
    "KMS_AZURE_TENANT_ID",
    "KMS_AZURE_CLIENT_ID",
    "KMS_AZURE_CLIENT_SECRET",
}

GOOGLE_CLIENT_ID = PersistentConfig(
    "GOOGLE_CLIENT_ID",
    "oauth.google.client_id",
    os.environ.get("GOOGLE_CLIENT_ID", ""),
)

GOOGLE_CLIENT_SECRET = PersistentConfig(
    "GOOGLE_CLIENT_SECRET",
    "oauth.google.client_secret",
    os.environ.get("GOOGLE_CLIENT_SECRET", ""),
)


GOOGLE_OAUTH_SCOPE = PersistentConfig(
    "GOOGLE_OAUTH_SCOPE",
    "oauth.google.scope",
    os.environ.get("GOOGLE_OAUTH_SCOPE", "openid email profile"),
)

GOOGLE_REDIRECT_URI = PersistentConfig(
    "GOOGLE_REDIRECT_URI",
    "oauth.google.redirect_uri",
    os.environ.get("GOOGLE_REDIRECT_URI", ""),
)


# Google Admin Directory API (조직/그룹 동기화)
GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY = os.environ.get(
    "GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY", ""
)
GOOGLE_ADMIN_IMPERSONATE_EMAIL = os.environ.get("GOOGLE_ADMIN_IMPERSONATE_EMAIL", "")
ENABLE_GOOGLE_ADMIN_SYNC = (
    os.environ.get("ENABLE_GOOGLE_ADMIN_SYNC", "False").lower() == "true"
)

MICROSOFT_CLIENT_ID = PersistentConfig(
    "MICROSOFT_CLIENT_ID",
    "oauth.microsoft.client_id",
    os.environ.get("MICROSOFT_CLIENT_ID", ""),
)

MICROSOFT_CLIENT_SECRET = PersistentConfig(
    "MICROSOFT_CLIENT_SECRET",
    "oauth.microsoft.client_secret",
    os.environ.get("MICROSOFT_CLIENT_SECRET", ""),
)

MICROSOFT_CLIENT_TENANT_ID = PersistentConfig(
    "MICROSOFT_CLIENT_TENANT_ID",
    "oauth.microsoft.tenant_id",
    os.environ.get("MICROSOFT_CLIENT_TENANT_ID", ""),
)

MICROSOFT_OAUTH_SCOPE = PersistentConfig(
    "MICROSOFT_OAUTH_SCOPE",
    "oauth.microsoft.scope",
    os.environ.get("MICROSOFT_OAUTH_SCOPE", "openid email profile"),
)

MICROSOFT_REDIRECT_URI = PersistentConfig(
    "MICROSOFT_REDIRECT_URI",
    "oauth.microsoft.redirect_uri",
    os.environ.get("MICROSOFT_REDIRECT_URI", ""),
)


GITHUB_CLIENT_ID = PersistentConfig(
    "GITHUB_CLIENT_ID",
    "oauth.github.client_id",
    os.environ.get("GITHUB_CLIENT_ID", ""),
)

GITHUB_CLIENT_SECRET = PersistentConfig(
    "GITHUB_CLIENT_SECRET",
    "oauth.github.client_secret",
    os.environ.get("GITHUB_CLIENT_SECRET", ""),
)

GITHUB_CLIENT_SCOPE = PersistentConfig(
    "GITHUB_CLIENT_SCOPE",
    "oauth.github.scope",
    os.environ.get("GITHUB_CLIENT_SCOPE", "user:email"),
)

GITHUB_CLIENT_REDIRECT_URI = PersistentConfig(
    "GITHUB_CLIENT_REDIRECT_URI",
    "oauth.github.redirect_uri",
    os.environ.get("GITHUB_CLIENT_REDIRECT_URI", ""),
)

OAUTH_CLIENT_ID = PersistentConfig(
    "OAUTH_CLIENT_ID",
    "oauth.oidc.client_id",
    os.environ.get("OAUTH_CLIENT_ID", ""),
)

OAUTH_CLIENT_SECRET = PersistentConfig(
    "OAUTH_CLIENT_SECRET",
    "oauth.oidc.client_secret",
    os.environ.get("OAUTH_CLIENT_SECRET", ""),
)

OPENID_PROVIDER_URL = PersistentConfig(
    "OPENID_PROVIDER_URL",
    "oauth.oidc.provider_url",
    os.environ.get("OPENID_PROVIDER_URL", ""),
)

OPENID_REDIRECT_URI = PersistentConfig(
    "OPENID_REDIRECT_URI",
    "oauth.oidc.redirect_uri",
    os.environ.get("OPENID_REDIRECT_URI", ""),
)

OAUTH_SCOPES = PersistentConfig(
    "OAUTH_SCOPES",
    "oauth.oidc.scopes",
    os.environ.get("OAUTH_SCOPES", "openid email profile"),
)

OAUTH_CODE_CHALLENGE_METHOD = PersistentConfig(
    "OAUTH_CODE_CHALLENGE_METHOD",
    "oauth.oidc.code_challenge_method",
    os.environ.get("OAUTH_CODE_CHALLENGE_METHOD", None),
)

OAUTH_PROVIDER_NAME = PersistentConfig(
    "OAUTH_PROVIDER_NAME",
    "oauth.oidc.provider_name",
    os.environ.get("OAUTH_PROVIDER_NAME", "SSO"),
)

OAUTH_USERNAME_CLAIM = PersistentConfig(
    "OAUTH_USERNAME_CLAIM",
    "oauth.oidc.username_claim",
    os.environ.get("OAUTH_USERNAME_CLAIM", "name"),
)


OAUTH_PICTURE_CLAIM = PersistentConfig(
    "OAUTH_PICTURE_CLAIM",
    "oauth.oidc.avatar_claim",
    os.environ.get("OAUTH_PICTURE_CLAIM", "picture"),
)

OAUTH_EMAIL_CLAIM = PersistentConfig(
    "OAUTH_EMAIL_CLAIM",
    "oauth.oidc.email_claim",
    os.environ.get("OAUTH_EMAIL_CLAIM", "email"),
)

OAUTH_GROUPS_CLAIM = PersistentConfig(
    "OAUTH_GROUPS_CLAIM",
    "oauth.oidc.group_claim",
    os.environ.get("OAUTH_GROUP_CLAIM", "groups"),
)

ENABLE_OAUTH_ROLE_MANAGEMENT = PersistentConfig(
    "ENABLE_OAUTH_ROLE_MANAGEMENT",
    "oauth.enable_role_mapping",
    os.environ.get("ENABLE_OAUTH_ROLE_MANAGEMENT", "False").lower() == "true",
)

ENABLE_OAUTH_GROUP_MANAGEMENT = PersistentConfig(
    "ENABLE_OAUTH_GROUP_MANAGEMENT",
    "oauth.enable_group_mapping",
    os.environ.get("ENABLE_OAUTH_GROUP_MANAGEMENT", "False").lower() == "true",
)

ENABLE_OAUTH_ORG_UNIT_MANAGEMENT = PersistentConfig(
    "ENABLE_OAUTH_ORG_UNIT_MANAGEMENT",
    "oauth.enable_org_unit_mapping",
    os.environ.get("ENABLE_OAUTH_ORG_UNIT_MANAGEMENT", "True").lower() == "true",
)

OAUTH_DEPARTMENT_CLAIM = PersistentConfig(
    "OAUTH_DEPARTMENT_CLAIM",
    "oauth.oidc.department_claim",
    os.environ.get("OAUTH_DEPARTMENT_CLAIM", "department"),
    sensitive=False,
)

OAUTH_ROLES_CLAIM = PersistentConfig(
    "OAUTH_ROLES_CLAIM",
    "oauth.roles_claim",
    os.environ.get("OAUTH_ROLES_CLAIM", "roles"),
)

OAUTH_ALLOWED_ROLES = PersistentConfig(
    "OAUTH_ALLOWED_ROLES",
    "oauth.allowed_roles",
    [
        role.strip()
        for role in os.environ.get("OAUTH_ALLOWED_ROLES", "user,admin").split(",")
    ],
)

OAUTH_ADMIN_ROLES = PersistentConfig(
    "OAUTH_ADMIN_ROLES",
    "oauth.admin_roles",
    [role.strip() for role in os.environ.get("OAUTH_ADMIN_ROLES", "admin").split(",")],
)

OAUTH_ALLOWED_DOMAINS = PersistentConfig(
    "OAUTH_ALLOWED_DOMAINS",
    "oauth.allowed_domains",
    [
        domain.strip()
        for domain in os.environ.get("OAUTH_ALLOWED_DOMAINS", "*").split(",")
    ],
)


def _merge_scopes(base: str, extra: list[str]) -> str:
    """공백 구분 base scope 문자열에 extra 항목을 중복 없이 추가."""
    seen = []
    for s in (base or "").split():
        if s and s not in seen:
            seen.append(s)
    for s in extra:
        if s and s not in seen:
            seen.append(s)
    return " ".join(seen)


def load_oauth_providers():
    OAUTH_PROVIDERS.clear()
    if GOOGLE_CLIENT_ID.value and GOOGLE_CLIENT_SECRET.value:
        # Gmail / Calendar / Drive scope 를 항상 추가. Google 은 offline_access
        # scope 가 없어서 access_type=offline 으로 refresh_token 을 요청 +
        # prompt=consent 로 scope 변경 시 기존 사용자도 새 동의 화면 통과.
        google_client_kwargs: dict = {
            "scope": _merge_scopes(GOOGLE_OAUTH_SCOPE.value, GMAIL_DELEGATED_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }

        def google_oauth_register(client):
            client.register(
                name="google",
                client_id=GOOGLE_CLIENT_ID.value,
                client_secret=GOOGLE_CLIENT_SECRET.value,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs=google_client_kwargs,
                redirect_uri=GOOGLE_REDIRECT_URI.value,
            )

        OAUTH_PROVIDERS["google"] = {
            "redirect_uri": GOOGLE_REDIRECT_URI.value,
            "register": google_oauth_register,
        }

    if (
        MICROSOFT_CLIENT_ID.value
        and MICROSOFT_CLIENT_SECRET.value
        and MICROSOFT_CLIENT_TENANT_ID.value
    ):
        # Microsoft Graph 위임 권한 (Mail / Calendar / Files 등) 항상 추가.
        # Azure 측에 admin grant 가 안 돼있으면 동의 화면이 막히는 게 가드.
        ms_scope = _merge_scopes(MICROSOFT_OAUTH_SCOPE.value, GRAPH_DELEGATED_SCOPES)

        def microsoft_oauth_register(client):
            client.register(
                name="microsoft",
                client_id=MICROSOFT_CLIENT_ID.value,
                client_secret=MICROSOFT_CLIENT_SECRET.value,
                server_metadata_url=f"https://login.microsoftonline.com/{MICROSOFT_CLIENT_TENANT_ID.value}/v2.0/.well-known/openid-configuration?appid={MICROSOFT_CLIENT_ID.value}",
                client_kwargs={
                    "scope": ms_scope,
                },
                redirect_uri=MICROSOFT_REDIRECT_URI.value,
            )

        OAUTH_PROVIDERS["microsoft"] = {
            "redirect_uri": MICROSOFT_REDIRECT_URI.value,
            "picture_url": "https://graph.microsoft.com/v1.0/me/photo/$value",
            "register": microsoft_oauth_register,
        }

    if GITHUB_CLIENT_ID.value and GITHUB_CLIENT_SECRET.value:

        def github_oauth_register(client):
            client.register(
                name="github",
                client_id=GITHUB_CLIENT_ID.value,
                client_secret=GITHUB_CLIENT_SECRET.value,
                access_token_url="https://github.com/login/oauth/access_token",
                authorize_url="https://github.com/login/oauth/authorize",
                api_base_url="https://api.github.com",
                userinfo_endpoint="https://api.github.com/user",
                client_kwargs={"scope": GITHUB_CLIENT_SCOPE.value},
                redirect_uri=GITHUB_CLIENT_REDIRECT_URI.value,
            )

        OAUTH_PROVIDERS["github"] = {
            "redirect_uri": GITHUB_CLIENT_REDIRECT_URI.value,
            "register": github_oauth_register,
            "sub_claim": "id",
        }

    if (
        OAUTH_CLIENT_ID.value
        and OAUTH_CLIENT_SECRET.value
        and OPENID_PROVIDER_URL.value
    ):

        def oidc_oauth_register(client):
            client_kwargs = {
                "scope": OAUTH_SCOPES.value,
            }

            if (
                OAUTH_CODE_CHALLENGE_METHOD.value
                and OAUTH_CODE_CHALLENGE_METHOD.value == "S256"
            ):
                client_kwargs["code_challenge_method"] = "S256"
            elif OAUTH_CODE_CHALLENGE_METHOD.value:
                raise Exception(
                    'Code challenge methods other than "%s" not supported. Given: "%s"'
                    % ("S256", OAUTH_CODE_CHALLENGE_METHOD.value)
                )

            client.register(
                name="oidc",
                client_id=OAUTH_CLIENT_ID.value,
                client_secret=OAUTH_CLIENT_SECRET.value,
                server_metadata_url=OPENID_PROVIDER_URL.value,
                client_kwargs=client_kwargs,
                redirect_uri=OPENID_REDIRECT_URI.value,
            )

        OAUTH_PROVIDERS["oidc"] = {
            "name": OAUTH_PROVIDER_NAME.value,
            "redirect_uri": OPENID_REDIRECT_URI.value,
            "register": oidc_oauth_register,
        }


load_oauth_providers()

####################################
# Static DIR
####################################

STATIC_DIR = Path(os.getenv("STATIC_DIR", OPEN_WEBUI_DIR / "static")).resolve()

for file_path in (FRONTEND_BUILD_DIR / "static").glob("**/*"):
    if file_path.is_file():
        target_path = STATIC_DIR / file_path.relative_to(
            (FRONTEND_BUILD_DIR / "static")
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(file_path, target_path)
        except Exception as e:
            logging.error(f"An error occurred: {e}")

frontend_favicon = FRONTEND_BUILD_DIR / "static" / "favicon.png"

if frontend_favicon.exists():
    try:
        shutil.copyfile(frontend_favicon, STATIC_DIR / "favicon.png")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

frontend_splash = FRONTEND_BUILD_DIR / "static" / "splash.png"

if frontend_splash.exists():
    try:
        shutil.copyfile(frontend_splash, STATIC_DIR / "splash.png")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

frontend_loader = FRONTEND_BUILD_DIR / "static" / "loader.js"

if frontend_loader.exists():
    try:
        shutil.copyfile(frontend_loader, STATIC_DIR / "loader.js")
    except Exception as e:
        logging.error(f"An error occurred: {e}")


####################################
# CUSTOM_NAME (Legacy)
####################################

CUSTOM_NAME = os.environ.get("CUSTOM_NAME", "")

if CUSTOM_NAME:
    try:
        r = requests.get(f"https://api.openwebui.com/api/v1/custom/{CUSTOM_NAME}")
        data = r.json()
        if r.ok:
            if "logo" in data:
                WEBUI_FAVICON_URL = url = (
                    f"https://api.openwebui.com{data['logo']}"
                    if data["logo"][0] == "/"
                    else data["logo"]
                )

                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(f"{STATIC_DIR}/favicon.png", "wb") as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)

            if "splash" in data:
                url = (
                    f"https://api.openwebui.com{data['splash']}"
                    if data["splash"][0] == "/"
                    else data["splash"]
                )

                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(f"{STATIC_DIR}/splash.png", "wb") as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)

            WEBUI_NAME = data["name"]
    except Exception as e:
        log.exception(e)
        pass


####################################
# LICENSE_KEY
####################################

LICENSE_KEY = os.environ.get("LICENSE_KEY", "")

####################################
# Cloosphere License Management
####################################

LICENSE_KEYS = PersistentConfig(
    "LICENSE_KEYS",
    "license.keys",
    [],
    sensitive=True,
)

FEATURE_KEYS = PersistentConfig(
    "FEATURE_KEYS",
    "license.feature_keys",
    [],
    sensitive=True,
)

ENABLE_LICENSE_ENFORCEMENT = PersistentConfig(
    "ENABLE_LICENSE_ENFORCEMENT",
    "license.enforcement_enabled",
    os.environ.get("ENABLE_LICENSE_ENFORCEMENT", "True").lower() == "true",
)

####################################
# STORAGE PROVIDER
####################################

# Image upload mode: 'base64' (inline in JSON) or 'storage' (upload to storage provider)
IMAGE_UPLOAD_MODE = PersistentConfig(
    "IMAGE_UPLOAD_MODE",
    "storage.image_upload_mode",
    os.environ.get("IMAGE_UPLOAD_MODE", "base64"),
)

STORAGE_PROVIDER = PersistentConfig(
    "STORAGE_PROVIDER",
    "storage.provider",
    os.environ.get("STORAGE_PROVIDER", "local"),
)

# 파일 스토리지 디폴트 — FILE_STORAGE_PROVIDER 미설정 시 AZURE_STORAGE_MEDIA_*
# (이미지 업로드용으로 이미 설정된 컨테이너) 가 있으면 azure 로 자동 fallback.
# .env 에 동일한 SAS/엔드포인트를 두 번 박지 않도록 하는 편의 디폴트.
_FILE_STORAGE_PROVIDER_DEFAULT = os.environ.get("FILE_STORAGE_PROVIDER") or (
    "azure" if os.environ.get("AZURE_STORAGE_MEDIA_BASE_URL") else "local"
)
FILE_STORAGE_PROVIDER = PersistentConfig(
    "FILE_STORAGE_PROVIDER",
    "storage.file.provider",
    _FILE_STORAGE_PROVIDER_DEFAULT,
)

# File Storage S3 Configuration (독립 자격증명)
FILE_S3_BUCKET_NAME = PersistentConfig(
    "FILE_S3_BUCKET_NAME",
    "storage.file.s3.bucket_name",
    os.environ.get("FILE_S3_BUCKET_NAME", ""),
)
FILE_S3_REGION_NAME = PersistentConfig(
    "FILE_S3_REGION_NAME",
    "storage.file.s3.region_name",
    os.environ.get("FILE_S3_REGION_NAME", "us-east-1"),
)
FILE_S3_ENDPOINT_URL = PersistentConfig(
    "FILE_S3_ENDPOINT_URL",
    "storage.file.s3.endpoint_url",
    os.environ.get("FILE_S3_ENDPOINT_URL", ""),
)
FILE_S3_ACCESS_KEY_ID = PersistentConfig(
    "FILE_S3_ACCESS_KEY_ID",
    "storage.file.s3.access_key_id",
    os.environ.get("FILE_S3_ACCESS_KEY_ID", ""),
)
FILE_S3_SECRET_ACCESS_KEY = PersistentConfig(
    "FILE_S3_SECRET_ACCESS_KEY",
    "storage.file.s3.secret_access_key",
    os.environ.get("FILE_S3_SECRET_ACCESS_KEY", ""),
)
FILE_S3_KEY_PREFIX = PersistentConfig(
    "FILE_S3_KEY_PREFIX",
    "storage.file.s3.key_prefix",
    os.environ.get("FILE_S3_KEY_PREFIX", ""),
    sensitive=False,  # path prefix, not a secret
)

# File Storage GCS Configuration (독립 자격증명)
FILE_GCS_BUCKET_NAME = PersistentConfig(
    "FILE_GCS_BUCKET_NAME",
    "storage.file.gcs.bucket_name",
    os.environ.get("FILE_GCS_BUCKET_NAME", ""),
)
FILE_GCS_CREDENTIALS_JSON = PersistentConfig(
    "FILE_GCS_CREDENTIALS_JSON",
    "storage.file.gcs.credentials_json",
    os.environ.get("FILE_GCS_CREDENTIALS_JSON", ""),
)

# File Storage Azure Configuration (독립 자격증명)
# FILE_AZURE_STORAGE_* 가 미설정이면 AZURE_STORAGE_MEDIA_* (이미지 업로드용
# 기존 설정) 로 fallback — 동일 SAS 를 두 번 박지 않도록 하는 편의 디폴트.
FILE_AZURE_STORAGE_ENDPOINT = PersistentConfig(
    "FILE_AZURE_STORAGE_ENDPOINT",
    "storage.file.azure.endpoint",
    os.environ.get("FILE_AZURE_STORAGE_ENDPOINT")
    or os.environ.get("AZURE_STORAGE_MEDIA_BASE_URL", ""),
)
FILE_AZURE_STORAGE_CONTAINER_NAME = PersistentConfig(
    "FILE_AZURE_STORAGE_CONTAINER_NAME",
    "storage.file.azure.container_name",
    os.environ.get("FILE_AZURE_STORAGE_CONTAINER_NAME")
    or os.environ.get("AZURE_STORAGE_MEDIA_CONTAINER", ""),
)
FILE_AZURE_STORAGE_KEY = PersistentConfig(
    "FILE_AZURE_STORAGE_KEY",
    "storage.file.azure.key",
    os.environ.get("FILE_AZURE_STORAGE_KEY")
    or os.environ.get("AZURE_STORAGE_MEDIA_SAS_KEY", ""),
    sensitive=True,
)

# S3 Configuration
S3_ACCESS_KEY_ID = PersistentConfig(
    "S3_ACCESS_KEY_ID",
    "storage.s3.access_key_id",
    os.environ.get("S3_ACCESS_KEY_ID", ""),
)
S3_SECRET_ACCESS_KEY = PersistentConfig(
    "S3_SECRET_ACCESS_KEY",
    "storage.s3.secret_access_key",
    os.environ.get("S3_SECRET_ACCESS_KEY", ""),
)
S3_REGION_NAME = PersistentConfig(
    "S3_REGION_NAME",
    "storage.s3.region_name",
    os.environ.get("S3_REGION_NAME", "us-east-1"),
)
S3_BUCKET_NAME = PersistentConfig(
    "S3_BUCKET_NAME",
    "storage.s3.bucket_name",
    os.environ.get("S3_BUCKET_NAME", ""),
)
S3_KEY_PREFIX = PersistentConfig(
    "S3_KEY_PREFIX",
    "storage.s3.key_prefix",
    os.environ.get("S3_KEY_PREFIX", ""),
    sensitive=False,  # path prefix, not a secret
)
S3_ENDPOINT_URL = PersistentConfig(
    "S3_ENDPOINT_URL",
    "storage.s3.endpoint_url",
    os.environ.get("S3_ENDPOINT_URL", ""),
)
S3_USE_ACCELERATE_ENDPOINT = (
    os.environ.get("S3_USE_ACCELERATE_ENDPOINT", "False").lower() == "true"
)
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", None)

############################
# Google Cloud Global Config
############################

GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY",
    "google_cloud.service_account_key",
    os.environ.get("GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", ""),
)

GOOGLE_CLOUD_ENABLED = PersistentConfig(
    "GOOGLE_CLOUD_ENABLED",
    "google_cloud.enabled",
    os.environ.get("GOOGLE_CLOUD_ENABLED", "False").lower() == "true",
)

# GCS Configuration
GCS_BUCKET_NAME = PersistentConfig(
    "GCS_BUCKET_NAME",
    "storage.gcs.bucket_name",
    os.environ.get("GCS_BUCKET_NAME", ""),
)
GOOGLE_APPLICATION_CREDENTIALS_JSON = PersistentConfig(
    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
    "storage.gcs.credentials_json",
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", ""),
)

# Azure Blob Storage Configuration
AZURE_STORAGE_ENDPOINT = PersistentConfig(
    "AZURE_STORAGE_ENDPOINT",
    "storage.azure.endpoint",
    os.environ.get("AZURE_STORAGE_ENDPOINT", ""),
)
AZURE_STORAGE_CONTAINER_NAME = PersistentConfig(
    "AZURE_STORAGE_CONTAINER_NAME",
    "storage.azure.container_name",
    os.environ.get("AZURE_STORAGE_CONTAINER_NAME", ""),
)
AZURE_STORAGE_KEY = PersistentConfig(
    "AZURE_STORAGE_KEY",
    "storage.azure.key",
    os.environ.get("AZURE_STORAGE_KEY", ""),
    sensitive=True,
)

####################################
# File Upload DIR
####################################

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


####################################
# Cache DIR
####################################

CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


####################################
# OPENTELEMETRY (Monitoring)
####################################

ENABLE_OTEL = PersistentConfig(
    "ENABLE_OTEL",
    "monitoring.otel.enable",
    os.environ.get("ENABLE_OTEL", "False").lower() == "true",
)

OTEL_EXPORTER_OTLP_ENDPOINT = PersistentConfig(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "monitoring.otel.endpoint",
    os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
)

####################################
# DIRECT CONNECTIONS
####################################

ENABLE_DIRECT_CONNECTIONS = PersistentConfig(
    "ENABLE_DIRECT_CONNECTIONS",
    "direct.enable",
    os.environ.get("ENABLE_DIRECT_CONNECTIONS", "True").lower() == "true",
)

####################################
# HITL (Human-in-the-Loop)
####################################

ENABLE_HITL = PersistentConfig(
    "ENABLE_HITL",
    "agent.hitl.enable",
    os.environ.get("ENABLE_HITL", "False").lower() == "true",
)

####################################
# OLLAMA_BASE_URL
####################################

ENABLE_OLLAMA_API = PersistentConfig(
    "ENABLE_OLLAMA_API",
    "ollama.enable",
    os.environ.get("ENABLE_OLLAMA_API", "True").lower() == "true",
)

OLLAMA_API_BASE_URL = os.environ.get(
    "OLLAMA_API_BASE_URL", "http://localhost:11434/api"
)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")
if OLLAMA_BASE_URL:
    # Remove trailing slash
    OLLAMA_BASE_URL = (
        OLLAMA_BASE_URL[:-1] if OLLAMA_BASE_URL.endswith("/") else OLLAMA_BASE_URL
    )


K8S_FLAG = os.environ.get("K8S_FLAG", "")
USE_OLLAMA_DOCKER = os.environ.get("USE_OLLAMA_DOCKER", "false")

if OLLAMA_BASE_URL == "" and OLLAMA_API_BASE_URL != "":
    OLLAMA_BASE_URL = (
        OLLAMA_API_BASE_URL[:-4]
        if OLLAMA_API_BASE_URL.endswith("/api")
        else OLLAMA_API_BASE_URL
    )

if ENV == "prod":
    if OLLAMA_BASE_URL == "/ollama" and not K8S_FLAG:
        if USE_OLLAMA_DOCKER.lower() == "true":
            # if you use all-in-one docker container (Open WebUI + Ollama)
            # with the docker build arg USE_OLLAMA=true (--build-arg="USE_OLLAMA=true") this only works with http://localhost:11434
            OLLAMA_BASE_URL = "http://localhost:11434"
        else:
            OLLAMA_BASE_URL = "http://host.docker.internal:11434"
    elif K8S_FLAG:
        OLLAMA_BASE_URL = "http://ollama-service.open-webui.svc.cluster.local:11434"


OLLAMA_BASE_URLS = os.environ.get("OLLAMA_BASE_URLS", "")
OLLAMA_BASE_URLS = OLLAMA_BASE_URLS if OLLAMA_BASE_URLS != "" else OLLAMA_BASE_URL

OLLAMA_BASE_URLS = [url.strip() for url in OLLAMA_BASE_URLS.split(";")]
OLLAMA_BASE_URLS = PersistentConfig(
    "OLLAMA_BASE_URLS", "ollama.base_urls", OLLAMA_BASE_URLS
)

OLLAMA_API_CONFIGS = PersistentConfig(
    "OLLAMA_API_CONFIGS",
    "ollama.api_configs",
    {},
)

####################################
# OPENAI_API
####################################


ENABLE_OPENAI_API = PersistentConfig(
    "ENABLE_OPENAI_API",
    "openai.enable",
    os.environ.get("ENABLE_OPENAI_API", "True").lower() == "true",
)


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_BASE_URL = os.environ.get("OPENAI_API_BASE_URL", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_BASE_URL = os.environ.get("GEMINI_API_BASE_URL", "")


if OPENAI_API_BASE_URL == "":
    OPENAI_API_BASE_URL = "https://api.openai.com/v1"

OPENAI_API_KEYS = os.environ.get("OPENAI_API_KEYS", "")
OPENAI_API_KEYS = OPENAI_API_KEYS if OPENAI_API_KEYS != "" else OPENAI_API_KEY

OPENAI_API_KEYS = [url.strip() for url in OPENAI_API_KEYS.split(";")]
OPENAI_API_KEYS = PersistentConfig(
    "OPENAI_API_KEYS", "openai.api_keys", OPENAI_API_KEYS
)

OPENAI_API_BASE_URLS = os.environ.get("OPENAI_API_BASE_URLS", "")
OPENAI_API_BASE_URLS = (
    OPENAI_API_BASE_URLS if OPENAI_API_BASE_URLS != "" else OPENAI_API_BASE_URL
)

OPENAI_API_BASE_URLS = [
    url.strip() if url != "" else "https://api.openai.com/v1"
    for url in OPENAI_API_BASE_URLS.split(";")
]
OPENAI_API_BASE_URLS = PersistentConfig(
    "OPENAI_API_BASE_URLS", "openai.api_base_urls", OPENAI_API_BASE_URLS
)

OPENAI_API_CONFIGS = PersistentConfig(
    "OPENAI_API_CONFIGS",
    "openai.api_configs",
    {},
)

# Get the actual OpenAI API key based on the base URL
OPENAI_API_KEY = ""
try:
    OPENAI_API_KEY = OPENAI_API_KEYS.value[
        OPENAI_API_BASE_URLS.value.index("https://api.openai.com/v1")
    ]
except Exception:
    pass
OPENAI_API_BASE_URL = "https://api.openai.com/v1"

####################################
# TOOL_SERVERS
####################################


TOOL_SERVER_CONNECTIONS = PersistentConfig(
    "TOOL_SERVER_CONNECTIONS",
    "tool_server.connections",
    [],
)

####################################
# WEBUI
####################################


WEBUI_URL = PersistentConfig(
    "WEBUI_URL", "webui.url", os.environ.get("WEBUI_URL", "http://localhost:3000")
)
# ENV이 설정되어 있으면 DB 값보다 우선 적용 (로컬/배포 환경 전환 시 DB 잔여값 문제 방지)
if os.environ.get("WEBUI_URL"):
    WEBUI_URL.value = os.environ.get("WEBUI_URL")


ENABLE_SIGNUP = PersistentConfig(
    "ENABLE_SIGNUP",
    "ui.enable_signup",
    (
        False
        if not WEBUI_AUTH
        else os.environ.get("ENABLE_SIGNUP", "True").lower() == "true"
    ),
)

ENABLE_ONBOARDING = PersistentConfig(
    "ENABLE_ONBOARDING",
    "ui.enable_onboarding",
    os.environ.get("ENABLE_ONBOARDING", "True").lower() == "true",
)

ENABLE_LOGIN_FORM = PersistentConfig(
    "ENABLE_LOGIN_FORM",
    "ui.ENABLE_LOGIN_FORM",
    os.environ.get("ENABLE_LOGIN_FORM", "True").lower() == "true",
)


DEFAULT_LOCALE = PersistentConfig(
    "DEFAULT_LOCALE",
    "ui.default_locale",
    os.environ.get("DEFAULT_LOCALE", ""),
)

DEFAULT_MODELS = PersistentConfig(
    "DEFAULT_MODELS", "ui.default_models", os.environ.get("DEFAULT_MODELS", None)
)

DEFAULT_PROMPT_SUGGESTIONS = PersistentConfig(
    "DEFAULT_PROMPT_SUGGESTIONS",
    "ui.prompt_suggestions",
    [
        {
            "title": ["Help me study", "vocabulary for a college entrance exam"],
            "content": "Help me study vocabulary: write a sentence for me to fill in the blank, and I'll try to pick the correct option.",
        },
        {
            "title": ["Give me ideas", "for what to do with my kids' art"],
            "content": "What are 5 creative things I could do with my kids' art? I don't want to throw them away, but it's also so much clutter.",
        },
        {
            "title": ["Tell me a fun fact", "about the Roman Empire"],
            "content": "Tell me a random fun fact about the Roman Empire",
        },
        {
            "title": ["Show me a code snippet", "of a website's sticky header"],
            "content": "Show me a code snippet of a website's sticky header in CSS and JavaScript.",
        },
        {
            "title": [
                "Explain options trading",
                "if I'm familiar with buying and selling stocks",
            ],
            "content": "Explain options trading in simple terms if I'm familiar with buying and selling stocks.",
        },
        {
            "title": ["Overcome procrastination", "give me tips"],
            "content": "Could you start by asking me about instances when I procrastinate the most and then give me some suggestions to overcome it?",
        },
    ],
)

MODEL_ORDER_LIST = PersistentConfig(
    "MODEL_ORDER_LIST",
    "ui.model_order_list",
    [],
)

DEFAULT_USER_ROLE = PersistentConfig(
    "DEFAULT_USER_ROLE",
    "ui.default_user_role",
    os.getenv("DEFAULT_USER_ROLE", "pending"),
)

USER_PERMISSIONS_WORKSPACE_AGENTS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_AGENTS_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS", "False").lower() == "true"
)

USER_PERMISSIONS_WORKSPACE_DATABASES_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_DATABASES_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_GRAPHS_ACCESS = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_GRAPHS_ACCESS", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_GUARDRAILS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_GUARDRAILS_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_AGENT_FLOWS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_AGENT_FLOWS_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_SCHEDULES_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_SCHEDULES_ACCESS", "True").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_TAGS_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_TAGS_ACCESS", "True").lower() == "true"
)

# 외부 서비스 연결을 다루므로 기본 잠금(none) — 관리자가 그룹별로 부여.
USER_PERMISSIONS_WORKSPACE_MARKETPLACE_ACCESS = (
    os.environ.get("USER_PERMISSIONS_WORKSPACE_MARKETPLACE_ACCESS", "False").lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_AGENTS_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_AGENTS_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_DATABASES_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_DATABASES_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)

USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ALLOW_PUBLIC_SHARING = (
    os.environ.get(
        "USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ALLOW_PUBLIC_SHARING", "False"
    ).lower()
    == "true"
)


USER_PERMISSIONS_CHAT_CONTROLS = (
    os.environ.get("USER_PERMISSIONS_CHAT_CONTROLS", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_FILE_UPLOAD = (
    os.environ.get("USER_PERMISSIONS_CHAT_FILE_UPLOAD", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_DELETE = (
    os.environ.get("USER_PERMISSIONS_CHAT_DELETE", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_EDIT = (
    os.environ.get("USER_PERMISSIONS_CHAT_EDIT", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_STT = (
    os.environ.get("USER_PERMISSIONS_CHAT_STT", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_TTS = (
    os.environ.get("USER_PERMISSIONS_CHAT_TTS", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_CALL = (
    os.environ.get("USER_PERMISSIONS_CHAT_CALL", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_MULTIPLE_MODELS = (
    os.environ.get("USER_PERMISSIONS_CHAT_MULTIPLE_MODELS", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_TEMPORARY = (
    os.environ.get("USER_PERMISSIONS_CHAT_TEMPORARY", "True").lower() == "true"
)

USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED = (
    os.environ.get("USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED", "False").lower()
    == "true"
)


USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS = (
    os.environ.get("USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS", "False").lower()
    == "true"
)

USER_PERMISSIONS_FEATURES_WEB_SEARCH = (
    os.environ.get("USER_PERMISSIONS_FEATURES_WEB_SEARCH", "True").lower() == "true"
)

USER_PERMISSIONS_FEATURES_IMAGE_GENERATION = (
    os.environ.get("USER_PERMISSIONS_FEATURES_IMAGE_GENERATION", "True").lower()
    == "true"
)

# Google Workspace 채팅 통합 — boolean 권한 (4단계 enum 아님).  admin Permissions UI 에서
# 그룹 단위로 켜고 끄며, 4단계 게이트의 2단계 (group permission) 역할.
USER_PERMISSIONS_FEATURES_GMAIL = (
    os.environ.get("USER_PERMISSIONS_FEATURES_GMAIL", "True").lower() == "true"
)

USER_PERMISSIONS_FEATURES_CALENDAR = (
    os.environ.get("USER_PERMISSIONS_FEATURES_CALENDAR", "True").lower() == "true"
)

USER_PERMISSIONS_FEATURES_DRIVE = (
    os.environ.get("USER_PERMISSIONS_FEATURES_DRIVE", "True").lower() == "true"
)

USER_PERMISSIONS_FEATURES_CODE_GATEWAY = (
    os.environ.get("USER_PERMISSIONS_FEATURES_CODE_GATEWAY", "False").lower() == "true"
)


DEFAULT_USER_PERMISSIONS = {
    "admin": {
        "users": "none",
        "evaluations": "none",
        "settings": "none",
        "monitoring": "none",
    },
    "workspace": {
        "agents": "write" if USER_PERMISSIONS_WORKSPACE_AGENTS_ACCESS else "none",
        "knowledge": "write" if USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS else "none",
        "prompts": "write" if USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS else "none",
        "tools": "write" if USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS else "none",
        "databases": "write" if USER_PERMISSIONS_WORKSPACE_DATABASES_ACCESS else "none",
        "glossaries": "write"
        if USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ACCESS
        else "none",
        "knowledge_graphs": "write"
        if USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_GRAPHS_ACCESS
        else "none",
        "guardrails": "write"
        if USER_PERMISSIONS_WORKSPACE_GUARDRAILS_ACCESS
        else "none",
        "agent_flows": "write"
        if USER_PERMISSIONS_WORKSPACE_AGENT_FLOWS_ACCESS
        else "none",
        "schedules": "read" if USER_PERMISSIONS_WORKSPACE_SCHEDULES_ACCESS else "none",
        "tags": "write" if USER_PERMISSIONS_WORKSPACE_TAGS_ACCESS else "none",
        "marketplace": "write"
        if USER_PERMISSIONS_WORKSPACE_MARKETPLACE_ACCESS
        else "none",
    },
    "sharing": {
        "public_agents": USER_PERMISSIONS_WORKSPACE_AGENTS_ALLOW_PUBLIC_SHARING,
        "public_knowledge": USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING,
        "public_prompts": USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING,
        "public_tools": USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING,
        "public_databases": USER_PERMISSIONS_WORKSPACE_DATABASES_ALLOW_PUBLIC_SHARING,
        "public_glossaries": USER_PERMISSIONS_WORKSPACE_GLOSSARIES_ALLOW_PUBLIC_SHARING,
    },
    "chat": {
        "controls": USER_PERMISSIONS_CHAT_CONTROLS,
        "file_upload": USER_PERMISSIONS_CHAT_FILE_UPLOAD,
        "delete": USER_PERMISSIONS_CHAT_DELETE,
        "edit": USER_PERMISSIONS_CHAT_EDIT,
        "stt": USER_PERMISSIONS_CHAT_STT,
        "tts": USER_PERMISSIONS_CHAT_TTS,
        "call": USER_PERMISSIONS_CHAT_CALL,
        "multiple_models": USER_PERMISSIONS_CHAT_MULTIPLE_MODELS,
        "temporary": USER_PERMISSIONS_CHAT_TEMPORARY,
        "temporary_enforced": USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED,
    },
    "features": {
        "direct_tool_servers": USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS,
        "web_search": USER_PERMISSIONS_FEATURES_WEB_SEARCH,
        "image_generation": USER_PERMISSIONS_FEATURES_IMAGE_GENERATION,
        "gmail": USER_PERMISSIONS_FEATURES_GMAIL,
        "calendar": USER_PERMISSIONS_FEATURES_CALENDAR,
        "drive": USER_PERMISSIONS_FEATURES_DRIVE,
        "scheduled_tasks": True,
        "code_gateway": USER_PERMISSIONS_FEATURES_CODE_GATEWAY,
    },
}

USER_PERMISSIONS = PersistentConfig(
    "USER_PERMISSIONS",
    "user.permissions",
    DEFAULT_USER_PERMISSIONS,
)

ENABLE_CHANNELS = PersistentConfig(
    "ENABLE_CHANNELS",
    "channels.enable",
    os.environ.get("ENABLE_CHANNELS", "False").lower() == "true",
)

####################################
# Code Gateway
####################################

ENABLE_CODE_GATEWAY = PersistentConfig(
    "ENABLE_CODE_GATEWAY",
    "code_gateway.enable",
    os.environ.get("ENABLE_CODE_GATEWAY", "False").lower() == "true",
)

CODE_GATEWAY_PROVIDERS = PersistentConfig(
    "CODE_GATEWAY_PROVIDERS",
    "code_gateway.providers",
    {},
)

CODE_GATEWAY_GUARDRAIL_IDS = PersistentConfig(
    "CODE_GATEWAY_GUARDRAIL_IDS",
    "code_gateway.guardrail_ids",
    [],
)

CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL = PersistentConfig(
    "CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL",
    "code_gateway.follow_global_guardrail",
    True,
)

CODE_GATEWAY_RATE_LIMIT = PersistentConfig(
    "CODE_GATEWAY_RATE_LIMIT",
    "code_gateway.rate_limit",
    0,
)

CODE_GATEWAY_ALLOWED_MODELS = PersistentConfig(
    "CODE_GATEWAY_ALLOWED_MODELS",
    "code_gateway.allowed_models",
    [],
)

CODE_GATEWAY_BLOCKED_FILE_PATTERNS = PersistentConfig(
    "CODE_GATEWAY_BLOCKED_FILE_PATTERNS",
    "code_gateway.blocked_file_patterns",
    [],
)

CODE_GATEWAY_BLOCKED_FILE_ACTION = PersistentConfig(
    "CODE_GATEWAY_BLOCKED_FILE_ACTION",
    "code_gateway.blocked_file_action",
    "block",  # "block" or "warn"
)

CODE_GATEWAY_BLOCKED_REPOS = PersistentConfig(
    "CODE_GATEWAY_BLOCKED_REPOS",
    "code_gateway.blocked_repos",
    [],
)

CODE_GATEWAY_REQUIRE_REPO_METADATA = PersistentConfig(
    "CODE_GATEWAY_REQUIRE_REPO_METADATA",
    "code_gateway.require_repo_metadata",
    False,
)

CODE_GATEWAY_MISSING_METADATA_ACTION = PersistentConfig(
    "CODE_GATEWAY_MISSING_METADATA_ACTION",
    "code_gateway.missing_metadata_action",
    "allow",  # "allow", "warn", "block"
)


ENABLE_EVALUATION_ARENA_MODELS = PersistentConfig(
    "ENABLE_EVALUATION_ARENA_MODELS",
    "evaluation.arena.enable",
    os.environ.get("ENABLE_EVALUATION_ARENA_MODELS", "True").lower() == "true",
)
EVALUATION_ARENA_MODELS = PersistentConfig(
    "EVALUATION_ARENA_MODELS",
    "evaluation.arena.models",
    [],
)

DEFAULT_ARENA_MODEL = {
    "id": "arena-model",
    "name": "Arena Model",
    "meta": {
        "profile_image_url": "/favicon.png",
        "description": "Submit your questions to anonymous AI chatbots and vote on the best response.",
        "model_ids": None,
    },
}

WEBHOOK_URL = PersistentConfig(
    "WEBHOOK_URL", "webhook_url", os.environ.get("WEBHOOK_URL", "")
)

ENABLE_ADMIN_EXPORT = os.environ.get("ENABLE_ADMIN_EXPORT", "True").lower() == "true"

ENABLE_ADMIN_CHAT_ACCESS = (
    os.environ.get("ENABLE_ADMIN_CHAT_ACCESS", "True").lower() == "true"
)

ENABLE_COMMUNITY_SHARING = PersistentConfig(
    "ENABLE_COMMUNITY_SHARING",
    "ui.enable_community_sharing",
    os.environ.get("ENABLE_COMMUNITY_SHARING", "False").lower() == "true",
)

ENABLE_MESSAGE_RATING = PersistentConfig(
    "ENABLE_MESSAGE_RATING",
    "ui.enable_message_rating",
    os.environ.get("ENABLE_MESSAGE_RATING", "True").lower() == "true",
)

ENABLE_USER_WEBHOOKS = PersistentConfig(
    "ENABLE_USER_WEBHOOKS",
    "ui.enable_user_webhooks",
    os.environ.get("ENABLE_USER_WEBHOOKS", "True").lower() == "true",
)

####################################
# Message Tracing Configuration
####################################

ENABLE_MESSAGE_TRACING = PersistentConfig(
    "ENABLE_MESSAGE_TRACING",
    "tracing.enabled",
    os.environ.get("ENABLE_MESSAGE_TRACING", "True").lower() == "true",
)

TRACE_RETENTION_DAYS = PersistentConfig(
    "TRACE_RETENTION_DAYS",
    "tracing.retention_days",
    int(os.environ.get("TRACE_RETENTION_DAYS", "30")),
)

TRACE_INPUTS_MAX_SIZE = PersistentConfig(
    "TRACE_INPUTS_MAX_SIZE",
    "tracing.inputs_max_size",
    int(os.environ.get("TRACE_INPUTS_MAX_SIZE", "10000")),
)

####################################
# Data Retention Configuration
####################################

ENABLE_DATA_RETENTION = PersistentConfig(
    "ENABLE_DATA_RETENTION",
    "data_retention.enabled",
    os.environ.get("ENABLE_DATA_RETENTION", "False").lower() == "true",
)

DATA_RETENTION_CLEANUP_HOUR = PersistentConfig(
    "DATA_RETENTION_CLEANUP_HOUR",
    "data_retention.cleanup_hour",
    int(os.environ.get("DATA_RETENTION_CLEANUP_HOUR", "3")),
)

# 각 로그 테이블별 보존 기간 (일). 0 = 영구 보존 (삭제 안 함)
RETENTION_DAYS_USAGE = PersistentConfig(
    "RETENTION_DAYS_USAGE",
    "data_retention.usage_days",
    int(os.environ.get("RETENTION_DAYS_USAGE", "0")),
)

RETENTION_DAYS_AUDIT_LOG = PersistentConfig(
    "RETENTION_DAYS_AUDIT_LOG",
    "data_retention.audit_log_days",
    int(os.environ.get("RETENTION_DAYS_AUDIT_LOG", "0")),
)

RETENTION_DAYS_GUARDRAIL_LOG = PersistentConfig(
    "RETENTION_DAYS_GUARDRAIL_LOG",
    "data_retention.guardrail_log_days",
    int(os.environ.get("RETENTION_DAYS_GUARDRAIL_LOG", "0")),
)

RETENTION_DAYS_TRACE = PersistentConfig(
    "RETENTION_DAYS_TRACE",
    "data_retention.trace_days",
    int(os.environ.get("RETENTION_DAYS_TRACE", "0")),
)

RETENTION_DAYS_TRACE_ANALYSIS = PersistentConfig(
    "RETENTION_DAYS_TRACE_ANALYSIS",
    "data_retention.trace_analysis_days",
    int(os.environ.get("RETENTION_DAYS_TRACE_ANALYSIS", "0")),
)

RETENTION_DAYS_AUTO_EVALUATION = PersistentConfig(
    "RETENTION_DAYS_AUTO_EVALUATION",
    "data_retention.auto_evaluation_days",
    int(os.environ.get("RETENTION_DAYS_AUTO_EVALUATION", "0")),
)

# Worker queue (Redis Streams) 좀비/stuck 자동 정리.
# 활성화 시 백그라운드 task가 주기적으로 cleanup_zombie_consumers + reclaim_stuck_messages 호출.
# 0 = 비활성 (기존과 동일하게 수동 정리만)
ENABLE_WORKER_AUTO_CLEANUP = PersistentConfig(
    "ENABLE_WORKER_AUTO_CLEANUP",
    "data_retention.worker_auto_cleanup_enabled",
    os.environ.get("ENABLE_WORKER_AUTO_CLEANUP", "True").lower() == "true",
)

# 좀비 컨슈머 idle 임계값 (시간). pending == 0 인 컨슈머만 대상.
WORKER_ZOMBIE_IDLE_HOURS = PersistentConfig(
    "WORKER_ZOMBIE_IDLE_HOURS",
    "data_retention.worker_zombie_idle_hours",
    int(os.environ.get("WORKER_ZOMBIE_IDLE_HOURS", "24")),
)

# Stuck pending 메시지 idle 임계값 (시간). 작업 최대 실행 시간보다 충분히 길게 잡아야
# 진행 중 작업이 강제 종료되지 않음.
WORKER_STUCK_IDLE_HOURS = PersistentConfig(
    "WORKER_STUCK_IDLE_HOURS",
    "data_retention.worker_stuck_idle_hours",
    int(os.environ.get("WORKER_STUCK_IDLE_HOURS", "6")),
)

# 자동 정리 실행 주기 (분).
WORKER_CLEANUP_INTERVAL_MINUTES = PersistentConfig(
    "WORKER_CLEANUP_INTERVAL_MINUTES",
    "data_retention.worker_cleanup_interval_minutes",
    int(os.environ.get("WORKER_CLEANUP_INTERVAL_MINUTES", "60")),
)

####################################
# Usage Limit Configuration
####################################

ENABLE_USAGE_LIMIT = PersistentConfig(
    "ENABLE_USAGE_LIMIT",
    "usage_limit.enabled",
    os.environ.get("ENABLE_USAGE_LIMIT", "False").lower() == "true",
)

USAGE_LIMIT_DEFAULT_DAILY_TOKENS = PersistentConfig(
    "USAGE_LIMIT_DEFAULT_DAILY_TOKENS",
    "usage_limit.default_daily_tokens",
    int(os.environ.get("USAGE_LIMIT_DEFAULT_DAILY_TOKENS", "0")),
)

USAGE_LIMIT_EXCEED_ACTION = PersistentConfig(
    "USAGE_LIMIT_EXCEED_ACTION",
    "usage_limit.exceed_action",
    os.environ.get("USAGE_LIMIT_EXCEED_ACTION", "warn"),
)


def _parse_per_model_env(raw: str) -> dict[str, int]:
    """USAGE_LIMIT_PER_MODEL env: JSON dict 또는 빈 문자열."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): int(v) for k, v in parsed.items() if v is not None}
    except (json.JSONDecodeError, ValueError, TypeError):
        log.warning("Invalid USAGE_LIMIT_PER_MODEL env value, ignoring")
    return {}


USAGE_LIMIT_PER_MODEL = PersistentConfig(
    "USAGE_LIMIT_PER_MODEL",
    "usage_limit.per_model",
    _parse_per_model_env(os.environ.get("USAGE_LIMIT_PER_MODEL", "")),
)


def validate_cors_origins(origins):
    for origin in origins:
        if origin != "*":
            validate_cors_origin(origin)


def validate_cors_origin(origin):
    parsed_url = urlparse(origin)

    # Check if the scheme is either http or https
    if parsed_url.scheme not in ["http", "https"]:
        raise ValueError(
            f"Invalid scheme in CORS_ALLOW_ORIGIN: '{origin}'. Only 'http' and 'https' are allowed."
        )

    # Ensure that the netloc (domain + port) is present, indicating it's a valid URL
    if not parsed_url.netloc:
        raise ValueError(f"Invalid URL structure in CORS_ALLOW_ORIGIN: '{origin}'.")


# For production, you should only need one host as
# fastapi serves the svelte-kit built frontend and backend from the same host and port.
# To test CORS_ALLOW_ORIGIN locally, you can set something like
# CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080
# in your .env file depending on your frontend port, 5173 in this case.
CORS_ALLOW_ORIGIN = os.environ.get("CORS_ALLOW_ORIGIN", "*").split(";")

if "*" in CORS_ALLOW_ORIGIN:
    log.warning(
        "\n\nWARNING: CORS_ALLOW_ORIGIN IS SET TO '*' - NOT RECOMMENDED FOR PRODUCTION DEPLOYMENTS.\n"
    )

validate_cors_origins(CORS_ALLOW_ORIGIN)


class BannerModel(BaseModel):
    id: str
    type: str
    title: Optional[str] = None
    content: str
    dismissible: bool
    timestamp: int


try:
    banners = json.loads(os.environ.get("WEBUI_BANNERS", "[]"))
    banners = [BannerModel(**banner) for banner in banners]
except Exception as e:
    log.exception(f"Error loading WEBUI_BANNERS: {e}")
    banners = []

WEBUI_BANNERS = PersistentConfig("WEBUI_BANNERS", "ui.banners", banners)


SHOW_ADMIN_DETAILS = PersistentConfig(
    "SHOW_ADMIN_DETAILS",
    "auth.admin.show",
    os.environ.get("SHOW_ADMIN_DETAILS", "true").lower() == "true",
)

ADMIN_EMAIL = PersistentConfig(
    "ADMIN_EMAIL",
    "auth.admin.email",
    os.environ.get("ADMIN_EMAIL", None),
)


####################################
# TASKS
####################################


TASK_MODEL = PersistentConfig(
    "TASK_MODEL",
    "task.model.default",
    os.environ.get("TASK_MODEL", ""),
)

TASK_MODEL_EXTERNAL = PersistentConfig(
    "TASK_MODEL_EXTERNAL",
    "task.model.external",
    os.environ.get("TASK_MODEL_EXTERNAL", ""),
)

# Memory extraction model — cheaper model for fact extraction + consolidation
# Fallback chain: MEMORY_EXTRACTION_MODEL → TASK_MODEL → chat model
MEMORY_EXTRACTION_MODEL = PersistentConfig(
    "MEMORY_EXTRACTION_MODEL",
    "memory.extraction.model",
    os.environ.get("MEMORY_EXTRACTION_MODEL", ""),
)

MEMORY_EXTRACTION_CONFIDENCE = PersistentConfig(
    "MEMORY_EXTRACTION_CONFIDENCE",
    "memory.extraction.confidence",
    float(os.environ.get("MEMORY_EXTRACTION_CONFIDENCE", "0.8")),
)

TITLE_GENERATION_PROMPT_TEMPLATE = PersistentConfig(
    "TITLE_GENERATION_PROMPT_TEMPLATE",
    "task.title.prompt_template",
    os.environ.get("TITLE_GENERATION_PROMPT_TEMPLATE", ""),
)

DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate a concise, 3-5 word title with an emoji summarizing the chat history.
### Guidelines:
- The title should clearly represent the main theme or subject of the conversation.
- Use emojis that enhance understanding of the topic, but avoid quotation marks or special formatting.
- Write the title in the chat's primary language; default to English if multilingual.
- Prioritize accuracy over excessive creativity; keep it clear and simple.
### Output:
JSON format: { "title": "your concise title here" }
### Examples:
- { "title": "📉 Stock Market Trends" },
- { "title": "🍪 Perfect Chocolate Chip Recipe" },
- { "title": "Evolution of Music Streaming" },
- { "title": "Remote Work Productivity Tips" },
- { "title": "Artificial Intelligence in Healthcare" },
- { "title": "🎮 Video Game Development Insights" }
### Chat History:
<chat_history>
{{MESSAGES:END:2}}
</chat_history>"""

TAGS_GENERATION_PROMPT_TEMPLATE = PersistentConfig(
    "TAGS_GENERATION_PROMPT_TEMPLATE",
    "task.tags.prompt_template",
    os.environ.get("TAGS_GENERATION_PROMPT_TEMPLATE", ""),
)

DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate 1-3 broad tags categorizing the main themes of the chat history, along with 1-3 more specific subtopic tags.

### Guidelines:
- Start with high-level domains (e.g. Science, Technology, Philosophy, Arts, Politics, Business, Health, Sports, Entertainment, Education)
- Consider including relevant subfields/subdomains if they are strongly represented throughout the conversation
- If content is too short (less than 3 messages) or too diverse, use only ["General"]
- Use the chat's primary language; default to English if multilingual
- Prioritize accuracy over specificity

### Output:
JSON format: { "tags": ["tag1", "tag2", "tag3"] }

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = PersistentConfig(
    "FOLLOW_UP_GENERATION_PROMPT_TEMPLATE",
    "task.follow_up.prompt_template",
    os.environ.get("FOLLOW_UP_GENERATION_PROMPT_TEMPLATE", ""),
)

DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = """### Task:
Suggest 3-5 relevant follow-up questions or prompts that the user might naturally ask next in this conversation as a **user**, based on the chat history, to help continue or deepen the discussion.
### Guidelines:
- Write all follow-up questions from the user's point of view, directed to the assistant.
- Make questions concise, clear, and directly related to the discussed topic(s).
- Only suggest follow-ups that make sense given the chat history and the assistant's last response.
- Match the conversational tone and style of the existing chat.
- Use the chat's primary language; default to English if multilingual.
- Avoid repeating questions already asked or answered in the chat history.
- If the conversation is concluded or no relevant follow-ups exist, return an empty list.
### Output:
JSON format: { "follow_ups": ["Question 1?", "Question 2?", "Question 3?"] }
### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

ENABLE_TAGS_GENERATION = PersistentConfig(
    "ENABLE_TAGS_GENERATION",
    "task.tags.enable",
    os.environ.get("ENABLE_TAGS_GENERATION", "True").lower() == "true",
)

ENABLE_TITLE_GENERATION = PersistentConfig(
    "ENABLE_TITLE_GENERATION",
    "task.title.enable",
    os.environ.get("ENABLE_TITLE_GENERATION", "True").lower() == "true",
)

ENABLE_FOLLOW_UP_GENERATION = PersistentConfig(
    "ENABLE_FOLLOW_UP_GENERATION",
    "task.follow_up.enable",
    os.environ.get("ENABLE_FOLLOW_UP_GENERATION", "False").lower() == "true",
)


ENABLE_AUTOCOMPLETE_GENERATION = PersistentConfig(
    "ENABLE_AUTOCOMPLETE_GENERATION",
    "task.autocomplete.enable",
    os.environ.get("ENABLE_AUTOCOMPLETE_GENERATION", "False").lower() == "true",
)

AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH = PersistentConfig(
    "AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH",
    "task.autocomplete.input_max_length",
    int(os.environ.get("AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH", "-1")),
)

AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = PersistentConfig(
    "AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE",
    "task.autocomplete.prompt_template",
    os.environ.get("AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE", ""),
)


DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = """### Task:
You are an autocompletion system. Continue the text in `<text>` based on the **completion type** in `<type>` and the given language.  

### **Instructions**:
1. Analyze `<text>` for context and meaning.  
2. Use `<type>` to guide your output:  
   - **General**: Provide a natural, concise continuation.  
   - **Search Query**: Complete as if generating a realistic search query.  
3. Start as if you are directly continuing `<text>`. Do **not** repeat, paraphrase, or respond as a model. Simply complete the text.  
4. Ensure the continuation:
   - Flows naturally from `<text>`.  
   - Avoids repetition, overexplaining, or unrelated ideas.  
5. If unsure, return: `{ "text": "" }`.  

### **Output Rules**:
- Respond only in JSON format: `{ "text": "<your_completion>" }`.

### **Examples**:
#### Example 1:  
Input:  
<type>General</type>  
<text>The sun was setting over the horizon, painting the sky</text>  
Output:  
{ "text": "with vibrant shades of orange and pink." }

#### Example 2:  
Input:  
<type>Search Query</type>  
<text>Top-rated restaurants in</text>  
Output:  
{ "text": "New York City for Italian cuisine." }  

---
### Context:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>
<type>{{TYPE}}</type>  
<text>{{PROMPT}}</text>  
#### Output:
"""

DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE = """Your task is to reflect the speaker's likely facial expression through a fitting emoji. Interpret emotions from the message and reflect their facial expression using fitting, diverse emojis (e.g., 😊, 😢, 😡, 😱).

Message: ```{{prompt}}```"""

DEFAULT_MOA_GENERATION_PROMPT_TEMPLATE = """You have been provided with a set of responses from various models to the latest user query: "{{prompt}}"

Your task is to synthesize these responses into a single, high-quality response. It is crucial to critically evaluate the information provided in these responses, recognizing that some of it may be biased or incorrect. Your response should not simply replicate the given answers but should offer a refined, accurate, and comprehensive reply to the instruction. Ensure your response is well-structured, coherent, and adheres to the highest standards of accuracy and reliability.

Responses from models: {{responses}}"""


####################################
# Code Interpreter
####################################

ENABLE_CODE_EXECUTION = PersistentConfig(
    "ENABLE_CODE_EXECUTION",
    "code_execution.enable",
    os.environ.get("ENABLE_CODE_EXECUTION", "True").lower() == "true",
)

CODE_EXECUTION_ENGINE = PersistentConfig(
    "CODE_EXECUTION_ENGINE",
    "code_execution.engine",
    os.environ.get("CODE_EXECUTION_ENGINE", "pyodide"),
)

CODE_EXECUTION_JUPYTER_URL = PersistentConfig(
    "CODE_EXECUTION_JUPYTER_URL",
    "code_execution.jupyter.url",
    os.environ.get("CODE_EXECUTION_JUPYTER_URL", ""),
)

CODE_EXECUTION_JUPYTER_AUTH = PersistentConfig(
    "CODE_EXECUTION_JUPYTER_AUTH",
    "code_execution.jupyter.auth",
    os.environ.get("CODE_EXECUTION_JUPYTER_AUTH", ""),
)

CODE_EXECUTION_JUPYTER_AUTH_TOKEN = PersistentConfig(
    "CODE_EXECUTION_JUPYTER_AUTH_TOKEN",
    "code_execution.jupyter.auth_token",
    os.environ.get("CODE_EXECUTION_JUPYTER_AUTH_TOKEN", ""),
)


CODE_EXECUTION_JUPYTER_AUTH_PASSWORD = PersistentConfig(
    "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD",
    "code_execution.jupyter.auth_password",
    os.environ.get("CODE_EXECUTION_JUPYTER_AUTH_PASSWORD", ""),
)

CODE_EXECUTION_JUPYTER_TIMEOUT = PersistentConfig(
    "CODE_EXECUTION_JUPYTER_TIMEOUT",
    "code_execution.jupyter.timeout",
    int(os.environ.get("CODE_EXECUTION_JUPYTER_TIMEOUT", "60")),
)

####################################
# Vector Database
####################################

VECTOR_DB = os.environ.get("VECTOR_DB", "chroma")

# Chroma
CHROMA_DATA_PATH = f"{DATA_DIR}/vector_db"

if VECTOR_DB == "chroma":
    import chromadb

    CHROMA_TENANT = os.environ.get("CHROMA_TENANT", chromadb.DEFAULT_TENANT)
    CHROMA_DATABASE = os.environ.get("CHROMA_DATABASE", chromadb.DEFAULT_DATABASE)
    CHROMA_HTTP_HOST = os.environ.get("CHROMA_HTTP_HOST", "")
    CHROMA_HTTP_PORT = int(os.environ.get("CHROMA_HTTP_PORT", "8000"))
    CHROMA_CLIENT_AUTH_PROVIDER = os.environ.get("CHROMA_CLIENT_AUTH_PROVIDER", "")
    CHROMA_CLIENT_AUTH_CREDENTIALS = os.environ.get(
        "CHROMA_CLIENT_AUTH_CREDENTIALS", ""
    )
    # Comma-separated list of header=value pairs
    CHROMA_HTTP_HEADERS = os.environ.get("CHROMA_HTTP_HEADERS", "")
    if CHROMA_HTTP_HEADERS:
        CHROMA_HTTP_HEADERS = dict(
            [pair.split("=") for pair in CHROMA_HTTP_HEADERS.split(",")]
        )
    else:
        CHROMA_HTTP_HEADERS = None
    CHROMA_HTTP_SSL = os.environ.get("CHROMA_HTTP_SSL", "false").lower() == "true"
# this uses the model defined in the Dockerfile ENV variable. If you dont use docker or docker based deployments such as k8s, the default embedding model will be used (sentence-transformers/all-MiniLM-L6-v2)

# Milvus

MILVUS_URI = os.environ.get("MILVUS_URI", f"{DATA_DIR}/vector_db/milvus.db")
MILVUS_DB = os.environ.get("MILVUS_DB", "default")
MILVUS_TOKEN = os.environ.get("MILVUS_TOKEN", None)

# Qdrant
QDRANT_URI = os.environ.get("QDRANT_URI", None)
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)

# OpenSearch
OPENSEARCH_URI = os.environ.get("OPENSEARCH_URI", "https://localhost:9200")
OPENSEARCH_SSL = os.environ.get("OPENSEARCH_SSL", "true").lower() == "true"
OPENSEARCH_CERT_VERIFY = (
    os.environ.get("OPENSEARCH_CERT_VERIFY", "false").lower() == "true"
)
OPENSEARCH_USERNAME = os.environ.get("OPENSEARCH_USERNAME", None)
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD", None)

# ElasticSearch
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "https://localhost:9200")
ELASTICSEARCH_CA_CERTS = os.environ.get("ELASTICSEARCH_CA_CERTS", None)
ELASTICSEARCH_API_KEY = os.environ.get("ELASTICSEARCH_API_KEY", None)
ELASTICSEARCH_USERNAME = os.environ.get("ELASTICSEARCH_USERNAME", None)
ELASTICSEARCH_PASSWORD = os.environ.get("ELASTICSEARCH_PASSWORD", None)
ELASTICSEARCH_CLOUD_ID = os.environ.get("ELASTICSEARCH_CLOUD_ID", None)
SSL_ASSERT_FINGERPRINT = os.environ.get("SSL_ASSERT_FINGERPRINT", None)
ELASTICSEARCH_INDEX_PREFIX = os.environ.get(
    "ELASTICSEARCH_INDEX_PREFIX", "open_webui_collections"
)
# Pgvector
PGVECTOR_DB_URL = os.environ.get("PGVECTOR_DB_URL", DATABASE_URL)
if VECTOR_DB == "pgvector" and not PGVECTOR_DB_URL.startswith("postgres"):
    raise ValueError(
        "Pgvector requires setting PGVECTOR_DB_URL or using Postgres with vector extension as the primary database."
    )
PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH = int(
    os.environ.get("PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH", "1536")
)

####################################
# Search Engine (extension_modules/search_engine)
# 지식기반, 용어집, DbSphere 등을 위한 검색 엔진 설정
####################################

# 검색 엔진 타입: azure_search, pgvector, milvus, elasticsearch, vertex_search
SEARCH_ENGINE_TYPE = PersistentConfig(
    "SEARCH_ENGINE_TYPE",
    "search_engine.type",
    os.environ.get("SEARCH_ENGINE_TYPE", ""),
)

# Azure AI Search
SEARCH_ENGINE_AZURE_ENDPOINT = PersistentConfig(
    "SEARCH_ENGINE_AZURE_ENDPOINT",
    "search_engine.azure.endpoint",
    os.environ.get("SEARCH_ENGINE_AZURE_ENDPOINT", ""),
)

SEARCH_ENGINE_AZURE_API_KEY = PersistentConfig(
    "SEARCH_ENGINE_AZURE_API_KEY",
    "search_engine.azure.api_key",
    os.environ.get("SEARCH_ENGINE_AZURE_API_KEY", ""),
)

SEARCH_ENGINE_AZURE_API_VERSION = PersistentConfig(
    "SEARCH_ENGINE_AZURE_API_VERSION",
    "search_engine.azure.api_version",
    os.environ.get("SEARCH_ENGINE_AZURE_API_VERSION", "2024-07-01"),
)

# pgvector
SEARCH_ENGINE_PGVECTOR_HOST = PersistentConfig(
    "SEARCH_ENGINE_PGVECTOR_HOST",
    "search_engine.pgvector.host",
    os.environ.get("SEARCH_ENGINE_PGVECTOR_HOST", "localhost"),
)

SEARCH_ENGINE_PGVECTOR_PORT = PersistentConfig(
    "SEARCH_ENGINE_PGVECTOR_PORT",
    "search_engine.pgvector.port",
    int(os.environ.get("SEARCH_ENGINE_PGVECTOR_PORT", "5432")),
)

SEARCH_ENGINE_PGVECTOR_DATABASE = PersistentConfig(
    "SEARCH_ENGINE_PGVECTOR_DATABASE",
    "search_engine.pgvector.database",
    os.environ.get("SEARCH_ENGINE_PGVECTOR_DATABASE", "postgres"),
)

SEARCH_ENGINE_PGVECTOR_USER = PersistentConfig(
    "SEARCH_ENGINE_PGVECTOR_USER",
    "search_engine.pgvector.user",
    os.environ.get("SEARCH_ENGINE_PGVECTOR_USER", "postgres"),
)

SEARCH_ENGINE_PGVECTOR_PASSWORD = PersistentConfig(
    "SEARCH_ENGINE_PGVECTOR_PASSWORD",
    "search_engine.pgvector.password",
    os.environ.get("SEARCH_ENGINE_PGVECTOR_PASSWORD", ""),
)

# Milvus
SEARCH_ENGINE_MILVUS_HOST = PersistentConfig(
    "SEARCH_ENGINE_MILVUS_HOST",
    "search_engine.milvus.host",
    os.environ.get("SEARCH_ENGINE_MILVUS_HOST", "localhost"),
)

SEARCH_ENGINE_MILVUS_PORT = PersistentConfig(
    "SEARCH_ENGINE_MILVUS_PORT",
    "search_engine.milvus.port",
    int(os.environ.get("SEARCH_ENGINE_MILVUS_PORT", "19530")),
)

SEARCH_ENGINE_MILVUS_USER = PersistentConfig(
    "SEARCH_ENGINE_MILVUS_USER",
    "search_engine.milvus.user",
    os.environ.get("SEARCH_ENGINE_MILVUS_USER", ""),
)

SEARCH_ENGINE_MILVUS_PASSWORD = PersistentConfig(
    "SEARCH_ENGINE_MILVUS_PASSWORD",
    "search_engine.milvus.password",
    os.environ.get("SEARCH_ENGINE_MILVUS_PASSWORD", ""),
)

# Elasticsearch
SEARCH_ENGINE_ELASTICSEARCH_URL = PersistentConfig(
    "SEARCH_ENGINE_ELASTICSEARCH_URL",
    "search_engine.elasticsearch.url",
    os.environ.get("SEARCH_ENGINE_ELASTICSEARCH_URL", "http://localhost:9200"),
)

SEARCH_ENGINE_ELASTICSEARCH_API_KEY = PersistentConfig(
    "SEARCH_ENGINE_ELASTICSEARCH_API_KEY",
    "search_engine.elasticsearch.api_key",
    os.environ.get("SEARCH_ENGINE_ELASTICSEARCH_API_KEY", ""),
)

SEARCH_ENGINE_ELASTICSEARCH_USER = PersistentConfig(
    "SEARCH_ENGINE_ELASTICSEARCH_USER",
    "search_engine.elasticsearch.user",
    os.environ.get("SEARCH_ENGINE_ELASTICSEARCH_USER", ""),
)

SEARCH_ENGINE_ELASTICSEARCH_PASSWORD = PersistentConfig(
    "SEARCH_ENGINE_ELASTICSEARCH_PASSWORD",
    "search_engine.elasticsearch.password",
    os.environ.get("SEARCH_ENGINE_ELASTICSEARCH_PASSWORD", ""),
)

SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS = PersistentConfig(
    "SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS",
    "search_engine.elasticsearch.ca_certs",
    os.environ.get("SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS", ""),
)

# Vertex AI Search
SEARCH_ENGINE_VERTEX_PROJECT_ID = PersistentConfig(
    "SEARCH_ENGINE_VERTEX_PROJECT_ID",
    "search_engine.vertex.project_id",
    os.environ.get("SEARCH_ENGINE_VERTEX_PROJECT_ID", ""),
)

SEARCH_ENGINE_VERTEX_LOCATION = PersistentConfig(
    "SEARCH_ENGINE_VERTEX_LOCATION",
    "search_engine.vertex.location",
    os.environ.get("SEARCH_ENGINE_VERTEX_LOCATION", "us-central1"),
)

SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY",
    "search_engine.vertex.service_account_key",
    os.environ.get("SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY", ""),
)

# === Reranker 설정 ===

RERANKER_TYPE = PersistentConfig(
    "RERANKER_TYPE",
    "reranker.type",
    os.environ.get("RERANKER_TYPE", ""),
)

RERANKER_VERTEX_PROJECT_ID = PersistentConfig(
    "RERANKER_VERTEX_PROJECT_ID",
    "reranker.vertex_project_id",
    os.environ.get("RERANKER_VERTEX_PROJECT_ID", ""),
)

RERANKER_VERTEX_LOCATION = PersistentConfig(
    "RERANKER_VERTEX_LOCATION",
    "reranker.vertex_location",
    os.environ.get("RERANKER_VERTEX_LOCATION", "global"),
)

RERANKER_VERTEX_MODEL = PersistentConfig(
    "RERANKER_VERTEX_MODEL",
    "reranker.vertex_model",
    os.environ.get("RERANKER_VERTEX_MODEL", "semantic-ranker-default@latest"),
)

RERANKER_VERTEX_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "RERANKER_VERTEX_SERVICE_ACCOUNT_KEY",
    "reranker.vertex_service_account_key",
    os.environ.get("RERANKER_VERTEX_SERVICE_ACCOUNT_KEY", ""),
)

# === Search Engine 검색 설정 ===

SEARCH_ENGINE_TOP_K = PersistentConfig(
    "SEARCH_ENGINE_TOP_K",
    "search_engine.top_k",
    int(os.environ.get("SEARCH_ENGINE_TOP_K", "20")),
)

SEARCH_ENGINE_RERANKER_TOP_K = PersistentConfig(
    "SEARCH_ENGINE_RERANKER_TOP_K",
    "search_engine.reranker_top_k",
    int(os.environ.get("SEARCH_ENGINE_RERANKER_TOP_K", "5")),
)

SEARCH_ENGINE_RERANKER_THRESHOLD = PersistentConfig(
    "SEARCH_ENGINE_RERANKER_THRESHOLD",
    "search_engine.reranker_threshold",
    float(os.environ.get("SEARCH_ENGINE_RERANKER_THRESHOLD", "0.1")),
)

# Variant A2 — knowledge_handler 의 raw user message fallback (Cloosphere RAG retrieval stability).
# system prompt 의 KV-cache conditioning 이 LLM tool args 를 흔드는 retrieval drift 차단
# (Channel B/C/D). True 시 사용자 원본 last user message 를 LLM-generated queries 앞에 prepend.
# Rollback: False 로 설정 시 LLM-only 기존 동작.
SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED = PersistentConfig(
    "SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED",
    "search_engine.raw_query_fallback_enabled",
    os.environ.get("SEARCH_ENGINE_RAW_QUERY_FALLBACK_ENABLED", "True").lower()
    == "true",
)

####################################
# Information Retrieval (RAG)
####################################


# If configured, Google Drive will be available as an upload option.
ENABLE_GOOGLE_DRIVE_INTEGRATION = PersistentConfig(
    "ENABLE_GOOGLE_DRIVE_INTEGRATION",
    "google_drive.enable",
    os.getenv("ENABLE_GOOGLE_DRIVE_INTEGRATION", "False").lower() == "true",
)

GOOGLE_DRIVE_CLIENT_ID = PersistentConfig(
    "GOOGLE_DRIVE_CLIENT_ID",
    "google_drive.client_id",
    os.environ.get("GOOGLE_DRIVE_CLIENT_ID", ""),
)

GOOGLE_DRIVE_API_KEY = PersistentConfig(
    "GOOGLE_DRIVE_API_KEY",
    "google_drive.api_key",
    os.environ.get("GOOGLE_DRIVE_API_KEY", ""),
)

ENABLE_ONEDRIVE_INTEGRATION = PersistentConfig(
    "ENABLE_ONEDRIVE_INTEGRATION",
    "onedrive.enable",
    os.getenv("ENABLE_ONEDRIVE_INTEGRATION", "False").lower() == "true",
)

ONEDRIVE_CLIENT_ID = PersistentConfig(
    "ONEDRIVE_CLIENT_ID",
    "onedrive.client_id",
    os.environ.get("ONEDRIVE_CLIENT_ID", ""),
)

# SharePoint Integration (Business/Enterprise)
ENABLE_SHAREPOINT_INTEGRATION = PersistentConfig(
    "ENABLE_SHAREPOINT_INTEGRATION",
    "sharepoint.enable",
    os.getenv("ENABLE_SHAREPOINT_INTEGRATION", "False").lower() == "true",
)

SHAREPOINT_CLIENT_ID = PersistentConfig(
    "SHAREPOINT_CLIENT_ID",
    "sharepoint.client_id",
    os.environ.get("ONEDRIVE_CLIENT_ID_BUSINESS", ""),
)

SHAREPOINT_TENANT_ID = PersistentConfig(
    "SHAREPOINT_TENANT_ID",
    "sharepoint.tenant_id",
    os.environ.get("ONEDRIVE_SHAREPOINT_TENANT_ID", ""),
)

SHAREPOINT_SITE_URL = PersistentConfig(
    "SHAREPOINT_SITE_URL",
    "sharepoint.site_url",
    os.environ.get("ONEDRIVE_SHAREPOINT_URL", ""),
)

# DbSphere Configuration
DBSPHERE_TYPES = [
    "MySQL",
    "MSSQL",
    "PostgreSQL",
    "Snowflake",
    "Oracle",
    "SQLite",
    "Databricks",
    "Synapse",
    "Fabric",
    "BigQuery",
]

# RAG Content Extraction
CONTENT_EXTRACTION_ENGINE = PersistentConfig(
    "CONTENT_EXTRACTION_ENGINE",
    "rag.CONTENT_EXTRACTION_ENGINE",
    os.environ.get("CONTENT_EXTRACTION_ENGINE", "").lower(),
)

TIKA_SERVER_URL = PersistentConfig(
    "TIKA_SERVER_URL",
    "rag.tika_server_url",
    os.getenv("TIKA_SERVER_URL", "http://tika:9998"),  # Default for sidecar deployment
)

DOCLING_SERVER_URL = PersistentConfig(
    "DOCLING_SERVER_URL",
    "rag.docling_server_url",
    os.getenv("DOCLING_SERVER_URL", "http://docling:5001"),
)

DOCUMENT_INTELLIGENCE_ENDPOINT = PersistentConfig(
    "DOCUMENT_INTELLIGENCE_ENDPOINT",
    "rag.document_intelligence_endpoint",
    os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT", ""),
)

DOCUMENT_INTELLIGENCE_KEY = PersistentConfig(
    "DOCUMENT_INTELLIGENCE_KEY",
    "rag.document_intelligence_key",
    os.getenv("DOCUMENT_INTELLIGENCE_KEY", ""),
    sensitive=True,
)

MISTRAL_OCR_API_KEY = PersistentConfig(
    "MISTRAL_OCR_API_KEY",
    "rag.mistral_ocr_api_key",
    os.getenv("MISTRAL_OCR_API_KEY", ""),
)

DOCUMENT_AI_PROJECT_ID = PersistentConfig(
    "DOCUMENT_AI_PROJECT_ID",
    "rag.document_ai_project_id",
    os.getenv("DOCUMENT_AI_PROJECT_ID", ""),
)
DOCUMENT_AI_LOCATION = PersistentConfig(
    "DOCUMENT_AI_LOCATION",
    "rag.document_ai_location",
    os.getenv("DOCUMENT_AI_LOCATION", "us"),
)
DOCUMENT_AI_PROCESSOR_ID = PersistentConfig(
    "DOCUMENT_AI_PROCESSOR_ID",
    "rag.document_ai_processor_id",
    os.getenv("DOCUMENT_AI_PROCESSOR_ID", ""),
)
DOCUMENT_AI_PROCESSOR_VERSION = PersistentConfig(
    "DOCUMENT_AI_PROCESSOR_VERSION",
    "rag.document_ai_processor_version",
    os.getenv("DOCUMENT_AI_PROCESSOR_VERSION", ""),
)
DOCUMENT_AI_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "DOCUMENT_AI_SERVICE_ACCOUNT_KEY",
    "rag.document_ai_service_account_key",
    os.getenv("DOCUMENT_AI_SERVICE_ACCOUNT_KEY", ""),
)

BYPASS_EMBEDDING_AND_RETRIEVAL = PersistentConfig(
    "BYPASS_EMBEDDING_AND_RETRIEVAL",
    "rag.bypass_embedding_and_retrieval",
    os.environ.get("BYPASS_EMBEDDING_AND_RETRIEVAL", "False").lower() == "true",
)


RAG_TOP_K = PersistentConfig(
    "RAG_TOP_K", "rag.top_k", int(os.environ.get("RAG_TOP_K", "3"))
)
RAG_FULL_CONTEXT = PersistentConfig(
    "RAG_FULL_CONTEXT",
    "rag.full_context",
    os.getenv("RAG_FULL_CONTEXT", "False").lower() == "true",
)

RAG_FILE_MAX_COUNT = PersistentConfig(
    "RAG_FILE_MAX_COUNT",
    "rag.file.max_count",
    (
        int(os.environ.get("RAG_FILE_MAX_COUNT"))
        if os.environ.get("RAG_FILE_MAX_COUNT")
        else None
    ),
)

RAG_FILE_MAX_SIZE = PersistentConfig(
    "RAG_FILE_MAX_SIZE",
    "rag.file.max_size",
    (
        int(os.environ.get("RAG_FILE_MAX_SIZE"))
        if os.environ.get("RAG_FILE_MAX_SIZE")
        else None
    ),
)

PDF_CONVERT_EXTENSIONS = PersistentConfig(
    "PDF_CONVERT_EXTENSIONS",
    "rag.file.pdf_convert_extensions",
    json.loads(os.environ.get("PDF_CONVERT_EXTENSIONS", "[]")),
)

ALLOWED_FILE_EXTENSIONS = PersistentConfig(
    "ALLOWED_FILE_EXTENSIONS",
    "rag.file.allowed_extensions",
    json.loads(os.environ.get("ALLOWED_FILE_EXTENSIONS", "[]")),
)

####################################
# Global Guardrails (전역 가드레일)
####################################

ENABLE_GLOBAL_GUARDRAIL = PersistentConfig(
    "ENABLE_GLOBAL_GUARDRAIL",
    "guardrail.global.enabled",
    os.environ.get("ENABLE_GLOBAL_GUARDRAIL", "False").lower() == "true",
)

GLOBAL_GUARDRAIL_IDS = PersistentConfig(
    "GLOBAL_GUARDRAIL_IDS",
    "guardrail.global.guardrail_ids",
    [],
)

####################################
# File Upload Guardrails
####################################

FILE_GUARDRAIL_ENABLED = PersistentConfig(
    "FILE_GUARDRAIL_ENABLED",
    "rag.file_guardrail.enabled",
    os.environ.get("FILE_GUARDRAIL_ENABLED", "False").lower() == "true",
)

FILE_GUARDRAIL_SCOPES = PersistentConfig(
    "FILE_GUARDRAIL_SCOPES",
    "rag.file_guardrail.scopes",
    json.loads(
        os.environ.get(
            "FILE_GUARDRAIL_SCOPES",
            '["chat", "knowledge", "project"]',
        )
    ),
)

FILE_GUARDRAIL_IDS = PersistentConfig(
    "FILE_GUARDRAIL_IDS",
    "rag.file_guardrail.guardrail_ids",
    json.loads(os.environ.get("FILE_GUARDRAIL_IDS", "[]")),
)

FILE_GUARDRAIL_EXIF_ENABLED = PersistentConfig(
    "FILE_GUARDRAIL_EXIF_ENABLED",
    "rag.file_guardrail.exif.enabled",
    os.environ.get("FILE_GUARDRAIL_EXIF_ENABLED", "False").lower() == "true",
)

FILE_GUARDRAIL_MACRO_ENABLED = PersistentConfig(
    "FILE_GUARDRAIL_MACRO_ENABLED",
    "rag.file_guardrail.macro.enabled",
    os.environ.get("FILE_GUARDRAIL_MACRO_ENABLED", "False").lower() == "true",
)

FILE_GUARDRAIL_MACRO_ACTION = PersistentConfig(
    "FILE_GUARDRAIL_MACRO_ACTION",
    "rag.file_guardrail.macro.action",
    os.environ.get("FILE_GUARDRAIL_MACRO_ACTION", "block"),
)

FILE_GUARDRAIL_NSFW_ENABLED = PersistentConfig(
    "FILE_GUARDRAIL_NSFW_ENABLED",
    "rag.file_guardrail.nsfw.enabled",
    os.environ.get("FILE_GUARDRAIL_NSFW_ENABLED", "False").lower() == "true",
)

FILE_GUARDRAIL_NSFW_MODEL = PersistentConfig(
    "FILE_GUARDRAIL_NSFW_MODEL",
    "rag.file_guardrail.nsfw.model",
    os.environ.get("FILE_GUARDRAIL_NSFW_MODEL", ""),
)

FILE_GUARDRAIL_NSFW_PROMPT = PersistentConfig(
    "FILE_GUARDRAIL_NSFW_PROMPT",
    "rag.file_guardrail.nsfw.prompt",
    os.environ.get(
        "FILE_GUARDRAIL_NSFW_PROMPT",
        "Analyze this image for inappropriate content (sexual, violent, hateful, or self-harm). Respond with ONLY 'PASS' if the image is safe, or 'BLOCK' if inappropriate.",
    ),
)

FILE_GUARDRAIL_NSFW_PASS_EXAMPLES = PersistentConfig(
    "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES",
    "rag.file_guardrail.nsfw.pass_examples",
    json.loads(os.environ.get("FILE_GUARDRAIL_NSFW_PASS_EXAMPLES", "[]")),
)

FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES = PersistentConfig(
    "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES",
    "rag.file_guardrail.nsfw.block_examples",
    json.loads(os.environ.get("FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES", "[]")),
)

FILE_GUARDRAIL_CLASSIFICATION_ENABLED = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_ENABLED",
    "rag.file_guardrail.classification.enabled",
    os.environ.get("FILE_GUARDRAIL_CLASSIFICATION_ENABLED", "False").lower() == "true",
)

FILE_GUARDRAIL_CLASSIFICATION_MODEL = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_MODEL",
    "rag.file_guardrail.classification.model",
    os.environ.get("FILE_GUARDRAIL_CLASSIFICATION_MODEL", ""),
)

FILE_GUARDRAIL_CLASSIFICATION_PROMPT = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_PROMPT",
    "rag.file_guardrail.classification.prompt",
    os.environ.get(
        "FILE_GUARDRAIL_CLASSIFICATION_PROMPT",
        'You are a document classification system.\nAnalyze the document content and classify it into exactly one sensitivity category.\n\nCategories:\n{categories}\n\nConsider: titles, headers, disclaimers, sensitivity markings, and actual content.\nWhen uncertain, choose the more restrictive category.\n\nRespond with ONLY JSON: {"category": "<CATEGORY_ID>", "confidence": <0.0-1.0>, "reason": "<brief reason>"}',
    ),
)

FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES",
    "rag.file_guardrail.classification.pass_examples",
    json.loads(os.environ.get("FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES", "[]")),
)

FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES",
    "rag.file_guardrail.classification.block_examples",
    json.loads(os.environ.get("FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES", "[]")),
)

FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS",
    "rag.file_guardrail.classification.max_chars",
    int(os.environ.get("FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS", "8000")),
)

FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES = PersistentConfig(
    "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES",
    "rag.file_guardrail.classification.categories",
    json.loads(
        os.environ.get(
            "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES",
            '[{"id":"PUBLIC","name":"Public","description":"Publicly shareable","action":"allow"},{"id":"INTERNAL","name":"Internal","description":"Internal use only","action":"allow"},{"id":"CONFIDENTIAL","name":"Confidential","description":"Business sensitive","action":"flag"},{"id":"RESTRICTED","name":"Restricted","description":"Highly sensitive","action":"block"}]',
        )
    ),
)

RAG_EMBEDDING_ENGINE = PersistentConfig(
    "RAG_EMBEDDING_ENGINE",
    "rag.embedding_engine",
    os.environ.get("RAG_EMBEDDING_ENGINE", ""),
)

PDF_EXTRACT_IMAGES = PersistentConfig(
    "PDF_EXTRACT_IMAGES",
    "rag.pdf_extract_images",
    os.environ.get("PDF_EXTRACT_IMAGES", "False").lower() == "true",
)

RAG_EMBEDDING_MODEL = PersistentConfig(
    "RAG_EMBEDDING_MODEL",
    "rag.embedding_model",
    os.environ.get("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
)
log.info(f"Embedding model set: {RAG_EMBEDDING_MODEL.value}")

RAG_EMBEDDING_MODEL_AUTO_UPDATE = (
    not OFFLINE_MODE
    and os.environ.get("RAG_EMBEDDING_MODEL_AUTO_UPDATE", "True").lower() == "true"
)

RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE = (
    os.environ.get("RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE", "True").lower() == "true"
)

RAG_EMBEDDING_BATCH_SIZE = PersistentConfig(
    "RAG_EMBEDDING_BATCH_SIZE",
    "rag.embedding_batch_size",
    int(
        os.environ.get("RAG_EMBEDDING_BATCH_SIZE")
        or os.environ.get("RAG_EMBEDDING_OPENAI_BATCH_SIZE", "32")
    ),
)

RAG_EMBEDDING_DIMENSIONS = PersistentConfig(
    "RAG_EMBEDDING_DIMENSIONS",
    "rag.embedding_dimensions",
    int(os.environ.get("RAG_EMBEDDING_DIMENSIONS", "0")) or 0,
)

RAG_EMBEDDING_QUERY_PREFIX = os.environ.get("RAG_EMBEDDING_QUERY_PREFIX", None)

RAG_EMBEDDING_CONTENT_PREFIX = os.environ.get("RAG_EMBEDDING_CONTENT_PREFIX", None)

RAG_EMBEDDING_PREFIX_FIELD_NAME = os.environ.get(
    "RAG_EMBEDDING_PREFIX_FIELD_NAME", None
)

RAG_TEXT_SPLITTER = PersistentConfig(
    "RAG_TEXT_SPLITTER",
    "rag.text_splitter",
    os.environ.get("RAG_TEXT_SPLITTER", ""),
)


TIKTOKEN_CACHE_DIR = os.environ.get("TIKTOKEN_CACHE_DIR", f"{CACHE_DIR}/tiktoken")
TIKTOKEN_ENCODING_NAME = PersistentConfig(
    "TIKTOKEN_ENCODING_NAME",
    "rag.tiktoken_encoding_name",
    os.environ.get("TIKTOKEN_ENCODING_NAME", "cl100k_base"),
)


CHUNK_SIZE = PersistentConfig(
    "CHUNK_SIZE", "rag.chunk_size", int(os.environ.get("CHUNK_SIZE", "1000"))
)
CHUNK_OVERLAP = PersistentConfig(
    "CHUNK_OVERLAP",
    "rag.chunk_overlap",
    int(os.environ.get("CHUNK_OVERLAP", "100")),
)

# 임베딩 직전 토큰 단위 청크 크기 안전망 (모든 splitter 공통).
# semantic chunker 는 최대 상한이 없어 거대 청크가 생길 수 있고, overlap/contextual
# 후처리가 청크를 더 키운다. 임베딩 모델 토큰 한도(OpenAI/Azure ~8191) 초과 시
# 배치 전체가 실패하므로, 한도를 넘는 청크는 토큰 경계로 재분할한다.
# 0 = 비활성. 기본값 2000 — 임베딩 한도(8191)보다 충분히 작고 RAG 검색 정밀도에도 적절.
RAG_CHUNK_MAX_TOKENS = PersistentConfig(
    "RAG_CHUNK_MAX_TOKENS",
    "rag.chunk_max_tokens",
    int(os.environ.get("RAG_CHUNK_MAX_TOKENS", "2000")),
)
# 인접한 과소 청크를 병합할 최소 토큰 수. 0 = 병합 안 함(기본).
RAG_CHUNK_MIN_TOKENS = PersistentConfig(
    "RAG_CHUNK_MIN_TOKENS",
    "rag.chunk_min_tokens",
    int(os.environ.get("RAG_CHUNK_MIN_TOKENS", "0")),
)

DEFAULT_RAG_TEMPLATE = """### Task:
Respond to the user query using the provided context, incorporating inline citations in the format [id] **only when the <source> tag includes an explicit id attribute** (e.g., <source id="1">).

### Guidelines:
- If you don't know the answer, clearly state that.
- If uncertain, ask the user for clarification.
- Respond in the same language as the user's query.
- If the context is unreadable or of poor quality, inform the user and provide the best possible answer.
- If the answer isn't present in the context but you possess the knowledge, explain this to the user and provide the answer using your own understanding.
- **Only include inline citations using [id] (e.g., [1], [2]) when the <source> tag includes an id attribute.**
- Do not cite if the <source> tag does not contain an id attribute.
- Do not use XML tags in your response.
- Ensure citations are concise and directly related to the information provided.

### Example of Citation:
If the user asks about a specific topic and the information is found in a source with a provided id attribute, the response should include the citation like in the following example:
* "According to the study, the proposed method increases efficiency by 20% [1]."

### Output:
Provide a clear and direct response to the user's query, including inline citations in the format [id] only when the <source> tag with id attribute is present in the context.

<context>
{{CONTEXT}}
</context>

<user_query>
{{QUERY}}
</user_query>
"""

RAG_TEMPLATE = PersistentConfig(
    "RAG_TEMPLATE",
    "rag.template",
    os.environ.get("RAG_TEMPLATE", DEFAULT_RAG_TEMPLATE),
)

RAG_OPENAI_API_BASE_URL = PersistentConfig(
    "RAG_OPENAI_API_BASE_URL",
    "rag.openai_api_base_url",
    os.getenv("RAG_OPENAI_API_BASE_URL", OPENAI_API_BASE_URL),
)
RAG_OPENAI_API_KEY = PersistentConfig(
    "RAG_OPENAI_API_KEY",
    "rag.openai_api_key",
    os.getenv("RAG_OPENAI_API_KEY", OPENAI_API_KEY),
)

RAG_OLLAMA_BASE_URL = PersistentConfig(
    "RAG_OLLAMA_BASE_URL",
    "rag.ollama.url",
    os.getenv("RAG_OLLAMA_BASE_URL", OLLAMA_BASE_URL),
)

RAG_OLLAMA_API_KEY = PersistentConfig(
    "RAG_OLLAMA_API_KEY",
    "rag.ollama.key",
    os.getenv("RAG_OLLAMA_API_KEY", ""),
    sensitive=True,
)

RAG_AZURE_OPENAI_API_BASE_URL = PersistentConfig(
    "RAG_AZURE_OPENAI_API_BASE_URL",
    "rag.azure_openai_api_base_url",
    os.getenv("RAG_AZURE_OPENAI_API_BASE_URL", ""),
)
RAG_AZURE_OPENAI_API_KEY = PersistentConfig(
    "RAG_AZURE_OPENAI_API_KEY",
    "rag.azure_openai_api_key",
    os.getenv("RAG_AZURE_OPENAI_API_KEY", ""),
)
RAG_AZURE_OPENAI_API_VERSION = PersistentConfig(
    "RAG_AZURE_OPENAI_API_VERSION",
    "rag.azure_openai_api_version",
    os.getenv("RAG_AZURE_OPENAI_API_VERSION", ""),
)

RAG_GEMINI_API_KEY = PersistentConfig(
    "RAG_GEMINI_API_KEY",
    "rag.gemini_api_key",
    os.getenv("RAG_GEMINI_API_KEY", ""),
)
RAG_VERTEX_AI_PROJECT_ID = PersistentConfig(
    "RAG_VERTEX_AI_PROJECT_ID",
    "rag.vertex_ai_project_id",
    os.getenv("RAG_VERTEX_AI_PROJECT_ID", ""),
)
RAG_VERTEX_AI_LOCATION = PersistentConfig(
    "RAG_VERTEX_AI_LOCATION",
    "rag.vertex_ai_location",
    os.getenv("RAG_VERTEX_AI_LOCATION", "us-central1"),
)
RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY",
    "rag.vertex_ai_service_account_key",
    os.getenv("RAG_VERTEX_AI_SERVICE_ACCOUNT_KEY", ""),
)


####################################
# Knowledge Base Question Generation
####################################

KB_QUESTION_GENERATION_ENABLED = PersistentConfig(
    "KB_QUESTION_GENERATION_ENABLED",
    "rag.kb_question_generation.enabled",
    os.getenv("KB_QUESTION_GENERATION_ENABLED", "False").lower() == "true",
)

KB_QUESTION_GENERATION_MODEL = PersistentConfig(
    "KB_QUESTION_GENERATION_MODEL",
    "rag.kb_question_generation.model",
    os.getenv("KB_QUESTION_GENERATION_MODEL", ""),
)

KB_MAX_QUESTIONS_PER_CHUNK = PersistentConfig(
    "KB_MAX_QUESTIONS_PER_CHUNK",
    "rag.kb_question_generation.max_questions_per_chunk",
    int(os.getenv("KB_MAX_QUESTIONS_PER_CHUNK", "10")),
)

KB_QUESTION_VECTOR_WEIGHT = PersistentConfig(
    "KB_QUESTION_VECTOR_WEIGHT",
    "rag.kb_question_generation.vector_weight",
    float(os.getenv("KB_QUESTION_VECTOR_WEIGHT", "0.5")),
)


ENABLE_RAG_LOCAL_WEB_FETCH = (
    os.getenv("ENABLE_RAG_LOCAL_WEB_FETCH", "False").lower() == "true"
)

YOUTUBE_LOADER_LANGUAGE = PersistentConfig(
    "YOUTUBE_LOADER_LANGUAGE",
    "rag.youtube_loader_language",
    os.getenv("YOUTUBE_LOADER_LANGUAGE", "en").split(","),
)

YOUTUBE_LOADER_PROXY_URL = PersistentConfig(
    "YOUTUBE_LOADER_PROXY_URL",
    "rag.youtube_loader_proxy_url",
    os.getenv("YOUTUBE_LOADER_PROXY_URL", ""),
)


####################################
# Web Search (RAG)
####################################

ENABLE_WEB_SEARCH = PersistentConfig(
    "ENABLE_WEB_SEARCH",
    "rag.web.search.enable",
    os.getenv("ENABLE_WEB_SEARCH", "False").lower() == "true",
)

WEB_SEARCH_ENGINE = PersistentConfig(
    "WEB_SEARCH_ENGINE",
    "rag.web.search.engine",
    os.getenv("WEB_SEARCH_ENGINE", ""),
)

BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL = PersistentConfig(
    "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL",
    "rag.web.search.bypass_embedding_and_retrieval",
    os.getenv("BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL", "False").lower() == "true",
)


WEB_SEARCH_RESULT_COUNT = PersistentConfig(
    "WEB_SEARCH_RESULT_COUNT",
    "rag.web.search.result_count",
    int(os.getenv("WEB_SEARCH_RESULT_COUNT", "3")),
)


# You can provide a list of your own websites to filter after performing a web search.
# This ensures the highest level of safety and reliability of the information sources.
WEB_SEARCH_DOMAIN_FILTER_LIST = PersistentConfig(
    "WEB_SEARCH_DOMAIN_FILTER_LIST",
    "rag.web.search.domain.filter_list",
    [
        # "wikipedia.com",
        # "wikimedia.org",
        # "wikidata.org",
    ],
)

WEB_SEARCH_CONCURRENT_REQUESTS = PersistentConfig(
    "WEB_SEARCH_CONCURRENT_REQUESTS",
    "rag.web.search.concurrent_requests",
    int(os.getenv("WEB_SEARCH_CONCURRENT_REQUESTS", "10")),
)

WEB_LOADER_ENGINE = PersistentConfig(
    "WEB_LOADER_ENGINE",
    "rag.web.loader.engine",
    os.environ.get("WEB_LOADER_ENGINE", ""),
)

ENABLE_WEB_LOADER_SSL_VERIFICATION = PersistentConfig(
    "ENABLE_WEB_LOADER_SSL_VERIFICATION",
    "rag.web.loader.ssl_verification",
    os.environ.get("ENABLE_WEB_LOADER_SSL_VERIFICATION", "True").lower() == "true",
)

WEB_SEARCH_TRUST_ENV = PersistentConfig(
    "WEB_SEARCH_TRUST_ENV",
    "rag.web.search.trust_env",
    os.getenv("WEB_SEARCH_TRUST_ENV", "False").lower() == "true",
)


SEARXNG_QUERY_URL = PersistentConfig(
    "SEARXNG_QUERY_URL",
    "rag.web.search.searxng_query_url",
    os.getenv("SEARXNG_QUERY_URL", ""),
)

GOOGLE_PSE_API_KEY = PersistentConfig(
    "GOOGLE_PSE_API_KEY",
    "rag.web.search.google_pse_api_key",
    os.getenv("GOOGLE_PSE_API_KEY", ""),
)

GOOGLE_PSE_ENGINE_ID = PersistentConfig(
    "GOOGLE_PSE_ENGINE_ID",
    "rag.web.search.google_pse_engine_id",
    os.getenv("GOOGLE_PSE_ENGINE_ID", ""),
)

BRAVE_SEARCH_API_KEY = PersistentConfig(
    "BRAVE_SEARCH_API_KEY",
    "rag.web.search.brave_search_api_key",
    os.getenv("BRAVE_SEARCH_API_KEY", ""),
)

KAGI_SEARCH_API_KEY = PersistentConfig(
    "KAGI_SEARCH_API_KEY",
    "rag.web.search.kagi_search_api_key",
    os.getenv("KAGI_SEARCH_API_KEY", ""),
)

MOJEEK_SEARCH_API_KEY = PersistentConfig(
    "MOJEEK_SEARCH_API_KEY",
    "rag.web.search.mojeek_search_api_key",
    os.getenv("MOJEEK_SEARCH_API_KEY", ""),
)

BOCHA_SEARCH_API_KEY = PersistentConfig(
    "BOCHA_SEARCH_API_KEY",
    "rag.web.search.bocha_search_api_key",
    os.getenv("BOCHA_SEARCH_API_KEY", ""),
)

SERPSTACK_API_KEY = PersistentConfig(
    "SERPSTACK_API_KEY",
    "rag.web.search.serpstack_api_key",
    os.getenv("SERPSTACK_API_KEY", ""),
)

SERPSTACK_HTTPS = PersistentConfig(
    "SERPSTACK_HTTPS",
    "rag.web.search.serpstack_https",
    os.getenv("SERPSTACK_HTTPS", "True").lower() == "true",
)

SERPER_API_KEY = PersistentConfig(
    "SERPER_API_KEY",
    "rag.web.search.serper_api_key",
    os.getenv("SERPER_API_KEY", ""),
)

SERPLY_API_KEY = PersistentConfig(
    "SERPLY_API_KEY",
    "rag.web.search.serply_api_key",
    os.getenv("SERPLY_API_KEY", ""),
)

JINA_API_KEY = PersistentConfig(
    "JINA_API_KEY",
    "rag.web.search.jina_api_key",
    os.getenv("JINA_API_KEY", ""),
)

SEARCHAPI_API_KEY = PersistentConfig(
    "SEARCHAPI_API_KEY",
    "rag.web.search.searchapi_api_key",
    os.getenv("SEARCHAPI_API_KEY", ""),
)

SEARCHAPI_ENGINE = PersistentConfig(
    "SEARCHAPI_ENGINE",
    "rag.web.search.searchapi_engine",
    os.getenv("SEARCHAPI_ENGINE", ""),
)

SERPAPI_API_KEY = PersistentConfig(
    "SERPAPI_API_KEY",
    "rag.web.search.serpapi_api_key",
    os.getenv("SERPAPI_API_KEY", ""),
)

SERPAPI_ENGINE = PersistentConfig(
    "SERPAPI_ENGINE",
    "rag.web.search.serpapi_engine",
    os.getenv("SERPAPI_ENGINE", ""),
)

BING_SEARCH_V7_ENDPOINT = PersistentConfig(
    "BING_SEARCH_V7_ENDPOINT",
    "rag.web.search.bing_search_v7_endpoint",
    os.environ.get(
        "BING_SEARCH_V7_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search"
    ),
)

BING_SEARCH_V7_SUBSCRIPTION_KEY = PersistentConfig(
    "BING_SEARCH_V7_SUBSCRIPTION_KEY",
    "rag.web.search.bing_search_v7_subscription_key",
    os.environ.get("BING_SEARCH_V7_SUBSCRIPTION_KEY", ""),
)

EXA_API_KEY = PersistentConfig(
    "EXA_API_KEY",
    "rag.web.search.exa_api_key",
    os.getenv("EXA_API_KEY", ""),
)

PERPLEXITY_API_KEY = PersistentConfig(
    "PERPLEXITY_API_KEY",
    "rag.web.search.perplexity_api_key",
    os.getenv("PERPLEXITY_API_KEY", ""),
)

SOUGOU_API_SID = PersistentConfig(
    "SOUGOU_API_SID",
    "rag.web.search.sougou_api_sid",
    os.getenv("SOUGOU_API_SID", ""),
)

SOUGOU_API_SK = PersistentConfig(
    "SOUGOU_API_SK",
    "rag.web.search.sougou_api_sk",
    os.getenv("SOUGOU_API_SK", ""),
    sensitive=True,
)

TAVILY_API_KEY = PersistentConfig(
    "TAVILY_API_KEY",
    "rag.web.search.tavily_api_key",
    os.getenv("TAVILY_API_KEY", ""),
)

TAVILY_EXTRACT_DEPTH = PersistentConfig(
    "TAVILY_EXTRACT_DEPTH",
    "rag.web.search.tavily_extract_depth",
    os.getenv("TAVILY_EXTRACT_DEPTH", "basic"),
)

PLAYWRIGHT_WS_URL = PersistentConfig(
    "PLAYWRIGHT_WS_URL",
    "rag.web.loader.playwright_ws_url",
    os.environ.get("PLAYWRIGHT_WS_URL", ""),
)

PLAYWRIGHT_TIMEOUT = PersistentConfig(
    "PLAYWRIGHT_TIMEOUT",
    "rag.web.loader.playwright_timeout",
    int(os.environ.get("PLAYWRIGHT_TIMEOUT", "10000")),
)

FIRECRAWL_API_KEY = PersistentConfig(
    "FIRECRAWL_API_KEY",
    "rag.web.loader.firecrawl_api_key",
    os.environ.get("FIRECRAWL_API_KEY", ""),
)

FIRECRAWL_API_BASE_URL = PersistentConfig(
    "FIRECRAWL_API_BASE_URL",
    "rag.web.loader.firecrawl_api_url",
    os.environ.get("FIRECRAWL_API_BASE_URL", "https://api.firecrawl.dev"),
)


####################################
# Images
####################################

IMAGE_GENERATION_ENGINE = PersistentConfig(
    "IMAGE_GENERATION_ENGINE",
    "image_generation.engine",
    os.getenv("IMAGE_GENERATION_ENGINE", "openai"),
)

ENABLE_IMAGE_GENERATION = PersistentConfig(
    "ENABLE_IMAGE_GENERATION",
    "image_generation.enable",
    os.environ.get("ENABLE_IMAGE_GENERATION", "").lower() == "true",
)

ENABLE_IMAGE_PROMPT_GENERATION = PersistentConfig(
    "ENABLE_IMAGE_PROMPT_GENERATION",
    "image_generation.prompt.enable",
    os.environ.get("ENABLE_IMAGE_PROMPT_GENERATION", "true").lower() == "true",
)

AUTOMATIC1111_BASE_URL = PersistentConfig(
    "AUTOMATIC1111_BASE_URL",
    "image_generation.automatic1111.base_url",
    os.getenv("AUTOMATIC1111_BASE_URL", ""),
)
AUTOMATIC1111_API_AUTH = PersistentConfig(
    "AUTOMATIC1111_API_AUTH",
    "image_generation.automatic1111.api_auth",
    os.getenv("AUTOMATIC1111_API_AUTH", ""),
    sensitive=True,
)

AUTOMATIC1111_CFG_SCALE = PersistentConfig(
    "AUTOMATIC1111_CFG_SCALE",
    "image_generation.automatic1111.cfg_scale",
    (
        float(os.environ.get("AUTOMATIC1111_CFG_SCALE"))
        if os.environ.get("AUTOMATIC1111_CFG_SCALE")
        else None
    ),
)


AUTOMATIC1111_SAMPLER = PersistentConfig(
    "AUTOMATIC1111_SAMPLER",
    "image_generation.automatic1111.sampler",
    (
        os.environ.get("AUTOMATIC1111_SAMPLER")
        if os.environ.get("AUTOMATIC1111_SAMPLER")
        else None
    ),
)

AUTOMATIC1111_SCHEDULER = PersistentConfig(
    "AUTOMATIC1111_SCHEDULER",
    "image_generation.automatic1111.scheduler",
    (
        os.environ.get("AUTOMATIC1111_SCHEDULER")
        if os.environ.get("AUTOMATIC1111_SCHEDULER")
        else None
    ),
)

COMFYUI_BASE_URL = PersistentConfig(
    "COMFYUI_BASE_URL",
    "image_generation.comfyui.base_url",
    os.getenv("COMFYUI_BASE_URL", ""),
)

COMFYUI_API_KEY = PersistentConfig(
    "COMFYUI_API_KEY",
    "image_generation.comfyui.api_key",
    os.getenv("COMFYUI_API_KEY", ""),
)

COMFYUI_DEFAULT_WORKFLOW = """
{
  "3": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "4",
        0
      ],
      "positive": [
        "6",
        0
      ],
      "negative": [
        "7",
        0
      ],
      "latent_image": [
        "5",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "KSampler"
    }
  },
  "4": {
    "inputs": {
      "ckpt_name": "model.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Load Checkpoint"
    }
  },
  "5": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "Empty Latent Image"
    }
  },
  "6": {
    "inputs": {
      "text": "Prompt",
      "clip": [
        "4",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP Text Encode (Prompt)"
    }
  },
  "7": {
    "inputs": {
      "text": "",
      "clip": [
        "4",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP Text Encode (Prompt)"
    }
  },
  "8": {
    "inputs": {
      "samples": [
        "3",
        0
      ],
      "vae": [
        "4",
        2
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE Decode"
    }
  },
  "9": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": [
        "8",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "Save Image"
    }
  }
}
"""


COMFYUI_WORKFLOW = PersistentConfig(
    "COMFYUI_WORKFLOW",
    "image_generation.comfyui.workflow",
    os.getenv("COMFYUI_WORKFLOW", COMFYUI_DEFAULT_WORKFLOW),
)

COMFYUI_WORKFLOW_NODES = PersistentConfig(
    "COMFYUI_WORKFLOW",
    "image_generation.comfyui.nodes",
    [],
)

IMAGES_OPENAI_API_BASE_URL = PersistentConfig(
    "IMAGES_OPENAI_API_BASE_URL",
    "image_generation.openai.api_base_url",
    os.getenv("IMAGES_OPENAI_API_BASE_URL", OPENAI_API_BASE_URL),
)
IMAGES_OPENAI_API_KEY = PersistentConfig(
    "IMAGES_OPENAI_API_KEY",
    "image_generation.openai.api_key",
    os.getenv("IMAGES_OPENAI_API_KEY", OPENAI_API_KEY),
)

IMAGES_GEMINI_API_BASE_URL = PersistentConfig(
    "IMAGES_GEMINI_API_BASE_URL",
    "image_generation.gemini.api_base_url",
    os.getenv("IMAGES_GEMINI_API_BASE_URL", GEMINI_API_BASE_URL),
)
IMAGES_GEMINI_API_KEY = PersistentConfig(
    "IMAGES_GEMINI_API_KEY",
    "image_generation.gemini.api_key",
    os.getenv("IMAGES_GEMINI_API_KEY", GEMINI_API_KEY),
)

# Azure OpenAI Image
IMAGES_AZURE_OPENAI_API_BASE_URL = PersistentConfig(
    "IMAGES_AZURE_OPENAI_API_BASE_URL",
    "image_generation.azure_openai.api_base_url",
    os.getenv("IMAGES_AZURE_OPENAI_API_BASE_URL", ""),
)
IMAGES_AZURE_OPENAI_API_KEY = PersistentConfig(
    "IMAGES_AZURE_OPENAI_API_KEY",
    "image_generation.azure_openai.api_key",
    os.getenv("IMAGES_AZURE_OPENAI_API_KEY", ""),
)
IMAGES_AZURE_OPENAI_API_VERSION = PersistentConfig(
    "IMAGES_AZURE_OPENAI_API_VERSION",
    "image_generation.azure_openai.api_version",
    os.getenv("IMAGES_AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
)
IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME = PersistentConfig(
    "IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME",
    "image_generation.azure_openai.deployment_name",
    os.getenv("IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME", ""),
)
IMAGES_AZURE_OPENAI_QUALITY = PersistentConfig(
    "IMAGES_AZURE_OPENAI_QUALITY",
    "image_generation.azure_openai.quality",
    os.getenv("IMAGES_AZURE_OPENAI_QUALITY", "auto"),
)
IMAGES_AZURE_OPENAI_OUTPUT_FORMAT = PersistentConfig(
    "IMAGES_AZURE_OPENAI_OUTPUT_FORMAT",
    "image_generation.azure_openai.output_format",
    os.getenv("IMAGES_AZURE_OPENAI_OUTPUT_FORMAT", "png"),
)
IMAGES_AZURE_OPENAI_BACKGROUND = PersistentConfig(
    "IMAGES_AZURE_OPENAI_BACKGROUND",
    "image_generation.azure_openai.background",
    os.getenv("IMAGES_AZURE_OPENAI_BACKGROUND", "auto"),
)

# Vertex AI Image
IMAGES_VERTEX_AI_PROJECT_ID = PersistentConfig(
    "IMAGES_VERTEX_AI_PROJECT_ID",
    "image_generation.vertex_ai.project_id",
    os.getenv("IMAGES_VERTEX_AI_PROJECT_ID", ""),
)
IMAGES_VERTEX_AI_LOCATION = PersistentConfig(
    "IMAGES_VERTEX_AI_LOCATION",
    "image_generation.vertex_ai.location",
    os.getenv("IMAGES_VERTEX_AI_LOCATION", "us-central1"),
)
IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY",
    "image_generation.vertex_ai.service_account_key",
    os.getenv("IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY", ""),
)

IMAGE_SIZE = PersistentConfig(
    "IMAGE_SIZE", "image_generation.size", os.getenv("IMAGE_SIZE", "1024x1024")
)

IMAGE_STEPS = PersistentConfig(
    "IMAGE_STEPS", "image_generation.steps", int(os.getenv("IMAGE_STEPS", 50))
)

IMAGE_GENERATION_MODEL = PersistentConfig(
    "IMAGE_GENERATION_MODEL",
    "image_generation.model",
    os.getenv("IMAGE_GENERATION_MODEL", ""),
)

# Multi-connection Image Generation
IMAGE_API_URLS = PersistentConfig(
    "IMAGE_API_URLS",
    "image.api_urls",
    [],
)
IMAGE_API_KEYS = PersistentConfig(
    "IMAGE_API_KEYS",
    "image.api_keys",
    [],
)
IMAGE_API_CONFIGS = PersistentConfig(
    "IMAGE_API_CONFIGS",
    "image.api_configs",
    {},
)

####################################
# Audio
####################################

# Transcription
WHISPER_MODEL = PersistentConfig(
    "WHISPER_MODEL",
    "audio.stt.whisper_model",
    os.getenv("WHISPER_MODEL", "base"),
)

WHISPER_MODEL_DIR = os.getenv("WHISPER_MODEL_DIR", f"{CACHE_DIR}/whisper/models")
WHISPER_MODEL_AUTO_UPDATE = (
    not OFFLINE_MODE
    and os.environ.get("WHISPER_MODEL_AUTO_UPDATE", "").lower() == "true"
)

WHISPER_VAD_FILTER = PersistentConfig(
    "WHISPER_VAD_FILTER",
    "audio.stt.whisper_vad_filter",
    os.getenv("WHISPER_VAD_FILTER", "False").lower() == "true",
)


# Add Deepgram configuration
DEEPGRAM_API_KEY = PersistentConfig(
    "DEEPGRAM_API_KEY",
    "audio.stt.deepgram.api_key",
    os.getenv("DEEPGRAM_API_KEY", ""),
)


AUDIO_STT_OPENAI_API_BASE_URL = PersistentConfig(
    "AUDIO_STT_OPENAI_API_BASE_URL",
    "audio.stt.openai.api_base_url",
    os.getenv("AUDIO_STT_OPENAI_API_BASE_URL", OPENAI_API_BASE_URL),
)

AUDIO_STT_OPENAI_API_KEY = PersistentConfig(
    "AUDIO_STT_OPENAI_API_KEY",
    "audio.stt.openai.api_key",
    os.getenv("AUDIO_STT_OPENAI_API_KEY", OPENAI_API_KEY),
)

AUDIO_STT_ENGINE = PersistentConfig(
    "AUDIO_STT_ENGINE",
    "audio.stt.engine",
    os.getenv("AUDIO_STT_ENGINE", ""),
)

AUDIO_STT_MODEL = PersistentConfig(
    "AUDIO_STT_MODEL",
    "audio.stt.model",
    os.getenv("AUDIO_STT_MODEL", ""),
)

AUDIO_STT_AZURE_API_KEY = PersistentConfig(
    "AUDIO_STT_AZURE_API_KEY",
    "audio.stt.azure.api_key",
    os.getenv("AUDIO_STT_AZURE_API_KEY", ""),
)

AUDIO_STT_AZURE_REGION = PersistentConfig(
    "AUDIO_STT_AZURE_REGION",
    "audio.stt.azure.region",
    os.getenv("AUDIO_STT_AZURE_REGION", ""),
)

AUDIO_STT_AZURE_LOCALES = PersistentConfig(
    "AUDIO_STT_AZURE_LOCALES",
    "audio.stt.azure.locales",
    os.getenv("AUDIO_STT_AZURE_LOCALES", ""),
)

# Google Cloud STT
AUDIO_STT_GOOGLE_PROJECT_ID = PersistentConfig(
    "AUDIO_STT_GOOGLE_PROJECT_ID",
    "audio.stt.google.project_id",
    os.getenv("AUDIO_STT_GOOGLE_PROJECT_ID", ""),
)
AUDIO_STT_GOOGLE_LOCATION = PersistentConfig(
    "AUDIO_STT_GOOGLE_LOCATION",
    "audio.stt.google.location",
    os.getenv("AUDIO_STT_GOOGLE_LOCATION", "global"),
)
AUDIO_STT_GOOGLE_LANGUAGE_CODES = PersistentConfig(
    "AUDIO_STT_GOOGLE_LANGUAGE_CODES",
    "audio.stt.google.language_codes",
    os.getenv("AUDIO_STT_GOOGLE_LANGUAGE_CODES", "auto"),
)
AUDIO_STT_GOOGLE_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "AUDIO_STT_GOOGLE_SERVICE_ACCOUNT_KEY",
    "audio.stt.google.service_account_key",
    os.getenv("AUDIO_STT_GOOGLE_SERVICE_ACCOUNT_KEY", ""),
)

AUDIO_TTS_OPENAI_API_BASE_URL = PersistentConfig(
    "AUDIO_TTS_OPENAI_API_BASE_URL",
    "audio.tts.openai.api_base_url",
    os.getenv("AUDIO_TTS_OPENAI_API_BASE_URL", OPENAI_API_BASE_URL),
)
AUDIO_TTS_OPENAI_API_KEY = PersistentConfig(
    "AUDIO_TTS_OPENAI_API_KEY",
    "audio.tts.openai.api_key",
    os.getenv("AUDIO_TTS_OPENAI_API_KEY", OPENAI_API_KEY),
)

AUDIO_TTS_API_KEY = PersistentConfig(
    "AUDIO_TTS_API_KEY",
    "audio.tts.api_key",
    os.getenv("AUDIO_TTS_API_KEY", ""),
)

AUDIO_TTS_ENGINE = PersistentConfig(
    "AUDIO_TTS_ENGINE",
    "audio.tts.engine",
    os.getenv("AUDIO_TTS_ENGINE", ""),
)


AUDIO_TTS_MODEL = PersistentConfig(
    "AUDIO_TTS_MODEL",
    "audio.tts.model",
    os.getenv("AUDIO_TTS_MODEL", "tts-1"),  # OpenAI default model
)

AUDIO_TTS_VOICE = PersistentConfig(
    "AUDIO_TTS_VOICE",
    "audio.tts.voice",
    os.getenv("AUDIO_TTS_VOICE", "alloy"),  # OpenAI default voice
)

AUDIO_TTS_SPLIT_ON = PersistentConfig(
    "AUDIO_TTS_SPLIT_ON",
    "audio.tts.split_on",
    os.getenv("AUDIO_TTS_SPLIT_ON", "punctuation"),
)

AUDIO_TTS_AZURE_SPEECH_REGION = PersistentConfig(
    "AUDIO_TTS_AZURE_SPEECH_REGION",
    "audio.tts.azure.speech_region",
    os.getenv("AUDIO_TTS_AZURE_SPEECH_REGION", "eastus"),
)

AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT = PersistentConfig(
    "AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT",
    "audio.tts.azure.speech_output_format",
    os.getenv(
        "AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT", "audio-24khz-160kbitrate-mono-mp3"
    ),
)

# Google Cloud TTS
AUDIO_TTS_GOOGLE_LANGUAGE_CODE = PersistentConfig(
    "AUDIO_TTS_GOOGLE_LANGUAGE_CODE",
    "audio.tts.google.language_code",
    os.getenv("AUDIO_TTS_GOOGLE_LANGUAGE_CODE", ""),
)
AUDIO_TTS_GOOGLE_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "AUDIO_TTS_GOOGLE_SERVICE_ACCOUNT_KEY",
    "audio.tts.google.service_account_key",
    os.getenv("AUDIO_TTS_GOOGLE_SERVICE_ACCOUNT_KEY", ""),
)

# Gemini TTS
AUDIO_TTS_GEMINI_MODEL = PersistentConfig(
    "AUDIO_TTS_GEMINI_MODEL",
    "audio.tts.gemini.model",
    os.getenv("AUDIO_TTS_GEMINI_MODEL", "gemini-2.5-flash-preview-tts"),
)
AUDIO_TTS_GEMINI_LOCATION = PersistentConfig(
    "AUDIO_TTS_GEMINI_LOCATION",
    "audio.tts.gemini.location",
    os.getenv("AUDIO_TTS_GEMINI_LOCATION", "us-central1"),
)
AUDIO_TTS_GEMINI_SERVICE_ACCOUNT_KEY = PersistentConfig(
    "AUDIO_TTS_GEMINI_SERVICE_ACCOUNT_KEY",
    "audio.tts.gemini.service_account_key",
    os.getenv("AUDIO_TTS_GEMINI_SERVICE_ACCOUNT_KEY", ""),
)


####################################
# LDAP
####################################

ENABLE_LDAP = PersistentConfig(
    "ENABLE_LDAP",
    "ldap.enable",
    os.environ.get("ENABLE_LDAP", "false").lower() == "true",
)

LDAP_SERVER_LABEL = PersistentConfig(
    "LDAP_SERVER_LABEL",
    "ldap.server.label",
    os.environ.get("LDAP_SERVER_LABEL", "LDAP Server"),
)

LDAP_SERVER_HOST = PersistentConfig(
    "LDAP_SERVER_HOST",
    "ldap.server.host",
    os.environ.get("LDAP_SERVER_HOST", "localhost"),
)

LDAP_SERVER_PORT = PersistentConfig(
    "LDAP_SERVER_PORT",
    "ldap.server.port",
    int(os.environ.get("LDAP_SERVER_PORT", "389")),
)

LDAP_ATTRIBUTE_FOR_MAIL = PersistentConfig(
    "LDAP_ATTRIBUTE_FOR_MAIL",
    "ldap.server.attribute_for_mail",
    os.environ.get("LDAP_ATTRIBUTE_FOR_MAIL", "mail"),
)

LDAP_ATTRIBUTE_FOR_USERNAME = PersistentConfig(
    "LDAP_ATTRIBUTE_FOR_USERNAME",
    "ldap.server.attribute_for_username",
    os.environ.get("LDAP_ATTRIBUTE_FOR_USERNAME", "uid"),
)

LDAP_APP_DN = PersistentConfig(
    "LDAP_APP_DN", "ldap.server.app_dn", os.environ.get("LDAP_APP_DN", "")
)

LDAP_APP_PASSWORD = PersistentConfig(
    "LDAP_APP_PASSWORD",
    "ldap.server.app_password",
    os.environ.get("LDAP_APP_PASSWORD", ""),
)

LDAP_SEARCH_BASE = PersistentConfig(
    "LDAP_SEARCH_BASE", "ldap.server.users_dn", os.environ.get("LDAP_SEARCH_BASE", "")
)

LDAP_SEARCH_FILTERS = PersistentConfig(
    "LDAP_SEARCH_FILTER",
    "ldap.server.search_filter",
    os.environ.get("LDAP_SEARCH_FILTER", os.environ.get("LDAP_SEARCH_FILTERS", "")),
)

LDAP_USE_TLS = PersistentConfig(
    "LDAP_USE_TLS",
    "ldap.server.use_tls",
    os.environ.get("LDAP_USE_TLS", "True").lower() == "true",
)

LDAP_CA_CERT_FILE = PersistentConfig(
    "LDAP_CA_CERT_FILE",
    "ldap.server.ca_cert_file",
    os.environ.get("LDAP_CA_CERT_FILE", ""),
)

LDAP_CIPHERS = PersistentConfig(
    "LDAP_CIPHERS", "ldap.server.ciphers", os.environ.get("LDAP_CIPHERS", "ALL")
)

AUDIO_AVATAR_ENGINE = PersistentConfig(
    "AUDIO_AVATAR_ENGINE",
    "audio.avatar.engine",
    os.getenv("AUDIO_AVATAR_ENGINE", ""),
)

AUDIO_AVATAR_API_KEY = PersistentConfig(
    "AUDIO_AVATAR_API_KEY",
    "audio.avatar.api_key",
    os.getenv("AUDIO_AVATAR_API_KEY", ""),
)

AUDIO_AVATAR_REGION = PersistentConfig(
    "AUDIO_AVATAR_REGION",
    "audio.avatar.region",
    os.getenv("AUDIO_AVATAR_REGION", ""),
)

AUDIO_TTS_AZURE_AVATAR_CHARACTER = PersistentConfig(
    "AUDIO_TTS_AZURE_AVATAR_CHARACTER",
    "audio.tts.azure.avatar_character",
    os.getenv("AUDIO_TTS_AZURE_AVATAR_CHARACTER", ""),
)

AUDIO_TTS_AZURE_AVATAR_STYLE = PersistentConfig(
    "AUDIO_TTS_AZURE_AVATAR_STYLE",
    "audio.tts.azure.avatar_style",
    os.getenv("AUDIO_TTS_AZURE_AVATAR_STYLE", ""),
)

AUDIO_TTS_AZURE_AVATAR_GREETING = PersistentConfig(
    "AUDIO_TTS_AZURE_AVATAR_GREETING",
    "audio.tts.azure.avatar_greeting",
    os.getenv("AUDIO_TTS_AZURE_AVATAR_GREETING", ""),
)

####################################
# Email / Notifications
####################################

# Email Engine: "smtp" or "sendgrid"
EMAIL_ENGINE = PersistentConfig(
    "EMAIL_ENGINE",
    "email.engine",
    os.environ.get("EMAIL_ENGINE", ""),
)

# SMTP Settings
SMTP_SERVER = PersistentConfig(
    "SMTP_SERVER",
    "smtp.server",
    os.environ.get("SMTP_SERVER", ""),
)

SMTP_PORT = PersistentConfig(
    "SMTP_PORT",
    "smtp.port",
    int(os.environ.get("SMTP_PORT", "587")),
)

SMTP_USERNAME = PersistentConfig(
    "SMTP_USERNAME",
    "smtp.username",
    os.environ.get("SMTP_USERNAME", ""),
)

SMTP_PASSWORD = PersistentConfig(
    "SMTP_PASSWORD",
    "smtp.password",
    os.environ.get("SMTP_PASSWORD", ""),
)

SMTP_USE_TLS = PersistentConfig(
    "SMTP_USE_TLS",
    "smtp.use_tls",
    os.environ.get("SMTP_USE_TLS", "True").lower() == "true",
)

SMTP_USE_SSL = PersistentConfig(
    "SMTP_USE_SSL",
    "smtp.use_ssl",
    os.environ.get("SMTP_USE_SSL", "False").lower() == "true",
)

SMTP_FROM_ADDRESS = PersistentConfig(
    "SMTP_FROM_ADDRESS",
    "smtp.from_address",
    os.environ.get("SMTP_FROM_ADDRESS", ""),
)

SMTP_FROM_NAME = PersistentConfig(
    "SMTP_FROM_NAME",
    "smtp.from_name",
    os.environ.get("SMTP_FROM_NAME", "Cloosphere"),
)

# SendGrid Settings
SENDGRID_API_KEY = PersistentConfig(
    "SENDGRID_API_KEY",
    "sendgrid.api_key",
    os.environ.get("SENDGRID_API_KEY", ""),
)

SENDGRID_FROM_ADDRESS = PersistentConfig(
    "SENDGRID_FROM_ADDRESS",
    "sendgrid.from_address",
    os.environ.get("SENDGRID_FROM_ADDRESS", ""),
)

SENDGRID_FROM_NAME = PersistentConfig(
    "SENDGRID_FROM_NAME",
    "sendgrid.from_name",
    os.environ.get("SENDGRID_FROM_NAME", "Cloosphere"),
)

# Webhook Settings
WEBHOOK_PROVIDER = PersistentConfig(
    "WEBHOOK_PROVIDER",
    "webhook.provider",
    os.environ.get("WEBHOOK_PROVIDER", ""),  # "slack", "teams", "discord"
)

NOTIFICATION_EVENTS = PersistentConfig(
    "NOTIFICATION_EVENTS",
    "notifications.events",
    json.loads(os.environ.get("NOTIFICATION_EVENTS", "[]")),
)

NOTIFICATION_EMAIL_CHANNELS = PersistentConfig(
    "NOTIFICATION_EMAIL_CHANNELS",
    "notifications.email_channels",
    json.loads(os.environ.get("NOTIFICATION_EMAIL_CHANNELS", "[]")),
)

NOTIFICATION_WEBHOOK_CHANNELS = PersistentConfig(
    "NOTIFICATION_WEBHOOK_CHANNELS",
    "notifications.webhook_channels",
    json.loads(os.environ.get("NOTIFICATION_WEBHOOK_CHANNELS", "[]")),
)


####################################
# TEAMS BOT (channel connection)
####################################

TEAMS_BOT_ENABLED = PersistentConfig(
    "TEAMS_BOT_ENABLED",
    "teams_bot.enabled",
    os.environ.get("TEAMS_BOT_ENABLED", "false").strip().lower() == "true",
)

TEAMS_BOT_APP_ID = PersistentConfig(
    "TEAMS_BOT_APP_ID",
    "teams_bot.app_id",
    os.environ.get("TEAMS_BOT_APP_ID", "").strip(),
)

TEAMS_BOT_APP_PASSWORD = PersistentConfig(
    "TEAMS_BOT_APP_PASSWORD",
    "teams_bot.app_password",
    os.environ.get("TEAMS_BOT_APP_PASSWORD", "").strip(),
)

TEAMS_BOT_TENANT_ID = PersistentConfig(
    "TEAMS_BOT_TENANT_ID",
    "teams_bot.tenant_id",
    os.environ.get("TEAMS_BOT_TENANT_ID", "").strip(),
)

TEAMS_BOT_MODEL_ID = PersistentConfig(
    "TEAMS_BOT_MODEL_ID",
    "teams_bot.model_id",
    os.environ.get("TEAMS_BOT_MODEL_ID", "").strip(),
)

# Teams 매니페스트 브랜딩 — 관리자가 고객사별 이름/설명으로 커스터마이즈.
# 미설정 시 Cloosphere 기본값 사용.
TEAMS_BOT_NAME = PersistentConfig(
    "TEAMS_BOT_NAME",
    "teams_bot.name",
    os.environ.get("TEAMS_BOT_NAME", "").strip(),
)

TEAMS_BOT_DESCRIPTION_SHORT = PersistentConfig(
    "TEAMS_BOT_DESCRIPTION_SHORT",
    "teams_bot.description_short",
    os.environ.get("TEAMS_BOT_DESCRIPTION_SHORT", "").strip(),
)

TEAMS_BOT_DESCRIPTION_FULL = PersistentConfig(
    "TEAMS_BOT_DESCRIPTION_FULL",
    "teams_bot.description_full",
    os.environ.get("TEAMS_BOT_DESCRIPTION_FULL", "").strip(),
)

TEAMS_BOT_DEVELOPER_NAME = PersistentConfig(
    "TEAMS_BOT_DEVELOPER_NAME",
    "teams_bot.developer_name",
    os.environ.get("TEAMS_BOT_DEVELOPER_NAME", "").strip(),
)

TEAMS_BOT_DEVELOPER_WEBSITE = PersistentConfig(
    "TEAMS_BOT_DEVELOPER_WEBSITE",
    "teams_bot.developer_website",
    os.environ.get("TEAMS_BOT_DEVELOPER_WEBSITE", "").strip(),
)

# 아이콘은 base64 data-url (data:image/png;base64,...) 형식으로 저장.
# 미설정 시 teams_app/color.png, teams_app/outline.png 기본값 사용.
TEAMS_BOT_COLOR_ICON = PersistentConfig(
    "TEAMS_BOT_COLOR_ICON",
    "teams_bot.color_icon",
    "",
)

TEAMS_BOT_OUTLINE_ICON = PersistentConfig(
    "TEAMS_BOT_OUTLINE_ICON",
    "teams_bot.outline_icon",
    "",
)


# 전사 배포용 설정. scope 는 ["personal"], ["personal","team"], ["personal","team","groupchat"]
# 등 조합으로 지정. env 는 JSON 배열 문자열로 입력 (예: '["personal","team"]').
def _parse_teams_scopes_env() -> list[str]:
    raw = os.environ.get("TEAMS_BOT_SCOPES", "").strip()
    if not raw:
        return ["personal"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(s) for s in parsed if s]
    except Exception:
        pass
    # CSV fallback
    return [s.strip() for s in raw.split(",") if s.strip()]


TEAMS_BOT_SCOPES = PersistentConfig(
    "TEAMS_BOT_SCOPES",
    "teams_bot.scopes",
    _parse_teams_scopes_env(),
)

TEAMS_BOT_ACCENT_COLOR = PersistentConfig(
    "TEAMS_BOT_ACCENT_COLOR",
    "teams_bot.accent_color",
    os.environ.get("TEAMS_BOT_ACCENT_COLOR", "#171717").strip() or "#171717",
)

# 다중 scope 설치 시 Teams 가 기본으로 pin 할 표면. 값: "team"|"groupchat"|"meetings"|""
TEAMS_BOT_DEFAULT_GROUP_CAPABILITY = PersistentConfig(
    "TEAMS_BOT_DEFAULT_GROUP_CAPABILITY",
    "teams_bot.default_group_capability",
    os.environ.get("TEAMS_BOT_DEFAULT_GROUP_CAPABILITY", "").strip(),
)


####################################
# BRANDING
####################################

BRANDING_APP_NAME = PersistentConfig("BRANDING_APP_NAME", "branding.app_name", "")

BRANDING_FAVICON_URL = PersistentConfig(
    "BRANDING_FAVICON_URL", "branding.favicon_url", ""
)
BRANDING_FAVICON_DARK_URL = PersistentConfig(
    "BRANDING_FAVICON_DARK_URL", "branding.favicon_dark_url", ""
)
BRANDING_LOGO_URL = PersistentConfig("BRANDING_LOGO_URL", "branding.logo_url", "")
BRANDING_SPLASH_URL = PersistentConfig("BRANDING_SPLASH_URL", "branding.splash_url", "")
BRANDING_SPLASH_DARK_URL = PersistentConfig(
    "BRANDING_SPLASH_DARK_URL", "branding.splash_dark_url", ""
)
BRANDING_BROWSER_FAVICON_URL = PersistentConfig(
    "BRANDING_BROWSER_FAVICON_URL", "branding.browser_favicon_url", ""
)


####################################
# DOCUMENT TEMPLATES
####################################
# Admin-uploaded master templates inherited by document generation tools
# (extension_modules/tools/document/{pptx,docx,xlsx}_tool.py). PROFESSIONAL
# tier feature — gated via FeatureModule.DOCUMENT_TEMPLATES.
#
# Value shape (dict):
#   {
#     "version": 1,
#     "file_path": "document-templates/{kind}/{uuid}.{ext}",
#     "original_filename": "월간보고서.pptx",
#     "uploaded_at": 1700000000,
#     "uploaded_by": "user-id"
#   }
# Empty dict {} means "no template configured — fall back to built-in theme".

DOCUMENT_TEMPLATE_PPTX = PersistentConfig(
    "DOCUMENT_TEMPLATE_PPTX", "document_templates.pptx", {}
)
DOCUMENT_TEMPLATE_DOCX = PersistentConfig(
    "DOCUMENT_TEMPLATE_DOCX", "document_templates.docx", {}
)
DOCUMENT_TEMPLATE_XLSX = PersistentConfig(
    "DOCUMENT_TEMPLATE_XLSX", "document_templates.xlsx", {}
)

# ── Presenton (외부 PPT 생성 서비스) ──────────────────────────────────────────
# 별도 docker 로 뜬 Presenton 서비스 연동. 활성화 시 document_tools 의 PPT 경로가
# 내장 python-pptx(create_pptx) 대신 Presenton(create_presentation)로 대체된다.
# 자세한 배포: services/Presenton/README.md
PRESENTON_ENABLED = PersistentConfig(
    "PRESENTON_ENABLED",
    "presenton.enabled",
    os.environ.get("PRESENTON_ENABLED", "false").lower() == "true",
)
PRESENTON_BASE_URL = PersistentConfig(
    "PRESENTON_BASE_URL",
    "presenton.base_url",
    os.environ.get("PRESENTON_BASE_URL", "http://localhost:5001"),
)
# 생성 전체 폴링 budget(초). 8슬라이드+이미지는 200~350s+ 걸려 넉넉히. 운영자가 조절.
PRESENTON_TIMEOUT = PersistentConfig(
    "PRESENTON_TIMEOUT",
    "presenton.timeout",
    int(os.environ.get("PRESENTON_TIMEOUT", "600")),
)
# 에이전트가 template 미지정 시 사용할 기본 템플릿 (general/modern/standard/swift 또는 custom-<id>).
PRESENTON_DEFAULT_TEMPLATE = PersistentConfig(
    "PRESENTON_DEFAULT_TEMPLATE",
    "presenton.default_template",
    os.environ.get("PRESENTON_DEFAULT_TEMPLATE", "general"),
)


####################################
# EXTERNAL WORKER
####################################

EXTERNAL_WORKER_ENABLED = PersistentConfig(
    "EXTERNAL_WORKER_ENABLED",
    "external_worker.enabled",
    os.environ.get("EXTERNAL_WORKER_ENABLED", "False").lower() == "true",
)

EXTERNAL_WORKER_TASKS = PersistentConfig(
    "EXTERNAL_WORKER_TASKS",
    "external_worker.tasks",
    os.environ.get("EXTERNAL_WORKER_TASKS", "file_processing").split(",")
    if os.environ.get("EXTERNAL_WORKER_TASKS")
    else ["file_processing"],
)

EXTERNAL_WORKER_API_KEY = PersistentConfig(
    "EXTERNAL_WORKER_API_KEY",
    "external_worker.api_key",
    os.environ.get("EXTERNAL_WORKER_API_KEY", ""),
)
