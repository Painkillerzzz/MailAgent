"""邮件理解模块测试（使用真实智谱AI API）"""

import pytest

from mail_agent.models import (
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)
from mail_agent.understanding.analyzer import EmailAnalyzer


class TestEmailAnalyzer:
    """集成测试：使用真实 LLM API 验证分析能力"""

    @pytest.fixture
    def analyzer(self, llm_client):
        return EmailAnalyzer(llm_client)

    def test_meeting_request(self, analyzer, sample_email_meeting):
        result = analyzer.analyze(sample_email_meeting)
        assert result.intent == EmailIntent.MEETING_REQUEST
        assert result.requires_reply is True
        assert result.contains_schedule is True
        assert result.category == EmailCategory.MEETING
        assert len(result.schedule_description) > 0
        assert len(result.summary) > 0

    def test_task_with_deadline(self, analyzer, sample_email_task):
        result = analyzer.analyze(sample_email_task)
        assert result.intent in (
            EmailIntent.TASK_ASSIGNMENT,
            EmailIntent.DEADLINE_REMINDER,
        )
        assert result.urgency in (UrgencyLevel.MEDIUM, UrgencyLevel.HIGH, UrgencyLevel.CRITICAL)
        assert result.requires_reply is True
        assert result.contains_schedule is True

    def test_notification(self, analyzer, sample_email_notification):
        result = analyzer.analyze(sample_email_notification)
        assert result.intent in (
            EmailIntent.NOTIFICATION,
            EmailIntent.INFORMATION_SHARING,
        )
        assert result.urgency in (UrgencyLevel.LOW, UrgencyLevel.MEDIUM)
        assert result.category in (
            EmailCategory.NOTIFICATION,
            EmailCategory.OTHER,
        )

    def test_social_email(self, analyzer):
        email = EmailMessage(
            sender="friend@gmail.com",
            sender_name="Alice",
            subject="Happy Birthday!",
            body="Hey! Just wanted to wish you a happy birthday! Hope you have a great day!",
        )
        result = analyzer.analyze(email)
        assert result.intent in (EmailIntent.SOCIAL, EmailIntent.OTHER, EmailIntent.NOTIFICATION)
        assert result.urgency in (UrgencyLevel.LOW, UrgencyLevel.MEDIUM)

    def test_cooperation_request(self, analyzer):
        email = EmailMessage(
            sender="researcher@stanford.edu",
            sender_name="Dr. Wang",
            subject="Research Collaboration Proposal",
            body=(
                "Dear Xiangyu,\n\n"
                "I've read your recent paper and I'm very interested in collaborating "
                "on a related project. Would you be open to discussing this further?\n\n"
                "Best regards,\nDr. Wang"
            ),
        )
        result = analyzer.analyze(email)
        assert result.intent in (
            EmailIntent.COOPERATION_REQUEST,
            EmailIntent.INQUIRY,
            EmailIntent.REPLY_EXPECTED,
        )
        assert result.requires_reply is True

    def test_empty_body_handled(self, analyzer):
        email = EmailMessage(
            sender="test@test.com",
            subject="Empty",
            body="",
        )
        result = analyzer.analyze(email)
        # 不应崩溃，应返回有效结果
        assert result.intent is not None
        assert result.urgency is not None

    def test_analysis_returns_key_points(self, analyzer, sample_email_meeting):
        result = analyzer.analyze(sample_email_meeting)
        assert isinstance(result.key_points, list)
        assert len(result.key_points) > 0

    def test_analysis_returns_summary(self, analyzer, sample_email_task):
        result = analyzer.analyze(sample_email_task)
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0
