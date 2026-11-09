"""
Issue #12: парсинг всех 12 типов намерений + issue #6: unit-тесты rules.py.
"""

from __future__ import annotations

import pytest

from core.symbio_core import SUPPORTED_ACTIONS, interpret_intent


class TestOriginalIntents:
    """Исходные 4+1 действий сохраняют поведение."""

    def test_create(self):
        result = interpret_intent("создать Проект Адаптация")
        assert result["action"] == "create"
        assert result["entity"] == "проект адаптация"

    def test_link(self):
        result = interpret_intent("связать Проект и Задача")
        assert result["action"] == "link"
        assert result["entities"] == ["проект", "задача"]

    def test_delete(self):
        result = interpret_intent("удалить Грядка")
        assert result["action"] == "delete"
        assert result["entity"] == "грядка"

    def test_query_variants(self):
        for text in ("найти X", "показать X", "что такое X"):
            result = interpret_intent(text)
            assert result["action"] == "query"
            assert result["entity"] == "x"

    def test_evolve(self):
        result = interpret_intent("эволюция Проект")
        assert result["action"] == "evolve"
        assert result["entity"] == "проект"


class TestTransformIntent:
    def test_rename_v(self):
        result = interpret_intent("переименовать проект в стартап")
        assert result["action"] == "transform"
        assert result["entity"] == "проект"
        assert result["to"] == "стартап"

    def test_change_na(self):
        result = interpret_intent("изменить грядку на огород")
        assert result["action"] == "transform"
        assert result["entity"] == "грядку"
        assert result["to"] == "огород"

    def test_priority_not_confused_with_transform(self):
        result = interpret_intent("изменить приоритет проекта на высокий")
        assert result["action"] == "prioritize"
        assert result["entity"] == "проекта"
        assert result["priority"] == "high"


class TestCloneIntent:
    def test_clone(self):
        result = interpret_intent("клонировать Проект")
        assert result["action"] == "clone"
        assert result["entity"] == "проект"

    def test_duplicate_synonym(self):
        result = interpret_intent("дублировать Грядка")
        assert result["action"] == "clone"

    def test_copy_synonym(self):
        result = interpret_intent("скопировать отчёт")
        assert result["action"] == "clone"
        assert result["entity"] == "отчёт"


class TestMergeIntent:
    def test_merge(self):
        result = interpret_intent("объединить проект и задача")
        assert result["action"] == "merge"
        assert result["entities"] == ["проект", "задача"]

    def test_merge_with_spaces(self):
        result = interpret_intent("объединить  Проект А  и  Задача Б ")
        assert result["action"] == "merge"
        assert result["entities"] == ["проект а", "задача б"]


class TestTagIntent:
    def test_add_tag_k(self):
        result = interpret_intent("добавить тег срочно к проект")
        assert result["action"] == "tag"
        assert result["tag"] == "срочно"
        assert result["entity"] == "проект"

    def test_add_tag_for(self):
        result = interpret_intent("добавить тег важный для огород")
        assert result["action"] == "tag"
        assert result["tag"] == "важный"
        assert result["entity"] == "огород"

    def test_mark_tagom(self):
        result = interpret_intent("пометить проект тегом альфа")
        assert result["action"] == "tag"
        assert result["entity"] == "проект"
        assert result["tag"] == "альфа"

    def test_tag_for_form(self):
        result = interpret_intent("тег бета для задачи")
        assert result["action"] == "tag"
        assert result["tag"] == "бета"
        assert result["entity"] == "задачи"


class TestPrioritizeIntent:
    def test_prioritize_set_high(self):
        result = interpret_intent("изменить приоритет проекта на высокий")
        assert result["action"] == "prioritize"
        assert result["priority"] == "high"

    def test_prioritize_direct(self):
        result = interpret_intent("приоритет грядка низкий")
        assert result["action"] == "prioritize"
        assert result["priority"] == "low"

    def test_prioritize_with_na(self):
        result = interpret_intent("приоритет проект на средний")
        assert result["action"] == "prioritize"
        assert result["priority"] == "medium"

    def test_raise_priority(self):
        result = interpret_intent("повысить приоритет проект")
        assert result["action"] == "prioritize"
        assert result["priority"] == "high"
        assert result["entity"] == "проект"

    def test_lower_priority(self):
        result = interpret_intent("понизить приоритет проект")
        assert result["action"] == "prioritize"
        assert result["priority"] == "low"

    def test_english_aliases(self):
        result = interpret_intent("приоритет проект max")
        assert result["priority"] == "high"


class TestScheduleIntent:
    def test_schedule(self):
        result = interpret_intent("запланировать полив на завтра")
        assert result["action"] == "schedule"
        assert result["task"] == "полив"
        assert result["when"] == "завтра"

    def test_schedule_imperative(self):
        result = interpret_intent("запланируй ревизию на 12:00")
        assert result["action"] == "schedule"
        assert result["task"] == "ревизию"
        assert result["when"] == "12:00"


class TestAnalyzeIntent:
    def test_analyze_graph(self):
        result = interpret_intent("проанализировать граф")
        assert result["action"] == "analyze"
        assert result["target"] == "graph"

    def test_analyze_entity(self):
        result = interpret_intent("проанализировать проект")
        assert result["action"] == "analyze"
        assert result["target"] == "проект"

    def test_analyze_noun(self):
        result = interpret_intent("анализ графа")
        assert result["action"] == "analyze"
        assert result["target"] == "graph"


class TestConfidencePresence:
    """Issue #11: каждый результат парсинга содержит confidence и route."""

    def test_all_actions_have_confidence(self):
        samples = [
            "создать X", "связать X и Y", "удалить X", "найти X",
            "эволюция X", "переименовать X в Y", "клонировать X",
            "объединить X и Y", "добавить тег T к X", "приоритет X высокий",
            "запланировать X на завтра", "проанализировать граф",
        ]
        for text in samples:
            result = interpret_intent(text)
            assert 0.0 <= result["confidence"] <= 1.0, text
            assert result["confidence"] > 0.5, text

    def test_unknown_zero_confidence(self):
        result = interpret_intent("какой сегодня день")
        assert result["action"] == "unknown"
        assert result["confidence"] == 0.0

    def test_incomplete_pattern_lower_confidence(self):
        complete = interpret_intent("переименовать проект в стартап")
        assert complete["confidence"] >= 0.8

    def test_supported_actions_count(self):
        # create, link, delete, query, evolve + 7 новых = 12
        assert len(SUPPORTED_ACTIONS) == 12


class TestEdgeCases:
    def test_empty(self):
        result = interpret_intent("")
        assert result["action"] == "unknown"
        assert "error" in result

    def test_none(self):
        result = interpret_intent(None)
        assert result["action"] == "unknown"
        assert "error" in result

    def test_unknown_keeps_raw(self):
        result = interpret_intent("какой сегодня день")
        assert result["raw"] == "какой сегодня день"

    def test_case_insensitive(self):
        result = interpret_intent("СОЗДАТЬ ПРОЕКТ")
        assert result["action"] == "create"
        assert result["entity"] == "проект"

    def test_schedule_without_when_is_unknown(self):
        result = interpret_intent("запланировать полив")
        assert result["action"] == "unknown"
