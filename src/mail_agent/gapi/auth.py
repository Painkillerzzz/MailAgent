"""Google OAuth2 授权

负责加载/刷新/创建 OAuth2 凭据。首次授权通过本地浏览器 (InstalledAppFlow)，
之后 token 缓存到磁盘，过期自动用 refresh_token 刷新。
"""

from __future__ import annotations

import logging
from pathlib import Path

from mail_agent.config import GoogleConfig

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    """Google 授权相关错误"""


def get_credentials(config: GoogleConfig, *, allow_interactive: bool = True):
    """获取有效的 Google OAuth2 凭据

    Args:
        config: Google 配置
        allow_interactive: 当没有有效 token 时是否允许弹出浏览器授权。
            在服务器/Web 场景下应设为 False，避免阻塞。

    Returns:
        google.oauth2.credentials.Credentials 实例

    Raises:
        GoogleAuthError: 凭据缺失或无法在非交互模式下完成授权
    """
    # 延迟导入，避免未安装 Google 依赖时影响其它功能
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = Path(config.token_path)
    creds_path = Path(config.credentials_path)
    scopes = config.scopes

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 token 失败，将重新授权: %s", e)
            creds = None

    # token 有效直接返回
    if creds and creds.valid:
        return creds

    # token 过期但可刷新
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(token_path, creds)
            return creds
        except Exception as e:  # noqa: BLE001
            logger.warning("刷新 token 失败，需要重新授权: %s", e)
            creds = None

    # 需要全新授权
    if not allow_interactive:
        raise GoogleAuthError(
            f"没有有效的 Google 授权 token（{token_path}）。"
            "请先在终端运行 `uv run mail-agent auth` 完成一次浏览器授权。"
        )

    flow = _build_flow(config, creds_path, scopes, InstalledAppFlow)
    # port=0 自动选择空闲端口
    creds = flow.run_local_server(port=0)
    _save_token(token_path, creds)
    logger.info("Google 授权成功，token 已保存到 %s", token_path)
    return creds


def _build_flow(config: GoogleConfig, creds_path: Path, scopes, InstalledAppFlow):
    """构建 OAuth 授权 flow

    优先级：
      1. 合法的 credentials.json 文件（Google Cloud 下载的标准格式）
      2. 环境变量 GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET
    """
    import json

    # 1) 尝试标准 credentials.json
    if creds_path.exists():
        raw = creds_path.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 常见错误：文件里只粘了一行裸的 client ID
            hint = ""
            if raw.endswith(".apps.googleusercontent.com") and "{" not in raw:
                hint = (
                    "\n检测到该文件只包含一个裸的 client ID，缺少 client_secret 等字段。"
                    "\n请改用以下任一方式："
                    "\n  A) 在 Google Cloud「凭据」页点该 OAuth 客户端的下载按钮，"
                    "用下载到的完整 JSON 覆盖 credentials.json；"
                    "\n  B) 在 .env 设置 GOOGLE_CLIENT_ID 和 GOOGLE_CLIENT_SECRET（无需此文件）。"
                )
            raise GoogleAuthError(
                f"credentials.json 不是合法的 OAuth 凭据 JSON：{creds_path}{hint}"
            )
        if isinstance(data, dict) and ("installed" in data or "web" in data):
            return InstalledAppFlow.from_client_config(data, scopes)
        raise GoogleAuthError(
            f"credentials.json 缺少 'installed'/'web' 顶层字段：{creds_path}\n"
            "请从 Google Cloud Console 下载「桌面应用」类型的 OAuth 客户端 JSON。"
        )

    # 2) 回退到环境变量提供的 client_id / client_secret
    if config.client_id and config.client_secret:
        client_config = {
            "installed": {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"],
            }
        }
        return InstalledAppFlow.from_client_config(client_config, scopes)

    raise GoogleAuthError(
        f"找不到 OAuth 客户端凭据：{creds_path} 不存在，且未设置 "
        "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET。\n"
        "请在 Google Cloud Console 创建 OAuth 客户端（桌面应用类型），"
        "下载 credentials.json 放到该路径，或把 client_id/secret 写入 .env。"
    )


def _save_token(token_path: Path, creds) -> None:
    """持久化 token 到磁盘"""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
