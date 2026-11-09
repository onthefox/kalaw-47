"""
Fallback-цепочка LLM-провайдеров (issue #9): OpenAI → Anthropic → Google → rule-based.

Цепочка возвращает None, если ни один провайдер не смог разобрать намерение —
тогда вызывающий код (flow) падает обратно на rule-based парсер.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from engine.llm.base import LLMError, LLMProvider
from engine.llm.providers import default_providers
from engine.llm.rate_limit import CostTracker, RateLimiter

logger = logging.getLogger("symbio.llm")


class LLMChain:
    """Последовательно опрашивает провайдеров с rate limiting и учётом затрат."""

    def __init__(
        self,
        providers: list[LLMProvider] | None = None,
        rate_limiter: RateLimiter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self.providers = providers if providers is not None else default_providers()
        self.rate_limiter = rate_limiter or RateLimiter(max_calls=30, period=60.0)
        self.cost_tracker = cost_tracker or CostTracker()
        self.last_provider: str | None = None
        self.last_errors: list[str] = []

    @property
    def available(self) -> bool:
        """Есть ли хоть один провайдер с ключом."""
        return any(p.available for p in self.providers)

    def interpret(self, text: str) -> dict[str, Any] | None:
        """Разобрать текст; None → fallback на rule-based.

        Возвращает {"parsed": ..., "probability": ..., "provider": ...}.
        """
        self.last_errors = []
        for provider in self.providers:
            if not provider.available:
                continue
            if not self.rate_limiter.allow(provider.name):
                self.last_errors.append(f"{provider.name}: rate limit")
                logger.warning("rate limit reached for provider=%s", provider.name)
                continue
            started = time.perf_counter()
            try:
                result = provider.interpret(text)
            except LLMError as exc:
                self.last_errors.append(f"{provider.name}: {exc}")
                logger.warning("provider failed: %s", exc)
                continue
            except Exception as exc:  # защита цепочки от любых ошибок провайдера
                self.last_errors.append(f"{provider.name}: {exc}")
                logger.warning("provider crashed: %s", exc)
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.last_provider = provider.name
            usage = provider.last_usage
            if usage:
                self.cost_tracker.record(
                    provider=provider.name,
                    model=provider.model or "",
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
            logger.info(
                "llm interpret via %s in %.1fms probability=%s",
                provider.name,
                elapsed_ms,
                result.get("probability"),
            )
            return {
                "parsed": result,
                "probability": result.get("probability", 0.5),
                "provider": provider.name,
                "elapsed_ms": round(elapsed_ms, 1),
            }
        return None


# Глобальная цепочка для flow/API
llm_chain = LLMChain()
