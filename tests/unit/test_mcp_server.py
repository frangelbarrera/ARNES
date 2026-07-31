"""Tests for arnes.mcp.server.

Covers the JSON-RPC dispatcher, path-traversal guards, the 6 MCP tools,
and the HTTP-transport security helpers (``_RateLimiter``, bearer-token
comparison). The HTTP server itself is not started — we test the request
handler and the security primitives directly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import arnes.mcp.server as mcp_server
from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.mcp.server import (
    _BLOCKED_PATH_PREFIXES,
    ArnesMCPServer,
    _constant_time_eq,
    _RateLimiter,
    _validate_playbook_path,
)

# Repository-relative path to the bundled example manuals. Using an absolute
# path resolved against this test file keeps the tests robust to CWD changes.
_MANUALS_DIR = Path(__file__).resolve().parents[2] / "manuals"


def _call_tool_response(result: dict[str, Any]) -> dict[str, Any]:
    """Extract the JSON payload from a tools/call response.

    ``handle_request`` wraps every tool result as ``{"content": [{"text": ...}]}``
    with ``text`` being a JSON-serialized string. This helper deserializes it
    so tests can assert on the structured payload.
    """
    return json.loads(result["result"]["content"][0]["text"])


class TestJSONRPCDispatcher:
    """Tests for the JSON-RPC ``handle_request`` dispatcher."""

    @pytest.mark.asyncio
    async def test_initialize_returns_correct_protocol_version(self) -> None:
        server = ArnesMCPServer()
        response = await server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        # The protocol version MUST match the constant declared on the class —
        # clients negotiate capabilities against this string.
        assert response["result"]["protocolVersion"] == ArnesMCPServer.PROTOCOL_VERSION
        assert response["result"]["serverInfo"]["name"] == "arnes"
        assert "tools" in response["result"]["capabilities"]

    @pytest.mark.asyncio
    async def test_tools_list_returns_six_tools(self) -> None:
        server = ArnesMCPServer()
        response = await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = response["result"]["tools"]
        assert len(tools) == 6, f"Expected 6 tools, got {len(tools)}: {[t['name'] for t in tools]}"
        names = {t["name"] for t in tools}
        assert names == {
            "arnes_run_playbook",
            "arnes_list_specialists",
            "arnes_list_specialists_detailed",
            "arnes_list_playbooks",
            "arnes_validate_playbook",
            "arnes_plan",
        }
        # Every tool must declare an inputSchema so clients can render args forms.
        for tool in tools:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_unknown_method_returns_method_not_found_error(self) -> None:
        """JSON-RPC -32601 is the spec-correct code for an unknown method."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {"jsonrpc": "2.0", "id": 99, "method": "totally/made/up"}
        )
        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_internal_error(self) -> None:
        """An unknown tool name surfaces as JSON-RPC -32603 (internal error)."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "arnes_nonexistent_tool", "arguments": {}},
            }
        )
        assert "error" in response
        assert response["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_initialize_carries_request_id(self) -> None:
        """The server must echo back the caller's id (JSON-RPC requirement)."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {"jsonrpc": "2.0", "id": "abc-123", "method": "initialize"}
        )
        assert response["id"] == "abc-123"


class TestListSpecialists:
    @pytest.mark.asyncio
    async def test_arnes_list_specialists_returns_all_specialists(self) -> None:
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "arnes_list_specialists", "arguments": {}},
            }
        )
        payload = _call_tool_response(response)
        # The default registry exposes 12 specialists: the 5 original v0.1
        # specialists (planner, coder, reviewer, tester, debugger) plus 7
        # specialist-expansion additions (researcher, security-auditor,
        # devops-engineer, data-scientist, product-manager, market-analyst,
        # cost-estimator). If this regresses (e.g. a specialist fails to
        # import), this test catches it.
        assert "specialists" in payload
        assert len(payload["specialists"]) == 12
        names = {s["name"] for s in payload["specialists"]}
        assert names == {
            "@planner",
            "@coder",
            "@reviewer",
            "@tester",
            "@debugger",
            "@researcher",
            "@security-auditor",
            "@devops-engineer",
            "@data-scientist",
            "@product-manager",
            "@market-analyst",
            "@cost-estimator",
        }
        # Each entry must be self-describing enough for a client to render it.
        for spec in payload["specialists"]:
            assert "name" in spec
            assert "description" in spec
            assert "default_model" in spec
            assert "tools" in spec


class TestValidatePlaybook:
    @pytest.mark.asyncio
    async def test_validate_playbook_with_valid_playbook(self) -> None:
        """A real, valid playbook should report valid=True plus its metadata."""
        path = str(_MANUALS_DIR / "hello-world.yaml")
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "arnes_validate_playbook", "arguments": {"path": path}},
            }
        )
        payload = _call_tool_response(response)
        assert payload["valid"] is True
        assert payload["name"] == "hello-world"
        assert "objective" in payload
        assert payload["steps"] == 2
        assert payload["step_ids"] == ["plan", "write_outline"]

    @pytest.mark.asyncio
    async def test_validate_playbook_with_invalid_playbook(self, tmp_path: Path) -> None:
        """An invalid YAML file should report valid=False with the parser error."""
        bad_yaml = tmp_path / "broken.yaml"
        # Invalid YAML: nested colon without proper quoting.
        bad_yaml.write_text("this is not: valid: yaml: [", encoding="utf-8")

        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_validate_playbook",
                    "arguments": {"path": str(bad_yaml)},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["valid"] is False
        assert "error" in payload
        # The error must mention YAML parsing, not path traversal.
        assert "YAML" in payload["error"] or "parse" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_playbook_with_invalid_schema(self, tmp_path: Path) -> None:
        """A YAML that parses but fails schema validation must report valid=False."""
        bad_yaml = tmp_path / "bad_schema.yaml"
        # Missing required `steps` field → schema validation fails.
        bad_yaml.write_text("name: incomplete\nobjective: no steps\n", encoding="utf-8")

        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_validate_playbook",
                    "arguments": {"path": str(bad_yaml)},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["valid"] is False
        assert "error" in payload

    @pytest.mark.asyncio
    async def test_validate_playbook_with_path_traversal_is_blocked(self) -> None:
        """``/etc/passwd`` must be rejected BEFORE the compiler reads it."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_validate_playbook",
                    "arguments": {"path": "/etc/passwd"},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["valid"] is False
        # The error must be the access-denied message, NOT a YAML parse error —
        # this proves the path check happened before any file read.
        assert "Access denied" in payload["error"]
        assert "/etc/passwd" in payload["error"]


class TestListPlaybooks:
    @pytest.mark.asyncio
    async def test_list_playbooks_with_valid_directory(self) -> None:
        """Listing the bundled manuals/ dir should return ≥10 playbooks."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_list_playbooks",
                    "arguments": {"dir": str(_MANUALS_DIR)},
                },
            }
        )
        payload = _call_tool_response(response)
        assert "playbooks" in payload
        assert "error" not in payload
        assert len(payload["playbooks"]) >= 10
        # Each entry should carry the metadata fields the UI needs.
        first = payload["playbooks"][0]
        assert "file" in first
        assert "name" in first
        assert "objective" in first
        assert "steps_count" in first
        assert "budget_usd" in first

    @pytest.mark.asyncio
    async def test_list_playbooks_with_nonexistent_directory(self, tmp_path: Path) -> None:
        """A missing directory should return an empty list with an error message."""
        missing = tmp_path / "does_not_exist"
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_list_playbooks",
                    "arguments": {"dir": str(missing)},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["playbooks"] == []
        assert "error" in payload
        assert "not found" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_list_playbooks_with_blocked_directory_is_blocked(self) -> None:
        """``arnes_list_playbooks('/etc')`` must refuse to enumerate /etc."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_list_playbooks",
                    "arguments": {"dir": "/etc"},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["playbooks"] == []
        assert "Access denied" in payload["error"]

    @pytest.mark.asyncio
    async def test_list_playbooks_records_compile_errors_per_file(self, tmp_path: Path) -> None:
        """A directory with one valid and one broken YAML should return the
        valid one plus an ``error`` entry for the broken one — NOT abort the
        whole listing.
        """
        valid = tmp_path / "good.yaml"
        valid.write_text(
            "name: good\nobjective: ok\nsteps:\n  - id: s1\n    specialist: '@planner'\n",
            encoding="utf-8",
        )
        broken = tmp_path / "bad.yaml"
        broken.write_text("this is not: valid: yaml: [", encoding="utf-8")

        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_list_playbooks",
                    "arguments": {"dir": str(tmp_path)},
                },
            }
        )
        payload = _call_tool_response(response)
        # Both files are listed — the broken one carries an `error` key
        # instead of the metadata fields, so the caller can show per-file
        # diagnostics without losing the good file.
        files = {entry["file"]: entry for entry in payload["playbooks"]}
        assert str(valid) in files
        assert str(broken) in files
        assert "name" in files[str(valid)]
        assert "error" in files[str(broken)]
        assert (
            "YAML" in files[str(broken)]["error"] or "parse" in files[str(broken)]["error"].lower()
        )

    @pytest.mark.asyncio
    async def test_list_playbooks_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        """An existing but empty directory yields an empty playbooks list
        with NO error message (the directory exists; it's just empty)."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_list_playbooks",
                    "arguments": {"dir": str(tmp_path)},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["playbooks"] == []
        assert "error" not in payload


class TestRunPlaybook:
    @pytest.mark.asyncio
    async def test_run_playbook_with_mock_provider_succeeds(self) -> None:
        """``arnes_run_playbook`` must execute end-to-end with a mocked LLM.

        We monkeypatch ``get_provider`` on the MCP server module so the
        executor gets our schema-valid mock — no network, no tokens spent.
        """

        class SchemaValidMockProvider(LLMProvider):
            """Returns JSON valid for each specialist's output_schema."""

            async def complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.0,
                max_tokens: int | None = None,
                response_format: dict[str, Any] | None = None,
                response_schema: dict[str, Any] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                sys_msg = next((m for m in messages if m.role == "system"), None)
                sys_content = sys_msg.content if sys_msg else ""
                if "@planner" in sys_content:
                    content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
                elif "@coder" in sys_content:
                    content = (
                        '{"files": [{"path": "out.py", "language": "python", '
                        '"content": "pass"}], "summary": "ok", "assumptions": [], '
                        '"warnings": []}'
                    )
                elif "@reviewer" in sys_content:
                    content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
                elif "@tester" in sys_content:
                    content = (
                        '{"test_files": [{"path": "test.py", "content": "pass"}], '
                        '"test_results": {"passed": 1, "failed": 0, "skipped": 0, '
                        '"failures": []}, "summary": "ok"}'
                    )
                elif "@debugger" in sys_content:
                    content = (
                        '{"root_cause": "x", "confidence": 0.9, "fix": {"file": "f.py", '
                        '"line": 1, "original": "x", "fixed": "y", "explanation": "ok"}, '
                        '"verification": "v", "alternative_causes": []}'
                    )
                else:
                    content = '{"result": "ok"}'
                return LLMResponse(
                    content=content,
                    tool_calls=[],
                    usage=LLMUsage(
                        tokens_in=10,
                        tokens_out=5,
                        cost_usd=0.0,
                        model=model,
                        cached=False,
                    ),
                    model=model,
                )

            async def stream_complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.0,
                max_tokens: int | None = None,
                response_format: dict[str, Any] | None = None,
                response_schema: dict[str, Any] | None = None,
                **kwargs: Any,
            ) -> AsyncIterator[LLMResponse]:
                """Yield the full response in one chunk."""
                response = await self.complete(
                    messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    response_schema=response_schema,
                    **kwargs,
                )
                yield response

            def list_models(self) -> list[str]:
                return ["mock"]

        server = ArnesMCPServer()
        path = str(_MANUALS_DIR / "hello-world.yaml")
        with patch.object(mcp_server, "get_provider", return_value=SchemaValidMockProvider()):
            response = await server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "arnes_run_playbook",
                        "arguments": {"path": path, "model": "mock/test"},
                    },
                }
            )
        payload = _call_tool_response(response)
        assert payload["success"] is True, f"Expected success, got: {payload}"
        assert payload["steps_executed"] == 2
        assert payload["steps_failed"] == 0
        assert payload["total_cost_usd"] == 0.0
        # The run log preview must be non-empty.
        assert payload["run_log_preview"]
        # Internal `__`-prefixed outputs are filtered out before serialization.
        for key in payload["outputs"]:
            assert not key.startswith("__")

    @pytest.mark.asyncio
    async def test_run_playbook_with_path_traversal_is_blocked(self) -> None:
        """Path-traversal attempts must be rejected before the compiler runs."""
        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_run_playbook",
                    "arguments": {"path": "/etc/passwd"},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["success"] is False
        assert "Access denied" in payload["error"]

    @pytest.mark.asyncio
    async def test_run_playbook_with_compile_error_returns_failure(self, tmp_path: Path) -> None:
        """A playbook that fails to compile surfaces a structured failure."""
        bad_yaml = tmp_path / "broken.yaml"
        bad_yaml.write_text("name: x\nobjective: y\nsteps:\n  - id: s1\n", encoding="utf-8")

        server = ArnesMCPServer()
        response = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "arnes_run_playbook",
                    "arguments": {"path": str(bad_yaml), "model": "mock/test"},
                },
            }
        )
        payload = _call_tool_response(response)
        assert payload["success"] is False
        assert "Compile error" in payload["error"]


class TestPathValidation:
    """Direct tests for the ``_validate_playbook_path`` traversal guard."""

    @pytest.mark.parametrize("blocked", list(_BLOCKED_PATH_PREFIXES))
    def test_validate_playbook_path_blocks_all_protected_prefixes(self, blocked: str) -> None:
        """Every prefix in ``_BLOCKED_PATH_PREFIXES`` must be rejected.

        Parametrized over the tuple so a future addition (e.g. ``/run``) is
        automatically covered.
        """
        assert _validate_playbook_path(blocked) is None
        # Trailing path components must also be blocked.
        assert _validate_playbook_path(f"{blocked}/some/file") is None

    def test_validate_playbook_path_blocks_specific_system_dirs(self) -> None:
        """The exact protected prefixes from the issue spec."""
        for path in ("/etc", "/root", "/var", "/proc", "/sys", "/dev"):
            assert _validate_playbook_path(path) is None, (
                f"Path '{path}' should be blocked but was allowed."
            )

    def test_validate_playbook_path_allows_user_paths(self, tmp_path: Path) -> None:
        """A regular user path resolves to an absolute Path."""
        result = _validate_playbook_path(str(tmp_path / "playbook.yaml"))
        assert result is not None
        assert result.is_absolute()

    def test_validate_playbook_path_resolves_relative_paths(self) -> None:
        """A relative path is resolved against CWD and returned as absolute."""
        result = _validate_playbook_path("manuals/hello-world.yaml")
        assert result is not None
        assert result.is_absolute()
        assert result.name == "hello-world.yaml"

    def test_validate_playbook_path_handles_nonexistent_paths(self) -> None:
        """Nonexistent paths are returned (not None) — they're not blocked,
        just non-existent. The downstream caller decides what to do."""
        result = _validate_playbook_path("/tmp/arnes-does-not-exist-xyz.yaml")
        # ``/tmp`` is NOT in the blocked list, so the path is allowed.
        assert result is not None
        assert str(result).startswith("/tmp/")


class TestRateLimiter:
    """Tests for the per-IP sliding-window rate limiter used by HTTP transport."""

    def test_allows_up_to_max_requests(self) -> None:
        limiter = _RateLimiter(max_requests=3, window_s=60.0)
        assert limiter.allow("1.2.3.4") is True
        assert limiter.allow("1.2.3.4") is True
        assert limiter.allow("1.2.3.4") is True
        # 4th request from the same IP must be denied.
        assert limiter.allow("1.2.3.4") is False

    def test_isolates_per_ip(self) -> None:
        limiter = _RateLimiter(max_requests=1, window_s=60.0)
        assert limiter.allow("1.1.1.1") is True
        assert limiter.allow("1.1.1.1") is False
        # Different IP — should get its own bucket.
        assert limiter.allow("2.2.2.2") is True

    def test_window_slides_after_expiry(self) -> None:
        """After the window expires, requests from the same IP are allowed again."""
        limiter = _RateLimiter(max_requests=1, window_s=0.05)
        assert limiter.allow("3.3.3.3") is True
        assert limiter.allow("3.3.3.3") is False
        # Wait past the window.
        import time

        time.sleep(0.06)
        assert limiter.allow("3.3.3.3") is True

    def test_unknown_ip_is_allowed(self) -> None:
        """The ``unknown`` fallback IP (used when remote is missing) is allowed."""
        limiter = _RateLimiter(max_requests=10, window_s=60.0)
        assert limiter.allow("unknown") is True


class TestBearerTokenComparison:
    """Tests for ``_constant_time_eq`` — bearer-token comparison helper."""

    def test_equal_strings_match(self) -> None:
        assert _constant_time_eq("sk-secret-token", "sk-secret-token") is True

    def test_different_strings_dont_match(self) -> None:
        assert _constant_time_eq("sk-secret-token", "sk-wrong-token") is False

    def test_different_lengths_dont_match(self) -> None:
        assert _constant_time_eq("short", "longer-string") is False

    def test_empty_strings_match(self) -> None:
        assert _constant_time_eq("", "") is True


class TestServerConstants:
    """Smoke tests for the server's declared constants — catches accidental
    contract drift (e.g. protocol version bump without test update)."""

    def test_protocol_version_is_dashed_date(self) -> None:
        # MCP protocol versions are YYYY-MM-DD strings.
        assert ArnesMCPServer.PROTOCOL_VERSION == "2024-11-05"

    def test_server_info_has_name_and_version(self) -> None:
        assert ArnesMCPServer.SERVER_INFO["name"] == "arnes"
        assert "version" in ArnesMCPServer.SERVER_INFO

    def test_blocked_path_prefixes_include_all_required(self) -> None:
        """The protected-prefix tuple must include every system dir from the
        issue spec. Adding new entries is fine; removing one is a regression.
        """
        for required in ("/etc", "/root", "/var", "/proc", "/sys", "/dev"):
            assert required in _BLOCKED_PATH_PREFIXES, (
                f"{required} must be in _BLOCKED_PATH_PREFIXES"
            )


class TestSSEEventStream:
    """Tests for the SSE (Server-Sent Events) ambient endpoint.

    The HTTP server registers ``GET /events`` and ``GET /sse`` as
    streaming routes that yield ``text/event-stream`` frames via
    :func:`arnes.mcp.server.sse_event_stream`. These tests exercise the
    generator directly (without binding a real socket) so the wire
    format and the initial-event behaviour are pinned.
    """

    @pytest.mark.asyncio
    async def test_format_sse_event_produces_spec_compliant_frame(self) -> None:
        """``_format_sse_event`` must emit ``event:`` + ``data:`` + blank line."""
        from arnes.mcp.sse import format_sse_event

        frame = format_sse_event("server_info", {"server": "arnes", "version": "0.1.0a1"})
        # Spec: every event ends with a blank line (``\n\n``).
        assert frame.endswith("\n\n")
        assert frame.startswith("event: server_info\n")
        assert "data: " in frame

    @pytest.mark.asyncio
    async def test_format_sse_event_handles_dict_payload(self) -> None:
        """A dict payload is JSON-serialised onto a single ``data:`` line.

        ``json.dumps`` escapes any embedded newlines in string values, so
        the common dict case produces exactly one ``data:`` line. This test
        pins that behaviour — a regression in the JSON encoding (e.g.
        accidentally enabling ``indent=``) would break the wire format.
        """
        from arnes.mcp.sse import format_sse_event

        frame = format_sse_event("server_info", {"server": "arnes", "ok": True})
        assert frame.startswith("event: server_info\n")
        # Exactly one ``data:`` line for a single-line JSON payload.
        assert frame.count("data: ") == 1
        assert '"server": "arnes"' in frame
        assert '"ok": true' in frame
        assert frame.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_sse_event_stream_emits_initial_server_info_event(self) -> None:
        """The first yielded frame must be a ``server_info`` event carrying
        the server name + version — this is what a browser-based subscriber
        uses to confirm the endpoint works end-to-end."""
        from arnes.mcp.sse import sse_event_stream

        server = ArnesMCPServer()
        # Use a tiny heartbeat interval so the test doesn't block on the
        # first heartbeat — but we only consume the first frame anyway.
        gen = sse_event_stream(server, heartbeat_interval_s=0.01, initial_event_count=1)

        first = await gen.__anext__()
        assert first.startswith("event: server_info\n")
        assert f'"server": "{server.SERVER_INFO["name"]}"' in first
        assert f'"version": "{server.SERVER_INFO["version"]}"' in first
        assert first.endswith("\n\n")

        # Close the generator so its heartbeat task doesn't leak.
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_sse_event_stream_yields_heartbeat_comment_after_initial_events(
        self,
    ) -> None:
        """After the initial ``server_info`` event(s), the stream must idle
        on ``: ping`` comments — these keep the connection alive through
        proxies without dispatching client-side event listeners."""
        from arnes.mcp.sse import sse_event_stream

        server = ArnesMCPServer()
        # Tiny heartbeat so the test doesn't sleep for 15 s.
        gen = sse_event_stream(server, heartbeat_interval_s=0.01, initial_event_count=1)

        # Skip the initial server_info frame.
        await gen.__anext__()

        # The next frame must be a heartbeat comment.
        heartbeat = await gen.__anext__()
        assert heartbeat.startswith(": ping")
        assert heartbeat.endswith("\n\n")

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_sse_event_stream_zero_initial_events_only_heartbeats(self) -> None:
        """When ``initial_event_count=0``, the very first frame is a heartbeat
        comment — confirms the heartbeat loop runs even when no intro event
        is requested."""
        from arnes.mcp.sse import sse_event_stream

        server = ArnesMCPServer()
        gen = sse_event_stream(server, heartbeat_interval_s=0.01, initial_event_count=0)

        first = await gen.__anext__()
        assert first.startswith(": ping")
        await gen.aclose()


class TestPlaybookEventStream:
    """Tests for the SSE wiring — :func:`arnes.mcp.sse.playbook_event_stream`.

    The wiring replaces the heartbeat-only stub with a real per-run
    channel that forwards each event from
    :meth:`arnes.playbooks.executor.PlaybookExecutor.stream` as an SSE
    frame. These tests exercise the generator directly (without binding
    a real HTTP socket) so the wire format, event ordering, and
    failure handling are pinned.
    """

    @pytest.fixture
    def mock_provider(self) -> Any:
        """A schema-valid mock provider that satisfies every specialist's
        response schema (planner / coder / reviewer / tester / debugger)."""

        class _SchemaValidMockProvider(LLMProvider):
            def __init__(self) -> None:
                self.call_count = 0

            async def complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.0,
                max_tokens: int | None = None,
                response_format: dict[str, Any] | None = None,
                response_schema: dict[str, Any] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                self.call_count += 1
                sys_msg = next((m for m in messages if m.role == "system"), None)
                sys_content = sys_msg.content if sys_msg else ""
                if "@planner" in sys_content:
                    content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
                elif "@coder" in sys_content:
                    content = (
                        '{"files": [{"path": "out.py", "language": "python", '
                        '"content": "pass"}], "summary": "ok", '
                        '"assumptions": [], "warnings": []}'
                    )
                elif "@reviewer" in sys_content:
                    content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
                else:
                    content = '{"result": "ok"}'
                tokens_in = sum(len(m.content) // 4 for m in messages)
                tokens_out = len(content) // 4
                return LLMResponse(
                    content=content,
                    tool_calls=[],
                    usage=LLMUsage(
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_usd=0.0,
                        model=model,
                        cached=False,
                    ),
                    model=model,
                )

            async def stream_complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.0,
                max_tokens: int | None = None,
                response_format: dict[str, Any] | None = None,
                response_schema: dict[str, Any] | None = None,
                **kwargs: Any,
            ) -> AsyncIterator[LLMResponse]:
                response = await self.complete(
                    messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    response_schema=response_schema,
                    **kwargs,
                )
                yield response

            def list_models(self) -> list[str]:
                return ["mock"]

        return _SchemaValidMockProvider()

    @pytest.fixture
    def executor(self, mock_provider: Any) -> Any:
        from arnes.middleware.cost_guard import CostBudget
        from arnes.playbooks.executor import PlaybookExecutor

        return PlaybookExecutor(
            provider=mock_provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

    @pytest.mark.asyncio
    async def test_emits_server_info_first_when_server_provided(self, executor: Any) -> None:
        """The first frame is a ``server_info`` event when ``server`` is
        provided and ``emit_initial_server_info`` is true — lets a browser
        client confirm the endpoint works before the first step event."""
        from arnes.mcp.sse import playbook_event_stream
        from arnes.playbooks.compiler import PlaybookCompiler

        playbook = PlaybookCompiler.from_string(
            """
name: sse_server_info
objective: Test server_info emission
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Plan"}
"""
        )
        server = ArnesMCPServer()
        gen = playbook_event_stream(executor, playbook, server=server)

        first = await gen.__anext__()
        assert first.startswith("event: server_info\n")
        assert f'"server": "{server.SERVER_INFO["name"]}"' in first
        assert f'"version": "{server.SERVER_INFO["version"]}"' in first
        assert first.endswith("\n\n")

        # Drain the rest so the asyncio task doesn't leak.
        async for _ in gen:
            pass

    @pytest.mark.asyncio
    async def test_emits_step_events_and_run_result_for_happy_path(self, executor: Any) -> None:
        """A 2-step run yields ``step_completed`` for each step, a
        ``run_completed`` transition, and a final ``run_result`` frame
        carrying the aggregate accounting."""
        from arnes.mcp.sse import playbook_event_stream
        from arnes.playbooks.compiler import PlaybookCompiler

        playbook = PlaybookCompiler.from_string(
            """
name: sse_happy
objective: Test happy path
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Plan"}
  - id: s2
    specialist: "@coder"
    input: {spec: "Code"}
"""
        )
        # Skip the server_info frame to keep the test focused on the
        # step / run frames.
        gen = playbook_event_stream(executor, playbook, emit_initial_server_info=False)

        frames: list[str] = []
        async for frame in gen:
            frames.append(frame)

        # Every frame ends with the SSE delimiter.
        assert all(f.endswith("\n\n") for f in frames)

        event_types = [f.split("\n", 1)[0].removeprefix("event: ") for f in frames]
        # Two step_completed + one run_completed + one run_result = 4
        assert event_types.count("step_completed") == 2, event_types
        assert "run_completed" in event_types, event_types
        assert event_types[-1] == "run_result", event_types

        # The final run_result frame carries the aggregate accounting.
        last = frames[-1]
        assert last.startswith("event: run_result\n")
        assert '"success": true' in last
        assert '"steps_executed": 2' in last
        assert '"steps_failed": 0' in last
        # The thread_id is present (non-null) on a successful run.
        assert '"thread_id":' in last and "null" not in last.split('"thread_id":')[1].split(",")[0]

    @pytest.mark.asyncio
    async def test_emits_run_failed_and_run_result_on_step_failure(self, executor: Any) -> None:
        """A failing step yields ``run_failed`` + a final ``run_result``
        frame with ``success: false`` — the client always sees the
        failure transition and the final accounting."""
        from arnes.mcp.sse import playbook_event_stream
        from arnes.playbooks.compiler import PlaybookCompiler

        playbook = PlaybookCompiler.from_string(
            """
name: sse_fail
objective: Test failure
steps:
  - id: s1
    specialist: "@nonexistent"
    input: {task: "x"}
"""
        )
        gen = playbook_event_stream(executor, playbook, emit_initial_server_info=False)

        frames: list[str] = []
        async for frame in gen:
            frames.append(frame)

        event_types = [f.split("\n", 1)[0].removeprefix("event: ") for f in frames]
        assert "run_failed" in event_types, event_types
        assert event_types[-1] == "run_result", event_types

        last = frames[-1]
        assert '"success": false' in last
        # Error message is surfaced on the final result.
        assert '"error":' in last

    @pytest.mark.asyncio
    async def test_skips_server_info_when_flag_false(self, executor: Any) -> None:
        """``emit_initial_server_info=False`` suppresses the up-front
        ``server_info`` frame — the first frame the client sees is a
        real step event."""
        from arnes.mcp.sse import playbook_event_stream
        from arnes.playbooks.compiler import PlaybookCompiler

        playbook = PlaybookCompiler.from_string(
            """
name: sse_no_info
objective: Test no server_info
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Plan"}
"""
        )
        server = ArnesMCPServer()
        gen = playbook_event_stream(
            executor,
            playbook,
            server=server,
            emit_initial_server_info=False,
        )

        first = await gen.__anext__()
        # Must NOT be a server_info event.
        assert not first.startswith("event: server_info\n")
        # Must be a real step event (step_started or step_completed).
        assert first.startswith("event: step_") or first.startswith("event: run_")

        async for _ in gen:
            pass

    def test_event_to_payload_carries_discriminator_fields(self) -> None:
        """``_event_to_payload`` must surface ``event_type``, ``thread_id``,
        ``step_id``, ``timestamp``, and ``data`` so a client can route
        the event without parsing the ``data`` blob."""
        from arnes.mcp.sse import _event_to_payload
        from arnes.thread import Thread
        from arnes.thread.events import StepStartedEvent

        thread = Thread.create()
        event = StepStartedEvent(
            thread_id=thread.id,
            step_id="my_step",
            specialist="@planner",
            data={"step_id": "my_step", "specialist": "@planner"},
        )
        payload = _event_to_payload(event)
        assert payload["event_type"] == "step_started"
        assert payload["step_id"] == "my_step"
        assert payload["specialist"] == "@planner"
        assert payload["thread_id"] == str(thread.id)
        assert "timestamp" in payload
        assert payload["data"] == {"step_id": "my_step", "specialist": "@planner"}

    def test_run_result_to_payload_omits_internal_keys(self) -> None:
        """``_run_result_to_payload`` must filter ``__``-prefixed outputs
        (internal control-flow keys like ``__skip_steps_until``) so they
        don't leak to the SSE client."""
        from arnes.mcp.sse import _run_result_to_payload
        from arnes.playbooks.result import PlaybookRunResult
        from arnes.thread import Thread

        thread = Thread.create()
        result = PlaybookRunResult(
            thread=thread,
            success=True,
            steps_executed=1,
            outputs={
                "visible_output": {"foo": "bar"},
                "__skip_steps_until": {"next_step": True},
            },
        )
        payload = _run_result_to_payload(result)
        assert "visible_output" in payload["outputs"]
        assert "__skip_steps_until" not in payload["outputs"]
        assert payload["thread_id"] == str(thread.id)
        assert payload["success"] is True
        assert payload["steps_executed"] == 1
