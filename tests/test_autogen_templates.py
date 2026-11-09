"""
Issue #20: автогенерация модулей — 5 шаблонов, валидация синтаксиса, регистрация.
"""

from __future__ import annotations

import ast
import time

import pytest

from core.symbio_hive import hive
from engine.autogen.templates import (
    TEMPLATE_TYPES,
    TEMPLATES,
    generate_module,
    render_template,
    validate_syntax,
)


class TestTemplateCatalog:
    def test_five_template_types(self):
        assert TEMPLATE_TYPES == (
            "python_module",
            "react_component",
            "api_endpoint",
            "test",
            "docs",
        )
        assert set(TEMPLATES) == set(TEMPLATE_TYPES)

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError):
            render_template("cobol_module", "X")


class TestPythonModuleTemplate:
    def test_renders_valid_python(self):
        rendered = render_template("python_module", "User Service", "service", ["os"])
        assert rendered["filename"] == "user_service.py"
        assert rendered["language"] == "python"
        ast.parse(rendered["content"])  # не бросает

    def test_contains_class_and_imports(self):
        rendered = render_template("python_module", "UserService", "service", ["os", "sys"])
        assert "class UserService:" in rendered["content"]
        assert "import os" in rendered["content"]
        assert "import sys" in rendered["content"]
        assert '__all__ = ["UserService"]' in rendered["content"]

    def test_name_variables_substituted(self):
        # Кириллическое имя без латиницы → fallback-имя класса Component
        rendered = render_template("python_module", "Парсер", "parser")
        assert "class Component:" in rendered["content"]
        assert 'name: str = "Парсер"' in rendered["content"]
        assert '"type": "parser"' in rendered["content"]


class TestReactComponentTemplate:
    def test_renders_jsx_with_pascal_case(self):
        rendered = render_template("react_component", "user card", "ui")
        assert rendered["filename"] == "UserCard.jsx"
        assert rendered["language"] == "jsx"
        assert "import React from 'react';" in rendered["content"]
        assert "export default UserCard;" in rendered["content"]

    def test_aria_attributes_present(self):
        rendered = render_template("react_component", "Карточка", "ui")
        assert 'role="region"' in rendered["content"]
        assert "aria-label=" in rendered["content"]

    def test_dependencies_imported(self):
        rendered = render_template("react_component", "Card", "ui", ["prop-types"])
        assert "import prop-types from 'prop-types';" in rendered["content"]

    def test_empty_state_branch(self):
        rendered = render_template("react_component", "Card", "ui")
        assert "items.length === 0" in rendered["content"]
        assert "Нет данных" in rendered["content"]


class TestApiEndpointTemplate:
    def test_renders_router_and_model(self):
        rendered = render_template("api_endpoint", "user profile", "api")
        assert rendered["filename"] == "endpoint_user_profile.py"
        ast.parse(rendered["content"])
        assert "APIRouter(prefix=\"/user_profile\"" in rendered["content"]
        assert "class UserProfileRouterItem(BaseModel):" in rendered["content"]

    def test_digit_leading_name_gets_router_prefix(self):
        rendered = render_template("api_endpoint", "42lab", "api")
        assert "class Router42LabRouterItem(BaseModel):" in rendered["content"]

    def test_get_and_post_handlers(self):
        rendered = render_template("api_endpoint", "items", "api")
        content = rendered["content"]
        assert "def list_items():" in content
        assert "def create_item(item:" in content
        assert "HTTPException" in content


class TestTestTemplate:
    def test_renders_valid_pytest(self):
        rendered = render_template("test", "user service", "service")
        assert rendered["filename"] == "test_user_service.py"
        ast.parse(rendered["content"])
        assert "import pytest" in rendered["content"]
        assert "def test_user_service_describe():" in rendered["content"]


class TestDocsTemplate:
    def test_renders_markdown_with_heading_and_table(self):
        rendered = render_template("docs", "User Service", "service", ["os"])
        assert rendered["filename"] == "docs/user_service.md"
        assert rendered["language"] == "markdown"
        assert rendered["content"].startswith("# User Service")
        assert "- **Тип**: service" in rendered["content"]
        assert "`os`" in rendered["content"]

    def test_no_dependencies_shows_net(self):
        rendered = render_template("docs", "X", "service")
        assert "**Зависимости**: нет" in rendered["content"]


class TestValidateSyntax:
    def test_valid_python(self):
        ok, err = validate_syntax("m.py", "x = 1\n")
        assert ok and err == ""

    def test_invalid_python(self):
        ok, err = validate_syntax("m.py", "def broken(:\n")
        assert not ok
        assert "Синтаксическая ошибка Python" in err

    def test_valid_jsx(self):
        rendered = render_template("react_component", "Card", "ui")
        ok, err = validate_syntax(rendered["filename"], rendered["content"])
        assert ok, err

    def test_unclosed_brace_rejected(self):
        ok, err = validate_syntax("c.jsx", "const a = () => {\n  return x;\n")
        assert not ok
        assert "Незакрытая скобка" in err

    def test_mismatched_bracket_rejected(self):
        ok, err = validate_syntax("c.jsx", "const a = (];")
        assert not ok
        assert "Несбалансированная скобка" in err

    def test_valid_markdown(self):
        ok, _ = validate_syntax("d.md", "# Заголовок\n\nТекст\n")
        assert ok

    def test_markdown_without_heading_rejected(self):
        ok, err = validate_syntax("d.md", "просто текст")
        assert not ok
        assert "заголовка" in err

    def test_empty_markdown_rejected(self):
        ok, err = validate_syntax("d.md", "   \n")
        assert not ok

    def test_unknown_extension(self):
        ok, err = validate_syntax("f.rs", "fn main() {}")
        assert not ok
        assert "Неизвестный тип файла" in err


class TestGenerateModule:
    def test_generates_and_registers_in_hive(self):
        hive.reset()
        result = generate_module("python_module", "Планировщик", type_="service")
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["elapsed_ms"] < 5000
        assert result["entity"]["name"] == "Планировщик"
        meta = result["entity"]["meta"]
        assert meta["autogen"] is True
        assert meta["template"] == "python_module"
        assert meta["files"] == ["планировщик.py"]
        hive.reset()

    def test_generation_is_fast(self):
        start = time.perf_counter()
        generate_module("react_component", "Card")
        assert (time.perf_counter() - start) < 5.0

    def test_all_five_templates_generate_valid_files(self):
        for template_type in TEMPLATE_TYPES:
            result = generate_module(template_type, "Модуль")
            assert result["valid"], f"{template_type}: {result['errors']}"
            assert result["files"], template_type

    def test_unknown_template_reports_error(self):
        result = generate_module("nope", "X")
        assert result["valid"] is False
        assert result["files"] == []
        assert "Неизвестный шаблон" in result["errors"][0]

    def test_registers_in_db_when_provided(self, db_session):
        result = generate_module("python_module", "DbModule", db=db_session)
        assert result["valid"] is True
        from backend.models import Entity

        entity = db_session.query(Entity).filter_by(name="DbModule").one()
        assert '"autogen": true' in (entity.meta or "").lower() or "autogen" in (entity.meta or "")

    def test_invalid_registration_skipped_for_unknown(self):
        hive.reset()
        result = generate_module("nope", "X")
        assert result["entity"] is None
        assert hive.get_entities() == []
        hive.reset()
