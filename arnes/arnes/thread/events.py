"""
ARNES event types — typed, immutable, pydantic-validated.

Events are the unit of state in ARNES. Every action (LLM call, tool call,
specialist invocation, cost threshold) is an event appended to a Thread.

This is the core of the stateless reducer pattern: (state, event) → state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """UTC timestamp, naive (avoids pydantic tz pitfalls)."""
    return datetime.now(UTC).replace(tzinfo=None)


class EventType(StrEnum):
    """All event types ARNES knows about. Extensible via SpecialistRegistry."""

    # Conversation
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # Tools
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Specialists
    SPECIALIST_INVOKED = "specialist_invoked"

    # Playbook steps
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"

    # Control flow
    CONDITIONAL_BRANCH = "conditional_branch"
    PARALLEL_BRANCH_STARTED = "parallel_branch_started"
    PARALLEL_BRANCH_COMPLETED = "parallel_branch_completed"

    # HITL
    HUMAN_APPROVAL_REQUESTED = "human_approval_requested"
    HUMAN_APPROVAL_RECEIVED = "human_approval_received"

    # Cost guard
    COST_THRESHOLD = "cost_threshold"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"

    # Token optimizer
    MODEL_ROUTED = "model_routed"
    CACHE_HIT = "cache_hit"
    CONTEXT_COMPACTED = "context_compacted"

    # Verification
    REFUSAL_TRIGGERED = "refusal_triggered"
    CONFIDENCE_SCORED = "confidence_scored"

    # Run lifecycle
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"


class Event(BaseModel):
    """Base event. All events are immutable and timestamped."""

    id: UUID = Field(default_factory=uuid4)
    type: EventType
    timestamp: datetime = Field(default_factory=_utc_now)
    thread_id: UUID
    step_id: str | None = None
    specialist: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def __str__(self) -> str:
        return f"[{self.timestamp.isoformat()}] {self.type.value}: {self.data}"


# ============================================================
# Conversation events
# ============================================================


class UserMessageEvent(Event):
    type: Literal[EventType.USER_MESSAGE] = EventType.USER_MESSAGE
    data: dict[str, Any]  # {"content": str, "role": "user"}


class AssistantMessageEvent(Event):
    type: Literal[EventType.ASSISTANT_MESSAGE] = EventType.ASSISTANT_MESSAGE
    data: dict[str, Any]  # {"content": str, "model": str, "tokens_in": int, "tokens_out": int}


# ============================================================
# Tool events
# ============================================================


class ToolCallEvent(Event):
    type: Literal[EventType.TOOL_CALL] = EventType.TOOL_CALL
    data: dict[str, Any]  # {"tool": str, "args": dict, "args_fingerprint": str}


class ToolResultEvent(Event):
    type: Literal[EventType.TOOL_RESULT] = EventType.TOOL_RESULT
    data: dict[str, Any]  # {"tool": str, "result": Any, "error": str | None}


# ============================================================
# Specialist events
# ============================================================


class SpecialistInvokedEvent(Event):
    type: Literal[EventType.SPECIALIST_INVOKED] = EventType.SPECIALIST_INVOKED
    data: dict[str, Any]  # {"specialist": str, "input": dict, "step_id": str}


# ============================================================
# Step lifecycle events
# ============================================================


class StepStartedEvent(Event):
    type: Literal[EventType.STEP_STARTED] = EventType.STEP_STARTED
    data: dict[str, Any]  # {"step_id": str, "specialist": str}


class StepCompletedEvent(Event):
    type: Literal[EventType.STEP_COMPLETED] = EventType.STEP_COMPLETED
    data: dict[
        str, Any
    ]  # {"step_id": str, "output": Any, "duration_s": float, "tokens_in": int, "tokens_out": int, "cost_usd": float}


class StepFailedEvent(Event):
    type: Literal[EventType.STEP_FAILED] = EventType.STEP_FAILED
    data: dict[str, Any]  # {"step_id": str, "error": str, "retry": bool}


# ============================================================
# Control flow events
# ============================================================


class ConditionalBranchEvent(Event):
    type: Literal[EventType.CONDITIONAL_BRANCH] = EventType.CONDITIONAL_BRANCH
    data: dict[str, Any]  # {"condition": str, "evaluated": bool, "branch": str}


# ============================================================
# HITL events
# ============================================================


class HumanApprovalRequestedEvent(Event):
    type: Literal[EventType.HUMAN_APPROVAL_REQUESTED] = EventType.HUMAN_APPROVAL_REQUESTED
    data: dict[str, Any]  # {"step_id": str, "question": str, "options": list, "ttl_s": int}


class HumanApprovalReceivedEvent(Event):
    type: Literal[EventType.HUMAN_APPROVAL_RECEIVED] = EventType.HUMAN_APPROVAL_RECEIVED
    data: dict[str, Any]  # {"step_id": str, "approved": bool, "comment": str | None}


# ============================================================
# Cost guard events
# ============================================================


class CostThresholdEvent(Event):
    type: Literal[EventType.COST_THRESHOLD] = EventType.COST_THRESHOLD
    data: dict[str, Any]  # {"threshold_pct": float, "spent_usd": float, "budget_usd": float}


# ============================================================
# Run lifecycle events
# ============================================================


class RunCompletedEvent(Event):
    type: Literal[EventType.RUN_COMPLETED] = EventType.RUN_COMPLETED
    data: dict[
        str, Any
    ]  # {"steps_executed": int, "duration_s": float, "total_tokens": int, "total_cost_usd": float}


class RunFailedEvent(Event):
    type: Literal[EventType.RUN_FAILED] = EventType.RUN_FAILED
    data: dict[str, Any]  # {"error": str, "step_id": str | None, "recoverable": bool}


# Discriminated union for type-safe event handling
EventUnion = (
    UserMessageEvent
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | SpecialistInvokedEvent
    | StepStartedEvent
    | StepCompletedEvent
    | StepFailedEvent
    | ConditionalBranchEvent
    | HumanApprovalRequestedEvent
    | HumanApprovalReceivedEvent
    | CostThresholdEvent
    | RunCompletedEvent
    | RunFailedEvent
    | Event
)
