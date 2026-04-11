"""日历调度模块

解析邮件中的时间信息并自动创建/检查日历事件。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser

from mail_agent.calendar.store import CalendarStore
from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailMessage,
    ScheduleConflict,
)

logger = logging.getLogger(__name__)

TIME_PARSE_SYSTEM_PROMPT = """You are a date/time parser. Given a schedule description and a reference date, extract the exact start datetime and end datetime.

Respond with ONLY a JSON object:
{
  "start_time": "YYYY-MM-DDTHH:MM:SS",
  "end_time": "YYYY-MM-DDTHH:MM:SS",
  "title": "short event title"
}

Rules:
- Use the reference date to resolve relative dates (e.g., "next Thursday", "tomorrow")
- If no end time is given, assume a 1-hour duration
- If only a day is mentioned without time, use 09:00 as default start time
- Use 24-hour format
- title should be a short descriptive event title based on the context"""


class CalendarScheduler:
    """日历调度器：解析时间、检查冲突、创建事件"""

    def __init__(self, store: CalendarStore, llm_client: LLMClient):
        self._store = store
        self._llm = llm_client

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
        return {
            "start_time": dateutil_parser.parse(data["start_time"]),
            "end_time": dateutil_parser.parse(data["end_time"]),
            "title": data.get("title", "Meeting"),
        }

    def schedule_from_email(
        self, email_msg: EmailMessage, analysis: EmailAnalysis
    ) -> tuple[CalendarEvent | None, ScheduleConflict | None]:
        """根据邮件分析结果自动调度日历事件

        Args:
            email_msg: 邮件消息
            analysis: 邮件分析结果

        Returns:
            (创建的事件或None, 冲突信息或None)
        """
        if not analysis.contains_schedule or not analysis.schedule_description:
            return None, None

        try:
            parsed = self.parse_schedule(
                analysis.schedule_description,
                reference_date=email_msg.date or datetime.now(),
                context=f"Email from {email_msg.sender_name}: {email_msg.subject}",
            )
        except Exception as e:
            logger.error("时间解析失败: %s", e)
            return None, None

        start_time = parsed["start_time"]
        end_time = parsed["end_time"]
        title = parsed["title"]

        # 检查冲突
        conflict = self._store.check_conflict(start_time, end_time)

        # 创建事件
        event = CalendarEvent(
            title=title,
            description=f"From email: {email_msg.subject}",
            start_time=start_time,
            end_time=end_time,
            attendees=[email_msg.sender],
            source_email_id=email_msg.message_id,
        )
        event = self._store.add_event(event)

        return event, conflict
