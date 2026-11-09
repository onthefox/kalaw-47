"""
LLM-провайдеры (issue #9): OpenAI, Anthropic, Google (Gemini).

Все запросы идут через httpx; ключи берутся из окружения
(OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY) и никогда не логируются.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from engine.llm.base import LLMError, LLMProvider, SYSTEM_PROMPT

logger = logging.getLogger("symbio.llm")

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
DEFAULT_GOOGLE_MODEL = "gemini-1.5-flash"


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions с JSON-ответом."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            model=model or DEFAULT_OPENAI_MODEL,
            base_url=base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=timeout,
        )
        self.last_usage = None

    def interpret(self, text: str) -> dict[str, Any]:
        if not self.available:
            raise LLMError("OpenAI: отсутствует API-ключ")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 300,
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI запрос не удался: {exc}") from exc
        data = response.json()
        self.last_usage = data.get("usage")
        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Неожиданный ответ OpenAI: {data}") from exc
        return self.parse_json_response(raw)


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            model=model or DEFAULT_ANTHROPIC_MODEL,
            base_url=base_url or "https://api.anthropic.com",
            timeout=timeout,
        )

    def interpret(self, text: str) -> dict[str, Any]:
        if not self.available:
            raise LLMError("Anthropic: отсутствует API-ключ")
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": 300,
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": self.api_key or "",
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic запрос не удался: {exc}") from exc
        data = response.json()
        self.last_usage = data.get("usage")
        try:
            raw = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Неожиданный ответ Anthropic: {data}") from exc
        return self.parse_json_response(raw)


class GoogleProvider(LLMProvider):
    """Google Gemini generateContent."""

    name = "google"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
            model=model or DEFAULT_GOOGLE_MODEL,
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta",
            timeout=timeout,
        )

    def interpret(self, text: str) -> dict[str, Any]:
        if not self.available:
            raise LLMError("Google: отсутствует API-ключ")
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Google запрос не удался: {exc}") from exc
        data = response.json()
        usage = data.get("usageMetadata")
        if usage:
            self.last_usage = {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
            }
        try:
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Неожиданный ответ Google: {data}") from exc
        return self.parse_json_response(raw)


def default_providers() -> list[LLMProvider]:
    """Провайдеры по умолчанию в порядке fallback-цепочки."""
    return [OpenAIProvider(), AnthropicProvider(), GoogleProvider()]
