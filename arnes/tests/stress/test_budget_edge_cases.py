"""ARNES Budget Exhaustion Edge Cases Stress Test (STRESS-3).

Stress-tests the CostGuard middleware against 6 budget-exhaustion edge cases:

1. Budget exactly at limit (budget == per-call cost).
2. Budget slightly under per-call cost (pre-flight rejection).
3. Circuit breaker: 10 calls injected in <1s should trip the rate limit.
4. Zero budget: should fail immediately.
5. Very large budget: should never trip.
6. Free model (Ollama-style): cost=$0.000 per call, tiny budget, never trips.

Uses a custom mock provider (``ConfigurableCostProvider``) that charges a
configurable fixed cost per call AND exposes ``peek_cost()`` so the guard
can do pre-flight budget checking.

Run via:
    pytest tests/stress/test_budget_edge_cases.py -s --no-cov
or:
    python tests/stress/test_budget_edge_cases.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# Make `arnes` importable when running the file directly (python tests/stress/...).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

from arnes.llm.base import (  # noqa: E402
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMUsage,
)
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard  # noqa: E402

# ============================================================
# Custom mock provider — configurable cost per call + peek_cost()
# ============================================================


class ConfigurableCostProvider(LLMProvider):
    """Mock provider that charges a fixed, configurable cost per call.

    - ``cost_per_call``: USD charged on every ``complete()`` invocation.
    - ``peek_cost()``: returns the same ``cost_per_call`` so CostGuard can
      do pre-flight budget checking (reject the call BEFORE it's made if
      the projected spend would exceed the budget).
    - ``call_count``: instrumentation — how many times ``complete()`` ran.
    """

    def __init__(
        self,
        *,
        cost_per_call: float = 0.0,
        response: str = "ok",
        delay_s: float = 0.0,
    ) -> None:
        self.cost_per_call = cost_per_call
        self.response = response
        self.delay_s = delay_s
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        self.call_count += 1
        return LLMResponse(
            content=self.response,
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

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Yield the full response in one chunk (matches MockLLMProvider contract)."""
        response = await self.complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_schema=response_schema,
            **kwargs,
        )
        yield response

    def list_models(self) -> list[str]:
        return ["mock"]

    def peek_cost(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> float | None:
        """Return the fixed per-call cost so CostGuard can pre-flight check."""
        return self.cost_per_call


# ============================================================
# Helpers
# ============================================================


def _msg() -> list[LLMMessage]:
    return [LLMMessage(role="user", content="hello")]


class _CallResult:
    """Outcome of a single guarded call: either ok or BudgetExceeded."""

    __slots__ = ("exc", "ok", "response")

    def __init__(
        self, *, ok: bool, exc: BudgetExceeded | None = None, response: LLMResponse | None = None
    ) -> None:
        self.ok = ok
        self.exc = exc
        self.response = response


async def _call(guard: CostGuard, *, model: str = "mock/test") -> _CallResult:
    try:
        r = await guard.complete(_msg(), model=model)
        return _CallResult(ok=True, response=r)
    except BudgetExceeded as e:
        return _CallResult(ok=False, exc=e)


def _fmt_exc(r: _CallResult) -> str:
    if r.ok:
        return "OK"
    assert r.exc is not None
    return (
        f"BudgetExceeded(level={r.exc.level}, spent={r.exc.spent:.6f}, budget={r.exc.budget:.6f})"
    )


# ============================================================
# Edge case 1: Budget exactly at limit
#   budget=$0.001, each call costs $0.001.
#   First call should SUCCEED, second should FAIL.
# ============================================================


class TestBudgetEdgeCases:
    async def test_ec1_budget_exactly_at_limit(self) -> None:
        """budget=$0.001, cost=$0.001/call. Call 1 OK, call 2 fails."""
        provider = ConfigurableCostProvider(cost_per_call=0.001)
        budget = CostBudget(task_budget_usd=0.001, max_usd_per_minute=1.0)
        guard = CostGuard(provider, budget=budget)

        r1 = await _call(guard)
        r2 = await _call(guard)

        assert r1.ok, f"Call 1 should succeed, got {_fmt_exc(r1)}"
        assert r1.response is not None
        assert r1.response.usage.cost_usd == 0.001
        assert guard.spent_usd == pytest.approx(0.001)

        assert not r2.ok, f"Call 2 should fail (spent==budget), got OK with spent={guard.spent_usd}"
        assert r2.exc is not None
        assert r2.exc.level in {"hard_stop", "preflight"}
        assert provider.call_count == 1, "Second call must NOT reach the provider"

        print(
            f"\n[EC1] r1={_fmt_exc(r1)}  r2={_fmt_exc(r2)}  "
            f"provider.calls={provider.call_count}  spent=${guard.spent_usd:.6f}"
        )

    # ============================================================
    # Edge case 2: Budget slightly under per-call cost
    #   budget=$0.0009, each call costs $0.001.
    #   First call should FAIL at pre-check (pre-flight rejection).
    # ============================================================

    async def test_ec2_budget_slightly_under_preflight(self) -> None:
        """budget=$0.0009, cost=$0.001/call. First call must fail pre-flight."""
        provider = ConfigurableCostProvider(cost_per_call=0.001)
        budget = CostBudget(task_budget_usd=0.0009, max_usd_per_minute=1.0)
        guard = CostGuard(provider, budget=budget)

        r1 = await _call(guard)

        assert not r1.ok, (
            "First call should fail pre-flight (cost $0.001 > budget $0.0009), "
            f"got OK with spent=${guard.spent_usd:.6f}"
        )
        assert r1.exc is not None
        # Pre-flight check should fire BEFORE the provider is touched.
        assert provider.call_count == 0, (
            "Pre-flight check must reject the call before it reaches the provider, "
            f"but provider.call_count={provider.call_count}"
        )
        assert guard.spent_usd == 0.0, "Nothing should have been spent"
        assert r1.exc.level == "preflight", (
            f"Expected level='preflight', got level={r1.exc.level!r}"
        )

        print(
            f"\n[EC2] r1={_fmt_exc(r1)}  provider.calls={provider.call_count}  "
            f"spent=${guard.spent_usd:.6f}"
        )

    # ============================================================
    # Edge case 3: Circuit breaker
    #   max_usd_per_minute=$0.005, inject 10 calls of $0.001 each in <1s.
    #   Should trip.
    # ============================================================

    async def test_ec3_circuit_breaker_trips(self) -> None:
        """10 calls of $0.001 in <1s with max_usd_per_minute=$0.005 → trip."""
        provider = ConfigurableCostProvider(cost_per_call=0.001)
        # High task budget so the per-task check doesn't fire first.
        budget = CostBudget(task_budget_usd=10.0, max_usd_per_minute=0.005)
        guard = CostGuard(provider, budget=budget)

        results: list[_CallResult] = []
        t0 = time.monotonic()
        for _ in range(10):
            results.append(await _call(guard))
        elapsed = time.monotonic() - t0

        ok_count = sum(1 for r in results if r.ok)
        cb_count = sum(1 for r in results if r.exc and r.exc.level == "circuit_breaker")

        assert elapsed < 1.0, f"10 calls took {elapsed:.3f}s, expected <1s"
        assert ok_count >= 1, "At least the first call should succeed"
        assert cb_count >= 1, (
            f"At least one call should trip the circuit breaker, got cb_count={cb_count}, "
            f"ok_count={ok_count}"
        )
        # After the breaker trips, the guard is aborted — subsequent calls
        # should also fail (with hard_stop, since _aborted=True).
        assert all(not r.ok for r in results[ok_count:]), (
            "Once the breaker trips, all subsequent calls must fail"
        )

        stats = guard.stats()
        print(
            f"\n[EC3] elapsed={elapsed:.3f}s  ok={ok_count}/10  "
            f"circuit_breaker={cb_count}  spent=${guard.spent_usd:.6f}  "
            f"spend_last_minute=${stats['spend_last_minute_usd']:.6f}  "
            f"aborted={guard._aborted}"
        )

    # ============================================================
    # Edge case 4: Zero budget
    #   budget=$0.00. Should fail immediately.
    # ============================================================

    async def test_ec4_zero_budget_fails_immediately(self) -> None:
        """budget=$0.00 → first call fails immediately, no provider call."""
        provider = ConfigurableCostProvider(cost_per_call=0.001)
        budget = CostBudget(task_budget_usd=0.0, max_usd_per_minute=1.0)
        guard = CostGuard(provider, budget=budget)

        r1 = await _call(guard)

        assert not r1.ok, "Zero budget should reject the first call"
        assert r1.exc is not None
        assert provider.call_count == 0, "Provider must not be called with zero budget"
        assert guard.spent_usd == 0.0
        assert guard._aborted, "Guard should be marked aborted after zero-budget rejection"

        print(
            f"\n[EC4] r1={_fmt_exc(r1)}  provider.calls={provider.call_count}  "
            f"spent=${guard.spent_usd:.6f}  aborted={guard._aborted}"
        )

    # ============================================================
    # Edge case 5: Very large budget
    #   budget=$1,000,000. Should never trip (10 calls).
    # ============================================================

    async def test_ec5_very_large_budget_never_trips(self) -> None:
        """budget=$1,000,000 → 10 calls of $0.001 all succeed, never trips."""
        provider = ConfigurableCostProvider(cost_per_call=0.001)
        # Keep default max_usd_per_minute ($1.00) — 10 calls = $0.01 << $1.00.
        budget = CostBudget(task_budget_usd=1_000_000.0, max_usd_per_minute=1.0)
        guard = CostGuard(provider, budget=budget)

        results = [await _call(guard) for _ in range(10)]

        ok_count = sum(1 for r in results if r.ok)
        assert ok_count == 10, f"All 10 calls should succeed, got {ok_count}/10"
        assert provider.call_count == 10
        assert guard.spent_usd == pytest.approx(0.010)
        assert not guard._aborted
        assert not guard._paused

        stats = guard.stats()
        pct = stats["pct_used"]
        assert pct < 0.001, f"Budget usage should be negligible, got {pct:.8%}"

        print(
            f"\n[EC5] ok={ok_count}/10  spent=${guard.spent_usd:.6f}  "
            f"pct_used={pct:.8%}  aborted={guard._aborted}"
        )

    # ============================================================
    # Edge case 6: Free model (Ollama) — cost=$0.000 per call
    #   Tiny budget, but free calls should never trip.
    # ============================================================

    async def test_ec6_free_model_never_trips_with_tiny_budget(self) -> None:
        """cost=$0.000/call, budget=$0.001 (tiny) → 50 calls, never trips."""
        provider = ConfigurableCostProvider(cost_per_call=0.0)  # free
        # Tiny budget + tiny per-minute limit. Free calls should not trip either.
        budget = CostBudget(task_budget_usd=0.001, max_usd_per_minute=0.001)
        guard = CostGuard(provider, budget=budget)

        results = [await _call(guard) for _ in range(50)]

        ok_count = sum(1 for r in results if r.ok)
        assert ok_count == 50, f"All 50 free calls should succeed, got {ok_count}/50"
        assert provider.call_count == 50
        assert guard.spent_usd == 0.0
        assert not guard._aborted
        assert not guard._paused

        print(
            f"\n[EC6] ok={ok_count}/50  spent=${guard.spent_usd:.6f}  "
            f"aborted={guard._aborted}  (free model, tiny budget)"
        )


# ============================================================
# Standalone runner (python tests/stress/test_budget_edge_cases.py)
# ============================================================


async def _run_standalone() -> int:
    """Run all 6 edge cases outside pytest. Returns exit code (0=pass, 1=fail)."""
    instance = TestBudgetEdgeCases()
    cases = [
        ("EC1", "budget exactly at limit", instance.test_ec1_budget_exactly_at_limit),
        (
            "EC2",
            "budget slightly under (pre-flight)",
            instance.test_ec2_budget_slightly_under_preflight,
        ),
        ("EC3", "circuit breaker trips", instance.test_ec3_circuit_breaker_trips),
        ("EC4", "zero budget fails immediately", instance.test_ec4_zero_budget_fails_immediately),
        ("EC5", "very large budget never trips", instance.test_ec5_very_large_budget_never_trips),
        (
            "EC6",
            "free model never trips (tiny budget)",
            instance.test_ec6_free_model_never_trips_with_tiny_budget,
        ),
    ]

    print("=" * 70)
    print("ARNES Budget Edge Cases Stress Test (STRESS-3)")
    print("=" * 70)

    passed = 0
    failed = 0
    for label, desc, fn in cases:
        print(f"\n--- {label}: {desc} ---")
        try:
            await fn()
            print("  -> PASS")
            passed += 1
        except AssertionError as e:
            print(f"  -> FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  -> ERROR: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULT: {passed}/{passed + failed} edge cases passed")
    if failed:
        print(f"STATUS: FAIL — {failed} edge case(s) failed")
    else:
        print("STATUS: PASS — all edge cases green")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_standalone()))
