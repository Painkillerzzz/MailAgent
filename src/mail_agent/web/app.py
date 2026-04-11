"""Web 应用主入口

FastAPI + Jinja2 + HTMX + Alpine.js
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mail_agent.config import load_config
from mail_agent.web.api import api_router, init_api
from mail_agent.web.result_store import ResultStore
from mail_agent.web.settings_store import SettingsStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "web_templates"
STATIC_DIR = PROJECT_ROOT / "static"

web_app = FastAPI(title="Mail Agent Dashboard")
web_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 持久化存储
result_store = ResultStore()
settings_store = SettingsStore()

# 初始化 API 模块
init_api(templates, result_store, settings_store)
web_app.include_router(api_router, prefix="/api")


# ── 页面路由 ──


@web_app.get("/", response_class=HTMLResponse)
async def emails_page(request: Request):
    """邮件列表页"""
    results = result_store.list_results()
    return templates.TemplateResponse(
        request=request,
        name="emails.html",
        context={"results": results, "total": result_store.count},
    )


@web_app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    """日历页"""
    return templates.TemplateResponse(request=request, name="calendar.html")


@web_app.get("/reminders", response_class=HTMLResponse)
async def reminders_page(request: Request):
    """提醒页"""
    return templates.TemplateResponse(request=request, name="reminders.html")


@web_app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置页"""
    return templates.TemplateResponse(request=request, name="settings.html")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动 Web 服务器"""
    import uvicorn

    uvicorn.run(web_app, host=host, port=port)
