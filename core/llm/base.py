"""
Базовый слой LLM (issue #9, задача 1): интерфейсы, результат, ошибки.

Каждый провайдер превращает текст намерения в структурированный
IntentResult. Провайдер без API-ключа или без установленного SDK
считается недоступным и пропускается оркестратором.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

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
    """Базовая ошибка обращения к LLM-провайдеру."""


class RateLimitError(LLMError):
    """Исчерпан лимит запросов к провайдеру."""


class AuthenticationError(LLMError):
    """Неверный/отсутствующий API-ключ."""


class LLMTimeoutError(LLMError):
    """Таймаут запроса к провайдеру."""


@dataclass
class IntentResult:
    """Результат интерпретации текста одним провайдером (или rule-based)."""

    action: str = "unknown"
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Абстрактный async LLM-провайдер."""

    @abstractmethod
    async def interpret(self, text: str) -> IntentResult:
        """Разобрать намерение и вернуть IntentResult."""

    @abstractmethod
    def get_name(self) -> str:
        """Имя провайдера (openai / anthropic / google)."""

    @abstractmethod
    def is_available(self) -> bool:
        """True, если провайдер настроен (ключ) и SDK доступен."""


def parse_intent_json(raw: str) -> dict[str, Any]:
    """Безопасно разобрать JSON-ответ модели → dict с action и probability."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Невалидный JSON от модели: {exc}") from exc
    if not isinstance(data, dict) or "action" not in data:
        raise LLMError(f"Ответ без action: {raw[:200]}")
    probability = data.pop("probability", 0.5)
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        probability = 0.5
    data = {k: v for k, v in data.items() if v is not None}
    data["probability"] = min(max(probability, 0.0), 1.0)
    return data


def result_from_parsed(
    parsed: dict[str, Any],
    provider_name: str,
    raw: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> IntentResult:
    """Собрать IntentResult из разобранного JSON-ответа модели."""
    entities = parsed.get("entities") or []
    if not entities and parsed.get("entity"):
        entities = [parsed["entity"]]
    return IntentResult(
        action=str(parsed.get("action", "unknown")),
        entities=[str(e) for e in entities],
        confidence=float(parsed.get("probability", 0.5)),
        raw_response=raw,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        provider=provider_name,
        data=parsed,
    )
