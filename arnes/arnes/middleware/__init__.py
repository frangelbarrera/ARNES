"""ARNES middleware — cross-cutting concerns for all LLM calls.

The :func:`build_middleware_stack` helper is the single source of truth for
the ``TokenOptimizer → VerificationLayer → CostGuard`` wrapping pattern.
Both :class:`arnes.agent.Harness` and
:class:`arnes.specialists.base.Specialist` call it; the duplicate inline
wrapping that grew across five call sites (R11 cleanup) has been removed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from arnes.llm.base import LLMProvider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer

__all__ = [
    "BudgetExceeded",
    "CostBudget",
    "CostGuard",
    "TokenOptimizer",
    "VerificationConfig",
    "VerificationLayer",
    "build_middleware_stack",
]


def build_middleware_stack(
    provider: LLMProvider,
    *,
    enable_cache: bool = True,
    enable_verification: bool = True,
    budget_usd: float = 0.50,
    output_schema: dict[str, Any] | None = None,
    pydantic_model: type[BaseModel] | None = None,
) -> LLMProvider:
    """Wrap a raw ``LLMProvider`` with the full ARNES middleware stack.

    Returns the wrapped provider in the canonical order (outermost first):

        CostGuard → VerificationLayer → TokenOptimizer → provider

    Parameters mirror the union of the previous inline call sites:

    - ``enable_cache``: forwarded to :class:`TokenOptimizer` (semantic cache).
    - ``enable_verification``: gate for :class:`VerificationLayer`. The layer
      is only added when this is ``True`` *and* a schema is available —
      structured-output forcing and refusal-pattern detection are only
      meaningful when the LLM is expected to return structured JSON.
    - ``budget_usd``: forwarded to :class:`CostBudget` as the per-task cap.
    - ``output_schema`` / ``pydantic_model``: the specialist's structured
      output contract. Either one is sufficient to enable the
      :class:`VerificationLayer`.

    The returned object sets the ``_arnes_wrapped`` marker (via
    :class:`CostGuard`) so downstream callers (e.g. ``Specialist.run``)
    can detect that the stack is already in place and skip re-wrapping.
    """
    inner: LLMProvider = TokenOptimizer(provider, enable_cache=enable_cache)
    has_schema = output_schema is not None or pydantic_model is not None
    if enable_verification and has_schema:
        inner = VerificationLayer(
            inner,
            VerificationConfig(structured_outputs=True, refusal_pattern=True),
        )
    return CostGuard(inner, budget=CostBudget(task_budget_usd=budget_usd))
