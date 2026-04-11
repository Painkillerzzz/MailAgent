"""ICS 导出模块测试"""

from datetime import datetime, timedelta

import pytest

from mail_agent.calendar.ics_export import event_to_ics, events_to_ics, export_to_file
from mail_agent.models import CalendarEvent


class TestICSExport:
    @pytest.fixture
    def sample_event(self):
        return CalendarEvent(
            event_id="ics-test-001",
            title="Test Meeting",
            description="A test meeting",
            start_time=datetime(2026, 4, 16, 15, 0),
            end_time=datetime(2026, 4, 16, 16, 0),
            location="Room 101",
            attendees=["a@test.com", "b@test.com"],
        )

    def test_single_event_to_ics(self, sample_event):
        ics = event_to_ics(sample_event)
        assert "BEGIN:VCALENDAR" in ics
        assert "BEGIN:VEVENT" in ics
        assert "END:VEVENT" in ics
        assert "END:VCALENDAR" in ics
        assert "Test Meeting" in ics
        assert "ics-test-001" in ics
        assert "Room 101" in ics

    def test_ics_contains_attendees(self, sample_event):
        ics = event_to_ics(sample_event)
        assert "a@test.com" in ics
        assert "b@test.com" in ics

    def test_multiple_events_to_ics(self):
        events = [
            CalendarEvent(
                event_id=f"evt-{i}",
                title=f"Event {i}",
                start_time=datetime(2026, 4, 16 + i, 10, 0),
                end_time=datetime(2026, 4, 16 + i, 11, 0),
            )
            for i in range(3)
        ]
        ics = events_to_ics(events)
        assert ics.count("BEGIN:VEVENT") == 3
        assert ics.count("END:VEVENT") == 3

    def test_export_to_file(self, sample_event, tmp_path):
        filepath = tmp_path / "test.ics"
        result = export_to_file([sample_event], filepath)
        assert result.exists()
        content = result.read_text()
        assert "BEGIN:VCALENDAR" in content
        assert "Test Meeting" in content

    def test_export_creates_parent_dirs(self, sample_event, tmp_path):
        filepath = tmp_path / "subdir" / "deep" / "test.ics"
        result = export_to_file([sample_event], filepath)
        assert result.exists()

    def test_empty_events_list(self):
        ics = events_to_ics([])
        assert "BEGIN:VCALENDAR" in ics
        assert "VEVENT" not in ics
