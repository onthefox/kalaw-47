"""
Autogen — выполнение намерений через БД (PostgreSQL через SQLAlchemy).

Поддерживает все 12 типов действий SymbioCore: create, link, delete, query,
evolve, transform, clone, merge, tag, prioritize, schedule, analyze.
Каждая мутация публикует событие в шину наблюдателя (issue #16).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.models import Entity, Link
from core.symbio_hive.links import normalize_link_type
from engine.observer import publish_change

logger = logging.getLogger("symbio.autogen")


def _load_meta(entity: Entity) -> dict[str, Any]:
    try:
        meta = json.loads(entity.meta or "{}")
    except json.JSONDecodeError:
        meta = {}
    return meta if isinstance(meta, dict) else {}


def _save_meta(entity: Entity, meta: dict[str, Any]) -> None:
    entity.meta = json.dumps(meta, ensure_ascii=False)


def _analyze_graph(db) -> dict[str, Any]:
    """Анализ графа: количество сущностей/связей, топ по связям, распределение типов."""
    entities = db.query(Entity).all()
    links = db.query(Link).all()
    id_to_name = {e.id: e.name for e in entities}
    degree: dict[int, int] = {}
    type_dist: dict[str, int] = {}
    for l in links:
        degree[l.source_id] = degree.get(l.source_id, 0) + 1
        degree[l.target_id] = degree.get(l.target_id, 0) + 1
        type_dist[l.type] = type_dist.get(l.type, 0) + 1
    top = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "action": "analyze",
        "target": "graph",
        "stats": {
            "entities": len(entities),
            "links": len(links),
            "links_by_type": type_dist,
        },
        "top_connected": [
            {"name": id_to_name.get(eid, f"#{eid}"), "links": count} for eid, count in top
        ],
    }


def autogen_handle(parsed_intent: dict[str, Any], db) -> dict[str, Any]:
    """Обработчик намерений: интерпретированная структура → действие в БД."""
    action = parsed_intent.get("action", "unknown")
    result: dict[str, Any] = {"action": action}

    try:
        if action == "create":
            name = str(parsed_intent.get("entity", "")).strip()
            if not name:
                return {"action": action, "error": "Имя сущности не указано"}
            existing = db.query(Entity).filter_by(name=name).first()
            if existing:
                return {"action": action, "exists": existing.to_dict()}
            meta = {}
            if parsed_intent.get("tag"):
                meta["tags"] = [str(parsed_intent["tag"])]
            entity = Entity(name=name, meta=json.dumps(meta, ensure_ascii=False))
            db.add(entity)
            db.commit()
            db.refresh(entity)
            result["created"] = entity.to_dict()
            publish_change(
                "entity.created",
                entity=name,
                data={"id": entity.id, "meta": meta},
            )

        elif action == "link":
            names = parsed_intent.get("entities", [])
            if not isinstance(names, list) or len(names) != 2:
                return {"action": action, "error": "Нужно ровно 2 имени для связи"}
            link_type = normalize_link_type(parsed_intent.get("link_type"))
            src = db.query(Entity).filter_by(name=str(names[0]).strip()).first()
            tgt = db.query(Entity).filter_by(name=str(names[1]).strip()).first()
            if not src or not tgt:
                missing = [
                    str(n).strip()
                    for n, e in ((names[0], src), (names[1], tgt))
                    if not e
                ]
                return {"action": action, "error": f"Сущность не найдена: {', '.join(missing)}"}
            existing_link = (
                db.query(Link)
                .filter_by(source_id=src.id, target_id=tgt.id, type=link_type)
                .first()
            )
            if existing_link:
                return {"action": action, "exists": existing_link.to_dict()}
            link = Link(source_id=src.id, target_id=tgt.id, type=link_type)
            db.add(link)
            db.commit()
            db.refresh(link)
            result["created"] = {
                "id": link.id,
                "source": src.name,
                "target": tgt.name,
                "type": link_type,
            }
            publish_change(
                "link.created",
                entity=src.name,
                data={"target": tgt.name, "type": link_type},
            )

        elif action == "delete":
            name = str(parsed_intent.get("entity", "")).strip()
            if not name:
                return {"action": action, "error": "Имя сущности не указано"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            # Дети теряют родителя (иерархия, issue #13)
            db.query(Entity).filter(Entity.parent_id == entity.id).update(
                {Entity.parent_id: None}, synchronize_session=False
            )
            db.delete(entity)
            db.commit()
            result["deleted"] = name
            publish_change("entity.deleted", entity=name)

        elif action == "query":
            name = str(parsed_intent.get("entity", "")).strip()
            if not name:
                return {"action": action, "error": "Имя сущности не указано"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            src_links = db.query(Link).filter_by(source_id=entity.id).all()
            tgt_links = db.query(Link).filter_by(target_id=entity.id).all()
            connections = []
            for lnk in src_links + tgt_links:
                other_id = lnk.target_id if lnk.source_id == entity.id else lnk.source_id
                other = db.query(Entity).filter_by(id=other_id).first()
                if other:
                    connections.append(
                        {"name": other.name, "type": lnk.type,
                         "direction": "out" if lnk.source_id == entity.id else "in"}
                    )
            result["entity"] = entity.to_dict()
            result["connections"] = connections

        elif action == "transform":
            name = str(parsed_intent.get("entity", "")).strip()
            to_name = str(parsed_intent.get("to", "")).strip()
            if not name or not to_name:
                return {"action": action, "error": "Нужны сущность и новое значение"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            conflict = db.query(Entity).filter_by(name=to_name).first()
            if conflict:
                return {"action": action, "error": f"Сущность '{to_name}' уже существует"}
            entity.name = to_name
            db.commit()
            db.refresh(entity)
            result["transformed"] = entity.to_dict()
            publish_change(
                "entity.updated",
                entity=to_name,
                data={"renamed_from": name},
            )

        elif action == "clone":
            name = str(parsed_intent.get("entity", "")).strip()
            if not name:
                return {"action": action, "error": "Имя сущности не указано"}
            source = db.query(Entity).filter_by(name=name).first()
            if not source:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            clone_name = f"{source.name} (копия)"
            counter = 2
            while db.query(Entity).filter_by(name=clone_name).first():
                clone_name = f"{source.name} (копия {counter})"
                counter += 1
            meta = _load_meta(source)
            clone = Entity(
                name=clone_name, meta=json.dumps(meta, ensure_ascii=False),
                parent_id=source.parent_id,
            )
            db.add(clone)
            db.commit()
            db.refresh(clone)
            # Копируем исходящие связи
            for lnk in db.query(Link).filter_by(source_id=source.id).all():
                db.add(Link(source_id=clone.id, target_id=lnk.target_id, type=lnk.type))
            db.commit()
            result["cloned"] = clone.to_dict()
            publish_change(
                "entity.created",
                entity=clone_name,
                data={"cloned_from": source.name},
            )

        elif action == "merge":
            names = parsed_intent.get("entities", [])
            if not isinstance(names, list) or len(names) != 2:
                return {"action": action, "error": "Нужно ровно 2 имени для объединения"}
            survivor = db.query(Entity).filter_by(name=str(names[0]).strip()).first()
            absorbed = db.query(Entity).filter_by(name=str(names[1]).strip()).first()
            if not survivor or not absorbed:
                missing = [
                    str(n).strip()
                    for n, e in ((names[0], survivor), (names[1], absorbed))
                    if not e
                ]
                return {"action": action, "error": f"Сущность не найдена: {', '.join(missing)}"}
            if survivor.id == absorbed.id:
                return {"action": action, "error": "Нельзя объединить сущность с собой"}
            # Переносим связи поглощённой на выжившую
            for lnk in db.query(Link).filter_by(source_id=absorbed.id).all():
                if lnk.target_id != survivor.id:
                    dup = (
                        db.query(Link)
                        .filter_by(source_id=survivor.id, target_id=lnk.target_id, type=lnk.type)
                        .first()
                    )
                    if not dup:
                        db.add(Link(source_id=survivor.id, target_id=lnk.target_id, type=lnk.type))
            for lnk in db.query(Link).filter_by(target_id=absorbed.id).all():
                if lnk.source_id != survivor.id:
                    dup = (
                        db.query(Link)
                        .filter_by(source_id=lnk.source_id, target_id=survivor.id, type=lnk.type)
                        .first()
                    )
                    if not dup:
                        db.add(Link(source_id=lnk.source_id, target_id=survivor.id, type=lnk.type))
            # Объединяем мета (теги)
            meta = _load_meta(survivor)
            other_meta = _load_meta(absorbed)
            tags = list(meta.get("tags", []))
            for tag in other_meta.get("tags", []):
                if tag not in tags:
                    tags.append(tag)
            if tags:
                meta["tags"] = tags
                _save_meta(survivor, meta)
            # Дети поглощённой переходят к выжившей
            db.query(Entity).filter(Entity.parent_id == absorbed.id).update(
                {Entity.parent_id: survivor.id}, synchronize_session=False
            )
            db.delete(absorbed)
            db.commit()
            db.refresh(survivor)
            result["merged"] = {
                "survivor": survivor.to_dict(),
                "absorbed": absorbed_name if (absorbed_name := str(names[1]).strip()) else None,
            }
            publish_change(
                "entity.deleted",
                entity=str(names[1]).strip(),
                data={"merged_into": survivor.name},
            )

        elif action == "tag":
            name = str(parsed_intent.get("entity", "")).strip()
            tag = str(parsed_intent.get("tag", "")).strip()
            if not name or not tag:
                return {"action": action, "error": "Нужны сущность и тег"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            meta = _load_meta(entity)
            tags = list(meta.get("tags", []))
            if tag not in tags:
                tags.append(tag)
            meta["tags"] = tags
            _save_meta(entity, meta)
            db.commit()
            db.refresh(entity)
            result["tagged"] = entity.to_dict()
            publish_change("entity.updated", entity=name, data={"tag_added": tag})

        elif action == "prioritize":
            name = str(parsed_intent.get("entity", "")).strip()
            priority = str(parsed_intent.get("priority", "")).strip()
            if not name or not priority:
                return {"action": action, "error": "Нужны сущность и приоритет"}
            if priority not in ("high", "medium", "low"):
                return {"action": action, "error": f"Неизвестный приоритет: {priority}"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            meta = _load_meta(entity)
            meta["priority"] = priority
            _save_meta(entity, meta)
            db.commit()
            db.refresh(entity)
            result["prioritized"] = entity.to_dict()
            publish_change("entity.updated", entity=name, data={"priority": priority})

        elif action == "schedule":
            task = str(parsed_intent.get("task", "")).strip()
            when = str(parsed_intent.get("when", "")).strip()
            if not task or not when:
                return {"action": action, "error": "Нужны задача и время"}
            schedule_data = {"task": task, "when": when, "status": "planned"}
            entity = db.query(Entity).filter_by(name=task).first()
            if entity:
                meta = _load_meta(entity)
                schedules = list(meta.get("schedules", []))
                schedules.append(schedule_data)
                meta["schedules"] = schedules
                _save_meta(entity, meta)
                db.commit()
                db.refresh(entity)
                result["scheduled"] = {"entity": entity.to_dict(), "schedule": schedule_data}
            else:
                entity = Entity(
                    name=task,
                    meta=json.dumps({"schedules": [schedule_data]}, ensure_ascii=False),
                )
                db.add(entity)
                db.commit()
                db.refresh(entity)
                result["scheduled"] = {"entity": entity.to_dict(), "schedule": schedule_data}
            publish_change(
                "entity.updated",
                entity=task,
                data={"scheduled": schedule_data},
            )

        elif action == "analyze":
            target = str(parsed_intent.get("target", "graph")).strip()
            if target == "graph":
                result.update(_analyze_graph(db))
            else:
                entity = db.query(Entity).filter_by(name=target).first()
                if not entity:
                    return {"action": action, "error": f"Сущность '{target}' не найдена"}
                src_count = db.query(Link).filter_by(source_id=entity.id).count()
                tgt_count = db.query(Link).filter_by(target_id=entity.id).count()
                meta = _load_meta(entity)
                result["target"] = target
                result["analysis"] = {
                    "entity": entity.to_dict(),
                    "links_out": src_count,
                    "links_in": tgt_count,
                    "tags": meta.get("tags", []),
                    "priority": meta.get("priority"),
                }

        elif action == "evolve":
            # Эволюция: добавить связанные теги-подсказки и зафиксировать намерение
            name = str(parsed_intent.get("entity", "")).strip()
            if not name:
                return {"action": action, "error": "Имя сущности не указано"}
            entity = db.query(Entity).filter_by(name=name).first()
            if not entity:
                return {"action": action, "error": f"Сущность '{name}' не найдена"}
            meta = _load_meta(entity)
            evolved = meta.get("evolved", 0) + 1
            meta["evolved"] = evolved
            _save_meta(entity, meta)
            db.commit()
            db.refresh(entity)
            result["evolved"] = entity.to_dict()
            publish_change("entity.updated", entity=name, data={"evolved": evolved})

        else:
            result["result"] = "Неизвестное действие"
            result["hint"] = (
                "Попробуйте: создать X, связать X и Y, найти X, удалить X, "
                "переименовать X в Y, клонировать X, объединить X и Y, "
                "добавить тег T к X, приоритет X высокий, "
                "запланировать X на завтра, проанализировать граф"
            )

    except Exception as exc:
        db.rollback()
        logger.exception("autogen failed for action=%s", action)
        result["error"] = str(exc)

    return result
