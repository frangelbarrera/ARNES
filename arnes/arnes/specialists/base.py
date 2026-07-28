"""
ARNES Specialist — a pre-built, role-based agent.

A Specialist is a (system_prompt + tools + output_schema) bundle. It's NOT
a class hierarchy — it's a data class. Specialists are registered in a
SpecialistRegistry and invoked by name from playbooks.

Design:
- Each specialist has a single responsibility (SRP).
- The system_prompt is the specialist's "personality" — versioned, diffable.
- The tools list defines what the specialist CAN do (capability-based).
- The output_schema (pydantic) defines what the specialist MUST return.

Specialists are stateless. State lives in the Thread, not in the specialist.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, ConfigDict, Field

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import BudgetExceeded, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer
from arnes.tools.base import ToolContext, ToolRegistry

logger = structlog.get_logger(__name__)


class SpecialistConfig(BaseModel):
    """Configuration for a specialist."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str  # e.g. "@planner"
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)  # tool names
    output_schema: dict[str, Any] | None = None  # JSON schema for structured output
    default_model: str | None = None  # If set, overrides the global default
    temperature: float = 0.0
    max_tokens: int | None = None


class Specialist(ABC):
    """Base class for all ARNES specialists.

    To add a specialist:
        class MySpecialist(Specialist):
            config = SpecialistConfig(
                name="@my-specialist",
                description="Does X",
                system_prompt="You are an expert in X...",
                tools=["fs_read", "shell"],
                output_schema={"type": "object", "required": ["result"]},
            )

            async def run(self, input_data, ctx) -> dict:
                # Custom logic (optional — default uses LLM completion)
                return await super().run(input_data, ctx)
    """

    config: ClassVar[SpecialistConfig]

    # Auto-registry
    _registry: ClassVar[dict[str, type[Specialist]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "config") and cls.config.name:
            Specialist._registry[cls.config.name] = cls

    async def run(
        self,
        input_data: dict[str, Any],
        ctx: ToolContext,
        *,
        provider: LLMProvider,
        tool_registry: ToolRegistry | None = None,
    ) -> dict[str, Any]:
        """Default specialist run: format input → LLM call → return structured output.

        Override this for custom logic (multi-step, tool use loops, etc.).
        """
        # Build messages
        user_content = self._format_input(input_data)
        messages = [
            LLMMessage(role="system", content=self.config.system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

        # Wrap provider with middleware (cost guard + verification + token optimizer)
        # Order: cost_guard(verification(token_optimizer(provider)))
        # Cost guard is outermost so it can abort before any work
        optimized_provider: LLMProvider = TokenOptimizer(provider)
        if self.config.output_schema:
            optimized_provider = VerificationLayer(
                optimized_provider,
                VerificationConfig(structured_outputs=True, refusal_pattern=True),
            )
        guarded_provider = CostGuard(optimized_provider)

        # Make the call
        model = self.config.default_model or "ollama/llama3.2"
        try:
            response = await guarded_provider.complete(
                messages,
                model=model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"} if self.config.output_schema else None,
            )
        except BudgetExceeded as e:
            logger.error("specialist_budget_exceeded", specialist=self.config.name, error=str(e))
            return {
                "specialist": self.config.name,
                "success": False,
                "error": f"Budget exceeded: {e}",
                "budget_exceeded": True,
            }

        # Parse structured output
        result = self._parse_output(response)
        return result

    # ============================================================
    # Helpers
    # ============================================================

    def _format_input(self, input_data: dict[str, Any]) -> str:
        """Format input dict as a user message."""
        import json

        return (
            f"Input:\n```json\n{json.dumps(input_data, indent=2, default=str)}\n```\n\n"
            f"Process this input according to your role. Return JSON matching the schema."
        )

    def _parse_output(self, response: LLMResponse) -> dict[str, Any]:
        """Parse LLM response into structured dict."""
        import json

        if not response.content:
            return {
                "specialist": self.config.name,
                "success": False,
                "error": "Empty response from LLM",
                "raw": None,
            }

        # Try JSON parse
        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            # Fall back to raw content
            parsed = {"raw": response.content}

        return {
            "specialist": self.config.name,
            "success": True,
            "output": parsed,
            "usage": {
                "tokens_in": response.usage.tokens_in,
                "tokens_out": response.usage.tokens_out,
                "cost_usd": response.usage.cost_usd,
                "model": response.usage.model,
                "cached": response.usage.cached,
            },
        }


class SpecialistRegistry:
    """Registry of available specialists."""

    def __init__(self) -> None:
        self._specialists: dict[str, Specialist] = {}

    def register(self, specialist: Specialist) -> None:
        if not specialist.config.name:
            raise ValueError("Specialist must have a name in its config")
        self._specialists[specialist.config.name] = specialist

    def register_class(self, specialist_class: type[Specialist]) -> None:
        instance = specialist_class()
        self.register(instance)

    def get(self, name: str) -> Specialist | None:
        # Normalize: ensure leading @
        if not name.startswith("@"):
            name = "@" + name
        return self._specialists.get(name)

    def list(self) -> list[str]:
        return sorted(self._specialists.keys())

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def configs(self) -> list[SpecialistConfig]:
        return [s.config for s in self._specialists.values()]


def get_default_specialist_registry() -> SpecialistRegistry:
    """Return a registry with all built-in specialists registered."""
    registry = SpecialistRegistry()
    # Imports here to avoid circular dependencies at module load
    from arnes.specialists.coder import Coder
    from arnes.specialists.debugger import Debugger
    from arnes.specialists.planner import Planner
    from arnes.specialists.reviewer import Reviewer
    from arnes.specialists.tester import Tester

    for cls in [Planner, Coder, Reviewer, Tester, Debugger]:
        registry.register_class(cls)
    return registry
