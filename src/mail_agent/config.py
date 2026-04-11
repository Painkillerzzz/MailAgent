"""应用配置管理"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


class LLMConfig(BaseModel):
    """LLM 配置"""

    api_key: str = Field(default_factory=lambda: os.getenv("ZAI_API_KEY", ""))
    model: str = "glm-5"
    temperature: float = 0.7
    max_tokens: int = 1024


class IMAPConfig(BaseModel):
    """IMAP 邮箱配置"""

    host: str = Field(default_factory=lambda: os.getenv("IMAP_HOST", ""))
    port: int = int(os.getenv("IMAP_PORT", "993"))
    username: str = Field(default_factory=lambda: os.getenv("IMAP_USERNAME", ""))
    password: str = Field(default_factory=lambda: os.getenv("IMAP_PASSWORD", ""))
    use_ssl: bool = True
    mailbox: str = "INBOX"


class CalendarConfig(BaseModel):
    """日历配置"""

    storage_path: Path = DATA_DIR / "calendar.json"


class UserProfile(BaseModel):
    """用户个人信息，用于生成个性化回复"""

    name: str = Field(default_factory=lambda: os.getenv("USER_NAME", "Xiangyu"))
    email: str = Field(
        default_factory=lambda: os.getenv(
            "USER_EMAIL", "xinagyuz22@mails.tsinghua.edu.cn"
        )
    )
    tone: str = "polite and concise"
    signature: str = ""


class AppConfig(BaseModel):
    """应用总配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    imap: IMAPConfig = Field(default_factory=IMAPConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    user: UserProfile = Field(default_factory=UserProfile)


def _load_settings_overrides() -> dict:
    """从 data/settings.json 读取用户通过 Web UI 保存的配置"""
    settings_path = DATA_DIR / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        import json

        return json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config() -> AppConfig:
    """加载应用配置

    优先级：data/settings.json > 环境变量 > 默认值
    """
    overrides = _load_settings_overrides()
    config = AppConfig()

    if "llm" in overrides:
        llm = overrides["llm"]
        if llm.get("api_key") and not llm["api_key"].startswith("****"):
            config.llm.api_key = llm["api_key"]
        if llm.get("model"):
            config.llm.model = llm["model"]
        if "temperature" in llm:
            config.llm.temperature = float(llm["temperature"])
        if "max_tokens" in llm:
            config.llm.max_tokens = int(llm["max_tokens"])

    if "imap" in overrides:
        imap = overrides["imap"]
        if imap.get("host"):
            config.imap.host = imap["host"]
        if imap.get("port"):
            config.imap.port = int(imap["port"])
        if imap.get("username"):
            config.imap.username = imap["username"]
        if imap.get("password") and not imap["password"].startswith("****"):
            config.imap.password = imap["password"]

    if "user" in overrides:
        user = overrides["user"]
        if user.get("name"):
            config.user.name = user["name"]
        if user.get("email"):
            config.user.email = user["email"]
        if user.get("tone"):
            config.user.tone = user["tone"]
        if "signature" in user:
            config.user.signature = user["signature"]

    return config
