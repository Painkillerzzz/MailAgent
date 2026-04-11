"""邮件总结模块测试"""

import pytest

from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    PriorityScore,
    ProcessingResult,
    UrgencyLevel,
)
from mail_agent.understanding.summarizer import EmailSummarizer


def _make_result(
    intent=EmailIntent.OTHER,
    urgency=UrgencyLevel.LOW,
    category=EmailCategory.OTHER,
    requires_reply=False,
    contains_schedule=False,
    subject="Test",
    sender="a@b.com",
) -> ProcessingResult:
    return ProcessingResult(
        email=EmailMessage(sender=sender, subject=subject),
        analysis=EmailAnalysis(
            intent=intent,
            urgency=urgency,
            category=category,
            requires_reply=requires_reply,
            contains_schedule=contains_schedule,
            summary=f"Summary of {subject}",
        ),
        priority=PriorityScore(level=urgency),
    )


class TestEmailSummarizer:
    def test_stats_empty(self):
        summarizer = EmailSummarizer()
        stats = summarizer.generate_stats([])
        assert stats["total"] == 0
        assert stats["needs_reply"] == 0

    def test_stats_counts(self):
        results = [
            _make_result(
                intent=EmailIntent.MEETING_REQUEST,
                category=EmailCategory.MEETING,
                urgency=UrgencyLevel.HIGH,
                requires_reply=True,
            ),
            _make_result(
                intent=EmailIntent.DEADLINE_REMINDER,
                category=EmailCategory.TASK,
                urgency=UrgencyLevel.CRITICAL,
                requires_reply=True,
                contains_schedule=True,
            ),
            _make_result(
                intent=EmailIntent.NOTIFICATION,
                category=EmailCategory.NOTIFICATION,
                urgency=UrgencyLevel.LOW,
            ),
        ]
        summarizer = EmailSummarizer()
        stats = summarizer.generate_stats(results)

        assert stats["total"] == 3
        assert stats["needs_reply"] == 2
        assert stats["meetings"] == 1
        assert stats["tasks"] == 1
        assert stats["urgent"] == 2
        assert stats["by_category"]["meeting"] == 1
        assert stats["by_category"]["task"] == 1
        assert stats["by_category"]["notification"] == 1
        assert stats["by_urgency"]["high"] == 1
        assert stats["by_urgency"]["critical"] == 1
        assert stats["by_urgency"]["low"] == 1

    def test_text_summary_no_llm(self):
        results = [
            _make_result(
                subject="Urgent Meeting",
                urgency=UrgencyLevel.CRITICAL,
                requires_reply=True,
            ),
        ]
        summarizer = EmailSummarizer()
        text = summarizer.generate_briefing(results)
        assert "1 emails processed" in text
        assert "Urgent" in text

    def test_text_summary_empty(self):
        summarizer = EmailSummarizer()
        text = summarizer.generate_briefing([])
        assert "No emails" in text

    def test_llm_briefing(self, llm_client):
        """集成测试：使用真实 LLM 生成简报"""
        results = [
            _make_result(
                subject="Meeting with Prof. Lee",
                intent=EmailIntent.MEETING_REQUEST,
                category=EmailCategory.MEETING,
                urgency=UrgencyLevel.HIGH,
                requires_reply=True,
            ),
            _make_result(
                subject="Submit draft by Friday",
                intent=EmailIntent.DEADLINE_REMINDER,
                category=EmailCategory.TASK,
                urgency=UrgencyLevel.CRITICAL,
                requires_reply=True,
                contains_schedule=True,
            ),
        ]
        summarizer = EmailSummarizer(llm_client)
        briefing = summarizer.generate_briefing(results)
        assert len(briefing) > 50
        # LLM 生成的简报应提及关键信息
        assert "2" in briefing or "two" in briefing.lower()
