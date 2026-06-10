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

        event, conflict = scheduler.schedule_from_email(email, analysis, write=True)

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

        event, conflict = scheduler.schedule_from_email(email, analysis, write=True)
        # 安全行为：冲突且未自动避让时不创建事件（避免双重预订），仅返回冲突
        assert conflict is not None and conflict.has_conflict
        assert len(conflict.conflicting_events) >= 1
        assert event is None
        # 不应写入第二个事件
        assert len(store.list_events()) == 1

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


# ── 空闲感知改期建议（确定性，不调用 LLM）──


class _FakeStore:
    """内存日历，仅实现 find_free_slots 所需的 list_events"""

    def __init__(self, events):
        self._e = events

    def list_events(self, start=None, end=None):
        return [
            e for e in self._e
            if (end is None or e.start_time < end)
            and (start is None or e.end_time > start)
        ]


def _evt(y, mo, d, h1, h2, title="Busy"):
    tz = timezone.utc
    return CalendarEvent(
        title=title,
        start_time=datetime(y, mo, d, h1, 0, tzinfo=tz),
        end_time=datetime(y, mo, d, h2, 0, tzinfo=tz),
    )


class TestFindFreeSlots:
    def _sched(self, events, **cfg):
        return CalendarScheduler(
            _FakeStore(events), llm_client=None, config=CalendarConfig(**cfg)
        )

    def test_suggests_non_conflicting_slots(self):
        tz = timezone.utc
        busy = [_evt(2026, 6, 10, 10, 11)]
        sch = self._sched(busy, suggest_count=3)
        slots = sch.find_free_slots(
            datetime(2026, 6, 10, 10, 0, tzinfo=tz),
            datetime(2026, 6, 10, 11, 0, tzinfo=tz),
        )
        assert len(slots) == 3
        # 没有任何建议与 busy(10-11) 重叠
        for s in slots:
            assert not (s.start_time < busy[0].end_time and busy[0].start_time < s.end_time)

    def test_sorted_by_closeness(self):
        tz = timezone.utc
        sch = self._sched([_evt(2026, 6, 10, 10, 11)], suggest_count=2)
        slots = sch.find_free_slots(
            datetime(2026, 6, 10, 10, 0, tzinfo=tz),
            datetime(2026, 6, 10, 11, 0, tzinfo=tz),
        )
        # 最近的空闲应是 09:00 或 11:00（距 10:00 各 1 小时）
        assert slots[0].start_time.hour in (9, 11)

    def test_respects_work_hours(self):
        tz = timezone.utc
        sch = self._sched([], work_start_hour=9, work_end_hour=18, suggest_count=10)
        slots = sch.find_free_slots(
            datetime(2026, 6, 10, 10, 0, tzinfo=tz),
            datetime(2026, 6, 10, 11, 0, tzinfo=tz),
        )
        for s in slots:
            assert 9 <= s.start_time.hour
            assert s.end_time.hour <= 18

    def test_rolls_to_next_day_when_full(self):
        tz = timezone.utc
        # 6/10 整个工作时间被占满
        full = [_evt(2026, 6, 10, 9, 18, "All day busy")]
        sch = self._sched(full, suggest_count=2, search_days=3)
        slots = sch.find_free_slots(
            datetime(2026, 6, 10, 10, 0, tzinfo=tz),
            datetime(2026, 6, 10, 11, 0, tzinfo=tz),
        )
        assert slots, "应顺延到后续日期给出建议"
        assert all(s.start_time.day != 10 for s in slots)

    def test_conflict_populates_suggestions(self):
        from unittest.mock import MagicMock

        from mail_agent.models import EmailAnalysis, EmailMessage

        tz = timezone.utc
        busy = [_evt(2026, 6, 10, 15, 16)]
        sch = self._sched(busy, suggest_count=3)
        # store 需要 check_conflict + add_event；用真实重叠逻辑的桩
        store = sch._store
        store.check_conflict = lambda s, e: __import__(
            "mail_agent.models", fromlist=["ScheduleConflict"]
        ).ScheduleConflict(has_conflict=True, conflicting_events=busy)
        store.add_event = lambda ev: ev
        # 跳过 LLM 时间解析，直接桩定 parse_schedule
        sch.parse_schedule = lambda *a, **k: {
            "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=tz),
            "end_time": datetime(2026, 6, 10, 16, 0, tzinfo=tz),
            "title": "Meeting",
        }
        email = EmailMessage(subject="meet", sender="a@x.com")
        analysis = EmailAnalysis(contains_schedule=True, schedule_description="3pm")
        event, conflict = sch.schedule_from_email(email, analysis)
        assert conflict.has_conflict is True
        assert len(conflict.suggested_slots) > 0
        for s in conflict.suggested_slots:
            assert not (s.start_time < busy[0].end_time and busy[0].start_time < s.end_time)
