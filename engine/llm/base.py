"""
Базовый интерфейс LLM-провайдера (issue #9).

Каждый провайдер превращает текст намерения в структурированный JSON
с вероятностью (confidence). Провайдер без API-ключа считается
недоступным и пропускается цепочкой.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("symbio.llm")

SYSTEM_PROMPT = (
    "Ты — парсер намерений системы SymbioSystem. Верни ТОЛЬКО валидный JSON "
    "без markdown с полями:\n"
    '{"action": "<create|link|delete|query|evolve|transform|clone|merge|tag|'
    'prioritize|schedule|analyze>",\n'
    ' "entity": "<имя сущности или null>", "entities": ["...", "..."] | null,\n'
    ' "to": "<новое значение или null>", "tag": "<тег или null>",\n'
    ' "priority": "<high|medium|low или null>", "task": "<... или null>",\n'
    ' "when": "<... или null>", "target": "<... или null>",\n'
    ' "probability": <0..1 — уверенность в разборе>}\n'
    "Заполняй только релевантные поля выбранного действия."
)


class LLMError(Exception):
    """Ошибка обращения к LLM-провайдеру."""


class LLMProvider(ABC):
    """Абстрактный LLM-провайдер."""

    name = "base"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.last_usage: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        """Провайдер доступен, если есть API-ключ."""
        return bool(self.api_key)

    @abstractmethod
    def interpret(self, text: str) -> dict[str, Any]:
        """Разобрать намерение. Возвращает dict с action, probability, provider."""

    def parse_json_response(self, raw: str) -> dict[str, Any]:
        """Безопасно разобрать JSON-ответ модели."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Невалидный JSON от {self.name}: {exc}") from exc
        if not isinstance(data, dict) or "action" not in data:
            raise LLMError(f"Ответ {self.name} без action: {raw[:200]}")
        probability = data.pop("probability", 0.5)
        try:
            probability = float(probability)
        except (TypeError, ValueError):
            probability = 0.5
        data = {k: v for k, v in data.items() if v is not None}
        data["probability"] = min(max(probability, 0.0), 1.0)
        data["provider"] = self.name
        return data
