"""
Autogen — автогенерация сущностей, связей и модулей по намерению
"""

from .autogen import autogen_handle
from .templates import (
    TEMPLATE_TYPES,
    TEMPLATES,
    generate_module,
    render_template,
    validate_syntax,
)

__all__ = [
    "autogen_handle",
    "TEMPLATE_TYPES",
    "TEMPLATES",
    "generate_module",
    "render_template",
    "validate_syntax",
]
