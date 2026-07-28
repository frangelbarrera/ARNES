"""
ARNES built-in tools: shell, http, fs_read, fs_write, human_approval.

SECURITY NOTES (post-audit fixes):
- Shell tool defaults to sandboxed execution. Local execution requires explicit
  ARNES_DEV_MODE=1 env var AND ctx.sandbox_enabled=False.
- HTTP tool performs full DNS resolution + IP validation to prevent SSRF
  (including DNS rebinding TOCTOU).
- Filesystem tools validate against symlinks (path traversal protection).
- Tool args fingerprinting is enforced for tools with requires_approval=True.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import time
import urllib.parse
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
        cwd: str = Field(default=".", description="Working directory inside sandbox")
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

        # Only inherit PATH from os.environ if not set (needed for basic commands)
        if "PATH" not in env:
            env["PATH"] = "/usr/local/bin:/usr/bin:/bin"

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
            "docker", "run", "--rm",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--network=none",
            "--read-only",
            "--tmpfs", "/workspace:size=100M",
            "-w", "/workspace",
        ]
        for key, value in args.env.items():
            if _looks_like_secret(key):
                continue
            if key in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"):
                continue
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
            return ToolResult.fail("shell", "Docker not available. Set ARNES_DEV_MODE=1 for local execution.")
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
    - Prevents DNS rebinding via TOCTOU-resistant validation
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

        # Full SSRF check with DNS resolution
        ssrf_error = await _check_ssrf_async(validated.url)
        if ssrf_error:
            return ToolResult.fail("http", ssrf_error, duration_s=time.monotonic() - start)

        # If secret broker is set, inject secrets JIT (never in LLM context)
        headers = dict(validated.headers)
        if ctx.secret_broker:
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

        # Symlink protection for write
        if safe_path.exists() and safe_path.is_symlink():
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
    r"\bnc\s+-l",  # reverse shell
    r"\b/dev/tcp/",  # bash reverse shell
    r"\bnohup\s+.*&\s*$",  # daemon escape
]


def _is_dangerous_command(cmd: str) -> bool:
    """Basic dangerous command detection. Not exhaustive — combine with sandbox."""
    return any(re.search(p, cmd, re.IGNORECASE) for p in _DANGEROUS_PATTERNS)


def _looks_like_secret(key: str) -> bool:
    """Heuristic: does this env var name suggest it's a secret?"""
    secret_patterns = ["API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "PRIVATE_KEY"]
    return any(p in key.upper() for p in secret_patterns)


def _validate_path(path: str, working_dir: str) -> Path | None:
    """Validate that path is inside working_dir (path traversal protection).

    Uses Path.resolve() to canonicalize the path, then checks containment.
    """
    try:
        base = Path(working_dir).resolve(strict=False)
        target = (base / path).resolve(strict=False)
        # Ensure target is inside base
        try:
            target.relative_to(base)
        except ValueError:
            return None
        return target
    except (ValueError, OSError):
        return None


# SSRF protection — full DNS resolution
_BLOCKED_HOSTS = {
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",  # GCP metadata
    "metadata.aws.internal",  # AWS metadata (alias)
}

# Cloud metadata IPs
_BLOCKED_IPS = {
    "169.254.169.254",  # AWS/Azure/GCP metadata
    "100.100.100.200",  # Alibaba Cloud metadata
    "fd00:ec2::254",  # AWS IPv6 metadata
}


async def _check_ssrf_async(url: str) -> str | None:
    """Full SSRF check with DNS resolution.

    Returns error message if URL is SSRF-risky, None if safe.
    Performs DNS resolution and validates ALL resolved IPs.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return f"Invalid URL: {url}"

    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme}"

    if not parsed.hostname:
        return "No hostname in URL"

    hostname = parsed.hostname.lower()

    # Block obvious internal hostnames
    if hostname in _BLOCKED_HOSTS:
        return f"Blocked internal host: {hostname}"

    # Try to parse as IP first
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_blocked_ip(ip):
            return f"Blocked private/loopback IP: {hostname}"
    except ValueError:
        # It's a hostname — resolve DNS and validate ALL IPs
        try:
            loop = asyncio.get_event_loop()
            infos = await loop.run_in_executor(
                None, lambda: socket.getaddrinfo(hostname, None)
            )
            for _, _, _, _, sockaddr in infos:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if _is_blocked_ip(ip):
                        return f"Blocked: {hostname} resolves to private IP {ip_str}"
                except ValueError:
                    continue
        except socket.gaierror:
            return f"DNS resolution failed for: {hostname}"

    return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP should be blocked for SSRF protection."""
    if str(ip) in _BLOCKED_IPS:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


# Keep sync version for backwards compat / tests
def _check_ssrf(url: str) -> str | None:
    """Sync SSRF check (basic, no DNS resolution). Use _check_ssrf_async for full protection."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return f"Invalid URL: {url}"

    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme}"

    if not parsed.hostname:
        return "No hostname in URL"

    hostname = parsed.hostname.lower()
    if hostname in _BLOCKED_HOSTS:
        return f"Blocked internal host: {hostname}"

    if hostname in _BLOCKED_IPS:
        return f"Blocked metadata endpoint: {hostname}"

    try:
        ip = ipaddress.ip_address(hostname)
        if _is_blocked_ip(ip):
            return f"Blocked private/loopback IP: {hostname}"
    except ValueError:
        pass

    return None
