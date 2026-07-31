"""
ARNES built-in tools: shell, http, fs_read, fs_write, human_approval.

SECURITY NOTES (post-audit fixes):
- Shell tool defaults to sandboxed execution. Local execution requires explicit
  ARNES_DEV_MODE=1 env var AND ctx.sandbox_enabled=False. The dangerous-command
  regex is DEFENSE-IN-DEPTH ONLY — it is not a substitute for sandboxing.
- HTTP tool performs full DNS resolution + IP validation to prevent SSRF.
  The resolved IP is PINNED for the actual httpx request (URL rewritten to
  use the IP, Host header set to original hostname, SNI preserved for HTTPS)
  to defeat DNS-rebinding TOCTOU. Redirects are NOT followed automatically.
- Filesystem tools validate against symlinks (path traversal protection).
- Tool args fingerprinting is enforced for tools with requires_approval=True.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from arnes.tools.base import Tool, ToolContext, ToolResult

# ============================================================
# Shell tool — executes commands in sandbox by default
# ============================================================


class ShellTool(Tool):
    """Execute a shell command. Sandboxed by default (Docker Tier 1).

    SECURITY: Local execution (no sandbox) requires BOTH:
    - ctx.sandbox_enabled = False
    - ARNES_DEV_MODE environment variable set to "1"

    This double-gate prevents accidental RCE in production.

    .. warning::
        The dangerous-command regex checked by ``_is_dangerous_command`` is
        **defense-in-depth only** and is trivially bypassable by an
        adversarial prompt (obfuscation, env-var expansion, heredocs,
        aliasing, etc.). It exists to catch careless commands, not to
        substitute for a real sandbox (Docker / nsjail / gVisor). For
        untrusted input, ALWAYS run inside ``ctx.sandbox_container``.
    """

    name: ClassVar[str] = "shell"
    description: ClassVar[str] = (
        "Execute a shell command. Returns stdout, stderr, and exit code. "
        "Use for: build, test, run scripts, inspect files. "
        "Sandboxed by default — local execution requires ARNES_DEV_MODE=1."
    )
    requires_approval: ClassVar[bool] = True  # Destructive by default
    sandbox_tier: ClassVar[int | None] = 1

    class Args(BaseModel):
        command: str = Field(..., description="Shell command to execute")
        cwd: str = Field(
            default=".",
            description="Working directory inside sandbox",
            pattern=r"^[a-zA-Z0-9_\-./ ]+$",
        )
        timeout_s: int = Field(default=30, ge=1, le=300)
        env: dict[str, str] = Field(default_factory=dict)

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            validated = self.Args.model_validate(args)
        except Exception as e:
            return ToolResult.fail("shell", f"Invalid args: {e}")

        cmd = validated.command
        if _is_dangerous_command(cmd):
            return ToolResult.fail(
                "shell",
                "Blocked: command matches dangerous pattern. Use a more specific tool.",
                duration_s=time.monotonic() - start,
            )

        if ctx.sandbox_enabled and ctx.sandbox_container:
            result = await self._execute_in_sandbox(validated, ctx)
        else:
            # SECURITY: Require explicit dev mode override
            if os.getenv("ARNES_DEV_MODE", "0") != "1":
                return ToolResult.fail(
                    "shell",
                    "Local shell execution disabled by default. Set ARNES_DEV_MODE=1 or "
                    "configure a sandbox container in ToolContext.",
                    duration_s=time.monotonic() - start,
                )
            result = await self._execute_local(validated, ctx)

        result.duration_s = time.monotonic() - start
        return result

    async def _execute_local(self, args: ShellTool.Args, ctx: ToolContext) -> ToolResult:
        """Local execution (dev mode only). NEVER inherits os.environ — only
        explicit env vars from args.env are passed (and secrets are filtered)."""
        env: dict[str, str] = {}

        for key, value in args.env.items():
            if _looks_like_secret(key):
                continue
            if key in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"):
                continue
            env[key] = value

        # Cross-platform PATH: inherit from os.environ if available
        # (needed for basic commands like 'python', 'echo', etc.)
        if "PATH" not in env:
            env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        # On Windows, also preserve SystemRoot and COMSPEC (needed for subprocess)
        if sys.platform == "win32":
            if "SYSTEMROOT" not in env:
                env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
            if "COMSPEC" not in env:
                env["COMSPEC"] = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")

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
                    "mode": "local-dev",
                },
                error=None if proc.returncode == 0 else f"Exit code: {proc.returncode}",
            )
        except TimeoutError:
            return ToolResult.fail("shell", f"Timeout after {args.timeout_s}s")
        except Exception as e:
            return ToolResult.fail("shell", str(e))

    async def _execute_in_sandbox(self, args: ShellTool.Args, ctx: ToolContext) -> ToolResult:
        """Docker-hardened execution (Tier 1 sandbox)."""
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--network=none",
            "--read-only",
            "--tmpfs",
            "/workspace:size=100M",
            "-w",
            "/workspace",
        ]
        for key, value in args.env.items():
            if _looks_like_secret(key):
                continue
            if key in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"):
                continue
            docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.extend(
            [ctx.sandbox_container or "arnes-sandbox:latest", "sh", "-c", args.command]
        )

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
            return ToolResult.fail(
                "shell", "Docker not available. Set ARNES_DEV_MODE=1 for local execution."
            )
        except TimeoutError:
            return ToolResult.fail("shell", f"Sandbox timeout after {args.timeout_s}s")


# ============================================================
# HTTP tool — calls external APIs with full SSRF protection
# ============================================================


class HttpTool(Tool):
    """Make HTTP requests with full SSRF protection.

    Security measures:
    - Blocks localhost, private IPs, link-local, multicast by default
    - Performs DNS resolution and validates ALL resolved IPs
    - Blocks cloud metadata endpoints (AWS, GCP, Azure)
    - **DNS-rebinding mitigation**: the resolved IP is pinned for the actual
      httpx request by rewriting the URL to use the IP directly, setting the
      ``Host`` header to the original hostname, and (for HTTPS) setting
      ``sni_hostname`` in the request extensions. Redirects are NOT followed
      by default — a ``Location`` header could point to a brand-new hostname
      and re-trigger DNS resolution.
    """

    name: ClassVar[str] = "http"
    description: ClassVar[str] = (
        "Make an HTTP request. Returns status, headers, body. "
        "SSRF-protected: blocks localhost, private IPs, cloud metadata endpoints."
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

        # Full SSRF check with DNS resolution. Returns the resolved IP so we
        # can pin it for the request (DNS-rebinding TOCTOU mitigation).
        ssrf_error, resolved_ip = await _check_ssrf_async(validated.url)
        if ssrf_error:
            return ToolResult.fail("http", ssrf_error, duration_s=time.monotonic() - start)

        headers = dict(validated.headers)

        # Rewrite the URL to use the resolved IP directly. This prevents
        # httpx from re-resolving DNS (which would re-open the DNS-rebinding
        # TOCTOU window that _check_ssrf_async just closed). The original
        # hostname is preserved as the Host header (HTTP) and as SNI (HTTPS).
        try:
            pinned_url, original_host, scheme = _build_ip_pinned_url(validated.url, resolved_ip)
        except ValueError as e:
            return ToolResult.fail("http", str(e), duration_s=time.monotonic() - start)

        # The Host header must match the original hostname for virtual-host
        # routing to work. httpx lets us override it explicitly.
        headers.setdefault("Host", original_host)

        try:
            async with httpx.AsyncClient(
                timeout=validated.timeout_s,
                follow_redirects=False,  # redirects would re-trigger DNS
            ) as client:
                request = client.build_request(
                    method=validated.method,
                    url=pinned_url,
                    headers=headers,
                    content=validated.body,
                )
                # For HTTPS, set SNI to the original hostname so the TLS
                # handshake presents the correct cert and validates against
                # the original hostname (not the IP). The httpcore backend
                # expects ``sni_hostname`` to be a ``str``.
                if scheme == "https":
                    request.extensions["sni_hostname"] = original_host
                response = await client.send(request)
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
# Filesystem tools — path-validated with symlink protection
# ============================================================


class FilesystemReadTool(Tool):
    """Read a file with path traversal AND symlink protection."""

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

        # Symlink protection: don't follow symlinks outside working_dir
        if safe_path.is_symlink():
            target = safe_path.resolve()
            base = Path(ctx.working_dir).resolve()
            if base not in target.parents and target != base:
                return ToolResult.fail("fs_read", f"Symlink escapes working_dir: {validated.path}")

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

        # Symlink protection for write.
        #
        # SECURITY (FIX-R3-SEC): use ``is_symlink()`` ALONE, NOT
        # ``exists() and is_symlink()``. ``Path.exists()`` follows the
        # link and returns False for a DANGLING symlink (target missing),
        # which previously caused this guard to be skipped — letting a
        # write through a dangling symlink that points outside
        # ``working_dir`` (e.g. ``link -> /etc/cron.d/evil`` with the
        # target not yet created). ``is_symlink()`` checks the link
        # entry itself, so it catches both dangling and non-dangling
        # symlinks.
        if safe_path.is_symlink():
            target = safe_path.resolve()
            base = Path(ctx.working_dir).resolve()
            if base not in target.parents and target != base:
                return ToolResult.fail("fs_write", f"Symlink escapes working_dir: {validated.path}")

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


# R16: security helpers extracted to :mod:`arnes.tools._security`
# to keep this module under the AGENTS.md 500-line rule. Re-exported
# here for backwards compatibility (tests import
# ``_is_dangerous_command`` from ``arnes.tools.builtin``).
from arnes.tools._security import (  # noqa: E402,F401 - re-export
    _BLOCKED_HOSTS,
    _BLOCKED_IPS,
    _DANGEROUS_PATTERNS,
    _build_ip_pinned_url,
    _check_ssrf_async,
    _is_blocked_ip,
    _is_dangerous_command,
    _looks_like_secret,
    _validate_path,
)
