"""读写回读自验证 harness

对 Gmail / Google Calendar 执行「写入 → 回读 → 校验 → 清理」闭环，
确保每一次写操作都能被读回且内容一致，从而保证读写正确性。

设计为依赖注入（接收 gmail / calendar 客户端），既可对真实 API 运行，
也可在单测中注入内存假客户端验证逻辑本身。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from mail_agent.models import CalendarEvent, ReplyDraft

logger = logging.getLogger(__name__)


class Check(BaseModel):
    """单条断言结果"""

    name: str
    passed: bool
    detail: str = ""


class VerifyResult(BaseModel):
    """一个读写回读循环的总体结果"""

    name: str
    passed: bool = True
    checks: list[Check] = Field(default_factory=list)
    artifact_id: str = ""  # 创建出的 event/draft id
    cleaned_up: bool = False

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, passed=passed, detail=detail))
        if not passed:
            self.passed = False


def _minute_key(dt: datetime) -> datetime:
    """归一到 UTC 分钟，便于跨时区比较写入/读回时间"""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


class RoundTripVerifier:
    """读写回读自验证器"""

    def __init__(self, gmail=None, calendar=None, redirect_to: str = ""):
        """
        Args:
            gmail: GmailClient（或兼容接口）
            calendar: GoogleCalendarClient（或兼容接口）
            redirect_to: 测试发送/草稿的目标邮箱
        """
        self._gmail = gmail
        self._calendar = calendar
        self._redirect_to = redirect_to

    # ── 日历：建 → get 回读 → list 命中 → 删 → 确认消失 ──

    def verify_calendar_roundtrip(self, cleanup: bool = True) -> VerifyResult:
        res = VerifyResult(name="calendar_roundtrip")
        if self._calendar is None:
            res.add("calendar_client", False, "未提供 calendar 客户端")
            return res

        token = uuid.uuid4().hex[:8]
        title = f"[SELFCHECK {token}]"
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
            minute=0, second=0, microsecond=0
        )
        end = start + timedelta(hours=1)
        event = CalendarEvent(
            title=title,
            description="round-trip self check",
            start_time=start,
            end_time=end,
        )

        created = self._calendar.add_event(event)
        res.artifact_id = created.event_id
        res.add("create_returns_id", bool(created.event_id), created.event_id)
        if not created.event_id:
            return res

        # 回读单个事件
        got = self._calendar.get_event(created.event_id)
        res.add("readback_exists", got is not None)
        if got is not None:
            res.add("title_match", got.title == title, f"{got.title!r}")
            res.add(
                "start_match",
                _minute_key(got.start_time) == _minute_key(start),
                f"{got.start_time} vs {start}",
            )
            res.add(
                "end_match",
                _minute_key(got.end_time) == _minute_key(end),
                f"{got.end_time} vs {end}",
            )

        # 在时间窗口内 list 能命中
        listed = self._calendar.list_events(
            start=start - timedelta(days=1), end=end + timedelta(days=1)
        )
        res.add(
            "list_contains",
            any(e.event_id == created.event_id for e in listed),
            f"window 共 {len(listed)} 个事件",
        )

        # 清理并确认删除
        if cleanup:
            removed = self._calendar.remove_event(created.event_id)
            res.add("delete_ok", bool(removed))
            gone = self._calendar.get_event(created.event_id)
            res.add("gone_after_delete", gone is None)
            res.cleaned_up = gone is None
        return res

    # ── 草稿：建 → get 回读 → list 命中 → 删 → 确认消失 ──

    def verify_draft_roundtrip(self, cleanup: bool = True) -> VerifyResult:
        res = VerifyResult(name="draft_roundtrip")
        if self._gmail is None:
            res.add("gmail_client", False, "未提供 gmail 客户端")
            return res
        if not self._redirect_to:
            res.add("redirect_to", False, "未设置测试目标邮箱")
            return res

        token = uuid.uuid4().hex[:8]
        subject = f"[SELFCHECK {token}] draft round-trip"
        body = f"self-check body {token}"
        reply = ReplyDraft(subject=subject, body=body, to=[self._redirect_to])

        draft_id = self._gmail.create_draft(reply, None)
        res.artifact_id = draft_id
        res.add("create_returns_id", bool(draft_id), draft_id)
        if not draft_id:
            return res

        # 回读草稿
        got = self._gmail.get_draft(draft_id)
        res.add("readback_exists", got is not None)
        if got is not None:
            res.add("subject_match", got.subject == subject, f"{got.subject!r}")
            res.add(
                "recipient_match",
                self._redirect_to in got.recipients,
                f"{got.recipients}",
            )
            res.add("body_contains_token", token in got.body)

        # list 能命中
        drafts = self._gmail.list_drafts()
        res.add(
            "list_contains",
            any(d.get("id") == draft_id for d in drafts),
            f"共 {len(drafts)} 个草稿",
        )

        # 清理并确认删除
        if cleanup:
            self._gmail.delete_draft(draft_id)
            remaining = self._gmail.list_drafts()
            gone = not any(d.get("id") == draft_id for d in remaining)
            res.add("gone_after_delete", gone)
            res.cleaned_up = gone
        return res

    # ── 发送：发到测试邮箱 → 在已发送中搜索命中 ──

    def verify_send_roundtrip(self) -> VerifyResult:
        res = VerifyResult(name="send_roundtrip")
        if self._gmail is None:
            res.add("gmail_client", False, "未提供 gmail 客户端")
            return res
        if not self._redirect_to:
            res.add("redirect_to", False, "未设置测试目标邮箱")
            return res

        token = uuid.uuid4().hex[:8]
        subject = f"[SELFCHECK {token}] send round-trip"
        reply = ReplyDraft(
            subject=subject,
            body=f"self-check send {token}",
            to=[self._redirect_to],
        )
        sent_id = self._gmail.send_reply(reply, None)
        res.artifact_id = sent_id
        res.add("send_returns_id", bool(sent_id), sent_id)
        if not sent_id:
            return res

        # 在已发送邮件里按 token 搜索命中
        found = self._gmail.fetch_query(f"in:sent {token}", limit=5)
        res.add(
            "found_in_sent",
            any(token in (m.subject or "") for m in found),
            f"命中 {len(found)} 封",
        )
        return res

    def run_all(self, *, cleanup: bool = True, include_send: bool = False):
        """运行全部读写回读循环

        Args:
            cleanup: 是否清理创建出的事件/草稿
            include_send: 是否包含真实发送验证（会真的发一封测试邮件）
        """
        results = [
            self.verify_calendar_roundtrip(cleanup=cleanup),
            self.verify_draft_roundtrip(cleanup=cleanup),
        ]
        if include_send:
            results.append(self.verify_send_roundtrip())
        return results
