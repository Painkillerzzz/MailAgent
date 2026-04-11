"""Web API 端点测试"""

import pytest
from fastapi.testclient import TestClient

from mail_agent.web.app import web_app, result_store


@pytest.fixture
def client():
    result_store.clear()
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

    def test_calendar_events_after_demo(self, client):
        client.post("/api/demo")
        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        # 检查 FullCalendar 格式
        evt = events[0]
        assert "id" in evt
        assert "title" in evt
        assert "start" in evt
        assert "end" in evt
        assert "color" in evt
        assert "extendedProps" in evt

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/calendar/events/nonexistent")
        assert resp.status_code == 404


class TestRemindersAPI:
    def test_reminders_count_empty(self, client):
        resp = client.get("/api/reminders/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_reminders_count_after_demo(self, client):
        client.post("/api/demo")
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
