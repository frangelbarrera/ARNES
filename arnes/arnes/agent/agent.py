"""
ARNES Harness — high-level wrapper for simple use cases.

NOTE: This was renamed from `Agent` to comply with manifesto declaration #2:
"ARNES nunca va a tener una clase llamada `Runnable`, `Chain`, `Workflow`
o `Agent`. Composición = funciones."

We keep `Agent` as a deprecated alias for backwards compatibility during
the alpha period.

Hello world:
    from arnes import Harness
    harness = Harness(model="ollama/llama3.2")
    result = await harness.run("@planner", {"task": "Plan a blog post about ARNES"})
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from arnes.llm.base import LLMProvider
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer
from arnes.specialists.base import (
    SpecialistRegistry,
    get_default_specialist_registry,
)
from arnes.thread import Thread
from arnes.tools.base import ToolContext, ToolRegistry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)


class HarnessConfig(BaseModel):
    """Configuration for a Harness."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "ollama/llama3.2"
    budget_usd: float = 0.50
    enable_cache: bool = True
    enable_verification: bool = True
    interactive: bool = False


class Harness:
    """High-level harness — wraps provider + middleware + specialist registry.

    The Harness wraps the provider ONCE with the full middleware stack
    (CostGuard → VerificationLayer → TokenOptimizer → provider). The wrapped
    provider is passed to the specialist, which does NOT re-wrap.

    For simple use cases:
        harness = Harness()
        result = await harness.run("@planner", {"task": "..."})

    For complex workflows, use PlaybookExecutor directly.
    """

    def __init__(
        self,
        config: HarnessConfig | None = None,
        *,
        provider: LLMProvider | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.provider = provider or get_provider(self.config.model)
        self.specialist_registry = specialist_registry or get_default_specialist_registry()
        self.tool_registry = tool_registry or get_default_registry()

    async def run(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a specialist with input data. Returns the result dict."""
        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            available = self.specialist_registry.list_names()
            return {
                "success": False,
                "error": f"Specialist '{specialist}' not found. Available: {available}",
            }

        # Wrap provider with middleware ONCE (order matters: cost outermost)
        wrapped_provider: LLMProvider = TokenOptimizer(
            self.provider, enable_cache=self.config.enable_cache
        )
        if self.config.enable_verification:
            wrapped_provider = VerificationLayer(
                wrapped_provider,
                VerificationConfig(structured_outputs=True, refusal_pattern=True),
            )
        wrapped_provider = CostGuard(
            wrapped_provider, budget=CostBudget(task_budget_usd=self.config.budget_usd)
        )

        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist=specialist,
            metadata={"interactive": self.config.interactive},
        )

        try:
            result = await specialist_obj.run(
                input_data,
                ctx,
                provider=wrapped_provider,
                tool_registry=self.tool_registry,
            )
            return result
        except Exception as e:
            logger.exception("harness_run_failed", specialist=specialist, error=str(e))
            return {"success": False, "error": str(e)}


# Deprecated alias — will be removed in v0.2
# Kept for early adopters who used the alpha within hours of release
Agent = Harness
AgentConfig = HarnessConfig
