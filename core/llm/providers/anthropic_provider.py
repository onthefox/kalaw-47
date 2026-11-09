"""Anthropic-провайдер (issue #9, задача 2): Claude через официальный SDK."""

from __future__ import annotations

from core.llm.base import (
    SYSTEM_PROMPT,
    AuthenticationError,
    IntentResult,
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    RateLimitError,
    parse_intent_json,
    result_from_parsed,
)

_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"


class AnthropicProvider(LLMProvider):
    """Async-провайдер Messages API; usage из response.usage."""

    def __init__(self, api_key: str | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.last_usage: dict[str, int] = {}

    def get_name(self) -> str:
        return "anthropic"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    async def interpret(self, text: str) -> IntentResult:
        """Messages API с Claude; маппинг usage в IntentResult."""
        import anthropic

        self.last_usage = {}
        try:
            client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
            message = await client.messages.create(
                model=_ANTHROPIC_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                max_tokens=512,
                temperature=0.0,
            )
        except anthropic.RateLimitError as exc:
            raise RateLimitError(f"Anthropic rate limit: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise AuthenticationError(f"Anthropic auth error: {exc}") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError(f"Anthropic timeout: {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise LLMError(f"Anthropic error: {exc}") from exc

        raw = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", "") == "text"
        )
        usage = getattr(message, "usage", None)
        self.last_usage = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
        parsed = parse_intent_json(raw)
        return result_from_parsed(
            parsed,
            self.get_name(),
            raw=raw,
            input_tokens=self.last_usage["input_tokens"],
            output_tokens=self.last_usage["output_tokens"],
        )
