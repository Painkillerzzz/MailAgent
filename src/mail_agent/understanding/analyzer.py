"""邮件语义分析模块

利用 LLM 分析邮件意图、紧急程度、是否需要回复、是否涉及日程。
"""

from __future__ import annotations

import logging

from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are an email analysis assistant. Analyze the given email and extract structured information.

You MUST respond with a valid JSON object containing exactly these fields:
{
  "intent": one of ["meeting_request", "task_assignment", "deadline_reminder", "information_sharing", "cooperation_request", "social", "notification", "inquiry", "reply_expected", "other"],
  "urgency": one of ["critical", "high", "medium", "low"],
  "category": one of ["meeting", "task", "cooperation", "notification", "social", "other"],
  "requires_reply": true or false,
  "contains_schedule": true or false,
  "schedule_description": "description of any time/date mentioned, or empty string",
  "summary": "one sentence summary of the email",
  "key_points": ["list", "of", "key", "points"]
}

Rules:
- "critical" urgency: immediate action required, deadlines within 24 hours
- "high" urgency: time-sensitive, deadlines within a few days, from important senders
- "medium" urgency: normal business communication, meetings, tasks
- "low" urgency: FYI, newsletters, social messages

contains_schedule — be STRICT. Set it true ONLY when the email asks THE RECIPIENT to personally attend or act at a specific time, i.e.:
  - a meeting / call / appointment / interview the recipient is invited to, with a date or time, OR
  - a concrete deadline the recipient personally must meet (e.g., "submit the report by Friday").
Set contains_schedule = FALSE (and schedule_description = "") for ALL of the following, even if they mention dates or times:
  - promotional / marketing / sales emails (e.g., "sale ends March 1", "deal expires soon")
  - newsletters, digests, recommendations, or event announcements that do NOT require the recipient's personal attendance
  - job postings / recruiting blasts and their application windows (e.g., "Fall 2026 internship")
  - automated system notifications, status/incident updates, delivery receipts, security alerts (their timestamps are not appointments)
  - vague time periods with no specific appointment (e.g., "this fall", "sometime next quarter")
When in doubt, set contains_schedule = false.
- schedule_description: only when contains_schedule is true; describe the time in a parseable way (e.g., "Thursday at 3pm", "next Tuesday 14:00"). Otherwise "".

requires_reply — true only when a human sender expects a personal response. Set false for automated/no-reply senders, newsletters, notifications, and promotional mail.

Respond ONLY with the JSON object, no other text."""

ANALYSIS_USER_TEMPLATE = """Analyze this email:

From: {sender_name} <{sender}>
Subject: {subject}
Date: {date}

{body}"""


class EmailAnalyzer:
    """邮件语义分析器"""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    def analyze(self, email_msg: EmailMessage) -> EmailAnalysis:
        """分析邮件语义

        Args:
            email_msg: 邮件消息

        Returns:
            EmailAnalysis 分析结果
        """
        user_content = ANALYSIS_USER_TEMPLATE.format(
            sender_name=email_msg.sender_name or email_msg.sender,
            sender=email_msg.sender,
            subject=email_msg.subject,
            date=email_msg.date or "unknown",
            body=email_msg.body[:2000],  # 截断过长的邮件
        )

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            data = self._llm.chat_json(messages, temperature=0.1)
            return EmailAnalysis(
                intent=EmailIntent(data.get("intent", "other")),
                urgency=UrgencyLevel(data.get("urgency", "low")),
                category=EmailCategory(data.get("category", "other")),
                requires_reply=data.get("requires_reply", False),
                contains_schedule=data.get("contains_schedule", False),
                schedule_description=data.get("schedule_description", ""),
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
            )
        except Exception as e:
            logger.error("邮件分析失败: %s", e)
            return EmailAnalysis(
                summary=f"分析失败: {e}",
            )
