"""PR4 — search_engine perf/config (P0 stabilization).

T4.1 pgvector concurrency: the hybrid ``search`` (vector + text) and the
``multi_vector_search`` 3-way (primary + secondary + text) sub-searches must run
CONCURRENTLY via ``asyncio.gather``, not sequentially. Each sub-search acquires
its own pooled connection (max_size=10), so concurrency is safe and removes the
serialized-await latency.

T4.1b pgvector pool lazy-init race: ``_get_pool`` must create the asyncpg pool
EXACTLY ONCE when N coroutines hit it concurrently (double-checked locking under
``_pool_lock``). Without the lock all N pass the ``if self._pool is None`` check
before the first ``await create_pool`` resolves -> N pools created ->
connection amplification + leaked pools.

T4.2 reranker ADC: ``VertexRanker`` already resolves project + client through
Application Default Credentials when no service_account_key is supplied (existing
ADC tests cover the live path). Here we pin the no-SA-key contract.

The engine is built via ``__new__`` to bypass the DB-connecting ``__init__`` and
the sub-searches are replaced with concurrency-tracking stubs, so the test needs
no Postgres/pgvector instance.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from extension_modules.search_engine.dbs.pgvector import PgVectorEngine


def _concurrency_tracker():
    """Return (state, stub). ``stub`` records peak simultaneous in-flight calls.

    Under asyncio.gather all stubs enter (incrementing ``active``) before any
    finishes its ``sleep``, so ``max`` reaches the number of gathered coros.
    Under sequential ``await`` each stub fully completes before the next starts,
    so ``max`` never exceeds 1.
    """
    state = {"active": 0, "max": 0}

    async def stub(*args, **kwargs):
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        await asyncio.sleep(0.02)  # yield so concurrent coros can enter
        state["active"] -= 1
        return []

    return state, stub


async def test_hybrid_search_runs_vector_and_text_concurrently():
    state, stub = _concurrency_tracker()

    engine = PgVectorEngine.__new__(PgVectorEngine)  # bypass DB-connecting __init__
    engine.embedding_config = None
    engine._reranker = None
    engine._vector_search = stub
    engine._text_search = stub
    engine._rrf_merge = lambda **kw: []

    query = SimpleNamespace(query="q", top_k=5, filter=None, reranker_threshold=0.0)
    await engine.search(query, query_vector=[0.1, 0.2, 0.3])

    assert state["max"] == 2, (
        f"vector/text search not concurrent (peak in-flight={state['max']}, "
        "expected 2 — gather missing?)"
    )


async def test_multi_vector_search_runs_three_searches_concurrently():
    state, stub = _concurrency_tracker()

    engine = PgVectorEngine.__new__(PgVectorEngine)
    engine.embedding_config = None
    engine._reranker = None
    engine.config = SimpleNamespace(secondary_vector_field="secondary_vector")
    engine._vector_search = stub
    engine._secondary_vector_search = stub
    engine._text_search = stub
    engine._weighted_rrf_merge = lambda **kw: []

    await engine.multi_vector_search(
        text="q",
        vector=[0.1],
        secondary_vector=[0.2],
        top_k=5,
        filter_expr=None,
    )

    assert state["max"] == 3, (
        f"3-way search not concurrent (peak in-flight={state['max']}, "
        "expected 3 — gather missing?)"
    )


async def test_get_pool_creates_single_pool_under_concurrent_access(monkeypatch):
    """T4.1b race fix: N concurrent ``_get_pool`` calls create the pool once.

    Mocks ``asyncpg.create_pool`` with a counting stub that yields mid-creation
    (widening the check->assign window). Without the double-checked lock the
    counter would reach N; with it, exactly 1. Pins the core PR4 fix that has no
    other regression guard.
    """
    import asyncpg

    create_calls = {"n": 0}

    async def fake_create_pool(*args, **kwargs):
        create_calls["n"] += 1
        await asyncio.sleep(0.02)  # yield so racing coros enter the None-check
        return SimpleNamespace(_sentinel="pool")

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)

    engine = PgVectorEngine.__new__(PgVectorEngine)  # bypass DB-connecting __init__
    engine._pool = None
    engine._pool_lock = asyncio.Lock()
    engine.host = engine.port = engine.database = engine.user = engine.password = None

    pools = await asyncio.gather(*[engine._get_pool() for _ in range(8)])

    assert create_calls["n"] == 1, (
        f"pool created {create_calls['n']}× under concurrent _get_pool "
        "(expected 1 — lazy-init double-checked lock missing?)"
    )
    assert all(p is pools[0] for p in pools), (
        "concurrent callers received different pool objects"
    )


def test_vertex_ranker_supports_adc_without_service_account_key():
    """T4.2: a VertexRanker built with no service_account_key relies on ADC.

    Project resolves from explicit config (or, in production, from the ADC
    default project / service account key) — no key file is required.
    """
    from extension_modules.search_engine.reranker.vertex_ranker import VertexRanker

    ranker = VertexRanker(project_id="proj-x")
    assert ranker.service_account_key is None
    assert ranker._resolve_project_id() == "proj-x"
