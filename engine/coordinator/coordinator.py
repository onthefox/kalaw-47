"""
Агент-координатор (issue #3, эпик Flow Executor): маршрутизация намерений.

Полный состав экосистемы из 5 агентов:
  наблюдатель (engine/observer), планировщик (engine/planner),
  исполнитель (engine/autogen), ревизор (engine/reviewer),
  координатор (этот модуль).

Координатор:
  - держит реестр агентов с состоянием (idle/busy/available)
  - dispatch(): unknown → clarification; один интент → исполнитель;
    несколько интентов → планировщик → исполнитель
  - review-gate: после мутаций прогоняет ревизора, при ошибке — эскалация
  - подписан на шину наблюдателя и ведёт счётчики маршрутов
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from engine.observer import ChangeEvent, publish_change

logger = logging.getLogger("symbio.coordinator")

MUTATION_ACTIONS = {"create", "link", "delete", "transform", "clone", "merge", "tag",
                    "prioritize", "schedule", "evolve"}


class CoordinatorAgent:
    """Реестр агентов + диспетчеризация намерений с review-gate."""

    def __init__(self, reviewer=None, bus=None) -> None:
        self.reviewer = reviewer
        self._lock = threading.Lock()
        self._agents: dict[str, dict[str, Any]] = {}
        self._routes: dict[str, int] = {}
        self._handled = 0
        self._subscriptions: list[str] = []
        if bus is not None:
            self._subscriptions.append(bus.subscribe(self.on_event, "*"))

    # --- Реестр агентов ---

    def _register_detected_agents(self) -> None:
        """Зарегистрировать всех 5 агентов эпика с доступностью модулей."""
        def available(module: str) -> bool:
            try:
                __import__(module)
                return True
            except ImportError:
                return False

        for name, module in (
            ("observer", "engine.observer"),
            ("planner", "engine.planner"),
            ("executor", "engine.autogen"),
            ("reviewer", "engine.reviewer"),
            ("coordinator", "engine.coordinator"),
        ):
            with self._lock:
                if name not in self._agents:
                    self._agents[name] = {
                        "name": name,
                        "status": "idle",
                        "available": available(module),
                        "handled": 0,
                        "last_activity": None,
                    }

    def list_agents(self) -> list[dict[str, Any]]:
        self._register_detected_agents()
        with self._lock:
            return [dict(a) for a in self._agents.values()]

    def _touch(self, name: str, status: str = "done") -> None:
        """Отметить активность агента; handled растёт один раз на завершение."""
        with self._lock:
            agent = self._agents.get(name)
            if agent:
                agent["status"] = "idle" if status == "done" else status
                if status == "done":
                    agent["handled"] += 1
                agent["last_activity"] = time.time()

    # --- Диспетчеризация ---

    def dispatch(self, intents: list[dict[str, Any]] | dict[str, Any], db) -> dict[str, Any]:
        """Маршрутизировать намерение(я) по агентам и вернуть отчёт о прогоне."""
        self._register_detected_agents()
        items = intents if isinstance(intents, list) else [intents]
        route = "clarification"
        if len(items) > 1:
            route = "planner"
        elif items and items[0].get("action") not in (None, "unknown"):
            route = "executor"
        with self._lock:
            self._routes[route] = self._routes.get(route, 0) + 1
            self._handled += 1

        result: dict[str, Any] = {"route": route, "agents_involved": ["coordinator"]}
        if route == "clarification":
            result["needs_clarification"] = True
            result["question"] = "Не распознано действие — уточните намерение"
            return result

        if route == "planner":
            from engine.planner import execute_plan, generate_plan, validate_plan

            self._touch("planner", "busy")
            result["agents_involved"].append("planner")
            plan = generate_plan(items)
            problems = validate_plan(plan)
            if problems:
                result["planner_error"] = problems
                self._touch("planner", "failed")
                return result
            result["execution"] = execute_plan(plan, db)
            self._touch("planner", "done")
        else:
            from engine.autogen import autogen_handle

            self._touch("executor", "busy")
            result["agents_involved"].append("executor")
            result["execution"] = autogen_handle(items[0], db)
            self._touch("executor", "done")

        # Review-gate: мутации проверяет ревизор
        execution = result.get("execution") or {}
        if self.reviewer is not None and any(
            step.get("action") in MUTATION_ACTIONS
            for step in (execution.get("results") or [execution])
            if isinstance(step, dict)
        ):
            self._touch("reviewer", "busy")
            result["agents_involved"].append("reviewer")
            findings = [
                f
                for f in (
                    self.reviewer.review_mutation(step)
                    for step in (execution.get("results") or [execution])
                    if isinstance(step, dict)
                )
                if f
            ]
            result["review"] = {"healthy": not findings, "findings": findings}
            if findings:
                result["escalated"] = True
                logger.warning("coordinator: эскалация — %d находок ревизора", len(findings))
            self._touch("reviewer", "done")

        publish_change(
            "coordinator.dispatched",
            data={"route": route, "agents": result["agents_involved"]},
            source="coordinator",
        )
        return result

    # --- События шины ---

    def on_event(self, event: ChangeEvent) -> None:
        """Подписка на шину: считаем события, помечаем наблюдателя активным."""
        self._register_detected_agents()
        self._touch("observer")

    # --- Статус ---

    def status(self) -> dict[str, Any]:
        self._register_detected_agents()
        with self._lock:
            return {
                "agents": [dict(a) for a in self._agents.values()],
                "routes": dict(self._routes),
                "total_handled": self._handled,
            }

    def reset(self) -> None:
        with self._lock:
            self._agents.clear()
            self._routes.clear()
            self._handled = 0


coordinator = CoordinatorAgent()
