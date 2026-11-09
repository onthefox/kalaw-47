"""
Агент-планировщик (issue #17): план → валидация → выполнение → откат.

Состав:
  - generate_plan: план из одного или нескольких намерений (текст или dict),
    с автоматическими зависимостями (создание сущности раньше её связывания)
  - validate_plan: неизвестные действия, битые зависимости, циклы зависимостей,
    конфликтующие шаги (два шага меняют одну сущность несовместимым образом)
  - execute_plan: последовательное (topological) или параллельное (волны,
    ThreadPoolExecutor + собственная сессия на шаг) выполнение
  - Rollback: при ошибке шага выполненные шаги откатываются в обратном порядке
    (созданное удаляется, удалённое восстанавливается вместе со связями)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from core.symbio_core import interpret_intent
from engine.autogen import autogen_handle

logger = logging.getLogger("symbio.planner")

EXECUTABLE_ACTIONS = {
    "create",
    "link",
    "delete",
    "query",
    "transform",
    "clone",
    "merge",
    "tag",
    "prioritize",
    "schedule",
    "analyze",
}


@dataclass
class PlanStep:
    """Шаг плана."""

    id: str
    action: str
    params: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending|running|done|failed|rolled_back|skipped
    result: dict[str, Any] | None = None
    error: str | None = None
    snapshot: dict[str, Any] | None = None  # для rollback (delete: сущность + связи)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "params": self.params,
            "depends_on": self.depends_on,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Plan:
    """План: цель + упорядоченные шаги."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }


def _entities_of(params: dict[str, Any]) -> list[str]:
    result: list[str] = []
    if params.get("entity"):
        result.append(str(params["entity"]))
    for name in params.get("entities") or []:
        result.append(str(name))
    return result


def generate_plan(intents: list[dict[str, Any] | str] | dict[str, Any] | str, goal: str = "") -> Plan:
    """Сгенерировать план из намерения/намерений.

    Автозависимости: шаг, использующий сущность, зависит от ближайшего
    предыдущего шага, который её создаёт (create/clone).
    """
    if isinstance(intents, (dict, str)):
        intents = [intents]
    plan = Plan(goal=goal or "План из намерений")
    producers: dict[str, str] = {}

    for item in intents:
        if isinstance(item, str):
            parsed = interpret_intent(item)
        else:
            parsed = dict(item)
        action = parsed.get("action", "unknown")
        step = PlanStep(
            id=f"s{len(plan.steps) + 1}",
            action=action,
            params={k: v for k, v in parsed.items() if k not in ("confidence", "route", "raw")},
        )
        if action in ("create", "clone"):
            deps: list[str] = []
            if action == "clone":
                source = str(parsed.get("entity", ""))
                if source and source in producers:
                    deps.append(producers[source])
            step.depends_on = deps
            name = str(parsed.get("entity", "")).lower()
            if action == "clone":
                name = f"{name} (копия)"
            if name:
                producers[name] = step.id
        elif action in ("link", "merge"):
            deps = []
            for name in parsed.get("entities") or []:
                dep = producers.get(str(name).lower())
                if dep and dep not in deps:
                    deps.append(dep)
            step.depends_on = deps
        elif action in ("delete", "transform", "tag", "prioritize", "schedule", "query", "evolve", "analyze"):
            name = str(parsed.get("entity") or parsed.get("task") or parsed.get("target") or "").lower()
            dep = producers.get(name)
            if name and dep:
                step.depends_on = [dep]
        plan.steps.append(step)
    return plan


def validate_plan(plan: Plan) -> list[str]:
    """Валидация плана. Возвращает список проблем (пустой = план валиден)."""
    problems: list[str] = []
    ids = [s.id for s in plan.steps]
    if len(ids) != len(set(ids)):
        problems.append("дубликаты id шагов")

    by_id = {s.id: s for s in plan.steps}
    for step in plan.steps:
        if step.action not in EXECUTABLE_ACTIONS:
            problems.append(f"шаг {step.id}: неизвестное действие '{step.action}'")
        for dep in step.depends_on:
            if dep not in by_id:
                problems.append(f"шаг {step.id}: зависимость '{dep}' не существует")
            elif dep == step.id:
                problems.append(f"шаг {step.id}: зависит от самого себя")

    # Циклы зависимостей (DFS)
    state: dict[str, int] = {}

    def visit(step_id: str, stack: list[str]) -> None:
        state[step_id] = 1
        for dep in by_id.get(step_id, PlanStep(step_id, "unknown", {})).depends_on:
            if dep == step_id:
                continue
            if state.get(dep, 0) == 1:
                problems.append(f"цикл зависимостей: {' → '.join(stack + [step_id, dep])}")
            elif state.get(dep, 0) == 0 and dep in by_id:
                visit(dep, stack + [step_id])
        state[step_id] = 2

    for step in plan.steps:
        if state.get(step.id, 0) == 0:
            visit(step.id, [])

    # Конфликт: шаг удаляет сущность, а последующий шаг её изменяет/использует
    deleted: dict[str, str] = {}
    for step in plan.steps:
        if step.action == "delete":
            for name in _entities_of(step.params):
                deleted[str(name).lower()] = step.id
        elif step.action in ("transform", "tag", "prioritize", "link", "merge"):
            for name in _entities_of(step.params):
                owner = deleted.get(str(name).lower())
                if owner and owner != step.id:
                    problems.append(
                        f"шаг {step.id} использует '{name}', удалённую в шаге {owner}"
                    )
    return problems


def _topo_order(plan: Plan) -> list[PlanStep]:
    """Топологический порядок (Kahn). Бросает ValueError при цикле."""
    by_id = {s.id: s for s in plan.steps}
    indegree = {s.id: 0 for s in plan.steps}
    dependents: dict[str, list[str]] = {s.id: [] for s in plan.steps}
    for step in plan.steps:
        for dep in step.depends_on:
            if dep in by_id:
                indegree[step.id] += 1
                dependents[dep].append(step.id)
    queue = [sid for sid, deg in indegree.items() if deg == 0]
    order: list[PlanStep] = []
    while queue:
        sid = queue.pop(0)
        order.append(by_id[sid])
        for nxt in dependents[sid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(plan.steps):
        raise ValueError("План содержит цикл зависимостей")
    return order


def _waves(plan: Plan) -> list[list[PlanStep]]:
    """Разбить шаги на волны параллельного выполнения."""
    by_id = {s.id: s for s in plan.steps}
    remaining_deps = {
        s.id: {d for d in s.depends_on if d in by_id} for s in plan.steps
    }
    scheduled: set[str] = set()
    waves: list[list[PlanStep]] = []
    while len(scheduled) < len(plan.steps):
        wave = [
            s
            for s in plan.steps
            if s.id not in scheduled and remaining_deps[s.id] <= scheduled
        ]
        if not wave:
            raise ValueError("План содержит цикл зависимостей")
        waves.append(wave)
        scheduled.update(s.id for s in wave)
    return waves


def _snapshot_entity(db, name: str) -> dict[str, Any] | None:
    """Снимок сущности и её связей для rollback удаления."""
    from backend.models import Entity, Link

    entity = db.query(Entity).filter_by(name=name).first()
    if not entity:
        return None
    links = (
        db.query(Link).filter(Link.source_id == entity.id).all()
        + db.query(Link).filter(Link.target_id == entity.id).all()
    )
    id_to_name = {
        e.id: e.name for e in db.query(Entity).filter(Entity.id.in_(
            [l.source_id for l in links] + [l.target_id for l in links]
        )).all()
    }
    id_to_name[entity.id] = entity.name
    return {
        "entity": entity.to_dict(),
        "links": [
            {
                "source": id_to_name.get(l.source_id),
                "target": id_to_name.get(l.target_id),
                "type": l.type,
            }
            for l in links
        ],
    }


def _rollback_step(step: PlanStep, db) -> None:
    """Откатить один выполненный шаг."""
    from backend.models import Entity, Link

    action = step.action
    params = step.params
    if action == "create" and step.result and isinstance(step.result.get("created"), dict):
        name = step.result["created"].get("name")
        if name:
            entity = db.query(Entity).filter_by(name=name).first()
            if entity:
                db.delete(entity)
                db.commit()
        step.status = "rolled_back"
    elif action == "link" and step.result and isinstance(step.result.get("created"), dict):
        created = step.result["created"]
        src_name, tgt_name = created.get("source"), created.get("target")
        src = db.query(Entity).filter_by(name=src_name).first()
        tgt = db.query(Entity).filter_by(name=tgt_name).first()
        if src and tgt:
            db.query(Link).filter_by(
                source_id=src.id, target_id=tgt.id, type=created.get("type", "relates")
            ).delete()
            db.commit()
        step.status = "rolled_back"
    elif action == "delete" and step.snapshot:
        data = step.snapshot["entity"]
        restored = Entity(name=data["name"], meta=data.get("meta", "{}"))
        db.add(restored)
        db.commit()
        db.refresh(restored)
        for l in step.snapshot.get("links", []):
            src = db.query(Entity).filter_by(name=l.get("source")).first()
            tgt = db.query(Entity).filter_by(name=l.get("target")).first()
            if src and tgt and (src.id != restored.id or tgt.id != restored.id):
                db.add(Link(source_id=src.id, target_id=tgt.id, type=l.get("type", "relates")))
        db.commit()
        step.status = "rolled_back"
    elif action == "transform" and step.snapshot:
        old_name = step.snapshot.get("old_name")
        entity = db.query(Entity).filter_by(name=params.get("to", "")).first()
        if old_name and entity:
            entity.name = old_name
            db.commit()
        step.status = "rolled_back"
    elif action == "tag":
        entity = db.query(Entity).filter_by(name=params.get("entity", "")).first()
        if entity:
            import json

            try:
                meta = json.loads(entity.meta or "{}")
            except json.JSONDecodeError:
                meta = {}
            tags = meta.get("tags", [])
            tag = str(params.get("tag", ""))
            if tag in tags:
                tags.remove(tag)
                meta["tags"] = tags
                entity.meta = json.dumps(meta, ensure_ascii=False)
                db.commit()
        step.status = "rolled_back"
    else:
        step.status = "rolled_back"


def execute_plan(
    plan: Plan,
    db,
    parallel: bool = False,
    session_factory: Callable[[], Any] | None = None,
    executor: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Выполнить план. При ошибке — откат выполненных шагов.

    parallel=True требует session_factory (своя сессия на шаг).
    """
    run_step = executor or autogen_handle
    plan_result: dict[str, Any] = {
        "plan_id": plan.id,
        "goal": plan.goal,
        "steps": [],
        "status": "completed",
    }

    def run_one(step: PlanStep, session) -> dict[str, Any]:
        step.status = "running"
        try:
            result = run_step(step.params, session)
            if "error" in result:
                step.status = "failed"
                step.error = str(result.get("error"))
                return {"ok": False, "result": result}
            step.status = "done"
            step.result = result
            return {"ok": True, "result": result}
        except Exception as exc:
            session.rollback()
            step.status = "failed"
            step.error = str(exc)
            return {"ok": False, "result": {"error": str(exc)}}

    def finish_failure(failed_step: PlanStep) -> dict[str, Any]:
        logger.warning("plan %s failed at step %s; rolling back", plan.id, failed_step.id)
        for completed in reversed(done_steps):
            if completed.action in ("create", "link", "delete", "transform", "tag"):
                try:
                    _rollback_step(completed, db)
                except Exception:
                    logger.exception("rollback failed for step %s", completed.id)
        db.commit()
        plan_result["status"] = "rolled_back" if done_steps else "failed"
        plan_result["failed_step"] = failed_step.id
        plan_result["error"] = failed_step.error
        plan_result["steps"] = [s.to_dict() for s in plan.steps]
        return plan_result

    done_steps: list[PlanStep] = []

    if not parallel:
        try:
            ordered = _topo_order(plan)
        except ValueError as exc:
            plan_result.update({"status": "invalid", "error": str(exc)})
            plan_result["steps"] = [s.to_dict() for s in plan.steps]
            return plan_result
        for step in ordered:
            # Снимок перед деструктивными шагами
            if step.action == "delete":
                step.snapshot = _snapshot_entity(db, str(step.params.get("entity", "")))
            elif step.action == "transform":
                from backend.models import Entity

                src = db.query(Entity).filter_by(name=str(step.params.get("entity", ""))).first()
                step.snapshot = {"old_name": src.name} if src else None
            outcome = run_one(step, db)
            plan_result["steps"].append(step.to_dict())
            if not outcome["ok"]:
                return finish_failure(step)
            done_steps.append(step)
    else:
        if session_factory is None:
            raise ValueError("parallel=True требует session_factory")
        try:
            waves = _waves(plan)
        except ValueError as exc:
            plan_result.update({"status": "invalid", "error": str(exc)})
            plan_result["steps"] = [s.to_dict() for s in plan.steps]
            return plan_result
        for wave in waves:
            with ThreadPoolExecutor(max_workers=min(4, len(wave))) as pool:
                futures = {}
                for step in wave:
                    if step.action == "delete":
                        step.snapshot = _snapshot_entity(db, str(step.params.get("entity", "")))
                    session = session_factory()
                    futures[pool.submit(run_one, step, session)] = step
                for future in futures:
                    future.result()
            wave_failed = [s for s in wave if s.status == "failed"]
            if wave_failed:
                done_steps.extend(s for s in plan.steps if s.status == "done" and s not in done_steps)
                return finish_failure(wave_failed[0])
            done_steps.extend(wave)

    plan_result["steps"] = [s.to_dict() for s in plan.steps]
    return plan_result


class PlannerAgent:
    """Обёртка: generate → validate → execute."""

    def __init__(self, name: str = "planner") -> None:
        self.name = name

    def plan(self, intents: list[dict[str, Any] | str] | dict[str, Any] | str, goal: str = "") -> dict[str, Any]:
        plan = generate_plan(intents, goal)
        problems = validate_plan(plan)
        return {"plan": plan.to_dict(), "valid": not problems, "problems": problems}

    def run(
        self,
        intents: list[dict[str, Any] | str] | dict[str, Any] | str,
        db,
        parallel: bool = False,
        session_factory: Callable[[], Any] | None = None,
        goal: str = "",
    ) -> dict[str, Any]:
        plan = generate_plan(intents, goal)
        problems = validate_plan(plan)
        if problems:
            return {"status": "invalid", "problems": problems, "plan": plan.to_dict()}
        return execute_plan(plan, db, parallel=parallel, session_factory=session_factory)


# Глобальный singleton
planner = PlannerAgent()
