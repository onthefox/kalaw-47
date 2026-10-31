"""
Tests for SymbioCore - Intent Parsing

Covers:
- Create entity parsing
- Link entities parsing
- Delete entity parsing
- Query entity parsing
- Empty input handling
- Unknown intent handling
"""

import pytest
from core.symbio_core.rules import interpret_intent


class TestCreateIntent:
    """Tests for 'создать' (create) action parsing."""

    def test_create_simple_entity(self):
        """Test parsing 'создать X' command."""
        result = interpret_intent("создать Проект Адаптация")
        assert result["action"] == "create"
        assert result["entity"] == "проект адаптация"

    def test_create_single_word(self):
        """Test parsing single word entity name."""
        result = interpret_intent("создать Грядка")
        assert result["action"] == "create"
        assert result["entity"] == "грядка"

    def test_create_with_extra_spaces(self):
        """Test parsing with extra whitespace."""
        result = interpret_intent("  создать   Проект X  ")
        assert result["action"] == "create"
        assert result["entity"] == "проект x"


class TestLinkIntent:
    """Tests for 'связать' (link) action parsing."""

    def test_link_two_entities(self):
        """Test parsing 'связать X и Y' command."""
        result = interpret_intent("связать SymbioSystem и piZdabolot")
        assert result["action"] == "link"
        assert len(result["entities"]) == 2
        assert result["entities"][0] == "symbiosystem"
        assert result["entities"][1] == "pizdabolot"

    def test_link_lowercase(self):
        """Test parsing lowercase link command."""
        result = interpret_intent("связать проект и задача")
        assert result["action"] == "link"
        assert result["entities"] == ["проект", "задача"]


class TestDeleteIntent:
    """Tests for 'удалить' (delete) action parsing."""

    def test_delete_entity(self):
        """Test parsing 'удалить X' command."""
        result = interpret_intent("удалить Проект Адаптация")
        assert result["action"] == "delete"
        assert result["entity"] == "проект адаптация"

    def test_delete_single_word(self):
        """Test deleting single word entity."""
        result = interpret_intent("удалить Грядка")
        assert result["action"] == "delete"
        assert result["entity"] == "грядка"


class TestQueryIntent:
    """Tests for query actions (найти, показать, что такое)."""

    def test_find_entity(self):
        """Test parsing 'найти X' command."""
        result = interpret_intent("найти Проект Адаптация")
        assert result["action"] == "query"
        assert result["entity"] == "проект адаптация"

    def test_show_entity(self):
        """Test parsing 'показать X' command."""
        result = interpret_intent("показать Грядка")
        assert result["action"] == "query"
        assert result["entity"] == "грядка"

    def test_what_is_entity(self):
        """Test parsing 'что такое X' command."""
        result = interpret_intent("что такое SymbioSystem")
        assert result["action"] == "query"
        assert result["entity"] == "symbiosystem"


class TestEvolveIntent:
    """Tests for evolution actions (эволюция, расширить, развить)."""

    def test_evolve_entity(self):
        """Test parsing 'эволюция X' command."""
        result = interpret_intent("эволюция Проект Адаптация")
        assert result["action"] == "evolve"
        assert result["entity"] == "проект адаптация"

    def test_expand_entity(self):
        """Test parsing 'расширить X' command."""
        result = interpret_intent("расширить Онтология")
        assert result["action"] == "evolve"
        assert result["entity"] == "онтология"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_input(self):
        """Test handling empty string."""
        result = interpret_intent("")
        assert result["action"] == "unknown"
        assert "error" in result

    def test_whitespace_only(self):
        """Test handling whitespace-only string."""
        result = interpret_intent("   ")
        assert result["action"] == "unknown"
        assert "error" in result

    def test_none_input(self):
        """Test handling None input."""
        result = interpret_intent(None)
        assert result["action"] == "unknown"
        assert "error" in result

    def test_unknown_intent(self):
        """Test handling unknown command."""
        result = interpret_intent("какой сегодня день")
        assert result["action"] == "unknown"
        assert result["raw"] == "какой сегодня день"

    def test_case_insensitive(self):
        """Test that parsing is case-insensitive."""
        result1 = interpret_intent("СОЗДАТЬ ПРОЕКТ")
        result2 = interpret_intent("создать проект")
        assert result1["action"] == result2["action"]
        assert result1["entity"] == result2["entity"]
