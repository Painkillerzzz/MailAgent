"""邮件回复生成模块

利用 LLM 生成个性化邮件回复。
"""

from __future__ import annotations

import logging

from mail_agent.config import UserProfile
from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailMessage,
    ReplyDraft,
    ScheduleConflict,
)

logger = logging.getLogger(__name__)

REPLY_SYSTEM_PROMPT = """You are an email reply assistant. Generate a professional and natural email reply.

Rules:
- Match the tone specified by the user profile
- Be concise but polite
- Address the key points of the original email
- If a meeting was confirmed, mention the agreed time
- If there is a schedule conflict, suggest alternative times
- Sign off with the user's name
- Write the reply body ONLY (no subject line, no metadata)
- Do NOT wrap the reply in quotes or code blocks"""

REPLY_USER_TEMPLATE = """Generate a reply for this email.

Original email:
From: {sender_name} <{sender}>
Subject: {subject}
Body:
{body}

---
My profile:
Name: {user_name}
Tone: {tone}
{calendar_context}

Write the reply body:"""


class ReplyGenerator:
    """邮件回复生成器"""

    def __init__(self, llm_client: LLMClient, user_profile: UserProfile | None = None):
        self._llm = llm_client
        self._user = user_profile or UserProfile()

    def generate(
        self,
        email_msg: EmailMessage,
        analysis: EmailAnalysis,
        calendar_event: CalendarEvent | None = None,
        conflict: ScheduleConflict | None = None,
    ) -> ReplyDraft:
        """生成邮件回复

        Args:
            email_msg: 原始邮件
            analysis: 邮件分析结果
            calendar_event: 已创建的日历事件（如有）
            conflict: 日程冲突信息（如有）

        Returns:
            ReplyDraft 回复草稿
        """
        # 构建日历上下文
        calendar_context = ""
        if calendar_event:
            calendar_context += (
                f"\nCalendar action: Meeting '{calendar_event.title}' "
                f"scheduled at {calendar_event.start_time.strftime('%Y-%m-%d %H:%M')}"
            )
        if conflict and conflict.has_conflict:
            conflict_info = ", ".join(
                f"'{e.title}' at {e.start_time.strftime('%H:%M')}-{e.end_time.strftime('%H:%M')}"
                for e in conflict.conflicting_events
            )
            calendar_context += f"\nWARNING: Schedule conflict with: {conflict_info}"
            if conflict.suggested_slots:
                slots = "; ".join(
                    f"{s.start_time.strftime('%Y-%m-%d %H:%M')}-{s.end_time.strftime('%H:%M')}"
                    for s in conflict.suggested_slots
                )
                calendar_context += (
                    f"\nThe following times ARE FREE on the user's calendar. "
                    f"Politely propose one or more of these specific times as an "
                    f"alternative: {slots}"
                )
            else:
                calendar_context += "\nSuggest an alternative time in the reply."

        user_content = REPLY_USER_TEMPLATE.format(
            sender_name=email_msg.sender_name or email_msg.sender,
            sender=email_msg.sender,
            subject=email_msg.subject,
            body=email_msg.body[:2000],
            user_name=self._user.name,
            tone=self._user.tone,
            calendar_context=calendar_context,
        )

        messages = [
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        reply_body = self._llm.chat(messages, temperature=0.7)

        # 添加签名
        if self._user.signature:
            reply_body = reply_body.strip() + "\n\n" + self._user.signature

        subject = email_msg.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        return ReplyDraft(
            subject=subject,
            body=reply_body.strip(),
            to=[email_msg.sender],
            tone=self._user.tone,
        )
