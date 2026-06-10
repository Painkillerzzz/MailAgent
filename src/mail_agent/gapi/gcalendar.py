"""Google Calendar API 客户端

与本地 CalendarStore 接口兼容（add_event / check_conflict / list_events），
可在 CalendarScheduler 中直接替换为真实的 Google Calendar。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dateutil import parser as dateutil_parser

from mail_agent.config import GoogleConfig
from mail_agent.models import CalendarEvent, ScheduleConflict

logger = logging.getLogger(__name__)


def _to_rfc3339(dt: datetime) -> str:
    """转为带时区的 RFC3339 字符串（无时区按本地时区处理）"""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def _parse_event_dt(node: dict) -> datetime:
    """解析 Google 事件的 start/end 节点（dateTime 或 date 全天）"""
    if "dateTime" in node:
        return dateutil_parser.parse(node["dateTime"])
    # 全天事件只有 date
    return dateutil_parser.parse(node["date"])


class GoogleCalendarClient:
    """Google Calendar API 客户端"""

    def __init__(self, config: GoogleConfig, credentials=None, service=None):
        self._config = config
        self._calendar_id = config.calendar_id
        if service is not None:
            self._service = service
            return
        if credentials is None:
            from mail_agent.gapi.auth import get_credentials

            credentials = get_credentials(config)
        from googleapiclient.discovery import build

        self._service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        """在 Google Calendar 创建事件，回填 event_id"""
        body = {
            "summary": event.title,
            "description": event.description,
            "start": {"dateTime": _to_rfc3339(event.start_time)},
            "end": {"dateTime": _to_rfc3339(event.end_time)},
        }
        if event.location:
            body["location"] = event.location
        if event.attendees:
            body["attendees"] = [{"email": a} for a in event.attendees]

        created = (
            self._service.events()
            .insert(calendarId=self._calendar_id, body=body)
            .execute()
        )
        event.event_id = created.get("id", "")
        logger.info("Google Calendar 已创建事件: %s (%s)", event.title, event.event_id)
        return event

    def get_event(self, event_id: str) -> CalendarEvent | None:
        """按 ID 读回单个事件（用于读写回读验证），不存在返回 None"""
        try:
            item = (
                self._service.events()
                .get(calendarId=self._calendar_id, eventId=event_id)
                .execute()
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("读取事件 %s 失败: %s", event_id, e)
            return None
        # 已取消的事件视为不存在
        if item.get("status") == "cancelled":
            return None
        return self._to_calendar_event(item)

    def remove_event(self, event_id: str) -> bool:
        """删除 Google Calendar 事件"""
        try:
            self._service.events().delete(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("删除事件失败 %s: %s", event_id, e)
            return False

    def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CalendarEvent]:
        """列出时间范围内的事件"""
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=1)
        if end is None:
            end = datetime.now(timezone.utc) + timedelta(days=30)

        resp = (
            self._service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=_to_rfc3339(start),
                timeMax=_to_rfc3339(end),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events: list[CalendarEvent] = []
        for item in resp.get("items", []):
            try:
                events.append(self._to_calendar_event(item))
            except Exception as e:  # noqa: BLE001
                logger.warning("解析日历事件失败: %s", e)
        return events

    def check_conflict(
        self, start_time: datetime, end_time: datetime
    ) -> ScheduleConflict:
        """检查时间段是否与现有事件冲突"""
        # 拉取覆盖该时段的事件再做精确重叠判断
        existing = self.list_events(
            start=start_time - timedelta(days=1),
            end=end_time + timedelta(days=1),
        )
        conflicts = []
        for e in existing:
            s, t = _ensure_aware(start_time), _ensure_aware(end_time)
            es, et = _ensure_aware(e.start_time), _ensure_aware(e.end_time)
            if es < t and s < et:
                conflicts.append(e)
        return ScheduleConflict(
            has_conflict=len(conflicts) > 0,
            conflicting_events=conflicts,
        )

    def _to_calendar_event(self, item: dict) -> CalendarEvent:
        attendees = [a.get("email", "") for a in item.get("attendees", [])]
        return CalendarEvent(
            event_id=item.get("id", ""),
            title=item.get("summary", "(无标题)"),
            description=item.get("description", ""),
            start_time=_parse_event_dt(item["start"]),
            end_time=_parse_event_dt(item["end"]),
            location=item.get("location", ""),
            attendees=[a for a in attendees if a],
        )


def _ensure_aware(dt: datetime) -> datetime:
    """确保 datetime 带时区，便于跨时区比较"""
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt
