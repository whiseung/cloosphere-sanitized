"""pytest conftest for dbsphere tests.

핵심: open_webui import 전에 DATABASE_URL 을 격리된 SQLite 로 강제 설정.
프로젝트의 .env 가 dev Azure Postgres 를 가리키고 있어, fixture 안에서 env 를
설정하면 이미 import 된 internal/db.py 가 운영 DB 를 사용하게 된다.

이 파일은 pytest 가 collection 직전에 import 하므로, module-top 코드가 모든
다른 open_webui import 보다 먼저 실행된다.
"""

from __future__ import annotations

import logging
import os
import tempfile

# ---- BEFORE any open_webui import: isolate DATABASE_URL ----
_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "pytest_dbsphere_isolated.db")
if os.path.exists(_TEST_DB_PATH):
    os.unlink(_TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
# REDIS_URL 은 그대로 (이미 로컬 Redis 가정).

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrate_isolated_db():
    """세션 시작 시 단 한 번 — alembic stamp parent + upgrade head.

    Cloosphere 의 alembic chain 일부 마이그레이션이 SQLite ALTER CONSTRAINT 를
    지원하지 않는다. 우리 마이그레이션 (aa8b9c0d1e2f) 의 parent (f0e1d2c3b4a5)
    까지 stamp 한 뒤 우리 것만 upgrade 한다.
    """
    cfg = Config("backend/open_webui/alembic.ini")
    cfg.set_main_option("script_location", "backend/open_webui/migrations")
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.stamp(cfg, "f0e1d2c3b4a5")
    command.upgrade(cfg, "head")
    yield
    # 세션 끝나면 DB 파일 정리 (다음 실행 재시작용).
    if os.path.exists(_TEST_DB_PATH):
        try:
            os.unlink(_TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _clean_per_test_state():
    """function-scope — 매 테스트 종료 시 격리 SQLite 의 dbsphere_sql_file +
    audit_log 테이블 truncate. orphan finder 테스트가 audit_log 를 직접 쓰므로
    cross-test leak 방지 필수.
    """
    yield
    try:
        from open_webui.internal.db import get_db
        from open_webui.models.audit_log import AuditLog
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFile

        with get_db() as db:
            db.query(DbSphereSqlFile).delete()
            db.query(AuditLog).delete()
            db.commit()
    except Exception as e:
        # Log instead of silent-swallow so cross-test pollution is diagnosable.
        logging.getLogger(__name__).warning("Test teardown cleanup failed: %s", e)
