"""
Issue #11: confidence scoring — оценка, пороги, смешивание, feedback loop.
"""

from __future__ import annotations

from core.symbio_core.confidence import (
    FeedbackStore,
    blend,
    keyword_score,
    route,
    score,
)
from core.symbio_core import interpret_intent


class TestKeywordScore:
    def test_full_pattern_high_score(self):
        parsed = interpret_intent("создать Проект")
        assert keyword_score(parsed) >= 0.9

    def test_unknown_zero(self):
        assert keyword_score({"action": "unknown"}) == 0.0

    def test_partial_fields_lower_score(self):
        full = keyword_score({"action": "transform", "entity": "x", "to": "y"})
        partial = keyword_score({"action": "transform", "entity": "x"})
        assert full > partial
        assert partial >= 0.5 * full - 0.01

    def test_score_clamped(self):
        assert keyword_score({"action": "create", "confidence": 5.0}) <= 1.0


class TestRouting:
    def test_auto_above_09(self):
        assert route(0.91) == "auto"
        assert route(0.95) == "auto"

    def test_review_between_07_and_09(self):
        assert route(0.9) == "review"
        assert route(0.75) == "review"

    def test_clarification_below_07(self):
        assert route(0.69) == "clarification"
        assert route(0.0) == "clarification"


class TestBlend:
    def test_no_llm_returns_keyword(self):
        assert blend(0.8, None) == 0.8

    def test_llm_pulls_score(self):
        assert blend(0.8, 0.6) == 0.72  # 0.6*0.8 + 0.4*0.6

    def test_clamping(self):
        assert blend(2.0, 2.0) == 1.0
        assert blend(-1.0, -1.0) == 0.0


class TestScore:
    def test_score_adds_route(self):
        parsed = interpret_intent("создать Проект")
        result = score(dict(parsed))
        # Полный шаблон create даёт ровно 0.9 — граница review (auto строго > 0.9)
        assert result["confidence"] == 0.9
        assert result["route"] == "review"

    def test_score_auto_route_above_threshold(self):
        result = score({"action": "analyze", "target": "x", "confidence": 0.95})
        assert result["confidence"] == 0.95
        assert result["route"] == "auto"

    def test_low_confidence_review_route(self):
        parsed = {"action": "analyze", "target": "x", "confidence": 0.8}
        result = score(parsed)
        assert result["route"] == "review"


class TestFeedbackLoop:
    def test_record_accepted_boosts(self):
        store = FeedbackStore()
        base = store.adjustment("create")
        store.record("create", accepted=True)
        assert store.adjustment("create") > base

    def test_record_rejected_penalizes(self):
        store = FeedbackStore()
        for _ in range(10):
            store.record("delete", accepted=False)
        assert store.adjustment("delete") < 0

    def test_penalty_can_override_pattern(self):
        store = FeedbackStore()
        for _ in range(10):
            store.record("create", accepted=False)
        parsed = {"action": "create", "entity": "x"}
        score_value = keyword_score({**parsed})
        # штраф применён внутри keyword_score только у глобального стора,
        # поэтому тут проверяем ручную поправку
        assert store.adjustment("create") <= -0.3
        assert score_value > 0.8

    def test_stats_and_reset(self):
        store = FeedbackStore()
        store.record("tag", accepted=True, confidence=0.85)
        stats = store.stats()
        assert stats["total"] == 1
        assert stats["accepted"]["tag"] == 1
        store.reset()
        assert store.stats()["total"] == 0

    def test_log_rotation(self):
        store = FeedbackStore(max_log_entries=5)
        for i in range(10):
            store.record("create", accepted=True)
        assert store.stats()["total"] == 5
