"""LangGraph checkpointer 싱글톤.

DATABASE_URL 에 따라 AsyncPostgresSaver / AsyncSqliteSaver 중 하나를 사용.
HITL interrupt-resume 흐름이 thread_id 기반으로 그래프 state 를 복구할 때 필요.

수명 주기:
    - lifespan startup 에서 init_checkpointer(app) 호출 → setup() (테이블 생성)
    - app.state.checkpointer 로 노출
    - lifespan shutdown 에서 close_checkpointer(app) 호출 → pool/conn 정리

SQLite 는 메인 webui.db 와 분리된 별도 파일을 사용한다 (alembic verify_schema_state 가
unknown 테이블을 보고 경고하지 않도록).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI
from open_webui.env import DATA_DIR, DATABASE_SCHEMA, DATABASE_URL

log = logging.getLogger(__name__)


_pg_pool = None  # AsyncConnectionPool, postgres 모드에서만
_sqlite_conn = None  # aiosqlite Connection, sqlite 모드에서만


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgres://")


async def init_checkpointer(app: FastAPI) -> None:
    """Lifespan startup 에서 호출. app.state.checkpointer 를 세팅한다."""
    global _pg_pool, _sqlite_conn

    if _is_postgres(DATABASE_URL):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        kwargs = {
            "autocommit": True,  # AsyncPostgresSaver 요구사항
            "prepare_threshold": 0,
            "row_factory": _dict_row(),
        }
        if DATABASE_SCHEMA:
            kwargs["options"] = f"-c search_path={DATABASE_SCHEMA}"

        _pg_pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=10,
            kwargs=kwargs,
            open=False,
            # 체크아웃 시 커넥션 생존 probe — idle/failover/NAT 로 server-side 에서
            # 끊긴 half-open 커넥션을 미리 폐기·교체. 없으면 죽은 커넥션을 그대로
            # 넘겨 "consuming input failed: SSL error: unexpected eof while reading" 발생.
            check=AsyncConnectionPool.check_connection,
            # base 커넥션(min_size=1)은 max_idle 로 안 줄어드므로 수명 상한으로 보조 recycle.
            max_lifetime=600.0,
        )
        await _pg_pool.open(wait=True)

        checkpointer = AsyncPostgresSaver(_pg_pool)
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        log.info(
            "[checkpointer] AsyncPostgresSaver ready (schema=%s)",
            DATABASE_SCHEMA or "public",
        )
        return

    # SQLite (default fallback)
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = DATA_DIR / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _sqlite_conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(_sqlite_conn)
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    log.info("[checkpointer] AsyncSqliteSaver ready (path=%s)", db_path)


async def close_checkpointer(app: FastAPI) -> None:
    """Lifespan shutdown 에서 호출."""
    global _pg_pool, _sqlite_conn

    if _pg_pool is not None:
        try:
            await _pg_pool.close()
        except Exception as e:
            log.warning("[checkpointer] postgres pool close failed: %s", e)
        _pg_pool = None

    if _sqlite_conn is not None:
        try:
            await _sqlite_conn.close()
        except Exception as e:
            log.warning("[checkpointer] sqlite conn close failed: %s", e)
        _sqlite_conn = None

    if hasattr(app.state, "checkpointer"):
        delattr(app.state, "checkpointer")


def get_checkpointer(app: FastAPI) -> Optional[object]:
    """편의 접근자. UnifiedAgent 등에서 사용."""
    return getattr(app.state, "checkpointer", None)


def _dict_row():
    """psycopg dict_row factory (lazy import)."""
    from psycopg.rows import dict_row

    return dict_row
