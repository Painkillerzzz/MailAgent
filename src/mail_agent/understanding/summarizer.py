"""邮件总结模块

生成邮件处理结果的每日/批量摘要。
"""

from __future__ import annotations

from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    EmailCategory,
    EmailIntent,
    ProcessingResult,
    UrgencyLevel,
)

SUMMARY_SYSTEM_PROMPT = """You are an email summary assistant. Given a batch of processed emails with their analysis results, generate a concise daily briefing.

Format your response as a structured summary with these sections:
1. Overview (one sentence: total emails, how many need action)
2. Action Required (emails that need replies, sorted by priority)
3. Meetings & Schedule (any calendar events created)
4. FYI / Low Priority (notifications and informational emails)

Keep it concise and scannable. Use bullet points. Write in English."""


class EmailSummarizer:
    """邮件总结生成器"""

    def __init__(self, llm_client: LLMClient | None = None):
        self._llm = llm_client

    def generate_stats(self, results: list[ProcessingResult]) -> dict:
        """生成统计数据（无需 LLM）"""
        total = len(results)
        needs_reply = sum(1 for r in results if r.analysis.requires_reply)
        meetings = sum(
            1 for r in results if r.analysis.category == EmailCategory.MEETING
        )
        tasks = sum(
            1 for r in results
            if r.analysis.intent
            in (EmailIntent.TASK_ASSIGNMENT, EmailIntent.DEADLINE_REMINDER)
        )
        urgent = sum(
            1 for r in results
            if r.priority.level in (UrgencyLevel.CRITICAL, UrgencyLevel.HIGH)
        )

        by_category: dict[str, int] = {}
        for r in results:
            cat = r.analysis.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        by_urgency: dict[str, int] = {}
        for r in results:
            urg = r.priority.level.value
            by_urgency[urg] = by_urgency.get(urg, 0) + 1

        return {
            "total": total,
            "needs_reply": needs_reply,
            "meetings": meetings,
            "tasks": tasks,
            "urgent": urgent,
            "by_category": by_category,
            "by_urgency": by_urgency,
        }

    def generate_briefing(self, results: list[ProcessingResult]) -> str:
        """使用 LLM 生成自然语言邮件简报

        Args:
            results: 处理结果列表

        Returns:
            简报文本
        """
        if not results:
            return "No emails to summarize."

        if not self._llm:
            return self._generate_text_summary(results)

        # 构建邮件摘要给 LLM
        email_summaries = []
        for i, r in enumerate(results[:20], 1):  # 限制 20 封
            email_summaries.append(
                f"{i}. [{r.priority.level.value.upper()}] "
                f"From: {r.email.sender_name or r.email.sender} | "
                f"Subject: {r.email.subject} | "
                f"Intent: {r.analysis.intent.value} | "
                f"Requires reply: {r.analysis.requires_reply} | "
                f"Summary: {r.analysis.summary}"
            )

        stats = self.generate_stats(results)
        context = (
            f"Total emails: {stats['total']}\n"
            f"Needs reply: {stats['needs_reply']}\n"
            f"Meetings: {stats['meetings']}\n"
            f"Tasks/Deadlines: {stats['tasks']}\n"
            f"Urgent: {stats['urgent']}\n\n"
            f"Emails:\n" + "\n".join(email_summaries)
        )

        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        return self._llm.chat(messages, temperature=0.3)

    def _generate_text_summary(self, results: list[ProcessingResult]) -> str:
        """无 LLM 时的纯文本摘要"""
        stats = self.generate_stats(results)
        lines = [
            f"Email Summary: {stats['total']} emails processed",
            f"  - {stats['needs_reply']} need reply",
            f"  - {stats['meetings']} meetings",
            f"  - {stats['tasks']} tasks/deadlines",
            f"  - {stats['urgent']} urgent",
            "",
        ]

        urgent_results = [
            r for r in results
            if r.priority.level in (UrgencyLevel.CRITICAL, UrgencyLevel.HIGH)
        ]
        if urgent_results:
            lines.append("Urgent:")
            for r in urgent_results:
                lines.append(
                    f"  [{r.priority.level.value.upper()}] "
                    f"{r.email.subject} - {r.analysis.summary}"
                )

        return "\n".join(lines)
