"""Cost tracking LLM (issue #9, задача 3).

Стоимость на 1K токенов по провайдерам (spec issue #9):
GPT-4: $0.03/1K input, $0.06/1K output. Расчёт и persist в БД
(LLMUsage из backend.models).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# $ за 1000 токенов (input, output)
COST_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4": (0.03, 0.06),
    "openai": (0.03, 0.06),
    "claude": (0.003, 0.015),
    "anthropic": (0.003, 0.015),
    "gemini": (0.000125, 0.000375),
    "google": (0.000125, 0.000375),
    "rule-based": (0.0, 0.0),
}


def calculate_estimated_cost(
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Оценить стоимость запроса по тарифу провайдера ($ за 1K токенов)."""
    in_rate, out_rate = COST_PER_1K.get(provider, COST_PER_1K["openai"])
    return round((input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate, 6)


class CostTracker:
    """Учёт стоимости: расчёт + persist записей LLMUsage в БД."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        provider: str,
        action: str,
        input_tokens: int,
        output_tokens: int,
        success: bool = True,
        db: Any = None,
    ) -> float:
        """Рассчитать стоимость, сохранить в память и (при db) в LLMUsage."""
        estimated_cost = calculate_estimated_cost(provider, input_tokens, output_tokens)
        record = {
            "provider": provider,
            "action": action,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "success": success,
            "timestamp": datetime.now(UTC),
        }
        self.records.append(record)
        if db is not None:
            self.persist(
                db,
                provider=provider,
                action=action,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
                success=success,
            )
        return estimated_cost

    def persist(
        self,
        db: Any,
        provider: str,
        action: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
        success: bool = True,
    ) -> None:
        """Записать строку LLMUsage в БД; ошибки БД не роняют основной поток."""
        try:
            from backend.models import LLMUsage

            db.add(
                LLMUsage(
                    provider=provider,
                    action=action,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost=estimated_cost,
                    success=success,
                )
            )
            db.commit()
        except Exception:  # noqa: BLE001 - учёт стоимости не должен ломать запрос
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    def usage(self) -> dict[str, Any]:
        """Агрегация по памяти (для тестов): суммы токенов/затрат по провайдерам."""
        agg: dict[str, dict[str, Any]] = {}
        for rec in self.records:
            entry = agg.setdefault(
                rec["provider"],
                {
                    "provider": rec["provider"],
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost": 0.0,
                    "success": 0,
                    "failed": 0,
                },
            )
            entry["requests"] += 1
            entry["input_tokens"] += rec["input_tokens"]
            entry["output_tokens"] += rec["output_tokens"]
            entry["estimated_cost"] = round(entry["estimated_cost"] + rec["estimated_cost"], 6)
            entry["success" if rec["success"] else "failed"] += 1
        return {
            "total_requests": len(self.records),
            "providers": sorted(agg.values(), key=lambda e: e["provider"]),
        }

    def reset(self) -> None:
        self.records.clear()
