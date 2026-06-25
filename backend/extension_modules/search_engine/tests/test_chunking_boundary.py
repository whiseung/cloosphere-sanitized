"""Adapter chunking boundary + partial-failure 회귀 테스트.

대용량 doc list 가 들어왔을 때 Azure/Elasticsearch adapter 가:

1. ``BATCH_SIZE`` (=500) 단위로 정확히 분할 호출하는지
2. 각 batch 의 ``succeeded`` 누적합을 caller 에게 반환하는지
3. 부분 실패 시 warning 로그를 남기는지

regression fixture. 1686 entries / payload-too-large 케이스(fix/glossary-bulk-indexing)
의 결정 산물.
"""

from __future__ import annotations

from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from extension_modules.search_engine.dbs.azure_search import (
    _AZURE_BATCH_SIZE,
    AzureSearchEngine,
)
from extension_modules.search_engine.dbs.elasticsearch import (
    _ES_BATCH_SIZE,
    ElasticsearchEngine,
)
from extension_modules.search_engine.models import (
    AzureSearchConfig,
    DocumentItem,
    ElasticsearchConfig,
    IndexConfig,
)

# ── 공용 fixture ────────────────────────────────────────────────────────────


def _make_docs(n: int) -> List[DocumentItem]:
    return [DocumentItem(id=f"doc_{i}", content=f"text_{i}") for i in range(n)]


def _azure_engine() -> AzureSearchEngine:
    return AzureSearchEngine(
        config=IndexConfig(index_name="test-index"),
        engine_config=AzureSearchConfig(endpoint="https://example", api_key="k"),
    )


def _es_engine() -> ElasticsearchEngine:
    return ElasticsearchEngine(
        config=IndexConfig(index_name="test-index"),
        engine_config=ElasticsearchConfig(url="http://localhost:9200"),
    )


def _azure_result(batch_size: int, fail_indexes: tuple = ()):
    """``IndexingResult`` like 객체 list 반환. succeeded=True/False 만 흉내."""
    items = []
    for i in range(batch_size):
        item = MagicMock()
        item.succeeded = i not in fail_indexes
        item.key = f"doc_{i}"
        items.append(item)
    return items


def _es_bulk_result(
    batch_size: int, action: str, success_result: str, fail_indexes: tuple = ()
) -> dict:
    """ES bulk response 흉내. action='index' or 'delete'."""
    items = []
    for i in range(batch_size):
        if i in fail_indexes:
            items.append({action: {"_id": f"doc_{i}", "error": {"type": "x"}}})
        else:
            items.append({action: {"_id": f"doc_{i}", "result": success_result}})
    return {"items": items}


# ── Azure: chunk boundary ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "total,expected_batches",
    [
        (0, 0),  # empty
        (1, 1),
        (_AZURE_BATCH_SIZE - 1, 1),  # 499
        (_AZURE_BATCH_SIZE, 1),  # 500 (정확 boundary)
        (_AZURE_BATCH_SIZE + 1, 2),  # 501
        (_AZURE_BATCH_SIZE * 2, 2),  # 1000
        (1686, 17),  # 100 단위 분할 → 17 batches — 실측 reproducer
    ],
)
async def test_azure_update_chunks_by_batch_size(total, expected_batches):
    engine = _azure_engine()
    client = MagicMock()
    client.merge_or_upload_documents = AsyncMock(
        side_effect=lambda documents: _azure_result(len(documents))
    )
    with patch.object(engine, "_get_search_client", return_value=client):
        count = await engine.update(_make_docs(total))

    assert count == total
    assert client.merge_or_upload_documents.await_count == expected_batches
    # 각 batch 의 doc 수가 BATCH_SIZE 이하임을 검증
    for call in client.merge_or_upload_documents.await_args_list:
        kw = call.kwargs.get("documents") or call.args[0]
        assert len(kw) <= _AZURE_BATCH_SIZE


@pytest.mark.asyncio
async def test_azure_insert_chunks_same_as_update():
    engine = _azure_engine()
    client = MagicMock()
    client.upload_documents = AsyncMock(
        side_effect=lambda documents: _azure_result(len(documents))
    )
    with patch.object(engine, "_get_search_client", return_value=client):
        count = await engine.insert(_make_docs(1686))
    assert count == 1686
    assert client.upload_documents.await_count == 17


@pytest.mark.asyncio
async def test_azure_delete_chunks_by_count_limit():
    """delete 페이로드는 작지만 1000 count limit 동일 — chunking 적용."""
    engine = _azure_engine()
    client = MagicMock()
    client.delete_documents = AsyncMock(
        side_effect=lambda documents: _azure_result(len(documents))
    )
    with patch.object(engine, "_get_search_client", return_value=client):
        count = await engine.delete([f"doc_{i}" for i in range(1500)])
    assert count == 1500
    assert client.delete_documents.await_count == 15  # 100 단위 → 15 batches


# ── Azure: partial failure ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_azure_update_partial_failure_returns_succeeded_count(caplog):
    """첫 batch 3개 fail → count = 500-3=497, batch 1 정상 → 총 997. warning 발생."""
    engine = _azure_engine()
    client = MagicMock()

    call_count = {"n": 0}

    def fake_call(documents):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _azure_result(len(documents), fail_indexes=(0, 1, 2))
        return _azure_result(len(documents))

    client.merge_or_upload_documents = AsyncMock(side_effect=fake_call)

    with patch.object(engine, "_get_search_client", return_value=client):
        with caplog.at_level("WARNING"):
            count = await engine.update(_make_docs(1000))

    assert count == 1000 - 3
    assert any(
        "AZURE_SEARCH" in rec.message and "partial fail" in rec.message
        for rec in caplog.records
    )


# ── Elasticsearch: chunk boundary ───────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "total,expected_batches",
    [
        (0, 0),
        (1, 1),
        (_ES_BATCH_SIZE, 1),
        (_ES_BATCH_SIZE + 1, 2),
        (1686, 4),
    ],
)
async def test_es_update_chunks_by_batch_size(total, expected_batches):
    engine = _es_engine()
    client = MagicMock()
    client.bulk = AsyncMock(
        side_effect=lambda operations, refresh: _es_bulk_result(
            len(operations) // 2,  # bulk operations 은 (header, body) pair
            "index",
            "created",
        )
    )
    with patch.object(engine, "_get_client", return_value=client):
        count = await engine.update(_make_docs(total))

    assert count == total
    assert client.bulk.await_count == expected_batches


@pytest.mark.asyncio
async def test_es_update_excludes_noop_from_count():
    """noop result 는 'created'/'updated' 아니므로 카운트에서 제외 (semantic 일관성)."""
    engine = _es_engine()
    client = MagicMock()

    def fake_bulk(operations, refresh):
        n = len(operations) // 2
        # 첫 5개는 noop, 나머지는 created
        items = []
        for i in range(n):
            if i < 5:
                items.append({"index": {"_id": f"doc_{i}", "result": "noop"}})
            else:
                items.append({"index": {"_id": f"doc_{i}", "result": "created"}})
        return {"items": items}

    client.bulk = AsyncMock(side_effect=fake_bulk)
    with patch.object(engine, "_get_client", return_value=client):
        count = await engine.update(_make_docs(100))

    assert count == 95  # 5개 noop 제외


@pytest.mark.asyncio
async def test_es_delete_counts_only_deleted_result():
    engine = _es_engine()
    client = MagicMock()
    client.bulk = AsyncMock(
        side_effect=lambda operations, refresh: _es_bulk_result(
            len(operations), "delete", "deleted"
        )
    )
    with patch.object(engine, "_get_client", return_value=client):
        count = await engine.delete([f"doc_{i}" for i in range(800)])
    assert count == 800
    assert client.bulk.await_count == 2  # 500+300


@pytest.mark.asyncio
async def test_es_partial_failure_warning(caplog):
    engine = _es_engine()
    client = MagicMock()

    def fake_bulk(operations, refresh):
        n = len(operations) // 2
        # 마지막 2개 error
        items = []
        for i in range(n):
            if i >= n - 2:
                items.append(
                    {"index": {"_id": f"doc_{i}", "error": {"type": "mapper"}}}
                )
            else:
                items.append({"index": {"_id": f"doc_{i}", "result": "updated"}})
        return {"items": items}

    client.bulk = AsyncMock(side_effect=fake_bulk)
    with patch.object(engine, "_get_client", return_value=client):
        with caplog.at_level("WARNING"):
            count = await engine.update(_make_docs(300))

    assert count == 298
    assert any(
        "ELASTICSEARCH" in rec.message and "partial fail" in rec.message
        for rec in caplog.records
    )
