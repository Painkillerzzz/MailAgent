"""用户设置持久化存储

持久化到 data/settings.json，支持密钥脱敏、键白名单与原子写入。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mail_agent.config import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = DATA_DIR / "settings.json"

# 需要脱敏的字段路径
_SECRET_FIELDS = {"llm.api_key", "imap.password"}
_REDACT_PLACEHOLDER = "****"

# 仅允许保存这些键；其余（尤其 google.credentials_path / token_path 等文件路径）
# 一律丢弃，避免通过设置接口写入任意路径或污染敏感配置。
_ALLOWED: dict[str, set[str]] = {
    "llm": {"api_key", "model", "base_url", "temperature", "max_tokens"},
    "imap": {"host", "port", "username", "password"},
    "user": {"name", "email", "tone", "signature"},
    "google": {"enabled", "calendar_id"},
    "testing": {"redirect_to"},
}


def _redact(value: str) -> str:
    if not value or len(value) <= 4:
        return _REDACT_PLACEHOLDER
    return _REDACT_PLACEHOLDER + value[-4:]


def _is_redacted(value: str) -> bool:
    return value.startswith(_REDACT_PLACEHOLDER)


def _sanitize(new_data: dict) -> dict:
    """仅保留白名单内的 section/key。"""
    out: dict = {}
    for section, keys in _ALLOWED.items():
        if isinstance(new_data.get(section), dict):
            kept = {k: v for k, v in new_data[section].items() if k in keys}
            if kept:
                out[section] = kept
    return out


class SettingsStore:
    """JSON 持久化设置存储"""

    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_SETTINGS_PATH
        self._data: dict = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("设置加载失败: %s", e)
                self._data = {}

    def _save(self):
        """原子写入并设为 0600，避免半写损坏与凭据被他人读取。"""
        from mail_agent.io_utils import atomic_write_text

        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        atomic_write_text(self._path, payload, mode=0o600)

    def get_raw(self) -> dict:
        """获取原始设置（含完整密钥）"""
        return dict(self._data)

    def get_redacted(self) -> dict:
        """获取脱敏后的设置"""
        import copy

        data = copy.deepcopy(self._data)
        for field_path in _SECRET_FIELDS:
            parts = field_path.split(".")
            obj = data
            for p in parts[:-1]:
                obj = obj.get(p, {})
            key = parts[-1]
            if key in obj and obj[key]:
                obj[key] = _redact(obj[key])
        return data

    def save(self, new_data: dict):
        """保存设置：先按白名单清洗键，再处理脱敏占位符（占位符则保留原值）。"""
        new_data = _sanitize(new_data)
        for field_path in _SECRET_FIELDS:
            parts = field_path.split(".")
            new_obj = new_data
            for p in parts[:-1]:
                new_obj = new_obj.get(p, {})
            key = parts[-1]
            new_val = new_obj.get(key, "")
            if new_val and _is_redacted(new_val):
                old_obj = self._data
                for p in parts[:-1]:
                    old_obj = old_obj.get(p, {})
                original = old_obj.get(key, "")
                if original:
                    new_obj[key] = original

        self._data = new_data
        self._save()

    def get_value(self, section: str, key: str, default: str = "") -> str:
        """获取某个设置值"""
        return self._data.get(section, {}).get(key, default)
