"""Unit tests for dbsphere_memory_usage model aggregation.

실제 in-memory SQLite 로 GROUP BY 집계·dbsphere 스코핑·anti-join distinct·
logging_active_since 게이트 보조를 검증한다(MagicMock 으론 SQL 의미 검증 불가).
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def usage_table(monkeypatch):
    """격리된 in-memory DB 에 바인딩된 DbsphereMemoryUsages 싱글톤을 돌려준다."""
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
    return mod.DbsphereMemoryUsages, mod.DbsphereMemoryUsageForm


def _form(FormCls, memory_id, dbsphere_id="db1", **kw):
    return FormCls(memory_id=memory_id, dbsphere_id=dbsphere_id, **kw)


def test_insert_and_count_single(usage_table):
    usages, Form = usage_table
    usages.insert_usage(
        _form(Form, "m1", user_id="u1", injection_point="system_prompt")
    )
    counts = usages.get_usage_counts("db1")
    assert counts["m1"]["use_count"] == 1
    assert counts["m1"]["last_used_at"] is not None


def test_bulk_insert_counts(usage_table):
    usages, Form = usage_table
    n = usages.insert_usage_bulk(
        [_form(Form, "m1"), _form(Form, "m1"), _form(Form, "m2")]
    )
    assert n == 3
    counts = usages.get_usage_counts("db1")
    assert counts["m1"]["use_count"] == 2
    assert counts["m2"]["use_count"] == 1


def test_dbsphere_scoping_no_bleed(usage_table):
    """다른 dbsphere 의 카운트가 누출되지 않아야 한다(M2)."""
    usages, Form = usage_table
    usages.insert_usage_bulk(
        [
            _form(Form, "m1", dbsphere_id="db1"),
            _form(Form, "m1", dbsphere_id="db2"),
            _form(Form, "m1", dbsphere_id="db2"),
        ]
    )
    assert usages.get_usage_counts("db1")["m1"]["use_count"] == 1
    assert usages.get_usage_counts("db2")["m1"]["use_count"] == 2


def test_memory_ids_filter(usage_table):
    usages, Form = usage_table
    usages.insert_usage_bulk([_form(Form, "m1"), _form(Form, "m2"), _form(Form, "m3")])
    counts = usages.get_usage_counts("db1", memory_ids=["m1", "m3"])
    assert set(counts.keys()) == {"m1", "m3"}


def test_used_memory_ids_distinct(usage_table):
    """anti-join 용 distinct 집합 — 중복 주입은 1개로."""
    usages, Form = usage_table
    usages.insert_usage_bulk([_form(Form, "m1"), _form(Form, "m1"), _form(Form, "m2")])
    used = usages.get_used_memory_ids("db1")
    assert used == {"m1", "m2"}
    # 다른 dbsphere 는 제외
    usages.insert_usage(_form(Form, "mX", dbsphere_id="db2"))
    assert usages.get_used_memory_ids("db1") == {"m1", "m2"}


def test_logging_active_since(usage_table):
    usages, Form = usage_table
    assert usages.get_logging_active_since("db1") is None  # 아직 없음 → None
    usages.insert_usage(_form(Form, "m1"))
    since = usages.get_logging_active_since("db1")
    assert isinstance(since, int) and since > 0


def test_delete_by_memory_ids(usage_table):
    usages, Form = usage_table
    usages.insert_usage_bulk([_form(Form, "m1"), _form(Form, "m2")])
    removed = usages.delete_by_memory_ids("db1", ["m1"])
    assert removed == 1
    assert usages.get_used_memory_ids("db1") == {"m2"}


def test_empty_bulk_noop(usage_table):
    usages, _ = usage_table
    assert usages.insert_usage_bulk([]) == 0
