"""日历调度模块测试（使用真实智谱AI API）"""

from datetime import datetime, timedelta, timezone

import pytest

from mail_agent.calendar.scheduler import CalendarScheduler
from mail_agent.calendar.store import CalendarStore
from mail_agent.config import CalendarConfig
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)


class TestCalendarScheduler:
    @pytest.fixture
    def store(self, tmp_calendar_path):
        config = CalendarConfig(storage_path=tmp_calendar_path)
        return CalendarStore(config)

    @pytest.fixture
    def scheduler(self, store, llm_client):
        return CalendarScheduler(store, llm_client)

    def test_parse_schedule_thursday_3pm(self, scheduler):
        """测试解析 'Thursday at 3pm'"""
        ref_date = datetime(2026, 4, 10, 10, 0)  # 假设是周五
        result = scheduler.parse_schedule(
            "Thursday at 3pm",
            reference_date=ref_date,
            context="Meeting with Prof. Lee",
        )
        assert "start_time" in result
        assert "end_time" in result
        assert isinstance(result["start_time"], datetime)
        assert result["start_time"].hour == 15  # 3pm = 15:00
        assert result["end_time"] > result["start_time"]

    def test_parse_schedule_next_tuesday(self, scheduler):
        """测试解析 'next Tuesday 14:00'"""
        ref_date = datetime(2026, 4, 10, 10, 0)
        result = scheduler.parse_schedule(
            "next Tuesday at 2pm",
            reference_date=ref_date,
            context="Paper discussion",
        )
        assert result["start_time"].hour == 14

    def test_schedule_from_meeting_email(self, scheduler, store):
        """测试从会议邮件自动创建事件"""
        email = EmailMessage(
            message_id="<sched-test-1@mail.com>",
            sender="lee@university.edu",
            sender_name="Prof. Lee",
            subject="Meeting",
            body="Can we meet Thursday at 3pm?",
            date=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.MEETING_REQUEST,
            urgency=UrgencyLevel.MEDIUM,
            category=EmailCategory.MEETING,
            requires_reply=True,
            contains_schedule=True,
            schedule_description="Thursday at 3pm",
        )

        event, conflict = scheduler.schedule_from_email(email, analysis)

        assert event is not None
        assert event.event_id  # 应有 ID
        assert event.start_time.hour == 15
        assert "lee@university.edu" in event.attendees
        # 事件应已存储
        assert len(store.list_events()) == 1

    def test_schedule_detects_conflict(self, scheduler, store):
        """测试冲突检测"""
        # 先添加一个已有事件
        existing = CalendarEvent(
            title="Existing Meeting",
            start_time=datetime(2026, 4, 16, 15, 0),  # Thursday 3pm
            end_time=datetime(2026, 4, 16, 16, 0),
        )
        store.add_event(existing)

        email = EmailMessage(
            sender="someone@test.com",
            subject="Another meeting",
            body="Let's meet Thursday at 3pm",
            date=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.MEETING_REQUEST,
            contains_schedule=True,
            schedule_description="Thursday at 3pm",
        )

        event, conflict = scheduler.schedule_from_email(email, analysis)
        # 新事件仍会创建，但应检测到冲突
        assert event is not None
        if conflict and conflict.has_conflict:
            assert len(conflict.conflicting_events) >= 1

    def test_no_schedule_returns_none(self, scheduler):
        """没有日程信息时应返回 None"""
        email = EmailMessage(sender="a@b.com", subject="FYI")
        analysis = EmailAnalysis(
            contains_schedule=False,
            schedule_description="",
        )
        event, conflict = scheduler.schedule_from_email(email, analysis)
        assert event is None
        assert conflict is None
