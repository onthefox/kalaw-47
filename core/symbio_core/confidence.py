"""
Confidence scoring для интерпретаций намерений (issue #11).

Правила:
  - Базовая оценка строится на keyword match (какой шаблон сработал)
    и полноте обязательных полей распознанной структуры.
  - Если LLM вернул свою вероятность — итог смешивается из двух оценок.
  - Маршрутизация: >0.9 → auto, 0.7–0.9 → review, <0.7 → clarification.
  - Feedback loop: пользователь подтверждает/отклоняет интерпретации,
    корректировки применяются к последующим оценкам и логируются.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("symbio.confidence")

AUTO_THRESHOLD = 0.9
REVIEW_THRESHOLD = 0.7

# Базовая уверенность по типу действия (сила keyword match шаблона)
PATTERN_CONFIDENCE: dict[str, float] = {
    "create": 0.90,
    "link": 0.90,
    "delete": 0.90,
    "query": 0.85,
    "evolve": 0.80,
    "transform": 0.85,
    "clone": 0.90,
    "merge": 0.90,
    "tag": 0.85,
    "prioritize": 0.85,
    "schedule": 0.85,
    "analyze": 0.80,
    "unknown": 0.0,
}

# Обязательные поля: неполный распознанный шаблон снижает уверенность
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "create": ("entity",),
    "link": ("entities",),
    "delete": ("entity",),
    "query": ("entity",),
    "evolve": ("entity",),
    "transform": ("entity", "to"),
    "clone": ("entity",),
    "merge": ("entities",),
    "tag": ("entity", "tag"),
    "prioritize": ("entity", "priority"),
    "schedule": ("task", "when"),
    "analyze": ("target",),
}


class FeedbackStore:
    """Feedback loop: пользователь подтверждает/отклоняет интерпретации.

    Подтверждённые действия слегка повышают последующие оценки,
    отклонённые — понижают. Каждое событие логируется.
    """

    def __init__(self, max_log_entries: int = 1000) -> None:
        self._lock = threading.Lock()
        self._accepted: dict[str, int] = {}
        self._rejected: dict[str, int] = {}
        self._log: list[dict[str, Any]] = []
        self._max_log_entries = max_log_entries

    def record(
        self,
        action: str,
        accepted: bool,
        confidence: float | None = None,
        intent_text: str | None = None,
    ) -> dict[str, Any]:
        """Записать обратную связь по действию. Возвращает запись."""
        entry = {
            "ts": time.time(),
            "action": action,
            "accepted": bool(accepted),
            "confidence": confidence,
        }
        with self._lock:
            if accepted:
                self._accepted[action] = self._accepted.get(action, 0) + 1
            else:
                self._rejected[action] = self._rejected.get(action, 0) + 1
            self._log.append(entry)
            if len(self._log) > self._max_log_entries:
                self._log = self._log[-self._max_log_entries :]
        logger.info(
            "feedback: action=%s accepted=%s confidence=%s",
            action,
            accepted,
            confidence,
        )
        return entry

    def adjustment(self, action: str) -> float:
        """Поправка к базовой оценке на основе накопленной статистики."""
        with self._lock:
            accepted = self._accepted.get(action, 0)
            rejected = self._rejected.get(action, 0)
        bonus = min(0.05, 0.01 * accepted)
        penalty = min(0.30, 0.05 * rejected)
        return round(bonus - penalty, 4)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "accepted": dict(self._accepted),
                "rejected": dict(self._rejected),
                "total": len(self._log),
            }

    def reset(self) -> None:
        with self._lock:
            self._accepted.clear()
            self._rejected.clear()
            self._log.clear()


# Глобальный стор обратной связи (используется flow и API)
feedback_store = FeedbackStore()


def keyword_score(parsed: dict[str, Any]) -> float:
    """Оценка уверенности на основе keyword match и полноты полей."""
    action = parsed.get("action", "unknown")
    if action == "unknown" or not action:
        return 0.0
    base = PATTERN_CONFIDENCE.get(action, 0.5)
    fields = REQUIRED_FIELDS.get(action, ())
    if fields:
        filled = sum(1 for field in fields if parsed.get(field))
        base *= 0.5 + 0.5 * filled / len(fields)
    base += feedback_store.adjustment(action)
    return round(min(max(base, 0.0), 1.0), 3)


def blend(keyword: float, llm_probability: float | None, llm_weight: float = 0.4) -> float:
    """Смешать keyword-оценку и вероятность от LLM."""
    if llm_probability is None:
        return round(keyword, 3)
    keyword = min(max(keyword, 0.0), 1.0)
    llm_probability = min(max(llm_probability, 0.0), 1.0)
    return round((1 - llm_weight) * keyword + llm_weight * llm_probability, 3)


def route(confidence: float) -> str:
    """Маршрутизация по порогам: >0.9 auto, 0.7–0.9 review, <0.7 clarification."""
    if confidence > AUTO_THRESHOLD:
        return "auto"
    if confidence >= REVIEW_THRESHOLD:
        return "review"
    return "clarification"


def score(parsed: dict[str, Any], llm_probability: float | None = None) -> dict[str, Any]:
    """Полная оценка: уверенность + маршрут. Логирует низкую уверенность."""
    keyword = parsed.get("confidence")
    if not isinstance(keyword, (int, float)):
        keyword = keyword_score(parsed)
    confidence = blend(float(keyword), llm_probability)
    parsed["confidence"] = confidence
    parsed["route"] = route(confidence)
    if confidence < REVIEW_THRESHOLD:
        logger.info(
            "low confidence: action=%s confidence=%s route=clarification",
            parsed.get("action"),
            confidence,
        )
    return parsed
