"""
SymbioHive — graph-абстракция в памяти (для прототипов и тестов).

Иерархия (issue #13): parent_id, дети, поддеревья, ограничение глубины.
Типизированные связи (issue #14): contains/depends/relates/blocks/triggers,
проверка циклов для depends и blocks.

Точки расширения:
  - заменить списки на PostgreSQL/Neo4j (backend/models.py)
  - добавить мета-данные (тэги, веса, временные метки)
"""

from __future__ import annotations

from collections import deque
from typing import Any

from core.symbio_hive.links import (
    LinkType,
    is_cycle_checked,
    normalize_link_type,
)

entities: list[dict[str, Any]] = []
links: list[dict[str, Any]] = []
_next_entity_id = 1
_next_link_id = 1


def _find_entity(name: str) -> dict[str, Any] | None:
    return next((e for e in entities if e["name"].lower() == name.lower()), None)


def create_entity(
    name: str, meta: dict[str, Any] | None = None, parent_id: int | None = None
) -> dict[str, Any]:
    """Создать сущность (опционально с родителем). Если имя существует — вернуть существующую."""
    global _next_entity_id
    existing = _find_entity(name)
    if existing:
        return existing
    if parent_id is not None and not any(e["id"] == parent_id for e in entities):
        raise ValueError(f"Родитель с id={parent_id} не найден")
    e = {"id": _next_entity_id, "name": name, "meta": dict(meta or {}), "parent_id": parent_id}
    entities.append(e)
    _next_entity_id += 1
    return e


def get_entity(name: str) -> dict[str, Any] | None:
    return _find_entity(name)


def get_children(name: str) -> list[dict[str, Any]]:
    """Прямые дети сущности."""
    parent = _find_entity(name)
    if not parent:
        return []
    return [e for e in entities if e.get("parent_id") == parent["id"]]


def has_children(name: str) -> bool:
    return bool(get_children(name))


def get_subtree(name: str, max_depth: int | None = None) -> dict[str, Any] | None:
    """Поддерево с корнем в указанной сущности, ограниченное по глубине."""
    root = _find_entity(name)
    if not root:
        return None

    def build(node: dict[str, Any], depth: int) -> dict[str, Any]:
        result = {**node, "children": []}
        if max_depth is not None and depth >= max_depth:
            return result
        for child in entities:
            if child.get("parent_id") == node["id"]:
                result["children"].append(build(child, depth + 1))
        return result

    return build(root, 0)


def get_entities() -> list[dict[str, Any]]:
    """Вернуть копию списка сущностей."""
    return [dict(e) for e in entities]


def set_parent(child_name: str, parent_name: str | None) -> bool:
    """Назначить родителя. Защита от циклов в иерархии."""
    child = _find_entity(child_name)
    if not child:
        return False
    if parent_name is None:
        child["parent_id"] = None
        return True
    parent = _find_entity(parent_name)
    if not parent:
        return False
    if parent["id"] == child["id"]:
        return False
    # Подняться по цепочке родителей: если встретим ребёнка — цикл
    walker = parent
    while walker is not None:
        if walker["id"] == child["id"]:
            return False
        walker = next(
            (e for e in entities if e["id"] == walker.get("parent_id")), None
        )
    child["parent_id"] = parent["id"]
    return True


def link_entities(
    source_name: str,
    target_name: str,
    link_type: str | LinkType = LinkType.RELATES,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Создать типизированную связь между двумя сущностями по именам.

    Для depends/blocks проверяет циклы и возвращает None при их обнаружении.
    """
    global _next_link_id
    src = _find_entity(source_name)
    tgt = _find_entity(target_name)
    if not src or not tgt:
        return None
    link_type = normalize_link_type(link_type)
    if is_cycle_checked(link_type) and creates_cycle(src["id"], tgt["id"], link_type):
        return None
    existing = next(
        (
            l
            for l in links
            if l["source"] == src["id"]
            and l["target"] == tgt["id"]
            and l.get("type") == link_type
        ),
        None,
    )
    if existing:
        return existing
    lnk = {
        "id": _next_link_id,
        "source": src["id"],
        "target": tgt["id"],
        "type": link_type,
        "meta": dict(meta or {}),
    }
    links.append(lnk)
    _next_link_id += 1
    return lnk


def get_links(link_type: str | LinkType | None = None) -> list[dict[str, Any]]:
    """Вернуть копию списка связей, опционально отфильтрованную по типу."""
    if link_type is None:
        return [dict(l) for l in links]
    wanted = normalize_link_type(link_type)
    return [dict(l) for l in links if l.get("type") == wanted]


def link_type_distribution() -> dict[str, int]:
    """Количество связей по типам."""
    result: dict[str, int] = {t.value: 0 for t in LinkType}
    for l in links:
        result[l.get("type", LinkType.RELATES.value)] = (
            result.get(l.get("type", LinkType.RELATES.value), 0) + 1
        )
    return result


def creates_cycle(source_id: int, target_id: int, link_type: str | LinkType) -> bool:
    """Проверка: создаст ли связь source→target цикл среди связей данного типа."""
    checked_type = normalize_link_type(link_type)
    adjacency: dict[int, list[int]] = {}
    for l in links:
        if l.get("type") == checked_type:
            adjacency.setdefault(l["source"], []).append(l["target"])
    visited: set[int] = set()
    queue: deque[int] = deque([target_id])
    while queue:
        node = queue.popleft()
        if node == source_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adjacency.get(node, []))
    return False


def delete_entity(name: str) -> bool:
    """Удалить сущность и все её связи; дети теряют родителя."""
    global _next_entity_id
    idx = next(
        (i for i, e in enumerate(entities) if e["name"].lower() == name.lower()), None
    )
    if idx is None:
        return False
    entity_id = entities[idx]["id"]
    for e in entities:
        if e.get("parent_id") == entity_id:
            e["parent_id"] = None
    entities.pop(idx)
    links[:] = [l for l in links if l["source"] != entity_id and l["target"] != entity_id]
    return True


def reset() -> None:
    """Очистить хранилище (для тестов)."""
    global _next_entity_id, _next_link_id
    entities.clear()
    links.clear()
    _next_entity_id = 1
    _next_link_id = 1


def stats() -> dict[str, int]:
    """Статистика экосистемы."""
    return {"entities": len(entities), "links": len(links)}
