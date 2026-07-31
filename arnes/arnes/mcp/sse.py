"""ARNES MCP server — SSE (Server-Sent Events) live-UX stub (R15).

Extracted from :mod:`arnes.mcp.server` in R15 to keep ``server.py`` under
the AGENTS.md 500-line rule. This module owns the SSE wire-format helper
and the async generator that drives the ``GET /events`` HTTP endpoint.

R15 stub behavior:

- Emits a single ``server_info`` event up-front so a browser-based
  subscriber can confirm the endpoint works end-to-end.
- Then idles on ``: ping`` heartbeats every 15 s to keep the connection
  alive through proxies.

v0.2 will replace the heartbeat loop with a real subscription to
:class:`arnes.playbooks.executor.PlaybookExecutor.stream` so subscribers
see step-level transitions in real time. The wire format
(``event: <name>\\ndata: <json>\\n\\n``) is stable across that upgrade —
clients written today keep working.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arnes.mcp.server import ArnesMCPServer

# Heartbeat interval for the SSE endpoint. A small ``: ping`` comment is
# sent every N seconds to keep the connection alive through proxies that
# would otherwise close idle connections after 30-60 s.
SSE_HEARTBEAT_INTERVAL_S: float = 15.0

# How many "hello" events to emit before settling into heartbeat-only mode.
# The current stub emits 1 server-info event so a browser-based subscriber
# can verify the endpoint works end-to-end. v0.2 will replace this with a
# real subscription to ``PlaybookExecutor.stream``.
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


async def sse_event_stream(
    server: ArnesMCPServer,
    *,
    heartbeat_interval_s: float = SSE_HEARTBEAT_INTERVAL_S,
    initial_event_count: int = SSE_INITIAL_EVENT_COUNT,
) -> AsyncIterator[str]:
    """Yield SSE-formatted frames for an HTTP ``GET /events`` subscriber.

    R15 stub behavior:

    - Emits ``initial_event_count`` ``server_info`` events up-front so a
      browser-based client can confirm the endpoint works end-to-end.
    - Then enters an idle heartbeat loop that emits an SSE comment
      (``: ping\\n\\n``) every ``heartbeat_interval_s`` seconds. Comments
      are part of the SSE spec — they keep the connection alive through
      proxies without dispatching client-side event listeners.

    v0.2 will replace the heartbeat loop with a real subscription to
    ``PlaybookExecutor.stream`` so subscribers see step-level transitions
    in real time. The wire format (``event: <name>\\ndata: <json>\\n\\n``)
    is stable across that upgrade — clients written today keep working.

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


__all__ = [
    "SSE_HEARTBEAT_INTERVAL_S",
    "SSE_INITIAL_EVENT_COUNT",
    "format_sse_event",
    "sse_event_stream",
]
