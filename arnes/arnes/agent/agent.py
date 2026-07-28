"""
ARNES Agent — high-level wrapper for simple use cases.

Most users will use the Playbook DSL for complex workflows. The Agent class
is for ad-hoc single-task invocation: "give this to a specialist and run".

Hello world:
    from arnes import Agent
    agent = Agent(model="ollama/llama3.2")
    result = await agent.run("@planner", {"task": "Plan a blog post about ARNES"})
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
from arnes.tools.base import ToolRegistry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)


class AgentConfig(BaseModel):
    """Configuration for an Agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "ollama/llama3.2"
    budget_usd: float = 0.50
    enable_cache: bool = True
    enable_verification: bool = True
    interactive: bool = False


class Agent:
    """High-level agent — wraps provider + middleware + specialist registry.

    For simple use cases:
        agent = Agent()
        result = await agent.run("@planner", {"task": "..."})

    For complex workflows, use PlaybookExecutor directly.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        provider: LLMProvider | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.provider = provider or get_provider(self.config.model)
        self.specialist_registry = specialist_registry or get_default_specialist_registry()
        self.tool_registry = tool_registry or get_default_registry()

    async def run(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a specialist with input data. Returns the result dict.

        Args:
            specialist: Name like "@planner" or "planner"
            input_data: Input dict for the specialist

        Returns:
            Result dict with keys: success, output, usage, error (if failed)
        """
        # Normalize specialist name
        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            available = self.specialist_registry.list()
            return {
                "success": False,
                "error": f"Specialist '{specialist}' not found. Available: {available}",
            }

        # Wrap provider with middleware
        # Order: cost_guard(verification(token_optimizer(provider)))
        provider: LLMProvider = TokenOptimizer(self.provider, enable_cache=self.config.enable_cache)
        if self.config.enable_verification:
            provider = VerificationLayer(
                provider,
                VerificationConfig(structured_outputs=True, refusal_pattern=True),
            )
        provider = CostGuard(provider, budget=CostBudget(task_budget_usd=self.config.budget_usd))

        thread = Thread.create()
        from arnes.tools.base import ToolContext

        ctx = ToolContext(
            thread_id=thread.id,
            specialist=specialist,
            metadata={"interactive": self.config.interactive},
        )

        try:
            result = await specialist_obj.run(
                input_data,
                ctx,
                provider=provider,
                tool_registry=self.tool_registry,
            )
            return result
        except Exception as e:
            logger.exception("agent_run_failed", specialist=specialist, error=str(e))
            return {"success": False, "error": str(e)}
