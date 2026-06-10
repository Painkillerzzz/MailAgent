"""Google 集成测试（Gmail API + Google Calendar API）

通过注入 mock service 验证逻辑，不发起真实网络请求/授权。
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import formatdate
from unittest.mock import MagicMock

import pytest

from mail_agent.config import GoogleConfig
from mail_agent.gapi.gcalendar import GoogleCalendarClient
from mail_agent.gapi.gmail import GmailClient
from mail_agent.models import CalendarEvent, ReplyDraft


# ── 辅助：构造一封原始邮件并编码为 Gmail raw ──


def _make_raw_email(
    subject: str, sender: str, body: str, msg_id: str
) -> str:
    msg = Message()
    msg["From"] = sender
    msg["To"] = "me@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    msg["Date"] = formatdate()
    msg.set_payload(body, charset="utf-8")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return raw


@pytest.fixture
def google_config() -> GoogleConfig:
    return GoogleConfig(enabled=True, calendar_id="primary")


# ── Gmail ──


class TestGmailClient:
    def test_fetch_unread_parses_messages(self, google_config):
        raw = _make_raw_email(
            "Hello", "Alice <alice@example.com>", "Hi there", "<abc@x.com>"
        )
        service = MagicMock()
        # list 返回两个引用
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "g1"}, {"id": "g2"}]
        }
        # get 每次返回同一封（够测试解析）
        service.users().messages().get().execute.return_value = {
            "id": "g1",
            "threadId": "t1",
            "labelIds": ["UNREAD", "INBOX"],
            "raw": raw,
        }
        client = GmailClient(google_config, service=service)
        emails = client.fetch_unread(limit=10)

        assert len(emails) == 2
        assert emails[0].subject == "Hello"
        assert emails[0].sender == "alice@example.com"
        assert emails[0].gmail_id == "g1"
        assert emails[0].gmail_thread_id == "t1"
        assert emails[0].is_read is False

    def test_fetch_uses_batch_then_fills_gaps(self, google_config):
        """batch 命中的直接用结果，未命中的逐封补齐，且保持顺序。"""
        raw1 = _make_raw_email("First", "a@x.com", "b1", "<m1@x.com>")
        raw2 = _make_raw_email("Second", "b@x.com", "b2", "<m2@x.com>")
        service = MagicMock()
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "g1"}, {"id": "g2"}]
        }
        # batch 只回调 g1；g2 留给逐封补齐
        class _FakeBatch:
            def __init__(self):
                self._calls = []

            def add(self, request, request_id=None, callback=None):
                self._calls.append((request_id, callback))

            def execute(self):
                for rid, cb in self._calls:
                    if rid == "g1":
                        cb(rid, {"id": "g1", "threadId": "t1",
                                 "labelIds": ["INBOX"], "raw": raw1}, None)

        service.new_batch_http_request.return_value = _FakeBatch()
        # 逐封补齐 g2
        service.users().messages().get().execute.return_value = {
            "id": "g2", "threadId": "t2", "labelIds": ["UNREAD"], "raw": raw2,
        }
        client = GmailClient(google_config, service=service)
        emails = client.fetch_unread(limit=10)

        assert [e.subject for e in emails] == ["First", "Second"]
        assert emails[0].gmail_id == "g1" and emails[0].is_read is True
        assert emails[1].gmail_id == "g2" and emails[1].is_read is False

    def test_fetch_falls_back_when_batch_raises(self, google_config):
        """batch 整体抛错时，全部逐封补齐而不丢邮件。"""
        raw = _make_raw_email("Hello", "a@x.com", "hi", "<m@x.com>")
        service = MagicMock()
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "g1"}, {"id": "g2"}]
        }
        service.new_batch_http_request.side_effect = RuntimeError("no batch")
        service.users().messages().get().execute.return_value = {
            "id": "g1", "threadId": "t1", "labelIds": ["UNREAD"], "raw": raw,
        }
        client = GmailClient(google_config, service=service)
        emails = client.fetch_unread(limit=10)
        assert len(emails) == 2

    def test_mark_read_calls_modify(self, google_config):
        service = MagicMock()
        client = GmailClient(google_config, service=service)
        client.mark_read("g1")
        service.users().messages().modify.assert_called_with(
            userId="me", id="g1", body={"removeLabelIds": ["UNREAD"]}
        )

    def test_build_raw_reply_sets_threading_headers(self, google_config):
        client = GmailClient(google_config, service=MagicMock())
        original = MagicMock()
        original.message_id = "<orig@x.com>"
        original.gmail_thread_id = "t1"
        reply = ReplyDraft(
            subject="Re: Hi", body="Sure!", to=["alice@example.com"]
        )
        raw = client._build_raw_reply(reply, original)
        raw_bytes = base64.urlsafe_b64decode(raw.encode("ascii"))
        import email as email_mod

        parsed = email_mod.message_from_bytes(raw_bytes)
        assert parsed["To"] == "alice@example.com"
        assert parsed["Subject"] == "Re: Hi"
        assert parsed["In-Reply-To"] == "<orig@x.com>"
        assert parsed["References"] == "<orig@x.com>"
        assert parsed.get_payload(decode=True).decode("utf-8") == "Sure!"

    def test_create_draft_includes_thread_id(self, google_config):
        service = MagicMock()
        service.users().drafts().create().execute.return_value = {"id": "d1"}
        client = GmailClient(google_config, service=service)

        original = MagicMock()
        original.message_id = "<orig@x.com>"
        original.gmail_thread_id = "t1"
        reply = ReplyDraft(subject="Re: Hi", body="ok", to=["a@x.com"])

        draft_id = client.create_draft(reply, original)
        assert draft_id == "d1"
        _, kwargs = service.users().drafts().create.call_args
        assert kwargs["body"]["message"]["threadId"] == "t1"
        assert "raw" in kwargs["body"]["message"]

    def test_send_reply_returns_id(self, google_config):
        service = MagicMock()
        service.users().messages().send().execute.return_value = {"id": "s1"}
        client = GmailClient(google_config, service=service)

        original = MagicMock()
        original.message_id = "<orig@x.com>"
        original.gmail_thread_id = "t1"
        reply = ReplyDraft(subject="Re: Hi", body="ok", to=["a@x.com"])

        sent_id = client.send_reply(reply, original)
        assert sent_id == "s1"
        _, kwargs = service.users().messages().send.call_args
        assert kwargs["body"]["threadId"] == "t1"


class TestGmailReadback:
    def test_get_message_parses(self, google_config):
        raw = _make_raw_email(
            "Sub", "Bob <bob@example.com>", "body", "<id@x>"
        )
        service = MagicMock()
        service.users().messages().get().execute.return_value = {
            "id": "g9",
            "threadId": "t9",
            "labelIds": ["INBOX"],
            "raw": raw,
        }
        client = GmailClient(google_config, service=service)
        msg = client.get_message("g9")
        assert msg.subject == "Sub"
        assert msg.gmail_id == "g9"
        assert msg.is_read is True  # 无 UNREAD 标签

    def test_get_draft_parses(self, google_config):
        raw = _make_raw_email(
            "Re: x", "me@gmail.com", "draft body", "<d@x>"
        )
        service = MagicMock()
        service.users().drafts().get().execute.return_value = {
            "id": "d1",
            "message": {"id": "m1", "threadId": "t1", "raw": raw},
        }
        client = GmailClient(google_config, service=service)
        msg = client.get_draft("d1")
        assert msg.subject == "Re: x"
        assert msg.gmail_id == "m1"
        assert msg.gmail_thread_id == "t1"

    def test_list_drafts(self, google_config):
        service = MagicMock()
        service.users().drafts().list().execute.return_value = {
            "drafts": [{"id": "d1"}, {"id": "d2"}]
        }
        client = GmailClient(google_config, service=service)
        drafts = client.list_drafts()
        assert [d["id"] for d in drafts] == ["d1", "d2"]

    def test_delete_draft(self, google_config):
        service = MagicMock()
        client = GmailClient(google_config, service=service)
        client.delete_draft("d1")
        service.users().drafts().delete.assert_called_with(userId="me", id="d1")


# ── Google Calendar ──


class TestGoogleCalendarClient:
    def test_add_event_builds_body_and_returns_id(self, google_config):
        service = MagicMock()
        service.events().insert().execute.return_value = {"id": "evt123"}
        client = GoogleCalendarClient(google_config, service=service)

        start = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)
        event = CalendarEvent(
            title="Sync",
            description="weekly",
            start_time=start,
            end_time=start + timedelta(hours=1),
            attendees=["a@x.com"],
        )
        out = client.add_event(event)
        assert out.event_id == "evt123"
        _, kwargs = service.events().insert.call_args
        body = kwargs["body"]
        assert body["summary"] == "Sync"
        assert body["attendees"] == [{"email": "a@x.com"}]
        assert "dateTime" in body["start"]

    def test_list_events_parses_items(self, google_config):
        service = MagicMock()
        service.events().list().execute.return_value = {
            "items": [
                {
                    "id": "e1",
                    "summary": "Meeting",
                    "start": {"dateTime": "2026-06-10T15:00:00+00:00"},
                    "end": {"dateTime": "2026-06-10T16:00:00+00:00"},
                    "attendees": [{"email": "a@x.com"}],
                }
            ]
        }
        client = GoogleCalendarClient(google_config, service=service)
        events = client.list_events()
        assert len(events) == 1
        assert events[0].title == "Meeting"
        assert events[0].event_id == "e1"
        assert events[0].attendees == ["a@x.com"]

    def test_check_conflict_detects_overlap(self, google_config):
        service = MagicMock()
        service.events().list().execute.return_value = {
            "items": [
                {
                    "id": "e1",
                    "summary": "Busy",
                    "start": {"dateTime": "2026-06-10T15:30:00+00:00"},
                    "end": {"dateTime": "2026-06-10T16:30:00+00:00"},
                }
            ]
        }
        client = GoogleCalendarClient(google_config, service=service)
        conflict = client.check_conflict(
            datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 16, 0, tzinfo=timezone.utc),
        )
        assert conflict.has_conflict is True
        assert len(conflict.conflicting_events) == 1

    def test_check_conflict_no_overlap(self, google_config):
        service = MagicMock()
        service.events().list().execute.return_value = {
            "items": [
                {
                    "id": "e1",
                    "summary": "Earlier",
                    "start": {"dateTime": "2026-06-10T09:00:00+00:00"},
                    "end": {"dateTime": "2026-06-10T10:00:00+00:00"},
                }
            ]
        }
        client = GoogleCalendarClient(google_config, service=service)
        conflict = client.check_conflict(
            datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 16, 0, tzinfo=timezone.utc),
        )
        assert conflict.has_conflict is False

    def test_remove_event(self, google_config):
        service = MagicMock()
        client = GoogleCalendarClient(google_config, service=service)
        assert client.remove_event("e1") is True
        service.events().delete.assert_called_with(
            calendarId="primary", eventId="e1"
        )

    def test_get_event_returns_event(self, google_config):
        service = MagicMock()
        service.events().get().execute.return_value = {
            "id": "e1",
            "summary": "Sync",
            "start": {"dateTime": "2026-06-10T15:00:00+00:00"},
            "end": {"dateTime": "2026-06-10T16:00:00+00:00"},
        }
        client = GoogleCalendarClient(google_config, service=service)
        ev = client.get_event("e1")
        assert ev is not None
        assert ev.title == "Sync"

    def test_get_event_cancelled_returns_none(self, google_config):
        service = MagicMock()
        service.events().get().execute.return_value = {
            "id": "e1",
            "status": "cancelled",
            "start": {"dateTime": "2026-06-10T15:00:00+00:00"},
            "end": {"dateTime": "2026-06-10T16:00:00+00:00"},
        }
        client = GoogleCalendarClient(google_config, service=service)
        assert client.get_event("e1") is None

    def test_get_event_missing_returns_none(self, google_config):
        service = MagicMock()
        service.events().get().execute.side_effect = Exception("404")
        client = GoogleCalendarClient(google_config, service=service)
        assert client.get_event("nope") is None


# ── 测试重定向 ──


class TestTestRedirect:
    def _make_agent(self, redirect_to, **kw):
        from unittest.mock import MagicMock

        from mail_agent.agent.orchestrator import MailAgent
        from mail_agent.config import load_config

        gmail = MagicMock()
        gmail.create_draft.return_value = "d1"
        gmail.send_reply.return_value = "s1"
        kw.setdefault("create_drafts", True)
        agent = MailAgent(
            load_config(),
            gmail_client=gmail,
            calendar_backend=MagicMock(),
            redirect_to=redirect_to,
            **kw,
        )
        return agent, gmail

    def _result(self):
        from mail_agent.models import (
            EmailAnalysis,
            EmailMessage,
            PriorityScore,
            ProcessingResult,
            ReplyDraft,
        )

        email = EmailMessage(
            message_id="<m@x>", sender="boss@company.com", gmail_id="g1"
        )
        res = ProcessingResult(
            email=email, analysis=EmailAnalysis(), priority=PriorityScore()
        )
        res.reply_draft = ReplyDraft(
            subject="Re: 进度", body="收到。", to=["boss@company.com"]
        )
        return res, email

    def test_redirect_rewrites_recipient_and_marks_real_target(self):
        agent, gmail = self._make_agent("test@qq.com")
        res, email = self._result()
        agent._deliver_reply(res, email, [])

        delivered = gmail.create_draft.call_args[0][0]
        assert delivered.to == ["test@qq.com"]
        assert "boss@company.com" in delivered.body  # 真实目标被标注
        assert "boss@company.com" in delivered.subject
        assert "TEST" in delivered.subject

    def test_records_draft_message_id(self):
        agent, gmail = self._make_agent(None)
        res, email = self._result()
        agent._deliver_reply(res, email, [])
        assert res.reply_delivery == "draft"
        assert res.reply_message_id == "d1"

    def test_records_sent_message_id(self):
        agent, gmail = self._make_agent(None, send_replies=True)
        res, email = self._result()
        agent._deliver_reply(res, email, [])
        assert res.reply_delivery == "sent"
        assert res.reply_message_id == "s1"

    def test_real_recipient_when_allowed(self):
        # 仅在显式 allow_real=True 且无重定向时，才发给真实收件人
        agent, gmail = self._make_agent(None, allow_real=True)
        res, email = self._result()
        agent._deliver_reply(res, email, [])

        delivered = gmail.create_draft.call_args[0][0]
        assert delivered.to == ["boss@company.com"]
        assert "TEST MODE" not in delivered.body

    def test_blocked_when_no_redirect_and_not_allowed(self):
        # 安全网：无重定向 + 未允许真实 → 拦截，不调用任何投递
        from unittest.mock import MagicMock

        from mail_agent.agent.orchestrator import MailAgent
        from mail_agent.config import AppConfig

        cfg = AppConfig()
        cfg.testing.redirect_to = ""  # 清空默认重定向
        gmail = MagicMock()
        agent = MailAgent(cfg, gmail_client=gmail, calendar_backend=MagicMock(),
                          create_drafts=True, allow_real=False)
        res, email = self._result()
        agent._deliver_reply(res, email, [])
        gmail.create_draft.assert_not_called()
        gmail.send_reply.assert_not_called()
        assert res.reply_delivery == "blocked:no-redirect"

    def test_redirect_applies_to_send_path(self):
        agent, gmail = self._make_agent("test@qq.com", send_replies=True)
        res, email = self._result()
        agent._deliver_reply(res, email, [])

        delivered = gmail.send_reply.call_args[0][0]
        assert delivered.to == ["test@qq.com"]


# ── 授权错误处理 ──


def test_get_credentials_missing_token_non_interactive(tmp_path):
    from mail_agent.gapi.auth import GoogleAuthError, get_credentials

    config = GoogleConfig(
        enabled=True,
        token_path=tmp_path / "token.json",
        credentials_path=tmp_path / "credentials.json",
    )
    with pytest.raises(GoogleAuthError):
        get_credentials(config, allow_interactive=False)


class TestBuildFlow:
    def _flow_cls(self):
        from google_auth_oauthlib.flow import InstalledAppFlow

        return InstalledAppFlow

    def test_valid_installed_json(self, tmp_path):
        import json

        from mail_agent.gapi.auth import _build_flow

        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "x.apps.googleusercontent.com",
                        "client_secret": "secret",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            )
        )
        cfg = GoogleConfig(enabled=True, credentials_path=creds)
        flow = _build_flow(cfg, creds, cfg.scopes, self._flow_cls())
        assert flow is not None

    def test_bare_client_id_raises_with_hint(self, tmp_path):
        from mail_agent.gapi.auth import GoogleAuthError, _build_flow

        creds = tmp_path / "credentials.json"
        creds.write_text("123-abc.apps.googleusercontent.com")
        cfg = GoogleConfig(enabled=True, credentials_path=creds)
        with pytest.raises(GoogleAuthError) as exc:
            _build_flow(cfg, creds, cfg.scopes, self._flow_cls())
        assert "client_secret" in str(exc.value)

    def test_env_fallback_when_no_file(self, tmp_path):
        from mail_agent.gapi.auth import _build_flow

        cfg = GoogleConfig(
            enabled=True,
            credentials_path=tmp_path / "nope.json",
            client_id="x.apps.googleusercontent.com",
            client_secret="secret",
        )
        flow = _build_flow(
            cfg, cfg.credentials_path, cfg.scopes, self._flow_cls()
        )
        assert flow is not None

    def test_no_file_no_env_raises(self, tmp_path):
        from mail_agent.gapi.auth import GoogleAuthError, _build_flow

        cfg = GoogleConfig(enabled=True, credentials_path=tmp_path / "nope.json")
        with pytest.raises(GoogleAuthError):
            _build_flow(cfg, cfg.credentials_path, cfg.scopes, self._flow_cls())
