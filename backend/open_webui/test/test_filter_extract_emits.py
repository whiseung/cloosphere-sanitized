"""Unit tests for the single-file finalize emit in
``filter_extract_worker._emit_single_complete_if_solo``.

Backend AC for issue #3:
- single-file extraction (no ``job_id``) → ``extraction:single-complete``
- batch extraction (has ``job_id``) → ``extraction:complete``
- the two events must be mutually exclusive on the worker side.

These tests pin only the helper. End-to-end Socket.IO routing is covered
by the integration suite (which requires the docker compose stack).
"""

from typing import List
from unittest.mock import AsyncMock

import pytest


def _install_fake_socket_main(monkeypatch, fake_send):
    """Register a fake ``open_webui.socket.main`` for the duration of the test.

    monkeypatch.setitem 은 sys.modules 를 자동 복원하므로 후속 테스트가
    실제 socket.main 의 ``get_event_call`` / ``get_event_emitter`` 등
    다른 attribute 를 import 할 수 있다.
    """
    import sys
    import types

    fake_socket_main = types.ModuleType("open_webui.socket.main")
    fake_socket_main.send_notification_to_user = AsyncMock(side_effect=fake_send)
    monkeypatch.setitem(sys.modules, "open_webui.socket.main", fake_socket_main)


@pytest.mark.asyncio
async def test_single_complete_fires_when_no_job_id(monkeypatch):
    captured: List[dict] = []

    async def fake_send(**kwargs):
        captured.append(kwargs)

    _install_fake_socket_main(monkeypatch, fake_send)

    from open_webui.retrieval.filter_extract_worker import (
        _emit_single_complete_if_solo,
    )

    await _emit_single_complete_if_solo(
        user_id="u1",
        kb_id="kb1",
        file_id="f1",
        filename="doc.txt",
        job_id=None,
        success=True,
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["event_type"] == "extraction:single-complete"
    assert payload["data"]["kb_id"] == "kb1"
    assert payload["data"]["file_id"] == "f1"
    assert payload["data"]["filename"] == "doc.txt"
    assert payload["data"]["success"] is True


@pytest.mark.asyncio
async def test_single_complete_skipped_for_batch_job(monkeypatch):
    """job_id 가 있으면 batch — single-complete 미발행."""
    captured: List[dict] = []

    async def fake_send(**kwargs):
        captured.append(kwargs)

    _install_fake_socket_main(monkeypatch, fake_send)

    from open_webui.retrieval.filter_extract_worker import (
        _emit_single_complete_if_solo,
    )

    await _emit_single_complete_if_solo(
        user_id="u1",
        kb_id="kb1",
        file_id="f1",
        filename="doc.txt",
        job_id="batch-1",
        success=True,
    )

    assert captured == []


@pytest.mark.asyncio
async def test_single_complete_propagates_failure_flag(monkeypatch):
    captured: List[dict] = []

    async def fake_send(**kwargs):
        captured.append(kwargs)

    _install_fake_socket_main(monkeypatch, fake_send)

    from open_webui.retrieval.filter_extract_worker import (
        _emit_single_complete_if_solo,
    )

    await _emit_single_complete_if_solo(
        user_id="u1",
        kb_id="kb1",
        file_id="f1",
        filename="",
        job_id=None,
        success=False,
    )

    assert len(captured) == 1
    assert captured[0]["data"]["success"] is False
