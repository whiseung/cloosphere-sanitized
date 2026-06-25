"""Google tools test fixtures.

WEBUI_SECRET_KEY 기본값이 빈 string 이면 ``mint_message_id`` 가 HMAC key 를
empty bytes 로 만들어 검증 자체는 정상 작동하지만 production 환경과 다른 sig
가 나오므로 테스트 전용 키를 한 번 설정한다.

내부 도메인 환경변수는 비워 두어 모든 외부 도메인 수신자가 ``external`` 로
판정되도록 — risk classifier 안정성.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _stable_secret_key(monkeypatch):
    """모든 google tool 테스트가 결정적 HMAC key 로 mint_message_id 호출."""
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-google-tools-secret-key")
    # _message_id 가 import-time 에 WEBUI_SECRET_KEY 를 읽었을 가능성이 있어
    # 모듈에 노출된 상수를 직접 갱신.
    from open_webui import env as openwebui_env

    monkeypatch.setattr(
        openwebui_env, "WEBUI_SECRET_KEY", "test-google-tools-secret-key"
    )
    yield


@pytest.fixture
def clear_internal_domains(monkeypatch):
    """``INTERNAL_EMAIL_DOMAINS`` 비워서 모든 도메인 external 강제 (안전 default)."""
    monkeypatch.setenv("INTERNAL_EMAIL_DOMAINS", "")
    # _hitl 의 frozenset 은 import-time eval — runtime 갱신 필요.
    from extension_modules.tools.google.inprocess import _hitl

    monkeypatch.setattr(_hitl, "INTERNAL_EMAIL_DOMAINS", frozenset())
    yield


@pytest.fixture
def with_internal_domain(monkeypatch):
    """``cloocus.com`` 을 내부 도메인으로 설정 — 내부 vs 외부 분기 검증용."""
    from extension_modules.tools.google.inprocess import _hitl

    monkeypatch.setattr(_hitl, "INTERNAL_EMAIL_DOMAINS", frozenset({"cloocus.com"}))
    yield


# pytest-asyncio asyncio_mode=auto — 모든 async def 테스트는 자동 wrap.
# (pyproject.toml 의 [tool.pytest.ini_options] asyncio_mode="auto")
os.environ.setdefault("WEBUI_SECRET_KEY", "test-google-tools-secret-key")
