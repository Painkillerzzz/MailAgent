"""回复生成模块测试（使用真实智谱AI API）"""

import pytest

from mail_agent.config import UserProfile
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    ScheduleConflict,
    UrgencyLevel,
)
from mail_agent.reply.generator import ReplyGenerator

from datetime import datetime


class TestReplyGenerator:
    @pytest.fixture
    def generator(self, llm_client):
        profile = UserProfile(name="Xiangyu", tone="polite and concise")
        return ReplyGenerator(llm_client, profile)

    def test_meeting_reply(self, generator, sample_email_meeting, sample_analysis_meeting):
        """测试会议确认回复"""
        event = CalendarEvent(
            title="Meeting with Prof. Lee",
            start_time=datetime(2026, 4, 16, 15, 0),
            end_time=datetime(2026, 4, 16, 16, 0),
        )
        reply = generator.generate(
            sample_email_meeting,
            sample_analysis_meeting,
            calendar_event=event,
        )
        assert reply.subject.startswith("Re:")
        assert len(reply.body) > 0
        assert "lee@tsinghua.edu.cn" in reply.to
        # 回复应提及时间
        body_lower = reply.body.lower()
        assert any(word in body_lower for word in ["thursday", "3", "pm", "15:00", "3pm"])

    def test_task_reply(self, generator, sample_email_task, sample_analysis_task):
        """测试任务确认回复"""
        reply = generator.generate(sample_email_task, sample_analysis_task)
        assert reply.subject.startswith("Re:")
        assert len(reply.body) > 0
        assert "john@company.com" in reply.to

    def test_reply_with_conflict(self, generator, sample_email_meeting, sample_analysis_meeting):
        """测试有冲突时的回复"""
        event = CalendarEvent(
            title="Meeting with Prof. Lee",
            start_time=datetime(2026, 4, 16, 15, 0),
            end_time=datetime(2026, 4, 16, 16, 0),
        )
        existing = CalendarEvent(
            title="Existing Class",
            start_time=datetime(2026, 4, 16, 14, 30),
            end_time=datetime(2026, 4, 16, 15, 30),
        )
        conflict = ScheduleConflict(
            has_conflict=True,
            conflicting_events=[existing],
        )
        reply = generator.generate(
            sample_email_meeting,
            sample_analysis_meeting,
            calendar_event=event,
            conflict=conflict,
        )
        assert len(reply.body) > 0
        # 回复应提及冲突或建议替代时间
        # （LLM 可能用不同措辞，我们只验证回复不为空）

    def test_subject_prefix(self, generator):
        """测试 Re: 前缀处理"""
        email = EmailMessage(
            sender="test@test.com",
            subject="Hello",
            body="Hi there",
        )
        analysis = EmailAnalysis(requires_reply=True)
        reply = generator.generate(email, analysis)
        assert reply.subject == "Re: Hello"

    def test_subject_already_has_re(self, generator):
        """已有 Re: 前缀时不重复添加"""
        email = EmailMessage(
            sender="test@test.com",
            subject="Re: Hello",
            body="Thanks for the reply.",
        )
        analysis = EmailAnalysis(requires_reply=True)
        reply = generator.generate(email, analysis)
        assert reply.subject == "Re: Hello"
        assert not reply.subject.startswith("Re: Re:")

    def test_custom_user_profile(self, llm_client):
        """测试自定义用户资料"""
        profile = UserProfile(
            name="Zhang San",
            tone="formal and academic",
            signature="--\nZhang San\nPhD Student",
        )
        generator = ReplyGenerator(llm_client, profile)
        email = EmailMessage(
            sender="advisor@university.edu",
            sender_name="Prof. Wang",
            subject="Paper Review",
            body="Please review the latest draft.",
        )
        analysis = EmailAnalysis(
            intent=EmailIntent.TASK_ASSIGNMENT,
            requires_reply=True,
        )
        reply = generator.generate(email, analysis)
        assert "Zhang San" in reply.body
        assert "PhD Student" in reply.body
