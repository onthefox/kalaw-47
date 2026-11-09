"""
Issue #9: LLM-интеграция — провайдеры, разбор JSON, rate limit, стоимость, цепочка.
"""

from __future__ import annotations

import pytest

from engine.llm.base import LLMError, LLMProvider, SYSTEM_PROMPT
from engine.llm.chain import LLMChain
from engine.llm.providers import GoogleProvider, OpenAIProvider, default_providers
from engine.llm.rate_limit import CostTracker, RateLimiter

ENV_KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]


@pytest.fixture(autouse=True)
def no_api_keys(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestProvidersWithoutKeys:
    def test_default_providers_all_unavailable(self):
        providers = default_providers()
        assert [p.name for p in providers] == ["openai", "anthropic", "google"]
        assert all(not p.available for p in providers)

    def test_explicit_key_makes_available(self):
        provider = OpenAIProvider(api_key="test-key")
        assert provider.available
        assert provider.model == "gpt-4o-mini"

    def test_interpret_without_key_raises(self):
        with pytest.raises(LLMError):
            OpenAIProvider().interpret("создать X")

    def test_system_prompt_mentions_probability(self):
        assert "probability" in SYSTEM_PROMPT


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, response=None, fail=None, **kwargs):
        super().__init__(api_key=kwargs.pop("api_key", "k"))
        self.response = response
        self.fail = fail
        self.calls: list[str] = []

    def interpret(self, text: str):
        self.calls.append(text)
        if self.fail is not None:
            raise self.fail
        return self.response


class TestParseJsonResponse:
    def setup_method(self):
        self.provider = OpenAIProvider(api_key="k")

    def test_plain_json(self):
        parsed = self.provider.parse_json_response('{"action": "create", "entity": "X"}')
        assert parsed["action"] == "create"
        assert parsed["entity"] == "X"
        assert parsed["provider"] == "openai"
        assert parsed["probability"] == 0.5  # дефолт

    def test_json_code_fence_stripped(self):
        raw = "```json\n{\"action\": \"link\", \"probability\": 0.87}\n```"
        parsed = self.provider.parse_json_response(raw)
        assert parsed["action"] == "link"
        assert parsed["probability"] == 0.87

    def test_probability_clamped(self):
        parsed = self.provider.parse_json_response('{"action": "create", "probability": 1.7}')
        assert parsed["probability"] == 1.0
        parsed = self.provider.parse_json_response('{"action": "create", "probability": -0.5}')
        assert parsed["probability"] == 0.0

    def test_probability_garbage_becomes_default(self):
        parsed = self.provider.parse_json_response('{"action": "create", "probability": "высокая"}')
        assert parsed["probability"] == 0.5

    def test_none_values_removed(self):
        parsed = self.provider.parse_json_response(
            '{"action": "create", "entity": "X", "tag": null}'
        )
        assert "tag" not in parsed

    def test_invalid_json_raises(self):
        with pytest.raises(LLMError):
            self.provider.parse_json_response("не json вообще")

    def test_missing_action_raises(self):
        with pytest.raises(LLMError):
            self.provider.parse_json_response('{"entity": "X"}')


class TestRateLimiter:
    def test_allows_up_to_limit(self):
        limiter = RateLimiter(max_calls=2, period=60.0)
        assert limiter.allow("openai")
        assert limiter.allow("openai")
        assert not limiter.allow("openai")

    def test_keys_independent(self):
        limiter = RateLimiter(max_calls=1, period=60.0)
        assert limiter.allow("openai")
        assert limiter.allow("anthropic")
        assert not limiter.allow("openai")

    def test_remaining(self):
        limiter = RateLimiter(max_calls=3, period=60.0)
        limiter.allow("openai")
        assert limiter.remaining("openai") == 2

    def test_sliding_window_expiry(self):
        limiter = RateLimiter(max_calls=1, period=10.0)
        assert limiter.allow("openai", now=100.0)
        assert not limiter.allow("openai", now=105.0)
        assert limiter.allow("openai", now=111.0)  # старый вызов вышел из окна

    def test_reset(self):
        limiter = RateLimiter(max_calls=1, period=60.0)
        limiter.allow("openai")
        limiter.reset()
        assert limiter.allow("openai")


class TestCostTracker:
    def test_known_model_pricing(self):
        tracker = CostTracker()
        entry = tracker.record(
            provider="openai", model="gpt-4o-mini",
            prompt_tokens=1_000_000, completion_tokens=1_000_000,
        )
        assert entry["cost_usd"] == pytest.approx(0.75)

    def test_unknown_model_uses_default_pricing(self):
        tracker = CostTracker()
        entry = tracker.record(provider="x", model="mystery", prompt_tokens=1_000_000)
        assert entry["cost_usd"] == pytest.approx(0.5)

    def test_usage_aggregates(self):
        tracker = CostTracker()
        tracker.record(provider="openai", model="gpt-4o-mini", prompt_tokens=100, completion_tokens=10)
        tracker.record(provider="openai", model="gpt-4o-mini", prompt_tokens=50, completion_tokens=5)
        tracker.record(provider="google", model="gemini-1.5-flash", prompt_tokens=200, completion_tokens=20)
        usage = tracker.usage()
        assert usage["total_requests"] == 3
        assert usage["total_prompt_tokens"] == 350
        assert usage["total_completion_tokens"] == 35
        assert usage["by_provider"]["openai"]["prompt_tokens"] == 150
        assert usage["total_cost_usd"] > 0

    def test_reset(self):
        tracker = CostTracker()
        tracker.record(provider="openai", model="gpt-4o-mini", prompt_tokens=10)
        tracker.reset()
        usage = tracker.usage()
        assert usage["total_requests"] == 0
        assert usage["total_cost_usd"] == 0


class TestLLMChain:
    def test_no_providers_returns_none(self):
        chain = LLMChain(providers=[])
        assert chain.available is False
        assert chain.interpret("создать X") is None

    def test_default_chain_unavailable_without_keys(self):
        chain = LLMChain()
        assert chain.available is False
        assert chain.interpret("создать X") is None

    def test_chain_uses_fake_provider(self):
        fake = FakeProvider(response={"action": "create", "entity": "X", "probability": 0.9})
        chain = LLMChain(providers=[fake])
        result = chain.interpret("создать X")
        assert result is not None
        assert result["parsed"]["action"] == "create"
        assert result["probability"] == 0.9
        assert result["provider"] == "fake"
        assert "elapsed_ms" in result
        assert chain.last_provider == "fake"

    def test_chain_skips_unavailable(self):
        offline = FakeProvider(api_key=None, response={"action": "create"})
        fake = FakeProvider(response={"action": "delete", "probability": 0.8})
        chain = LLMChain(providers=[offline, fake])
        result = chain.interpret("удалить X")
        assert result["provider"] == "fake"
        assert offline.calls == []

    def test_chain_survives_provider_error(self):
        broken = FakeProvider(fail=LLMError("boom"))
        fake = FakeProvider(response={"action": "query", "probability": 0.6})
        chain = LLMChain(providers=[broken, fake])
        result = chain.interpret("найти X")
        assert result["provider"] == "fake"
        assert any("boom" in e for e in chain.last_errors)

    def test_chain_survives_crash(self):
        broken = FakeProvider(fail=RuntimeError("unexpected"))
        fake = FakeProvider(response={"action": "query"})
        chain = LLMChain(providers=[broken, fake])
        assert chain.interpret("найти X")["provider"] == "fake"

    def test_chain_records_cost_from_usage(self):
        fake = FakeProvider(response={"action": "create", "probability": 0.9})
        fake.last_usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
        tracker = CostTracker()
        chain = LLMChain(providers=[fake], cost_tracker=tracker)
        chain.interpret("создать X")
        usage = tracker.usage()
        assert usage["total_requests"] == 1
        assert usage["total_cost_usd"] == pytest.approx(0.5)  # модель fake → дефолт-прайс

    def test_rate_limit_blocks_provider(self):
        fake = FakeProvider(response={"action": "create"})
        chain = LLMChain(providers=[fake], rate_limiter=RateLimiter(max_calls=0))
        assert chain.interpret("создать X") is None
        assert fake.calls == []
        assert any("rate limit" in e for e in chain.last_errors)
