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
