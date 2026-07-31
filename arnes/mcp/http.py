"""ARNES MCP server — HTTP transport.

Owns the HTTP transport for :class:`arnes.mcp.server.ArnesMCPServer`:

- :func:`serve_http` — bind an aiohttp app, register routes, run forever.
- :class:`_RateLimiter` — sliding-window per-IP rate limiter (100 req/min).
- :func:`_constant_time_eq` — constant-time bearer-token comparison.
- Constants ``_MAX_REQUEST_BYTES`` (1 MiB body cap), ``_RATE_LIMIT_RPM``.

The HTTP transport (and its security helpers) lives in this sibling
module so ``server.py`` stays focused on the JSON-RPC dispatcher and
the path-validation guard.

Routes registered on the aiohttp app:

- ``POST /`` and ``POST /mcp`` — JSON-RPC over HTTP.
- ``GET /events`` and ``GET /sse`` — SSE ambient channel
  (heartbeat-only). See :func:`arnes.mcp.sse.sse_event_stream`.
- ``POST /runs/stream`` — SSE per-run channel. Streams step-level
  events from :meth:`PlaybookExecutor.stream` for a single playbook
  run. See :func:`arnes.mcp.sse.playbook_event_stream`.

All routes run through :func:`auth_and_limits_middleware` which
enforces bearer-token auth, request-size cap, and per-IP rate
limiting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from arnes.llm.factory import get_provider
from arnes.mcp.sse import format_sse_event, playbook_event_stream, sse_event_stream
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor

if TYPE_CHECKING:
    from arnes.mcp.server import ArnesMCPServer

logger = structlog.get_logger(__name__)

# ============================================================
# HTTP transport security constants
# ============================================================

_MAX_REQUEST_BYTES = 1024 * 1024  # 1 MiB body cap
_RATE_LIMIT_RPM = 100  # max requests per minute per IP


class _RateLimiter:
    """Sliding-window per-IP rate limiter (in-memory, single-process).

    Adequate for the simple HTTP transport shipped here. For multi-worker
    deployments, swap this for a Redis-backed limiter.
    """

    def __init__(self, max_requests: int, window_s: float) -> None:
        self._max = max_requests
        self._window = window_s
        self._hits: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        bucket = self._hits.get(ip, [])
        # Drop entries outside the window.
        cutoff = now - self._window
        bucket = [t for t in bucket if t >= cutoff]
        if len(bucket) >= self._max:
            self._hits[ip] = bucket
            return False
        bucket.append(now)
        self._hits[ip] = bucket
        return True


_rate_limiter = _RateLimiter(max_requests=_RATE_LIMIT_RPM, window_s=60.0)


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks on the token.

    Falls back to ``hmac.compare_digest`` when available.
    """
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ============================================================
# HTTP transport — aiohttp app + route handlers
# ============================================================


async def serve_http(  # noqa: PLR0915 - HTTP transport + 4 route handlers in one function
    server: ArnesMCPServer, host: str = "127.0.0.1", port: int = 8765
) -> None:
    """Run the MCP server over HTTP (simple POST /endpoint).

    This is a minimal HTTP server for testing. For production use the
    official MCP SDK with proper SSE transport.

    SECURITY:
    - If env var ``ARNES_MCP_TOKEN`` is set, every request must carry
      ``Authorization: Bearer <token>``. Constant-time comparison is used.
    - If no token is configured, the server refuses to bind on anything
      other than ``127.0.0.1`` / ``::1`` (loopback only) — binding to
      ``0.0.0.0`` without auth would expose playbook execution to the
      local network.
    - Rate limited: at most ``_RATE_LIMIT_RPM`` requests per minute per
      client IP (sliding window, in-memory).
    - Request body size capped at ``_MAX_REQUEST_BYTES`` (1 MiB).
    """
    # Import inside the function so ``aiohttp`` stays an optional
    # dependency (the stdio transport does not need it).
    from aiohttp import web

    # Import the path-validation guard from ``mcp.server`` here (rather
    # than at module top) to avoid a circular import: ``mcp.server``
    # imports ``serve_http`` from this module in its
    # ``_attach_serve_methods`` setup.
    from arnes.mcp.server import _validate_playbook_path

    token = os.environ.get("ARNES_MCP_TOKEN")
    if not token:
        # No token configured → enforce loopback-only binding.
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(
                "ARNES_MCP_TOKEN is not set. Refusing to start HTTP server on "
                f"non-loopback host '{host}'. Set ARNES_MCP_TOKEN or bind to "
                "127.0.0.1 / ::1."
            )

    @web.middleware
    async def auth_and_limits_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        # --- 1. Bearer token authentication ---
        if token:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return web.json_response(
                    {"error": "Missing or malformed Authorization header"}, status=401
                )
            provided = auth_header[len("Bearer ") :]
            # Constant-time comparison to avoid timing side channels.
            if not _constant_time_eq(provided, token):
                return web.json_response({"error": "Invalid token"}, status=401)

        # --- 2. Request size limit ---
        cl = request.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > _MAX_REQUEST_BYTES:
                    return web.json_response({"error": "Request body too large"}, status=413)
            except ValueError:
                return web.json_response({"error": "Invalid Content-Length"}, status=400)

        # --- 3. Rate limiting (per IP, sliding window) ---
        client_ip = request.remote or "unknown"
        if not _rate_limiter.allow(client_ip):
            return web.json_response(
                {"error": "Rate limit exceeded. Max 100 requests/minute."}, status=429
            )

        return await handler(request)

    async def handle(request: web.Request) -> web.Response:
        try:
            # Cap the actual body read size too (Content-Length can lie / be absent).
            raw = await request.content.read(_MAX_REQUEST_BYTES + 1)
            if len(raw) > _MAX_REQUEST_BYTES:
                return web.json_response({"error": "Request body too large"}, status=413)
            try:
                request_data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return web.json_response({"error": f"Invalid JSON: {e}"}, status=400)
            response = await server.handle_request(request_data)
            return web.json_response(response)
        except Exception:
            # Avoid leaking internal details (paths, stack fragments) to a
            # remote caller — log the full error, return a generic message.
            logger.exception("mcp_http_request_failed")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_sse(request: web.Request) -> web.StreamResponse:
        """SSE endpoint — ``GET /events`` (ambient channel).

        Returns a ``text/event-stream`` response that streams
        ``event: <name>\\ndata: <json>\\n\\n`` frames via
        :func:`sse_event_stream`. The ambient channel emits a single
        ``server_info`` event up-front, then idles on ``: ping``
        heartbeats. For real step-level transitions, use
        ``POST /runs/stream`` (see :func:`handle_sse_run`).

        Auth + rate-limit rules from the middleware still apply (the
        middleware runs on every route registered on ``app``, including
        this GET). The body-size cap is irrelevant for a GET (no body).
        """
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                # ``X-Accel-Buffering: no`` disables proxy buffering on
                # nginx — without it, the proxy holds the stream open
                # and the browser never receives the events until the
                # buffer fills or the connection closes.
                "X-Accel-Buffering": "no",
                # Opt out of HTTP/2 connection coalescing so each
                # browser tab gets its own stream — without this, a
                # second ``EventSource`` on the same origin may
                # silently share the first tab's stream.
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        # Drive ``sse_event_stream`` and forward each frame to the client.
        # If the client disconnects, ``resp.write`` raises
        # ``ConnectionResetError`` — we let the exception bubble out of
        # the ``async for`` so aiohttp tears down the response cleanly.
        try:
            async for frame in sse_event_stream(server):
                await resp.write(frame.encode("utf-8"))
        except (ConnectionResetError, asyncio.CancelledError):
            # Client disconnected — exit cleanly.
            pass
        return resp

    async def handle_sse_run(request: web.Request) -> web.StreamResponse:
        """SSE endpoint — ``POST /runs/stream`` (per-run channel).

        Accepts a JSON body ``{"path": ..., "input"?: ..., "model"?: ...,
        "budget_usd"?: ...}`` and streams the playbook run as a finite
        sequence of SSE frames: one ``server_info`` event up-front, one
        frame per Thread event (``step_started``, ``step_completed``,
        ``run_completed`` / ``run_failed``, …), and a final
        ``run_result`` frame carrying the aggregate accounting. The
        connection closes after the ``run_result`` frame.

        Wires :func:`arnes.mcp.sse.playbook_event_stream` to
        :meth:`arnes.playbooks.executor.PlaybookExecutor.stream`.

        Auth + rate-limit + body-size rules from the middleware apply
        (this is a POST, so the 1 MiB body cap is enforced on the
        request JSON).
        """
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        try:
            # Cap the body read to the middleware-enforced limit. The
            # middleware has already validated Content-Length, but we
            # also cap the actual read to defend against a lying header.
            raw = await request.content.read(_MAX_REQUEST_BYTES + 1)
            if len(raw) > _MAX_REQUEST_BYTES:
                await resp.write(
                    format_sse_event("error", {"error": "Request body too large"}).encode("utf-8")
                )
                return resp
            try:
                body = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                await resp.write(
                    format_sse_event("error", {"error": f"Invalid JSON: {e}"}).encode("utf-8")
                )
                return resp

            path = body.get("path")
            if not isinstance(path, str) or not path:
                await resp.write(
                    format_sse_event("error", {"error": "Missing required field 'path'"}).encode(
                        "utf-8"
                    )
                )
                return resp

            # SECURITY: same path-traversal guard as _run_playbook /
            # _validate_playbook / _list_playbooks. A blocked path
            # emits an error event and closes the stream.
            resolved = _validate_playbook_path(path)
            if resolved is None:
                await resp.write(
                    format_sse_event(
                        "error",
                        {
                            "error": (
                                f"Access denied: path '{path}' is invalid or "
                                "in a blocked system directory."
                            )
                        },
                    ).encode("utf-8")
                )
                return resp

            try:
                playbook = PlaybookCompiler.from_file(str(resolved))
            except PlaybookCompileError as e:
                await resp.write(
                    format_sse_event("error", {"error": f"Compile error: {e}"}).encode("utf-8")
                )
                return resp

            model = body.get("model", "ollama/llama3.2")
            budget = body.get("budget_usd", 0.50)
            initial_input = body.get("input")

            provider = get_provider(model)
            executor = PlaybookExecutor(
                provider=provider,
                cost_budget=CostBudget(task_budget_usd=budget),
            )

            # Stream events to the client. ``playbook_event_stream``
            # terminates after the final ``run_result`` frame — the
            # connection closes naturally.
            async for frame in playbook_event_stream(
                executor,
                playbook,
                initial_input=initial_input,
                server=server,
                emit_initial_server_info=True,
            ):
                await resp.write(frame.encode("utf-8"))
        except (ConnectionResetError, asyncio.CancelledError):
            # Client disconnected mid-stream — exit cleanly. The
            # executor's ``stream()`` generator receives
            # ``asyncio.CancelledError`` on its next ``await`` and
            # tears down its asyncio tasks.
            pass
        except Exception:
            # Any other error (provider failure, compile error after
            # the path check, …) is emitted as a final ``error`` event
            # so the client sees the failure rather than getting a
            # truncated stream. The full traceback is logged.
            logger.exception("mcp_sse_run_failed")
            with contextlib.suppress(ConnectionResetError, asyncio.CancelledError):
                await resp.write(
                    format_sse_event("error", {"error": "Internal server error"}).encode("utf-8")
                )
        return resp

    app = web.Application(
        middlewares=[auth_and_limits_middleware]  # type: ignore[list-item]
    )
    app.router.add_post("/", handle)
    app.router.add_post("/mcp", handle)
    # SSE ambient channel — heartbeat + server_info only.
    app.router.add_get("/events", handle_sse)
    app.router.add_get("/sse", handle_sse)
    # SSE per-run channel — streams step-level events from
    # ``PlaybookExecutor.stream`` for a single playbook run.
    app.router.add_post("/runs/stream", handle_sse_run)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Run forever
    await asyncio.Event().wait()


__all__ = [
    "_MAX_REQUEST_BYTES",
    "_RATE_LIMIT_RPM",
    "_RateLimiter",
    "_constant_time_eq",
    "_rate_limiter",
    "serve_http",
]
