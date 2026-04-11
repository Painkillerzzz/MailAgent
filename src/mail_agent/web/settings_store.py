"""用户设置持久化存储

持久化到 data/settings.json，支持密钥脱敏。
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


def _redact(value: str) -> str:
    if not value or len(value) <= 4:
        return _REDACT_PLACEHOLDER
    return _REDACT_PLACEHOLDER + value[-4:]


def _is_redacted(value: str) -> bool:
    return value.startswith(_REDACT_PLACEHOLDER)


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
            except Exception as e:
                logger.warning("设置加载失败: %s", e)
                self._data = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        """保存设置（处理脱敏占位符）

        如果提交的值是脱敏占位符，保留原始值。
        """
        for field_path in _SECRET_FIELDS:
            parts = field_path.split(".")
            # 获取新值
            new_obj = new_data
            for p in parts[:-1]:
                new_obj = new_obj.get(p, {})
            key = parts[-1]
            new_val = new_obj.get(key, "")

            if new_val and _is_redacted(new_val):
                # 保留原始值
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
