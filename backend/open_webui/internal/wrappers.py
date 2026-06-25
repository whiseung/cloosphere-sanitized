import logging
from contextvars import ContextVar

from open_webui.env import DATABASE_SCHEMA, SRC_LOG_LEVELS
from peewee import InterfaceError as PeeWeeInterfaceError
from peewee import (
    PostgresqlDatabase,
    SqliteDatabase,
)
from playhouse.db_url import connect, parse
from playhouse.shortcuts import ReconnectMixin
from psycopg2 import InterfaceError, OperationalError

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["DB"])

db_state_default = {"closed": None, "conn": None, "ctx": None, "transactions": None}
db_state = ContextVar("db_state", default=db_state_default.copy())


class PeeweeConnectionState(object):
    def __init__(self, **kwargs):
        super().__setattr__("_state", db_state)
        super().__init__(**kwargs)

    def __setattr__(self, name, value):
        self._state.get()[name] = value

    def __getattr__(self, name):
        value = self._state.get()[name]
        return value


class CustomReconnectMixin(ReconnectMixin):
    reconnect_errors = (
        # psycopg2
        (OperationalError, "termin"),
        (InterfaceError, "closed"),
        # peewee
        (PeeWeeInterfaceError, "closed"),
    )


class ReconnectingPostgresqlDatabase(CustomReconnectMixin, PostgresqlDatabase):
    def _initialize_connection(self, conn):
        super()._initialize_connection(conn)
        # peewee 마이그레이션이 DATABASE_SCHEMA 로 테이블을 만들도록 search_path 주입
        if DATABASE_SCHEMA:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{DATABASE_SCHEMA}", ag_catalog')


def register_connection(db_url):
    db = connect(db_url, unquote_password=True)
    if isinstance(db, PostgresqlDatabase):
        # Enable autoconnect for SQLite databases, managed by Peewee
        db.autoconnect = True
        db.reuse_if_open = True
        log.info("Connected to PostgreSQL database")

        # Get the connection details
        connection = parse(db_url, unquote_password=True)

        # Use our custom database class that supports reconnection
        db = ReconnectingPostgresqlDatabase(**connection)
        db.connect(reuse_if_open=True)
    elif isinstance(db, SqliteDatabase):
        # Enable autoconnect for SQLite databases, managed by Peewee
        db.autoconnect = True
        db.reuse_if_open = True
        log.info("Connected to SQLite database")
    else:
        raise ValueError("Unsupported database connection")
    return db
