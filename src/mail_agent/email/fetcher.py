"""IMAP 邮件获取模块

通过 IMAP 协议连接邮箱服务器，获取未读邮件。
"""

from __future__ import annotations

import imaplib
import logging

from mail_agent.config import IMAPConfig
from mail_agent.email.parser import parse_raw_email
from mail_agent.models import EmailMessage

logger = logging.getLogger(__name__)


class IMAPFetcher:
    """IMAP 邮件获取器"""

    def __init__(self, config: IMAPConfig):
        self._config = config
        self._connection: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None

    def connect(self):
        """建立 IMAP 连接"""
        if self._config.use_ssl:
            self._connection = imaplib.IMAP4_SSL(
                self._config.host, self._config.port
            )
        else:
            self._connection = imaplib.IMAP4(
                self._config.host, self._config.port
            )
        self._connection.login(self._config.username, self._config.password)
        logger.info("已连接到 %s", self._config.host)

    def disconnect(self):
        """断开 IMAP 连接"""
        if self._connection:
            try:
                self._connection.logout()
            except Exception:
                pass
            self._connection = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def _search_and_fetch(
        self, criteria: str, limit: int
    ) -> list[EmailMessage]:
        """按 IMAP 搜索条件取最新 limit 封并解析。"""
        if not self._connection:
            raise RuntimeError("未连接到 IMAP 服务器，请先调用 connect()")

        self._connection.select(self._config.mailbox)
        _, data = self._connection.search(None, criteria)
        if not data or not data[0]:
            return []

        msg_ids = data[0].split()[-limit:]  # 取最新的 limit 条
        emails = []
        for msg_id in msg_ids:
            try:
                _, msg_data = self._connection.fetch(msg_id, "(RFC822)")
                if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                    emails.append(parse_raw_email(msg_data[0][1]))
            except Exception as e:  # noqa: BLE001
                logger.warning("获取邮件 %s 失败: %s", msg_id, e)
        logger.info("获取了 %d 封邮件 (criteria=%s)", len(emails), criteria)
        return emails

    def fetch_unread(self, limit: int = 50) -> list[EmailMessage]:
        """获取未读邮件（最多 limit 封）"""
        return self._search_and_fetch("UNSEEN", limit)

    def fetch_all(self, limit: int = 100) -> list[EmailMessage]:
        """获取所有邮件（含已读，最多 limit 封）"""
        return self._search_and_fetch("ALL", limit)
