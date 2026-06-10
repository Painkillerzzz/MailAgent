"""Agent 编排器集成测试（使用真实智谱AI API）"""

import os

import pytest

from mail_agent.agent.orchestrator import MailAgent
from mail_agent.models import EmailMessage, UrgencyLevel

from datetime import datetime, timezone

# 这些用例会发起真实 LLM 调用：无真实 key 时整模块跳过
pytestmark = pytest.mark.skipif(
    not (os.getenv("ZAI_API_KEY") and os.getenv("ZAI_API_KEY") != "test-dummy-key"),
    reason="需要真实 ZAI_API_KEY 的集成测试",
)


class TestMailAgent:
    @pytest.fixture
    def agent(self, tmp_calendar_path):
        from mail_agent.config import AppConfig, CalendarConfig

        config = AppConfig(calendar=CalendarConfig(storage_path=tmp_calendar_path))
        return MailAgent(config)

    def test_process_meeting_email(self, agent, sample_email_meeting):
        """测试完整流程：会议邮件"""
        result = agent.process_email(sample_email_meeting)

        # 分析结果
        assert result.analysis.intent.value == "meeting_request"
        assert result.analysis.requires_reply is True
        assert result.analysis.contains_schedule is True

        # 优先级
        assert result.priority.total_score > 0
        assert result.priority.level in (
            UrgencyLevel.MEDIUM,
            UrgencyLevel.HIGH,
            UrgencyLevel.CRITICAL,
        )

        # 日历事件应被创建
        assert result.calendar_event is not None
        assert result.calendar_event.start_time.hour == 15

        # 回复草稿应被生成
        assert result.reply_draft is not None
        assert len(result.reply_draft.body) > 0
        assert result.reply_draft.subject.startswith("Re:")

        # 处理步骤应被记录
        assert len(result.processing_steps) > 0
        assert any("Step 1" in s for s in result.processing_steps)

    def test_process_task_email(self, agent, sample_email_task):
        """测试完整流程：任务邮件"""
        result = agent.process_email(sample_email_task)

        assert result.analysis.requires_reply is True
        assert result.reply_draft is not None
        assert result.priority.total_score > 0

    def test_process_notification_email(self, agent, sample_email_notification):
        """测试完整流程：通知邮件"""
        result = agent.process_email(sample_email_notification)

        assert result.analysis.intent.value in (
            "notification",
            "information_sharing",
        )
        # 通知邮件可能不需要回复
        assert result.priority.total_score > 0

    def test_batch_processing_sorted(self, agent):
        """测试批量处理和优先级排序"""
        emails = [
            EmailMessage(
                sender="random@gmail.com",
                subject="FYI: Newsletter",
                body="Just a newsletter update.",
                date=datetime.now(timezone.utc),
            ),
            EmailMessage(
                sender="boss@tsinghua.edu.cn",
                sender_name="Prof. Boss",
                subject="Urgent: Submit report NOW",
                body="The report is due today, please submit immediately!",
                date=datetime.now(timezone.utc),
            ),
        ]

        results = agent.process_emails(emails)

        assert len(results) == 2
        # 高优先级邮件应排在前面
        assert results[0].priority.total_score >= results[1].priority.total_score

    def test_calendar_store_accessible(self, agent):
        """测试日历存储可访问"""
        store = agent.calendar_store
        assert store is not None
        events = store.list_events()
        assert isinstance(events, list)
