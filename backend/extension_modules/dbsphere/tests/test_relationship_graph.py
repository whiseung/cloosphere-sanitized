"""Unit tests for save_documentation deterministic-id upsert (Option C E1 dep).

The relationship doc itself moved to ``dbsphere.data["join_graph"]`` under Option
C (``_save_relationship_graph`` removed); the relationship builder / orchestrator
tests now live in ``test_join_graph_recompute.py``. This file keeps only the
deterministic-id upsert semantics that the relationship doc relied on and that
the E1 fixed-id purge (``delete_relationship_graph_doc``) depends on.

전략: 엔진을 id-keyed FakeStore 로 치환해 upsert 시맨틱(azure merge_or_upload /
pg ON CONFLICT / es index by _id)을 모델 — dict no-op mock 금지.
"""

from __future__ import annotations

from extension_modules.dbsphere.memory.search_memory import SearchEngineDbSphereMemory


# ---------------------------------------------------------------------------
# save_documentation deterministic-id upsert
# ---------------------------------------------------------------------------
class FakeStore:
    """id-keyed 문서 store — 엔진 upsert 시맨틱 모델.

    update = merge_or_upload(고정 id 덮어쓰기/생성), insert = id 로 set
    (uuid 면 매번 다른 id → 누적 = 기존 버그 재현).
    """

    def __init__(self):
        self.docs: dict = {}
        self.insert_calls = 0
        self.update_calls = 0

    async def insert(self, documents):
        self.insert_calls += 1
        for d in documents:
            self.docs[d.id] = d
        return len(documents)

    async def update(self, documents):
        self.update_calls += 1
        for d in documents:
            self.docs[d.id] = d
        return len(documents)


async def _fake_emb(text):
    return [0.0] * 8


def _doc_memory():
    mem = SearchEngineDbSphereMemory(
        app=None, dbsphere_id="ds1", embedding_func=_fake_emb
    )
    mem._session_active = True  # _engine_ctx → no-op
    store = FakeStore()
    mem._engine = store

    async def _noop(engine):
        return True

    mem._ensure_index_exists = _noop
    return mem, store


async def test_documentation_fixed_id_is_idempotent():
    """memory_id 고정 → 2회 저장 후 store 에 1 doc(update upsert)."""
    mem, store = _doc_memory()
    for _ in range(2):
        await mem.save_documentation(
            content="rel graph",
            doc_type="context",
            title="JOIN Guide",
            memory_id="ds1__relationship_graph",
        )
    assert store.update_calls == 2
    assert store.insert_calls == 0
    assert len(store.docs) == 1
    assert "ds1__relationship_graph" in store.docs


async def test_documentation_without_id_keeps_insert_uuid_behavior():
    """memory_id 미지정 → 기존 동작(uuid + insert) 하위호환 유지."""
    mem, store = _doc_memory()
    for _ in range(2):
        await mem.save_documentation(content="ad hoc note", doc_type="rule")
    assert store.insert_calls == 2
    assert store.update_calls == 0
    assert len(store.docs) == 2  # uuid → 누적(기존 동작)
