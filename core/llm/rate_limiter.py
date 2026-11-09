"""Token bucket rate limiter (issue #9, задача 2).

Лимит по умолчанию — 60 запросов/мин на провайдера; при исчерпании
бакета поднимается RateLimitError (подкласс LLMError).
"""

from __future__ import annotations

import threading
import time

from core.llm.base import RateLimitError

# Лимиты запросов в минуту на провайдера (spec issue #9)
PROVIDER_REQUESTS_PER_MINUTE: dict[str, float] = {
    "openai": 60.0,
    "anthropic": 60.0,
    "google": 60.0,
}


class TokenBucketRateLimiter:
    """Потокобезопасный token bucket: capacity = requests_per_minute,

    refill = requests_per_minute / 60 токенов в секунду.
    """

    def __init__(
        self,
        requests_per_minute: float = 60.0,
        providers: dict[str, float] | None = None,
    ) -> None:
        self.providers = providers or PROVIDER_REQUESTS_PER_MINUTE
        self._limits = {k: float(v) for k, v in self.providers.items()}
        self._capacity: dict[str, float] = dict(self._limits)
        self._tokens: dict[str, float] = dict(self._limits)
        self._last_refill: dict[str, float] = {k: time.monotonic() for k in self._limits}
        self._default_rpm = float(requests_per_minute)
        self._lock = threading.Lock()

    def _refill(self, key: str, now: float) -> None:
        capacity = self._capacity.get(key, self._default_rpm)
        rate = self._limits.get(key, self._default_rpm) / 60.0
        elapsed = max(0.0, now - self._last_refill.get(key, now))
        self._tokens[key] = min(capacity, self._tokens.get(key, capacity) + elapsed * rate)
        self._last_refill[key] = now

    def check(self, provider: str) -> None:
        """Убрать 1 токен; при пустом бакете поднять RateLimitError."""
        with self._lock:
            now = time.monotonic()
            self._refill(provider, now)
            if self._tokens.get(provider, 0.0) < 1.0:
                limit = self._limits.get(provider, self._default_rpm)
                raise RateLimitError(
                    f"Достигнут лимит {limit:.0f} запросов/мин для провайдера {provider!r}"
                )
            self._tokens[provider] -= 1.0

    def try_acquire(self, provider: str) -> bool:
        """Неблокирующая версия check() — True, если токен получен."""
        try:
            self.check(provider)
        except RateLimitError:
            return False
        return True

    def remaining(self, provider: str) -> float:
        """Текущее число доступных токенов (для тестов/мониторинга)."""
        with self._lock:
            self._refill(provider, time.monotonic())
            return self._tokens.get(provider, 0.0)
