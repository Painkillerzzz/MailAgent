"""LLM 客户端测试（使用真实智谱AI API）"""

import pytest

from mail_agent.config import LLMConfig
from mail_agent.llm.client import LLMClient


class TestLLMClientInit:
    def test_create_with_valid_key(self):
        client = LLMClient()
        assert client.model == "glm-4.6"

    def test_create_without_key_raises(self):
        config = LLMConfig(api_key="")
        with pytest.raises(ValueError, match="ZAI_API_KEY"):
            LLMClient(config)

    def test_custom_model(self):
        config = LLMConfig(model="glm-4-flash")
        client = LLMClient(config)
        assert client.model == "glm-4-flash"


class TestLLMChat:
    """集成测试：调用真实 API"""

    def test_basic_chat(self, llm_client):
        response = llm_client.chat(
            [{"role": "user", "content": "Reply with exactly: OK"}]
        )
        assert isinstance(response, str)
        assert len(response) > 0

    def test_system_prompt(self, llm_client):
        response = llm_client.chat(
            [
                {"role": "system", "content": "You only respond with numbers."},
                {"role": "user", "content": "What is 2+3?"},
            ]
        )
        assert "5" in response

    def test_temperature_zero(self, llm_client):
        """低温度应产生更确定的输出"""
        response = llm_client.chat(
            [{"role": "user", "content": "What is the capital of France? Answer in one word."}],
            temperature=0.0,
        )
        assert "Paris" in response or "paris" in response.lower()


class TestLLMChatJSON:
    """测试 JSON 解析能力"""

    def test_json_response(self, llm_client):
        response = llm_client.chat_json(
            [
                {
                    "role": "user",
                    "content": 'Respond with this exact JSON: {"name": "test", "value": 42}',
                }
            ]
        )
        assert isinstance(response, dict)
        assert response["name"] == "test"
        assert response["value"] == 42

    def test_json_with_markdown_wrapper(self, llm_client):
        """测试处理 markdown 代码块包裹的 JSON"""
        response = llm_client.chat_json(
            [
                {
                    "role": "system",
                    "content": "Respond with a JSON object wrapped in ```json code blocks.",
                },
                {
                    "role": "user",
                    "content": 'Return: {"status": "ok"}',
                },
            ]
        )
        assert isinstance(response, dict)
        assert response["status"] == "ok"
