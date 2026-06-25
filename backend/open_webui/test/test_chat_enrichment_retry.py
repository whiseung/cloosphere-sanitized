"""Unit tests for chat fan-out retry in ``ainvoke_temperature_safe``.

문서 업로드 시 contextual chunking / 질의예시 생성은 청크마다 chat LLM 을
fan-out 호출한다. Azure S0 tier 같은 rate limit 에서 429 가 나면 retry 없이
청크가 통째로 버려지던 것을, ``ainvoke_temperature_safe`` 의 일시적 에러
재시도(+ 서버 ``Retry-After`` 존중)로 흡수한다. 실제 sleep 없이 빠르게
검증하기 위해 ``asyncio.sleep`` 을 monkeypatch 로 가로채 대기값만 기록한다.

기존 임베딩 경로(`test_embedding_retry.py`)와 동일하게 `asyncio.run()` 으로
async 함수를 구동한다 (pytest-asyncio 모드 의존 없음).
"""

import asyncio

import pytest
from extension_modules.utils import llm


# ---------------------------------------------------------------------------
# helpers / fakes
# ---------------------------------------------------------------------------
class RateLimitError(Exception):
    """openai SDK 의 RateLimitError 를 흉내 (클래스명 기반 retryable 판정 검증).

    ``retry_after`` 가 주어지면 embedding_retry.retry_after_seconds 가 읽는
    속성으로 노출한다.
    """

    def __init__(self, retry_after=None):
        super().__init__(
            "Error code: 429 - {'error': {'message': 'Too Many Requests'}}"
        )
        if retry_after is not None:
            self.retry_after = retry_after


class TemperatureError(Exception):
    """temperature 미지원 400 을 흉내 (openai SDK 구조화 param 형태)."""

    def __init__(self):
        super().__init__("Unsupported value: 'temperature' does not support 0.3")
        self.status_code = 400
        self.param = "temperature"


class _Resp:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """ainvoke 가 미리 적재한 예외를 순서대로 던지고, 소진되면 성공 응답 반환."""

    def __init__(self, errors=None, model_name="chat-test-model"):
        self.model_name = model_name
        # _strip_temperature 가 None 으로 바꾸는지 검증할 수 있도록 값 보유.
        self.temperature = 0.3
        self.top_p = None
        self._errors = list(errors or [])
        self.calls = 0

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return _Resp("ok")


@pytest.fixture(autouse=True)
def _clean_temp_cache():
    # _FIXED_TEMP_MODELS 는 모듈 전역 — 테스트 간 누수 방지.
    llm._FIXED_TEMP_MODELS.clear()
    yield
    llm._FIXED_TEMP_MODELS.clear()


@pytest.fixture
def captured_sleeps(monkeypatch):
    """asyncio.sleep 을 가로채 실제 대기 없이 delay 값만 기록."""
    delays = []

    async def _fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return delays


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 재시도 기본 동작
# ---------------------------------------------------------------------------
def test_retries_on_429_then_succeeds(captured_sleeps):
    fake = FakeLLM(errors=[RateLimitError(), RateLimitError()])
    out = _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=5))
    assert out.content == "ok"
    assert fake.calls == 3  # 최초 + 2 재시도
    assert len(captured_sleeps) == 2


def test_exhausts_and_reraises(captured_sleeps):
    fake = FakeLLM(errors=[RateLimitError() for _ in range(10)])
    with pytest.raises(RateLimitError):
        _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=2))
    assert fake.calls == 1 + 2  # 최초 + max_retries
    assert len(captured_sleeps) == 2


def test_non_retryable_reraises_immediately(captured_sleeps):
    fake = FakeLLM(errors=[ValueError("permanent")])
    with pytest.raises(ValueError):
        _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=5))
    assert fake.calls == 1  # 재시도 없음
    assert captured_sleeps == []


def test_no_retry_when_max_retries_zero(captured_sleeps):
    # 기본값(0) 유지 — 기존 caller 동작 불변 보장.
    fake = FakeLLM(errors=[RateLimitError()])
    with pytest.raises(RateLimitError):
        _run(llm.ainvoke_temperature_safe(fake, ["m"]))
    assert fake.calls == 1
    assert captured_sleeps == []


# ---------------------------------------------------------------------------
# Retry-After 존중 (신규)
# ---------------------------------------------------------------------------
def test_respects_retry_after_header(captured_sleeps):
    # 서버가 Retry-After=2 를 주면 backoff 대신 그 값을 그대로 대기 (jitter 없음).
    fake = FakeLLM(
        errors=[RateLimitError(retry_after=2), RateLimitError(retry_after=2)]
    )
    out = _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=5))
    assert out.content == "ok"
    assert captured_sleeps == [2.0, 2.0]


def test_retry_after_capped_at_max_wait(captured_sleeps):
    # 소진→reraise 하도록 error 를 넉넉히 적재 (max_retries=1 → 1회만 대기).
    fake = FakeLLM(errors=[RateLimitError(retry_after=99999) for _ in range(5)])
    with pytest.raises(RateLimitError):
        _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=1, max_wait=30.0))
    assert captured_sleeps == [30.0]


def test_exponential_backoff_when_no_retry_after(captured_sleeps, monkeypatch):
    # Retry-After 부재 → base_delay × 2^attempt (jitter 는 0 으로 고정해 결정적 검증).
    monkeypatch.setattr(llm.random, "uniform", lambda a, b: 0.0)
    fake = FakeLLM(errors=[RateLimitError(), RateLimitError()])
    _run(
        llm.ainvoke_temperature_safe(
            fake, ["m"], max_retries=5, base_delay=1.0, max_wait=30.0
        )
    )
    assert captured_sleeps == [1.0, 2.0]


def test_backoff_capped_at_max_wait(captured_sleeps, monkeypatch):
    monkeypatch.setattr(llm.random, "uniform", lambda a, b: 0.0)
    # attempt 가 커지면 2^attempt 가 폭발 → max_wait 로 cap.
    fake = FakeLLM(errors=[RateLimitError() for _ in range(10)])
    with pytest.raises(RateLimitError):
        _run(
            llm.ainvoke_temperature_safe(
                fake, ["m"], max_retries=8, base_delay=1.0, max_wait=5.0
            )
        )
    assert max(captured_sleeps) == 5.0
    assert all(d <= 5.0 for d in captured_sleeps)


# ---------------------------------------------------------------------------
# temperature 우회 회귀 (기존 동작 보존)
# ---------------------------------------------------------------------------
def test_temperature_error_stripped_then_succeeds(captured_sleeps):
    fake = FakeLLM(errors=[TemperatureError()], model_name="temp-reject-model")
    out = _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=0))
    assert out.content == "ok"
    # temperature 우회는 재시도 카운트/대기를 소모하지 않는다.
    assert fake.calls == 2
    assert captured_sleeps == []
    # 모델이 학습 캐시에 등록되고 temperature 가 제거됐다.
    assert "temp-reject-model" in llm._FIXED_TEMP_MODELS
    assert fake.temperature is None


def test_temperature_then_rate_limit(captured_sleeps):
    # temperature 우회(카운트 미소모) 후 429 1회 → 재시도로 흡수.
    fake = FakeLLM(
        errors=[TemperatureError(), RateLimitError(retry_after=1)],
        model_name="temp-then-429",
    )
    out = _run(llm.ainvoke_temperature_safe(fake, ["m"], max_retries=3))
    assert out.content == "ok"
    assert fake.calls == 3  # temp(1) + 429(1) + 성공(1)
    assert captured_sleeps == [1.0]  # 429 한 번만 대기


# ---------------------------------------------------------------------------
# fan-out 전체 타임아웃 best-effort 폴백
# (retry 가 semaphore 슬롯을 쥔 채 누적돼 file-processing 타임아웃을 넘기면
#  job 전체가 죽어 청크가 통째로 소실되는 것을 방지 — enrichment 는 optional 후처리)
# ---------------------------------------------------------------------------
class _SlowLLM:
    """ainvoke 가 budget 보다 오래 걸리는 LLM (enrichment timeout 가드 검증용)."""

    model_name = "slow-model"
    temperature = None
    top_p = None

    async def ainvoke(self, messages, **kwargs):
        await asyncio.sleep(30)  # ENRICH_TIMEOUT 보다 훨씬 김 → wait_for 가 취소
        return _Resp("never")


def test_contextual_enrichment_timeout_falls_back_to_original(monkeypatch):
    from langchain_core.documents import Document

    from open_webui.retrieval import contextual_chunking as cc

    monkeypatch.setattr(cc, "ENRICH_TIMEOUT", 0.05)
    # 함수 내부 lazy import 대상 모듈 속성을 패치 (느린 LLM 주입).
    monkeypatch.setattr(
        "extension_modules.utils.llm.create_llm_from_app",
        lambda app, model_id: _SlowLLM(),
    )
    docs = [Document(page_content="a"), Document(page_content="b")]
    out = _run(
        cc.apply_contextual_chunking(app=None, docs=docs, full_text="a b", model_id="m")
    )
    # budget 초과 → 원본 청크 그대로 (enrich 안 됨), job 은 계속 진행 가능.
    assert out is docs
    assert all(not d.metadata.get("has_context") for d in out)


def test_question_generation_timeout_falls_back_to_empty(monkeypatch):
    from open_webui.retrieval import question_generator as qg

    monkeypatch.setattr(qg, "ENRICH_TIMEOUT", 0.05)
    gen = qg.ChunkQuestionGenerator(llm=_SlowLLM(), max_questions=5)
    out = _run(gen.generate_batch(["a", "b", "c"]))
    # budget 초과 → 청크 수만큼 빈 질의예시 (저장은 계속 진행).
    assert out == ["", "", ""]
