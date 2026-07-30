"""
ARNES Thread — the append-only event log.

A Thread is the unit of state in ARNES. It's a list of Events that can be
reduced to a current state. It's stateless in the sense that the same
sequence of events always produces the same state — the reducer is a pure
function over ``self.events``.

The Thread is also the unit of persistence and replay. A Thread can be
serialized to JSON, sent over the wire, persisted to SQLite/Postgres, and
replayed from any point.

Thread is **append-only**, NOT immutable: ``append()`` mutates the
internal ``events`` list in place and returns ``self`` for chaining. The
previous implementation rebuilt the entire list on every append
(``events=[*self.events, event]``), which made building a thread of N
events an O(N²) operation (1k events ≈ 43ms, 10k events would be
minutes). The in-place mutation is O(1) per append and is safe because
ARNES is single-threaded async — coroutine interleaving cannot tear a
``list.append`` (it's atomic in CPython) and ``_drain_middleware_events``
runs synchronously inside each step.

Callers that previously relied on the immutability guarantee (e.g. the
parallel-branch executor snapshotting the parent thread) must explicitly
copy the Thread before sharing it across coroutines that mutate it.
``_execute_parallel`` does this via ``Thread(id=..., events=list(...))``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from arnes.thread.events import Event, EventType


class Thread(BaseModel):
    """Append-only event log.

    Usage:
        thread = Thread.create()
        thread.append(UserMessageEvent(thread_id=thread.id, data={"content": "Hello"}))
        for event in thread.events:
            print(event)

    Thread is append-only: ``append()`` mutates ``self.events`` in place
    and returns ``self`` (so ``thread = thread.append(e)`` is a no-op
    reassignment but still reads naturally for chaining). This is NOT
    thread-safe; ARNES is single-threaded async and the executor's
    parallel-branch path explicitly copies the Thread before sharing it
    across coroutines.
    """

    id: UUID = Field(default_factory=uuid4)
    events: list[Event] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    # ============================================================
    # Constructors
    # ============================================================

    @classmethod
    def create(cls) -> Thread:
        """Create a new empty thread."""
        return cls(id=uuid4(), events=[])

    @classmethod
    def from_events(cls, events: Sequence[Event]) -> Thread:
        """Create a thread from a sequence of events (replay)."""
        if not events:
            return cls.create()
        return cls(id=events[0].thread_id, events=list(events))

    # ============================================================
    # Mutation (in place, returns self for chaining)
    # ============================================================

    def append(self, event: Event) -> Thread:
        """Append an event in place, returning ``self`` for chaining.

        O(1) per call. The previous implementation rebuilt the entire
        events list on every append (``events=[*self.events, event]``),
        making N appends an O(N²) operation. Mutating in place is safe
        because ARNES is single-threaded async; callers that need to
        isolate a Thread across coroutines (e.g. parallel branch
        sub-steps) must explicitly copy it before sharing.
        """
        if event.thread_id != self.id:
            raise ValueError(
                f"Event thread_id {event.thread_id} does not match Thread id {self.id}"
            )
        self.events.append(event)
        return self

    def extend(self, events: Sequence[Event]) -> Thread:
        """Append multiple events in place, returning ``self`` for chaining."""
        for event in events:
            if event.thread_id != self.id:
                raise ValueError(
                    f"Event thread_id {event.thread_id} does not match Thread id {self.id}"
                )
            self.events.append(event)
        return self

    # ============================================================
    # Iteration / access
    # ============================================================

    def __iter__(self) -> Iterator[Event]:  # type: ignore[override]
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, index: int) -> Event:
        return self.events[index]

    def last(self) -> Event | None:
        return self.events[-1] if self.events else None

    def filter_by_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self.events if e.type == event_type]

    def filter_by_step(self, step_id: str) -> list[Event]:
        return [e for e in self.events if e.step_id == step_id]

    def filter_by_specialist(self, specialist: str) -> list[Event]:
        return [e for e in self.events if e.specialist == specialist]

    # ============================================================
    # State reduction (stateless reducer pattern)
    # ============================================================

    def reduce(self) -> dict[str, Any]:
        """Reduce the event log to a current state dict.

        This is the pure function (state, event) → state. Given the same
        sequence of events, it always produces the same state.
        """
        state: dict[str, Any] = {
            "messages": [],
            "steps": {},
            "specialists_invoked": [],
            "tools_called": [],
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost_usd": 0.0,
            "status": "pending",
            "current_step_id": None,
            "human_approval_pending": None,
            "errors": [],
        }

        for event in self.events:
            state = _reduce_event(state, event)

        return state

    # ============================================================
    # Persistence
    # ============================================================

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> Thread:
        """Deserialize from JSON string."""
        return cls.model_validate_json(json_str)

    def save(self, path: str | Path) -> None:
        """Save to disk as JSON."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Thread:
        """Load from disk."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def to_markdown(self) -> str:
        """Render the thread as an audit-friendly markdown bitácora."""
        lines: list[str] = []
        lines.append(f"# Bitácora ARNES — Thread {self.id}")
        lines.append("")
        lines.append(f"**Total events:** {len(self.events)}")
        lines.append("")

        for event in self.events:
            lines.append(f"## [{event.timestamp.isoformat()}] {event.type.value}")
            if event.step_id:
                lines.append(f"**Step:** `{event.step_id}`")
            if event.specialist:
                lines.append(f"**Specialist:** `{event.specialist}`")
            lines.append("")
            if event.data:
                lines.append("```json")
                lines.append(json.dumps(event.data, indent=2, default=str, ensure_ascii=False))
                lines.append("```")
                lines.append("")

        return "\n".join(lines)


# ============================================================
# Reducer
# ============================================================


def _reduce_event(state: dict[str, Any], event: Event) -> dict[str, Any]:
    """Pure function (state, event) → state."""
    if event.type == EventType.USER_MESSAGE:
        state["messages"].append({"role": "user", "content": event.data.get("content", "")})

    elif event.type == EventType.ASSISTANT_MESSAGE:
        state["messages"].append(
            {
                "role": "assistant",
                "content": event.data.get("content", ""),
                "model": event.data.get("model", ""),
            }
        )
        # NOTE: token/cost accumulation for AssistantMessageEvent is intentionally
        # omitted to avoid double-counting. The authoritative per-step token/cost
        # lives on the StepCompletedEvent (one per step, summing every LLM call
        # the specialist made inside that step). AssistantMessageEvent still
        # carries tokens_in/out/cost_usd in its ``data`` payload for visibility
        # in the bitácora — it's just not what the reducer sums.

    elif event.type == EventType.TOOL_CALL:
        state["tools_called"].append(
            {"tool": event.data.get("tool"), "args_fingerprint": event.data.get("args_fingerprint")}
        )

    elif event.type == EventType.STEP_STARTED:
        step_id = event.data.get("step_id", event.step_id or "unknown")
        state["current_step_id"] = step_id
        state["steps"][step_id] = {"status": "running", "started_at": event.timestamp.isoformat()}

    elif event.type == EventType.STEP_COMPLETED:
        step_id = event.data.get("step_id", event.step_id or state["current_step_id"])
        if step_id in state["steps"]:
            state["steps"][step_id].update(
                {
                    "status": "completed",
                    "output": event.data.get("output"),
                    "duration_s": event.data.get("duration_s", 0.0),
                    "tokens_in": event.data.get("tokens_in", 0),
                    "tokens_out": event.data.get("tokens_out", 0),
                    "cost_usd": event.data.get("cost_usd", 0.0),
                    "completed_at": event.timestamp.isoformat(),
                }
            )
        # Authoritative token/cost accumulator: sum from StepCompletedEvent.
        # This avoids double-counting with AssistantMessageEvent (which fires
        # once per LLM call inside a step) — StepCompletedEvent is the
        # per-step aggregate produced by the executor from the specialist's
        # total usage.
        state["total_tokens_in"] += event.data.get("tokens_in", 0)
        state["total_tokens_out"] += event.data.get("tokens_out", 0)
        state["total_cost_usd"] += event.data.get("cost_usd", 0.0)

    elif event.type == EventType.STEP_FAILED:
        step_id = event.data.get("step_id", event.step_id or state["current_step_id"])
        if step_id in state["steps"]:
            state["steps"][step_id].update(
                {
                    "status": "failed",
                    "error": event.data.get("error"),
                    "retry": event.data.get("retry", False),
                }
            )
        state["errors"].append(
            {"step_id": step_id, "error": event.data.get("error", "Unknown error")}
        )

    elif event.type == EventType.SPECIALIST_INVOKED:
        state["specialists_invoked"].append(event.specialist or event.data.get("specialist"))

    elif event.type == EventType.HUMAN_APPROVAL_REQUESTED:
        state["human_approval_pending"] = event.data.get("step_id")

    elif event.type == EventType.HUMAN_APPROVAL_RECEIVED:
        state["human_approval_pending"] = None

    elif event.type == EventType.RUN_COMPLETED:
        state["status"] = "completed"
        state["current_step_id"] = None

    elif event.type == EventType.RUN_FAILED:
        state["status"] = "failed"

    elif event.type == EventType.RUN_PAUSED:
        state["status"] = "paused"

    elif event.type == EventType.RUN_RESUMED:
        state["status"] = "running"

    return state
