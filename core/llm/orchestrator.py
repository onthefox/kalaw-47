"""Оркестратор LLM (issue #9, задача 3): fallback-цепочка + rule-based.

Порядок по умолчанию: OpenAI → Anthropic → Google. Если все провайдеры
упали (LLMError/таймаут) — делегируем rule-based парсеру
interpret_intent() из core.symbio_core.rules.
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm.base import (
    IntentResult,
    LLMError,
    LLMProvider,
)
from core.llm.config import LLMConfig, LLMConfigError, get_llm_config
from core.llm.cost_tracker import CostTracker
from core.llm.providers import default_providers
from core.llm.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class LLMOrchestrator:
    """Координирует провайдеров: ordered fallback → rule-based fallback."""

    def __init__(
        self,
        providers: list[LLMProvider] | None = None,
        config: LLMConfig | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        if config is None:
            try:
                config = get_llm_config()
            except LLMConfigError:
                # Нет ключей — оркестратор работает в rule-based режиме
                config = LLMConfig()
        self.config = config
        self.providers = providers if providers is not None else default_providers(config)
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.cost_tracker = cost_tracker or CostTracker()
        self.last_provider: str | None = None

    def has_available_providers(self) -> bool:
        """True, если хотя бы один провайдер настроен и его SDK доступен."""
        return any(p.is_available() for p in self.providers)

    def _available_providers(self) -> list[LLMProvider]:
        return [p for p in self.providers if p.is_available()]

    async def interpret_with_fallback(
        self,
        text: str,
        db: Any = None,
    ) -> IntentResult:
        """Interpret text через провайдеров по порядку; при полном фейле —
        rule-based interpret_intent(). Метаданные — в IntentResult.provider.
        """
        last_error: Exception | None = None
        for provider in self._available_providers():
            name = provider.get_name()
            try:
                self.rate_limiter.check(name)
            except LLMError as exc:
                logger.warning("Rate limiter: %s — пропускаю %s", exc, name)
                last_error = exc
                continue
            try:
                result = await provider.interpret(text)
            except LLMError as exc:
                logger.warning("Провайдер %s упал: %s", name, exc)
                self.cost_tracker.record(
                    provider=name, action="unknown", input_tokens=0,
                    output_tokens=0, success=False, db=db,
                )
                last_error = exc
                continue
            except TimeoutError as exc:
                logger.warning("Провайдер %s упал по таймауту: %s", name, exc)
                self.cost_tracker.record(
                    provider=name, action="unknown", input_tokens=0,
                    output_tokens=0, success=False, db=db,
                )
                last_error = exc
                continue
            self.last_provider = name
            self.cost_tracker.record(
                provider=name,
                action=result.action,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                success=True,
                db=db,
            )
            return result

        rule_result = self._rule_based_fallback(text)
        self.last_provider = rule_result.provider
        self.cost_tracker.record(
            provider=rule_result.provider or "rule-based",
            action=rule_result.action,
            input_tokens=0,
            output_tokens=0,
            success=True,
            db=db,
        )
        if last_error is not None:
            logger.info("Все LLM-провайдеры недоступны (%s) — rule-based fallback", last_error)
        return rule_result

    def _rule_based_fallback(self, text: str) -> IntentResult:
        """rule-based парсер из core.symbio_core.rules → IntentResult."""
        from core.symbio_core.rules import interpret_intent

        parsed = interpret_intent(text)
        entities = parsed.get("entities") or []
        if not entities and parsed.get("entity"):
            entities = [parsed["entity"]]
        return IntentResult(
            action=str(parsed.get("action", "unknown")),
            entities=[str(e) for e in entities],
            confidence=float(parsed.get("confidence", 0.0)),
            raw_response=text,
            input_tokens=0,
            output_tokens=0,
            provider="rule-based",
            data=parsed,
        )
