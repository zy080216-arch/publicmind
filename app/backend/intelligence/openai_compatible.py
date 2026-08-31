"""OpenAI Chat Completions-compatible JSON generation adapter."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import httpx

from .base import LLMProviderError


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMProviderError("模型没有返回可解析的 JSON") from exc
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested:
            raise LLMProviderError("模型返回的 JSON 格式不完整") from nested
    if not isinstance(payload, dict):
        raise LLMProviderError("模型返回结果必须是 JSON 对象")
    return payload


class OpenAICompatibleProvider:
    """DeepSeek's OpenAI-compatible Chat Completions adapter.

    The generic class name is kept because tests and future providers can still
    inject another compatible base URL, while the product defaults are now
    intentionally DeepSeek-specific.
    """

    name = "deepseek"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("PUBLICMIND_LLM_API_KEY")
        )
        self.base_url = (
            base_url
            or os.getenv("PUBLICMIND_LLM_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.model = model or os.getenv("PUBLICMIND_LLM_MODEL") or "deepseek-v4-flash"
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate_json(self, system: str, prompt: str) -> Dict[str, Any]:
        if not self.configured:
            raise LLMProviderError(
                "DeepSeek 尚未配置：请在本机设置页填写 DeepSeek API Key。"
            )
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": "Bearer %s" % self.api_key, "Content-Type": "application/json"}
        try:
            response = httpx.post(
                self.base_url + "/chat/completions",
                headers=headers,
                json=body,
                timeout=self.timeout,
            )
            if response.status_code in {400, 404, 422}:
                body.pop("response_format", None)
                response = httpx.post(
                    self.base_url + "/chat/completions",
                    headers=headers,
                    json=body,
                    timeout=self.timeout,
                )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("模型服务调用失败：%s" % exc) from exc
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        return _extract_json(str(content))
