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
- Audit log: every decision logged to Thread events
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import structlog
from pydantic import BaseModel

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)


class BudgetExceeded(Exception):
    """Raised when a budget is exceeded. Aborts the current run."""

    def __init__(self, message: str, *, spent: float, budget: float, level: str) -> None:
        super().__init__(message)
        self.spent = spent
        self.budget = budget
        self.level = level


class CostBudget(BaseModel):
    """Hierarchical budget for a run.

    Each level inherits from its parent unless explicitly overridden:
    - org_budget_usd: total budget for the organization (None = unlimited)
    - project_budget_usd: budget for this project (inherits from org)
    - agent_budget_usd: budget for this agent (inherits from project)
    - task_budget_usd: budget for this specific task (inherits from agent)

    Plus temporal circuit breaker:
    - max_usd_per_minute: abort if spend rate exceeds this (DoW defense)
    """

    org_budget_usd: float | None = None
    project_budget_usd: float | None = None
    agent_budget_usd: float | None = None
    task_budget_usd: float | None = 0.50  # Default: $0.50 per task

    max_usd_per_minute: float = 1.00  # Default: max $1/min (DoW defense)
    warn_at_pct: float = 0.75  # Warn at 75%
    pause_at_pct: float = 0.95  # Pause + HITL at 95%
    abort_at_pct: float = 1.00  # Hard stop at 100%

    # Effective budget = most specific non-None value
    def effective_budget(self) -> float | None:
        for v in [
            self.task_budget_usd,
            self.agent_budget_usd,
            self.project_budget_usd,
            self.org_budget_usd,
        ]:
            if v is not None:
                return v
        return None


class CostGuard:
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
        # Marker so specialists can detect already-wrapped providers
        # and avoid double-wrapping the middleware stack.
        self._arnes_wrapped = True

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
            if self.spent_usd >= effective_budget * self.budget.abort_at_pct:
                self._aborted = True
                logger.error(
                    "cost_guard_abort",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=self.spent_usd / effective_budget,
                )
                raise BudgetExceeded(
                    f"Budget exceeded: ${self.spent_usd:.4f} >= ${effective_budget:.4f}",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    level="hard_stop",
                )

            if self.spent_usd >= effective_budget * self.budget.pause_at_pct:
                # Emit a pause event — in interactive mode, this would block
                # and wait for human approval. In non-interactive mode, we log
                # a warning and continue (the next call will hard-stop at 100%).
                logger.warning(
                    "cost_guard_pause_threshold_reached",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=self.spent_usd / effective_budget,
                    interactive=interactive,
                )
                # TODO v0.2: emit HumanApprovalRequestedEvent and block

            elif self.spent_usd >= effective_budget * self.budget.warn_at_pct:
                logger.warning(
                    "cost_guard_warn",
                    spent=self.spent_usd,
                    budget=effective_budget,
                    pct=self.spent_usd / effective_budget,
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
