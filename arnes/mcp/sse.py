"""ARNES MCP server — SSE (Server-Sent Events) live-UX module.

This module owns the SSE surface for the MCP HTTP transport:

- The SSE wire-format helper (:func:`format_sse_event`).
- The ambient heartbeat generator (:func:`sse_event_stream`) —
  used by ``GET /events`` and ``GET /sse``.
- The playbook-streaming generator (:func:`playbook_event_stream`)
  that drives ``POST /runs/stream`` by forwarding each event from
  :meth:`arnes.playbooks.executor.PlaybookExecutor.stream` as an SSE
  frame.

The ``GET /events`` route keeps its heartbeat-only behaviour (for
ambient subscription patterns that want a keep-alive channel); the
``POST /runs/stream`` route streams step-level transitions.

Wire format (stable across v0.2)::

    event: <event_type>\\n
    data: <json>\\n
    \\n

Clients written today keep working when v0.2 adds more event types
(MCP transport, HITL pause/resume, OTel export).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arnes.mcp.server import ArnesMCPServer
    from arnes.playbooks.executor import PlaybookExecutor
    from arnes.playbooks.schema import Playbook
    from arnes.thread.events import Event

# Heartbeat interval for the SSE endpoint. A small ``: ping`` comment is
# sent every N seconds to keep the connection alive through proxies that
# would otherwise close idle connections after 30-60 s.
SSE_HEARTBEAT_INTERVAL_S: float = 15.0

# How many "hello" events to emit before settling into heartbeat-only mode.
# The current stub emits 1 server-info event so a browser-based subscriber
# can verify the endpoint works end-to-end. The heartbeat loop is the
# ambient channel; ``POST /runs/stream`` is the per-run channel.
SSE_INITIAL_EVENT_COUNT: int = 1


def format_sse_event(event: str, data: Any) -> str:
    """Format a single SSE event frame as ``event: <name>\\ndata: <json>\\n\\n``.

    The trailing ``\\n\\n`` is part of the SSE wire format — it delimits one
    event from the next. Multi-line ``data`` is split across multiple
    ``data:`` lines per the spec so a single ``JSON.parse`` on the client
    reconstructs the full payload.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    # Spec: a newline in ``data`` becomes a separate ``data:`` line on the
    # wire; the client joins them with ``\\n`` before dispatching the event.
    lines = payload.split("\n")
    body = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{body}\n\n"


def _event_to_payload(event: Event) -> dict[str, Any]:
    """Convert a Thread event into a JSON-serialisable dict for SSE.

    Keeps the wire payload small: only the event-type discriminator and
    the most useful fields (``thread_id``, ``step_id``, ``specialist``,
    ``timestamp``, ``data``). The full event log stays in the Thread
    (clients fetch it via ``arnes_get_events`` if they need the
    complete transcript).
    """
    return {
        "event_type": event.type.value,
        "event_id": str(event.id),
        "thread_id": str(event.thread_id),
        "step_id": event.step_id,
        "specialist": event.specialist,
        "timestamp": event.timestamp.isoformat(),
        "data": event.data,
    }


def _run_result_to_payload(result: Any) -> dict[str, Any]:
    """Convert a :class:`PlaybookRunResult` into a JSON-serialisable dict.

    The full thread is omitted from the SSE payload (it can be huge for
    long playbooks). Callers that need the full thread fetch it via
    ``arnes_get_events(thread_id)`` after the stream ends.
    """
    return {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "steps_failed": result.steps_failed,
        "duration_s": result.duration_s,
        "total_tokens_in": result.total_tokens_in,
        "total_tokens_out": result.total_tokens_out,
        "total_cost_usd": result.total_cost_usd,
        "error": result.error,
        "outputs": {k: v for k, v in result.outputs.items() if not k.startswith("__")},
        "thread_id": str(result.thread.id) if result.thread is not None else None,
    }


async def sse_event_stream(
    server: ArnesMCPServer,
    *,
    heartbeat_interval_s: float = SSE_HEARTBEAT_INTERVAL_S,
    initial_event_count: int = SSE_INITIAL_EVENT_COUNT,
) -> AsyncIterator[str]:
    """Yield SSE-formatted frames for an HTTP ``GET /events`` subscriber.

    Ambient-channel behaviour (preserved for backwards compatibility):

    - Emits ``initial_event_count`` ``server_info`` events up-front so a
      browser-based client can confirm the endpoint works end-to-end.
    - Then enters an idle heartbeat loop that emits an SSE comment
      (``: ping\\n\\n``) every ``heartbeat_interval_s`` seconds. Comments
      are part of the SSE spec — they keep the connection alive through
      proxies without dispatching client-side event listeners.

    Use :func:`playbook_event_stream` for the per-run channel — that is
    what actually streams step-level transitions to a client. This
    generator is for ambient subscription patterns (presence,
    keep-alive, server-info discovery) only.

    The generator is cancellable: closing the HTTP response (client
    disconnect) cancels the asyncio task driving the iteration, which
    raises ``asyncio.CancelledError`` inside this function and exits
    cleanly. No cleanup is required.
    """
    for _ in range(initial_event_count):
        yield format_sse_event(
            "server_info",
            {
                "server": server.SERVER_INFO["name"],
                "version": server.SERVER_INFO["version"],
                "protocol": server.PROTOCOL_VERSION,
                "ts": time.time(),
            },
        )

    # Heartbeat loop — emit a comment every N seconds forever.
    while True:
        await asyncio.sleep(heartbeat_interval_s)
        # SSE comment frame: ``: <text>\n\n``. The leading colon tells
        # the client to ignore the line; the trailing blank line marks
        # the end of the (zero-length) event.
        yield ": ping\n\n"


async def playbook_event_stream(
    executor: PlaybookExecutor,
    playbook: Playbook,
    *,
    initial_input: dict[str, Any] | None = None,
    server: ArnesMCPServer | None = None,
    emit_initial_server_info: bool = True,
) -> AsyncIterator[str]:
    """Stream a playbook run as SSE frames.

    Wraps :meth:`arnes.playbooks.executor.PlaybookExecutor.stream` and
    converts each yielded item into an SSE frame:

    - Each :class:`arnes.thread.events.Event` becomes an SSE event whose
      ``event:`` field is the event-type value (``step_started``,
      ``step_completed``, ``run_completed``, ``run_failed``,
      ``cost_threshold``, ``assistant_message``, …). The ``data:`` field
      is the JSON-serialised event payload (see :func:`_event_to_payload`).
    - The final :class:`arnes.playbooks.result.PlaybookRunResult` becomes
      an SSE event of type ``run_result`` carrying the aggregate
      accounting (success flag, steps, tokens, cost, error, outputs).
      This is always the last frame.

    If ``server`` is provided and ``emit_initial_server_info`` is true,
    a single ``server_info`` event is emitted up-front so the client can
    confirm the endpoint works before the first step event arrives. The
    event is identical to the one emitted by :func:`sse_event_stream`.

    The stream ends after the ``run_result`` frame — no heartbeats.
    This is a finite stream: open a new ``POST /runs/stream`` connection
    for each run. For an ambient keep-alive channel, use ``GET /events``.

    Behaviour on failure:

    - If the run aborts mid-step (``BudgetExceeded``), the executor
      yields a ``RunFailedEvent`` followed by the final
      ``PlaybookRunResult(success=False)``. Both are forwarded as SSE
      frames — the client always sees the failure transition and the
      final accounting.
    - If the run completes successfully, the client sees
      ``step_completed`` per step, then ``run_completed``, then
      ``run_result``.

    Cancellation: closing the HTTP response (client disconnect)
    cancels the asyncio task driving the iteration. The executor's
    ``stream()`` generator receives ``asyncio.CancelledError`` on its
    next ``await`` and exits cleanly. No partial state is committed
    to disk; the in-memory Thread is discarded.
    """
    if emit_initial_server_info and server is not None:
        yield format_sse_event(
            "server_info",
            {
                "server": server.SERVER_INFO["name"],
                "version": server.SERVER_INFO["version"],
                "protocol": server.PROTOCOL_VERSION,
                "ts": time.time(),
            },
        )

    async for item in executor.stream(playbook, initial_input=initial_input):
        # The executor yields either an Event or a PlaybookRunResult. We
        # discriminate on the presence of ``type`` (Event has it;
        # PlaybookRunResult does not — it has ``success`` / ``outputs``).
        event_type = getattr(item, "type", None)
        if event_type is not None and hasattr(event_type, "value"):
            # It's a Thread Event — narrow the type via cast so mypy
            # accepts the ``_event_to_payload`` call (the executor's
            # stream() return type is a union of Event | PlaybookRunResult).
            yield format_sse_event(event_type.value, _event_to_payload(item))  # type: ignore[arg-type]
        else:
            # It's the final PlaybookRunResult.
            yield format_sse_event("run_result", _run_result_to_payload(item))


__all__ = [
    "SSE_HEARTBEAT_INTERVAL_S",
    "SSE_INITIAL_EVENT_COUNT",
    "format_sse_event",
    "playbook_event_stream",
    "sse_event_stream",
]
