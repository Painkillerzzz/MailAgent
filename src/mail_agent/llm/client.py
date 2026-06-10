"""智谱AI LLM 客户端封装"""

from __future__ import annotations

import json
import logging
from typing import Any

from zhipuai import ZhipuAI

from mail_agent.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMClient:
    """智谱AI GLM 大模型客户端"""

    def __init__(self, config: LLMConfig | None = None):
        if config is None:
            config = LLMConfig()
        self._config = config
        if not config.api_key:
            raise ValueError("ZAI_API_KEY 未设置，请在 .env 文件中配置")
        if getattr(config, "base_url", ""):
            self._client = ZhipuAI(api_key=config.api_key, base_url=config.base_url)
        else:
            self._client = ZhipuAI(api_key=config.api_key)

    @property
    def model(self) -> str:
        return self._config.model

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送聊天请求并返回文本回复

        Args:
            messages: 消息列表，格式 [{"role": "system"/"user"/"assistant", "content": "..."}]
            temperature: 生成温度，覆盖默认值
            max_tokens: 最大 token 数，覆盖默认值

        Returns:
            模型回复的文本内容
        """
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            temperature=temperature or self._config.temperature,
            max_tokens=max_tokens or self._config.max_tokens,
        )
        content = response.choices[0].message.content
        logger.debug("LLM response: %s", content)
        return content

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """发送聊天请求并解析 JSON 回复

        Returns:
            解析后的 JSON 字典
        """
        raw = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        # 处理可能被 markdown 代码块包裹的 JSON
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉首尾的 ``` 行
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 容错：截取第一个 {...} 对象再试
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"LLM 未返回可解析的 JSON: {text[:120]!r}")
