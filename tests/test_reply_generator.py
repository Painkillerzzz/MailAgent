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


# ── 改期建议注入（确定性，不调用真实 LLM）──


class _CaptureLLM:
    """捕获传给 LLM 的 messages，返回固定回复"""

    def __init__(self):
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return "Thanks, one of those times works."


class TestReplySuggestedSlots:
    def _gen(self):
        llm = _CaptureLLM()
        return ReplyGenerator(llm, UserProfile(name="Xiangyu")), llm

    def _conflict_with_slots(self):
        from mail_agent.models import TimeSlot
        ev = CalendarEvent(
            title="Existing",
            start_time=datetime(2026, 6, 10, 15, 0),
            end_time=datetime(2026, 6, 10, 16, 0),
        )
        return ScheduleConflict(
            has_conflict=True,
            conflicting_events=[ev],
            suggested_slots=[
                TimeSlot(start_time=datetime(2026, 6, 10, 11, 0),
                         end_time=datetime(2026, 6, 10, 12, 0)),
                TimeSlot(start_time=datetime(2026, 6, 10, 16, 0),
                         end_time=datetime(2026, 6, 10, 17, 0)),
            ],
        )

    def test_free_slots_injected_into_prompt(self):
        gen, llm = self._gen()
        email = EmailMessage(subject="Meet?", sender="prof@x.edu",
                             body="Can we meet at 3pm?")
        analysis = EmailAnalysis(requires_reply=True, contains_schedule=True)
        gen.generate(email, analysis, conflict=self._conflict_with_slots())
        user_msg = llm.messages[-1]["content"]
        assert "FREE on the user's calendar" in user_msg
        assert "2026-06-10 11:00" in user_msg
        assert "2026-06-10 16:00" in user_msg

    def test_no_slots_falls_back_to_generic(self):
        gen, llm = self._gen()
        email = EmailMessage(subject="Meet?", sender="p@x.edu", body="3pm?")
        analysis = EmailAnalysis(requires_reply=True, contains_schedule=True)
        conflict = ScheduleConflict(has_conflict=True, conflicting_events=[])
        gen.generate(email, analysis, conflict=conflict)
        user_msg = llm.messages[-1]["content"]
        assert "Suggest an alternative time" in user_msg
