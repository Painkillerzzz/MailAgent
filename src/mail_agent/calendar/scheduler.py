"""日历调度模块

解析邮件中的时间信息并自动创建/检查日历事件。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser

from mail_agent.calendar.store import CalendarStore
from mail_agent.config import CalendarConfig
from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailMessage,
    ScheduleConflict,
    TimeSlot,
)

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    """确保 datetime 带时区，便于跨时区比较"""
    return dt if dt.tzinfo is not None else dt.astimezone()


def _overlaps_any(start: datetime, end: datetime, events) -> bool:
    s, e = _aware(start), _aware(end)
    for ev in events:
        if _aware(ev.start_time) < e and s < _aware(ev.end_time):
            return True
    return False

TIME_PARSE_SYSTEM_PROMPT = """You are a date/time parser. Given a schedule description and a reference date, extract the exact start datetime and end datetime.

Respond with ONLY a JSON object:
{
  "start_time": "YYYY-MM-DDTHH:MM:SS",
  "end_time": "YYYY-MM-DDTHH:MM:SS",
  "title": "short event title"
}

Rules:
- Use the reference date to resolve relative dates (e.g., "next Thursday", "tomorrow")
- DURATION: if the text states how long it lasts, set end_time = start_time + that duration. Parse natural-language durations, e.g.:
    "15 minutes" / "just 15 min" / "a quarter hour" -> 15 min
    "half an hour" / "30 minutes" / "30 min" -> 30 min
    "45 minutes" / "about 45 min" / "three quarters of an hour" -> 45 min
    "an hour" / "one hour" / "~1h" -> 60 min
    "90 minutes" / "an hour and a half" -> 90 min
- Only if NEITHER an explicit end time NOR a duration is mentioned, assume a 1-hour duration
- If only a day is mentioned without time, use 09:00 as default start time
- Use 24-hour format
- title should be a short descriptive event title based on the context"""


class CalendarScheduler:
    """日历调度器：解析时间、检查冲突、创建事件"""

    def __init__(
        self,
        store: CalendarStore,
        llm_client: LLMClient,
        config: CalendarConfig | None = None,
        auto_resolve_conflicts: bool = False,
    ):
        self._store = store
        self._llm = llm_client
        self._config = config or CalendarConfig()
        # 冲突时是否自动把事件落到最近空闲槽（批量排程场景用）
        self._auto_resolve = auto_resolve_conflicts

    def find_free_slots(
        self,
        desired_start: datetime,
        desired_end: datetime,
        ref_now: datetime | None = None,
    ) -> list[TimeSlot]:
        """在日历空闲处找出靠近期望时间、不与已有事件冲突的可行时段

        在配置的工作时间窗口内、未来 search_days 天范围按粒度扫描，
        返回离期望时间最近的若干个空闲时段。

        Args:
            desired_start: 期望开始时间
            desired_end: 期望结束时间
            ref_now: 参考“当前时刻”，早于它的时段视为过去而不建议。
                默认取系统当前时间；测试可注入以获得确定性结果。

        Returns:
            按与期望时间接近程度排序的 TimeSlot 列表
        """
        cfg = self._config
        # 保持输入的 tz 特性（naive/aware）一致，避免与存储事件比较时报错；
        # 仅在做时间差/排序时统一归一。
        ds = desired_start
        dur = desired_end - desired_start
        if dur <= timedelta(0):
            dur = timedelta(hours=1)
        gran = timedelta(minutes=max(5, cfg.slot_granularity_min))

        # 一次性拉取整个搜索窗口的事件（避免每天一次 N+1 调用）
        win_start = ds.replace(
            hour=cfg.work_start_hour, minute=0, second=0, microsecond=0
        )
        win_end = (ds + timedelta(days=cfg.search_days)).replace(
            hour=cfg.work_end_hour, minute=0, second=0, microsecond=0
        )
        try:
            events = self._store.list_events(win_start, win_end)
        except Exception as e:  # noqa: BLE001
            logger.warning("查询空闲时段失败: %s", e)
            events = []

        # 不建议早于参考时刻的（过去）时段；ref_now 可注入以便测试确定性
        ref_now = _aware(ref_now) if ref_now is not None else datetime.now().astimezone()
        found: list[TimeSlot] = []
        for off in range(0, cfg.search_days + 1):
            day = ds + timedelta(days=off)
            ws = day.replace(
                hour=cfg.work_start_hour, minute=0, second=0, microsecond=0
            )
            we = day.replace(
                hour=cfg.work_end_hour, minute=0, second=0, microsecond=0
            )
            t = ws
            while t + dur <= we:
                if _aware(t) >= ref_now and not _overlaps_any(t, t + dur, events):
                    found.append(TimeSlot(start_time=t, end_time=t + dur))
                t += gran

        found.sort(
            key=lambda s: abs(
                (_aware(s.start_time) - _aware(desired_start)).total_seconds()
            )
        )
        out: list[TimeSlot] = []
        seen: set[str] = set()
        for s in found:
            key = _aware(s.start_time).isoformat()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= cfg.suggest_count:
                break
        return out

    def parse_schedule(
        self,
        schedule_description: str,
        reference_date: datetime | None = None,
        context: str = "",
    ) -> dict:
        """用 LLM 解析时间描述为精确时间

        Args:
            schedule_description: 时间描述文本（如 "Thursday at 3pm"）
            reference_date: 参考日期（用于解析相对日期）
            context: 邮件上下文（帮助生成标题）

        Returns:
            包含 start_time, end_time, title 的字典
        """
        if reference_date is None:
            reference_date = datetime.now()

        messages = [
            {"role": "system", "content": TIME_PARSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Reference date: {reference_date.strftime('%Y-%m-%d %A')}\n"
                    f"Schedule description: {schedule_description}\n"
                    f"Context: {context}"
                ),
            },
        ]

        data = self._llm.chat_json(messages, temperature=0.0)
        if not isinstance(data, dict) or not data.get("start_time") or not data.get("end_time"):
            raise ValueError(f"时间解析结果缺少 start_time/end_time: {data!r}")
        return {
            "start_time": dateutil_parser.parse(data["start_time"]),
            "end_time": dateutil_parser.parse(data["end_time"]),
            "title": data.get("title") or "Meeting",
        }

    def schedule_from_email(
        self,
        email_msg: EmailMessage,
        analysis: EmailAnalysis,
        write: bool = False,
    ) -> tuple[CalendarEvent | None, ScheduleConflict | None]:
        """根据邮件分析结果自动调度日历事件

        Args:
            email_msg: 邮件消息
            analysis: 邮件分析结果
            write: 为 True 才真正写入日历后端；否则只计算事件/冲突用于展示（安全默认）

        Returns:
            (事件或None, 冲突信息或None)。未解决的冲突返回 (None, conflict)，不写日历。
        """
        if not analysis.contains_schedule or not analysis.schedule_description:
            return None, None

        try:
            parsed = self.parse_schedule(
                analysis.schedule_description,
                reference_date=email_msg.date or datetime.now(),
                context=(
                    f"Email from {email_msg.sender_name}, subject: {email_msg.subject}.\n"
                    f"Full email body (use it to determine the DURATION):\n"
                    f"{email_msg.body[:600]}"
                ),
            )
        except Exception as e:
            logger.error("时间解析失败: %s", e)
            return None, None

        start_time = parsed["start_time"]
        end_time = parsed["end_time"]
        title = parsed["title"]

        # 检查冲突；若冲突则基于日历空闲给出可行改期建议
        conflict = self._store.check_conflict(start_time, end_time)
        description = f"From email: {email_msg.subject}"
        if conflict.has_conflict:
            try:
                conflict.suggested_slots = self.find_free_slots(
                    start_time, end_time
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("计算改期建议失败: %s", e)
            # 自动避让：把事件落到最近空闲槽，避免双重预订
            if self._auto_resolve and conflict.suggested_slots:
                orig = start_time
                slot = conflict.suggested_slots[0]
                start_time, end_time = slot.start_time, slot.end_time
                description += f" (auto-rescheduled from {orig.strftime('%H:%M')})"
            else:
                # 冲突且未自动避让：不写入日历（避免双重预订），仅返回冲突+建议
                return None, conflict

        # 构建事件（write=False 时仅用于展示，不落库）
        event = CalendarEvent(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=[email_msg.sender],
            source_email_id=email_msg.message_id,
        )
        if write:
            event = self._store.add_event(event)

        return event, conflict
