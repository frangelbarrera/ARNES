"""
ARNES Specialist — a pre-built, role-based agent with tool-use loop.

A Specialist is a (system_prompt + tools + output_schema) bundle. The default
`run()` implementation executes a ReAct-style tool-use loop:

1. Format input as user message.
2. Call LLM with tools registered.
3. If LLM returns tool_calls, execute each tool and append results.
4. Repeat until LLM returns final response (no tool_calls) or max_iterations.
5. Validate response against output_schema (pydantic).
6. Return structured result.

Specialists are stateless. State lives in the Thread, not in the specialist.
"""

from __future__ import annotations

import json
from abc import ABC
from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import BudgetExceeded
from arnes.tools.base import Tool, ToolContext, ToolRegistry

logger = structlog.get_logger(__name__)


class SpecialistConfig(BaseModel):
    """Configuration for a specialist."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str  # e.g. "@planner"
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)  # tool names
    output_schema: dict[str, Any] | None = None  # JSON schema for structured output
    pydantic_model: type[BaseModel] | None = None  # Stronger than output_schema
    default_model: str | None = None  # If set, overrides the global default
    temperature: float = 0.0
    max_tokens: int | None = None
    max_iterations: int = 5  # ReAct loop limit


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
        """Default specialist run: ReAct tool-use loop + schema validation.

        Override this for custom logic if needed, but most specialists should
        use the default implementation.
        """
        # Build initial messages
        user_content = self._format_input(input_data)
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=self.config.system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

        # Get available tools (intersect config.tools with registry)
        available_tools: list[Tool] = []
        tool_schemas: list[dict[str, Any]] = []
        if tool_registry and self.config.tools:
            for tool_name in self.config.tools:
                tool = tool_registry.get(tool_name)
                if tool:
                    available_tools.append(tool)
                    tool_schemas.append(self._tool_to_schema(tool))

        # Build middleware-wrapped provider
        # The caller (Harness or PlaybookExecutor) is responsible for wrapping
        # the provider with the full middleware stack (CostGuard → Verification →
        # TokenOptimizer → provider). The specialist should NOT re-wrap.
        #
        # We detect already-wrapped providers by checking for the _arnes_wrapped
        # marker attribute that all our middleware classes set.
        wrapped_provider = provider

        # If the provider is not already wrapped, wrap it with the full stack.
        # This is a safety net — in normal usage, the caller always wraps first.
        if not getattr(provider, "_arnes_wrapped", False):
            from arnes.middleware.cost_guard import CostBudget, CostGuard
            from arnes.middleware.token_optimizer import TokenOptimizer
            from arnes.middleware.verification import VerificationConfig, VerificationLayer

            inner = TokenOptimizer(provider, enable_cache=True)
            if self.config.output_schema or self.config.pydantic_model:
                inner = VerificationLayer(
                    inner,
                    VerificationConfig(structured_outputs=True, refusal_pattern=True),
                )
            wrapped_provider = CostGuard(inner, budget=CostBudget(task_budget_usd=1.0))

        # ReAct tool-use loop
        total_usage = LLMUsage()
        all_tool_results: list[dict[str, Any]] = []
        model = self.config.default_model or "ollama/llama3.2"

        for iteration in range(self.config.max_iterations):
            try:
                response = await wrapped_provider.complete(
                    messages,
                    model=model,
                    tools=tool_schemas if tool_schemas else None,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    response_format={"type": "json_object"}
                    if (self.config.output_schema or self.config.pydantic_model)
                    else None,
                    response_schema=self.config.output_schema,
                    interactive=ctx.metadata.get("interactive", False),
                )
            except BudgetExceeded as e:
                logger.error(
                    "specialist_budget_exceeded", specialist=self.config.name, error=str(e)
                )
                return {
                    "specialist": self.config.name,
                    "success": False,
                    "error": f"Budget exceeded: {e}",
                    "budget_exceeded": True,
                }

            total_usage = total_usage + response.usage

            # If no tool calls, we have the final response
            if not response.tool_calls:
                break

            # Execute each tool call
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for tc in response.tool_calls:
                tool_result = await self._execute_tool_call(tc, available_tools, ctx)
                all_tool_results.append(tool_result)
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(tool_result, default=str),
                        tool_call_id=tc.get("id"),
                        name=tc.get("function", {}).get("name"),
                    )
                )

            # Continue loop for next iteration

        # Validate output against schema
        result = self._parse_and_validate_output(response, total_usage, all_tool_results)
        return result

    # ============================================================
    # Tool execution
    # ============================================================

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        available_tools: list[Tool],
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Execute a single tool call from the LLM."""
        function = tool_call.get("function", {})
        tool_name = function.get("name", "")
        args_str = function.get("arguments", "{}")

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            return {
                "tool": tool_name,
                "success": False,
                "error": f"Invalid JSON arguments: {args_str}",
            }

        # Find the tool
        tool = next((t for t in available_tools if t.name == tool_name), None)
        if not tool:
            return {
                "tool": tool_name,
                "success": False,
                "error": f"Tool '{tool_name}' not available",
            }

        # HITL check: if tool requires approval, fingerprint args and
        # compare against any pre-approved fingerprint (rug-pull defense).
        if tool.requires_approval:
            fingerprint = Tool.fingerprint(args)
            approved_fingerprints = ctx.metadata.get("_approved_fingerprints", {})

            if fingerprint in approved_fingerprints:
                # Pre-approved: execute
                logger.info(
                    "tool_approved_fingerprint_match",
                    tool=tool_name,
                    fingerprint=fingerprint,
                )
            elif not ctx.metadata.get("interactive", False):
                # Non-interactive and not pre-approved: auto-reject
                return {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Tool '{tool_name}' requires human approval. Set interactive=True.",
                    "fingerprint": fingerprint,
                }
            else:
                # Interactive: prompt for approval
                approval = await self._request_human_approval(tool_name, args, fingerprint, ctx)
                if not approval:
                    return {
                        "tool": tool_name,
                        "success": False,
                        "error": f"Human rejected tool call for '{tool_name}'.",
                        "fingerprint": fingerprint,
                    }
                # Record the approved fingerprint so we can detect rug-pull
                # if the LLM tries to call the same tool with different args
                approved_fingerprints[fingerprint] = tool_name

        try:
            result = await tool.execute(args, ctx)
            return {
                "tool": tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
            }
        except Exception as e:
            logger.exception("tool_execution_failed", tool=tool_name, error=str(e))
            return {
                "tool": tool_name,
                "success": False,
                "error": str(e),
            }

    async def _request_human_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        fingerprint: str,
        ctx: ToolContext,
    ) -> bool:
        """Request human approval for a tool call. Returns True if approved."""
        try:
            from rich.console import Console
            from rich.prompt import Confirm

            console = Console()
            console.print(f"\n[yellow]⚠ Approval required for tool:[/yellow] {tool_name}")
            console.print(f"  [dim]Args fingerprint:[/dim] {fingerprint}")
            console.print(f"  [dim]Args:[/dim] {json.dumps(args, indent=2, default=str)}")
            return Confirm.ask("  Approve this tool call?", default=False)
        except ImportError:
            logger.warning("rich not available — auto-rejecting tool call")
            return False

    # ============================================================
    # Schema validation
    # ============================================================

    def _parse_and_validate_output(
        self,
        response: LLMResponse,
        total_usage: LLMUsage,
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Parse LLM response and validate against pydantic_model or output_schema."""
        if not response.content:
            return {
                "specialist": self.config.name,
                "success": False,
                "error": "Empty response from LLM",
                "raw": None,
                "usage": total_usage.model_dump(),
                "tool_results": tool_results,
            }

        # Try JSON parse
        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            # If we expected JSON, this is a failure
            if self.config.output_schema or self.config.pydantic_model:
                return {
                    "specialist": self.config.name,
                    "success": False,
                    "error": f"LLM did not return valid JSON. Got: {response.content[:200]}",
                    "raw": response.content,
                    "usage": total_usage.model_dump(),
                    "tool_results": tool_results,
                }
            # If no schema expected, return raw content
            parsed = {"raw": response.content}

        # Strong validation with pydantic model if defined
        if self.config.pydantic_model:
            try:
                validated = self.config.pydantic_model.model_validate(parsed)
                return {
                    "specialist": self.config.name,
                    "success": True,
                    "output": validated.model_dump(),
                    "usage": total_usage.model_dump(),
                    "tool_results": tool_results,
                }
            except ValidationError as e:
                return {
                    "specialist": self.config.name,
                    "success": False,
                    "error": f"Output schema validation failed: {e}",
                    "raw": parsed,
                    "usage": total_usage.model_dump(),
                    "tool_results": tool_results,
                }

        # Weak validation with JSON schema (required fields only)
        if self.config.output_schema:
            required = self.config.output_schema.get("required", [])
            missing = [f for f in required if f not in parsed]
            if missing:
                return {
                    "specialist": self.config.name,
                    "success": False,
                    "error": f"Missing required fields: {missing}",
                    "raw": parsed,
                    "usage": total_usage.model_dump(),
                    "tool_results": tool_results,
                }

        return {
            "specialist": self.config.name,
            "success": True,
            "output": parsed,
            "usage": total_usage.model_dump(),
            "tool_results": tool_results,
        }

    # ============================================================
    # Helpers
    # ============================================================

    def _format_input(self, input_data: dict[str, Any]) -> str:
        """Format input dict as a user message."""
        return (
            f"Input:\n```json\n{json.dumps(input_data, indent=2, default=str)}\n```\n\n"
            f"Process this input according to your role. "
            f"Return JSON matching the schema. Use tools if needed."
        )

    def _tool_to_schema(self, tool: Tool) -> dict[str, Any]:
        """Convert an ARNES Tool to OpenAI tool schema for LLM."""
        args_schema = getattr(tool, "Args", None)
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": args_schema.model_json_schema()
                if args_schema
                else {"type": "object", "properties": {}},
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
    from arnes.specialists.coder import Coder
    from arnes.specialists.debugger import Debugger
    from arnes.specialists.planner import Planner
    from arnes.specialists.reviewer import Reviewer
    from arnes.specialists.tester import Tester

    for cls in [Planner, Coder, Reviewer, Tester, Debugger]:
        registry.register_class(cls)
    return registry
