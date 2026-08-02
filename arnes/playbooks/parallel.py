"""Parallel-branch execution for ``PlaybookExecutor``.

Extracted from ``arnes.playbooks.executor`` to keep the executor file under
800 lines. The free function ``_execute_parallel_branch`` is called directly
from ``PlaybookExecutor._execute_step``.

The function takes the executor instance as its first argument (``executor``)
so it can invoke ``executor._execute_step`` recursively on each sub-step. It
is NOT a method on the class — keeping it as a free function means the
executor file stays focused on the sequential run / stream paths while the
parallel-branch complexity lives in its own module (with its own test
surface).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from arnes.middleware.cost_guard import CostGuard
from arnes.thread import Thread
from arnes.thread.events import Event, EventType

if TYPE_CHECKING:
    from arnes.playbooks.executor import PlaybookExecutor
    from arnes.playbooks.schema import Playbook, PlaybookStep


async def _execute_parallel_branch(
    executor: PlaybookExecutor,
    step: PlaybookStep,
    thread_holder: list[Thread],
    outputs: dict[str, Any],
    cost_guard: CostGuard,
    playbook: Playbook,
) -> dict[str, Any]:
    """Execute parallel sub-steps concurrently with ``asyncio.gather``.

    Each sub-step gets its OWN thread_holder (a copy of the parent thread
    at this point) so appends are isolated — no race on the shared
    ``thread_holder[0]`` reference. After all sub-steps complete, their
    event deltas are merged back into the parent thread_holder in
    timestamp order. This preserves the audit-log pattern while
    enabling true parallelism (the previous implementation ran sub-steps
    sequentially in a for-loop, which was correct but not concurrent).

    ``Thread.append`` mutates in place (O(1) per append, replacing the
    old O(N²) ``[*self.events, event]`` rebuild). Because the sub-step
    coroutines mutate their own Thread objects, we MUST give each one
    an isolated copy (with its own ``events`` list reference) — sharing
    the parent reference would let every sub-step clobber the others'
    appends. The copy is shallow on the list (a new list of the same
    Event references); Events themselves are frozen pydantic models so
    sharing the references is safe.

    The shared ``cost_guard._events`` sink is drained by each sub-step's
    own ``_execute_step`` call; because ``_drain_middleware_events`` is
    synchronous, drains run atomically in the single-threaded asyncio
    loop. An event emitted by sub-step B's specialist may end up drained
    into sub-step A's thread_holder, but each event carries its own
    ``step_id`` (set by ``_emit_assistant_message`` from the
    ``ToolContext``) so the merged audit log is still correctly
    attributed — the delta is just a container for the merge, not an
    authoritative attribution.

    Emits ``PARALLEL_BRANCH_STARTED`` before ``asyncio.gather`` and
    ``PARALLEL_BRANCH_COMPLETED`` after the merge so the audit log
    marks the parallel block boundaries (previously these event types
    were defined but never instantiated).
    """
    if not step.parallel:
        return {"success": False, "error": "No parallel steps defined"}

    # Snapshot the parent thread so each sub-step's delta is exactly
    # the events it appends beyond this point. The parent thread already
    # has the outer StepStartedEvent(parallel) appended by _execute_step.
    parent_snapshot = thread_holder[0]
    parent_event_count = len(parent_snapshot.events)

    # Emit PARALLEL_BRANCH_STARTED so the audit log records the
    # parallel-block boundary. ``step_id`` is the outer parallel step's
    # id; sub-step ids live inside the ``sub_steps`` payload.
    thread_holder[0] = thread_holder[0].append(
        Event(
            type=EventType.PARALLEL_BRANCH_STARTED,
            thread_id=parent_snapshot.id,
            step_id=step.id,
            data={
                "step_id": step.id,
                "sub_step_ids": [s.id for s in step.parallel],
                "sub_step_count": len(step.parallel),
            },
        )
    )
    # Re-snapshot so the STARTED event is part of every sub-step's
    # parent_event_count baseline (it belongs to the parent, not to
    # any individual sub-step's delta).
    parent_snapshot = thread_holder[0]
    parent_event_count = len(parent_snapshot.events)

    # Each sub-step gets its OWN Thread copy with a fresh events list.
    # ``Thread.append`` mutates in place, so without this copy every
    # sub-step would share the same parent.events list and clobber
    # each other. The new list contains the same Event references
    # (Events are frozen, so sharing is safe).
    sub_holders: list[list[Thread]] = [
        [Thread(id=parent_snapshot.id, events=list(parent_snapshot.events))] for _ in step.parallel
    ]

    # Run all sub-steps concurrently. return_exceptions=True so a single
    # failure doesn't cancel the others — every sub-step runs to
    # completion (or to its own failure) and we merge everything.
    coros = [
        executor._execute_step(
            sub_step,
            sub_holders[i],
            outputs,
            cost_guard,
            playbook,
        )
        for i, sub_step in enumerate(step.parallel)
    ]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    # Merge sub-step deltas back into the parent thread_holder in
    # timestamp order. Each delta is the events the sub-step appended
    # beyond the shared snapshot (StepStarted, AssistantMessage(s),
    # StepCompleted/Failed for the sub-step, plus any middleware events
    # it drained from the shared cost_guard sink).
    merged_events: list[Event] = []
    for holder in sub_holders:
        merged_events.extend(holder[0].events[parent_event_count:])
    # Stable sort by timestamp preserves intra-sub-step order for events
    # with identical timestamps (the natural audit order within a single
    # sub-step's lifecycle: Started → AssistantMessage → Completed).
    merged_events.sort(key=lambda e: e.timestamp)

    thread_holder[0] = thread_holder[0].extend(merged_events)

    # Emit PARALLEL_BRANCH_COMPLETED with the per-sub-step outcome so
    # the audit log marks the parallel-block end and records which
    # branches succeeded / failed.
    sub_step_outcomes: list[dict[str, Any]] = []
    all_success = True
    first_error: str | None = None
    outputs_map: dict[str, dict[str, Any]] = {}

    for sub_step, raw in zip(step.parallel, raw_results, strict=True):
        if isinstance(raw, BaseException):
            # A sub-step coroutine raised (shouldn't happen — _execute_step
            # catches exceptions — but defend against executor bugs).
            outputs_map[sub_step.id] = {
                "output": None,
                "success": False,
                "error": str(raw),
            }
            sub_step_outcomes.append(
                {"sub_step_id": sub_step.id, "success": False, "error": str(raw)}
            )
            all_success = False
            if first_error is None:
                first_error = str(raw)
        else:
            outputs_map[sub_step.id] = {
                "output": raw.get("output"),
                "success": raw.get("success", False),
                "error": raw.get("error"),
            }
            sub_step_outcomes.append(
                {
                    "sub_step_id": sub_step.id,
                    "success": raw.get("success", False),
                    "error": raw.get("error"),
                }
            )
            if not raw.get("success", False):
                all_success = False
                if first_error is None:
                    first_error = raw.get("error")

    thread_holder[0] = thread_holder[0].append(
        Event(
            type=EventType.PARALLEL_BRANCH_COMPLETED,
            thread_id=thread_holder[0].id,
            step_id=step.id,
            data={
                "step_id": step.id,
                "all_success": all_success,
                "sub_step_outcomes": sub_step_outcomes,
                "merged_event_count": len(merged_events),
            },
        )
    )

    result: dict[str, Any] = {
        "success": all_success,
        "output": outputs_map,
    }
    if first_error is not None:
        result["error"] = first_error
    return result
