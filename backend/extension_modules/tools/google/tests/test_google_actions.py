"""``routers/google_actions.py`` 단위 테스트.

T-B13 / T-B18 의 5축 게이트 + idempotency + error path 직접 호출 (TestClient 없이
async route 함수 직접 invoke — 코드베이스 컨벤션).

확인 항목:
- (a) HMAC owner verify — 404 (IDOR-safe)
- (b) features.{gmail,calendar} 재확인 — 403
- (c) ENABLE_{GMAIL,CALENDAR}_INTEGRATION 재확인 — 403
- (d) idempotency — replay 응답 (already_sent / previously_failed / already_created)
- 에러: GoogleReauthRequired → 401 + audit GMAIL_SEND_FAILED
- 에러: GoogleApiError → 502 + audit GMAIL_SEND_FAILED
- 성공: 200 + audit GMAIL_SEND
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from extension_modules.tools.google.inprocess._common import (
    GoogleApiError,
    GoogleReauthRequired,
)
from extension_modules.tools.google.inprocess._message_id import mint_message_id
from fastapi import HTTPException
from open_webui.routers.google_actions import (
    CalendarConfirmBody,
    DriveConfirmBody,
    GmailConfirmBody,
    confirm_calendar_create_event,
    confirm_drive_create_doc,
    confirm_gmail_send,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_request(
    *, gmail_enable=True, calendar_enable=True, drive_enable=True, user_perms=None
):
    """``request.app.state.config`` 만 채운 가벼운 mock."""
    config = SimpleNamespace(
        ENABLE_GMAIL_INTEGRATION=gmail_enable,
        ENABLE_CALENDAR_INTEGRATION=calendar_enable,
        ENABLE_DRIVE_INTEGRATION=drive_enable,
        USER_PERMISSIONS=user_perms or {},
    )
    state = SimpleNamespace(config=config)
    app = SimpleNamespace(state=state)
    return SimpleNamespace(app=app)


def _make_user(user_id="u", role="user"):
    return SimpleNamespace(id=user_id, role=role)


@dataclass
class _FakeAuditRow:
    action: str
    after_state: dict = field(default_factory=dict)
    resource_type: str = "gmail_message"
    resource_id: str = ""


# ---------------------------------------------------------------------------
# Gmail confirm — 5-gate
# ---------------------------------------------------------------------------


class TestGmailConfirmGateA:
    """(a) HMAC owner — 미스매치 시 404."""

    async def test_invalid_message_id_returns_404(self):
        request = _make_request()
        user = _make_user("user-a")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_gmail_send(
                message_id="bogus.signature1234",
                request=request,
                body=body,
                user=user,
            )
        assert exc_info.value.status_code == 404

    async def test_cross_user_message_id_returns_404(self):
        # user-a 가 발급받은 message_id 를 user-b 가 사용 → 404
        mid = mint_message_id("user-a")
        request = _make_request()
        user_b = _make_user("user-b")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_gmail_send(
                message_id=mid, request=request, body=body, user=user_b
            )
        assert exc_info.value.status_code == 404


class TestGmailConfirmGateB:
    """(b) features.gmail group permission — 거절 시 403."""

    async def test_user_without_permission_403(self):
        mid = mint_message_id("user-a")
        request = _make_request(user_perms={"features": {"gmail": False}})
        user = _make_user("user-a", role="user")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        # has_permission 을 명시적으로 False 로
        with patch(
            "open_webui.routers.google_actions.has_permission", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await confirm_gmail_send(
                    message_id=mid, request=request, body=body, user=user
                )
        assert exc_info.value.status_code == 403

    async def test_admin_bypasses_permission(self):
        # admin role 은 permission 체크 우회.  하지만 다른 게이트 (admin flag)
        # 와 idempotency 통과해야 send 까지 도달.
        mid = mint_message_id("admin-a")
        request = _make_request(user_perms={"features": {"gmail": False}})
        user = _make_user("admin-a", role="admin")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        # has_permission 안 불러야 하지만 어차피 우회.  idempotency dedup → 없음, send 모킹.
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.send_gmail_now",
                new=AsyncMock(return_value={"id": "g1", "threadId": "t1"}),
            ):
                with patch("open_webui.routers.google_actions.write_audit_log"):
                    resp = await confirm_gmail_send(
                        message_id=mid, request=request, body=body, user=user
                    )
        assert resp.status == "sent"


class TestGmailConfirmGateC:
    """(c) ENABLE_GMAIL_INTEGRATION admin flag — OFF 시 403."""

    async def test_admin_flag_off_403(self):
        mid = mint_message_id("user-a")
        request = _make_request(gmail_enable=False)
        user = _make_user("user-a", role="admin")  # admin role 도 막힘
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_gmail_send(
                message_id=mid, request=request, body=body, user=user
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Gmail confirm — Idempotency (gate d)
# ---------------------------------------------------------------------------


class TestGmailConfirmIdempotency:
    async def test_already_sent_returns_cached_result(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        prior = {
            "action": "GMAIL_SEND",
            "after_state": {
                "gmail_message_id": "g-existing",
                "thread_id": "t-existing",
            },
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt",
            return_value=prior,
        ):
            # send 가 호출되지 않아야 함
            with patch("open_webui.routers.google_actions.send_gmail_now") as send_mock:
                resp = await confirm_gmail_send(
                    message_id=mid, request=request, body=body, user=user
                )
                send_mock.assert_not_called()
        assert resp.status == "already_sent"
        assert resp.gmail_message_id == "g-existing"
        assert resp.thread_id == "t-existing"

    async def test_previously_failed_blocks_retry(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        prior = {
            "action": "GMAIL_SEND_FAILED",
            "after_state": {"error": "google_api_error_403"},
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=prior
        ):
            with patch("open_webui.routers.google_actions.send_gmail_now") as send_mock:
                resp = await confirm_gmail_send(
                    message_id=mid, request=request, body=body, user=user
                )
                send_mock.assert_not_called()
        assert resp.status == "previously_failed"


# ---------------------------------------------------------------------------
# Gmail confirm — Error paths
# ---------------------------------------------------------------------------


class TestGmailConfirmErrorPaths:
    async def test_reauth_required_writes_failed_audit_and_401(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        audit_calls = []

        def capture_audit(**kwargs):
            audit_calls.append(kwargs)

        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.send_gmail_now",
                new=AsyncMock(
                    side_effect=GoogleReauthRequired(
                        user_id="user-a", reason="invalid_grant"
                    )
                ),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=capture_audit,
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_gmail_send(
                            message_id=mid, request=request, body=body, user=user
                        )
        assert exc_info.value.status_code == 401
        # audit GMAIL_SEND_FAILED 호출됨
        assert len(audit_calls) == 1
        assert audit_calls[0]["action"].value == "GMAIL_SEND_FAILED"
        assert audit_calls[0]["after_state"]["error"] == "google_reauth_required"

    async def test_api_error_writes_failed_audit_and_502(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = GmailConfirmBody(to=["x@y.com"], subject="s", body="b")
        audit_calls = []

        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.send_gmail_now",
                new=AsyncMock(side_effect=GoogleApiError(403, "insufficient scope")),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_gmail_send(
                            message_id=mid, request=request, body=body, user=user
                        )
        assert exc_info.value.status_code == 502
        assert audit_calls[0]["action"].value == "GMAIL_SEND_FAILED"
        assert "google_api_error_403" in audit_calls[0]["after_state"]["error"]


# ---------------------------------------------------------------------------
# Gmail confirm — Success
# ---------------------------------------------------------------------------


class TestGmailConfirmSuccess:
    async def test_writes_audit_with_hashed_pii_and_returns_sent(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = GmailConfirmBody(
            to=["alice@example.com"],
            subject="hi",
            body="hello world",
            cc=["c@x.com"],
        )
        audit_calls = []

        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.send_gmail_now",
                new=AsyncMock(
                    return_value={"id": "gmail-id-1", "threadId": "thread-1"}
                ),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    resp = await confirm_gmail_send(
                        message_id=mid, request=request, body=body, user=user
                    )
        assert resp.status == "sent"
        assert resp.gmail_message_id == "gmail-id-1"
        assert resp.thread_id == "thread-1"

        audit = audit_calls[0]
        assert audit["action"].value == "GMAIL_SEND"
        state = audit["after_state"]
        assert state["gmail_message_id"] == "gmail-id-1"
        assert state["cc_count"] == 1
        # privacy — 평문 이메일 X, hash 만
        assert "alice@example.com" not in str(state)
        assert "recipients_hash" in state
        assert isinstance(state["recipients_hash"], list)
        assert len(state["recipients_hash"][0]) == 32


# ---------------------------------------------------------------------------
# Calendar confirm — gates + idempotency (대표 케이스만)
# ---------------------------------------------------------------------------


class TestCalendarConfirmGates:
    def _body(self):
        return CalendarConfirmBody(
            title="Sync",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
        )

    async def test_invalid_message_id_404(self):
        request = _make_request()
        user = _make_user("user-a")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_calendar_create_event(
                message_id="bogus.x", request=request, body=self._body(), user=user
            )
        assert exc_info.value.status_code == 404

    async def test_admin_flag_off_403(self):
        mid = mint_message_id("user-a")
        request = _make_request(calendar_enable=False)
        user = _make_user("user-a", role="admin")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_calendar_create_event(
                message_id=mid, request=request, body=self._body(), user=user
            )
        assert exc_info.value.status_code == 403

    async def test_iana_only_validated_in_body(self):
        # CalendarConfirmBody 자체 validator — `Z` / offset 거부
        with pytest.raises(Exception):
            CalendarConfirmBody(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="+09:00",
            )

    async def test_start_before_end_validated_in_body(self):
        # CalendarConfirmBody 자체 model_validator — start >= end 거부 (I-2).
        # 프론트가 편집해서 invalid range 를 보내도 Google API 400 전에 차단.
        with pytest.raises(Exception):
            CalendarConfirmBody(
                title="t",
                start="2026-05-20T11:00:00",
                end="2026-05-20T10:00:00",
                timezone="Asia/Seoul",
            )
        with pytest.raises(Exception):
            CalendarConfirmBody(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T10:00:00",
                timezone="Asia/Seoul",
            )

    async def test_already_created_returns_replay(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        prior = {
            "action": "CALENDAR_CREATE_EVENT",
            "after_state": {
                "event_id": "evt-existing",
                "html_link": "https://cal/existing",
            },
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt",
            return_value=prior,
        ):
            with patch(
                "open_webui.routers.google_actions.create_calendar_event_now"
            ) as create_mock:
                resp = await confirm_calendar_create_event(
                    message_id=mid,
                    request=request,
                    body=self._body(),
                    user=user,
                )
                create_mock.assert_not_called()
        assert resp.status == "already_created"
        assert resp.event_id == "evt-existing"


class TestCalendarConfirmSuccess:
    async def test_writes_audit_and_returns_created(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = CalendarConfirmBody(
            title="Sync",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
            attendees=["alice@example.com"],
        )
        audit_calls = []

        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_calendar_event_now",
                new=AsyncMock(
                    return_value={
                        "id": "evt-1",
                        "htmlLink": "https://cal/evt-1",
                        "hangoutLink": None,
                    }
                ),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    resp = await confirm_calendar_create_event(
                        message_id=mid, request=request, body=body, user=user
                    )
        assert resp.status == "created"
        assert resp.event_id == "evt-1"
        audit = audit_calls[0]
        assert audit["action"].value == "CALENDAR_CREATE_EVENT"
        # PII not in plaintext
        assert "alice@example.com" not in str(audit["after_state"])
        assert "attendees_hash" in audit["after_state"]

    async def test_api_failure_audits_failed_and_502(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = CalendarConfirmBody(
            title="Sync",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
        )
        audit_calls = []
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_calendar_event_now",
                new=AsyncMock(side_effect=GoogleApiError(400, "bad request")),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_calendar_create_event(
                            message_id=mid,
                            request=request,
                            body=body,
                            user=user,
                        )
        assert exc_info.value.status_code == 502
        assert audit_calls[0]["action"].value == "CALENDAR_CREATE_EVENT_FAILED"


# ---------------------------------------------------------------------------
# Drive confirm — 5축 게이트 + idempotency + 2-call success
# ---------------------------------------------------------------------------


class TestDriveConfirmGates:
    def _body(self):
        return DriveConfirmBody(name="Report", content="# Title\n\n- item")

    async def test_invalid_message_id_404(self):
        request = _make_request()
        user = _make_user("user-a")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_drive_create_doc(
                message_id="bogus.x", request=request, body=self._body(), user=user
            )
        assert exc_info.value.status_code == 404

    async def test_cross_user_message_id_404(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user_b = _make_user("user-b")
        with pytest.raises(HTTPException) as exc_info:
            await confirm_drive_create_doc(
                message_id=mid, request=request, body=self._body(), user=user_b
            )
        assert exc_info.value.status_code == 404

    async def test_user_without_permission_403(self):
        mid = mint_message_id("user-a")
        request = _make_request(user_perms={"features": {"drive": False}})
        user = _make_user("user-a", role="user")
        with patch(
            "open_webui.routers.google_actions.has_permission", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await confirm_drive_create_doc(
                    message_id=mid, request=request, body=self._body(), user=user
                )
        assert exc_info.value.status_code == 403

    async def test_admin_bypasses_permission(self):
        # admin role 은 permission 체크 우회. 다른 게이트 통과 후 create 까지 도달.
        mid = mint_message_id("admin-a")
        request = _make_request(user_perms={"features": {"drive": False}})
        user = _make_user("admin-a", role="admin")
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now",
                new=AsyncMock(
                    return_value={
                        "id": "doc-1",
                        "web_view_link": "https://docs/doc-1",
                        "name": "Report",
                    }
                ),
            ):
                with patch("open_webui.routers.google_actions.write_audit_log"):
                    resp = await confirm_drive_create_doc(
                        message_id=mid, request=request, body=self._body(), user=user
                    )
        assert resp.status == "created"

    async def test_admin_flag_off_403(self):
        mid = mint_message_id("user-a")
        request = _make_request(drive_enable=False)
        user = _make_user("user-a", role="admin")  # admin role 도 막힘
        with pytest.raises(HTTPException) as exc_info:
            await confirm_drive_create_doc(
                message_id=mid, request=request, body=self._body(), user=user
            )
        assert exc_info.value.status_code == 403


class TestDriveConfirmIdempotency:
    def _body(self):
        return DriveConfirmBody(name="Report", content="body")

    async def test_already_created_returns_replay(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        prior = {
            "action": "DRIVE_CREATE_DOC",
            "after_state": {
                "doc_id": "doc-existing",
                "web_link": "https://docs/existing",
            },
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt",
            return_value=prior,
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now"
            ) as create_mock:
                resp = await confirm_drive_create_doc(
                    message_id=mid, request=request, body=self._body(), user=user
                )
                create_mock.assert_not_called()
        assert resp.status == "already_created"
        assert resp.doc_id == "doc-existing"
        assert resp.web_link == "https://docs/existing"

    async def test_previously_failed_blocks_retry(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        prior = {
            "action": "DRIVE_CREATE_DOC_FAILED",
            "after_state": {"error": "google_api_error_403"},
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=prior
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now"
            ) as create_mock:
                resp = await confirm_drive_create_doc(
                    message_id=mid, request=request, body=self._body(), user=user
                )
                create_mock.assert_not_called()
        assert resp.status == "previously_failed"


class TestDriveConfirmErrorPaths:
    def _body(self):
        return DriveConfirmBody(name="Report", content="body")

    async def test_reauth_required_writes_failed_audit_and_401(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        audit_calls = []
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now",
                new=AsyncMock(
                    side_effect=GoogleReauthRequired(
                        user_id="user-a", reason="invalid_grant"
                    )
                ),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_drive_create_doc(
                            message_id=mid,
                            request=request,
                            body=self._body(),
                            user=user,
                        )
        assert exc_info.value.status_code == 401
        assert audit_calls[0]["action"].value == "DRIVE_CREATE_DOC_FAILED"
        assert audit_calls[0]["after_state"]["error"] == "google_reauth_required"

    async def test_api_error_writes_failed_audit_and_502(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        audit_calls = []
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now",
                new=AsyncMock(side_effect=GoogleApiError(403, "insufficient scope")),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_drive_create_doc(
                            message_id=mid,
                            request=request,
                            body=self._body(),
                            user=user,
                        )
        assert exc_info.value.status_code == 502
        assert audit_calls[0]["action"].value == "DRIVE_CREATE_DOC_FAILED"
        assert "google_api_error_403" in audit_calls[0]["after_state"]["error"]
        # 실행 가능한 Google 에러 메시지가 사용자에게 surface 돼야 한다
        # (예: "Docs API 활성화 필요 + 링크") — 로그만 보지 않게.
        assert "insufficient scope" in exc_info.value.detail

    async def test_api_error_with_partial_records_orphan_doc(self):
        # ORPHAN-DOC 계약 — create_drive_doc_now 가 Step1 성공 / Step2 실패 시
        # exc.partial = {"id", "web_view_link", "name"} 를 실어 raise 한다
        # (send.py L293). confirm endpoint 는 그 partial 을 읽어 FAILED audit 의
        # after_state.doc_id / web_link 로 기록해야 orphan 문서를 추적할 수 있다.
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        audit_calls = []
        exc = GoogleApiError(500, "step2 batchUpdate failed")
        exc.partial = {
            "id": "orphan-1",
            "web_view_link": "https://docs/orphan",
            "name": "Report",
        }
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now",
                new=AsyncMock(side_effect=exc),
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await confirm_drive_create_doc(
                            message_id=mid,
                            request=request,
                            body=self._body(),
                            user=user,
                        )
        assert exc_info.value.status_code == 502
        state = audit_calls[0]["after_state"]
        assert state["doc_id"] == "orphan-1"
        assert state["web_link"] == "https://docs/orphan"


class TestDriveConfirmSuccess:
    async def test_writes_audit_with_hashed_content_and_returns_created(self):
        mid = mint_message_id("user-a")
        request = _make_request()
        user = _make_user("user-a", role="admin")
        body = DriveConfirmBody(
            name="Quarterly Secret Report",
            content="confidential revenue figures",
            folder_id="folder-9",
        )
        audit_calls = []
        create_mock = AsyncMock(
            return_value={
                "id": "doc-1",
                "web_view_link": "https://docs/doc-1",
                "name": "Quarterly Secret Report",
            }
        )
        with patch(
            "open_webui.routers.google_actions._prior_attempt", return_value=None
        ):
            with patch(
                "open_webui.routers.google_actions.create_drive_doc_now",
                new=create_mock,
            ):
                with patch(
                    "open_webui.routers.google_actions.write_audit_log",
                    side_effect=lambda **k: audit_calls.append(k),
                ):
                    resp = await confirm_drive_create_doc(
                        message_id=mid, request=request, body=body, user=user
                    )
        assert resp.status == "created"
        assert resp.doc_id == "doc-1"
        assert resp.web_link == "https://docs/doc-1"
        # create_drive_doc_now 2-call 실행체는 단일 진입점 — kwargs 캡처 검증
        create_mock.assert_awaited_once_with(
            user_id="user-a",
            name="Quarterly Secret Report",
            content="confidential revenue figures",
            folder_id="folder-9",
        )
        audit = audit_calls[0]
        assert audit["action"].value == "DRIVE_CREATE_DOC"
        state = audit["after_state"]
        assert state["doc_id"] == "doc-1"
        assert state["folder_id"] == "folder-9"
        # privacy — 평문 제목/본문 X, hash 만
        assert "Quarterly Secret Report" not in str(state)
        assert "confidential revenue figures" not in str(state)
        assert len(state["name_hash"]) == 32
        assert len(state["content_hash"]) == 32
