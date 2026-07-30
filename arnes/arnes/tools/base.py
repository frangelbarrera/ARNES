"""
ARNES Tool — structured outputs as the unit of agent action.

A Tool is a typed, validated function that an agent can call. Tools are
*NOT* Python callables — they are pydantic-validated schemas that produce
structured results. This is Factor 2 of the 12-factor-agents manifesto.

Key design:
- Each tool declares its args schema (pydantic) and result schema (pydantic).
- Tools are registered via `__init_subclass__` — adding a tool = 1 file.
- Tool args are *fingerprinted* (hash) so HITL can detect rug-pull (LLM
  asking approval with args X but executing with args Y).
- Tool execution is sandboxed (Docker Tier 1 by default).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ToolError(Exception):
    """Raised when a tool execution fails."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class ToolResult(BaseModel):
    """Structured result of a tool call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tool: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, tool: str, output: Any, *, duration_s: float = 0.0, **meta: Any) -> ToolResult:
        return cls(
            tool=tool,
            success=True,
            output=output,
            duration_s=duration_s,
            metadata=meta,
        )

    @classmethod
    def fail(cls, tool: str, error: str, *, duration_s: float = 0.0, **meta: Any) -> ToolResult:
        return cls(
            tool=tool,
            success=False,
            error=error,
            duration_s=duration_s,
            metadata=meta,
        )


class Tool(ABC, BaseModel):
    """Base class for all ARNES tools.

    To add a tool:
        class MyTool(Tool):
            name: ClassVar[str] = "my_tool"
            description: ClassVar[str] = "Does X"

            class Args(BaseModel):
                input_value: str

            async def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
                ...

    The tool is auto-registered via __init_subclass__.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Class-level metadata (set by subclasses)
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires_approval: ClassVar[bool] = False  # HITL gate before execution
    sandbox_tier: ClassVar[int | None] = None  # None = no sandbox required

    # Auto-registry
    _registry: ClassVar[dict[str, type[Tool]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name and cls.name not in cls._registry:
            cls._registry[cls.name] = cls

    # ============================================================
    # Fingerprint (rug-pull defense)
    # ============================================================

    @staticmethod
    def fingerprint(args: dict[str, Any]) -> str:
        """Stable hash of args. Used for HITL rug-pull detection.

        The LLM asks approval with args X (fingerprint F1). At execution,
        we re-hash the actual args. If F2 != F1, abort.
        """
        canonical = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    # ============================================================
    # Execution contract
    # ============================================================

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must be idempotent for retry safety."""
        raise NotImplementedError

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate args against the tool's Args schema (if defined)."""
        args_schema = getattr(self, "Args", None)
        if args_schema is None:
            return args
        # Pydantic validation
        validated = args_schema.model_validate(args)
        # ``model_dump`` returns a dict[str, Any] for a pydantic BaseModel, but
        # ``args_schema`` is duck-typed via getattr so the return type is Any.
        dumped = validated.model_dump(exclude_none=True)
        assert isinstance(dumped, dict)
        return dumped


# ============================================================
# Tool context — passed to every tool execution
# ============================================================


class ToolContext(BaseModel):
    """Context passed to every tool execution. Carries thread state, sandbox
    config, secret broker, and logger."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    thread_id: UUID
    step_id: str | None = None
    specialist: str | None = None
    working_dir: str = "."
    sandbox_enabled: bool = False
    sandbox_container: str | None = None
    secret_broker: Any = None  # SecretBroker instance (avoids circular import)
    budget_remaining_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Registry
# ============================================================


class ToolRegistry:
    """Runtime registry of available tools. Supports both built-in and
    plugin tools discovered via entry_points."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        self._tools[tool.name] = tool

    def register_class(self, tool_class: type[Tool]) -> None:
        instance = tool_class()
        self.register(instance)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """Return a sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> list[dict[str, Any]]:
        """Return JSON schemas for all registered tools (for LLM tool_use)."""
        result = []
        for name, tool in self._tools.items():
            args_schema = getattr(tool, "Args", None)
            schema = {
                "name": name,
                "description": tool.description,
                "requires_approval": tool.requires_approval,
                "args": args_schema.model_json_schema() if args_schema else {},
            }
            result.append(schema)
        return result


# ============================================================
# Tool execution wrapper
# ============================================================


ToolExecutor = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]
