"""读写回读自验证 harness 单测

用内存假客户端真实地走「写→读回→校验→删」闭环，验证 RoundTripVerifier 逻辑，
并覆盖写入内容被篡改时能被检测出来的负向用例。
"""

from __future__ import annotations

import uuid

from mail_agent.gapi.verify import RoundTripVerifier
from mail_agent.models import CalendarEvent, EmailMessage, ReplyDraft


class FakeCalendar:
    """内存日历，模拟 GoogleCalendarClient 接口"""

    def __init__(self, *, corrupt_title: bool = False, drop_on_read: bool = False):
        self.events: dict[str, CalendarEvent] = {}
        self._corrupt_title = corrupt_title
        self._drop_on_read = drop_on_read

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        event.event_id = "evt-" + uuid.uuid4().hex[:8]
        if self._corrupt_title:
            stored = event.model_copy(update={"title": "WRONG"})
        else:
            stored = event
        self.events[event.event_id] = stored
        return event

    def get_event(self, event_id: str):
        if self._drop_on_read:
            return None
        return self.events.get(event_id)

    def list_events(self, start=None, end=None):
        return list(self.events.values())

    def remove_event(self, event_id: str) -> bool:
        return self.events.pop(event_id, None) is not None


class FakeGmail:
    """内存 Gmail，模拟 GmailClient 接口"""

    def __init__(self, *, corrupt_subject: bool = False, fail_send: bool = False):
        self.drafts: dict[str, EmailMessage] = {}
        self.sent: list[EmailMessage] = []
        self._corrupt_subject = corrupt_subject
        self._fail_send = fail_send

    def create_draft(self, reply: ReplyDraft, original=None) -> str:
        did = "d-" + uuid.uuid4().hex[:8]
        subject = "WRONG" if self._corrupt_subject else reply.subject
        self.drafts[did] = EmailMessage(
            gmail_id=did,
            subject=subject,
            body=reply.body,
            recipients=list(reply.to),
        )
        return did

    def get_draft(self, draft_id: str) -> EmailMessage:
        return self.drafts[draft_id]

    def list_drafts(self, limit: int = 50):
        return [{"id": k} for k in self.drafts]

    def delete_draft(self, draft_id: str) -> None:
        self.drafts.pop(draft_id, None)

    def send_reply(self, reply: ReplyDraft, original=None) -> str:
        if self._fail_send:
            return ""
        sid = "s-" + uuid.uuid4().hex[:8]
        self.sent.append(
            EmailMessage(
                gmail_id=sid, subject=reply.subject, recipients=list(reply.to)
            )
        )
        return sid

    def fetch_query(self, query: str, limit: int = 50):
        # query 形如 "in:sent <token>"
        token = query.split()[-1]
        return [m for m in self.sent if token in (m.subject or "")]


# ── 日历闭环 ──


class TestCalendarRoundTrip:
    def test_happy_path_passes_and_cleans_up(self):
        v = RoundTripVerifier(calendar=FakeCalendar())
        res = v.verify_calendar_roundtrip(cleanup=True)
        assert res.passed is True, [c for c in res.checks if not c.passed]
        assert res.cleaned_up is True
        names = {c.name for c in res.checks}
        assert {
            "create_returns_id",
            "readback_exists",
            "title_match",
            "start_match",
            "end_match",
            "list_contains",
            "delete_ok",
            "gone_after_delete",
        } <= names

    def test_no_cleanup_keeps_event(self):
        cal = FakeCalendar()
        v = RoundTripVerifier(calendar=cal)
        res = v.verify_calendar_roundtrip(cleanup=False)
        assert res.passed is True
        assert res.cleaned_up is False
        assert res.artifact_id in cal.events

    def test_detects_corrupted_title(self):
        v = RoundTripVerifier(calendar=FakeCalendar(corrupt_title=True))
        res = v.verify_calendar_roundtrip(cleanup=True)
        assert res.passed is False
        assert any(c.name == "title_match" and not c.passed for c in res.checks)

    def test_detects_missing_readback(self):
        v = RoundTripVerifier(calendar=FakeCalendar(drop_on_read=True))
        res = v.verify_calendar_roundtrip(cleanup=True)
        assert res.passed is False
        assert any(c.name == "readback_exists" and not c.passed for c in res.checks)

    def test_no_client(self):
        res = RoundTripVerifier().verify_calendar_roundtrip()
        assert res.passed is False


# ── 草稿闭环 ──


class TestDraftRoundTrip:
    def test_happy_path(self):
        v = RoundTripVerifier(gmail=FakeGmail(), redirect_to="t@qq.com")
        res = v.verify_draft_roundtrip(cleanup=True)
        assert res.passed is True, [c for c in res.checks if not c.passed]
        assert res.cleaned_up is True

    def test_recipient_is_redirect_target(self):
        gmail = FakeGmail()
        v = RoundTripVerifier(gmail=gmail, redirect_to="t@qq.com")
        res = v.verify_draft_roundtrip(cleanup=False)
        stored = gmail.drafts[res.artifact_id]
        assert stored.recipients == ["t@qq.com"]
        assert res.passed is True

    def test_detects_corrupted_subject(self):
        v = RoundTripVerifier(
            gmail=FakeGmail(corrupt_subject=True), redirect_to="t@qq.com"
        )
        res = v.verify_draft_roundtrip(cleanup=True)
        assert res.passed is False
        assert any(c.name == "subject_match" and not c.passed for c in res.checks)

    def test_requires_redirect_to(self):
        res = RoundTripVerifier(gmail=FakeGmail()).verify_draft_roundtrip()
        assert res.passed is False


# ── 发送闭环 ──


class TestSendRoundTrip:
    def test_happy_path_finds_in_sent(self):
        v = RoundTripVerifier(gmail=FakeGmail(), redirect_to="t@qq.com")
        res = v.verify_send_roundtrip()
        assert res.passed is True, [c for c in res.checks if not c.passed]
        assert any(c.name == "found_in_sent" and c.passed for c in res.checks)

    def test_detects_send_failure(self):
        v = RoundTripVerifier(
            gmail=FakeGmail(fail_send=True), redirect_to="t@qq.com"
        )
        res = v.verify_send_roundtrip()
        assert res.passed is False


# ── run_all ──


def test_run_all_default_excludes_send():
    v = RoundTripVerifier(
        gmail=FakeGmail(), calendar=FakeCalendar(), redirect_to="t@qq.com"
    )
    results = v.run_all(cleanup=True)
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_run_all_with_send():
    v = RoundTripVerifier(
        gmail=FakeGmail(), calendar=FakeCalendar(), redirect_to="t@qq.com"
    )
    results = v.run_all(cleanup=True, include_send=True)
    assert len(results) == 3
    assert all(r.passed for r in results)
