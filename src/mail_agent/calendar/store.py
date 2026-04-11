"""本地日历事件存储

使用 JSON 文件持久化日历事件，支持 CRUD 和冲突检测。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from mail_agent.config import CalendarConfig
from mail_agent.models import CalendarEvent, ScheduleConflict

logger = logging.getLogger(__name__)


class CalendarStore:
    """基于 JSON 的本地日历存储"""

    def __init__(self, config: CalendarConfig | None = None):
        if config is None:
            config = CalendarConfig()
        self._path = Path(config.storage_path)
        self._events: list[CalendarEvent] = []
        self._load()

    def _load(self):
        """从 JSON 文件加载事件"""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._events = [CalendarEvent.model_validate(e) for e in data]
                logger.debug("加载了 %d 个日历事件", len(self._events))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("日历数据加载失败: %s，将使用空日历", e)
                self._events = []
        else:
            self._events = []

    def _save(self):
        """持久化到 JSON 文件"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump(mode="json") for e in self._events]
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        """添加日历事件

        Args:
            event: 日历事件（如果 event_id 为空会自动生成）

        Returns:
            添加后的事件（含 event_id）
        """
        if not event.event_id:
            event.event_id = uuid.uuid4().hex[:12]
        self._events.append(event)
        self._save()
        logger.info("创建日历事件: %s (%s)", event.title, event.event_id)
        return event

    def remove_event(self, event_id: str) -> bool:
        """删除日历事件"""
        before = len(self._events)
        self._events = [e for e in self._events if e.event_id != event_id]
        if len(self._events) < before:
            self._save()
            return True
        return False

    def get_event(self, event_id: str) -> CalendarEvent | None:
        """根据 ID 获取事件"""
        for e in self._events:
            if e.event_id == event_id:
                return e
        return None

    def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CalendarEvent]:
        """列出时间范围内的事件

        Args:
            start: 起始时间（包含），None 表示不限
            end: 结束时间（包含），None 表示不限

        Returns:
            匹配的事件列表，按开始时间排序
        """
        results = []
        for e in self._events:
            if start and e.end_time < start:
                continue
            if end and e.start_time > end:
                continue
            results.append(e)
        return sorted(results, key=lambda e: e.start_time)

    def check_conflict(
        self, start_time: datetime, end_time: datetime
    ) -> ScheduleConflict:
        """检查时间段是否有冲突

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            ScheduleConflict 冲突信息
        """
        conflicts = []
        for e in self._events:
            # 两个时间段重叠的条件: start1 < end2 and start2 < end1
            if e.start_time < end_time and start_time < e.end_time:
                conflicts.append(e)
        return ScheduleConflict(
            has_conflict=len(conflicts) > 0,
            conflicting_events=conflicts,
        )

    def clear(self):
        """清空所有事件"""
        self._events.clear()
        self._save()
