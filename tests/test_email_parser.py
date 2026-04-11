"""邮件解析模块测试"""

from datetime import timezone

from mail_agent.email.parser import (
    decode_header_value,
    extract_body,
    extract_sender_email,
    extract_sender_name,
    html_to_text,
    parse_raw_email,
)


class TestHTMLToText:
    def test_simple_html(self):
        html = "<p>Hello <b>World</b></p>"
        assert "Hello" in html_to_text(html)
        assert "World" in html_to_text(html)

    def test_skip_script_style(self):
        html = "<script>alert('x')</script><style>.x{}</style><p>Content</p>"
        text = html_to_text(html)
        assert "alert" not in text
        assert "Content" in text

    def test_line_breaks(self):
        html = "<p>Line1</p><p>Line2</p>"
        text = html_to_text(html)
        assert "Line1" in text
        assert "Line2" in text

    def test_empty_html(self):
        assert html_to_text("") == ""

    def test_nested_tags(self):
        html = "<div><p>Nested <span>content</span></p></div>"
        text = html_to_text(html)
        assert "Nested" in text
        assert "content" in text


class TestDecodeHeader:
    def test_plain_ascii(self):
        assert decode_header_value("Hello World") == "Hello World"

    def test_none_value(self):
        assert decode_header_value(None) == ""

    def test_empty_string(self):
        assert decode_header_value("") == ""

    def test_rfc2047_utf8(self):
        encoded = "=?utf-8?B?5rWL6K+V?="  # "测试" in base64
        result = decode_header_value(encoded)
        assert result == "测试"

    def test_rfc2047_quoted_printable(self):
        encoded = "=?utf-8?Q?Hello_World?="
        result = decode_header_value(encoded)
        assert "Hello" in result


class TestSenderExtraction:
    def test_extract_name(self):
        assert extract_sender_name("John Doe <john@test.com>") == "John Doe"

    def test_extract_email(self):
        assert extract_sender_email("John Doe <john@test.com>") == "john@test.com"

    def test_email_only(self):
        assert extract_sender_email("john@test.com") == "john@test.com"

    def test_empty_name(self):
        assert extract_sender_name("john@test.com") == ""


class TestParseRawEmail:
    def test_simple_plain_text(self):
        raw = b"""From: Test User <test@test.com>
To: recipient@test.com
Subject: Test Subject
Date: Mon, 06 Apr 2026 12:00:00 +0000
Message-ID: <abc123@mail.com>

This is the body of the email.
"""
        msg = parse_raw_email(raw)
        assert msg.sender == "test@test.com"
        assert msg.sender_name == "Test User"
        assert msg.subject == "Test Subject"
        assert "body of the email" in msg.body
        assert msg.message_id == "<abc123@mail.com>"
        assert msg.date is not None
        assert msg.date.tzinfo is not None

    def test_multipart_email(self):
        raw = b"""From: sender@test.com
To: recipient@test.com
Subject: Multipart Test
Date: Mon, 06 Apr 2026 12:00:00 +0000
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset="utf-8"

Plain text version.
--boundary123
Content-Type: text/html; charset="utf-8"

<html><body><p>HTML version.</p></body></html>
--boundary123--
"""
        msg = parse_raw_email(raw)
        # 应优先使用纯文本
        assert "Plain text version" in msg.body

    def test_html_only_email(self):
        raw = b"""From: sender@test.com
To: recipient@test.com
Subject: HTML Only
Content-Type: text/html; charset="utf-8"

<html><body><p>HTML content only.</p></body></html>
"""
        msg = parse_raw_email(raw)
        assert "HTML content only" in msg.body

    def test_multiple_recipients(self):
        raw = b"""From: sender@test.com
To: a@test.com, b@test.com, c@test.com
Subject: Multi

Body
"""
        msg = parse_raw_email(raw)
        assert len(msg.recipients) == 3

    def test_attachment_detection(self):
        raw = b"""From: sender@test.com
To: recipient@test.com
Subject: With Attachment
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary456"

--boundary456
Content-Type: text/plain

Email body.
--boundary456
Content-Type: application/pdf
Content-Disposition: attachment; filename="report.pdf"

(binary content)
--boundary456--
"""
        msg = parse_raw_email(raw)
        assert msg.has_attachments is True
        assert "report.pdf" in msg.attachments

    def test_no_date(self):
        raw = b"""From: sender@test.com
To: recipient@test.com
Subject: No Date

Body without date header.
"""
        msg = parse_raw_email(raw)
        assert msg.date is None

    def test_chinese_subject(self):
        raw = b"""From: sender@test.com
To: recipient@test.com
Subject: =?utf-8?B?5Lya6K6u6YKA6K+3?=

Body
"""
        msg = parse_raw_email(raw)
        assert msg.subject == "会议邀请"
