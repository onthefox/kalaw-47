"""
Агент-ревизор (issue #3, эпик Flow Executor): аудит целостности онтологии.

Проверки:
  - висячие связи (link указывает на несуществующую сущность)
  - сущности-сироты (нет ни одной связи)
  - дубликаты имён без учёта регистра (DB unique — регистрозависимый)
  - пустые/пробельные имена
  - циклы в иерархии parent_id

Каждый аудит публикует событие review.completed в шину наблюдателя.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from backend.models import Entity, Link
from engine.observer import publish_change

logger = logging.getLogger("symbio.reviewer")

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class ReviewerAgent:
    """Аудит целостности графа: findings с severity + сводка здоровья."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_report: dict[str, Any] | None = None
        self.audits_run = 0

    # --- Проверки ---

    def _find_dangling_links(self, db) -> list[dict[str, Any]]:
        entities = db.query(Entity).all()
        known_ids = {e.id for e in entities}
        id_to_name = {e.id: e.name for e in entities}
        findings = []
        for link in db.query(Link).all():
            for side, endpoint in (("source", link.source_id), ("target", link.target_id)):
                if endpoint not in known_ids:
                    findings.append(
                        {
                            "severity": "critical",
                            "kind": "dangling_link",
                            "entity": id_to_name.get(endpoint, f"#{endpoint}"),
                            "detail": (
                                f"Связь #{link.id} ({link.type}) указывает на "
                                f"несуществующую сущность ({side}={endpoint})"
                            ),
                        }
                    )
        return findings

    def _find_orphans(self, db) -> list[dict[str, Any]]:
        entities = db.query(Entity).all()
        if len(entities) <= 1:
            return []
        degree: dict[int, int] = {}
        for link in db.query(Link).all():
            degree[link.source_id] = degree.get(link.source_id, 0) + 1
            degree[link.target_id] = degree.get(link.target_id, 0) + 1
        parented = {e.parent_id for e in entities if e.parent_id is not None}
        return [
            {
                "severity": "info",
                "kind": "orphan_entity",
                "entity": e.name,
                "detail": f"Сущность '{e.name}' не связана с графом",
            }
            for e in entities
            if degree.get(e.id, 0) == 0 and e.id not in parented and e.parent_id is None
        ]

    def _find_duplicate_names(self, db) -> list[dict[str, Any]]:
        entities = db.query(Entity).all()
        seen: dict[str, list[str]] = {}
        for e in entities:
            seen.setdefault(e.name.lower(), []).append(e.name)
        return [
            {
                "severity": "warning",
                "kind": "duplicate_name",
                "entity": names[0],
                "detail": f"Регистрозависимые дубликаты имён: {', '.join(names)}",
            }
            for names in seen.values()
            if len(names) > 1
        ]

    def _find_empty_names(self, db) -> list[dict[str, Any]]:
        entities = db.query(Entity).all()
        return [
            {
                "severity": "critical",
                "kind": "empty_name",
                "entity": f"#{e.id}",
                "detail": f"Сущность #{e.id} имеет пустое имя",
            }
            for e in entities
            if not (e.name or "").strip()
        ]

    def _find_hierarchy_cycles(self, db) -> list[dict[str, Any]]:
        entities = db.query(Entity).all()
        parent_of = {e.id: e.parent_id for e in entities}
        id_to_name = {e.id: e.name for e in entities}
        findings: list[dict[str, Any]] = []
        visited: set[int] = set()
        for start in parent_of:
            if start in visited:
                continue
            path: list[int] = []
            node: int | None = start
            while node is not None and node in parent_of:
                if node in path:
                    cycle = path[path.index(node):]
                    visited.update(cycle)
                    names = [id_to_name.get(n, f"#{n}") for n in cycle]
                    findings.append(
                        {
                            "severity": "critical",
                            "kind": "hierarchy_cycle",
                            "entity": " → ".join(names),
                            "detail": f"Цикл в иерархии: {' → '.join(names)}",
                        }
                    )
                    break
                path.append(node)
                node = parent_of[node]
            visited.update(path)
        return findings

    # --- Публичный API ---

    def audit(self, db) -> dict[str, Any]:
        """Полный аудит: все проверки, отчёт с findings и вердиктом."""
        findings: list[dict[str, Any]] = []
        findings += self._find_dangling_links(db)
        findings += self._find_empty_names(db)
        findings += self._find_duplicate_names(db)
        findings += self._find_hierarchy_cycles(db)
        findings += self._find_orphans(db)
        findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 3))
        report = {
            "healthy": not any(f["severity"] in ("critical", "warning") for f in findings),
            "findings": findings,
            "counts": {
                "critical": sum(1 for f in findings if f["severity"] == "critical"),
                "warning": sum(1 for f in findings if f["severity"] == "warning"),
                "info": sum(1 for f in findings if f["severity"] == "info"),
            },
            "stats": {
                "entities": db.query(Entity).count(),
                "links": db.query(Link).count(),
            },
            "audited_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self.last_report = report
            self.audits_run += 1
        publish_change(
            "review.completed",
            data={
                "healthy": report["healthy"],
                "critical": report["counts"]["critical"],
                "warning": report["counts"]["warning"],
            },
            source="reviewer",
        )
        return report

    def review_mutation(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Быстрая проверка результата мутации: ошибка исполнителя — finding."""
        if result.get("error"):
            return {
                "severity": "warning",
                "kind": "mutation_error",
                "entity": None,
                "detail": str(result["error"]),
            }
        return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "audits_run": self.audits_run,
                "last_report_healthy": self.last_report["healthy"] if self.last_report else None,
            }

    def reset(self) -> None:
        with self._lock:
            self.last_report = None
            self.audits_run = 0


reviewer = ReviewerAgent()
