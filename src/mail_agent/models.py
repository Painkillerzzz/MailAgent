"""核心数据模型定义"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── 邮件相关模型 ──


class EmailMessage(BaseModel):
    """邮件消息"""

    message_id: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    date: Optional[datetime] = None
    thread_id: str = ""
    is_read: bool = False
    has_attachments: bool = False
    attachments: list[str] = Field(default_factory=list)
    # Gmail API 专用标识（IMAP 来源时为空）
    gmail_id: str = ""
    gmail_thread_id: str = ""


# ── 邮件分析相关模型 ──


class EmailIntent(str, Enum):
    """邮件意图类型"""

    MEETING_REQUEST = "meeting_request"
    TASK_ASSIGNMENT = "task_assignment"
    DEADLINE_REMINDER = "deadline_reminder"
    INFORMATION_SHARING = "information_sharing"
    COOPERATION_REQUEST = "cooperation_request"
    SOCIAL = "social"
    NOTIFICATION = "notification"
    INQUIRY = "inquiry"
    REPLY_EXPECTED = "reply_expected"
    OTHER = "other"


class UrgencyLevel(str, Enum):
    """紧急程度"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EmailCategory(str, Enum):
    """邮件分类"""

    MEETING = "meeting"
    TASK = "task"
    COOPERATION = "cooperation"
    NOTIFICATION = "notification"
    SOCIAL = "social"
    OTHER = "other"


class EmailAnalysis(BaseModel):
    """LLM 邮件语义分析结果"""

    intent: EmailIntent = EmailIntent.OTHER
    urgency: UrgencyLevel = UrgencyLevel.LOW
    category: EmailCategory = EmailCategory.OTHER
    requires_reply: bool = False
    contains_schedule: bool = False
    schedule_description: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)


class PriorityScore(BaseModel):
    """邮件优先级评分"""

    sender_weight: float = 0.0
    deadline_weight: float = 0.0
    intent_weight: float = 0.0
    urgency_weight: float = 0.0
    total_score: float = 0.0
    level: UrgencyLevel = UrgencyLevel.LOW
    reasoning: str = ""


# ── 日历相关模型 ──


class CalendarEvent(BaseModel):
    """日历事件"""

    event_id: str = ""
    title: str = ""
    description: str = ""
    start_time: datetime
    end_time: datetime
    location: str = ""
    attendees: list[str] = Field(default_factory=list)
    source_email_id: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class TimeSlot(BaseModel):
    """一个空闲时间段建议"""

    start_time: datetime
    end_time: datetime


class ScheduleConflict(BaseModel):
    """日程冲突信息"""

    has_conflict: bool = False
    conflicting_events: list[CalendarEvent] = Field(default_factory=list)
    # 基于日历空闲计算出的可行改期建议
    suggested_slots: list[TimeSlot] = Field(default_factory=list)


# ── 回复相关模型 ──


class ReplyDraft(BaseModel):
    """邮件回复草稿"""

    subject: str = ""
    body: str = ""
    to: list[str] = Field(default_factory=list)
    tone: str = "polite and concise"


# ── Agent 处理结果模型 ──


class ProcessingResult(BaseModel):
    """邮件处理完整结果"""

    email: EmailMessage
    analysis: EmailAnalysis
    priority: PriorityScore
    calendar_event: Optional[CalendarEvent] = None
    schedule_conflict: Optional[ScheduleConflict] = None
    reply_draft: Optional[ReplyDraft] = None
    # 回复投递状态："" 未投递 / "draft" 已存草稿 / "sent" 已发送 / "failed:..." 失败
    reply_delivery: str = ""
    # 投递产物 id（草稿 id 或已发送邮件 id），便于回读校验与清理
    reply_message_id: str = ""
    # 日历后端："local" 本地 JSON / "google" Google Calendar
    calendar_backend: str = "local"
    processing_steps: list[str] = Field(default_factory=list)
