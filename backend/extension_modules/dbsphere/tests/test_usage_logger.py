"""Tests for the fire-and-forget memory usage logger."""

import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def usage_db(monkeypatch):
    import open_webui.models.dbsphere_memory_usage as mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    mod.DbsphereMemoryUsage.__table__.create(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    @contextmanager
    def fake_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(mod, "get_db", fake_get_db)
    return mod.DbsphereMemoryUsages


def test_no_running_loop_is_noop():
    """동기 컨텍스트(러닝 루프 없음)에서 호출해도 예외 없이 no-op."""
    from extension_modules.dbsphere.memory import usage_logger

    # 예외가 나지 않아야 한다.
    usage_logger.record_memory_references(dbsphere_id="db1", memory_ids=["m1", "m2"])
    assert len(usage_logger._pending_tasks) == 0


def test_empty_ids_noop():
    from extension_modules.dbsphere.memory import usage_logger

    usage_logger.record_memory_references(dbsphere_id="db1", memory_ids=[])
    usage_logger.record_memory_references(dbsphere_id="", memory_ids=["m1"])
    assert len(usage_logger._pending_tasks) == 0


@pytest.mark.asyncio
async def test_records_within_loop(usage_db):
    from extension_modules.dbsphere.memory import usage_logger

    usage_logger.record_memory_references(
        dbsphere_id="db1",
        memory_ids=["m1", "m1", "m2"],
        user_id="u1",
        chat_id="c1",
        injection_point="system_prompt",
    )
    # fire-and-forget — 호출은 즉시 반환하고 task 가 스케줄됨.
    assert len(usage_logger._pending_tasks) == 1
    # 백그라운드 task 완료 대기.
    await asyncio.gather(*list(usage_logger._pending_tasks))

    counts = usage_db.get_usage_counts("db1")
    assert counts["m1"]["use_count"] == 2
    assert counts["m2"]["use_count"] == 1
    # 완료 후 핸들 정리(GC 안전).
    assert len(usage_logger._pending_tasks) == 0
