"""Типизированные связи (issue #14): enum типов и вспомогательные функции."""

from __future__ import annotations

from enum import Enum

from typing import Any


class LinkType(str, Enum):
    """Пять стандартных типов связей между сущностями."""

    CONTAINS = "contains"
    DEPENDS = "depends"
    RELATES = "relates"
    BLOCKS = "blocks"
    TRIGGERS = "triggers"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(t.value for t in cls)


def is_cycle_checked(link_type: str | LinkType) -> bool:
    """Для каких типов связей нужна проверка циклов (depends, blocks)."""
    value = normalize_link_type(link_type)
    return value in (LinkType.DEPENDS.value, LinkType.BLOCKS.value)


def normalize_link_type(link_type: Any) -> str:
    """Привести значение к валидному типу связи (по умолчанию relates)."""
    if link_type is None:
        return LinkType.RELATES.value
    value = str(getattr(link_type, "value", link_type)).lower().strip()
    try:
        return LinkType(value).value
    except ValueError:
        return LinkType.RELATES.value
