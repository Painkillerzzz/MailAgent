"""CLI 安全默认行为测试：fetch 默认重定向到测试邮箱，仅 --real 才发真实收件人。"""

from __future__ import annotations

import mail_agent.cli.app as cliapp
from mail_agent.config import load_config
from mail_agent.models import EmailMessage


class _CaptureAgent:
    last_kwargs: dict = {}

    def __init__(self, *a, **kw):
        _CaptureAgent.last_kwargs = kw

    def process_emails(self, emails):
        return []


def _patch(monkeypatch):
    """让 fetch 走 Google 分支并拿到一封邮件，用捕获式 agent 记录构造参数。"""
    monkeypatch.setattr(cliapp, "MailAgent", _CaptureAgent)
    monkeypatch.setattr(
        "mail_agent.gapi.auth.get_credentials", lambda *a, **k: "creds"
    )

    class _FakeGmail:
        def __init__(self, *a, **k):
            pass

        def fetch_unread(self, limit=10):
            return [EmailMessage(message_id="<x@x>", sender="real@ext.com",
                                 subject="hi", body="hi")]

    monkeypatch.setattr("mail_agent.gapi.gmail.GmailClient", _FakeGmail)

    cfg = load_config()
    cfg.google.enabled = True
    if not cfg.testing.redirect_to:
        cfg.testing.redirect_to = "zhangxiangyu40@qq.com"
    monkeypatch.setattr(cliapp, "load_config", lambda: cfg)
    return cfg


def test_fetch_defaults_to_redirect(monkeypatch):
    from typer.testing import CliRunner

    cfg = _patch(monkeypatch)
    result = CliRunner().invoke(cliapp.app, ["fetch", "--limit", "1"])
    assert result.exit_code == 0, result.output
    kw = _CaptureAgent.last_kwargs
    assert kw.get("redirect_to") == cfg.testing.redirect_to
    assert kw.get("allow_real") is False


def test_fetch_real_flag_sends_to_real(monkeypatch):
    from typer.testing import CliRunner

    _patch(monkeypatch)
    result = CliRunner().invoke(cliapp.app, ["fetch", "--limit", "1", "--real"])
    assert result.exit_code == 0, result.output
    kw = _CaptureAgent.last_kwargs
    assert kw.get("redirect_to") is None
    assert kw.get("allow_real") is True


def test_fetch_does_not_write_calendar_by_default(monkeypatch):
    from typer.testing import CliRunner

    _patch(monkeypatch)
    CliRunner().invoke(cliapp.app, ["fetch", "--limit", "1"])
    assert _CaptureAgent.last_kwargs.get("write_calendar") is False
