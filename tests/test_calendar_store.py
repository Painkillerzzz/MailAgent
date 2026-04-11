"""日历存储模块测试"""

from datetime import datetime, timedelta

import pytest

from mail_agent.calendar.store import CalendarStore
from mail_agent.config import CalendarConfig
from mail_agent.models import CalendarEvent


class TestCalendarStore:
    @pytest.fixture
    def store(self, tmp_calendar_path):
        config = CalendarConfig(storage_path=tmp_calendar_path)
        return CalendarStore(config)

    @pytest.fixture
    def event_a(self):
        now = datetime.now()
        return CalendarEvent(
            title="Event A",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            attendees=["a@test.com"],
        )

    @pytest.fixture
    def event_b(self):
        now = datetime.now()
        return CalendarEvent(
            title="Event B",
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            attendees=["b@test.com"],
        )

    def test_add_event(self, store, event_a):
        result = store.add_event(event_a)
        assert result.event_id  # 应自动生成 ID
        assert result.title == "Event A"

    def test_add_event_preserves_id(self, store):
        now = datetime.now()
        event = CalendarEvent(
            event_id="custom-id",
            title="Custom",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )
        result = store.add_event(event)
        assert result.event_id == "custom-id"

    def test_get_event(self, store, event_a):
        added = store.add_event(event_a)
        found = store.get_event(added.event_id)
        assert found is not None
        assert found.title == "Event A"

    def test_get_event_not_found(self, store):
        assert store.get_event("nonexistent") is None

    def test_remove_event(self, store, event_a):
        added = store.add_event(event_a)
        assert store.remove_event(added.event_id) is True
        assert store.get_event(added.event_id) is None

    def test_remove_nonexistent(self, store):
        assert store.remove_event("nonexistent") is False

    def test_list_events_all(self, store, event_a, event_b):
        store.add_event(event_a)
        store.add_event(event_b)
        events = store.list_events()
        assert len(events) == 2

    def test_list_events_time_range(self, store):
        now = datetime.now()
        e1 = CalendarEvent(
            title="Past",
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=2, hours=-1),
        )
        e2 = CalendarEvent(
            title="Future",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        store.add_event(e1)
        store.add_event(e2)

        future_events = store.list_events(start=now)
        assert len(future_events) == 1
        assert future_events[0].title == "Future"

    def test_list_events_sorted(self, store):
        now = datetime.now()
        e_late = CalendarEvent(
            title="Late",
            start_time=now + timedelta(hours=5),
            end_time=now + timedelta(hours=6),
        )
        e_early = CalendarEvent(
            title="Early",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        store.add_event(e_late)
        store.add_event(e_early)

        events = store.list_events()
        assert events[0].title == "Early"
        assert events[1].title == "Late"

    def test_check_conflict_no_conflict(self, store, event_a):
        store.add_event(event_a)
        now = datetime.now()
        conflict = store.check_conflict(
            now + timedelta(hours=5),
            now + timedelta(hours=6),
        )
        assert conflict.has_conflict is False

    def test_check_conflict_overlap(self, store, event_a):
        store.add_event(event_a)
        now = datetime.now()
        # 与 event_a (now+1h ~ now+2h) 重叠
        conflict = store.check_conflict(
            now + timedelta(hours=1, minutes=30),
            now + timedelta(hours=2, minutes=30),
        )
        assert conflict.has_conflict is True
        assert len(conflict.conflicting_events) == 1

    def test_check_conflict_exact_overlap(self, store, event_a):
        store.add_event(event_a)
        conflict = store.check_conflict(
            event_a.start_time,
            event_a.end_time,
        )
        assert conflict.has_conflict is True

    def test_persistence(self, tmp_calendar_path):
        config = CalendarConfig(storage_path=tmp_calendar_path)
        now = datetime.now()

        # 写入
        store1 = CalendarStore(config)
        store1.add_event(CalendarEvent(
            title="Persistent",
            start_time=now,
            end_time=now + timedelta(hours=1),
        ))

        # 重新加载
        store2 = CalendarStore(config)
        events = store2.list_events()
        assert len(events) == 1
        assert events[0].title == "Persistent"

    def test_clear(self, store, event_a, event_b):
        store.add_event(event_a)
        store.add_event(event_b)
        assert len(store.list_events()) == 2
        store.clear()
        assert len(store.list_events()) == 0

    def test_corrupt_file_handled(self, tmp_calendar_path):
        tmp_calendar_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_calendar_path.write_text("not valid json")
        config = CalendarConfig(storage_path=tmp_calendar_path)
        store = CalendarStore(config)
        assert len(store.list_events()) == 0  # 应优雅处理
