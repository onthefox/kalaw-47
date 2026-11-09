"""Google-провайдер (issue #9, задача 2): Gemini Pro через google-generativeai."""

from __future__ import annotations

from core.llm.base import (
    SYSTEM_PROMPT,
    IntentResult,
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    RateLimitError,
    parse_intent_json,
    result_from_parsed,
)

_GEMINI_MODEL = "gemini-1.5-flash"


class GoogleProvider(LLMProvider):
    """Async-обёртка (SDK синхронный) над Gemini; usage из usage_metadata."""

    def __init__(self, api_key: str | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.last_usage: dict[str, int] = {}
        self._configured_key: str | None = None

    def get_name(self) -> str:
        return "google"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import google.generativeai  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure_model(self):
        import google.generativeai as genai

        if self._configured_key != self.api_key:
            genai.configure(api_key=self.api_key)
            self._configured_key = self.api_key
        return genai.GenerativeModel(
            model_name=_GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
        )

    def _generate_sync(self, text: str):
        import google.api_core.exceptions as gexc

        model = self._ensure_model()
        try:
            return model.generate_content(
                text,
                generation_config={"temperature": 0.0, "max_output_tokens": 512},
                request_options={"timeout": self.timeout},
            )
        except gexc.DeadlineExceeded as exc:
            raise LLMTimeoutError(f"Google timeout: {exc}") from exc
        except gexc.ResourceExhausted as exc:
            raise RateLimitError(f"Google rate limit: {exc}") from exc
        except gexc.Unauthenticated as exc:
            raise LLMError(f"Google auth error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - любые ошибки SDK → LLMError
            raise LLMError(f"Google error: {exc}") from exc

    async def interpret(self, text: str) -> IntentResult:
        """generate_content через to_thread; маппинг usage_metadata."""
        self.last_usage = {}
        response = await asyncio_to_thread(self._generate_sync, text)
        raw = (response.text or "").strip() if hasattr(response, "text") else ""
        metadata = getattr(response, "usage_metadata", None)
        self.last_usage = {
            "input_tokens": getattr(metadata, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(metadata, "candidates_token_count", 0) or 0,
        }
        parsed = parse_intent_json(raw)
        return result_from_parsed(
            parsed,
            self.get_name(),
            raw=raw,
            input_tokens=self.last_usage["input_tokens"],
            output_tokens=self.last_usage["output_tokens"],
        )


def asyncio_to_thread(func, /, *args, **kwargs):
    """Обёртка asyncio.to_thread, чтобы не тащить импорт на верхний уровень."""
    import asyncio

    return asyncio.to_thread(func, *args, **kwargs)
