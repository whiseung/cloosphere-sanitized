"""Unit tests for DbSphere SQL-memory hygiene (#1 tenant isolation + #2 dedup).

Post-fetch 격리/collapse 로직과 dedup keying 은 순수 함수로 추출돼 mock SearchResult
만으로 검증한다 (live search engine 불필요).
"""

from extension_modules.dbsphere.memory.search_memory import (
    SCHEMA_EXTRACTION_SOURCE,
    _apply_sql_memory_policy,
    _sql_memory_row_visible,
    compute_sql_memory_dedup_key,
)
from extension_modules.search_engine.models import SearchResult


def _sr(
    rid: str,
    question: str,
    sql: str,
    *,
    score: float = 0.9,
    user_id=None,
    source=None,
    success: bool = True,
    with_dedup_key: bool = True,
    with_success: bool = True,
) -> SearchResult:
    """mock SQL_MEMORY SearchResult."""
    md = {
        "entity_type": "sql_memory",
        "sql_query": sql,
        "user_id": user_id,
        "source": source,
    }
    if with_success:
        md["success"] = success
    if with_dedup_key:
        md["dedup_key"] = compute_sql_memory_dedup_key(question, sql)
    return SearchResult(id=rid, content=question, score=score, metadata=md)


class TestDedupKey:
    """#2 dedup identity = (정규화 질문, 정확한 SQL) — 결정 D4."""

    def test_identical_question_and_sql_same_key(self):
        k1 = compute_sql_memory_dedup_key("Show top customers", "SELECT * FROM c")
        k2 = compute_sql_memory_dedup_key("Show top customers", "SELECT * FROM c")
        assert k1 == k2

    def test_question_casing_and_whitespace_collapse(self):
        k1 = compute_sql_memory_dedup_key("  Show  TOP customers ", "SELECT 1")
        k2 = compute_sql_memory_dedup_key("show top customers", "SELECT 1")
        assert k1 == k2

    def test_different_sql_distinct_key(self):
        # 같은 질문, 다른 SQL → 별개 variant 보존.
        k1 = compute_sql_memory_dedup_key("top customers", "SELECT * FROM c LIMIT 10")
        k2 = compute_sql_memory_dedup_key("top customers", "SELECT * FROM c LIMIT 5")
        assert k1 != k2

    def test_different_question_distinct_key(self):
        k1 = compute_sql_memory_dedup_key("top customers", "SELECT 1")
        k2 = compute_sql_memory_dedup_key("bottom customers", "SELECT 1")
        assert k1 != k2

    def test_sql_outer_whitespace_trimmed(self):
        k1 = compute_sql_memory_dedup_key("q", "  SELECT 1  ")
        k2 = compute_sql_memory_dedup_key("q", "SELECT 1")
        assert k1 == k2

    def test_sql_inner_difference_preserved(self):
        # 내부 SQL 차이는 보존 (정규화 안 함 — exact).
        k1 = compute_sql_memory_dedup_key("q", "SELECT a,b FROM t")
        k2 = compute_sql_memory_dedup_key("q", "SELECT a, b FROM t")
        assert k1 != k2

    def test_stable_hex_digest(self):
        assert len(compute_sql_memory_dedup_key("q", "SELECT 1")) == 64


class TestRowVisible:
    """#1 격리 술어 — admin | 본인 | schema_extraction."""

    def test_admin_sees_everything(self):
        assert _sql_memory_row_visible(
            {"user_id": "userA"}, requester_user_id="userB", is_admin=True
        )

    def test_owner_sees_own(self):
        assert _sql_memory_row_visible(
            {"user_id": "userB"}, requester_user_id="userB", is_admin=False
        )

    def test_non_owner_blocked(self):
        assert not _sql_memory_row_visible(
            {"user_id": "userA"}, requester_user_id="userB", is_admin=False
        )

    def test_schema_extraction_visible_to_all(self):
        # schema 샘플 Q&A 는 admin A 가 추출했어도 공유 스키마 지식 → B 가 봄.
        assert _sql_memory_row_visible(
            {"user_id": "adminA", "source": SCHEMA_EXTRACTION_SOURCE},
            requester_user_id="userB",
            is_admin=False,
        )

    def test_legacy_null_user_hidden_from_non_admin(self):
        assert not _sql_memory_row_visible(
            {"user_id": None}, requester_user_id="userB", is_admin=False
        )


class TestPostFetchPolicy:
    """#1 격리 + success + threshold + #2 dedup 통합 (post-fetch)."""

    def _policy(self, results, **kw):
        kw.setdefault("requester_user_id", "userB")
        kw.setdefault("is_admin", False)
        kw.setdefault("similarity_threshold", 0.5)
        kw.setdefault("limit", 5)
        return _apply_sql_memory_policy(results, **kw)

    def test_user_b_does_not_see_user_a_rows(self):
        results = [
            _sr("1", "q1", "SELECT 1", user_id="userA"),
            _sr("2", "q2", "SELECT 2", user_id="userB"),
        ]
        out = self._policy(results)
        assert [r.memory.memory_id for r in out] == ["2"]

    def test_admin_sees_both(self):
        results = [
            _sr("1", "q1", "SELECT 1", user_id="userA"),
            _sr("2", "q2", "SELECT 2", user_id="userB"),
        ]
        out = self._policy(results, is_admin=True)
        assert {r.memory.memory_id for r in out} == {"1", "2"}

    def test_schema_extraction_row_surfaces_for_other_user(self):
        results = [
            _sr(
                "1", "q1", "SELECT 1", user_id="adminA", source=SCHEMA_EXTRACTION_SOURCE
            ),
            _sr("2", "q2", "SELECT 2", user_id="userA"),
        ]
        out = self._policy(results)
        assert [r.memory.memory_id for r in out] == ["1"]

    def test_failed_sql_excluded_from_few_shot(self):
        results = [
            _sr("1", "q1", "SELECT 1", user_id="userB", success=False),
            _sr("2", "q2", "SELECT 2", user_id="userB", success=True),
        ]
        out = self._policy(results)
        assert [r.memory.memory_id for r in out] == ["2"]

    def test_legacy_missing_success_treated_as_success(self):
        results = [_sr("1", "q1", "SELECT 1", user_id="userB", with_success=False)]
        out = self._policy(results)
        assert [r.memory.memory_id for r in out] == ["1"]

    def test_threshold_cut(self):
        results = [
            _sr("1", "q1", "SELECT 1", user_id="userB", score=0.3),
            _sr("2", "q2", "SELECT 2", user_id="userB", score=0.8),
        ]
        out = self._policy(results, similarity_threshold=0.5)
        assert [r.memory.memory_id for r in out] == ["2"]

    def test_limit_respected_and_ranked(self):
        results = [
            _sr(str(i), f"q{i}", f"SELECT {i}", user_id="userB") for i in range(10)
        ]
        out = self._policy(results, limit=3)
        assert len(out) == 3
        assert [r.rank for r in out] == [1, 2, 3]

    def test_dedup_collapse_same_question_sql(self):
        # 같은 질문+SQL 3회 → 1개로 collapse (최초/최고 score 유지).
        results = [
            _sr("1", "top customers", "SELECT * FROM c", user_id="userB", score=0.95),
            _sr("2", "top customers", "SELECT * FROM c", user_id="userB", score=0.90),
            _sr("3", "TOP  customers", "SELECT * FROM c", user_id="userB", score=0.85),
        ]
        out = self._policy(results)
        assert len(out) == 1
        assert out[0].memory.memory_id == "1"

    def test_dedup_preserves_distinct_sql(self):
        results = [
            _sr("1", "top customers", "SELECT * FROM c LIMIT 10", user_id="userB"),
            _sr("2", "top customers", "SELECT * FROM c LIMIT 5", user_id="userB"),
        ]
        out = self._policy(results)
        assert len(out) == 2

    def test_dedup_recompute_when_key_absent(self):
        # legacy row (dedup_key 없음) 도 question+sql 재계산으로 collapse.
        results = [
            _sr("1", "q", "SELECT 1", user_id="userB", with_dedup_key=False),
            _sr("2", "q", "SELECT 1", user_id="userB", with_dedup_key=False),
        ]
        out = self._policy(results)
        assert len(out) == 1


# --- #2 save-upsert (mock engine) ---------------------------------------------
import contextlib  # noqa: E402

from extension_modules.dbsphere.memory.search_memory import (  # noqa: E402
    SearchEngineDbSphereMemory,
    _sql_memory_doc_id,
)


class _FakeEngine:
    def __init__(self):
        self.store = {}
        self.embed_calls = 0
        self.update_calls = 0
        self.insert_calls = 0

    async def index_exists(self):
        return True

    async def get(self, ids):
        return [self.store[i] for i in ids if i in self.store]

    async def update(self, docs):
        for d in docs:
            self.store[d.id] = d
        self.update_calls += 1
        return len(docs)

    async def insert(self, docs):
        for d in docs:
            self.store[d.id] = d
        self.insert_calls += 1
        return len(docs)


def _make_memory(engine, user_id="userB"):
    mem = SearchEngineDbSphereMemory(app=None, dbsphere_id="db1", user_id=user_id)
    mem._get_engine = lambda: engine

    @contextlib.asynccontextmanager
    async def _ctx(_e):
        yield engine

    mem._engine_ctx = _ctx

    async def _ensure(_e):
        return True

    mem._ensure_index_exists = _ensure

    async def _embed(_text):
        engine.embed_calls += 1
        return [0.1, 0.2, 0.3]

    mem._create_embedding = _embed
    return mem


class TestDocId:
    def test_deterministic(self):
        k = compute_sql_memory_dedup_key("q", "SELECT 1")
        assert _sql_memory_doc_id("db1", k) == _sql_memory_doc_id("db1", k)

    def test_distinct_per_dbsphere(self):
        k = compute_sql_memory_dedup_key("q", "SELECT 1")
        assert _sql_memory_doc_id("db1", k) != _sql_memory_doc_id("db2", k)


class TestSaveUpsert:
    async def test_same_question_sql_upserts_single_row(self):
        eng = _FakeEngine()
        mem = _make_memory(eng)
        r1 = await mem.save_sql_memory(
            "top customers", "SELECT * FROM c", metadata={"user_id": "userB"}
        )
        r2 = await mem.save_sql_memory(
            "top customers", "SELECT * FROM c", metadata={"user_id": "userB"}
        )
        assert r1.memory_id == r2.memory_id  # 결정적 id
        assert len(eng.store) == 1  # 단일 row
        assert eng.embed_calls == 1  # 2번째는 short-circuit
        assert eng.insert_calls == 0  # upsert 경로(update)

    async def test_normalized_question_collapses(self):
        eng = _FakeEngine()
        mem = _make_memory(eng)
        await mem.save_sql_memory(
            "Top  Customers", "SELECT 1", metadata={"user_id": "u"}
        )
        await mem.save_sql_memory(
            "top customers", "SELECT 1", metadata={"user_id": "u"}
        )
        assert len(eng.store) == 1

    async def test_distinct_sql_two_rows(self):
        eng = _FakeEngine()
        mem = _make_memory(eng)
        await mem.save_sql_memory("q", "SELECT 1", metadata={"user_id": "u"})
        await mem.save_sql_memory("q", "SELECT 2", metadata={"user_id": "u"})
        assert len(eng.store) == 2

    async def test_seam_fields_persisted(self):
        eng = _FakeEngine()
        mem = _make_memory(eng)
        await mem.save_sql_memory(
            "q",
            "SELECT 1",
            success=False,
            metadata={"user_id": "u", "source": "schema_extraction"},
        )
        doc = next(iter(eng.store.values()))
        assert doc.metadata["success"] is False
        assert doc.metadata["source"] == "schema_extraction"
        assert doc.metadata["dedup_key"]
        assert doc.metadata["user_id"] == "u"


class TestRequesterAdmin:
    """#1 admin bypass resolve — fail-closed(예외→격리 적용) 보장."""

    def _mem(self, user_id="userB"):
        return SearchEngineDbSphereMemory(app=None, dbsphere_id="db1", user_id=user_id)

    def test_empty_user_id_not_admin(self):
        assert self._mem(user_id="")._requester_is_admin() is False

    def test_admin_role_true(self, monkeypatch):
        class _U:
            role = "admin"

        monkeypatch.setattr(
            "open_webui.models.users.Users.get_user_by_id", lambda uid: _U()
        )
        assert self._mem()._requester_is_admin() is True

    def test_non_admin_role_false(self, monkeypatch):
        class _U:
            role = "user"

        monkeypatch.setattr(
            "open_webui.models.users.Users.get_user_by_id", lambda uid: _U()
        )
        assert self._mem()._requester_is_admin() is False

    def test_lookup_exception_fails_closed(self, monkeypatch):
        def _raise(uid):
            raise RuntimeError("db down")

        monkeypatch.setattr("open_webui.models.users.Users.get_user_by_id", _raise)
        # 예외 시 admin 아님으로 처리 → 격리 적용(누수 방지).
        assert self._mem()._requester_is_admin() is False
