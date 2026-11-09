"""
SymbioCore — интерпретация намерений (issue #12: 12 типов намерений)

Поддерживает: create, link, delete, query, evolve, transform, clone,
merge, tag, prioritize, schedule, analyze.

Каждый результат содержит confidence (issue #11), вычисленный
из силы keyword match и полноты полей.
"""

from __future__ import annotations

import re
from typing import Any

from core.symbio_core.confidence import keyword_score

SUPPORTED_ACTIONS = (
    "create",
    "link",
    "delete",
    "query",
    "evolve",
    "transform",
    "clone",
    "merge",
    "tag",
    "prioritize",
    "schedule",
    "analyze",
)

# --- Регулярные выражения; порядок проверок важен ---
_RE_PRIORITIZE_ON = re.compile(r"^изменить\s+приоритет\s+(.+?)\s+на\s+(\S+)$")
_RE_PRIORITIZE_PREP = re.compile(r"^приоритет\s+(.+?)\s+на\s+(\S+)$")
_RE_PRIORITIZE_UPDOWN = re.compile(r"^(?:повысить|понизить)\s+приоритет\s+(.+)$")
_RE_PRIORITIZE_DIRECT = re.compile(r"^приоритет\s+(.+?)\s+(\S+)$")
_RE_MERGE = re.compile(r"^объединить\s+(.+?)\s+и\s+(.+)$")
_RE_TAG_ADD = re.compile(r"^добавить\s+тег\s+(.+?)\s+(?:к|для)\s+(.+)$")
_RE_TAG_MARK = re.compile(r"^пометить\s+(.+?)\s+тегом\s+(.+)$")
_RE_TAG_FOR = re.compile(r"^тег\s+(.+?)\s+для\s+(.+)$")
_RE_TRANSFORM = re.compile(
    r"^(?:переименовать|изменить)\s+(?!приоритет\b)(.+?)\s+(?:в|на)\s+(.+)$"
)
_RE_CLONE = re.compile(r"^(?:клонировать|дублировать|скопировать)\s+(.+)$")
_RE_SCHEDULE = re.compile(r"^(?:запланировать|запланируй)\s+(.+?)\s+на\s+(.+)$")
_RE_ANALYZE = re.compile(r"^(?:проанализировать|анализировать|анализ)\s+(.+)$")
_RE_CREATE = re.compile(r"^(?:создать|создай)\s+(.+)$")
_RE_LINK = re.compile(r"^(?:связать|свяжи|соединить)\s+(.+?)\s+и\s+(.+)$")
_RE_DELETE = re.compile(r"^(?:удалить|удали)\s+(.+)$")
_RE_QUERY = re.compile(r"^(?:найти|показать|что\s+такое)\s+(.+)$")
_RE_EVOLVE = re.compile(r"^(?:эволюция|расширить|развить)\s+(.+)$")

PRIORITY_ALIASES = {
    "высокий": "high",
    "высокая": "high",
    "высокое": "high",
    "высок": "high",
    "high": "high",
    "max": "high",
    "максимум": "high",
    "средний": "medium",
    "средняя": "medium",
    "среднее": "medium",
    "medium": "medium",
    "normal": "medium",
    "обычный": "medium",
    "низкий": "low",
    "низкая": "low",
    "низкое": "low",
    "низк": "low",
    "low": "low",
    "min": "low",
    "минимум": "low",
}


def _result(action: str, **fields: Any) -> dict[str, Any]:
    """Собрать результат парсинга и оценить уверенность."""
    parsed: dict[str, Any] = {"action": action, **fields}
    parsed["confidence"] = keyword_score(parsed)
    return parsed


def _normalize_priority(value: str) -> str:
    return PRIORITY_ALIASES.get(value.lower().strip(), value.lower().strip())


def _normalize_analyze_target(value: str) -> str:
    value = value.strip()
    if value.startswith("граф"):
        return "graph"
    return value


def interpret_intent(text: str | None) -> dict[str, Any]:
    """
    Интерпретация текстового намерения.
    Возвращает структурированный словарь с действием, параметрами
    и confidence (0–1).
    """
    if not text or not text.strip():
        return {
            "action": "unknown",
            "raw": "",
            "error": "Пустое намерение",
            "confidence": 0.0,
        }

    text = text.strip().lower()

    # Приоритет: "изменить приоритет X на высокий", "приоритет X высокий",
    # "повысить приоритет X"
    m = _RE_PRIORITIZE_ON.match(text)
    if m:
        return _result(
            "prioritize",
            entity=m.group(1).strip(),
            priority=_normalize_priority(m.group(2)),
            raw=text,
        )
    m = _RE_PRIORITIZE_PREP.match(text)
    if m:
        return _result(
            "prioritize",
            entity=m.group(1).strip(),
            priority=_normalize_priority(m.group(2)),
            raw=text,
        )
    m = _RE_PRIORITIZE_UPDOWN.match(text)
    if m:
        priority = "high" if text.startswith("повысить") else "low"
        return _result("prioritize", entity=m.group(1).strip(), priority=priority, raw=text)
    m = _RE_PRIORITIZE_DIRECT.match(text)
    if m:
        return _result(
            "prioritize",
            entity=m.group(1).strip(),
            priority=_normalize_priority(m.group(2)),
            raw=text,
        )

    # Объединить: "объединить X и Y"
    m = _RE_MERGE.match(text)
    if m:
        return _result("merge", entities=[m.group(1).strip(), m.group(2).strip()], raw=text)

    # Теги: "добавить тег T к X", "пометить X тегом T", "тег T для X"
    m = _RE_TAG_ADD.match(text)
    if m:
        return _result("tag", entity=m.group(2).strip(), tag=m.group(1).strip(), raw=text)
    m = _RE_TAG_MARK.match(text)
    if m:
        return _result("tag", entity=m.group(1).strip(), tag=m.group(2).strip(), raw=text)
    m = _RE_TAG_FOR.match(text)
    if m:
        return _result("tag", entity=m.group(2).strip(), tag=m.group(1).strip(), raw=text)

    # Изменить/переименовать: "переименовать X в Y", "изменить X на Y"
    m = _RE_TRANSFORM.match(text)
    if m:
        return _result("transform", entity=m.group(1).strip(), to=m.group(2).strip(), raw=text)

    # Клонировать: "клонировать X", "дублировать X", "скопировать X"
    m = _RE_CLONE.match(text)
    if m:
        return _result("clone", entity=m.group(1).strip(), raw=text)

    # Запланировать: "запланировать X на <когда>"
    m = _RE_SCHEDULE.match(text)
    if m:
        return _result("schedule", task=m.group(1).strip(), when=m.group(2).strip(), raw=text)

    # Проанализировать: "проанализировать граф", "анализ X"
    m = _RE_ANALYZE.match(text)
    if m:
        return _result(
            "analyze",
            target=_normalize_analyze_target(m.group(1)),
            raw=text,
        )

    # Создать сущность
    m = _RE_CREATE.match(text)
    if m:
        entity = m.group(1).strip()
        return _result("create", entity=entity, raw=text)

    # Связать сущности
    m = _RE_LINK.match(text)
    if m:
        return _result(
            "link",
            entities=[m.group(1).strip(), m.group(2).strip()],
            raw=text,
        )

    # Удалить сущность
    m = _RE_DELETE.match(text)
    if m:
        return _result("delete", entity=m.group(1).strip(), raw=text)

    # Запрос информации
    m = _RE_QUERY.match(text)
    if m:
        return _result("query", entity=m.group(1).strip(), raw=text)

    # Эволюция / расширить
    m = _RE_EVOLVE.match(text)
    if m:
        return _result("evolve", entity=m.group(1).strip(), raw=text)

    return {"action": "unknown", "raw": text, "confidence": 0.0}
