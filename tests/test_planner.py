"""
Issue #17: планировщик — генерация, валидация, выполнение (послед./паралл.), откат.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, Entity, Link
from engine.planner.planner import (
    EXECUTABLE_ACTIONS,
    Plan,
    PlanStep,
    PlannerAgent,
    execute_plan,
    generate_plan,
    validate_plan,
)


class TestGeneratePlan:
    def test_single_string_intent(self):
        plan = generate_plan("создать Alpha")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.action == "create"
        assert step.params["entity"] == "alpha"
        assert step.status == "pending"
        assert plan.goal

    def test_params_strip_confidence_route_raw(self):
        plan = generate_plan(["создать Alpha"])
        params = plan.steps[0].params
        assert "confidence" not in params
        assert "raw" not in params
        assert "route" not in params
        assert params["action"] == "create"

    def test_link_depends_on_producers(self):
        plan = generate_plan(["создать Alpha", "создать Beta", "связать Alpha и Beta"])
        assert [s.action for s in plan.steps] == ["create", "create", "link"]
        assert plan.steps[2].depends_on == ["s1", "s2"]

    def test_clone_depends_on_source(self):
        plan = generate_plan(["создать Alpha", "клонировать Alpha"])
        assert plan.steps[1].action == "clone"
        assert plan.steps[1].depends_on == ["s1"]

    def test_delete_depends_on_create(self):
        plan = generate_plan(["создать Alpha", "удалить Alpha"])
        assert plan.steps[1].action == "delete"
        assert plan.steps[1].depends_on == ["s1"]

    def test_independent_steps_have_no_deps(self):
        plan = generate_plan(["создать Alpha", "создать Beta"])
        assert plan.steps[0].depends_on == []
        assert plan.steps[1].depends_on == []

    def test_plan_to_dict(self):
        plan = generate_plan(["создать Alpha"], goal="Цель")
        d = plan.to_dict()
        assert d["goal"] == "Цель"
        assert d["steps"][0]["action"] == "create"
        assert "created_at" in d and d["id"]


class TestValidatePlan:
    def test_valid_plan(self):
        plan = generate_plan(["создать Alpha", "создать Beta", "связать Alpha и Beta"])
        assert validate_plan(plan) == []

    def test_unknown_action(self):
        plan = Plan(goal="t", steps=[PlanStep(id="s1", action="fly", params={})])
        problems = validate_plan(plan)
        assert any("неизвестное действие 'fly'" in p for p in problems)

    def test_executable_actions_covers_eleven(self):
        assert "create" in EXECUTABLE_ACTIONS
        assert "evolve" not in EXECUTABLE_ACTIONS
        assert len(EXECUTABLE_ACTIONS) == 11

    def test_missing_dependency(self):
        plan = Plan(
            goal="t",
            steps=[PlanStep(id="s1", action="create", params={}, depends_on=["s9"])],
        )
        problems = validate_plan(plan)
        assert any("не существует" in p for p in problems)

    def test_self_dependency(self):
        plan = Plan(
            goal="t",
            steps=[PlanStep(id="s1", action="create", params={}, depends_on=["s1"])],
        )
        problems = validate_plan(plan)
        assert any("самого себя" in p for p in problems)

    def test_dependency_cycle_detected(self):
        plan = Plan(
            goal="t",
            steps=[
                PlanStep(id="s1", action="create", params={}, depends_on=["s2"]),
                PlanStep(id="s2", action="create", params={}, depends_on=["s1"]),
            ],
        )
        problems = validate_plan(plan)
        assert any("цикл зависимостей" in p for p in problems)

    def test_delete_then_use_conflict(self):
        plan = Plan(
            goal="t",
            steps=[
                PlanStep(id="s1", action="delete", params={"entity": "alpha"}),
                PlanStep(id="s2", action="tag", params={"entity": "alpha", "tag": "x"}),
            ],
        )
        problems = validate_plan(plan)
        assert any("использует 'alpha', удалённую в шаге s1" in p for p in problems)

    def test_duplicate_step_ids(self):
        plan = Plan(
            goal="t",
            steps=[
                PlanStep(id="s1", action="create", params={"entity": "a"}),
                PlanStep(id="s1", action="create", params={"entity": "b"}),
            ],
        )
        assert any("дубликаты id" in p for p in validate_plan(plan))


class TestExecuteSequential:
    def test_happy_path_creates_and_links(self, db_session):
        plan = generate_plan(["создать Alpha", "создать Beta", "связать Alpha и Beta"])
        result = execute_plan(plan, db_session)
        assert result["status"] == "completed"
        assert all(s["status"] == "done" for s in result["steps"])
        names = {e.name for e in db_session.query(Entity).all()}
        assert names == {"alpha", "beta"}
        link = db_session.query(Link).one()
        assert (link.source_id, link.target_id) != (None, None)

    def test_rollback_on_failure(self, db_session):
        plan = generate_plan(["создать Alpha", "связать Alpha и Ghost"])
        result = execute_plan(plan, db_session)
        assert result["status"] == "rolled_back"
        assert result["failed_step"] == "s2"
        assert db_session.query(Entity).count() == 0

    def test_multi_step_rollback_removes_created_entities_and_links(self, db_session):
        plan = generate_plan(
            ["создать Alpha", "создать Beta", "связать Alpha и Beta", "связать Alpha и Ghost"]
        )
        result = execute_plan(plan, db_session)
        assert result["status"] == "rolled_back"
        assert db_session.query(Entity).count() == 0
        assert db_session.query(Link).count() == 0
        statuses = {s["id"]: s["status"] for s in result["steps"]}
        # s4 не зависит от s3 (Kahn выполняет его раньше), поэтому s3 остаётся pending
        assert statuses == {
            "s1": "rolled_back",
            "s2": "rolled_back",
            "s3": "pending",
            "s4": "failed",
        }

    def test_failed_step_records_error(self, db_session):
        plan = generate_plan(["удалить Ghost"])
        result = execute_plan(plan, db_session)
        assert result["status"] == "failed"
        assert "не найдена" in (result["error"] or "")

    def test_cycle_plan_is_invalid(self, db_session):
        plan = Plan(
            goal="t",
            steps=[
                PlanStep(id="s1", action="create", params={}, depends_on=["s2"]),
                PlanStep(id="s2", action="create", params={}, depends_on=["s1"]),
            ],
        )
        result = execute_plan(plan, db_session)
        assert result["status"] == "invalid"

    def test_custom_executor_used(self, db_session):
        calls = []

        def executor(params, db):
            calls.append(params.get("action"))
            return {"ok": True, "action": params.get("action")}

        plan = generate_plan(["создать Alpha", "создать Beta"])
        result = execute_plan(plan, db_session, executor=executor)
        assert result["status"] == "completed"
        assert calls == ["create", "create"]


@pytest.fixture()
def parallel_env(tmp_path):
    """Файловая SQLite БД: у каждой сессии своё соединение (без гонок StaticPool)."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'plan.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield factory
    engine.dispose()


class TestExecuteParallel:
    def test_parallel_requires_session_factory(self, db_session):
        plan = generate_plan(["создать Alpha"])
        with pytest.raises(ValueError):
            execute_plan(plan, db_session, parallel=True)

    def test_parallel_happy_path(self, parallel_env):
        plan = generate_plan(["создать Alpha", "создать Beta", "связать Alpha и Beta"])
        result = execute_plan(
            plan, parallel_env(), parallel=True, session_factory=parallel_env
        )
        assert result["status"] == "completed"
        check = parallel_env()
        names = {e.name for e in check.query(Entity).all()}
        assert names == {"alpha", "beta"}
        assert check.query(Link).count() == 1

    def test_parallel_failure_rolls_back(self, parallel_env):
        plan = generate_plan(["создать Alpha", "связать Alpha и Ghost"])
        db = parallel_env()
        result = execute_plan(plan, db, parallel=True, session_factory=parallel_env)
        assert result["status"] == "rolled_back"
        assert db.query(Entity).count() == 0


class TestPlannerAgent:
    def test_plan_returns_validation_report(self):
        agent = PlannerAgent()
        report = agent.plan(["создать Alpha", "связать Alpha и Beta"], goal="g")
        # Beta не создана → шаг link зависимостей не имеет, но план валиден
        assert report["valid"] is True
        assert report["problems"] == []
        assert report["plan"]["goal"] == "g"

    def test_plan_reports_problems(self):
        agent = PlannerAgent()
        report = agent.plan(["несуществующее действие"])  # unknown action
        assert report["valid"] is False
        assert report["problems"]

    def test_run_executes_plan(self, db_session, session_factory):
        agent = PlannerAgent()
        result = agent.run(
            ["создать Alpha", "создать Beta", "связать Alpha и Beta"],
            db_session,
            session_factory=session_factory,
        )
        assert result["status"] == "completed"
        assert db_session.query(Entity).count() == 2

    def test_run_rejects_invalid_plan(self, db_session):
        agent = PlannerAgent()
        result = agent.run(["неведомая команда"], db_session)
        assert result["status"] == "invalid"
        assert db_session.query(Entity).count() == 0
