"""Middleware event draining + internal-key filtering for the executor.

- ``_drain_middleware_events``: pulls events that middleware (CostGuard,
  TokenOptimizer, VerificationLayer) emitted into the shared ``_events``
  sink during a step, patches their nil ``thread_id`` / ``step_id``
  placeholders, and appends them to the Thread. Idempotent: clears the
  sink after draining so the same events are not appended twice.
- ``_filter_internal_keys``: strips internal sentinel keys (``__*`` and
  ``_approved_fingerprints``) from the outputs dict before it is exposed
  on ``PlaybookRunResult.outputs``.
"""

from __future__ import annotations

from typing import Any

from arnes.middleware.cost_guard import CostGuard
from arnes.thread import Thread


def _drain_middleware_events(
    thread_holder: list[Thread],
    cost_guard: CostGuard,
    step_id: str,
) -> None:
    """Drain the middleware event sink and append events to the Thread.

    Middleware (CostGuard, TokenOptimizer, VerificationLayer) emit
    events to a shared ``_events`` list because they do not have direct
    access to the Thread. The events are created with a nil thread_id
    placeholder; here we patch the real thread_id and step_id and
    append them to the Thread.

    Idempotent: clears the sink after draining so the same events are
    not appended twice.
    """
    events = getattr(cost_guard, "_events", None)
    if not events:
        return

    thread_id = thread_holder[0].id
    for event in events:
        # Events are frozen pydantic models; use model_copy(update=...)
        # to set the real thread_id and step_id without mutating the
        # original (which may be referenced by middleware state).
        patched = event.model_copy(
            update={"thread_id": thread_id, "step_id": event.step_id or step_id}
        )
        thread_holder[0] = thread_holder[0].append(patched)

    events.clear()


def _filter_internal_keys(outputs: dict[str, Any]) -> dict[str, Any]:
    """Filter internal sentinel keys from outputs before returning to user.

    These keys are used internally by the executor for control flow
    (skip-until tracking, approved fingerprints, etc.) and should not
    be exposed in PlaybookRunResult.outputs.
    """
    return {
        k: v for k, v in outputs.items() if not k.startswith("__") and k != "_approved_fingerprints"
    }


# ============================================================
# Review-loop event emitters (actor-critic iterative refinement)
# ============================================================


def _emit_review_event(
    thread_holder: list[Thread],
    step_id: str,
    iteration: int,
    *,
    verdict: str,
    score: float | None = None,
    feedback: str = "",
    approved: bool = False,
) -> None:
    """Append a ``REVIEW_ITERATION`` event to the Thread.

    Records one critic evaluation within the review loop: the verdict
    (approve / request_changes / reject / unknown), optional numeric
    score, the critic's feedback text, and whether the loop stopped
    after this iteration.
    """
    from arnes.thread.events import Event, EventType

    thread = thread_holder[0]
    event = Event(
        type=EventType.REVIEW_ITERATION,
        thread_id=thread.id,
        step_id=step_id,
        data={
            "iteration": iteration,
            "verdict": verdict,
            "score": score,
            "feedback": feedback[:1000],
            "approved": approved,
        },
    )
    thread_holder[0] = thread.append(event)


def _emit_review_completed(
    thread_holder: list[Thread],
    step_id: str,
    *,
    iterations: int,
    approved: bool,
    final_verdict: str,
) -> None:
    """Append a ``REVIEW_COMPLETED`` event to the Thread.

    Records the final outcome of the review loop: how many iterations ran,
    whether the critic ultimately approved, and the final verdict.
    """
    from arnes.thread.events import Event, EventType

    thread = thread_holder[0]
    event = Event(
        type=EventType.REVIEW_COMPLETED,
        thread_id=thread.id,
        step_id=step_id,
        data={
            "iterations": iterations,
            "approved": approved,
            "final_verdict": final_verdict,
        },
    )
    thread_holder[0] = thread.append(event)
