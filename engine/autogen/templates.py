"""
Шаблоны модулей Autogen (issue #20).

5 шаблонов: python module, React component, API endpoint, test, docs.
Переменные: name, type, dependencies. Каждый шаблон выдаёт файлы
с корректными импортами; синтаксис проверяется перед выдачей.
Сгенерированный модуль регистрируется в Hive (Entity с meta.autogen).
"""

from __future__ import annotations

import ast
import json
import re
import time
from typing import Any

TEMPLATE_TYPES = (
    "python_module",
    "react_component",
    "api_endpoint",
    "test",
    "docs",
)


def _snake_case(name: str) -> str:
    value = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip()
    value = re.sub(r"[\s-]+", "_", value)
    return value.lower() or "module"


def _pascal_case(name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if not parts:
        return "Component"
    return "".join(p[:1].upper() + p[1:] for p in parts)


# --- Шаблоны ---


def _tpl_python_module(name: str, type_: str, dependencies: list[str]) -> dict[str, Any]:
    snake = _snake_case(name)
    pascal = _pascal_case(name)
    imports = "\n".join(f"import {dep}" for dep in dependencies)
    import_block = f"\n{imports}\n" if dependencies else ""
    content = f'''"""Автосгенерированный модуль {name} (тип: {type_})."""

{import_block}
class {pascal}:
    """{type_}: {name}."""

    def __init__(self, name: str = "{name}") -> None:
        self.name = name

    def describe(self) -> dict:
        return {{"name": self.name, "type": "{type_}"}}


__all__ = ["{pascal}"]
'''
    return {"filename": f"{snake}.py", "content": content, "language": "python"}


def _tpl_react_component(name: str, type_: str, dependencies: list[str]) -> dict[str, Any]:
    pascal = _pascal_case(name)
    extra_imports = "\n".join(f"import {dep} from '{dep}';" for dep in dependencies)
    extra_block = f"\n{extra_imports}\n" if dependencies else ""
    content = f'''import React from 'react';
{extra_block}
const {pascal} = ({{ title = '{name}', items = [] }}) => (
  <section className="{_snake_case(name)}" role="region" aria-label={{title}}>
    <h2>{{title}}</h2>
    {{items.length === 0 ? (
      <p>Нет данных</p>
    ) : (
      <ul>
        {{items.map((item) => (
          <li key={{String(item.id ?? item)}}>{{String(item.name ?? item)}}</li>
        ))}}
      </ul>
    )}}
  </section>
);

export default {pascal};
'''
    return {"filename": f"{pascal}.jsx", "content": content, "language": "jsx"}


def _tpl_api_endpoint(name: str, type_: str, dependencies: list[str]) -> dict[str, Any]:
    snake = _snake_case(name)
    router = f"{snake}_router"
    model_name = f"{router.title().replace('_', '')}Item"
    if model_name[0].isdigit():
        model_name = f"Router{model_name}"
    content = f'''\"\"\"Автосгенерированный API endpoint для {name}.\"\"\"

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


{router} = APIRouter(prefix="/{snake}", tags=["{name}"])


class {model_name}(BaseModel):
    """Элемент {name}."""
    id: int | None = None
    name: str


_ITEMS: dict[int, dict] = {{}}
_NEXT_ID = 1


@{router}.get("")
def list_items():
    """Список элементов."""
    return {{"items": list(_ITEMS.values()), "total": len(_ITEMS)}}


@{router}.post("")
def create_item(item: {model_name}):
    """Создать элемент."""
    global _NEXT_ID
    if not item.name.strip():
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    record = {{"id": _NEXT_ID, "name": item.name}}
    _ITEMS[_NEXT_ID] = record
    _NEXT_ID += 1
    return {{"created": record}}
'''
    return {"filename": f"endpoint_{snake}.py", "content": content, "language": "python"}


def _tpl_test(name: str, type_: str, dependencies: list[str]) -> dict[str, Any]:
    snake = _snake_case(name)
    pascal = _pascal_case(name)
    content = f'''\"\"\"Автосгенерированные тесты для {name}.\"\"\"

import pytest


def test_{snake}_describe():
    from {snake} import {pascal}

    instance = {pascal}()
    assert instance.describe() == {{"name": "{name}", "type": "{type_}"}}
'''
    return {"filename": f"test_{snake}.py", "content": content, "language": "python"}


def _tpl_docs(name: str, type_: str, dependencies: list[str]) -> dict[str, Any]:
    snake = _snake_case(name)
    deps = ", ".join(f"`{d}`" for d in dependencies) if dependencies else "нет"
    content = f'''# {name}

Автосгенерированная документация.

- **Тип**: {type_}
- **Зависимости**: {deps}

## Использование

```bash
python -c "from symbio import {snake}"
```

## Переменные шаблона

| Переменная | Значение |
|-----------|----------|
| name | {name} |
| type | {type_} |
| dependencies | {deps} |
'''
    return {"filename": f"docs/{snake}.md", "content": content, "language": "markdown"}


TEMPLATES = {
    "python_module": _tpl_python_module,
    "react_component": _tpl_react_component,
    "api_endpoint": _tpl_api_endpoint,
    "test": _tpl_test,
    "docs": _tpl_docs,
}


# --- Валидация синтаксиса ---


def _check_balanced(content: str) -> tuple[bool, str]:
    """Лёгкая проверка баланса скобок и кавычек для JS/JSX."""
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_line_comment = False
    quote: str | None = None
    escaped = False
    for line_no, line in enumerate(content.splitlines(), start=1):
        in_line_comment = False
        for ch in line:
            if in_line_comment:
                continue
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch == "/" and line.lstrip().startswith("//"):
                in_line_comment = True
                continue
            if ch in "\"'`":
                quote = ch
                continue
            if ch in "([{":
                stack.append((ch, line_no))
            elif ch in ")]}":
                if not stack or stack[-1][0] != pairs[ch]:
                    return False, f"Несбалансированная скобка '{ch}' на строке {line_no}"
                stack.pop()
    if quote:
        return False, "Незакрытая строка (кавычка)"
    if stack:
        return False, f"Незакрытая скобка '{stack[-1][0]}' со строки {stack[-1][1]}"
    return True, ""


def validate_syntax(filename: str, content: str) -> tuple[bool, str]:
    """Проверить синтаксис файла.

    Python → полный разбор через ast; JS/JSX → проверка баланса скобок и
    кавычек (без внешних парсеров); Markdown → непустой документ с заголовком.
    """
    lower = filename.lower()
    if lower.endswith(".py"):
        try:
            ast.parse(content)
            return True, ""
        except SyntaxError as exc:
            return False, f"Синтаксическая ошибка Python: {exc.msg} (строка {exc.lineno})"
    if lower.endswith((".jsx", ".js")):
        return _check_balanced(content)
    if lower.endswith(".md"):
        if not content.strip():
            return False, "Пустая документация"
        if not content.lstrip().startswith("#"):
            return False, "Документация должна начинаться с заголовка"
        return True, ""
    return False, f"Неизвестный тип файла: {filename}"


# --- Генерация и регистрация ---


def render_template(
    template_type: str,
    name: str,
    type_: str = "service",
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    """Отрисовать шаблон без регистрации. Бросает ValueError при неизвестном типе."""
    if template_type not in TEMPLATES:
        raise ValueError(
            f"Неизвестный шаблон '{template_type}'. Доступно: {', '.join(TEMPLATE_TYPES)}"
        )
    return TEMPLATES[template_type](name, type_, list(dependencies or []))


def generate_module(
    template_type: str,
    name: str,
    db=None,
    type_: str = "service",
    dependencies: list[str] | None = None,
    register: bool = True,
) -> dict[str, Any]:
    """Сгенерировать модуль: рендер + проверка синтаксиса + регистрация в Hive.

    Возвращает {"template", "files", "valid", "errors", "elapsed_ms", "entity"}.
    """
    from engine.observer import publish_change

    started = time.perf_counter()
    errors: list[str] = []
    files: list[dict[str, Any]] = []
    try:
        rendered = render_template(template_type, name, type_, dependencies)
    except ValueError as exc:
        return {
            "template": template_type,
            "files": [],
            "valid": False,
            "errors": [str(exc)],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "entity": None,
        }
    ok, error = validate_syntax(rendered["filename"], rendered["content"])
    if not ok:
        errors.append(f"{rendered['filename']}: {error}")
    files.append(rendered)

    entity_dict: dict[str, Any] | None = None
    valid = not errors
    if register and valid:
        meta = {
            "autogen": True,
            "template": template_type,
            "module_type": type_,
            "dependencies": list(dependencies or []),
            "files": [f["filename"] for f in files],
        }
        if db is not None:
            from backend.models import Entity

            existing = db.query(Entity).filter_by(name=name).first()
            if existing:
                try:
                    existing_meta = json.loads(existing.meta or "{}")
                except json.JSONDecodeError:
                    existing_meta = {}
                existing_meta.update(meta)
                existing.meta = json.dumps(existing_meta, ensure_ascii=False)
                db.commit()
                db.refresh(existing)
                entity_dict = existing.to_dict()
            else:
                entity = Entity(name=name, meta=json.dumps(meta, ensure_ascii=False))
                db.add(entity)
                db.commit()
                db.refresh(entity)
                entity_dict = entity.to_dict()
        else:
            from core.symbio_hive import hive as hive_module

            hive_entity = hive_module.create_entity(name, meta=meta)
            entity_dict = dict(hive_entity)
        publish_change(
            "module.generated",
            entity=name,
            data={"template": template_type, "files": [f["filename"] for f in files]},
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "template": template_type,
        "files": files,
        "valid": valid,
        "errors": errors,
        "elapsed_ms": elapsed_ms,
        "entity": entity_dict,
    }
