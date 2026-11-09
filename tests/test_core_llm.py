"""Тесты core/llm (issue #9, задачи 1–3)."""

from __future__ import annotations

import asyncio

import pytest

from core.llm.base import (
    AuthenticationError,
    IntentResult,
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    RateLimitError,
    parse_intent_json,
    result_from_parsed,
)
from core.llm.config import LLMConfig, LLMConfigError, get_llm_config
from core.llm.cost_tracker import CostTracker, calculate_estimated_cost
from core.llm.orchestrator import LLMOrchestrator
from core.llm.rate_limiter import TokenBucketRateLimiter


# --- Фейки (только в тестах) ---

class FakeProvider(LLMProvider):
    def __init__(self, name: str, available: bool = True, result: IntentResult | None = None,
                 error: Exception | None = None):
        self._name = name
        self._available = available
        self._result = result
        self._error = error
        self.calls = 0

    def get_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    async def interpret(self, text: str) -> IntentResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result or result_from_parsed(
            {"action": "create", "entity": "X", "probability": 0.95}, self._name
        )


# --- Задача 1: config и base ---

class TestConfig:
    def test_get_llm_config_no_keys_raises(self, monkeypatch):
        for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(LLMConfigError):
            get_llm_config()

    def test_get_llm_config_valid(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PRIMARY_PROVIDER", raising=False)
        cfg = get_llm_config()
        assert cfg.openai_api_key == "sk-test"
        assert cfg.primary_provider == "openai"
        assert cfg.enabled_providers == ["openai"]
        assert cfg.timeout_seconds >= 1

    def test_primary_without_key_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
        with pytest.raises(LLMConfigError):
            get_llm_config()

    def test_unknown_primary_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk")
        monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "mistral")
        with pytest.raises(LLMConfigError):
            get_llm_config()

    def test_explicit_config_bypasses_env(self):
        cfg = LLMConfig(openai_api_key="k", primary_provider="openai")
        orch = LLMOrchestrator(config=cfg)
        assert orch.config is cfg


class TestBaseParsing:
    def test_parse_plain_json(self):
        data = parse_intent_json('{"action": "create", "entity": "Молоко", "probability": 0.9}')
        assert data["action"] == "create"
        assert data["probability"] == 0.9

    def test_parse_fenced_json(self):
        raw = "```json\n{\"action\": \"query\", \"probability\": \"0.7\"}\n```"
        data = parse_intent_json(raw)
        assert data["action"] == "query"
        assert data["probability"] == 0.7

    def test_parse_invalid_json_raises(self):
        with pytest.raises(LLMError):
            parse_intent_json("не JSON")

    def test_parse_missing_action_raises(self):
        with pytest.raises(LLMError):
            parse_intent_json('{"entity": "X"}')

    def test_probability_clamped(self):
        data = parse_intent_json('{"action": "tag", "probability": 1.7}')
        assert data["probability"] == 1.0

    def test_result_from_parsed_entity_fallback(self):
        result = result_from_parsed(
            {"action": "clone", "entity": "A", "probability": 0.8}, "openai",
            input_tokens=10, output_tokens=5,
        )
        assert isinstance(result, IntentResult)
        assert result.entities == ["A"]
        assert result.provider == "openai"
        assert result.input_tokens == 10
        assert result.output_tokens == 5


# --- Задача 2: rate limiter ---

class TestTokenBucket:
    def test_allows_up_to_capacity_then_raises(self):
        limiter = TokenBucketRateLimiter(requests_per_minute=3, providers={"openai": 3})
        for _ in range(3):
            limiter.check("openai")
        with pytest.raises(RateLimitError):
            limiter.check("openai")

    def test_rate_limit_error_is_llm_error(self):
        assert issubclass(RateLimitError, LLMError)
        assert issubclass(AuthenticationError, LLMError)
        assert issubclass(LLMTimeoutError, LLMError)

    def test_providers_are_independent(self):
        limiter = TokenBucketRateLimiter(requests_per_minute=1, providers={"openai": 1, "anthropic": 1})
        limiter.check("openai")
        limiter.check("anthropic")
        with pytest.raises(RateLimitError):
            limiter.check("openai")

    def test_refill_over_time(self, monkeypatch):
        import core.llm.rate_limiter as rl_module

        limiter = TokenBucketRateLimiter(requests_per_minute=60, providers={"openai": 60})
        for _ in range(60):
            limiter.check("openai")
        with pytest.raises(RateLimitError):
            limiter.check("openai")
        # Сдвигаем время: бакет должен пополниться (1 токен/сек)
        real_monotonic = rl_module.time.monotonic
        monkeypatch.setattr(
            rl_module.time, "monotonic", lambda: real_monotonic() + 30.0
        )
        limiter.check("openai")

    def test_try_acquire(self):
        limiter = TokenBucketRateLimiter(requests_per_minute=1, providers={"google": 1})
        assert limiter.try_acquire("google") is True
        assert limiter.try_acquire("google") is False


# --- Задача 2: провайдеры без ключей недоступны ---

class TestProvidersAvailability:
    def test_openai_unavailable_without_key(self):
        from core.llm.providers import OpenAIProvider

        assert OpenAIProvider(api_key=None).is_available() is False

    def test_anthropic_unavailable_without_key(self):
        from core.llm.providers import AnthropicProvider

        assert AnthropicProvider(api_key=None).is_available() is False

    def test_google_unavailable_without_key(self):
        from core.llm.providers import GoogleProvider

        assert GoogleProvider(api_key=None).is_available() is False

    def test_default_providers_order(self):
        from core.llm.providers import default_providers

        providers = default_providers(LLMConfig())
        assert [p.get_name() for p in providers] == ["openai", "anthropic", "google"]

    def test_primary_first(self):
        from core.llm.providers import default_providers

        providers = default_providers(LLMConfig(anthropic_api_key="k", primary_provider="anthropic"))
        assert providers[0].get_name() == "anthropic"


# --- Задача 3: cost tracker ---

class TestCostTracker:
    def test_gpt4_pricing_1k(self):
        # GPT-4: $0.03/1K input, $0.06/1K output
        assert calculate_estimated_cost("gpt-4", 1000, 1000) == pytest.approx(0.09)

    def test_zero_tokens_zero_cost(self):
        assert calculate_estimated_cost("openai", 0, 0) == 0.0

    def test_rule_based_free(self):
        assert calculate_estimated_cost("rule-based", 1000, 1000) == 0.0

    def test_record_persists_to_db(self, db_session):
        from backend.models import LLMUsage

        tracker = CostTracker()
        cost = tracker.record(
            provider="openai", action="create",
            input_tokens=500, output_tokens=100, success=True, db=db_session,
        )
        assert cost > 0
        rows = db_session.query(LLMUsage).all()
        assert len(rows) == 1
        assert rows[0].provider == "openai"
        assert rows[0].input_tokens == 500
        assert rows[0].output_tokens == 100
        assert rows[0].success is True

    def test_record_without_db_keeps_memory_only(self):
        tracker = CostTracker()
        tracker.record(provider="anthropic", action="tag", input_tokens=10, output_tokens=5)
        assert tracker.usage()["total_requests"] == 1

    def test_usage_aggregation(self):
        tracker = CostTracker()
        tracker.record(provider="openai", action="create", input_tokens=100, output_tokens=10)
        tracker.record(provider="openai", action="tag", input_tokens=100, output_tokens=10)
        tracker.record(provider="google", action="query", input_tokens=50, output_tokens=5)
        usage = tracker.usage()
        assert usage["total_requests"] == 3
        by_name = {e["provider"]: e for e in usage["providers"]}
        assert by_name["openai"]["requests"] == 2
        assert by_name["openai"]["input_tokens"] == 200
        assert by_name["google"]["requests"] == 1


# --- Задача 3: оркестратор ---

class TestOrchestrator:
    def test_first_provider_wins(self):
        ok = FakeProvider("openai")
        fallback = FakeProvider("anthropic")
        orch = LLMOrchestrator(
            providers=[ok, fallback],
            config=LLMConfig(openai_api_key="k"),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать X"))
        assert result.provider == "openai"
        assert ok.calls == 1
        assert fallback.calls == 0

    def test_fallback_on_llm_error(self):
        broken = FakeProvider("openai", error=RateLimitError("429"))
        ok = FakeProvider("anthropic")
        orch = LLMOrchestrator(
            providers=[broken, ok], config=LLMConfig(openai_api_key="k"),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать X"))
        assert result.provider == "anthropic"
        assert broken.calls == 1
        assert ok.calls == 1

    def test_fallback_on_timeout(self):
        broken = FakeProvider("openai", error=LLMTimeoutError("timeout"))
        ok = FakeProvider("google")
        orch = LLMOrchestrator(
            providers=[broken, ok], config=LLMConfig(openai_api_key="k"),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать X"))
        assert result.provider == "google"

    def test_rule_based_fallback_when_all_fail(self):
        broken = FakeProvider("openai", error=AuthenticationError("401"))
        orch = LLMOrchestrator(
            providers=[broken], config=LLMConfig(openai_api_key="k"),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать Молоко"))
        assert result.provider == "rule-based"
        assert result.action == "create"

    def test_rule_based_fallback_without_providers(self):
        orch = LLMOrchestrator(providers=[], config=LLMConfig())
        result = asyncio.run(orch.interpret_with_fallback("объединить A и B"))
        assert result.provider == "rule-based"
        assert result.action == "merge"
        assert result.entities == ["a", "b"]

    def test_unavailable_provider_skipped(self):
        unavailable = FakeProvider("openai", available=False)
        ok = FakeProvider("anthropic")
        orch = LLMOrchestrator(
            providers=[unavailable, ok], config=LLMConfig(openai_api_key="k"),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать X"))
        assert result.provider == "anthropic"
        assert unavailable.calls == 0

    def test_cost_recorded_per_request(self, db_session):
        from backend.models import LLMUsage

        provider = FakeProvider("openai")
        provider._result = result_from_parsed(
            {"action": "create", "probability": 0.9}, "openai",
            input_tokens=1000, output_tokens=1000,
        )
        orch = LLMOrchestrator(
            providers=[provider], config=LLMConfig(openai_api_key="k"),
        )
        asyncio.run(orch.interpret_with_fallback("создать X", db=db_session))
        rows = db_session.query(LLMUsage).all()
        assert len(rows) == 1
        assert rows[0].provider == "openai"
        assert rows[0].estimated_cost == pytest.approx(0.09)

    def test_rate_limit_skips_provider(self):
        limited = FakeProvider("openai")
        ok = FakeProvider("anthropic")
        orch = LLMOrchestrator(
            providers=[limited, ok],
            config=LLMConfig(openai_api_key="k"),
            rate_limiter=TokenBucketRateLimiter(
                requests_per_minute=60, providers={"openai": 0, "anthropic": 60}
            ),
        )
        result = asyncio.run(orch.interpret_with_fallback("создать X"))
        assert result.provider == "anthropic"
        assert limited.calls == 0

    def test_has_available_providers(self):
        orch = LLMOrchestrator(providers=[], config=LLMConfig())
        assert orch.has_available_providers() is False
        orch2 = LLMOrchestrator(providers=[FakeProvider("openai")], config=LLMConfig())
        assert orch2.has_available_providers() is True


# --- Задача 3: интеграция flow + API ---

class TestFlowIntegration:
    def test_handle_intent_uses_orchestrator(self, db_session):
        from engine.symbio_flow.flow import handle_intent

        provider = FakeProvider("openai")
        provider._result = result_from_parsed(
            {"action": "create", "entity": "LLM-Сущность", "probability": 0.97},
            "openai", input_tokens=42, output_tokens=7,
        )
        orch = LLMOrchestrator(
            providers=[provider], config=LLMConfig(openai_api_key="k"),
        )
        result = handle_intent("создать LLM-Сущность", db_session, orchestrator=orch)
        assert provider.calls == 1
        assert result["llm_provider"] == "openai"
        assert result["provider"] == "openai"
        assert result["tokens_used"] == 49

    def test_handle_intent_sync_stays_sync(self, db_session):
        """handle_intent остаётся синхронным и работает без оркестратора."""
        from engine.symbio_flow.flow import handle_intent

        result = handle_intent("создать Простая", db_session, use_llm=False)
        assert result["action"] == "create"
        assert "provider" not in result


class TestStatsLlmEndpoint:
    def test_stats_llm_empty(self, client):
        resp = client.get("/stats/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0
        assert data["total_estimated_cost"] == 0
        assert data["providers"] == []

    def test_stats_llm_aggregates(self, client, db_session):
        from backend.models import LLMUsage

        db_session.add(LLMUsage(provider="openai", action="create", input_tokens=1000,
                                output_tokens=1000, estimated_cost=0.09, success=True))
        db_session.add(LLMUsage(provider="openai", action="tag", input_tokens=500,
                                output_tokens=0, estimated_cost=0.015, success=False))
        db_session.add(LLMUsage(provider="google", action="query", input_tokens=100,
                                output_tokens=50, estimated_cost=0.00003125, success=True))
        db_session.commit()

        resp = client.get("/stats/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 3
        by_name = {e["provider"]: e for e in data["providers"]}
        assert by_name["openai"]["requests"] == 2
        assert by_name["openai"]["input_tokens"] == 1500
        assert by_name["openai"]["failed"] == 1
        assert by_name["google"]["success"] == 1
        assert data["total_estimated_cost"] == pytest.approx(round(0.09 + 0.015 + 0.00003125, 6))

    def test_intent_response_includes_optional_fields(self, client):
        resp = client.post("/intent", json={"intent": "создать Тестовая", "use_llm": False})
        assert resp.status_code == 200
        data = resp.json()
        # Optional-поля присутствуют (None без LLM), свободные поля сохранены
        assert "provider" in data
        assert "confidence" in data
        assert "tokens_used" in data
        assert data["action"] == "create"
