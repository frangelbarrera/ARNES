"""Tests for arnes.tools."""

from __future__ import annotations

from uuid import uuid4

import pytest

from arnes.tools.base import Tool, ToolContext, ToolResult
from arnes.tools.builtin import (
    FilesystemReadTool,
    FilesystemWriteTool,
    HttpTool,
    ShellTool,
)
from arnes.tools.registry import get_default_registry


class TestToolRegistry:
    def test_default_registry_has_all_builtin_tools(self):
        registry = get_default_registry()
        assert "shell" in registry
        assert "http" in registry
        assert "fs_read" in registry
        assert "fs_write" in registry
        assert "human_approval" in registry
        assert len(registry) == 5

    def test_list_returns_sorted(self):
        registry = get_default_registry()
        tools = registry.list_names()
        assert tools == sorted(tools)

    def test_schemas_returns_json_schemas(self):
        registry = get_default_registry()
        schemas = registry.schemas()
        assert len(schemas) == 5
        for s in schemas:
            assert "name" in s
            assert "description" in s
            assert "args" in s


class TestToolResult:
    def test_ok_factory(self):
        result = ToolResult.ok("test", {"output": "data"}, duration_s=0.1)
        assert result.success is True
        assert result.output == {"output": "data"}
        assert result.duration_s == 0.1

    def test_fail_factory(self):
        result = ToolResult.fail("test", "Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.output is None


class TestShellTool:
    @pytest.fixture
    def ctx(self, monkeypatch):
        # SECURITY FIX: Shell tool now requires ARNES_DEV_MODE=1 for local exec
        monkeypatch.setenv("ARNES_DEV_MODE", "1")
        return ToolContext(thread_id=uuid4(), step_id="test")

    @pytest.mark.asyncio
    async def test_execute_echo(self, ctx):
        """Cross-platform: use python with a script file (python -c is blocked)."""
        import tempfile
        from pathlib import Path

        tool = ShellTool()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            script_path = f.name
        try:
            result = await tool.execute({"command": f"python {script_path}", "timeout_s": 10}, ctx)
            assert result.success is True, f"Shell failed: {result.error}"
            assert "hello" in result.output["stdout"]
        finally:
            Path(script_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self, ctx):
        tool = ShellTool()
        result = await tool.execute({"command": "rm -rf /"}, ctx)
        assert result.success is False
        assert "dangerous" in result.error.lower()

    @pytest.mark.asyncio
    async def test_python_c_blocked(self, ctx):
        """SECURITY: ``python -c`` is now in the dangerous pattern list."""
        tool = ShellTool()
        result = await tool.execute({"command": 'python -c "print(1)"'}, ctx)
        assert result.success is False
        assert "dangerous" in result.error.lower()

    @pytest.mark.asyncio
    async def test_eval_exec_blocked(self, ctx):
        """SECURITY: eval() and exec() invocations match the dangerous pattern."""
        from arnes.tools.builtin import _is_dangerous_command

        assert _is_dangerous_command("eval(  open  )") is True
        assert _is_dangerous_command("exec( compile(...) )") is True
        assert _is_dangerous_command("find / -delete") is True
        assert _is_dangerous_command("echo abc | base64 -d") is True
        assert _is_dangerous_command("echo abc | base64 --decode") is True
        # sanity: normal commands are NOT flagged
        assert _is_dangerous_command("echo hello") is False
        assert _is_dangerous_command("ls -la") is False

    @pytest.mark.asyncio
    async def test_local_exec_blocked_without_dev_mode(self, monkeypatch):
        """SECURITY: Without ARNES_DEV_MODE=1, local shell execution must fail."""
        monkeypatch.delenv("ARNES_DEV_MODE", raising=False)
        ctx = ToolContext(thread_id=uuid4(), step_id="test", sandbox_enabled=False)
        tool = ShellTool()
        result = await tool.execute({"command": "echo hello"}, ctx)
        assert result.success is False
        assert "ARNES_DEV_MODE" in result.error

    @pytest.mark.asyncio
    async def test_secrets_filtered_from_env(self, ctx):
        """SECURITY: API keys in args.env must be filtered out.

        Uses a python script file because ``python -c`` is now blocked
        by the dangerous-command regex (defense-in-depth).
        """
        import tempfile
        from pathlib import Path

        tool = ShellTool()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                "import os\n"
                "print(os.environ.get('API_KEY', 'NOT_SET'))\n"
                "print(os.environ.get('FOO', 'NOT_SET'))\n"
            )
            script_path = f.name
        try:
            result = await tool.execute(
                {
                    "command": f"python {script_path}",
                    "env": {"API_KEY": "sk-secret", "FOO": "bar"},
                },
                ctx,
            )
            assert result.success is True, f"Shell failed: {result.error}"
            # The secret must NOT appear in the subprocess env
            assert "sk-secret" not in result.output["stdout"]
            assert "NOT_SET" in result.output["stdout"]  # API_KEY was filtered
            assert "bar" in result.output["stdout"]  # FOO was passed through
        finally:
            Path(script_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_invalid_args(self, ctx):
        tool = ShellTool()
        result = await tool.execute({}, ctx)
        assert result.success is False


class TestHttpTool:
    @pytest.fixture
    def ctx(self):
        return ToolContext(thread_id=uuid4())

    @pytest.mark.asyncio
    async def test_ssrf_localhost_blocked(self, ctx):
        tool = HttpTool()
        result = await tool.execute({"url": "http://localhost:8080/secret"}, ctx)
        assert result.success is False
        assert "ssrf" in result.error.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ssrf_private_ip_blocked(self, ctx):
        tool = HttpTool()
        result = await tool.execute({"url": "http://10.0.0.1/"}, ctx)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_ssrf_metadata_endpoint_blocked(self, ctx):
        tool = HttpTool()
        result = await tool.execute({"url": "http://169.254.169.254/latest/meta-data/"}, ctx)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_ssrf_non_http_scheme_blocked(self, ctx):
        tool = HttpTool()
        result = await tool.execute({"url": "file:///etc/passwd"}, ctx)
        assert result.success is False


class TestFilesystemTools:
    @pytest.fixture
    def ctx_with_tmp(self, tmp_path):
        return ToolContext(thread_id=uuid4(), working_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_fs_write_and_read(self, ctx_with_tmp):
        write_tool = FilesystemWriteTool()
        read_tool = FilesystemReadTool()

        # Write a file
        result = await write_tool.execute(
            {"path": "test.txt", "content": "hello world"},
            ctx_with_tmp,
        )
        assert result.success is True

        # Read it back
        result = await read_tool.execute({"path": "test.txt"}, ctx_with_tmp)
        assert result.success is True
        assert result.output["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_fs_read_path_traversal_blocked(self, ctx_with_tmp):
        read_tool = FilesystemReadTool()
        result = await read_tool.execute({"path": "../../../etc/passwd"}, ctx_with_tmp)
        assert result.success is False
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fs_write_path_traversal_blocked(self, ctx_with_tmp):
        write_tool = FilesystemWriteTool()
        result = await write_tool.execute(
            {"path": "../../etc/cron.d/evil", "content": "* * * * * rm -rf /"},
            ctx_with_tmp,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_fs_read_nonexistent(self, ctx_with_tmp):
        read_tool = FilesystemReadTool()
        result = await read_tool.execute({"path": "nonexistent.txt"}, ctx_with_tmp)
        assert result.success is False
        assert "not found" in result.error.lower()


class TestToolFingerprint:
    def test_fingerprint_stable(self):
        args1 = {"a": 1, "b": 2}
        args2 = {"b": 2, "a": 1}  # same args, different order
        assert Tool.fingerprint(args1) == Tool.fingerprint(args2)

    def test_fingerprint_different(self):
        args1 = {"a": 1, "b": 2}
        args2 = {"a": 1, "b": 3}
        assert Tool.fingerprint(args1) != Tool.fingerprint(args2)

    def test_fingerprint_short(self):
        fp = Tool.fingerprint({"x": 1})
        assert len(fp) == 16  # 16 char hex
