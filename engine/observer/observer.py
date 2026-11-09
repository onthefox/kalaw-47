"""
Агент-наблюдатель (issue #16): мониторинг изменений онтологии.

Состав:
  - EventBus: публикация/подписка событий с pattern matching (fnmatch)
  - ObserverAgent: журнал изменений с фильтрацией, alert-пороги
    (N событий шаблона за окно времени), подписка на шину
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

logger = logging.getLogger("symbio.observer")

EVENT_TYPES = (
    "entity.created",
    "entity.updated",
    "entity.deleted",
    "link.created",
    "link.deleted",
    "ontology.imported",
    "module.generated",
    "intent.processed",
    "intent.clarification",
    "review.completed",
    "coordinator.dispatched",
)


class ChangeEvent:
    """Событие изменения онтологии."""

    def __init__(
        self,
        event_type: str,
        entity: str | None = None,
        data: dict[str, Any] | None = None,
        source: str = "system",
        ts: float | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.ts = time.time() if ts is None else ts
        self.type = event_type
        self.entity = entity
        self.data = dict(data or {})
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "entity": self.entity,
            "data": self.data,
            "source": self.source,
        }


class EventBus:
    """Шина событий: подписчики с fnmatch-паттернами (например, 'entity.*')."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[str, Callable[[ChangeEvent], None]]] = []
        self._lock = threading.Lock()

    def subscribe(
        self, callback: Callable[[ChangeEvent], None], pattern: str = "*"
    ) -> str:
        handle = uuid.uuid4().hex[:12]
        with self._lock:
            self._subscribers.append((handle, pattern, callback))
        return handle

    def unsubscribe(self, handle: str) -> bool:
        with self._lock:
            before = len(self._subscribers)
            self._subscribers = [s for s in self._subscribers if s[0] != handle]
            return len(self._subscribers) < before

    def publish(self, event: ChangeEvent) -> int:
        """Доставить событие подходящим подписчикам. Возвращает число доставок."""
        delivered = 0
        with self._lock:
            subscribers = list(self._subscribers)
        for handle, pattern, callback in subscribers:
            if fnmatch.fnmatch(event.type, pattern):
                try:
                    callback(event)
                    delivered += 1
                except Exception:
                    logger.exception("subscriber %s failed on %s", handle, event.type)
        return delivered


class AlertRule:
    """Пороговое правило: >= threshold событий по паттерну за окно window сек."""

    def __init__(
        self,
        rule_id: str,
        pattern: str,
        threshold: int = 1,
        window: float = 60.0,
        callback: Callable[[ChangeEvent, "AlertRule"], None] | None = None,
        message: str | None = None,
    ) -> None:
        self.id = rule_id
        self.pattern = pattern
        self.threshold = max(1, int(threshold))
        self.window = float(window)
        self.callback = callback
        self.message = message
        self.hits: deque[float] = deque()
        self.triggered_count = 0


class ObserverAgent:
    """Наблюдатель: журнал изменений + пороговые оповещения."""

    def __init__(
        self,
        bus: EventBus | None = None,
        max_log: int = 1000,
        max_alerts: int = 500,
    ) -> None:
        self.bus = bus or EventBus()
        self._log: deque[ChangeEvent] = deque(maxlen=max_log)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=max_alerts)
        self._rules: dict[str, AlertRule] = {}
        self._lock = threading.Lock()
        self.bus.subscribe(self._on_event, "*")

    # --- Правила ---

    def add_rule(
        self,
        pattern: str,
        threshold: int = 1,
        window: float = 60.0,
        callback: Callable[[ChangeEvent, AlertRule], None] | None = None,
        message: str | None = None,
    ) -> str:
        rule_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._rules[rule_id] = AlertRule(
                rule_id, pattern, threshold, window, callback, message
            )
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": r.id,
                    "pattern": r.pattern,
                    "threshold": r.threshold,
                    "window": r.window,
                    "message": r.message,
                    "triggered": r.triggered_count,
                }
                for r in self._rules.values()
            ]

    # --- Обработка событий ---

    def _on_event(self, event: ChangeEvent) -> None:
        with self._lock:
            self._log.append(event)
            rules = list(self._rules.values())
        for rule in rules:
            if not fnmatch.fnmatch(event.type, rule.pattern):
                continue
            now = event.ts
            with self._lock:
                rule.hits.append(now)
                while rule.hits and rule.hits[0] < now - rule.window:
                    rule.hits.popleft()
                hits_count = len(rule.hits)
            if hits_count >= rule.threshold:
                with self._lock:
                    rule.hits.clear()
                    rule.triggered_count += 1
                alert = {
                    "id": uuid.uuid4().hex[:12],
                    "ts": now,
                    "rule_id": rule.id,
                    "pattern": rule.pattern,
                    "message": rule.message or f"Порог {rule.threshold} по '{rule.pattern}'",
                    "event": event.to_dict(),
                }
                with self._lock:
                    self._alerts.append(alert)
                logger.warning(
                    "alert: rule=%s pattern=%s count>=%d", rule.id, rule.pattern, rule.threshold
                )
                if rule.callback:
                    try:
                        rule.callback(event, rule)
                    except Exception:
                        logger.exception("alert callback failed for rule %s", rule.id)

    # --- Журнал и оповещения ---

    def get_log(
        self,
        event_type: str | None = None,
        entity: str | None = None,
        since_ts: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Журнал изменений с фильтрацией по типу, сущности и времени."""
        with self._lock:
            events = list(self._log)
        result = []
        for event in reversed(events):  # свежие первыми
            if event_type and not fnmatch.fnmatch(event.type, event_type):
                continue
            if entity and event.entity != entity:
                continue
            if since_ts is not None and event.ts < since_ts:
                continue
            result.append(event.to_dict())
            if len(result) >= max(1, limit):
                break
        return result

    def get_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            alerts = list(self._alerts)
        return list(reversed(alerts))[: max(1, limit)]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "events": len(self._log),
                "alerts": len(self._alerts),
                "rules": len(self._rules),
            }

    def reset(self) -> None:
        with self._lock:
            self._log.clear()
            self._alerts.clear()
            self._rules.clear()


def publish_change(
    event_type: str,
    entity: str | None = None,
    data: dict[str, Any] | None = None,
    source: str = "autogen",
) -> ChangeEvent:
    """Опубликовать событие через глобального наблюдателя."""
    event = ChangeEvent(event_type, entity=entity, data=data, source=source)
    observer.bus.publish(event)
    return event


# Глобальные singleton'ы: шина + наблюдатель
bus = EventBus()
observer = ObserverAgent(bus=bus)
