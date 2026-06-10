"""Gmail API 客户端

通过 Gmail REST API 读取未读邮件、标记已读、创建草稿、发送回复。
相比 IMAP，支持原生的标签操作、草稿、按线程回复。
"""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

from mail_agent.config import GoogleConfig
from mail_agent.email.parser import parse_raw_email
from mail_agent.models import EmailMessage, ReplyDraft

logger = logging.getLogger(__name__)


class GmailClient:
    """Gmail API 客户端"""

    def __init__(self, config: GoogleConfig, credentials=None, service=None):
        """
        Args:
            config: Google 配置
            credentials: 已有的 OAuth 凭据；为 None 时按需获取（可能触发浏览器授权）
            service: 预构建的 Gmail API service（主要用于测试注入）
        """
        self._config = config
        if service is not None:
            self._service = service
            return
        if credentials is None:
            from mail_agent.gapi.auth import get_credentials

            credentials = get_credentials(config)
        from googleapiclient.discovery import build

        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    # ── 读取 ──

    def fetch_unread(self, limit: int = 50) -> list[EmailMessage]:
        """获取未读邮件

        Args:
            limit: 最多获取数量

        Returns:
            EmailMessage 列表（已附带 gmail_id / gmail_thread_id）
        """
        return self._fetch_by_query("is:unread", limit)

    def fetch_query(self, query: str, limit: int = 50) -> list[EmailMessage]:
        """按 Gmail 搜索语法获取邮件（如 "from:boss@x.com newer_than:7d"）"""
        return self._fetch_by_query(query, limit)

    def _fetch_by_query(self, query: str, limit: int) -> list[EmailMessage]:
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
        )
        msg_refs = resp.get("messages", [])
        emails: list[EmailMessage] = []
        for ref in msg_refs:
            try:
                emails.append(self._get_message(ref["id"]))
            except Exception as e:  # noqa: BLE001
                logger.warning("获取邮件 %s 失败: %s", ref.get("id"), e)
        logger.info("Gmail 获取了 %d 封邮件 (query=%r)", len(emails), query)
        return emails

    def get_message(self, gmail_id: str) -> EmailMessage:
        """按 ID 读回单封邮件（公开接口，用于读写回读验证）"""
        return self._get_message(gmail_id)

    def _get_message(self, gmail_id: str) -> EmailMessage:
        """按 raw 格式获取并解析单封邮件"""
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=gmail_id, format="raw")
            .execute()
        )
        raw_bytes = base64.urlsafe_b64decode(msg["raw"].encode("ascii"))
        email_msg = parse_raw_email(raw_bytes)
        email_msg.gmail_id = msg.get("id", gmail_id)
        email_msg.gmail_thread_id = msg.get("threadId", "")
        email_msg.is_read = "UNREAD" not in msg.get("labelIds", [])
        return email_msg

    # ── 写操作 ──

    def mark_read(self, gmail_id: str) -> None:
        """移除 UNREAD 标签，标记为已读"""
        self._service.users().messages().modify(
            userId="me", id=gmail_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        logger.info("已标记为已读: %s", gmail_id)

    def add_label(self, gmail_id: str, label_id: str) -> None:
        """为邮件添加标签（label_id 需为已存在的标签 ID）"""
        self._service.users().messages().modify(
            userId="me", id=gmail_id, body={"addLabelIds": [label_id]}
        ).execute()

    def create_draft(
        self, reply: ReplyDraft, original: EmailMessage | None = None
    ) -> str:
        """创建回复草稿（不发送），返回草稿 ID"""
        body = self._build_raw_reply(reply, original)
        message: dict = {"message": {"raw": body}}
        if original and original.gmail_thread_id:
            message["message"]["threadId"] = original.gmail_thread_id
        draft = (
            self._service.users()
            .drafts()
            .create(userId="me", body=message)
            .execute()
        )
        logger.info("已创建 Gmail 草稿: %s", draft.get("id"))
        return draft.get("id", "")

    def get_draft(self, draft_id: str) -> EmailMessage:
        """读回草稿内容并解析为 EmailMessage（用于回读验证）"""
        draft = (
            self._service.users()
            .drafts()
            .get(userId="me", id=draft_id, format="raw")
            .execute()
        )
        msg = draft.get("message", {})
        raw_bytes = base64.urlsafe_b64decode(msg["raw"].encode("ascii"))
        email_msg = parse_raw_email(raw_bytes)
        email_msg.gmail_id = msg.get("id", "")
        email_msg.gmail_thread_id = msg.get("threadId", "")
        return email_msg

    def list_drafts(self, limit: int = 50) -> list[dict]:
        """列出草稿引用（{id, message:{id, threadId}}）"""
        resp = (
            self._service.users()
            .drafts()
            .list(userId="me", maxResults=limit)
            .execute()
        )
        return resp.get("drafts", [])

    def delete_draft(self, draft_id: str) -> None:
        """删除草稿"""
        self._service.users().drafts().delete(
            userId="me", id=draft_id
        ).execute()
        logger.info("已删除草稿: %s", draft_id)

    def send_reply(
        self, reply: ReplyDraft, original: EmailMessage | None = None
    ) -> str:
        """直接发送回复，返回已发送邮件的 ID"""
        body = self._build_raw_reply(reply, original)
        message: dict = {"raw": body}
        if original and original.gmail_thread_id:
            message["threadId"] = original.gmail_thread_id
        sent = (
            self._service.users()
            .messages()
            .send(userId="me", body=message)
            .execute()
        )
        logger.info("已发送回复: %s", sent.get("id"))
        return sent.get("id", "")

    def _build_raw_reply(
        self, reply: ReplyDraft, original: EmailMessage | None
    ) -> str:
        """构建 RFC822 MIME 邮件并 base64url 编码

        正确设置 In-Reply-To / References 头，使 Gmail 将其归入原线程。
        """
        mime = MIMEText(reply.body, "plain", "utf-8")
        mime["To"] = ", ".join(reply.to)
        mime["Subject"] = reply.subject
        if original and original.message_id:
            mime["In-Reply-To"] = original.message_id
            mime["References"] = original.message_id
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        return raw
