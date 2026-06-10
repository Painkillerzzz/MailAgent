"""测试公共 fixtures"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mail_agent.config import AppConfig, CalendarConfig, LLMConfig, UserProfile
from mail_agent.llm.client import LLMClient
from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    UrgencyLevel,
)


@pytest.fixture
def sample_email_meeting() -> EmailMessage:
    """会议请求示例邮件"""
    return EmailMessage(
        message_id="<test-meeting-001@mail.com>",
        sender="lee@tsinghua.edu.cn",
        sender_name="Prof. Lee",
        recipients=["xiangyu@test.com"],
        subject="Meeting",
        body=(
            "Hi Xiangyu,\n\n"
            "Can we meet Thursday at 3pm to discuss the results?\n\n"
            "Best,\nLee"
        ),
        date=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_email_task() -> EmailMessage:
    """任务分配示例邮件"""
    return EmailMessage(
        message_id="<test-task-001@mail.com>",
        sender="john@company.com",
        sender_name="John Smith",
        recipients=["xiangyu@test.com"],
        subject="Please submit the draft by Friday",
        body=(
            "Hi Xiangyu,\n\n"
            "Please make sure to submit the final draft of the report "
            "by this Friday EOD. Let me know if you need more time.\n\n"
            "Thanks,\nJohn"
        ),
        date=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_email_notification() -> EmailMessage:
    """通知类示例邮件"""
    return EmailMessage(
        message_id="<test-notif-001@mail.com>",
        sender="notifications@arxiv.org",
        sender_name="arXiv",
        recipients=["xiangyu@test.com"],
        subject="FYI: Paper accepted at NeurIPS 2026",
        body=(
            "Dear author,\n\n"
            "We are pleased to inform you that your paper "
            "has been accepted at NeurIPS 2026.\n\n"
            "Congratulations!"
        ),
        date=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_analysis_meeting() -> EmailAnalysis:
    """会议请求分析结果"""
    return EmailAnalysis(
        intent=EmailIntent.MEETING_REQUEST,
        urgency=UrgencyLevel.MEDIUM,
        category=EmailCategory.MEETING,
        requires_reply=True,
        contains_schedule=True,
        schedule_description="Thursday at 3pm",
        summary="Prof. Lee requests a meeting on Thursday at 3pm.",
        key_points=["Meeting request", "Thursday 3pm", "Discuss results"],
    )


@pytest.fixture
def sample_analysis_task() -> EmailAnalysis:
    """任务分析结果"""
    return EmailAnalysis(
        intent=EmailIntent.DEADLINE_REMINDER,
        urgency=UrgencyLevel.HIGH,
        category=EmailCategory.TASK,
        requires_reply=True,
        contains_schedule=True,
        schedule_description="this Friday EOD",
        summary="Submit draft report by Friday.",
        key_points=["Submit draft", "Deadline: Friday EOD"],
    )


@pytest.fixture
def sample_calendar_event() -> CalendarEvent:
    """示例日历事件"""
    now = datetime.now()
    return CalendarEvent(
        event_id="test-evt-001",
        title="Meeting with Prof. Lee",
        description="Discuss results",
        start_time=now + timedelta(days=1, hours=3),
        end_time=now + timedelta(days=1, hours=4),
        attendees=["lee@tsinghua.edu.cn"],
        source_email_id="<test-meeting-001@mail.com>",
    )


@pytest.fixture
def tmp_calendar_path(tmp_path) -> Path:
    """临时日历存储路径"""
    return tmp_path / "test_calendar.json"


_DUMMY_KEY = "test-dummy-key"


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """全局隔离：默认数据路径指向临时目录；无真实 key 时给个占位 key 让对象能构造。"""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    import mail_agent.config as cfg
    import mail_agent.web.result_store as rs
    import mail_agent.web.settings_store as ss

    monkeypatch.setattr(cfg, "DATA_DIR", data, raising=False)
    monkeypatch.setattr(rs, "DEFAULT_RESULTS_PATH", data / "results.json", raising=False)
    monkeypatch.setattr(ss, "DEFAULT_SETTINGS_PATH", data / "settings.json", raising=False)
    fld = cfg.CalendarConfig.model_fields.get("storage_path")
    if fld is not None:
        monkeypatch.setattr(fld, "default", data / "calendar.json", raising=False)
    # 占位 key：让 LLMClient/MailAgent 能构造（不会真的调用，调用类测试另行跳过）
    if not os.getenv("ZAI_API_KEY"):
        monkeypatch.setenv("ZAI_API_KEY", _DUMMY_KEY)
    yield


def has_real_key() -> bool:
    key = os.getenv("ZAI_API_KEY")
    return bool(key) and key != _DUMMY_KEY


def _require_key():
    if not has_real_key():
        pytest.skip("需要真实 ZAI_API_KEY 的集成测试（未设置则跳过）")


@pytest.fixture
def llm_config() -> LLMConfig:
    """LLM 配置（真实 API key；无 key 时跳过依赖它的测试）"""
    _require_key()
    return LLMConfig()


@pytest.fixture
def llm_client(llm_config) -> LLMClient:
    """LLM 客户端实例（真实 API；无 key 时跳过）"""
    return LLMClient(llm_config)
