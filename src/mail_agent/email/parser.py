"""邮件内容解析模块

将原始邮件（email.message.Message 或原始字节）解析为 EmailMessage 模型。
"""

from __future__ import annotations

import email
import email.header
import email.utils
import logging
import re
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from io import StringIO

from mail_agent.models import EmailMessage

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""

    def __init__(self):
        super().__init__()
        self._result = StringIO()
        self._skip = False

    def handle_starttag(self, tag: str, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._result.write("\n")

    def handle_data(self, data: str):
        if not self._skip:
            self._result.write(data)

    def get_text(self) -> str:
        return self._result.getvalue().strip()


def html_to_text(html: str) -> str:
    """将 HTML 转换为纯文本"""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def decode_header_value(raw: str | None) -> str:
    """解码邮件头部字段（支持 RFC 2047 编码）"""
    if not raw:
        return ""
    decoded_parts = email.header.decode_header(raw)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def extract_sender_name(from_header: str) -> str:
    """从 From 头提取发件人显示名称"""
    name, _ = email.utils.parseaddr(from_header)
    return name


def extract_sender_email(from_header: str) -> str:
    """从 From 头提取发件人邮箱地址"""
    _, addr = email.utils.parseaddr(from_header)
    return addr


def extract_body(msg: Message) -> str:
    """提取邮件正文内容，优先纯文本，降级 HTML→文本"""
    if msg.is_multipart():
        text_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                text_parts.append(decoded)
            elif content_type == "text/html":
                html_parts.append(decoded)
        if text_parts:
            return "\n".join(text_parts).strip()
        if html_parts:
            return html_to_text("\n".join(html_parts))
        return ""
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        if content_type == "text/html":
            return html_to_text(decoded)
        return decoded.strip()


def extract_attachments(msg: Message) -> list[str]:
    """提取附件文件名列表"""
    filenames = []
    if not msg.is_multipart():
        return filenames
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            filename = part.get_filename()
            if filename:
                filenames.append(decode_header_value(filename))
    return filenames


def parse_date(msg: Message) -> datetime | None:
    """解析邮件日期"""
    date_str = msg.get("Date")
    if not date_str:
        return None
    parsed = email.utils.parsedate_to_datetime(date_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_raw_email(raw_bytes: bytes) -> EmailMessage:
    """从原始字节解析出 EmailMessage

    Args:
        raw_bytes: 原始邮件字节流

    Returns:
        EmailMessage 实例
    """
    msg = email.message_from_bytes(raw_bytes)
    return parse_message(msg)


def parse_message(msg: Message) -> EmailMessage:
    """从 email.message.Message 解析出 EmailMessage"""
    from_header = decode_header_value(msg.get("From", ""))
    to_raw = decode_header_value(msg.get("To", ""))
    recipients = [
        addr.strip() for addr in re.split(r"[,;]", to_raw) if addr.strip()
    ]
    attachments = extract_attachments(msg)

    return EmailMessage(
        message_id=msg.get("Message-ID", ""),
        sender=extract_sender_email(from_header),
        sender_name=extract_sender_name(from_header),
        recipients=recipients,
        subject=decode_header_value(msg.get("Subject", "")),
        body=extract_body(msg),
        date=parse_date(msg),
        thread_id=msg.get("References", msg.get("In-Reply-To", "")),
        is_read=False,
        has_attachments=len(attachments) > 0,
        attachments=attachments,
    )
