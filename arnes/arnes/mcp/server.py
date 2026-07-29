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
from pathlib import Path
from typing import Any, ClassVar

import structlog

from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry

logger = structlog.get_logger(__name__)


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

        # Path traversal protection: resolve and validate
        from pathlib import Path

        try:
            resolved = Path(path).resolve(strict=False)
        except (ValueError, OSError) as e:
            return {"success": False, "error": f"Invalid path: {e}"}

        # Block access to sensitive system paths
        blocked_prefixes = ["/etc", "/root", "/var", "/proc", "/sys", "/dev"]
        path_str = str(resolved)
        if any(path_str.startswith(prefix) for prefix in blocked_prefixes):
            return {
                "success": False,
                "error": f"Access denied: path '{path_str}' is in a blocked system directory.",
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
        path = Path(dir_path)
        if not path.exists():
            return {"playbooks": [], "error": f"Directory not found: {path}"}

        playbooks = []
        for yaml_file in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
            try:
                pb = PlaybookCompiler.from_file(yaml_file)
                playbooks.append(
                    {
                        "file": str(yaml_file),
                        "name": pb.metadata.name,
                        "objective": pb.metadata.objective,
                        "steps_count": len(pb.steps),
                        "budget_usd": pb.metadata.budget_usd,
                    }
                )
            except PlaybookCompileError as e:
                playbooks.append({"file": str(yaml_file), "error": str(e)})

        return {"playbooks": playbooks}

    def _validate_playbook(self, path: str) -> dict[str, Any]:
        try:
            playbook = PlaybookCompiler.from_file(path)
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
    """Run the MCP server over stdio (JSON-RPC)."""
    # Read JSON-RPC messages from stdin, write responses to stdout
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, __import__("sys").stdin)

    while True:
        line = await reader.readline()
        if not line:
            break

        try:
            request = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue

        response = await server.handle_request(request)
        print(json.dumps(response), flush=True)


async def serve_http(server: ArnesMCPServer, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the MCP server over HTTP (simple POST /endpoint).

    This is a minimal HTTP server for testing. For production use the
    official MCP SDK with proper SSE transport.
    """
    from aiohttp import web

    async def handle(request: web.Request) -> web.Response:
        try:
            request_data = await request.json()
            response = await server.handle_request(request_data)
            return web.json_response(response)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_post("/", handle)
    app.router.add_post("/mcp", handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Run forever
    await asyncio.Event().wait()


# Patch the ArnesMCPServer class to add serve_stdio and serve_http methods
def _patch_server_class() -> None:
    def serve_stdio_self(self) -> Any:
        return serve_stdio(self)

    def serve_http_self(self, host: str = "127.0.0.1", port: int = 8765) -> Any:
        return serve_http(self, host, port)

    ArnesMCPServer.serve_stdio = serve_stdio_self
    ArnesMCPServer.serve_http = serve_http_self


_patch_server_class()


if __name__ == "__main__":
    asyncio.run(serve_stdio(ArnesMCPServer()))
