"""邮件理解模块测试（使用真实智谱AI API）"""

import pytest

from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)
from mail_agent.understanding.analyzer import (
    ANALYSIS_SYSTEM_PROMPT,
    EmailAnalyzer,
)


class _FakeLLM:
    """返回固定 JSON 的假 LLM，用于确定性测试"""

    def __init__(self, payload):
        self.payload = payload
        self.last_messages = None

    def chat_json(self, messages, **kwargs):
        self.last_messages = messages
        return self.payload


class TestEmailAnalyzerUnit:
    """确定性单测：不依赖网络"""

    def test_maps_fields_from_llm(self):
        fake = _FakeLLM({
            "intent": "meeting_request",
            "urgency": "high",
            "category": "meeting",
            "requires_reply": True,
            "contains_schedule": True,
            "schedule_description": "Thursday at 3pm",
            "summary": "meeting",
            "key_points": ["a", "b"],
        })
        analyzer = EmailAnalyzer(fake)
        result = analyzer.analyze(EmailMessage(subject="x", body="y"))
        assert result.intent == EmailIntent.MEETING_REQUEST
        assert result.urgency == UrgencyLevel.HIGH
        assert result.contains_schedule is True
        assert result.schedule_description == "Thursday at 3pm"
        assert result.key_points == ["a", "b"]

    def test_marketing_payload_no_schedule(self):
        # 即使提到日期，营销邮件应被模型判为无日程（此处验证映射如实透传 false）
        fake = _FakeLLM({
            "intent": "notification",
            "urgency": "low",
            "category": "notification",
            "requires_reply": False,
            "contains_schedule": False,
            "schedule_description": "",
            "summary": "promo",
            "key_points": [],
        })
        result = EmailAnalyzer(fake).analyze(EmailMessage(subject="Sale ends March 1"))
        assert result.contains_schedule is False
        assert result.schedule_description == ""
        assert result.requires_reply is False

    def test_invalid_json_returns_safe_default(self):
        class _BadLLM:
            def chat_json(self, messages, **kwargs):
                raise ValueError("bad json")

        result = EmailAnalyzer(_BadLLM()).analyze(EmailMessage(subject="x"))
        assert isinstance(result, EmailAnalysis)
        assert "分析失败" in result.summary

    def test_prompt_enforces_strict_schedule(self):
        # 守护性测试：prompt 必须包含收紧日程判定的关键约束
        assert "be STRICT" in ANALYSIS_SYSTEM_PROMPT
        assert "promotional" in ANALYSIS_SYSTEM_PROMPT
        assert "When in doubt, set contains_schedule = false" in ANALYSIS_SYSTEM_PROMPT


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

    # ── 收紧日程判定后的回归测试（真实 LLM）──

    def test_marketing_email_no_schedule(self, analyzer):
        email = EmailMessage(
            sender="deals@weee.com",
            sender_name="Weee!",
            subject="解锁最强劲爆价💌 Sale ends March 1",
            body=(
                "限时特惠！新品上架，多款商品补货。"
                "Big sale — deals expire March 1. 立即抢购，错过再等一年！"
            ),
        )
        result = analyzer.analyze(email)
        assert result.contains_schedule is False
        assert result.requires_reply is False

    def test_job_posting_no_schedule(self, analyzer):
        email = EmailMessage(
            sender="jobs-noreply@linkedin.com",
            sender_name="LinkedIn",
            subject="Machine Learning Intern/Co-op (Fall, 2026) at Cohere",
            body=(
                "Based on your profile, here are job recommendations: "
                "Machine Learning Intern/Co-op (Fall 2026) at Cohere. Apply now."
            ),
        )
        result = analyzer.analyze(email)
        assert result.contains_schedule is False

    def test_status_notification_no_schedule(self, analyzer):
        email = EmailMessage(
            sender="noreply@statuspage.io",
            sender_name="Statuspage",
            subject="Incident - Elevated errors",
            body=(
                "We are investigating elevated error rates. "
                "Incident started at 2026-06-05 17:13 UTC. We will update shortly."
            ),
        )
        result = analyzer.analyze(email)
        assert result.contains_schedule is False
        assert result.requires_reply is False

    def test_genuine_meeting_still_detected(self, analyzer):
        # 收紧后真实会议邀约仍应识别为含日程
        email = EmailMessage(
            sender="prof.li@tsinghua.edu.cn",
            sender_name="李教授",
            subject="下周三的论文讨论",
            body="方便的话我们下周三下午3点见个面，讨论论文，大概一小时。",
        )
        result = analyzer.analyze(email)
        assert result.contains_schedule is True
        assert result.requires_reply is True
