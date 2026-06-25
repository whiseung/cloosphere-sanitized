import json
import logging
from contextlib import contextmanager
from typing import Any, Optional

from open_webui.env import (
    DATABASE_POOL_MAX_OVERFLOW,
    DATABASE_POOL_RECYCLE,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT,
    DATABASE_SCHEMA,
    DATABASE_URL,
    OPEN_WEBUI_DIR,
    SRC_LOG_LEVELS,
)
from open_webui.internal.wrappers import register_connection
from peewee_migrate import Router
from sqlalchemy import Dialect, MetaData, create_engine, event, types
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.sql.type_api import _T
from typing_extensions import Self

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["DB"])


class JSONField(types.TypeDecorator):
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value: Optional[_T], dialect: Dialect) -> Any:
        return json.dumps(value)

    def process_result_value(self, value: Optional[_T], dialect: Dialect) -> Any:
        if value is not None:
            return json.loads(value)

    def copy(self, **kw: Any) -> Self:
        return JSONField(self.impl.length)

    def db_value(self, value):
        return json.dumps(value)

    def python_value(self, value):
        if value is not None:
            return json.loads(value)


# Workaround to handle the peewee migration
# This is required to ensure the peewee migration is handled before the alembic migration
def handle_peewee_migration(DATABASE_URL):
    db = None
    try:
        # Replace the postgresql:// with postgres:// to handle the peewee migration
        db = register_connection(DATABASE_URL.replace("postgresql://", "postgres://"))
        migrate_dir = OPEN_WEBUI_DIR / "internal" / "migrations"
        router = Router(db, logger=log, migrate_dir=migrate_dir)
        router.run()
        db.close()

    except Exception as e:
        # Multi-worker 환경에서 동시에 마이그레이션 실행 시 duplicate key 에러 발생 가능
        # 다른 워커가 이미 처리했으므로 무시하고 계속 진행
        if "duplicate key" in str(e) or "already exists" in str(e):
            log.warning(
                f"Peewee migration skipped (likely handled by another worker): {e}"
            )
        else:
            log.error(f"Failed to initialize the database connection: {e}")
            raise
    finally:
        # Properly closing the database connection
        if db and not db.is_closed():
            db.close()

        # Assert if db connection has been closed
        assert db.is_closed(), "Database connection is still open."


def _ensure_database_schema(database_url: str, schema: Optional[str]) -> None:
    """PostgreSQL 비-default 스키마 사용 시 스키마가 존재하도록 보장.

    peewee/alembic 마이그레이션이 `search_path` 를 쓰므로,
    그 전에 타겟 스키마가 반드시 존재해야 한다.
    """
    if not schema or "postgres" not in database_url:
        return
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        conn.close()


_ensure_database_schema(DATABASE_URL, DATABASE_SCHEMA)
handle_peewee_migration(DATABASE_URL)


SQLALCHEMY_DATABASE_URL = DATABASE_URL
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    if DATABASE_POOL_SIZE > 0:
        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_POOL_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT,
            pool_recycle=DATABASE_POOL_RECYCLE,
            pool_pre_ping=True,
            poolclass=QueuePool,
        )
    else:
        engine = create_engine(
            SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool
        )

# 비-default 스키마 사용 시 모든 PostgreSQL 커넥션에 search_path 주입.
# `ag_catalog` 는 Apache AGE 확장이 고정 스키마라 항상 포함.
if DATABASE_SCHEMA and "postgres" in SQLALCHEMY_DATABASE_URL:

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _connection_record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute(f'SET search_path TO "{DATABASE_SCHEMA}", ag_catalog')
        finally:
            cur.close()


SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)
metadata_obj = MetaData(schema=DATABASE_SCHEMA)
Base = declarative_base(metadata=metadata_obj)
Session = scoped_session(SessionLocal)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


get_db = contextmanager(get_session)
