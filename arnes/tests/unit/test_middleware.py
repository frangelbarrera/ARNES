"""Tests for arnes.middleware."""

from __future__ import annotations

from typing import Any

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.llm.mock import MockLLMProvider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer
from arnes.thread.events import EventType, HumanApprovalRequestedEvent


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


class _ConfigurableCostProvider(LLMProvider):
    """Mock provider that charges a fixed, configurable cost per call.

    Mirrors the one in tests/stress/test_budget_edge_cases.py — kept local
    so the unit tests don't depend on the stress test module.
    """

    def __init__(self, *, cost_per_call: float = 0.0) -> None:
        self.cost_per_call = cost_per_call
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="ok",
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=10,
                tokens_out=5,
                cost_usd=self.cost_per_call,
                model=model,
                cached=False,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock"]


class TestCostGuardPause:
    """Tests for the 95% pause-at-budget behaviour (FIX-R3-SEC Issue 2)."""

    @pytest.mark.asyncio
    async def test_interactive_pause_raises_and_emits_human_approval(self):
        """At 95% budget in interactive mode, the guard must:
        - set _paused = True
        - emit a HumanApprovalRequestedEvent
        - raise BudgetExceeded(level="pause")
        """
        provider = _ConfigurableCostProvider(cost_per_call=0.0)
        # budget=$0.10. pause threshold = $0.095, abort threshold = $0.10.
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=0.10))
        # Manually place spent between pause and abort thresholds so the
        # pre-call abort check does NOT fire first. The provider charges
        # $0 per call so the call itself doesn't push spent over abort.
        guard.spent_usd = 0.096

        messages = [LLMMessage(role="user", content="hi")]

        with pytest.raises(BudgetExceeded, match="paused at 95%") as exc_info:
            await guard.complete(messages, model="mock/test", interactive=True)

        assert exc_info.value.level == "pause"
        assert guard._paused is True
        assert guard._aborted is False  # pause ≠ abort
        # Provider must NOT have been called — pause raises pre-call.
        assert provider.call_count == 0

        # The events sink must contain a CostThresholdEvent AND a
        # HumanApprovalRequestedEvent.
        event_types = [type(e).__name__ for e in guard._events]
        assert "CostThresholdEvent" in event_types
        assert "HumanApprovalRequestedEvent" in event_types

        human_events = [e for e in guard._events if isinstance(e, HumanApprovalRequestedEvent)]
        assert len(human_events) == 1
        he = human_events[0]
        assert he.type == EventType.HUMAN_APPROVAL_REQUESTED
        assert "approve" in he.data["options"]
        assert "reject" in he.data["options"]
        assert he.data["spent_usd"] == pytest.approx(0.096)
        assert he.data["budget_usd"] == pytest.approx(0.10)

    @pytest.mark.asyncio
    async def test_interactive_pause_blocks_subsequent_calls(self):
        """Once _paused is set, subsequent calls raise immediately with
        level='pause' (without re-charging the provider)."""
        provider = _ConfigurableCostProvider(cost_per_call=0.0)
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=0.10))
        guard.spent_usd = 0.096  # between pause (0.095) and abort (0.10)

        messages = [LLMMessage(role="user", content="hi")]

        # First call crosses 95% → raises pause (provider not called).
        with pytest.raises(BudgetExceeded, match="paused at 95%"):
            await guard.complete(messages, model="mock/test", interactive=True)
        assert provider.call_count == 0

        # Second call must raise immediately (paused state) — provider
        # must NOT be invoked again.
        with pytest.raises(BudgetExceeded) as exc_info:
            await guard.complete(messages, model="mock/test", interactive=True)
        assert exc_info.value.level == "pause"
        assert provider.call_count == 0, "Paused guard must not invoke the provider"

    @pytest.mark.asyncio
    async def test_non_interactive_pause_does_not_raise_or_block(self):
        """In non-interactive mode, hitting 95% must:
        - NOT raise (continue so the call completes)
        - NOT set _paused (so the hard stop at 100% catches future calls)
        - still emit the CostThresholdEvent(level='pause') for audit
        """
        provider = _ConfigurableCostProvider(cost_per_call=0.0)
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=0.10))
        # Place spent between pause and abort thresholds.
        guard.spent_usd = 0.096

        messages = [LLMMessage(role="user", content="hi")]

        # Pre-call: spent=0.096 < 0.10 (abort) → no abort. No peek_cost →
        # no preflight. spent=0.096 >= 0.095 (pause) → pause threshold
        # reached. Non-interactive → log+continue, do NOT raise.
        response = await guard.complete(messages, model="mock/test", interactive=False)
        assert response.content == "ok"
        assert guard._paused is False, (
            "Non-interactive pause must NOT set _paused — the hard stop at 100% "
            "is responsible for catching the run, not the pause."
        )
        assert guard._aborted is False
        # The provider WAS called (non-interactive pause doesn't block).
        assert provider.call_count == 1

        # The CostThresholdEvent(level="pause") must be in the sink.
        pause_events = [
            e for e in guard._events if getattr(e, "data", {}).get("threshold_level") == "pause"
        ]
        assert len(pause_events) == 1
        assert pause_events[0].data["interactive"] is False

    @pytest.mark.asyncio
    async def test_non_interactive_pause_then_hard_stop_at_100(self):
        """Non-interactive: 95% logs+continues, 100% hard-stops."""
        provider = _ConfigurableCostProvider(cost_per_call=0.0)
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=0.10))

        messages = [LLMMessage(role="user", content="hi")]

        # Call 1: spent=0.096 (95% threshold, non-interactive → continue).
        guard.spent_usd = 0.096
        await guard.complete(messages, model="mock/test", interactive=False)
        assert guard._paused is False

        # Call 2: bump spent to 100% to trigger the hard stop.
        guard.spent_usd = 0.10
        with pytest.raises(BudgetExceeded) as exc_info:
            await guard.complete(messages, model="mock/test", interactive=False)
        assert exc_info.value.level == "hard_stop"
        assert guard._aborted is True
