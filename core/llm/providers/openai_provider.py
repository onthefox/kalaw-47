"""OpenAI-провайдер (issue #9, задача 2): GPT-4 через официальный SDK."""

from __future__ import annotations

import asyncio

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

_OPENAI_MODEL = "gpt-4o-mini"


class OpenAIProvider(LLMProvider):
    """Async-провайдер chat completions; input tokens считает tiktoken."""

    def __init__(self, api_key: str | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.last_usage: dict[str, int] = {}

    def get_name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
            import tiktoken  # noqa: F401
        except ImportError:
            return False
        return True

    def _count_input_tokens(self, text: str) -> int:
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(SYSTEM_PROMPT + text))
        except ImportError:
            return 0

    async def interpret(self, text: str) -> IntentResult:
        """Chat completion с GPT-4 и маппингом ответа в IntentResult."""
        import openai

        self.last_usage = {}
        input_tokens = self._count_input_tokens(text)
        try:
            client = openai.AsyncOpenAI(api_key=self.api_key, timeout=self.timeout)
            response = await client.chat.completions.create(
                model=_OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=512,
            )
        except openai.RateLimitError as exc:
            raise RateLimitError(f"OpenAI rate limit: {exc}") from exc
        except openai.AuthenticationError as exc:
            raise AuthenticationError(f"OpenAI auth error: {exc}") from exc
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError(f"OpenAI timeout: {exc}") from exc
        except openai.OpenAIError as exc:
            raise LLMError(f"OpenAI error: {exc}") from exc

        raw = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": input_tokens or getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
        }
        parsed = parse_intent_json(raw)
        return result_from_parsed(
            parsed,
            self.get_name(),
            raw=raw,
            input_tokens=self.last_usage["input_tokens"],
            output_tokens=self.last_usage["output_tokens"],
        )


async def _main() -> None:  # pragma: no cover - ручная проверка
    provider = OpenAIProvider()
    result = await provider.interpret("создай сущность Молоко")
    print(result)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
