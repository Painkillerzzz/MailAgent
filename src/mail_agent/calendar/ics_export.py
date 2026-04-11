"""ICS (iCalendar) 导出模块"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from icalendar import Calendar, Event

from mail_agent.models import CalendarEvent


def event_to_ics(event: CalendarEvent) -> str:
    """将单个事件转为 ICS 字符串"""
    cal = Calendar()
    cal.add("prodid", "-//MailAgent//EN")
    cal.add("version", "2.0")

    ics_event = Event()
    ics_event.add("uid", event.event_id)
    ics_event.add("summary", event.title)
    ics_event.add("description", event.description)
    ics_event.add("dtstart", event.start_time)
    ics_event.add("dtend", event.end_time)
    if event.location:
        ics_event.add("location", event.location)
    for attendee in event.attendees:
        ics_event.add("attendee", f"mailto:{attendee}")
    ics_event.add("created", event.created_at)

    cal.add_component(ics_event)
    return cal.to_ical().decode("utf-8")


def events_to_ics(events: list[CalendarEvent]) -> str:
    """将多个事件导出为一个 ICS 字符串"""
    cal = Calendar()
    cal.add("prodid", "-//MailAgent//EN")
    cal.add("version", "2.0")

    for event in events:
        ics_event = Event()
        ics_event.add("uid", event.event_id)
        ics_event.add("summary", event.title)
        ics_event.add("description", event.description)
        ics_event.add("dtstart", event.start_time)
        ics_event.add("dtend", event.end_time)
        if event.location:
            ics_event.add("location", event.location)
        for attendee in event.attendees:
            ics_event.add("attendee", f"mailto:{attendee}")
        ics_event.add("created", event.created_at)
        cal.add_component(ics_event)

    return cal.to_ical().decode("utf-8")


def export_to_file(events: list[CalendarEvent], path: str | Path) -> Path:
    """导出事件到 .ics 文件"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ics_content = events_to_ics(events)
    path.write_text(ics_content, encoding="utf-8")
    return path
