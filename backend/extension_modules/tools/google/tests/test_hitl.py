"""HITL risk classifier + confirmation payload builders 단위 테스트.

plan §5.9 (anti cargo-cult confirm) — 외부 도메인/다수 수신자/cc·bcc/스레드
회신/긴 body 가 high risk 로 분류돼 2-click confirm UX 강제.
"""

from __future__ import annotations

from extension_modules.tools.google.inprocess._hitl import (
    classify_calendar_risk,
    classify_gmail_risk,
    make_calendar_confirmation,
    make_gmail_confirmation,
)

# ---------------------------------------------------------------------------
# classify_gmail_risk
# ---------------------------------------------------------------------------


class TestClassifyGmailRisk:
    def test_internal_single_short_is_low(self, with_internal_domain):
        # cloocus.com 만 내부 도메인, 1명, body 짧음
        risk = classify_gmail_risk(to=["alice@cloocus.com"], body="hello")
        assert risk == "low"

    def test_external_recipient_is_high(self, with_internal_domain):
        risk = classify_gmail_risk(to=["alice@external.com"], body="hello")
        assert risk == "high"

    def test_no_internal_domains_all_external(self, clear_internal_domains):
        # 내부 도메인 list 비어있으면 모두 external — 안전 default
        risk = classify_gmail_risk(to=["alice@cloocus.com"], body="hello")
        assert risk == "high"

    def test_three_recipients_is_high(self, with_internal_domain):
        risk = classify_gmail_risk(
            to=["a@cloocus.com", "b@cloocus.com", "c@cloocus.com"], body="hi"
        )
        assert risk == "high"

    def test_cc_makes_high(self, with_internal_domain):
        risk = classify_gmail_risk(
            to=["a@cloocus.com"], cc=["b@cloocus.com"], body="hi"
        )
        assert risk == "high"

    def test_bcc_makes_high(self, with_internal_domain):
        risk = classify_gmail_risk(
            to=["a@cloocus.com"], bcc=["b@cloocus.com"], body="hi"
        )
        assert risk == "high"

    def test_in_reply_to_makes_high(self, with_internal_domain):
        risk = classify_gmail_risk(
            to=["a@cloocus.com"], body="hi", in_reply_to="<msg-123@example>"
        )
        assert risk == "high"

    def test_long_body_makes_high(self, with_internal_domain):
        risk = classify_gmail_risk(to=["a@cloocus.com"], body="x" * 1500)
        assert risk == "high"

    def test_900_chars_still_low(self, with_internal_domain):
        # boundary check — _GMAIL_BODY_HIGH_RISK_LEN = 1000
        risk = classify_gmail_risk(to=["a@cloocus.com"], body="x" * 999)
        assert risk == "low"


# ---------------------------------------------------------------------------
# classify_calendar_risk
# ---------------------------------------------------------------------------


class TestClassifyCalendarRisk:
    def test_no_attendees_none_send_updates_is_low(self, with_internal_domain):
        assert classify_calendar_risk(attendees=None, send_updates="none") == "low"

    def test_internal_attendee_send_updates_none_is_low(self, with_internal_domain):
        assert (
            classify_calendar_risk(
                attendees=[{"email": "alice@cloocus.com"}],
                send_updates="none",
            )
            == "low"
        )

    def test_send_updates_all_is_high(self, with_internal_domain):
        # 외부에 알림 메일 발송 — high
        assert (
            classify_calendar_risk(
                attendees=[{"email": "alice@cloocus.com"}],
                send_updates="all",
            )
            == "high"
        )

    def test_external_attendee_is_high(self, with_internal_domain):
        assert (
            classify_calendar_risk(
                attendees=[{"email": "external@elsewhere.com"}],
                send_updates="none",
            )
            == "high"
        )

    def test_three_attendees_is_high(self, with_internal_domain):
        assert (
            classify_calendar_risk(
                attendees=[
                    {"email": "a@cloocus.com"},
                    {"email": "b@cloocus.com"},
                    {"email": "c@cloocus.com"},
                ],
                send_updates="none",
            )
            == "high"
        )

    def test_long_description_is_high(self, with_internal_domain):
        assert (
            classify_calendar_risk(
                attendees=None, send_updates="none", description="x" * 1500
            )
            == "high"
        )


# ---------------------------------------------------------------------------
# make_gmail_confirmation
# ---------------------------------------------------------------------------


class TestMakeGmailConfirmation:
    def test_payload_shape(self, with_internal_domain):
        payload = make_gmail_confirmation(
            message_id="abc.def",
            to=["alice@cloocus.com"],
            subject="hi",
            body="hello",
        )
        assert payload["confirmation_required"] is True
        assert payload["tool"] == "gmail_send"
        assert payload["message_id"] == "abc.def"
        assert payload["risk_level"] == "low"
        assert payload["draft"]["to"] == ["alice@cloocus.com"]
        assert payload["draft"]["cc"] == []
        assert payload["draft"]["bcc"] == []
        assert payload["draft"]["subject"] == "hi"
        assert payload["draft"]["body"] == "hello"
        # recipients_meta with domain + is_external
        meta = payload["recipients_meta"]
        assert len(meta) == 1
        assert meta[0]["email"] == "alice@cloocus.com"
        assert meta[0]["domain"] == "cloocus.com"
        assert meta[0]["is_external"] is False

    def test_meta_includes_cc_bcc(self, with_internal_domain):
        payload = make_gmail_confirmation(
            message_id="m.s",
            to=["a@cloocus.com"],
            cc=["b@external.com"],
            bcc=["c@cloocus.com"],
            subject="s",
            body="b",
        )
        emails = [m["email"] for m in payload["recipients_meta"]]
        assert emails == ["a@cloocus.com", "b@external.com", "c@cloocus.com"]
        # 외부 도메인 표시
        externals = {m["email"]: m["is_external"] for m in payload["recipients_meta"]}
        assert externals["b@external.com"] is True
        assert externals["a@cloocus.com"] is False


# ---------------------------------------------------------------------------
# make_calendar_confirmation
# ---------------------------------------------------------------------------


class TestMakeCalendarConfirmation:
    def test_payload_shape(self, with_internal_domain):
        payload = make_calendar_confirmation(
            message_id="m.s",
            title="Sync",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
            attendees=[{"email": "alice@cloocus.com"}],
            send_updates="all",
        )
        assert payload["confirmation_required"] is True
        assert payload["tool"] == "calendar_create_event"
        assert payload["message_id"] == "m.s"
        assert payload["risk_level"] == "high"  # send_updates="all"
        assert payload["draft"]["title"] == "Sync"
        assert payload["draft"]["timezone"] == "Asia/Seoul"
        assert payload["draft"]["send_updates"] == "all"
        assert payload["draft"]["create_meet"] is False
        # attendees_meta
        meta = payload["attendees_meta"]
        assert len(meta) == 1
        assert meta[0]["email"] == "alice@cloocus.com"
        assert meta[0]["is_external"] is False

    def test_empty_attendees_default(self, with_internal_domain):
        payload = make_calendar_confirmation(
            message_id="m.s",
            title="Solo",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
        )
        assert payload["draft"]["attendees"] == []
        assert payload["attendees_meta"] == []
        # 알림 없음 + 외부 없음 + 짧은 description → low
        assert payload["risk_level"] == "low"


# ---------------------------------------------------------------------------
# make_drive_confirmation (risk hardcoded low — no classifier)
# ---------------------------------------------------------------------------


class TestMakeDriveConfirmation:
    def test_payload_shape(self):
        from extension_modules.tools.google.inprocess._hitl import (
            make_drive_confirmation,
        )

        payload = make_drive_confirmation(
            message_id="mid.sig",
            name="Q2 Report",
            content="# Heading\n\nbody",
            folder_id=None,
        )
        assert payload["confirmation_required"] is True
        assert payload["tool"] == "drive_create_doc"
        assert payload["message_id"] == "mid.sig"
        # 내 드라이브 생성은 외부 도달 없음 → 항상 low, 분류기 없음.
        assert payload["risk_level"] == "low"
        assert payload["draft"] == {
            "name": "Q2 Report",
            "content": "# Heading\n\nbody",
            "folder_id": None,
        }
        # gmail/calendar 와 달리 recipients/attendees meta 없음.
        assert "recipients_meta" not in payload
        assert "attendees_meta" not in payload

    def test_folder_id_preserved(self):
        from extension_modules.tools.google.inprocess._hitl import (
            make_drive_confirmation,
        )

        payload = make_drive_confirmation(
            message_id="m.s", name="n", content="c", folder_id="folder-123"
        )
        assert payload["draft"]["folder_id"] == "folder-123"
