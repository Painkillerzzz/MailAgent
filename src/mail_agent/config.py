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
    model: str = Field(default_factory=lambda: os.getenv("ZAI_MODEL", "glm-4.6"))
    # 自定义 API 端点。Coding Plan 需用专属地址：
    # https://open.bigmodel.cn/api/coding/paas/v4
    base_url: str = Field(default_factory=lambda: os.getenv("ZAI_BASE_URL", ""))
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
    # 空闲感知改期建议：工作时间窗口与搜索参数
    work_start_hour: int = 9
    work_end_hour: int = 18
    slot_granularity_min: int = 30
    suggest_count: int = 3
    search_days: int = 5


class GoogleConfig(BaseModel):
    """Google (Gmail + Calendar) OAuth2 配置

    通过 Google Cloud 项目下载的 OAuth 客户端凭据 (credentials.json) 完成授权，
    首次授权会在浏览器中确认，token 缓存到 token.json 后续免登录。
    """

    enabled: bool = Field(
        default_factory=lambda: os.getenv("GOOGLE_ENABLED", "").lower()
        in ("1", "true", "yes")
    )
    credentials_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("GOOGLE_CREDENTIALS", str(PROJECT_ROOT / "credentials.json"))
        )
    )
    # 备选：不放 credentials.json，直接用环境变量提供 client_id/secret
    client_id: str = Field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", ""))
    client_secret: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_CLIENT_SECRET", "")
    )
    token_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("GOOGLE_TOKEN", str(DATA_DIR / "token.json"))
        )
    )
    # 目标日历 ID，"primary" 为用户主日历
    calendar_id: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_CALENDAR_ID", "primary")
    )
    # OAuth 授权范围：读写邮件 + 发送 + 日历
    scopes: list[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
        ]
    )


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


class TestingConfig(BaseModel):
    """测试配置

    开启重定向后，所有外发回复都改投到测试邮箱，并在正文标注真实目标收件人，
    避免测试邮件误发给真实联系人。
    """

    # 测试重定向目标邮箱
    redirect_to: str = Field(
        default_factory=lambda: os.getenv(
            "TEST_REDIRECT_TO", "zhangxiangyu40@qq.com"
        )
    )


class AppConfig(BaseModel):
    """应用总配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    imap: IMAPConfig = Field(default_factory=IMAPConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    user: UserProfile = Field(default_factory=UserProfile)
    testing: TestingConfig = Field(default_factory=TestingConfig)


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
        if "base_url" in llm:
            config.llm.base_url = llm["base_url"]
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

    if "google" in overrides:
        google = overrides["google"]
        if "enabled" in google:
            config.google.enabled = bool(google["enabled"])
        if google.get("calendar_id"):
            config.google.calendar_id = google["calendar_id"]
        # 安全：credentials_path / token_path 只能来自环境变量/.env，
        # 不接受来自 settings.json（防止经设置接口写入任意路径）。

    if "testing" in overrides:
        testing = overrides["testing"]
        if testing.get("redirect_to"):
            config.testing.redirect_to = testing["redirect_to"]

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
