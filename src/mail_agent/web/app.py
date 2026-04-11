"""简单 Web 仪表板

基于 FastAPI + Jinja2 的邮件处理结果查看界面。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mail_agent.agent.orchestrator import MailAgent
from mail_agent.config import load_config
from mail_agent.models import EmailMessage, ProcessingResult

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "web_templates"

web_app = FastAPI(title="Mail Agent Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 内存缓存处理结果
_results_cache: list[ProcessingResult] = []


def _get_agent() -> MailAgent:
    return MailAgent(load_config())


@web_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """主仪表板页面"""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "results": _results_cache,
            "total": len(_results_cache),
        },
    )


@web_app.post("/demo")
async def run_demo(request: Request):
    """运行演示处理"""
    global _results_cache

    sample_emails = [
        EmailMessage(
            message_id="<demo-1@mail.com>",
            sender="lee@tsinghua.edu.cn",
            sender_name="Prof. Lee",
            subject="Meeting",
            body=(
                "Hi Xiangyu,\n\n"
                "Can we meet Thursday at 3pm to discuss the results?\n\n"
                "Best,\nLee"
            ),
            date=datetime.now(timezone.utc),
        ),
        EmailMessage(
            message_id="<demo-2@mail.com>",
            sender="john@company.com",
            sender_name="John Smith",
            subject="Please submit the draft by Friday",
            body=(
                "Hi Xiangyu,\n\n"
                "Please make sure to submit the final draft of the report "
                "by this Friday EOD. Let me know if you need more time.\n\n"
                "Thanks,\nJohn"
            ),
            date=datetime.now(timezone.utc),
        ),
        EmailMessage(
            message_id="<demo-3@mail.com>",
            sender="notifications@arxiv.org",
            sender_name="arXiv",
            subject="FYI: Paper accepted at NeurIPS 2026",
            body=(
                "Dear author,\n\n"
                "We are pleased to inform you that your paper "
                "has been accepted at NeurIPS 2026.\n\n"
                "Congratulations!"
            ),
            date=datetime.now(timezone.utc),
        ),
    ]

    agent = _get_agent()
    _results_cache = agent.process_emails(sample_emails)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "results": _results_cache,
            "total": len(_results_cache),
            "message": f"已处理 {len(_results_cache)} 封邮件",
        },
    )


@web_app.post("/analyze")
async def analyze_email(request: Request):
    """分析手动输入的邮件"""
    global _results_cache

    form = await request.form()
    email_msg = EmailMessage(
        sender=str(form.get("sender", "")),
        sender_name=str(form.get("sender_name", "")),
        subject=str(form.get("subject", "")),
        body=str(form.get("body", "")),
        date=datetime.now(timezone.utc),
    )

    agent = _get_agent()
    result = agent.process_email(email_msg)
    _results_cache.insert(0, result)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "results": _results_cache,
            "total": len(_results_cache),
            "message": "邮件分析完成",
        },
    )


@web_app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(request: Request):
    """日历视图"""
    config = load_config()
    from mail_agent.calendar.store import CalendarStore

    store = CalendarStore(config.calendar)
    now = datetime.now()
    events = store.list_events(start=now, end=now + timedelta(days=30))

    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "events": events,
        },
    )


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动 Web 服务器"""
    import uvicorn

    uvicorn.run(web_app, host=host, port=port)
