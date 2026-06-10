"""Web API 端点测试"""

import pytest
from fastapi.testclient import TestClient

from mail_agent.web.app import web_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """完全隔离的测试客户端：临时存储 + 不碰真实 LLM/Google/data。"""
    from mail_agent.web import api as webapi
    from mail_agent.web.result_store import ResultStore
    from mail_agent.web.settings_store import SettingsStore

    # 设置/结果存储指向临时目录，绝不动真实 data/
    monkeypatch.setattr(
        webapi, "_settings_store", SettingsStore(path=tmp_path / "settings.json")
    )
    monkeypatch.setattr(
        webapi, "_result_store", ResultStore(path=tmp_path / "results.json")
    )

    # demo/analyze 不调用真实 LLM：用桩 agent 直接产出确定性结果
    class _StubAgent:
        def process_emails(self, emails):
            from mail_agent.models import (
                EmailAnalysis, PriorityScore, ProcessingResult,
            )
            return [
                ProcessingResult(email=e, analysis=EmailAnalysis(summary="stub"),
                                 priority=PriorityScore())
                for e in emails
            ]

        def process_email(self, email):
            return self.process_emails([email])[0]

    monkeypatch.setattr(webapi, "_get_agent", lambda: _StubAgent())

    # 日历后端用本地临时存储，绝不连真实 Google Calendar
    from mail_agent.calendar.store import CalendarStore
    from mail_agent.config import CalendarConfig

    cal = CalendarStore(CalendarConfig(storage_path=tmp_path / "cal.json"))
    monkeypatch.setattr(webapi, "_get_calendar_store", lambda config=None: cal)

    # 默认不进行真实 Google 授权（需要的测试自行覆盖）
    from mail_agent.gapi.auth import GoogleAuthError

    def _no_creds(*a, **k):
        raise GoogleAuthError("test isolation")

    monkeypatch.setattr("mail_agent.gapi.auth.get_credentials", _no_creds)
    return TestClient(web_app)


class TestPageRoutes:
    def test_emails_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Mail Agent" in resp.text
        assert "filter-bar" in resp.text

    def test_calendar_page(self, client):
        resp = client.get("/calendar")
        assert resp.status_code == 200
        assert "fullcalendar" in resp.text
        assert "fc-calendar" in resp.text

    def test_reminders_page(self, client):
        resp = client.get("/reminders")
        assert resp.status_code == 200
        assert "Urgent Emails" in resp.text

    def test_settings_page(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "settings.js" in resp.text
        assert "API Key" in resp.text

    def test_static_css(self, client):
        resp = client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert "color-primary" in resp.text

    def test_static_js(self, client):
        resp = client.get("/static/js/app.js")
        assert resp.status_code == 200
        assert "showToast" in resp.text


class TestEmailsAPI:
    def test_emails_partial_empty(self, client):
        resp = client.get("/api/emails/partial")
        assert resp.status_code == 200
        assert "empty-state" in resp.text

    def test_demo(self, client):
        resp = client.post("/api/demo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_emails_partial_after_demo(self, client):
        client.post("/api/demo")
        resp = client.get("/api/emails/partial")
        assert resp.status_code == 200
        assert "email-card" in resp.text

    def test_filter_urgency(self, client):
        client.post("/api/demo")
        resp = client.get("/api/emails/partial?urgency=low")
        assert resp.status_code == 200
        # 只有 low urgency 的结果
        assert "badge-low" in resp.text or "empty-state" in resp.text

    def test_process_email(self, client):
        resp = client.post(
            "/api/emails/process",
            data={
                "sender": "test@test.com",
                "sender_name": "Tester",
                "subject": "Hello",
                "body": "Just a test message.",
            },
        )
        assert resp.status_code == 200

    def test_search(self, client):
        client.post("/api/demo")
        resp = client.get("/api/emails/partial?search=Meeting")
        assert resp.status_code == 200


class TestCalendarAPI:
    def test_calendar_events_empty(self, client):
        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_calendar_events_with_data(self, client):
        # 直接向（隔离的）日历后端播种一个事件，再校验端点输出 FullCalendar 格式
        from datetime import datetime, timedelta

        from mail_agent.models import CalendarEvent
        from mail_agent.web import api as webapi

        now = datetime.now()
        webapi._get_calendar_store().add_event(
            CalendarEvent(title="测试会议", start_time=now + timedelta(hours=1),
                          end_time=now + timedelta(hours=2))
        )
        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        evt = events[0]
        for k in ("id", "title", "start", "end", "color", "extendedProps"):
            assert k in evt

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/calendar/events/nonexistent")
        assert resp.status_code == 404


class TestRemindersAPI:
    def test_reminders_count_empty(self, client):
        resp = client.get("/api/reminders/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_reminders_count_with_urgent(self, client):
        # 播种一封高优先级邮件，校验提醒计数反映之
        from mail_agent.models import (
            EmailAnalysis, EmailMessage, PriorityScore, ProcessingResult,
            UrgencyLevel,
        )
        from mail_agent.web import api as webapi

        webapi._get_result_store().add(ProcessingResult(
            email=EmailMessage(message_id="<u@x>", subject="紧急"),
            analysis=EmailAnalysis(urgency=UrgencyLevel.HIGH),
            priority=PriorityScore(level=UrgencyLevel.HIGH, total_score=9.0),
        ))
        resp = client.get("/api/reminders/count")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_reminders_json(self, client):
        client.post("/api/demo")
        resp = client.get("/api/reminders")
        assert resp.status_code == 200
        data = resp.json()
        assert "urgent_emails" in data
        assert "upcoming_deadlines" in data
        assert "todays_events" in data

    def test_reminders_partial_urgent(self, client):
        resp = client.get("/api/reminders/partial?section=urgent")
        assert resp.status_code == 200

    def test_reminders_partial_deadlines(self, client):
        resp = client.get("/api/reminders/partial?section=deadlines")
        assert resp.status_code == 200

    def test_reminders_partial_today(self, client):
        resp = client.get("/api/reminders/partial?section=today")
        assert resp.status_code == 200


class TestSettingsAPI:
    def test_get_settings(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm" in data
        assert "imap" in data
        assert "user" in data

    def test_save_settings(self, client):
        resp = client.post(
            "/api/settings",
            json={
                "llm": {"model": "glm-4", "temperature": 0.5},
                "user": {"name": "New Name"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_test_llm(self, client):
        resp = client.post(
            "/api/settings/test-llm",
            json={"api_key": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "message" in data

    def test_settings_includes_google_and_base_url(self, client, monkeypatch):
        from mail_agent.gapi.auth import GoogleAuthError

        def _raise(*a, **k):
            raise GoogleAuthError("no token")

        monkeypatch.setattr("mail_agent.gapi.auth.get_credentials", _raise)
        data = client.get("/api/settings").json()
        assert "google" in data
        assert "testing" in data
        assert "base_url" in data["llm"]
        assert data["google"]["authorized"] is False


# ── Google / 自检 端点 ──


class _FakeGmailWeb:
    def __init__(self, *a, **k):
        self.drafts = {}
        self.sent = []

    def fetch_unread(self, limit=10):
        return []

    def create_draft(self, reply, original=None):
        from mail_agent.models import EmailMessage

        did = f"d-{len(self.drafts) + 1}"
        self.drafts[did] = EmailMessage(
            gmail_id=did, subject=reply.subject, body=reply.body,
            recipients=list(reply.to),
        )
        return did

    def get_draft(self, did):
        return self.drafts[did]

    def list_drafts(self, limit=50):
        return [{"id": k} for k in self.drafts]

    def delete_draft(self, did):
        self.drafts.pop(did, None)

    def send_reply(self, reply, original=None):
        from mail_agent.models import EmailMessage

        sid = f"s-{len(self.sent) + 1}"
        self.sent.append(
            EmailMessage(gmail_id=sid, subject=reply.subject, recipients=list(reply.to))
        )
        return sid

    def fetch_query(self, q, limit=50):
        token = q.split()[-1]
        return [m for m in self.sent if token in (m.subject or "")]


class _FakeCalWeb:
    def __init__(self, *a, **k):
        self.events = {}

    def add_event(self, e):
        e.event_id = f"evt-{len(self.events) + 1}"
        self.events[e.event_id] = e
        return e

    def get_event(self, eid):
        return self.events.get(eid)

    def list_events(self, start=None, end=None):
        return list(self.events.values())

    def remove_event(self, eid):
        return self.events.pop(eid, None) is not None


@pytest.fixture
def patch_google(monkeypatch):
    monkeypatch.setattr(
        "mail_agent.gapi.auth.get_credentials", lambda *a, **k: "creds"
    )
    monkeypatch.setattr("mail_agent.gapi.gmail.GmailClient", _FakeGmailWeb)
    monkeypatch.setattr(
        "mail_agent.gapi.gcalendar.GoogleCalendarClient", _FakeCalWeb
    )


def _disabled_config():
    from mail_agent.config import AppConfig

    cfg = AppConfig()
    cfg.google.enabled = False
    cfg.imap.host = ""
    return cfg


class TestGoogleAPI:
    def test_google_status(self, client, monkeypatch):
        monkeypatch.setattr(
            "mail_agent.gapi.auth.get_credentials", lambda *a, **k: "creds"
        )
        data = client.get("/api/google/status").json()
        assert "enabled" in data
        assert "authorized" in data

    def test_selfcheck_happy_path(self, client, patch_google):
        resp = client.post("/api/selfcheck", json={"send": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        names = {r["name"] for r in data["results"]}
        assert {"calendar_roundtrip", "draft_roundtrip"} <= names

    def test_selfcheck_with_send(self, client, patch_google):
        data = client.post("/api/selfcheck", json={"send": True}).json()
        assert data["success"] is True
        assert any(r["name"] == "send_roundtrip" for r in data["results"])

    def test_selfcheck_disabled(self, client, monkeypatch):
        monkeypatch.setattr(
            "mail_agent.web.api.load_config", _disabled_config
        )
        resp = client.post("/api/selfcheck", json={})
        assert resp.status_code == 400

    def test_fetch_google_no_unread(self, client, patch_google):
        resp = client.post("/api/emails/fetch", json={"limit": 5, "test": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 0

    def test_fetch_disabled_no_imap(self, client, monkeypatch):
        monkeypatch.setattr(
            "mail_agent.web.api.load_config", _disabled_config
        )
        resp = client.post("/api/emails/fetch", json={"limit": 5})
        assert resp.status_code == 400
