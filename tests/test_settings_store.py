"""SettingsStore 测试"""

import pytest

from mail_agent.web.settings_store import SettingsStore


class TestSettingsStore:
    @pytest.fixture
    def store(self, tmp_path):
        return SettingsStore(path=tmp_path / "settings.json")

    def test_empty_initial(self, store):
        assert store.get_raw() == {}
        assert store.get_redacted() == {}

    def test_save_and_load(self, store):
        data = {
            "llm": {"api_key": "sk-abc123xyz", "model": "glm-5"},
            "user": {"name": "Test"},
        }
        store.save(data)
        raw = store.get_raw()
        assert raw["llm"]["api_key"] == "sk-abc123xyz"
        assert raw["user"]["name"] == "Test"

    def test_redact_api_key(self, store):
        store.save({"llm": {"api_key": "sk-abc123xyz"}})
        redacted = store.get_redacted()
        assert redacted["llm"]["api_key"] == "****3xyz"

    def test_redact_imap_password(self, store):
        store.save({"imap": {"password": "mypassword123"}})
        redacted = store.get_redacted()
        assert redacted["imap"]["password"] == "****d123"

    def test_redact_short_value(self, store):
        store.save({"llm": {"api_key": "ab"}})
        redacted = store.get_redacted()
        assert redacted["llm"]["api_key"] == "****"

    def test_save_preserves_redacted_values(self, store):
        store.save({"llm": {"api_key": "real-secret-key-12345"}})
        # 模拟 Web UI 提交脱敏值
        store.save({"llm": {"api_key": "****2345", "model": "glm-4"}})
        raw = store.get_raw()
        assert raw["llm"]["api_key"] == "real-secret-key-12345"
        assert raw["llm"]["model"] == "glm-4"

    def test_get_value(self, store):
        store.save({"user": {"name": "Alice"}})
        assert store.get_value("user", "name") == "Alice"
        assert store.get_value("user", "missing", "default") == "default"
        assert store.get_value("nonexistent", "key", "fallback") == "fallback"

    def test_persistence(self, tmp_path):
        path = tmp_path / "settings.json"
        store1 = SettingsStore(path=path)
        store1.save({"llm": {"model": "glm-5"}})
        store2 = SettingsStore(path=path)
        assert store2.get_raw()["llm"]["model"] == "glm-5"


class TestConfigIntegration:
    """测试 config.py 读取 settings.json"""

    def test_load_config_with_overrides(self, tmp_path):
        import json

        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "llm": {"model": "glm-4-flash"},
            "user": {"name": "Override User", "tone": "formal"},
        }))

        from mail_agent.config import DATA_DIR, _load_settings_overrides

        # 直接测试 override 函数（通过临时写入 DATA_DIR）
        import mail_agent.config as cfg
        original_dir = cfg.DATA_DIR
        try:
            cfg.DATA_DIR = tmp_path
            overrides = _load_settings_overrides()
            assert overrides["llm"]["model"] == "glm-4-flash"
            assert overrides["user"]["name"] == "Override User"
        finally:
            cfg.DATA_DIR = original_dir

    def test_load_config_no_settings_file(self, tmp_path):
        """没有 settings.json 时应正常回落到环境变量"""
        import mail_agent.config as cfg

        original_dir = cfg.DATA_DIR
        try:
            cfg.DATA_DIR = tmp_path  # 指向空目录
            from mail_agent.config import load_config

            config = load_config()
            assert config.llm.model == "glm-4.6"
        finally:
            cfg.DATA_DIR = original_dir
