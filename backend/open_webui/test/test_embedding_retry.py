"""Unit tests for the embedding retry/backoff helper.

`open_webui.retrieval.embedding_retry` 는 Azure OpenAI 등 클라우드 임베딩 API의
429 RateLimitReached / 5xx / 네트워크 오류를 transient 로 간주해 재시도하고,
서버가 내려준 ``Retry-After`` 헤더를 우선 존중한다. 실제 sleep 없이 빠르게
검증하기 위해 wait 계산을 0 으로 monkeypatch 한다.
"""

import asyncio

import pytest
import requests

from open_webui.retrieval import embedding_retry as er


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _http_error(status: int, retry_after=None) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return requests.HTTPError(response=resp)


class RateLimitError(Exception):
    """openai SDK 의 RateLimitError 를 흉내 (클래스명 기반 판정 검증용)."""


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # 데코레이터가 쓰는 wait 계산을 0 으로 → 테스트가 즉시 끝남.
    monkeypatch.setattr(er, "compute_wait", lambda *a, **k: 0.0)


# ---------------------------------------------------------------------------
# is_retryable_embedding_error
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_http_status_retryable(status):
    assert er.is_retryable_embedding_error(_http_error(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_http_status_not_retryable(status):
    assert er.is_retryable_embedding_error(_http_error(status)) is False


def test_network_errors_retryable():
    assert er.is_retryable_embedding_error(requests.ConnectionError()) is True
    assert er.is_retryable_embedding_error(requests.Timeout()) is True


def test_generic_exception_not_retryable():
    assert er.is_retryable_embedding_error(ValueError("boom")) is False


def test_sdk_classname_retryable():
    # openai/google SDK 예외는 하드 import 없이 클래스명으로 판정.
    assert er.is_retryable_embedding_error(RateLimitError()) is True


def test_aiohttp_network_errors_retryable():
    # PATH 2(aiohttp) 의 transient 네트워크 오류도 클래스명으로 재시도 판정.
    import asyncio as _asyncio

    class ServerDisconnectedError(Exception):
        pass

    class ClientPayloadError(Exception):
        pass

    assert er.is_retryable_embedding_error(_asyncio.TimeoutError()) is True
    assert er.is_retryable_embedding_error(ServerDisconnectedError()) is True
    assert er.is_retryable_embedding_error(ClientPayloadError()) is True


def test_retryable_embedding_error_type():
    assert er.is_retryable_embedding_error(er.RetryableEmbeddingError(429)) is True
    assert er.is_retryable_embedding_error(er.RetryableEmbeddingError(400)) is False


# ---------------------------------------------------------------------------
# Retry-After / wait policy
# ---------------------------------------------------------------------------
def test_retry_after_parsed_from_header():
    exc = _http_error(429, retry_after=2)
    assert er.retry_after_seconds(exc) == 2.0


def test_retry_after_absent():
    assert er.retry_after_seconds(_http_error(429)) is None
    assert er.retry_after_seconds(ValueError()) is None


def test_compute_wait_respects_retry_after(monkeypatch):
    # compute_wait 원본을 검증해야 하므로 autouse 패치를 되돌린다.
    monkeypatch.undo()
    exc = _http_error(429, retry_after=2)
    assert er.compute_wait(1, exc) == 2.0


def test_compute_wait_caps_retry_after(monkeypatch):
    monkeypatch.undo()
    huge = _http_error(429, retry_after=99999)
    assert er.compute_wait(1, huge) == er.EMBEDDING_RETRY_MAX_WAIT


def test_compute_wait_exponential_capped(monkeypatch):
    monkeypatch.undo()
    # exc 없음 → expo backoff + jitter, 상한 적용.
    w = er.compute_wait(20, None)
    assert (
        er.EMBEDDING_RETRY_MAX_WAIT
        <= w
        <= er.EMBEDDING_RETRY_MAX_WAIT + er.EMBEDDING_RETRY_JITTER
    )


# ---------------------------------------------------------------------------
# embedding_retry decorator — sync
# ---------------------------------------------------------------------------
def test_sync_retry_succeeds_after_transient():
    calls = {"n": 0}

    @er.embedding_retry
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429, retry_after=1)
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3  # 첫 시도 + 2 재시도


def test_sync_retry_exhausts_and_reraises():
    calls = {"n": 0}

    @er.embedding_retry
    def always_429():
        calls["n"] += 1
        raise _http_error(429)

    with pytest.raises(requests.HTTPError):
        always_429()
    assert calls["n"] == 1 + er.EMBEDDING_MAX_RETRIES


def test_sync_no_retry_on_permanent_error():
    calls = {"n": 0}

    @er.embedding_retry
    def bad_request():
        calls["n"] += 1
        raise _http_error(400)

    with pytest.raises(requests.HTTPError):
        bad_request()
    assert calls["n"] == 1  # 재시도 없음


# ---------------------------------------------------------------------------
# embedding_retry decorator — async
# ---------------------------------------------------------------------------
def test_async_retry_succeeds_after_transient():
    calls = {"n": 0}

    @er.embedding_retry
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise er.RetryableEmbeddingError(429, retry_after=1)
        return "ok"

    assert asyncio.run(flaky()) == "ok"
    assert calls["n"] == 3


def test_async_retry_exhausts():
    calls = {"n": 0}

    @er.embedding_retry
    async def always_503():
        calls["n"] += 1
        raise er.RetryableEmbeddingError(503)

    with pytest.raises(er.RetryableEmbeddingError):
        asyncio.run(always_503())
    assert calls["n"] == 1 + er.EMBEDDING_MAX_RETRIES


# ---------------------------------------------------------------------------
# integration: generate_openai_batch_embeddings (실제 KB 업로드 임베딩 경로)
# ---------------------------------------------------------------------------
def _json_response(status: int, body=None, retry_after=None) -> requests.Response:
    import json as _json

    r = requests.Response()
    r.status_code = status
    if retry_after is not None:
        r.headers["Retry-After"] = str(retry_after)
    if body is not None:
        r._content = _json.dumps(body).encode()
    return r


def test_openai_batch_embeddings_retries_on_429(monkeypatch):
    """Azure OpenAI 429 → backoff → 성공. 보고된 KB 업로드 버그의 회귀 테스트."""
    from open_webui.retrieval import utils as ru

    responses = [
        _json_response(429, retry_after=1),
        _json_response(
            200,
            {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "usage": {}},
        ),
    ]
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None):
        idx = calls["n"]
        calls["n"] += 1
        return responses[idx]

    monkeypatch.setattr(er.requests, "post", fake_post)

    out = ru.generate_openai_batch_embeddings(
        "text-embedding-3-large",
        ["hello"],
        url="https://krc-aif-clsp.openai.azure.com",
        key="k",
        azure_api_version="2025-04-01-preview",
    )

    assert out == [[0.1, 0.2, 0.3]]
    assert calls["n"] == 2  # 429 1회 → 재시도 → 200


def test_openai_batch_embeddings_returns_none_when_exhausted(monkeypatch):
    """재시도 소진 시 기존 계약대로 None 반환 (호출부가 ValueError 로 변환)."""
    from open_webui.retrieval import utils as ru

    calls = {"n": 0}

    def always_429(url, headers=None, json=None):
        calls["n"] += 1
        return _json_response(429)

    monkeypatch.setattr(er.requests, "post", always_429)

    out = ru.generate_openai_batch_embeddings(
        "text-embedding-3-large", ["hello"], url="https://x.openai.azure.com", key="k"
    )

    assert out is None
    assert calls["n"] == 1 + er.EMBEDDING_MAX_RETRIES
