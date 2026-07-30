"""Tests for arnes.middleware."""

from __future__ import annotations

import pytest

from arnes.llm.base import LLMMessage
from arnes.llm.mock import MockLLMProvider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer


class TestTokenOptimizer:
    @pytest.mark.asyncio
    async def test_cache_hit_saves_tokens(self):
        provider = MockLLMProvider(default_response="cached response")
        optimizer = TokenOptimizer(provider, enable_cache=True)

        messages = [LLMMessage(role="user", content="Hello")]

        # First call — miss
        r1 = await optimizer.complete(messages, model="mock/test")
        assert r1.usage.cached is False

        # Second call — should hit cache
        r2 = await optimizer.complete(messages, model="mock/test")
        assert r2.usage.cached is True

        stats = optimizer.stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1

    @pytest.mark.asyncio
    async def test_different_inputs_dont_cache(self):
        provider = MockLLMProvider()
        optimizer = TokenOptimizer(provider)

        msg1 = [LLMMessage(role="user", content="Hello")]
        msg2 = [LLMMessage(role="user", content="Goodbye")]

        await optimizer.complete(msg1, model="mock/test")
        await optimizer.complete(msg2, model="mock/test")

        stats = optimizer.stats()
        assert stats["cache_misses"] == 2
        assert stats["cache_hits"] == 0

    @pytest.mark.asyncio
    async def test_routing_to_cheaper_model(self):
        provider = MockLLMProvider()
        optimizer = TokenOptimizer(provider, enable_routing=True)

        # Short input, no tools → should route to cheaper model
        short_msg = [LLMMessage(role="user", content="Hi")]
        await optimizer.complete(short_msg, model="anthropic/claude-sonnet-4-20250514")

        stats = optimizer.stats()
        assert stats["routing_decisions"] >= 1


class TestVerificationLayer:
    @pytest.mark.asyncio
    async def test_refusal_pattern_injected(self):
        provider = MockLLMProvider(default_response="I don't know the answer")
        verification = VerificationLayer(provider, VerificationConfig(refusal_pattern=True))

        messages = [LLMMessage(role="user", content="What is X?")]
        response = await verification.complete(messages, model="mock/test")

        # Should detect hedging and replace with refusal
        assert (
            response.content
            == "I don't have enough confidence to answer this. Please verify manually."
        )

    @pytest.mark.asyncio
    async def test_structured_output_validation(self):
        # Return invalid JSON
        provider = MockLLMProvider(default_response="not valid json")
        verification = VerificationLayer(
            provider,
            VerificationConfig(structured_outputs=True, refusal_pattern=False),
        )

        messages = [LLMMessage(role="user", content="Return JSON")]
        response = await verification.complete(
            messages,
            model="mock/test",
            response_schema={"type": "object", "required": ["result"]},
        )

        # Should fail validation and return refusal
        assert "don't have enough confidence" in response.content


class TestCostGuard:
    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        # Track spend manually to exceed tiny budget
        provider = MockLLMProvider(default_response="x" * 1000)  # Large response = high tokens
        budget = CostBudget(task_budget_usd=0.0001)  # Very tiny budget
        guard = CostGuard(provider, budget=budget)

        messages = [LLMMessage(role="user", content="Hello")]

        # First call should succeed (cost is 0 for mock)
        r1 = await guard.complete(messages, model="mock/test")
        assert r1.usage.cost_usd == 0.0

        # Manually inflate spent_usd to exceed budget
        guard.spent_usd = 0.001  # 10x the budget

        # Second call should raise BudgetExceeded
        with pytest.raises(BudgetExceeded, match="Budget exceeded"):
            await guard.complete(messages, model="mock/test")

    @pytest.mark.asyncio
    async def test_circuit_breaker_triggers(self):
        provider = MockLLMProvider()
        # Very low max per minute
        budget = CostBudget(task_budget_usd=10.0, max_usd_per_minute=0.001)
        guard = CostGuard(provider, budget=budget)

        # Inject fake spend history to trigger circuit breaker
        import time

        guard._spend_history.append((time.time(), 0.005))  # 5x the per-minute limit

        with pytest.raises(BudgetExceeded, match="Circuit breaker"):
            await guard.complete(
                [LLMMessage(role="user", content="x")],
                model="mock/test",
            )

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        provider = MockLLMProvider()
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=1.0))

        await guard.complete([LLMMessage(role="user", content="hi")], model="mock/test")

        stats = guard.stats()
        assert stats["calls_made"] == 1
        assert stats["spent_usd"] == 0.0  # Mock is free

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        provider = MockLLMProvider()
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=1.0))

        await guard.complete([LLMMessage(role="user", content="hi")], model="mock/test")
        guard.spent_usd = 0.5
        guard.calls_made = 10

        guard.reset()

        assert guard.spent_usd == 0.0
        assert guard.calls_made == 0
