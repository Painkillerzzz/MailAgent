"""/api/* JSON 端点"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from mail_agent.agent.orchestrator import MailAgent
from mail_agent.calendar.store import CalendarStore
from mail_agent.config import load_config
from mail_agent.email.fetcher import IMAPFetcher
from mail_agent.llm.client import LLMClient
from mail_agent.models import EmailMessage
from mail_agent.web.result_store import ResultStore
from mail_agent.web.settings_store import SettingsStore

logger = logging.getLogger(__name__)

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
    if _result_store is None:
        raise RuntimeError("API 未初始化：result_store 为空，请先调用 init_api()")
    return _result_store


def _get_settings_store() -> SettingsStore:
    if _settings_store is None:
        raise RuntimeError("API 未初始化：settings_store 为空，请先调用 init_api()")
    return _settings_store


def _get_agent() -> MailAgent:
    # 仪表板为展示用途：生成回复文本但不推送 Gmail 草稿、不发送
    return MailAgent(load_config(), create_drafts=False)


def _get_calendar_store(config=None):
    """根据配置返回日历后端：Google Calendar 或本地 JSON。

    Google 授权不可用时回落到本地存储，保证页面不崩。
    """
    config = config or load_config()
    if config.google.enabled:
        try:
            from mail_agent.gapi.auth import get_credentials
            from mail_agent.gapi.gcalendar import GoogleCalendarClient

            creds = get_credentials(config.google, allow_interactive=False)
            return GoogleCalendarClient(config.google, credentials=creds)
        except Exception:  # noqa: BLE001
            pass
    return CalendarStore(config.calendar)


def _today_window() -> tuple[datetime, datetime]:
    """返回 (今天 00:00, 明天 00:00)。"""
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


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
def api_demo():
    store = _get_result_store()
    agent = _get_agent()
    results = agent.process_emails(SAMPLE_EMAILS)
    store.add_many(results)
    return {"count": len(results), "message": f"已处理 {len(results)} 封邮件"}


@api_router.post("/emails/fetch")
async def api_fetch_emails(request: Request):
    """拉取未读邮件并处理，用于在仪表板展示摘要/回复/日程。

    展示导向：生成回复草稿文本供查看，但不推送 Gmail 草稿、不发送、不标记已读。
    """
    config = load_config()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        limit = int(body.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))  # 钳制，避免一次拉取过多阻塞

    try:
        if config.google.enabled:
            from mail_agent.gapi.auth import get_credentials
            from mail_agent.gapi.gmail import GmailClient

            creds = get_credentials(config.google, allow_interactive=False)
            gmail = GmailClient(config.google, credentials=creds)
            emails = gmail.fetch_unread(limit=limit)
            agent = MailAgent(
                config,
                gmail_client=gmail,
                send_replies=False,
                create_drafts=False,
                mark_read=False,
            )
        else:
            if not config.imap.host:
                return JSONResponse(
                    {"success": False, "message": "未启用 Google 且未配置 IMAP"},
                    status_code=400,
                )
            with IMAPFetcher(config.imap) as fetcher:
                emails = fetcher.fetch_unread(limit=limit)
            agent = MailAgent(config)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            {"success": False, "message": f"获取邮件失败: {e}"}, status_code=400
        )

    if not emails:
        return {"success": True, "count": 0, "message": "没有未读邮件"}

    results = agent.process_emails(emails)
    _get_result_store().add_many(results)
    return {
        "success": True,
        "count": len(results),
        "message": f"已处理 {len(results)} 封真实邮件",
    }


@api_router.post("/selfcheck")
async def api_selfcheck(request: Request):
    """对真实 Gmail / Calendar 跑读写回读自验证，返回逐项结果"""
    config = load_config()
    if not config.google.enabled:
        return JSONResponse(
            {"success": False, "message": "未启用 Google"}, status_code=400
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    include_send = bool(body.get("send", False))

    try:
        from mail_agent.gapi.auth import get_credentials
        from mail_agent.gapi.gcalendar import GoogleCalendarClient
        from mail_agent.gapi.gmail import GmailClient
        from mail_agent.gapi.verify import RoundTripVerifier

        creds = get_credentials(config.google, allow_interactive=False)
        verifier = RoundTripVerifier(
            gmail=GmailClient(config.google, credentials=creds),
            calendar=GoogleCalendarClient(config.google, credentials=creds),
            redirect_to=config.testing.redirect_to,
        )
        results = verifier.run_all(cleanup=True, include_send=include_send)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            {"success": False, "message": f"自检失败: {e}"}, status_code=400
        )

    all_passed = all(r.passed for r in results)
    return {
        "success": all_passed,
        "redirect_to": config.testing.redirect_to,
        "results": [r.model_dump() for r in results],
    }


@api_router.get("/google/status")
def api_google_status():
    """返回 Google 集成状态，供前端展示是否已授权"""
    config = load_config()
    status = {
        "enabled": config.google.enabled,
        "credentials_exists": config.google.credentials_path.exists(),
        "authorized": False,
        "calendar_id": config.google.calendar_id,
    }
    if config.google.enabled:
        try:
            from mail_agent.gapi.auth import get_credentials

            get_credentials(config.google, allow_interactive=False)
            status["authorized"] = True
        except Exception:  # noqa: BLE001
            status["authorized"] = False
    return status


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
def api_emails_partial(
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


def _iso_or(default, value):
    if not value:
        return default
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return default


@api_router.get("/calendar/events")
def api_calendar_events(
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    # 同步处理函数（无 await）→ Starlette 在线程池执行，不阻塞事件循环
    config = load_config()
    store = _get_calendar_store(config)

    start_dt = _iso_or(datetime.now() - timedelta(days=90), start)
    end_dt = _iso_or(datetime.now() + timedelta(days=90), end)

    events = store.list_events(start=start_dt, end=end_dt)

    # 颜色：一次性建立 message_id → 紧急度 索引（避免每事件全表扫描）
    level_by_mid = {
        r.email.message_id: r.priority.level.value
        for r in _get_result_store().list_results()
        if r.email.message_id
    }

    def _aw(dt):
        return dt if dt.tzinfo is not None else dt.astimezone()

    fc_events = []
    for i, evt in enumerate(events):
        color = URGENCY_COLORS.get(level_by_mid.get(evt.source_email_id), "#3498db")
        # 冲突检测在已取窗口内内存计算（避免每事件一次后端往返）
        has_conflict = any(
            j != i
            and _aw(o.start_time) < _aw(evt.end_time)
            and _aw(evt.start_time) < _aw(o.end_time)
            for j, o in enumerate(events)
        )

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
def api_delete_calendar_event(event_id: str):
    config = load_config()
    store = _get_calendar_store(config)
    if store.remove_event(event_id):
        return {"message": "事件已删除"}
    return JSONResponse({"message": "事件未找到"}, status_code=404)


# ── 提醒端点 ──


@api_router.get("/reminders")
def api_reminders():
    store = _get_result_store()
    config = load_config()
    cal_store = _get_calendar_store(config)

    today_start, today_end = _today_window()

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
def api_reminders_count():
    store = _get_result_store()
    return {"count": len(store.get_urgent())}


@api_router.get("/reminders/partial", response_class=HTMLResponse)
def api_reminders_partial(
    request: Request,
    section: str = Query("urgent"),
):
    store = _get_result_store()
    config = load_config()
    cal_store = _get_calendar_store(config)

    today_start, today_end = _today_window()

    template_map = {
        "urgent": ("partials/_reminders_urgent.html", {"results": store.get_urgent()}),
        "deadlines": ("partials/_reminders_deadlines.html", {"results": store.get_deadlines()}),
        "today": ("partials/_reminders_today.html", {"events": cal_store.list_events(start=today_start, end=today_end)}),
    }

    template_name, ctx = template_map.get(section, template_map["urgent"])
    return _templates.TemplateResponse(request=request, name=template_name, context=ctx)


# ── 总结端点 ──


@api_router.get("/summary")
def api_summary():
    store = _get_result_store()
    results = store.list_results()

    from mail_agent.understanding.summarizer import EmailSummarizer

    summarizer = EmailSummarizer()
    stats = summarizer.generate_stats(results)
    return stats


@api_router.get("/summary/briefing")
def api_summary_briefing():
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
def api_get_settings():
    store = _get_settings_store()
    data = store.get_redacted()
    # 如果没有保存过设置，用默认值填充
    config = load_config()
    # Google 授权状态（只读，不写入 settings）
    google_authorized = False
    if config.google.enabled:
        try:
            from mail_agent.gapi.auth import get_credentials

            get_credentials(config.google, allow_interactive=False)
            google_authorized = True
        except Exception:  # noqa: BLE001
            google_authorized = False

    defaults = {
        "llm": {
            "api_key": "",
            "model": config.llm.model,
            "base_url": config.llm.base_url,
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
        "google": {
            "enabled": config.google.enabled,
            "calendar_id": config.google.calendar_id,
            "credentials_exists": config.google.credentials_path.exists(),
            "authorized": google_authorized,
        },
        "testing": {
            "redirect_to": config.testing.redirect_to,
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

        llm_cfg = LLMConfig(api_key=api_key)
        if body.get("model"):
            llm_cfg.model = body["model"]
        if body.get("base_url"):
            llm_cfg.base_url = body["base_url"]
        client = LLMClient(llm_cfg)
        response = client.chat(
            [{"role": "user", "content": "Say OK"}],
            max_tokens=10,
        )
        ok = bool(response and response.strip())
        return {
            "success": ok,
            "message": f"连接成功 ({llm_cfg.model})" if ok else "连接失败：无响应",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("test-llm 失败: %s", e)
        return {"success": False, "message": "连接失败：请检查 API Key / 模型 / 端点"}


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
    except Exception as e:  # noqa: BLE001
        logger.warning("test-imap 失败: %s", e)
        return {"success": False, "message": "连接失败：请检查主机/端口/账号/密码"}
