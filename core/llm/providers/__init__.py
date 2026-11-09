"""Провайдеры core.llm (issue #9, задача 2) и фабрика по умолчанию."""

from core.llm.providers.anthropic_provider import AnthropicProvider
from core.llm.providers.google_provider import GoogleProvider
from core.llm.providers.openai_provider import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "GoogleProvider",
    "OpenAIProvider",
    "default_providers",
]


def default_providers(
    config: "LLMConfig | None" = None,
) -> list["LLMProvider"]:
    """Список провайдеров в порядке приоритета: openai → anthropic → google.

    Primary-провайдер из конфига ставится первым.
    """
    from core.llm.base import LLMProvider
    from core.llm.config import LLMConfig

    config = config or LLMConfig()
    providers: list[LLMProvider] = [
        OpenAIProvider(api_key=config.openai_api_key, timeout=config.timeout_seconds),
        AnthropicProvider(api_key=config.anthropic_api_key, timeout=config.timeout_seconds),
        GoogleProvider(api_key=config.google_api_key, timeout=config.timeout_seconds),
    ]
    primary = config.primary_provider
    by_name = {p.get_name(): p for p in providers}
    if primary in by_name:
        providers = [by_name[primary]] + [p for p in providers if p.get_name() != primary]
    return providers
