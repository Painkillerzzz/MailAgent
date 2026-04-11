"""优先级评分模块测试"""

from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)
from mail_agent.understanding.priority import PriorityScorer


class TestPriorityScorer:
    def setup_method(self):
        self.scorer = PriorityScorer()

    def test_vip_sender_tsinghua(self):
        email = EmailMessage(
            sender="prof@tsinghua.edu.cn",
            sender_name="Prof. Zhang",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.OTHER,
            urgency=UrgencyLevel.LOW,
        )
        result = self.scorer.score(email, analysis)
        # tsinghua domain + "prof" keyword
        assert result.sender_weight > 0

    def test_vip_sender_keyword_prof(self):
        email = EmailMessage(
            sender="someone@gmail.com",
            sender_name="Professor Smith",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.OTHER,
            urgency=UrgencyLevel.LOW,
        )
        result = self.scorer.score(email, analysis)
        assert result.sender_weight >= 1.5

    def test_normal_sender(self):
        email = EmailMessage(
            sender="nobody@random.com",
            sender_name="Random Person",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.OTHER,
            urgency=UrgencyLevel.LOW,
        )
        result = self.scorer.score(email, analysis)
        assert result.sender_weight == 0.0

    def test_deadline_weight_with_schedule(self):
        email = EmailMessage(sender="a@b.com")
        analysis = EmailAnalysis(
            intent=EmailIntent.DEADLINE_REMINDER,
            contains_schedule=True,
            key_points=["deadline is Friday"],
        )
        result = self.scorer.score(email, analysis)
        assert result.deadline_weight >= 3.5  # schedule + deadline intent + keyword

    def test_intent_weight_meeting(self):
        email = EmailMessage(sender="a@b.com")
        analysis = EmailAnalysis(intent=EmailIntent.MEETING_REQUEST)
        result = self.scorer.score(email, analysis)
        assert result.intent_weight == 3.0

    def test_intent_weight_notification(self):
        email = EmailMessage(sender="a@b.com")
        analysis = EmailAnalysis(intent=EmailIntent.NOTIFICATION)
        result = self.scorer.score(email, analysis)
        assert result.intent_weight == 0.5

    def test_urgency_weight_critical(self):
        email = EmailMessage(sender="a@b.com")
        analysis = EmailAnalysis(urgency=UrgencyLevel.CRITICAL)
        result = self.scorer.score(email, analysis)
        assert result.urgency_weight == 5.0

    def test_urgency_weight_low(self):
        email = EmailMessage(sender="a@b.com")
        analysis = EmailAnalysis(urgency=UrgencyLevel.LOW)
        result = self.scorer.score(email, analysis)
        assert result.urgency_weight == 0.5

    def test_total_score_is_sum(self):
        email = EmailMessage(
            sender="boss@tsinghua.edu.cn",
            sender_name="Prof. Boss",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.MEETING_REQUEST,
            urgency=UrgencyLevel.HIGH,
            contains_schedule=True,
        )
        result = self.scorer.score(email, analysis)
        expected = (
            result.sender_weight
            + result.deadline_weight
            + result.intent_weight
            + result.urgency_weight
        )
        assert abs(result.total_score - expected) < 0.01

    def test_level_critical(self):
        email = EmailMessage(
            sender="boss@tsinghua.edu.cn",
            sender_name="Prof. Boss",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.DEADLINE_REMINDER,
            urgency=UrgencyLevel.CRITICAL,
            contains_schedule=True,
            key_points=["urgent deadline"],
        )
        result = self.scorer.score(email, analysis)
        assert result.level == UrgencyLevel.CRITICAL

    def test_level_low(self):
        email = EmailMessage(sender="random@gmail.com")
        analysis = EmailAnalysis(
            intent=EmailIntent.NOTIFICATION,
            urgency=UrgencyLevel.LOW,
        )
        result = self.scorer.score(email, analysis)
        assert result.level == UrgencyLevel.LOW

    def test_reasoning_contains_info(self):
        email = EmailMessage(
            sender="boss@tsinghua.edu.cn",
            sender_name="Manager Lee",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.MEETING_REQUEST,
            urgency=UrgencyLevel.MEDIUM,
        )
        result = self.scorer.score(email, analysis)
        assert "VIP sender" in result.reasoning
        assert "meeting_request" in result.reasoning

    def test_custom_vip_domains(self):
        scorer = PriorityScorer(vip_domains=["mycompany.com"])
        email = EmailMessage(sender="ceo@mycompany.com")
        analysis = EmailAnalysis()
        result = scorer.score(email, analysis)
        assert result.sender_weight >= 2.0

    def test_custom_vip_keywords(self):
        scorer = PriorityScorer(vip_keywords=["ceo", "cto"])
        email = EmailMessage(
            sender="someone@gmail.com",
            sender_name="CEO Johnson",
        )
        analysis = EmailAnalysis()
        result = scorer.score(email, analysis)
        assert result.sender_weight >= 1.5
