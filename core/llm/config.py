"""Конфигурация LLM из переменных окружения (issue #9, задача 1).

Паттерн как в backend/db.py: константы уровня модуля + геттер,
валидирующий обязательные значения.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Константы уровня модуля — читаются один раз при импорте (паттерн backend/db.py)
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_PRIMARY_PROVIDER: str = os.getenv("LLM_PRIMARY_PROVIDER", "openai")

REQUIRED_KEYS_BY_PROVIDER: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


class LLMConfigError(Exception):
    """Конфигурация LLM неполна или некорректна."""


@dataclass
class LLMConfig:
    """Снимок конфигурации провайдеров."""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    timeout_seconds: int = LLM_TIMEOUT_SECONDS
    primary_provider: str = LLM_PRIMARY_PROVIDER
    enabled_providers: list[str] = field(default_factory=list)


def get_llm_config() -> LLMConfig:
    """Собрать LLMConfig из env и проверить согласованность настроек.

    Переменные читаются заново при каждом вызове (свежие значения для
    тестов/рантайма); константы модуля выше — снимок на момент импорта.
    Primary-провайдер обязан иметь свой ключ; если у primary нет ключа,
    поднимаем LLMConfigError — некорректная конфигурация, а не тихий
    пропуск провайдера (ключи остальных — опциональны).
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")
    timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS)))
    primary = os.getenv("LLM_PRIMARY_PROVIDER", LLM_PRIMARY_PROVIDER)

    if primary not in REQUIRED_KEYS_BY_PROVIDER:
        raise LLMConfigError(
            f"LLM_PRIMARY_PROVIDER={primary!r} — допустимые значения: "
            f"{sorted(REQUIRED_KEYS_BY_PROVIDER)}"
        )
    if timeout <= 0:
        raise LLMConfigError(f"LLM_TIMEOUT_SECONDS={timeout} — должен быть > 0")
    if not openai_key and not anthropic_key and not google_key:
        raise LLMConfigError(
            "Не задан ни один API-ключ: установите OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY или GOOGLE_API_KEY"
        )

    required_env = REQUIRED_KEYS_BY_PROVIDER[primary]
    if not os.getenv(required_env):
        raise LLMConfigError(
            f"{required_env} обязателен: LLM_PRIMARY_PROVIDER={primary}"
        )

    enabled: list[str] = []
    if openai_key:
        enabled.append("openai")
    if anthropic_key:
        enabled.append("anthropic")
    if google_key:
        enabled.append("google")

    return LLMConfig(
        openai_api_key=openai_key,
        anthropic_api_key=anthropic_key,
        google_api_key=google_key,
        timeout_seconds=timeout,
        primary_provider=primary,
        enabled_providers=enabled,
    )
