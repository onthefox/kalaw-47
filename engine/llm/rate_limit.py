"""
Rate limiting и учёт стоимости LLM-запросов (issue #9).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

# Цены $ за 1M токенов (input, output) — приблизительные дефолты, модель → цена
PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-haiku-latest": (0.80, 4.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}
DEFAULT_PRICING = (0.50, 1.50)


class RateLimiter:
    """Скользящее окно на ключ (например, имя провайдера).

    max_calls за period секунд; при превышении allow() возвращает False.
    """

    def __init__(self, max_calls: int = 30, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.period:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return False
            hits.append(now)
            return True

    def remaining(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.period:
                hits.popleft()
            return max(0, self.max_calls - len(hits))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class CostTracker:
    """Учёт токенов и стоимости по провайдерам/моделям."""

    def __init__(self, pricing: dict[str, tuple[float, float]] | None = None) -> None:
        self.pricing = pricing or PRICING_PER_MILLION
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def _rates(self, model: str) -> tuple[float, float]:
        return self.pricing.get(model, DEFAULT_PRICING)

    def record(
        self,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict[str, Any]:
        """Записать использование; возвращает стоимость записи в $."""
        in_rate, out_rate = self._rates(model)
        cost = (
            prompt_tokens / 1_000_000 * in_rate
            + completion_tokens / 1_000_000 * out_rate
        )
        entry = {
            "ts": time.time(),
            "provider": provider,
            "model": model,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "cost_usd": round(cost, 8),
        }
        with self._lock:
            self._records.append(entry)
        return entry

    def usage(self) -> dict[str, Any]:
        """Сводка: токены и $ по провайдерам, итог."""
        with self._lock:
            records = list(self._records)
        by_provider: dict[str, dict[str, float]] = {}
        total_cost = 0.0
        total_in = 0
        total_out = 0
        for r in records:
            agg = by_provider.setdefault(
                r["provider"], {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
            )
            agg["prompt_tokens"] += r["prompt_tokens"]
            agg["completion_tokens"] += r["completion_tokens"]
            agg["cost_usd"] = round(agg["cost_usd"] + r["cost_usd"], 8)
            total_cost += r["cost_usd"]
            total_in += r["prompt_tokens"]
            total_out += r["completion_tokens"]
        return {
            "total_cost_usd": round(total_cost, 8),
            "total_prompt_tokens": total_in,
            "total_completion_tokens": total_out,
            "total_requests": len(records),
            "by_provider": by_provider,
        }

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
