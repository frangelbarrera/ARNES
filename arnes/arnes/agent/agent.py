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
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
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
        except BudgetExceeded as e:
            # Budget exceeded is a known, expected exception — return structured result
            logger.warning("harness_budget_exceeded", specialist=specialist, error=str(e))
            return {
                "success": False,
                "error": f"Budget exceeded: {e}",
                "specialist": specialist,
                "budget_exceeded": True,
            }
        except Exception as e:
            # Unexpected exceptions — log with full traceback for debugging
            logger.exception("harness_run_failed", specialist=specialist, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "specialist": specialist,
                "error_type": type(e).__name__,
            }

    async def stream(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ):
        """Stream a specialist's response token by token.

        Yields LLMResponse chunks as they arrive from the provider.
        The final chunk contains the full usage stats.

        Usage:
            async for chunk in harness.stream("@coder", {"spec": "..."}):
                print(chunk.content, end="", flush=True)
        """
        from collections.abc import AsyncIterator

        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            available = self.specialist_registry.list()
            yield {
                "success": False,
                "error": f"Specialist '{specialist}' not found. Available: {available}",
            }
            return

        # Build messages (same as specialist.run but without tool-use loop)
        import json

        user_content = json.dumps(input_data, indent=2, default=str)
        messages = [
            LLMMessage(role="system", content=specialist_obj.config.system_prompt),
            LLMMessage(
                role="user",
                content=f"Input:\n```json\n{user_content}\n```\n\nReturn JSON matching the schema.",
            ),
        ]

        model = specialist_obj.config.default_model or "ollama/llama3.2"

        # Wrap provider with middleware (same as run())
        wrapped_provider = TokenOptimizer(self.provider, enable_cache=self.config.enable_cache)
        if self.config.enable_verification:
            wrapped_provider = VerificationLayer(
                wrapped_provider,
                VerificationConfig(structured_outputs=True, refusal_pattern=True),
            )
        wrapped_provider = CostGuard(
            wrapped_provider, budget=CostBudget(task_budget_usd=self.config.budget_usd)
        )

        # Stream from the provider
        async for chunk in wrapped_provider.stream_complete(
            messages,
            model=model,
            temperature=specialist_obj.config.temperature,
            max_tokens=specialist_obj.config.max_tokens,
            response_format={"type": "json_object"}
            if specialist_obj.config.output_schema
            else None,
            response_schema=specialist_obj.config.output_schema,
        ):
            yield chunk


# Deprecated alias — will be removed in v0.2
# Kept for early adopters who used the alpha within hours of release
Agent = Harness
AgentConfig = HarnessConfig
