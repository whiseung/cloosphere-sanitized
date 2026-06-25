"""임베딩 호출 재시도/백오프 공유 유틸.

Azure OpenAI 등 클라우드 임베딩 API 의 ``429 RateLimitReached`` / 5xx /
네트워크 오류를 transient 로 간주해 재시도한다. 서버가 내려준 ``Retry-After``
헤더를 **우선 존중**하고, 없으면 exponential backoff + jitter 를 적용한다.

지식기반 문서 업로드 시 임베딩 단계(`retrieval/utils.py`, requests, sync),
검색 시점(`extension_modules/search_engine/embedding.py`, aiohttp, async),
DbSphere 메모리(openai SDK) 가 모두 동일 정책을 공유하도록 sync/async 양쪽에
적용 가능한 단일 데코레이터(`embedding_retry`)를 제공한다.

기존 패턴(`extension_modules/tools/google/inprocess/_common.py`)과 동일하게
tenacity 를 사용하되, 그쪽이 다루지 않는 ``Retry-After`` 존중을 custom wait 로
추가했다.

설정(환경변수):
- ``RAG_EMBEDDING_MAX_RETRIES``      (기본 5)  최초 시도 외 추가 재시도 횟수
- ``RAG_EMBEDDING_RETRY_BASE_WAIT``  (기본 1.0s) backoff 기준 대기
- ``RAG_EMBEDDING_RETRY_MAX_WAIT``   (기본 30.0s) 한 번의 대기 상한
- ``RAG_EMBEDDING_RETRY_JITTER``     (기본 1.0s) backoff 에 더해지는 랜덤 지터
- ``RAG_EMBEDDING_MAX_CONCURRENCY``  (기본 4)   임베딩 배치 동시 실행 상한(0=무제한)
"""

import logging
import os
import random
from typing import Optional

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 설정 (환경변수 → 모듈 로드 시 1회 평가)
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, "")).strip())
    except (ValueError, TypeError):
        return default
    return value if value >= 0 else default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(str(os.environ.get(name, "")).strip())
    except (ValueError, TypeError):
        return default
    return value if value >= 0 else default


# 총 시도 = 1(최초) + EMBEDDING_MAX_RETRIES
EMBEDDING_MAX_RETRIES: int = _env_int("RAG_EMBEDDING_MAX_RETRIES", 5)
EMBEDDING_RETRY_BASE_WAIT: float = _env_float("RAG_EMBEDDING_RETRY_BASE_WAIT", 1.0)
EMBEDDING_RETRY_MAX_WAIT: float = _env_float("RAG_EMBEDDING_RETRY_MAX_WAIT", 30.0)
EMBEDDING_RETRY_JITTER: float = _env_float("RAG_EMBEDDING_RETRY_JITTER", 1.0)
# 임베딩 배치 동시 실행 상한 — burst 로 rate limit 을 자초하는 것을 막는다.
EMBEDDING_MAX_CONCURRENCY: int = _env_int("RAG_EMBEDDING_MAX_CONCURRENCY", 4)

# 재시도 대상 HTTP 상태코드 (rate limit + 일시적 서버 오류)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# 하드 import 없이 클래스명으로 판정하는 transient SDK/네트워크 예외
# (openai / google api_core / aiohttp). 패키지 미설치 환경에서도 안전.
# 클래스명 매칭이라 같은 이름의 무관한 예외도 재시도될 수 있으나, 여기 나열한
# 이름들은 본질적으로 transient(rate limit / 5xx / 네트워크)라 허용 가능.
_RETRYABLE_EXCEPTION_NAMES = frozenset(
    {
        "RateLimitError",  # openai
        "APITimeoutError",  # openai
        "APIConnectionError",  # openai
        "InternalServerError",  # openai (5xx)
        "ResourceExhausted",  # google api_core (429)
        "ServiceUnavailable",  # google api_core (503)
        "TooManyRequests",  # google api_core (429)
        "DeadlineExceeded",  # google api_core (timeout)
        "ServerTimeoutError",  # aiohttp
        "ClientConnectorError",  # aiohttp
        "ClientOSError",  # aiohttp
        "ClientConnectionError",  # aiohttp (커넥션 오류 베이스)
        "ServerDisconnectedError",  # aiohttp (keep-alive 끊김)
        "ClientPayloadError",  # aiohttp (불완전 응답 body)
        # asyncio/builtin timeout (aiohttp total timeout). builtin TimeoutError 도
        # 함께 매칭되지만 timeout 은 본질적으로 transient → 재시도 허용.
        "TimeoutError",
    }
)


class RetryableEmbeddingError(Exception):
    """상태코드를 직접 검사하는 경로(aiohttp 등)에서 transient 오류를 표준화.

    ``status`` 가 :data:`RETRYABLE_STATUS` 에 속하면 재시도 대상이 된다.
    ``retry_after`` 는 응답 헤더에서 추출한 초 단위 대기(있으면).
    """

    def __init__(
        self, status: int, message: str = "", retry_after: Optional[object] = None
    ):
        self.status = status
        self.retry_after = retry_after
        super().__init__(message or f"retryable embedding error: HTTP {status}")


def _status_of(exc: BaseException) -> Optional[int]:
    """예외에서 HTTP 상태코드를 best-effort 로 추출."""
    if isinstance(exc, RetryableEmbeddingError):
        return exc.status
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if code is None:
            code = getattr(resp, "status", None)  # aiohttp 스타일
        if isinstance(code, int):
            return code
    code = getattr(exc, "status_code", None)  # openai SDK 등
    if isinstance(code, int):
        return code
    return None


def is_retryable_embedding_error(exc: BaseException) -> bool:
    """이 예외를 재시도해야 하는가? (429 / 5xx / 네트워크 / transient SDK 오류)"""
    if isinstance(exc, RetryableEmbeddingError):
        return exc.status in RETRYABLE_STATUS
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if type(exc).__name__ in _RETRYABLE_EXCEPTION_NAMES:
        return True
    status = _status_of(exc)
    return status is not None and status in RETRYABLE_STATUS


def _parse_retry_after(value: object) -> Optional[float]:
    """``Retry-After`` 값을 초로 파싱. 숫자만 지원(HTTP-date 는 backoff 폴백)."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return None
    return seconds if seconds >= 0 else None


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """예외에 실린 ``Retry-After`` (초)를 추출. 없으면 None."""
    explicit = getattr(exc, "retry_after", None)
    parsed = _parse_retry_after(explicit)
    if parsed is not None:
        return parsed
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        try:
            return _parse_retry_after(
                headers.get("Retry-After") or headers.get("retry-after")
            )
        except Exception:
            return None
    return None


def compute_wait(attempt_number: int, exc: Optional[BaseException] = None) -> float:
    """다음 재시도까지 대기(초).

    서버 ``Retry-After`` 가 있으면 그것을(상한 적용) 그대로 존중하고, 없으면
    exponential backoff(base * 2^(n-1)) + jitter 를 적용한다. ``attempt_number``
    는 방금 실패한 시도의 1-기반 번호.
    """
    if exc is not None:
        after = retry_after_seconds(exc)
        if after is not None:
            return min(after, EMBEDDING_RETRY_MAX_WAIT)
    backoff = EMBEDDING_RETRY_BASE_WAIT * (2 ** max(0, attempt_number - 1))
    backoff = min(backoff, EMBEDDING_RETRY_MAX_WAIT)
    return backoff + random.uniform(0, EMBEDDING_RETRY_JITTER)


def _embedding_wait(retry_state) -> float:
    exc = None
    outcome = getattr(retry_state, "outcome", None)
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
    return compute_wait(retry_state.attempt_number, exc)


def _before_sleep_log(retry_state) -> None:
    outcome = getattr(retry_state, "outcome", None)
    exc = outcome.exception() if (outcome is not None and outcome.failed) else None
    log.warning(
        "Embedding call transient error (%s); retrying (attempt %d, max %d retries)",
        type(exc).__name__ if exc else "?",
        retry_state.attempt_number,
        EMBEDDING_MAX_RETRIES,
    )


def embedding_retry(fn):
    """sync/async 임베딩 호출에 재시도/backoff 를 적용하는 데코레이터.

    tenacity 가 동기/비동기 함수를 모두 지원하므로 동일 데코레이터를 양쪽에
    쓸 수 있다. transient(429/5xx/네트워크) 가 아니면 즉시 reraise.
    """
    return retry(
        retry=retry_if_exception(is_retryable_embedding_error),
        wait=_embedding_wait,
        stop=stop_after_attempt(1 + EMBEDDING_MAX_RETRIES),
        before_sleep=_before_sleep_log,
        reraise=True,
    )(fn)


@embedding_retry
def post_embedding_request(
    url: str,
    *,
    headers: dict,
    json_data: dict,
    label: str = "Embedding API error",
) -> requests.Response:
    """재시도가 적용된 동기 임베딩 POST.

    4xx(=429 제외) 같은 영구 오류는 즉시 전파되고, 429/5xx/네트워크 오류는
    backoff 후 재시도된다. 진단을 위해 실패 응답 본문 일부를 로깅한다.
    """
    r = requests.post(url, headers=headers, json=json_data)
    if r.status_code >= 400:
        log.warning("%s: HTTP %s %s", label, r.status_code, (r.text or "")[:300])
        r.raise_for_status()
    return r
