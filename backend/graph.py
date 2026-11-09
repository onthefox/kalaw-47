"""
Утилиты графа на основе БД (issues #13, #14):

  - build_tree: дерево из плоского списка сущностей
  - get_subtree: поддерево с ограничением глубины
  - get_descendants: все потомки с ограничением глубины
  - creates_cycle: проверка цикла для depends/blocks связей
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.models import Entity, Link
from core.symbio_hive.links import normalize_link_type


def build_tree(entity_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Собрать лес деревьев из плоского списка сущностей (to_dict-структуры).

    Сущности с parent_id, указывающим на отсутствующую/саму себя,
    считаются корнями.
    """
    nodes_by_id = {d["id"]: {**d, "children": []} for d in entity_dicts}
    roots: list[dict[str, Any]] = []
    for d in entity_dicts:
        node = nodes_by_id[d["id"]]
        parent_id = d.get("parent_id")
        parent_node = nodes_by_id.get(parent_id) if parent_id is not None else None
        if parent_id == d["id"] or parent_node is None or parent_node is node:
            roots.append(node)
        else:
            parent_node["children"].append(node)
    return roots


def get_subtree(db: Session, root: Entity, max_depth: int | None = None) -> dict[str, Any]:
    """Поддерево от корня с ограничением глубины (0 = только корень).

    Ограничение применяется на каждом уровне: узлы на границе глубины
    помечаются truncated=True, если у них есть непоказанные потомки.
    """
    def build(node: Entity, depth: int) -> dict[str, Any]:
        data = {**node.to_dict(), "children": []}
        if max_depth is not None and depth >= max_depth:
            data["truncated"] = bool(node.children)
            return data
        for child in node.children:
            data["children"].append(build(child, depth + 1))
        return data

    return build(root, 0)


def get_descendants(
    db: Session, entity: Entity, max_depth: int | None = None
) -> list[Entity]:
    """Потомки сущности (BFS) с ограничением глубины."""
    result: list[Entity] = []
    visited: set[int] = {entity.id}
    frontier: list[Entity] = [entity]
    depth = 0
    while frontier and (max_depth is None or depth < max_depth):
        next_frontier: list[Entity] = []
        for node in frontier:
            children = (
                db.query(Entity)
                .filter(Entity.parent_id == node.id, Entity.id != node.id)
                .all()
            )
            for child in children:
                if child.id in visited:
                    continue
                visited.add(child.id)
                result.append(child)
                next_frontier.append(child)
        frontier = next_frontier
        depth += 1
    return result


def creates_cycle(
    db: Session, source_id: int, target_id: int, link_type: str
) -> bool:
    """Создаст ли связь source→target цикл среди связей данного типа.

    Используется для depends и blocks (issue #14).
    """
    checked_type = normalize_link_type(link_type)
    visited: set[int] = set()
    frontier: list[int] = [target_id]
    while frontier:
        node = frontier.pop()
        if node == source_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        next_ids = (
            db.query(Link.target_id)
            .filter(Link.source_id == node, Link.type == checked_type)
            .all()
        )
        frontier.extend(row[0] for row in next_ids)
    return False
