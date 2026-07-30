"""ARNES MCP server — exposes playbooks as MCP tools.

When installed as an MCP server in Claude Desktop, Cursor, Cline, or Zed,
ARNES exposes 4 tools:
- arnes_run_playbook(path, input?) → run a playbook
- arnes_list_specialists() → list available specialists
- arnes_list_playbooks(dir?) → list playbooks in a directory
- arnes_get_events(thread_id) → get event log for a thread

Usage in Claude Desktop config:
{
  "mcpServers": {
    "arnes": {
      "command": "arnes",
      "args": ["mcp", "serve"]
    }
  }
}
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import structlog

from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry

logger = structlog.get_logger(__name__)

# ============================================================
# Path traversal protection
# ============================================================

# System directories that playbook paths may NEVER touch, regardless of how
# the caller resolves them. Mirrors the policy enforced in `_run_playbook`.
_BLOCKED_PATH_PREFIXES: tuple[str, ...] = ("/etc", "/root", "/var", "/proc", "/sys", "/dev")


def _validate_playbook_path(path: str) -> Path | None:
    """Resolve a playbook path and reject anything that escapes the allow-list.

    Returns the resolved `Path` if safe, or `None` if the path is invalid /
    points at a blocked system directory. Centralized here so that
    `_run_playbook`, `_validate_playbook`, and `_list_playbooks` share the
    SAME policy — previously only `_run_playbook` enforced it, leaving the
    other two open to path-traversal reads.
    """
    try:
        resolved = Path(path).resolve(strict=False)
    except (ValueError, OSError):
        return None
    path_str = str(resolved)
    if any(path_str.startswith(prefix) for prefix in _BLOCKED_PATH_PREFIXES):
        return None
    return resolved


class ArnesMCPServer:
    """Minimal MCP server implementation (stdio transport).

    This is a simplified stdio-based MCP server. For full MCP spec
    compliance, use the official `mcp` Python SDK and wrap this class.
    """

    PROTOCOL_VERSION: ClassVar[str] = "2024-11-05"
    SERVER_INFO: ClassVar[dict[str, str]] = {
        "name": "arnes",
        "version": "0.1.0a1",
    }

    TOOLS: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "arnes_run_playbook",
            "description": "Execute an ARNES playbook (YAML manual). Returns the run result.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the playbook YAML file"},
                    "input": {"type": "object", "description": "Initial input variables"},
                    "model": {
                        "type": "string",
                        "description": "LLM model (default: ollama/llama3.2)",
                    },
                    "budget_usd": {"type": "number", "description": "Max budget in USD"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "arnes_list_specialists",
            "description": "List all available ARNES specialists.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "arnes_list_playbooks",
            "description": "List all playbooks in a directory.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "dir": {
                        "type": "string",
                        "description": "Directory to scan (default: manuales/)",
                    },
                },
            },
        },
        {
            "name": "arnes_validate_playbook",
            "description": "Validate a playbook YAML without executing it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    ]

    def __init__(self) -> None:
        self._executor: PlaybookExecutor | None = None

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle a single JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        req_id = request.get("id")

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": self.PROTOCOL_VERSION,
                        "serverInfo": self.SERVER_INFO,
                        "capabilities": {"tools": {}},
                    },
                }

            if method == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": self.TOOLS},
                }

            if method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                result = await self._call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    result, indent=2, default=str, ensure_ascii=False
                                ),
                            }
                        ]
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        except Exception as e:
            logger.exception("mcp_request_failed", method=method)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }

    async def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call."""
        if name == "arnes_run_playbook":
            return await self._run_playbook(args)
        if name == "arnes_list_specialists":
            return self._list_specialists()
        if name == "arnes_list_playbooks":
            return self._list_playbooks(args.get("dir", "manuales"))
        if name == "arnes_validate_playbook":
            return self._validate_playbook(args["path"])
        raise ValueError(f"Unknown tool: {name}")

    async def _run_playbook(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a playbook. Path is validated to prevent traversal."""
        path = args["path"]

        # Path traversal protection (shared with _validate_playbook / _list_playbooks)
        resolved = _validate_playbook_path(path)
        if resolved is None:
            return {
                "success": False,
                "error": (
                    f"Access denied: path '{path}' is invalid or in a blocked system directory."
                ),
            }

        model = args.get("model", "ollama/llama3.2")
        budget = args.get("budget_usd", 0.50)
        initial_input = args.get("input")

        try:
            playbook = PlaybookCompiler.from_file(path)
        except PlaybookCompileError as e:
            return {"success": False, "error": f"Compile error: {e}"}

        provider = get_provider(model)
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=budget),
        )

        result = await executor.run(playbook, initial_input=initial_input)

        return {
            "success": result.success,
            "steps_executed": result.steps_executed,
            "steps_failed": result.steps_failed,
            "duration_s": result.duration_s,
            "total_tokens_in": result.total_tokens_in,
            "total_tokens_out": result.total_tokens_out,
            "total_cost_usd": result.total_cost_usd,
            "outputs": {k: v for k, v in result.outputs.items() if not k.startswith("__")},
            "error": result.error,
            "bitacora_preview": result.to_markdown()[:500] + "..."
            if len(result.to_markdown()) > 500
            else result.to_markdown(),
        }

    def _list_specialists(self) -> dict[str, Any]:
        registry = get_default_specialist_registry()
        return {
            "specialists": [
                {
                    "name": c.name,
                    "description": c.description,
                    "default_model": c.default_model,
                    "tools": c.tools,
                }
                for c in registry.configs()
            ]
        }

    def _list_playbooks(self, dir_path: str) -> dict[str, Any]:
        # SECURITY: apply the same path validation as _run_playbook — a missing
        # check here previously allowed `arnes_list_playbooks` to enumerate
        # sensitive directories like /etc.
        resolved = _validate_playbook_path(dir_path)
        if resolved is None:
            return {
                "playbooks": [],
                "error": (
                    f"Access denied: directory '{dir_path}' is invalid or in a "
                    "blocked system directory."
                ),
            }
        path = resolved
        if not path.exists() or not path.is_dir():
            return {"playbooks": [], "error": f"Directory not found: {path}"}

        playbooks = []
        for yaml_file in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
            # Each discovered file is also re-validated (in case a symlink
            # inside the directory points back into a blocked prefix).
            if _validate_playbook_path(str(yaml_file)) is None:
                playbooks.append(
                    {"file": str(yaml_file), "error": "blocked: path in protected directory"}
                )
                continue
            try:
                pb = PlaybookCompiler.from_file(yaml_file)
                # The Playbook schema's `_build_metadata` validator guarantees
                # `metadata` is non-None after compilation; assert so mypy
                # narrows the Optional away.
                assert pb.metadata is not None
                entry: dict[str, Any] = {
                    "file": str(yaml_file),
                    "name": pb.metadata.name,
                    "objective": pb.metadata.objective,
                    "steps_count": len(pb.steps),
                    "budget_usd": pb.metadata.budget_usd,
                }
                playbooks.append(entry)
            except PlaybookCompileError as e:
                playbooks.append({"file": str(yaml_file), "error": str(e)})

        return {"playbooks": playbooks}

    def _validate_playbook(self, path: str) -> dict[str, Any]:
        # SECURITY: apply the same path validation as _run_playbook — a missing
        # check here previously allowed `arnes_validate_playbook` to read
        # arbitrary YAML files (path traversal).
        if _validate_playbook_path(path) is None:
            return {
                "valid": False,
                "error": (
                    f"Access denied: path '{path}' is invalid or in a blocked system directory."
                ),
            }
        try:
            playbook = PlaybookCompiler.from_file(path)
            assert playbook.metadata is not None
            return {
                "valid": True,
                "name": playbook.metadata.name,
                "objective": playbook.metadata.objective,
                "steps": len(playbook.steps),
                "step_ids": [s.id for s in playbook.steps],
            }
        except PlaybookCompileError as e:
            return {"valid": False, "error": str(e)}


async def serve_stdio(server: ArnesMCPServer) -> None:
    """Run the MCP server over stdio (JSON-RPC).

    Cross-platform: reads line-delimited JSON from stdin, writes JSON to stdout.
    Uses synchronous readline in a thread executor to avoid Windows asyncio
    pipe compatibility issues.
    """
    import sys

    while True:
        try:
            # Read line from stdin in a thread (Windows-compatible)
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break

            try:
                request = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            response = await server.handle_request(request)
            print(json.dumps(response), flush=True)
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            logger.error("mcp_stdio_error", error=str(e))
            break


async def serve_http(server: ArnesMCPServer, host: str = "127.0.0.1", port: int = 8765) -> None:
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
    from aiohttp import web

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

    app = web.Application(
        middlewares=[auth_and_limits_middleware]  # type: ignore[list-item]
    )
    app.router.add_post("/", handle)
    app.router.add_post("/mcp", handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Run forever
    await asyncio.Event().wait()


# ============================================================
# HTTP transport security helpers
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


# Add ``serve_stdio`` / ``serve_http`` as methods on ArnesMCPServer.
# We assign them here (rather than declaring them inside the class body)
# because they delegate to the module-level functions defined above, which
# in turn need ``ArnesMCPServer`` to already exist. The ``# type: ignore``
# silences mypy's complaint about assigning to a class attribute that isn't
# declared in the class body — this is a standard Python pattern for adding
# methods after class definition (e.g. for backwards-compat aliases).
def _attach_serve_methods() -> None:
    def serve_stdio_self(self: ArnesMCPServer) -> Any:
        return serve_stdio(self)

    def serve_http_self(self: ArnesMCPServer, host: str = "127.0.0.1", port: int = 8765) -> Any:
        return serve_http(self, host, port)

    # mypy cannot see runtime monkey-patching of class attributes. Use a
    # bare ``# type: ignore`` (rather than specific codes) so the suppression
    # is robust to mypy version differences in how it classifies this.
    ArnesMCPServer.serve_stdio = serve_stdio_self  # type: ignore[attr-defined]
    ArnesMCPServer.serve_http = serve_http_self  # type: ignore[attr-defined]


_attach_serve_methods()


if __name__ == "__main__":
    asyncio.run(serve_stdio(ArnesMCPServer()))
