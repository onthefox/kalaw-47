"""
Issue #16: агент-наблюдатель — шина событий, журнал, alert-пороги.
"""

from __future__ import annotations

import pytest

from engine.observer import observer as global_observer
from engine.observer.observer import (
    EVENT_TYPES,
    ChangeEvent,
    EventBus,
    ObserverAgent,
    publish_change,
)


class TestChangeEvent:
    def test_defaults(self):
        event = ChangeEvent("entity.created", entity="А")
        assert event.type == "entity.created"
        assert event.entity == "А"
        assert event.data == {}
        assert event.source == "system"
        assert len(event.id) == 12

    def test_to_dict_roundtrip(self):
        event = ChangeEvent("link.created", entity="Б", data={"x": 1}, source="test")
        d = event.to_dict()
        assert d["type"] == "link.created"
        assert d["entity"] == "Б"
        assert d["data"] == {"x": 1}
        assert d["source"] == "test"
        assert isinstance(d["ts"], float)


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        seen = []
        bus.subscribe(seen.append)
        event = ChangeEvent("entity.created")
        delivered = bus.publish(event)
        assert delivered == 1
        assert seen == [event]

    def test_pattern_matching(self):
        bus = EventBus()
        entity_events = []
        bus.subscribe(entity_events.append, pattern="entity.*")
        bus.publish(ChangeEvent("entity.created"))
        bus.publish(ChangeEvent("link.created"))
        bus.publish(ChangeEvent("entity.deleted"))
        assert [e.type for e in entity_events] == ["entity.created", "entity.deleted"]

    def test_delivered_count(self):
        bus = EventBus()
        bus.subscribe(lambda e: None, pattern="a.*")
        bus.subscribe(lambda e: None, pattern="a.created")
        assert bus.publish(ChangeEvent("a.created")) == 2
        assert bus.publish(ChangeEvent("b.created")) == 0

    def test_subscriber_exception_does_not_break_bus(self):
        bus = EventBus()

        def bad(_event):
            raise RuntimeError("boom")

        seen = []
        bus.subscribe(bad)
        bus.subscribe(seen.append)
        delivered = bus.publish(ChangeEvent("entity.created"))
        assert delivered == 1
        assert len(seen) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        seen = []
        handle = bus.subscribe(seen.append)
        assert bus.unsubscribe(handle)
        bus.publish(ChangeEvent("entity.created"))
        assert seen == []
        assert not bus.unsubscribe(handle)  # повторно уже нельзя


class TestChangeLog:
    # publish_change пишет в глобальный singleton — используем его.
    def test_log_records_published_events(self):
        publish_change("entity.created", entity="А")
        entries = global_observer.get_log()
        assert len(entries) == 1
        assert entries[0]["type"] == "entity.created"

    def test_log_filter_by_event_type_pattern(self):
        publish_change("entity.created")
        publish_change("link.created")
        publish_change("entity.deleted")
        entity_only = global_observer.get_log(event_type="entity.*")
        assert {e["type"] for e in entity_only} == {"entity.created", "entity.deleted"}

    def test_log_filter_by_entity(self):
        publish_change("entity.created", entity="А")
        publish_change("entity.created", entity="Б")
        assert [e["entity"] for e in global_observer.get_log(entity="А")] == ["А"]

    def test_log_filter_since_ts(self):
        agent = ObserverAgent()
        old = ChangeEvent("entity.created")
        old.ts = 1000.0
        agent.bus.publish(old)
        new = ChangeEvent("entity.created")
        new.ts = 2000.0
        agent.bus.publish(new)
        assert [e["ts"] for e in agent.get_log(since_ts=1500.0)] == [2000.0]

    def test_log_newest_first_and_limit(self):
        agent = ObserverAgent()
        for i in range(5):
            event = ChangeEvent("entity.created")
            event.ts = float(i)
            agent.bus.publish(event)
        entries = agent.get_log(limit=3)
        assert len(entries) == 3
        assert [e["ts"] for e in entries] == [4.0, 3.0, 2.0]


class TestAlertRules:
    def test_threshold_triggers_alert(self):
        global_observer.add_rule("entity.*", threshold=2, window=60.0)
        publish_change("entity.created", entity="А")
        assert global_observer.get_alerts() == []
        publish_change("entity.created", entity="Б")
        alerts = global_observer.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["pattern"] == "entity.*"

    def test_triggered_count_and_reset(self):
        global_observer.add_rule("entity.*", threshold=1)
        publish_change("entity.created")
        publish_change("entity.deleted")
        rules = global_observer.list_rules()
        assert rules[0]["triggered"] == 2
        assert len(global_observer.get_alerts()) == 2

    def test_window_expiry_no_alert(self):
        agent = ObserverAgent()
        agent.add_rule("entity.*", threshold=2, window=10.0)
        old = ChangeEvent("entity.created")
        old.ts = 100.0
        agent.bus.publish(old)  # попадёт в окно, но при следующем событии истечёт
        late = ChangeEvent("entity.created")
        late.ts = 100.0 + 11.0  # вне окна: старое событие выталкивается
        agent.bus.publish(late)
        assert agent.get_alerts() == []

    def test_callback_invoked(self):
        calls = []
        global_observer.add_rule("entity.*", threshold=1, callback=lambda e, r: calls.append((e, r)))
        publish_change("entity.created", entity="А")
        assert len(calls) == 1
        event, rule = calls[0]
        assert event.type == "entity.created"
        assert rule.pattern == "entity.*"

    def test_pattern_mismatch_no_alert(self):
        agent = ObserverAgent()
        agent.add_rule("link.*", threshold=1)
        publish_change("entity.created")
        assert agent.get_alerts() == []

    def test_remove_rule(self):
        agent = ObserverAgent()
        rule_id = agent.add_rule("entity.*", threshold=1)
        assert agent.remove_rule(rule_id)
        publish_change("entity.created")
        assert agent.get_alerts() == []
        assert agent.list_rules() == []
        assert not agent.remove_rule(rule_id)


class TestStatsAndHelpers:
    def test_stats(self):
        global_observer.add_rule("entity.*", threshold=1)
        publish_change("entity.created")
        stats = global_observer.stats()
        assert stats == {"events": 1, "alerts": 1, "rules": 1}

    def test_reset(self):
        agent = ObserverAgent()
        agent.add_rule("entity.*", threshold=1)
        publish_change("entity.created")
        agent.reset()
        assert agent.stats() == {"events": 0, "alerts": 0, "rules": 0}

    def test_event_types_catalog(self):
        assert "entity.created" in EVENT_TYPES
        assert "ontology.imported" in EVENT_TYPES
        assert "module.generated" in EVENT_TYPES
        assert len(EVENT_TYPES) >= 8

    def test_publish_change_returns_event(self):
        event = publish_change("module.generated", entity="mod", data={"files": 2})
        assert event.type == "module.generated"
        assert event.data == {"files": 2}
