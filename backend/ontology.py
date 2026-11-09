"""
Экспорт/импорт онтологии (issue #15).

Форматы: JSON (полный payload) и GraphML (XML).
Импорт: валидация структуры, стратегии replace (полная замена)
и merge (добавление недостающего по имени).
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

from sqlalchemy.orm import Session

from backend.models import Entity, Link
from core.symbio_hive.links import LinkType, normalize_link_type
from engine.observer import publish_change

logger = logging.getLogger("symbio.ontology")

GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"

# Разрешённые поля payload
ENTITY_FIELDS = {"id", "name", "meta", "parent_id"}
LINK_FIELDS = {"id", "source_id", "target_id", "type", "meta"}


# --- Экспорт ---


def export_json(db: Session) -> dict[str, Any]:
    """Полный экспорт онтологии в JSON-структуру."""
    entities = [e.to_dict() for e in db.query(Entity).all()]
    links = [l.to_dict() for l in db.query(Link).all()]
    return {
        "version": 1,
        "exported_at": time.time(),
        "entities": entities,
        "links": links,
    }


def export_graphml(db: Session) -> str:
    """Экспорт онтологии в GraphML (XML)."""
    entities = db.query(Entity).all()
    links = db.query(Link).all()
    ET.register_namespace("", GRAPHML_NS)
    root = ET.Element(f"{{{GRAPHML_NS}}}graphml")
    ET.SubElement(
        root,
        f"{{{GRAPHML_NS}}}key",
        {"id": "d_name", "for": "node", "attr.name": "name", "attr.type": "string"},
    )
    ET.SubElement(
        root,
        f"{{{GRAPHML_NS}}}key",
        {"id": "d_meta", "for": "node", "attr.name": "meta", "attr.type": "string"},
    )
    ET.SubElement(
        root,
        f"{{{GRAPHML_NS}}}key",
        {"id": "d_type", "for": "edge", "attr.name": "type", "attr.type": "string"},
    )
    graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph", {"edgedefault": "directed"})
    for e in entities:
        node = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {"id": f"n{e.id}"})
        ET.SubElement(node, f"{{{GRAPHML_NS}}}data", {"key": "d_name"}).text = e.name
        ET.SubElement(node, f"{{{GRAPHML_NS}}}data", {"key": "d_meta"}).text = e.meta or "{}"
    for l in links:
        edge = ET.SubElement(
            graph,
            f"{{{GRAPHML_NS}}}edge",
            {"id": f"e{l.id}", "source": f"n{l.source_id}", "target": f"n{l.target_id}"},
        )
        ET.SubElement(edge, f"{{{GRAPHML_NS}}}data", {"key": "d_type"}).text = l.type
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# --- Валидация ---


def validate_payload(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Валидация JSON-payload онтологии.

    Возвращает (очищенные данные, список ошибок).
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return {"entities": [], "links": []}, ["payload должен быть объектом"]

    raw_entities = data.get("entities")
    raw_links = data.get("links", [])
    if not isinstance(raw_entities, list):
        return {"entities": [], "links": []}, ["entities должен быть списком"]
    if not isinstance(raw_links, list):
        errors.append("links должен быть списком")
        raw_links = []

    clean_entities: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for i, raw in enumerate(raw_entities):
        if not isinstance(raw, dict):
            errors.append(f"entities[{i}]: должен быть объектом")
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            errors.append(f"entities[{i}]: отсутствует name")
            continue
        if name.lower() in seen_names:
            errors.append(f"entities[{i}]: дубликат имени '{name}'")
            continue
        entity_id = raw.get("id")
        if entity_id is not None:
            try:
                entity_id = int(entity_id)
                if entity_id <= 0:
                    raise ValueError
                if entity_id in seen_ids:
                    errors.append(f"entities[{i}]: дубликат id {entity_id}")
                    continue
            except (TypeError, ValueError):
                errors.append(f"entities[{i}]: некорректный id {raw.get('id')!r}")
                continue
            seen_ids.add(entity_id)
        seen_names.add(name.lower())
        meta = raw.get("meta", "{}")
        if not isinstance(meta, str):
            meta = json.dumps(meta, ensure_ascii=False) if meta is not None else "{}"
        parent_id = raw.get("parent_id")
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                parent_id = None
        clean_entities.append(
            {"id": entity_id, "name": name, "meta": meta, "parent_id": parent_id}
        )

    valid_ids = {e["id"] for e in clean_entities if e["id"] is not None}
    valid_names = {e["name"].lower() for e in clean_entities}
    clean_links: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_links):
        if not isinstance(raw, dict):
            errors.append(f"links[{i}]: должен быть объектом")
            continue
        src, tgt = raw.get("source_id"), raw.get("target_id")
        try:
            src, tgt = int(src), int(tgt)
        except (TypeError, ValueError):
            errors.append(f"links[{i}]: некорректные source_id/target_id")
            continue
        if src not in valid_ids or tgt not in valid_ids:
            errors.append(
                f"links[{i}]: source/target ({src}→{tgt}) не найдены в entities"
            )
            continue
        link_type = normalize_link_type(raw.get("type"))
        meta = raw.get("meta", "{}")
        if not isinstance(meta, str):
            meta = json.dumps(meta, ensure_ascii=False) if meta is not None else "{}"
        clean_links.append(
            {"id": raw.get("id"), "source_id": src, "target_id": tgt, "type": link_type, "meta": meta}
        )

    return {"entities": clean_entities, "links": clean_links}, errors


# --- Импорт ---


def parse_import_payload(payload: Any) -> dict[str, Any]:
    """Распознать формат импорта: JSON-payload или GraphML-XML.

    Поддерживаются: dict с entities, dict {"format": "graphml", "data": "..."},
    или строка XML/JSON.
    """
    if isinstance(payload, dict):
        if "entities" in payload:
            return payload
        if "data" in payload:
            inner = payload["data"]
            if isinstance(inner, str):
                return parse_import_payload(inner)
            if isinstance(inner, dict):
                return inner
        raise ValueError("payload должен содержать 'entities' или 'data'")
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("<"):
            return _graphml_to_payload(text)
        return json.loads(text)
    raise ValueError("Неподдерживаемый формат импорта")


def _graphml_to_payload(xml_text: str) -> dict[str, Any]:
    """Преобразовать GraphML в JSON-payload."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Невалидный GraphML: {exc}") from exc
    graph = root.find(f"{{{GRAPHML_NS}}}graph")
    if graph is None:
        raise ValueError("GraphML без <graph>")
    entities: list[dict[str, Any]] = []
    id_map: dict[str, int] = {}
    for node in graph.findall(f"{{{GRAPHML_NS}}}node"):
        node_id = node.get("id", "")
        name = node_id
        meta = "{}"
        for data in node.findall(f"{{{GRAPHML_NS}}}data"):
            key = data.get("key")
            if key == "d_name" and data.text:
                name = data.text
            elif key == "d_meta" and data.text:
                meta = data.text
        numeric = "".join(ch for ch in node_id if ch.isdigit())
        new_id = int(numeric) if numeric else len(entities) + 1
        id_map[node_id] = new_id
        entities.append({"id": new_id, "name": name, "meta": meta})
    links: list[dict[str, Any]] = []
    for edge in graph.findall(f"{{{GRAPHML_NS}}}edge"):
        src, tgt = edge.get("source"), edge.get("target")
        if src not in id_map or tgt not in id_map:
            continue
        link_type = "relates"
        for data in edge.findall(f"{{{GRAPHML_NS}}}data"):
            if data.get("key") == "d_type" and data.text:
                link_type = data.text
        links.append(
            {
                "source_id": id_map[src],
                "target_id": id_map[tgt],
                "type": normalize_link_type(link_type),
            }
        )
    return {"entities": entities, "links": links}


def apply_import(db: Session, data: dict[str, Any], mode: str = "merge") -> dict[str, Any]:
    """Применить валидированный payload. mode: replace|merge.

    replace — полная замена графа (с сохранением исходных id).
    merge — добавление недостающих сущностей (по имени) и связей.
    """
    mode = (mode or "merge").lower()
    if mode not in ("replace", "merge"):
        raise ValueError(f"Неизвестная стратегия: {mode}. Доступно: replace, merge")

    created_entities = 0
    skipped_entities = 0
    created_links = 0
    skipped_links = 0

    if mode == "replace":
        db.query(Link).delete()
        db.query(Entity).delete()
        db.commit()

    existing_by_name = {e.name.lower(): e for e in db.query(Entity).all()}
    id_map: dict[int, int] = {}

    for raw in data.get("entities", []):
        name = raw["name"]
        existing = existing_by_name.get(name.lower())
        if existing:
            id_map[raw["id"] or existing.id] = existing.id
            if raw.get("id") is not None:
                id_map[raw["id"]] = existing.id
            skipped_entities += 1
            continue
        if mode == "replace" and raw.get("id") is not None:
            entity = Entity(
                id=raw["id"],
                name=name,
                meta=raw.get("meta", "{}"),
                parent_id=None,  # родители проставим вторым проходом
            )
        else:
            entity = Entity(name=name, meta=raw.get("meta", "{}"), parent_id=None)
        db.add(entity)
        db.flush()
        if raw.get("id") is not None:
            id_map[raw["id"]] = entity.id
        id_map[raw["id"] or entity.id] = entity.id
        existing_by_name[name.lower()] = entity
        created_entities += 1

    db.commit()

    # Второй проход: parent_id (родитель может появиться позже в payload)
    for raw in data.get("entities", []):
        if raw.get("parent_id") is None:
            continue
        target = None
        if raw.get("id") is not None:
            target = existing_by_name.get(raw["name"].lower())
        if target and raw["parent_id"] in id_map:
            parent_id = id_map[raw["parent_id"]]
            if parent_id != target.id:
                target.parent_id = parent_id
    db.commit()

    existing_links = {
        (l.source_id, l.target_id, l.type) for l in db.query(Link).all()
    }
    for raw in data.get("links", []):
        src = id_map.get(raw["source_id"], raw["source_id"])
        tgt = id_map.get(raw["target_id"], raw["target_id"])
        key = (src, tgt, raw["type"])
        if key in existing_links or src == tgt:
            skipped_links += 1
            continue
        db.add(
            Link(
                source_id=src,
                target_id=tgt,
                type=raw["type"],
                meta=raw.get("meta", "{}"),
            )
        )
        existing_links.add(key)
        created_links += 1
    db.commit()

    stats = {
        "mode": mode,
        "entities_created": created_entities,
        "entities_skipped": skipped_entities,
        "links_created": created_links,
        "links_skipped": skipped_links,
    }
    publish_change("ontology.imported", data=stats)
    return stats
