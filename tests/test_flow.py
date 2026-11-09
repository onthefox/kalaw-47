"""
Issues #9/#10/#11 (интеграция): SymbioFlow — контекст сессий, уверенность,
LLM fallback и уточняющие вопросы в полном пайплайне.
"""

from __future__ import annotations

import pytest

from backend.models import Entity
from core.symbio_core.confidence import feedback_store
from core.symbio_core.context import ContextMemory
from engine.symbio_flow.flow import handle_intent, record_feedback
from tests.test_llm import FakeProvider
from engine.llm.chain import LLMChain
from engine.llm.rate_limit import RateLimiter


@pytest.fixture()
def memory():
    return ContextMemory()


class TestBasicExecution:
    def test_create_entity_full_pipeline(self, db_session, memory):
        result = handle_intent("создать ноутбук", db_session, session_id="s1", context_memory=memory)
        assert result["action"] == "create"
        assert result["created"]["name"] == "ноутбук"
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["route"] in ("auto", "review")
        assert result["intent_id"]
        assert result["session_id"] == "s1"
        assert "review_required" in result

    def test_unknown_intent_asks_clarification(self, db_session, memory):
        result = handle_intent("абракадабра бимбим", db_session, session_id="s1", context_memory=memory)
        assert result["needs_clarification"] is True
        assert "Уточните" in result["question"]
        assert result["confidence"] == 0.0

    def test_context_stored_after_create(self, db_session, memory):
        handle_intent("создать монитор", db_session, session_id="sess", context_memory=memory)
        last = memory.last_entity("sess")
        assert last == "монитор"

    def test_publishes_intent_processed_event(self, db_session, memory):
        from engine.observer import observer as global_observer

        handle_intent("создать Стол", db_session, session_id="s", context_memory=memory)
        entries = global_observer.get_log(event_type="intent.processed")
        assert len(entries) == 1
        assert entries[0]["data"]["action"] == "create"


class TestSessionContext:
    def test_pronoun_resolves_to_last_entity(self, db_session, memory):
        handle_intent("создать принтер", db_session, session_id="sess", context_memory=memory)
        result = handle_intent("удалить его", db_session, session_id="sess", context_memory=memory)
        assert result["action"] == "delete"
        assert result["deleted"] == "принтер"

    def test_different_sessions_isolated(self, db_session, memory):
        handle_intent("создать кресло", db_session, session_id="a", context_memory=memory)
        result = handle_intent("удалить его", db_session, session_id="b", context_memory=memory)
        assert result.get("needs_clarification") is True

    def test_unresolved_reference_asks_clarification(self, db_session, memory):
        result = handle_intent("удалить его", db_session, session_id="fresh", context_memory=memory)
        assert result["action"] == "clarification"
        assert result["needs_clarification"] is True
        assert "его" in result["question"]

    def test_use_context_false_skips_resolution(self, db_session, memory):
        handle_intent("создать Шкаф", db_session, session_id="s", context_memory=memory)
        result = handle_intent(
            "найти его", db_session, session_id="s", use_context=False, context_memory=memory
        )
        # без контекста "найти его" ищет сущность "его" → её нет, но это query, не clarification
        assert result["action"] == "query"


class TestConfidenceRouting:
    def test_confidence_present_in_all_responses(self, db_session, memory):
        for text in ("создать X", "найди X", "бред", "удалить его"):
            result = handle_intent(text, db_session, session_id="c", context_memory=memory)
            assert "confidence" in result, text

    def test_accepted_feedback_boosts_to_auto(self, db_session, memory):
        # create = 0.90 (review); одно подтверждение даёт бонус +0.01 → 0.91 (auto)
        record_feedback("i0", "create", accepted=True)
        result = handle_intent("создать дверь", db_session, session_id="r", context_memory=memory)
        assert result["route"] == "auto"
        assert result["review_required"] is False

    def test_create_without_feedback_is_review(self, db_session, memory):
        result = handle_intent("создать окно", db_session, session_id="r", context_memory=memory)
        assert result["route"] == "review"

    def test_clarification_route_for_weak_intent(self, db_session, memory):
        result = handle_intent("абракадабра", db_session, session_id="r", context_memory=memory)
        assert result["needs_clarification"] is True

    def test_feedback_loop_updates_stats(self, db_session, memory):
        handle_intent("создать ключ", db_session, session_id="f", context_memory=memory)
        entry = record_feedback("intent-1", "create", accepted=True)
        assert entry["accepted"] is True
        stats = feedback_store.stats()
        assert stats["total"] == 1
        assert stats["accepted"]["create"] == 1


class TestLLMFallback:
    def test_llm_adopted_when_rules_unknown(self, db_session, memory):
        fake = FakeProvider(
            response={"action": "schedule", "task": "встреча", "when": "завтра", "probability": 0.95}
        )
        chain = LLMChain(providers=[fake], rate_limiter=RateLimiter(max_calls=10))
        result = handle_intent(
            "назначь встречу на завтра",
            db_session,
            session_id="llm",
            use_context=False,
            context_memory=memory,
            llm_chain=chain,
        )
        assert fake.calls  # LLM вызывался
        assert result["action"] == "schedule"
        assert result["scheduled"]["schedule"]["task"] == "встреча"
        assert result["llm_provider"] == "fake"

    def test_no_llm_providers_still_works(self, db_session, memory):
        chain = LLMChain(providers=[])
        result = handle_intent(
            "создать Ящик",
            db_session,
            session_id="s",
            use_context=False,
            context_memory=memory,
            llm_chain=chain,
        )
        assert result["action"] == "create"
        assert "llm_provider" not in result

    def test_llm_error_falls_back_to_rules(self, db_session, memory):
        broken = FakeProvider(fail=RuntimeError("api down"))
        chain = LLMChain(providers=[broken], rate_limiter=RateLimiter(max_calls=10))
        result = handle_intent(
            "создать Полку",
            db_session,
            session_id="s",
            use_context=False,
            context_memory=memory,
            llm_chain=chain,
        )
        assert result["action"] == "create"
        assert "llm_provider" not in result


class TestFlowWithDB:
    def test_link_after_two_creates(self, db_session, memory):
        handle_intent("создать роутер", db_session, session_id="n", context_memory=memory)
        handle_intent("создать компьютер", db_session, session_id="n", context_memory=memory)
        result = handle_intent("связать роутер и компьютер", db_session, session_id="n", context_memory=memory)
        assert result["action"] == "link"
        assert result["created"]["source"] == "роутер"
        assert result["created"]["target"] == "компьютер"
        assert db_session.query(Entity).count() == 2

    def test_delete_removes_entity(self, db_session, memory):
        handle_intent("создать ваза", db_session, session_id="d", context_memory=memory)
        result = handle_intent("удалить ваза", db_session, session_id="d", context_memory=memory)
        assert result["deleted"] == "ваза"
        assert db_session.query(Entity).count() == 0
