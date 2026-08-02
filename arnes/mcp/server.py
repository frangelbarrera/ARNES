"""ARNES MCP server — exposes playbooks as MCP tools.

When installed as an MCP server in Claude Desktop, Cursor, Cline, or Zed,
ARNES exposes 4 tools:

- arnes_run_playbook(path, input?) → run a playbook
- arnes_list_specialists() → list available specialists
- arnes_list_playbooks(dir?) → list playbooks in a directory
- arnes_validate_playbook(path) → validate a playbook YAML

The HTTP transport exposes two SSE channels: ``GET /events`` for an
ambient heartbeat, and ``POST /runs/stream`` for a per-run channel
that wires :func:`arnes.mcp.sse.playbook_event_stream` to
:meth:`arnes.playbooks.executor.PlaybookExecutor.stream` so subscribers
see step-level transitions in real time.

The HTTP transport (aiohttp app, route handlers, security helpers)
lives in :mod:`arnes.mcp.http`; this module focuses on the JSON-RPC
dispatcher + path-validation guard.

Usage in Claude Desktop config::

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
import sys
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
# Backwards-compat re-exports (HTTP transport lives in arnes.mcp.http)
# ============================================================
# The HTTP transport lives in :mod:`arnes.mcp.http` to keep this
# module focused on the JSON-RPC dispatcher + path-validation guard.
# The security helpers (``_RateLimiter``, ``_constant_time_eq``,
# ``_MAX_REQUEST_BYTES``, ``_RATE_LIMIT_RPM``) and ``serve_http``
# live there. They are re-exported here so existing imports of
# the shape ``from arnes.mcp.server import _constant_time_eq``
# (used by tests) keep working — the canonical home is
# :mod:`arnes.mcp.http`.

from arnes.mcp.http import (  # noqa: E402 - intentional re-export after logger setup
    _MAX_REQUEST_BYTES,
    _RATE_LIMIT_RPM,
    _constant_time_eq,
    _rate_limiter,
    _RateLimiter,
    serve_http,
)

# ``__all__`` declares the re-exports explicitly so type-checkers and
# linters treat the imported names as the public surface of this
# module (otherwise ruff F401 would flag them as unused imports).
__all__ = [
    "_BLOCKED_PATH_PREFIXES",
    "_MAX_REQUEST_BYTES",
    "_RATE_LIMIT_RPM",
    "ArnesMCPServer",
    "_RateLimiter",
    "_attach_serve_methods",
    "_constant_time_eq",
    "_rate_limiter",
    "_validate_playbook_path",
    "serve_http",
    "serve_stdio",
]

# ============================================================
# Path traversal protection
# ============================================================

# System directories that playbook paths may NEVER touch, regardless of how
# the caller resolves them. Mirrors the policy enforced in `_run_playbook`.
_BLOCKED_PATH_PREFIXES: tuple[str, ...] = (
    # Unix system directories
    "/etc",
    "/private/etc",  # macOS: /etc -> /private/etc
    "/root",
    "/var",
    "/proc",
    "/sys",
    "/dev",
    # NOTE: /private/var is intentionally NOT blocked — on macOS the
    # per-user temp directory lives under /private/var/folders/... and
    # blocking it would reject legitimate playbook paths in pytest tmp_path.
    # Windows system directories (lowercase for case-insensitive match)
    "c:\\windows",
    "c:\\program files",
    "c:\\users\\public",
)


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
    # Normalise to lowercase with forward slashes so the prefix match works
    # consistently across Linux, macOS (where /etc -> /private/etc), and
    # Windows (where C:\\Windows and c:\\windows are the same path).
    path_str = str(resolved).lower().replace("\\", "/")
    blocked = [p.replace("\\", "/") for p in _BLOCKED_PATH_PREFIXES]
    if any(path_str.startswith(prefix) for prefix in blocked):
        return None
    # On macOS, /var -> /private/var. Block /private/var EXCEPT for the
    # per-user temp directory (/private/var/folders/...) which is where
    # pytest's tmp_path lives — blocking it would reject legitimate test
    # playbooks and user temp files.
    # Note: check both with and without trailing slash so /var and /var/x
    # are both caught.
    if (
        path_str == "/private/var" or path_str.startswith("/private/var/")
    ) and not path_str.startswith("/private/var/folders/"):
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
        {
            "name": "arnes_plan",
            "description": "Proactively analyze a request, assess market viability, estimate costs, identify risks, and generate a playbook. ARNES researches BEFORE executing — it doesn't just start coding.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "What the user wants to build (e.g., 'Build a dating app for the Play Store')",
                    },
                    "model": {
                        "type": "string",
                        "description": "LLM model for planning (default: ollama/llama3.2)",
                    },
                    "budget_usd": {
                        "type": "number",
                        "description": "Max budget for the planning call (default: 5.0)",
                    },
                },
                "required": ["request"],
            },
        },
        {
            "name": "arnes_list_specialists_detailed",
            "description": "List all 12 ARNES specialists with their roles, tools, and capabilities.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]

    # ``ArnesMCPServer`` is stateless across calls — no ``__init__``
    # state is required. Executors are constructed per-request inside
    # ``_run_playbook`` / ``handle_sse_run``.

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
        if name == "arnes_list_specialists_detailed":
            return self._list_specialists_detailed()
        if name == "arnes_list_playbooks":
            return self._list_playbooks(args.get("dir", "manuals"))
        if name == "arnes_validate_playbook":
            return self._validate_playbook(args["path"])
        if name == "arnes_plan":
            return await self._proactive_plan(args)
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
            "run_log_preview": result.to_markdown()[:500] + "..."
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

    def _list_specialists_detailed(self) -> dict[str, Any]:
        """List all specialists with detailed capabilities."""
        registry = get_default_specialist_registry()
        specialists = []
        for config in registry.configs():
            specialists.append(
                {
                    "name": config.name,
                    "description": config.description,
                    "tools": config.tools,
                    "default_model": config.default_model or "ollama/llama3.2",
                    "has_structured_output": bool(config.output_schema or config.pydantic_model),
                }
            )
        return {
            "total": len(specialists),
            "specialists": specialists,
        }

    async def _proactive_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run the proactive planner — researches before executing."""
        from arnes.llm.factory import get_provider
        from arnes.proactive import ProactivePlanner

        request = args["request"]
        model = args.get("model", "ollama/llama3.2")
        budget = args.get("budget_usd", 5.0)

        try:
            provider = get_provider(model)
        except Exception as e:
            return {"error": f"Failed to initialize provider: {e}"}

        planner = ProactivePlanner(provider=provider, budget_usd=budget)
        plan_result = await planner.plan(request)

        if "error" in plan_result:
            return plan_result

        # Also generate YAML so the caller can save and run it
        yaml_content = ProactivePlanner.to_yaml(plan_result)
        plan_result["generated_yaml"] = yaml_content

        return plan_result


async def serve_stdio(server: ArnesMCPServer) -> None:
    """Run the MCP server over stdio (JSON-RPC).

    Cross-platform: reads line-delimited JSON from stdin, writes JSON to stdout.
    Uses synchronous readline in a thread executor to avoid Windows asyncio
    pipe compatibility issues.
    """

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


# ============================================================
# Serve-method attachment (serve_http lives in arnes.mcp.http)
# ============================================================


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
