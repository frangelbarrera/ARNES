"""ARNES Cost Guard — budget model + exception.

Owns:

- :class:`BudgetExceeded` — raised by :class:`arnes.middleware.cost_guard.CostGuard`
  when a budget threshold is breached.
- :class:`CostBudget` — the hierarchical budget model
  (org → project → agent → task) with temporal circuit breaker +
  threshold percentages.

The budget model + exception (pure data + a thin exception, no logic)
live in this sibling module so ``cost_guard.py`` stays focused on the
:class:`CostGuard` middleware (the LLMProvider wrapper that enforces
the budget). The two modules are imported together via
:mod:`arnes.middleware.cost_guard`'s re-exports so existing
``from arnes.middleware.cost_guard import CostBudget, BudgetExceeded``
imports keep working.
"""

from __future__ import annotations

from pydantic import BaseModel


class BudgetExceeded(Exception):
    """Raised when a budget is exceeded. Aborts the current run.

    Caught by :class:`arnes.playbooks.executor.PlaybookExecutor` and
    converted to a :class:`arnes.thread.events.RunFailedEvent`. The
    ``level`` attribute discriminates the breach type:

    - ``hard_stop`` — spend reached ``abort_at_pct`` (100 %).
    - ``preflight`` — pre-call projection showed the next call would
      overshoot the budget.
    - ``pause`` — spend reached ``pause_at_pct`` (95 %) in interactive
      mode (waiting for HITL approval).
    - ``circuit_breaker`` — spend rate exceeded ``max_usd_per_minute``.
    """

    def __init__(self, message: str, *, spent: float, budget: float, level: str) -> None:
        super().__init__(message)
        self.spent = spent
        self.budget = budget
        self.level = level


class CostBudget(BaseModel):
    """Hierarchical budget for a run.

    Each level inherits from its parent unless explicitly overridden:

    - ``org_budget_usd`` — total budget for the organization (None = unlimited).
    - ``project_budget_usd`` — budget for this project (inherits from org).
    - ``agent_budget_usd`` — budget for this agent (inherits from project).
    - ``task_budget_usd`` — budget for this specific task (inherits from agent).

    Plus temporal circuit breaker:

    - ``max_usd_per_minute`` — abort if spend rate exceeds this (DoW defense).
    - ``warn_at_pct`` — log a warning when spend crosses this fraction (default 75 %).
    - ``pause_at_pct`` — pause + emit HITL approval request when spend
      crosses this fraction (default 95 %).
    - ``abort_at_pct`` — hard stop when spend crosses this fraction
      (default 100 %).
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
        """Walk the hierarchy from most-specific to least-specific.

        Returns the first non-None USD budget found (task → agent →
        project → org), or ``None`` if every level is unlimited.
        """
        for v in [
            self.task_budget_usd,
            self.agent_budget_usd,
            self.project_budget_usd,
            self.org_budget_usd,
        ]:
            if v is not None:
                return v
        return None


__all__ = ["BudgetExceeded", "CostBudget"]
