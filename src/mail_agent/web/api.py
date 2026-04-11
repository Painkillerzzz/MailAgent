"""/api/* JSON 端点"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from mail_agent.agent.orchestrator import MailAgent
from mail_agent.calendar.store import CalendarStore
from mail_agent.config import load_config
from mail_agent.email.fetcher import IMAPFetcher
from mail_agent.llm.client import LLMClient
from mail_agent.models import EmailMessage, UrgencyLevel
from mail_agent.web.result_store import ResultStore
from mail_agent.web.settings_store import SettingsStore

api_router = APIRouter()

# 这些在 app.py 中被注入
_templates: Jinja2Templates | None = None
_result_store: ResultStore | None = None
_settings_store: SettingsStore | None = None


def init_api(
    templates: Jinja2Templates,
    result_store: ResultStore,
    settings_store: SettingsStore,
):
    global _templates, _result_store, _settings_store
    _templates = templates
    _result_store = result_store
    _settings_store = settings_store


def _get_result_store() -> ResultStore:
    assert _result_store is not None
    return _result_store


def _get_settings_store() -> SettingsStore:
    assert _settings_store is not None
    return _settings_store


def _get_agent() -> MailAgent:
    return MailAgent(load_config())


# ── 邮件端点 ──


SAMPLE_EMAILS = [
    EmailMessage(
        message_id="<demo-1@mail.com>",
        sender="lee@tsinghua.edu.cn",
        sender_name="Prof. Lee",
        subject="Meeting",
        body="Hi Xiangyu,\n\nCan we meet Thursday at 3pm to discuss the results?\n\nBest,\nLee",
        date=datetime.now(timezone.utc),
    ),
    EmailMessage(
        message_id="<demo-2@mail.com>",
        sender="john@company.com",
        sender_name="John Smith",
        subject="Please submit the draft by Friday",
        body="Hi Xiangyu,\n\nPlease make sure to submit the final draft of the report by this Friday EOD. Let me know if you need more time.\n\nThanks,\nJohn",
        date=datetime.now(timezone.utc),
    ),
    EmailMessage(
        message_id="<demo-3@mail.com>",
        sender="notifications@arxiv.org",
        sender_name="arXiv",
        subject="FYI: Paper accepted at NeurIPS 2026",
        body="Dear author,\n\nWe are pleased to inform you that your paper has been accepted at NeurIPS 2026.\n\nCongratulations!",
        date=datetime.now(timezone.utc),
    ),
]


@api_router.post("/demo")
async def api_demo():
    store = _get_result_store()
    agent = _get_agent()
    results = agent.process_emails(SAMPLE_EMAILS)
    store.add_many(results)
    return {"count": len(results), "message": f"已处理 {len(results)} 封邮件"}


@api_router.post("/emails/process")
async def api_process_email(request: Request):
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
    _get_result_store().add(result)
    return {"message": "邮件分析完成"}


@api_router.get("/emails/partial", response_class=HTMLResponse)
async def api_emails_partial(
    request: Request,
    urgency: str | None = Query(None),
    category: str | None = Query(None),
    intent: str | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("priority"),
    order: str = Query("desc"),
):
    store = _get_result_store()
    results = store.list_results(
        urgency=urgency or None,
        category=category or None,
        intent=intent or None,
        search=search or None,
        sort_by=sort_by,
        order=order,
    )
    return _templates.TemplateResponse(
        request=request,
        name="partials/_email_list.html",
        context={"results": results},
    )


# ── 日历端点 ──

URGENCY_COLORS = {
    "critical": "#e74c3c",
    "high": "#e67e22",
    "medium": "#f1c40f",
    "low": "#27ae60",
}


@api_router.get("/calendar/events")
async def api_calendar_events(
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    config = load_config()
    store = CalendarStore(config.calendar)

    start_dt = datetime.fromisoformat(start) if start else datetime.now() - timedelta(days=90)
    end_dt = datetime.fromisoformat(end) if end else datetime.now() + timedelta(days=90)

    events = store.list_events(start=start_dt, end=end_dt)
    result_store = _get_result_store()

    fc_events = []
    for evt in events:
        # 查找来源邮件的紧急度来确定颜色
        color = "#3498db"  # 默认蓝色
        source_results = [
            r for r in result_store.list_results()
            if r.email.message_id == evt.source_email_id
        ]
        if source_results:
            color = URGENCY_COLORS.get(
                source_results[0].priority.level.value, "#3498db"
            )

        # 冲突检测（排除自身）
        conflict = store.check_conflict(evt.start_time, evt.end_time)
        has_conflict = len([
            c for c in conflict.conflicting_events
            if c.event_id != evt.event_id
        ]) > 0

        fc_events.append({
            "id": evt.event_id,
            "title": evt.title,
            "start": evt.start_time.isoformat(),
            "end": evt.end_time.isoformat(),
            "color": color,
            "borderColor": "#e74c3c" if has_conflict else color,
            "extendedProps": {
                "description": evt.description,
                "attendees": evt.attendees,
                "location": evt.location,
                "source_email_id": evt.source_email_id,
                "has_conflict": has_conflict,
            },
        })

    return fc_events


@api_router.delete("/calendar/events/{event_id}")
async def api_delete_calendar_event(event_id: str):
    config = load_config()
    store = CalendarStore(config.calendar)
    if store.remove_event(event_id):
        return {"message": "事件已删除"}
    return JSONResponse({"message": "事件未找到"}, status_code=404)


# ── 提醒端点 ──


@api_router.get("/reminders")
async def api_reminders():
    store = _get_result_store()
    config = load_config()
    cal_store = CalendarStore(config.calendar)

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    return {
        "urgent_emails": [
            {
                "subject": r.email.subject,
                "sender": r.email.sender_name or r.email.sender,
                "urgency": r.priority.level.value,
                "score": r.priority.total_score,
                "summary": r.analysis.summary,
            }
            for r in store.get_urgent()
        ],
        "upcoming_deadlines": [
            {
                "subject": r.email.subject,
                "sender": r.email.sender_name or r.email.sender,
                "schedule": r.analysis.schedule_description,
                "summary": r.analysis.summary,
            }
            for r in store.get_deadlines()
        ],
        "todays_events": [
            {
                "title": e.title,
                "start": e.start_time.isoformat(),
                "end": e.end_time.isoformat(),
                "attendees": e.attendees,
            }
            for e in cal_store.list_events(start=today_start, end=today_end)
        ],
    }


@api_router.get("/reminders/count")
async def api_reminders_count():
    store = _get_result_store()
    return {"count": len(store.get_urgent())}


@api_router.get("/reminders/partial", response_class=HTMLResponse)
async def api_reminders_partial(
    request: Request,
    section: str = Query("urgent"),
):
    store = _get_result_store()
    config = load_config()
    cal_store = CalendarStore(config.calendar)

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    template_map = {
        "urgent": ("partials/_reminders_urgent.html", {"results": store.get_urgent()}),
        "deadlines": ("partials/_reminders_deadlines.html", {"results": store.get_deadlines()}),
        "today": ("partials/_reminders_today.html", {"events": cal_store.list_events(start=today_start, end=today_end)}),
    }

    template_name, ctx = template_map.get(section, template_map["urgent"])
    return _templates.TemplateResponse(request=request, name=template_name, context=ctx)


# ── 总结端点 ──


@api_router.get("/summary")
async def api_summary():
    store = _get_result_store()
    results = store.list_results()

    from mail_agent.understanding.summarizer import EmailSummarizer

    summarizer = EmailSummarizer()
    stats = summarizer.generate_stats(results)
    return stats


@api_router.get("/summary/briefing")
async def api_summary_briefing():
    store = _get_result_store()
    results = store.list_results()

    from mail_agent.understanding.summarizer import EmailSummarizer

    config = load_config()
    llm = LLMClient(config.llm)
    summarizer = EmailSummarizer(llm)
    briefing = summarizer.generate_briefing(results)
    return {"briefing": briefing}


# ── 设置端点 ──


@api_router.get("/settings")
async def api_get_settings():
    store = _get_settings_store()
    data = store.get_redacted()
    # 如果没有保存过设置，用默认值填充
    config = load_config()
    defaults = {
        "llm": {
            "api_key": "",
            "model": config.llm.model,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
        },
        "imap": {
            "host": config.imap.host,
            "port": config.imap.port,
            "username": config.imap.username,
            "password": "",
        },
        "user": {
            "name": config.user.name,
            "email": config.user.email,
            "tone": config.user.tone,
            "signature": config.user.signature,
        },
    }
    # 合并：已保存的设置优先
    for section in defaults:
        if section not in data:
            data[section] = defaults[section]
        else:
            for key in defaults[section]:
                if key not in data[section]:
                    data[section][key] = defaults[section][key]
    return data


@api_router.post("/settings")
async def api_save_settings(request: Request):
    try:
        body = await request.json()
        store = _get_settings_store()
        store.save(body)
        return {"success": True, "message": "设置已保存"}
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": f"保存失败: {e}"},
            status_code=400,
        )


@api_router.post("/settings/test-llm")
async def api_test_llm(request: Request):
    try:
        body = await request.json()
        api_key = body.get("api_key", "")
        # 如果是脱敏值，使用已保存的
        if api_key.startswith("****"):
            store = _get_settings_store()
            api_key = store.get_value("llm", "api_key", "")
        if not api_key:
            # 回落到环境变量
            config = load_config()
            api_key = config.llm.api_key

        from mail_agent.config import LLMConfig

        client = LLMClient(LLMConfig(api_key=api_key))
        response = client.chat(
            [{"role": "user", "content": "Say OK"}],
            max_tokens=10,
        )
        return {"success": True, "message": f"连接成功: {response[:50]}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {e}"}


@api_router.post("/settings/test-imap")
async def api_test_imap(request: Request):
    try:
        body = await request.json()
        from mail_agent.config import IMAPConfig

        password = body.get("password", "")
        if password.startswith("****"):
            store = _get_settings_store()
            password = store.get_value("imap", "password", "")

        config = IMAPConfig(
            host=body.get("host", ""),
            port=int(body.get("port", 993)),
            username=body.get("username", ""),
            password=password,
        )
        fetcher = IMAPFetcher(config)
        fetcher.connect()
        fetcher.disconnect()
        return {"success": True, "message": "IMAP 连接成功"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {e}"}
