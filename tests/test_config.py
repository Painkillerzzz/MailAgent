"""配置模块测试"""

import os

from mail_agent.config import (
    AppConfig,
    CalendarConfig,
    IMAPConfig,
    LLMConfig,
    UserProfile,
    load_config,
)


class TestLLMConfig:
    def test_default_model(self):
        config = LLMConfig()
        assert config.model == "glm-4.6"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ZAI_API_KEY", "test-key-123")
        assert LLMConfig().api_key == "test-key-123"

    def test_custom_values(self):
        config = LLMConfig(model="glm-4", temperature=0.5, max_tokens=2048)
        assert config.model == "glm-4"
        assert config.temperature == 0.5
        assert config.max_tokens == 2048


class TestIMAPConfig:
    def test_default_values(self):
        config = IMAPConfig()
        assert config.port == 993
        assert config.use_ssl is True
        assert config.mailbox == "INBOX"


class TestUserProfile:
    def test_default_values(self):
        profile = UserProfile()
        assert profile.name == "Xiangyu"
        assert profile.tone == "polite and concise"

    def test_custom_values(self):
        profile = UserProfile(name="Test User", tone="formal")
        assert profile.name == "Test User"
        assert profile.tone == "formal"


class TestAppConfig:
    def test_load_config(self):
        config = load_config()
        assert isinstance(config, AppConfig)
        assert isinstance(config.llm, LLMConfig)
        assert isinstance(config.imap, IMAPConfig)
        assert isinstance(config.calendar, CalendarConfig)
        assert isinstance(config.user, UserProfile)

    def test_nested_defaults(self):
        config = AppConfig()
        assert config.llm.model == "glm-4.6"
        assert config.calendar.storage_path is not None
        assert config.google is not None
        assert config.testing.redirect_to
