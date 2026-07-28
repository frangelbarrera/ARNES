"""ARNES built-in tools: shell, http, fs_read, fs_write, human_approval."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from arnes.tools.base import Tool, ToolContext, ToolResult


# ============================================================
# Shell tool — executes commands in sandbox
# ============================================================


class ShellTool(Tool):
    """Execute a shell command. Sandboxed by default (Docker Tier 1)."""

    name: ClassVar[str] = "shell"
    description: ClassVar[str] = (
        "Execute a shell command. Returns stdout, stderr, and exit code. "
        "Use for: build, test, run scripts, inspect files."
    )
    requires_approval: ClassVar[bool] = True  # Destructive by default
    sandbox_tier: ClassVar[int | None] = 1

    class Args(BaseModel):
        command: str = Field(..., description="Shell command to execute")
        cwd: str = Field(default=".", description="Working directory inside sandbox")
        timeout_s: int = Field(default=30, ge=1, le=300)
        env: dict[str, str] = Field(default_factory=dict)

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("shell", f"Invalid args: {e}")

        # SSRF / dangerous command guard (basic, not exhaustive)
        cmd = validated.command
        if _is_dangerous_command(cmd):
            return ToolResult.fail(
                "shell",
                f"Blocked: command matches dangerous pattern. Use a more specific tool.",
                duration_s=time.monotonic() - start,
            )

        # Execute (subprocess in dev-local; Docker in sandbox mode)
        if ctx.sandbox_enabled and ctx.sandbox_container:
            result = await self._execute_in_sandbox(validated, ctx)
        else:
            result = await self._execute_local(validated, ctx)

        result.duration_s = time.monotonic() - start
        return result

    async def _execute_local(self, args: ShellTool.Args, ctx: ToolContext) -> ToolResult:
        """Local execution (dev mode). Logs warning that this is unsafe."""
        env = {**os.environ, **args.env}
        try:
            proc = await asyncio.create_subprocess_shell(
                args.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=args.cwd,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_s)
            return ToolResult(
                tool="shell",
                success=proc.returncode == 0,
                output={
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "exit_code": proc.returncode,
                },
                error=None if proc.returncode == 0 else f"Exit code: {proc.returncode}",
            )
        except TimeoutError:
            return ToolResult.fail("shell", f"Timeout after {args.timeout_s}s")
        except Exception as e:
            return ToolResult.fail("shell", str(e))

    async def _execute_in_sandbox(self, args: ShellTool.Args, ctx: ToolContext) -> ToolResult:
        """Docker-hardened execution (Tier 1 sandbox)."""
        # Build docker run command with all security options
        docker_cmd = [
            "docker", "run", "--rm",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--network=none",
            "--read-only",
            "--tmpfs", "/workspace:size=100M",
            "-w", "/workspace",
        ]
        # Inject env vars (secrets NEVER passed here — they go through secret broker)
        for key, value in args.env.items():
            if _looks_like_secret(key):
                continue  # Skip secrets in shell env
            docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.extend([ctx.sandbox_container or "arnes-sandbox:latest", "sh", "-c", args.command])

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_s)
            return ToolResult(
                tool="shell",
                success=proc.returncode == 0,
                output={
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "exit_code": proc.returncode,
                    "sandbox": "docker-tier1",
                },
                error=None if proc.returncode == 0 else f"Exit code: {proc.returncode}",
            )
        except FileNotFoundError:
            return ToolResult.fail("shell", "Docker not available. Set ctx.sandbox_enabled=False for dev mode.")
        except TimeoutError:
            return ToolResult.fail("shell", f"Sandbox timeout after {args.timeout_s}s")


# ============================================================
# HTTP tool — calls external APIs with SSRF protection
# ============================================================


class HttpTool(Tool):
    """Make HTTP requests with SSRF protection."""

    name: ClassVar[str] = "http"
    description: ClassVar[str] = (
        "Make an HTTP request. Returns status, headers, body. "
        "SSRF-protected: blocks localhost, link-local, private IPs."
    )

    class Args(BaseModel):
        url: str
        method: str = Field(default="GET", pattern="^(GET|POST|PUT|DELETE|PATCH|HEAD)$")
        headers: dict[str, str] = Field(default_factory=dict)
        body: str | None = None
        timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("http", f"Invalid args: {e}")

        # SSRF check
        ssrf_error = _check_ssrf(validated.url)
        if ssrf_error:
            return ToolResult.fail("http", ssrf_error, duration_s=time.monotonic() - start)

        # If secret broker is set, inject secrets JIT (never in LLM context)
        headers = dict(validated.headers)
        if ctx.secret_broker:
            # Secret broker injects Authorization headers without exposing values to LLM
            headers = ctx.secret_broker.inject_secrets(headers, ctx)

        try:
            async with httpx.AsyncClient(timeout=validated.timeout_s) as client:
                response = await client.request(
                    method=validated.method,
                    url=validated.url,
                    headers=headers,
                    content=validated.body,
                )
            return ToolResult.ok(
                "http",
                {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text[:10000],  # Truncate to prevent context bloat
                },
                duration_s=time.monotonic() - start,
                url=validated.url,
            )
        except httpx.HTTPError as e:
            return ToolResult.fail("http", str(e), duration_s=time.monotonic() - start)


# ============================================================
# Filesystem tools — path-validated
# ============================================================


class FilesystemReadTool(Tool):
    """Read a file with path traversal protection."""

    name: ClassVar[str] = "fs_read"
    description: ClassVar[str] = "Read a file. Path must be inside working_dir."

    class Args(BaseModel):
        path: str
        max_bytes: int = Field(default=65536, ge=1, le=1048576)

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("fs_read", f"Invalid args: {e}")

        safe_path = _validate_path(validated.path, ctx.working_dir)
        if not safe_path:
            return ToolResult.fail("fs_read", f"Path outside working_dir: {validated.path}")

        try:
            content = safe_path.read_bytes()[: validated.max_bytes]
            return ToolResult.ok(
                "fs_read",
                {
                    "path": str(safe_path),
                    "content": content.decode("utf-8", errors="replace"),
                    "size_bytes": len(content),
                },
            )
        except FileNotFoundError:
            return ToolResult.fail("fs_read", f"File not found: {validated.path}")
        except PermissionError:
            return ToolResult.fail("fs_read", f"Permission denied: {validated.path}")


class FilesystemWriteTool(Tool):
    """Write a file with path traversal protection. Requires approval."""

    name: ClassVar[str] = "fs_write"
    description: ClassVar[str] = "Write a file. Path must be inside working_dir. Requires approval."
    requires_approval: ClassVar[bool] = True

    class Args(BaseModel):
        path: str
        content: str
        mode: str = Field(default="w", pattern="^(w|a)$")

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("fs_write", f"Invalid args: {e}")

        safe_path = _validate_path(validated.path, ctx.working_dir)
        if not safe_path:
            return ToolResult.fail("fs_write", f"Path outside working_dir: {validated.path}")

        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with safe_path.open(validated.mode) as f:
                f.write(validated.content)
            return ToolResult.ok(
                "fs_write",
                {"path": str(safe_path), "bytes_written": len(validated.content)},
            )
        except PermissionError:
            return ToolResult.fail("fs_write", f"Permission denied: {validated.path}")


# ============================================================
# Human approval tool — HITL as a typed tool call
# ============================================================


class HumanApprovalTool(Tool):
    """Pause execution and ask a human for approval. HITL as a tool."""

    name: ClassVar[str] = "human_approval"
    description: ClassVar[str] = (
        "Ask a human for approval before proceeding. "
        "Use for destructive actions, irreversible changes, or high-cost operations."
    )

    class Args(BaseModel):
        question: str = Field(..., description="What you're asking approval for")
        options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
        default: str | None = None
        ttl_s: int = Field(default=86400, ge=60, le=604800)  # 1min - 7days

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        # In MVP, this returns immediately with "approved" if no human interface.
        # Real HITL goes through the MCP server / CLI interactive prompt.
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("human_approval", f"Invalid args: {e}")

        # For non-interactive runs, default to reject (fail-safe)
        if not ctx.metadata.get("interactive", False):
            return ToolResult(
                tool="human_approval",
                success=False,
                output={"decision": "auto_rejected", "reason": "non_interactive"},
                error="No human available in non-interactive mode. Set ctx.metadata['interactive']=True.",
            )

        # Interactive prompt via rich (CLI mode)
        try:
            from rich.console import Console
            from rich.prompt import Confirm

            console = Console()
            console.print(f"\n[yellow]Human approval required:[/yellow] {validated.question}")
            approved = Confirm.ask("Approve?", default=False)
            return ToolResult.ok(
                "human_approval",
                {"decision": "approved" if approved else "rejected"},
            )
        except ImportError:
            return ToolResult.fail("human_approval", "rich not installed for interactive prompt")


# ============================================================
# Helpers
# ============================================================


_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",  # fork bomb
    r"\b>\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+777\s+/",
    r"\bcurl\s+.*\|\s*sh",
    r"\bwget\s+.*\|\s*sh",
]


def _is_dangerous_command(cmd: str) -> bool:
    """Basic dangerous command detection. Not exhaustive — combine with sandbox."""
    return any(re.search(p, cmd, re.IGNORECASE) for p in _DANGEROUS_PATTERNS)


def _looks_like_secret(key: str) -> bool:
    """Heuristic: does this env var name suggest it's a secret?"""
    secret_patterns = ["API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL"]
    return any(p in key.upper() for p in secret_patterns)


def _validate_path(path: str, working_dir: str) -> Path | None:
    """Validate that path is inside working_dir (path traversal protection)."""
    try:
        base = Path(working_dir).resolve()
        target = (base / path).resolve()
        # Ensure target is inside base
        if base in target.parents or target == base:
            return target
        return None
    except (ValueError, OSError):
        return None


# SSRF protection
_PRIVATE_IP_PATTERNS = [
    r"^10\.",
    r"^172\.(1[6-9]|2[0-9]|3[01])\.",
    r"^192\.168\.",
    r"^127\.",
    r"^0\.",
    r"^169\.254\.",
    r"^::1$",
    r"^fc00:",
    r"^fe80:",
]


def _check_ssrf(url: str) -> str | None:
    """Return error message if URL is SSRF-risky, None if safe."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return f"Invalid URL: {url}"

    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme}"

    if not parsed.hostname:
        return "No hostname in URL"

    # Block obvious internal hostnames
    internal_hosts = {"localhost", "ip6-localhost", "ip6-loopback"}
    if parsed.hostname.lower() in internal_hosts:
        return f"Blocked internal host: {parsed.hostname}"

    # Try to parse as IP and check if private
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return f"Blocked private/loopback IP: {parsed.hostname}"
    except ValueError:
        # It's a hostname, not an IP — allow (DNS will resolve)
        pass

    # Block cloud metadata endpoints
    if parsed.hostname == "169.254.169.254":
        return "Blocked cloud metadata endpoint"

    return None
