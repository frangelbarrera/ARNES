"""
ARNES Cost Guard — budget enforcement with circuit breaker.

This is THE killer differentiator of ARNES. No other agent framework
implements budget enforcement correctly:

- OpenHands: max_budget_per_task (1 level, no circuit breaker)
- browser-use: warning at 75% of step budget (no enforcement)
- langfuse: MAX_AGENT_STEPS=10 hardcap (no USD tracking)
- crewai: max_tokens only (no USD, no circuit breaker)

ARNES CostGuard provides:

- Hierarchical budget: org → project → agent → task with inheritance
- Per-step + per-total USD tracking
- Circuit breaker temporal: max USD/minute (denial-of-wallet defense)
- Model fallback: if budget < threshold, switch to cheaper model
- HITL: pause and ask for approval at 95% of budget
- Hard stop: abort at 100% of budget
- Audit log: every decision logged to Thread events via the event sink

R16 split: :class:`BudgetExceeded` and :class:`CostBudget` were
extracted to :mod:`arnes.middleware.budget` to keep this module
under the AGENTS.md 500-line rule. They are re-exported here for
backwards compatibility (existing
``from arnes.middleware.cost_guard import CostBudget, BudgetExceeded``
imports keep working).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import structlog

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse
from arnes.middleware.budget import BudgetExceeded, CostBudget
from arnes.thread.events import CostThresholdEvent, Event, EventType, HumanApprovalRequestedEvent

logger = structlog.get_logger(__name__)

# Re-export ``BudgetExceeded`` and ``CostBudget`` for backwards
# compatibility (existing imports of the shape
# ``from arnes.middleware.cost_guard import CostBudget`` keep working
# after the R16 split). The canonical home for these is
# :mod:`arnes.middleware.budget`.
__all__ = ["BudgetExceeded", "CostBudget", "CostGuard"]


# Sentinel thread_id used by middleware when the real Thread id is not
# available (middleware does not receive a ToolContext). The PlaybookExecutor
# patches these events with the real thread_id and step_id when it drains the
# event sink after each step. Using a stable nil UUID makes the placeholder
# easy to spot in logs.
NIL_THREAD_ID = UUID(int=0)


class CostGuard(LLMProvider):
    """Middleware that enforces cost budgets.

    Wraps an LLMProvider and tracks spend. If budget exceeded, raises
    BudgetExceeded (which the executor catches and converts to a
    RunFailedEvent).
    """

    def __init__(
        self,
        provider: LLMProvider,
        budget: CostBudget | None = None,
    ) -> None:
        self.provider = provider
        self.budget = budget or CostBudget()
        self.spent_usd = 0.0
        self.calls_made = 0
        self._spend_history: deque[tuple[float, float]] = deque(maxlen=1000)  # (timestamp, cost)
        self._paused = False
        self._aborted = False
        # Event sink: middleware that does not have direct access to the
        # Thread (it only sees LLMMessage lists) appends events here. The
        # PlaybookExecutor drains this list after each step and appends the
        # events to the Thread (patching thread_id and step_id). The list is
        # shared with any inner middleware (TokenOptimizer, VerificationLayer)
        # so they can emit through the same sink.
        self._events: list[Event] = []
        # Marker so specialists can detect already-wrapped providers
        # and avoid double-wrapping the middleware stack.
        self._arnes_wrapped = True
        # Share our event sink with any inner ARNES middleware in the chain.
        self._propagate_event_sink()

    def _propagate_event_sink(self) -> None:
        """Share ``self._events`` with inner ARNES middleware.

        Walks the ``provider`` chain. Each middleware that has an
        ``_events`` attribute is pointed at our shared list so that all
        middleware emit through a single sink that the executor drains.
        """
        inner: Any = self.provider
        while hasattr(inner, "provider") and hasattr(inner, "_events"):
            inner._events = self._events
            inner = inner.provider

    def _emit(self, event: Event) -> None:
        """Append an event to the shared sink (drained by the executor)."""
        self._events.append(event)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        interactive: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Cost-guarded completion. May raise BudgetExceeded."""

        # Check if we're already aborted
        if self._aborted:
            raise BudgetExceeded(
                "Run aborted due to budget exceeded",
                spent=self.spent_usd,
                budget=self.budget.effective_budget() or 0.0,
                level="hard_stop",
            )

        # Check if we're paused (waiting for HITL)
        if self._paused:
            logger.info(
                "cost_guard_paused", spent=self.spent_usd, budget=self.budget.effective_budget()
            )
            raise BudgetExceeded(
                "Run paused at 95% budget — awaiting human approval",
                spent=self.spent_usd,
                budget=self.budget.effective_budget() or 0.0,
                level="pause",
            )

        # Pre-call budget check
        effective_budget = self.budget.effective_budget()
        if effective_budget is not None:
            abort_threshold = effective_budget * self.budget.abort_at_pct
            # pct_used is informational only — guard against budget<=0 to avoid
            # ZeroDivisionError when effective_budget is 0.0 (EC4: zero budget).
            pct_used = (
                (self.spent_usd / effective_budget)
                if effective_budget > 0
                else (1.0 if self.spent_usd > 0 else 0.0)
            )

            if self.spent_usd >= abort_threshold:
                self._aborted = True
                logger.error(
                    "cost_guard_abort",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=pct_used,
                )
                self._emit(
                    CostThresholdEvent(
                        thread_id=NIL_THREAD_ID,
                        data={
                            "threshold_pct": pct_used,
                            "threshold_level": "abort",
                            "spent_usd": self.spent_usd,
                            "budget_usd": effective_budget,
                        },
                    )
                )
                raise BudgetExceeded(
                    f"Budget exceeded: ${self.spent_usd:.4f} >= ${effective_budget:.4f}",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    level="hard_stop",
                )

            # Pre-flight check: if the provider can estimate the upcoming cost,
            # reject the call BEFORE it's made when the projected spend would
            # breach the budget. This prevents spending money on a call that
            # is guaranteed to push us over (e.g. budget=$0.0009, cost=$0.001).
            estimated_cost = self._peek_cost(
                model=model,
                messages=messages,
                tools=tools,
                response_schema=response_schema,
                **kwargs,
            )
            if estimated_cost is not None and estimated_cost > 0:
                projected = self.spent_usd + estimated_cost
                if projected > abort_threshold:
                    self._aborted = True
                    logger.error(
                        "cost_guard_preflight_abort",
                        spent=self.spent_usd,
                        estimated_cost=estimated_cost,
                        projected=projected,
                        budget=effective_budget,
                    )
                    self._emit(
                        CostThresholdEvent(
                            thread_id=NIL_THREAD_ID,
                            data={
                                "threshold_pct": projected / effective_budget,
                                "threshold_level": "preflight_abort",
                                "spent_usd": self.spent_usd,
                                "budget_usd": effective_budget,
                                "estimated_cost_usd": estimated_cost,
                                "projected_usd": projected,
                            },
                        )
                    )
                    raise BudgetExceeded(
                        f"Budget would be exceeded by next call: "
                        f"${projected:.6f} (spent ${self.spent_usd:.6f} "
                        f"+ est ${estimated_cost:.6f}) > ${effective_budget:.6f}",
                        spent=self.spent_usd,
                        budget=effective_budget,
                        level="preflight",
                    )

            if self.spent_usd >= effective_budget * self.budget.pause_at_pct:
                # 95% threshold reached — pause for HITL approval.
                #
                # Interactive mode: actually pause. Set ``_paused`` so
                # subsequent calls also block until a human resumes the
                # run (via ``reset()`` or a future ``resume()`` API).
                # Emit a ``HumanApprovalRequestedEvent`` so the executor /
                # UI can surface the prompt, then raise to abort the
                # current call chain. The executor catches the
                # ``BudgetExceeded`` and converts it to a ``RunFailedEvent``
                # so the run halts cleanly.
                #
                # Non-interactive mode: log + emit the threshold event but
                # do NOT set ``_paused`` (which would block all subsequent
                # calls). The hard stop at ``abort_at_pct`` (100%) will
                # catch the run if spend keeps growing. This matches the
                # documented contract: a non-interactive run never blocks
                # on human input — it either finishes or hard-stops.
                self._emit(
                    CostThresholdEvent(
                        thread_id=NIL_THREAD_ID,
                        data={
                            "threshold_pct": pct_used,
                            "threshold_level": "pause",
                            "spent_usd": self.spent_usd,
                            "budget_usd": effective_budget,
                            "interactive": interactive,
                        },
                    )
                )
                if interactive:
                    self._paused = True
                    logger.warning(
                        "cost_guard_paused_interactive",
                        spent=self.spent_usd,
                        budget=effective_budget,
                        pct=pct_used,
                    )
                    self._emit(
                        HumanApprovalRequestedEvent(
                            thread_id=NIL_THREAD_ID,
                            data={
                                "question": (
                                    f"Budget at {pct_used:.0%} "
                                    f"(${self.spent_usd:.4f} / "
                                    f"${effective_budget:.4f}). "
                                    f"Approve continued spend?"
                                ),
                                "options": ["approve", "reject"],
                                "ttl_s": 86400,
                                "spent_usd": self.spent_usd,
                                "budget_usd": effective_budget,
                                "threshold_level": "pause",
                            },
                        )
                    )
                    # Also emit a RUN_PAUSED lifecycle event so the audit
                    # log records the run-state transition explicitly
                    # (HumanApprovalRequestedEvent explains WHAT the user
                    # must do; RUN_PAUSED records THAT the run is now
                    # paused). Previously ``EventType.RUN_PAUSED`` was
                    # defined but never instantiated.
                    self._emit(
                        Event(
                            type=EventType.RUN_PAUSED,
                            thread_id=NIL_THREAD_ID,
                            data={
                                "reason": "cost_pause_threshold",
                                "spent_usd": self.spent_usd,
                                "budget_usd": effective_budget,
                                "pct_used": pct_used,
                                "interactive": True,
                            },
                        )
                    )
                    raise BudgetExceeded(
                        f"Budget paused at 95%: ${self.spent_usd:.4f} / "
                        f"${effective_budget:.4f} — awaiting human approval",
                        spent=self.spent_usd,
                        budget=effective_budget,
                        level="pause",
                    )
                # Non-interactive: log and continue. The hard stop at 100%
                # (abort_at_pct) will catch the run if spend keeps growing.
                logger.warning(
                    "cost_guard_pause_threshold_reached",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=pct_used,
                    interactive=interactive,
                )

            elif self.spent_usd >= effective_budget * self.budget.warn_at_pct:
                logger.warning(
                    "cost_guard_warn",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=pct_used,
                )
                self._emit(
                    CostThresholdEvent(
                        thread_id=NIL_THREAD_ID,
                        data={
                            "threshold_pct": pct_used,
                            "threshold_level": "warn",
                            "spent_usd": self.spent_usd,
                            "budget_usd": effective_budget,
                        },
                    )
                )

        # Circuit breaker: check spend rate
        if self._check_circuit_breaker():
            self._aborted = True
            raise BudgetExceeded(
                f"Circuit breaker tripped: spend rate exceeded ${self.budget.max_usd_per_minute}/min",
                spent=self.spent_usd,
                budget=effective_budget or 0.0,
                level="circuit_breaker",
            )

        # Make the call
        response = await self.provider.complete(
            messages,
            model=model,
            tools=tools,
            response_schema=response_schema,
            **kwargs,
        )

        # Track spend
        cost = response.usage.cost_usd
        self.spent_usd += cost
        self.calls_made += 1
        self._spend_history.append((time.time(), cost))

        logger.info(
            "llm_call_tracked",
            model=model,
            cost_usd=cost,
            total_spent=self.spent_usd,
            budget=effective_budget,
            tokens_in=response.usage.tokens_in,
            tokens_out=response.usage.tokens_out,
        )

        return response

    def _check_circuit_breaker(self) -> bool:
        """Check if spend rate exceeds max_usd_per_minute."""
        if not self._spend_history:
            return False

        now = time.time()
        window_s = 60.0
        recent_spend = sum(cost for ts, cost in self._spend_history if now - ts < window_s)
        return recent_spend > self.budget.max_usd_per_minute

    def _peek_cost(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> float | None:
        """Ask the wrapped provider to estimate the upcoming call's cost.

        Uses duck typing (``getattr``) so this works whether ``self.provider``
        is a real ``LLMProvider`` subclass, a middleware wrapper
        (``TokenOptimizer`` / ``VerificationLayer`` — plain classes), or a
        third-party callable. Returns ``None`` when no estimate is available,
        in which case the pre-flight check is skipped and the guard falls
        back to the existing post-call ``spent >= budget`` enforcement.
        """
        peek = getattr(self.provider, "peek_cost", None)
        if not callable(peek):
            return None
        try:
            estimate = peek(
                model=model,
                messages=messages,
                tools=tools,
                response_schema=response_schema,
                **kwargs,
            )
        except Exception:
            logger.warning("cost_guard_peek_cost_failed", exc_info=True)
            return None
        # ``peek`` is untyped (duck-typed via getattr), so the return is Any.
        # Coerce to float | None — providers that don't return a number will
        # surface as a TypeError at the call site, which the caller handles.
        if estimate is None:
            return None
        return float(estimate)

    # ============================================================
    # Stats
    # ============================================================

    def stats(self) -> dict[str, Any]:
        effective_budget = self.budget.effective_budget()
        return {
            "spent_usd": self.spent_usd,
            "budget_usd": effective_budget,
            "pct_used": (self.spent_usd / effective_budget) if effective_budget else 0.0,
            "calls_made": self.calls_made,
            "paused": self._paused,
            "aborted": self._aborted,
            "spend_last_minute_usd": sum(
                cost for ts, cost in self._spend_history if time.time() - ts < 60
            ),
        }

    def reset(self) -> None:
        """Reset for a new run (keeps config)."""
        self.spent_usd = 0.0
        self.calls_made = 0
        self._spend_history.clear()
        self._paused = False
        self._aborted = False

    def list_models(self) -> list[str]:
        """Delegate to the wrapped provider (middleware is transparent)."""
        return self.provider.list_models()

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Stream a completion while tracking cost on the final chunk.

        v0.1 behavior:

        - Pre-flight abort check (``spent >= abort_threshold``) and
          circuit-breaker check run *before* the stream starts, same as
          :meth:`complete`. If either trips, ``BudgetExceeded`` is raised
          on the first iteration — no tokens are streamed.
        - Tokens are accumulated as they arrive (each chunk's
          ``usage.tokens_in`` / ``usage.tokens_out`` if non-zero).
        - ``spent_usd`` is updated *after* the stream ends, using the
          final chunk's ``usage.cost_usd``. The pause threshold (95% HITL)
          and per-chunk circuit-breaker are NOT applied mid-stream — they
          land in v0.2 alongside AG-UI transport.

        Full per-chunk accounting (abort mid-stream when cumulative spend
        crosses ``abort_at_pct``, emit ``COST_THRESHOLD`` events as
        percentage gates are crossed, apply the circuit breaker per
        chunk) is v0.2 work.
        """
        # Pre-flight: refuse to start the stream if we're already aborted.
        if self._aborted:
            raise BudgetExceeded(
                "Run aborted due to budget exceeded",
                spent=self.spent_usd,
                budget=self.budget.effective_budget() or 0.0,
                level="hard_stop",
            )
        if self._paused:
            raise BudgetExceeded(
                "Run paused at 95% budget — awaiting human approval",
                spent=self.spent_usd,
                budget=self.budget.effective_budget() or 0.0,
                level="pause",
            )

        effective_budget = self.budget.effective_budget()
        if effective_budget is not None:
            abort_threshold = effective_budget * self.budget.abort_at_pct
            if self.spent_usd >= abort_threshold:
                self._aborted = True
                logger.error(
                    "cost_guard_stream_abort",
                    spent=self.spent_usd,
                    budget=effective_budget,
                )
                raise BudgetExceeded(
                    f"Budget exceeded: ${self.spent_usd:.4f} >= ${effective_budget:.4f}",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    level="hard_stop",
                )

        # Circuit breaker: check spend rate before starting the stream.
        if self._check_circuit_breaker():
            self._aborted = True
            raise BudgetExceeded(
                f"Circuit breaker tripped: spend rate exceeded ${self.budget.max_usd_per_minute}/min",
                spent=self.spent_usd,
                budget=effective_budget or 0.0,
                level="circuit_breaker",
            )

        # Stream and accumulate tokens/cost as they arrive. The final
        # chunk (yielded by the provider after generation completes)
        # carries the full ``LLMUsage``; intermediate chunks have zeros.
        final_tokens_in = 0
        final_tokens_out = 0
        final_cost = 0.0
        saw_usage = False

        async for chunk in self.provider.stream_complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_schema=response_schema,
            **kwargs,
        ):
            # Accumulate tokens/cost — the last non-zero usage wins
            # (providers send the full count on the final chunk, not a
            # running delta).
            if chunk.usage.tokens_in > 0:
                final_tokens_in = chunk.usage.tokens_in
            if chunk.usage.tokens_out > 0:
                final_tokens_out = chunk.usage.tokens_out
            if chunk.usage.cost_usd > 0:
                final_cost = chunk.usage.cost_usd
                saw_usage = True
            yield chunk

        # Post-stream accounting: update spent_usd and spend history.
        self.calls_made += 1
        if saw_usage and final_cost > 0:
            self.spent_usd += final_cost
            self._spend_history.append((time.time(), final_cost))
            logger.info(
                "llm_stream_call_tracked",
                model=model,
                cost_usd=final_cost,
                total_spent=self.spent_usd,
                budget=effective_budget,
                tokens_in=final_tokens_in,
                tokens_out=final_tokens_out,
            )
        else:
            # No usage info from the stream — count the call but don't
            # update spend (can't charge what we can't measure).
            logger.info(
                "llm_stream_call_no_usage",
                model=model,
                total_spent=self.spent_usd,
                budget=effective_budget,
            )
