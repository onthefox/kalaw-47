"""core.llm — SDK-based LLM layer (issue #9, задачи 1–3).

Публичный интерфейс: IntentResult, LLMProvider, ошибки, конфиг,
rate limiter, оркестратор и cost tracking.
"""

from core.llm.base import (
    AuthenticationError,
    IntentResult,
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    RateLimitError,
    SYSTEM_PROMPT,
)
from core.llm.config import LLMConfig, LLMConfigError, get_llm_config
from core.llm.cost_tracker import CostTracker, calculate_estimated_cost
from core.llm.orchestrator import LLMOrchestrator
from core.llm.rate_limiter import TokenBucketRateLimiter

__all__ = [
    "SYSTEM_PROMPT",
    "AuthenticationError",
    "CostTracker",
    "IntentResult",
    "LLMConfig",
    "LLMConfigError",
    "LLMError",
    "LLMOrchestrator",
    "LLMProvider",
    "LLMTimeoutError",
    "RateLimitError",
    "TokenBucketRateLimiter",
    "calculate_estimated_cost",
    "get_llm_config",
]
