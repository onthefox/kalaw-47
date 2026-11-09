"""Тесты агентов-ревизора и координатора (issue #3, эпик Flow Executor)."""

from __future__ import annotations

import pytest

from engine.coordinator import CoordinatorAgent
from engine.observer import EventBus
from engine.reviewer import ReviewerAgent


# --- Ревизор ---

class TestReviewer:
    def test_healthy_graph_passes(self, db_session):
        from backend.models import Entity, Link

        a = Entity(name="А"); b = Entity(name="Б")
        db_session.add_all([a, b]); db_session.commit()
        db_session.add(Link(source_id=a.id, target_id=b.id, type="relates"))
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        assert report["healthy"] is True
        assert report["counts"]["critical"] == 0
        assert report["counts"]["warning"] == 0

    def test_dangling_link_detected(self, db_session):
        from backend.models import Entity, Link

        a = Entity(name="А")
        db_session.add(a); db_session.commit()
        # Прямая вставка связи на несуществующую сущность (мимо ограничений API)
        db_session.add(Link(source_id=a.id, target_id=99999, type="relates"))
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        assert report["healthy"] is False
        kinds = {f["kind"] for f in report["findings"]}
        assert "dangling_link" in kinds
        assert report["counts"]["critical"] >= 1

    def test_duplicate_case_names_detected(self, db_session):
        from backend.models import Entity

        db_session.add_all([Entity(name="Молоко"), Entity(name="молоко")])
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        kinds = {f["kind"] for f in report["findings"]}
        assert "duplicate_name" in kinds
        assert report["healthy"] is False

    def test_hierarchy_cycle_detected(self, db_session):
        from backend.models import Entity

        a = Entity(name="А"); b = Entity(name="Б"); c = Entity(name="В")
        db_session.add_all([a, b, c]); db_session.commit()
        b.parent_id = a.id
        c.parent_id = b.id
        a.parent_id = c.id  # замыкаем цикл напрямую в БД
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        kinds = {f["kind"] for f in report["findings"]}
        assert "hierarchy_cycle" in kinds

    def test_empty_name_detected(self, db_session):
        from backend.models import Entity

        db_session.add(Entity(name="   "))
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        assert any(f["kind"] == "empty_name" for f in report["findings"])

    def test_orphan_reported_as_info(self, db_session):
        from backend.models import Entity

        db_session.add(Entity(name="Одинокая"))
        db_session.commit()

        report = ReviewerAgent().audit(db_session)
        # Одинокая сущность — единственная, сирот-детект включается от 2+
        db_session.add(Entity(name="Вторая"))
        db_session.commit()
        report = ReviewerAgent().audit(db_session)
        orphans = [f for f in report["findings"] if f["kind"] == "orphan_entity"]
        assert len(orphans) == 2
        assert all(f["severity"] == "info" for f in orphans)
        assert report["healthy"] is True  # info не делает граф нездоровым

    def test_audit_publishes_event(self, db_session):
        from engine.observer import observer

        ReviewerAgent().audit(db_session)
        events = observer.get_log(event_type="review.completed")
        assert len(events) == 1
        assert events[0]["source"] == "reviewer"

    def test_stats_and_reset(self, db_session):
        agent = ReviewerAgent()
        agent.audit(db_session)
        assert agent.stats()["audits_run"] == 1
        agent.reset()
        assert agent.stats()["audits_run"] == 0
        assert agent.stats()["last_report_healthy"] is None

    def test_review_mutation_flags_error(self):
        agent = ReviewerAgent()
        assert agent.review_mutation({"action": "create"}) is None
        finding = agent.review_mutation({"action": "create", "error": "не найдено"})
        assert finding is not None
        assert finding["severity"] == "warning"


# --- Координатор ---

class TestCoordinator:
    def test_registry_contains_five_agents(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        agents = {a["name"] for a in coord.list_agents()}
        assert agents == {"observer", "planner", "executor", "reviewer", "coordinator"}
        assert all(a["available"] for a in coord.list_agents())

    def test_unknown_intent_routes_to_clarification(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        result = coord.dispatch({"action": "unknown"}, db_session)
        assert result["route"] == "clarification"
        assert result["needs_clarification"] is True

    def test_single_intent_routes_to_executor(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        result = coord.dispatch({"action": "create", "entity": "Коорд-Сущность"}, db_session)
        assert result["route"] == "executor"
        assert "executor" in result["agents_involved"]
        assert result["execution"]["created"]["name"] == "Коорд-Сущность"

    def test_multiple_intents_route_to_planner(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        result = coord.dispatch(
            [
                {"action": "create", "entity": "План-А"},
                {"action": "create", "entity": "План-Б"},
            ],
            db_session,
        )
        assert result["route"] == "planner"
        assert "planner" in result["agents_involved"]
        assert result["execution"]["status"] == "completed"
        assert len(result["execution"]["steps"]) == 2

    def test_review_gate_on_mutation(self, db_session):
        reviewer = ReviewerAgent()
        coord = CoordinatorAgent(reviewer=reviewer)
        result = coord.dispatch({"action": "create", "entity": "Гейт"}, db_session)
        assert "reviewer" in result["agents_involved"]
        assert result["review"]["healthy"] is True
        assert reviewer.stats()["audits_run"] == 0  # review_mutation не полный аудит

    def test_review_gate_escalates_on_error(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        # delete несуществующей сущности → error от исполнителя → эскалация
        result = coord.dispatch({"action": "delete", "entity": "Нет-Такой"}, db_session)
        assert result.get("escalated") is True
        assert result["review"]["healthy"] is False

    def test_query_does_not_trigger_review(self, db_session):
        from backend.models import Entity

        db_session.add(Entity(name="Сущь"))
        db_session.commit()
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        result = coord.dispatch({"action": "query", "entity": "Сущь"}, db_session)
        assert "reviewer" not in result["agents_involved"]
        assert "review" not in result

    def test_status_counters(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        coord.dispatch({"action": "unknown"}, db_session)
        coord.dispatch({"action": "create", "entity": "Счёт"}, db_session)
        status = coord.status()
        assert status["routes"] == {"clarification": 1, "executor": 1}
        assert status["total_handled"] == 2
        by_name = {a["name"]: a for a in status["agents"]}
        assert by_name["executor"]["handled"] == 1
        assert by_name["coordinator"]["handled"] == 0  # сам себя не трогает

    def test_reset(self, db_session):
        coord = CoordinatorAgent(reviewer=ReviewerAgent())
        coord.dispatch({"action": "create", "entity": "Сброс"}, db_session)
        coord.reset()
        assert coord.status()["total_handled"] == 0
        # Реестр перевыстраивается автоматически, но счётчики обнулены
        by_name = {a["name"]: a for a in coord.status()["agents"]}
        assert by_name["executor"]["handled"] == 0
        assert coord.status()["routes"] == {}

    def test_bus_subscription_marks_observer(self, db_session):
        bus = EventBus()
        coord = CoordinatorAgent(reviewer=ReviewerAgent(), bus=bus)
        bus.publish(type("E", (), {"type": "entity.created"})())
        by_name = {a["name"]: a for a in coord.list_agents()}
        assert by_name["observer"]["handled"] == 1


# --- API ---

class TestAgentsApi:
    def test_review_endpoint(self, client):
        resp = client.post("/review")
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data
        assert "findings" in data
        assert data["counts"]["critical"] == 0

    def test_agents_status_endpoint(self, client):
        resp = client.get("/agents/status")
        assert resp.status_code == 200
        data = resp.json()
        names = {a["name"] for a in data["agents"]}
        assert names == {"observer", "planner", "executor", "reviewer", "coordinator"}
        assert "reviewer" in data
