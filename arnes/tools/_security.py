"""ARNES built-in tools — security helpers.

Owns the security primitives shared by :mod:`arnes.tools.builtin`:

- :func:`_is_dangerous_command` — defense-in-depth dangerous-command
  regex checker (NOT a substitute for sandboxing).
- :func:`_looks_like_secret` — heuristic env-var name classifier
  used to scrub secrets from subprocess env.
- :func:`_validate_path` — path-traversal / symlink-escape guard
  used by ``FilesystemReadTool`` / ``FilesystemWriteTool``.
- :func:`_check_ssrf_async` — DNS-resolution + IP-validation guard
  used by ``HttpTool``.
- :func:`_build_ip_pinned_url` — DNS-rebinding TOCTOU mitigation
  (rewrites the URL to use the resolved IP).
- :func:`_is_blocked_ip` — private/loopback/link-local/multicast
  IP classifier.
- Constants ``_DANGEROUS_PATTERNS``, ``_BLOCKED_HOSTS``, ``_BLOCKED_IPS``.

These helpers are shared across tools rather than specific to one, so
they live in a sibling module — ``builtin.py`` stays focused on the
tool classes themselves.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import urllib.parse
from pathlib import Path

# ============================================================
# Dangerous-command detection (defense-in-depth only)
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
    # --- Added in v0.1.x security hardening (defense-in-depth) ---
    r"\bpython\s+-c\b",  # arbitrary code execution via -c
    r"\bpython3\s+-c\b",  # arbitrary code execution via -c
    r"\beval\s*\(",  # JS/Python eval() invocation
    r"\bexec\s*\(",  # Python exec() invocation
    r"\bfind\s+.*-delete\b",  # find ... -delete
    r"\bbase64\s+-d\b",  # base64 decode (payload decoding)
    r"\bbase64\s+--decode\b",  # base64 decode long form
    r"\b\s{2,}.*&&",  # suspiciously-indented chained commands
]


def _is_dangerous_command(cmd: str) -> bool:
    """Basic dangerous command detection.

    .. warning::
        This regex is **defense-in-depth only**. It catches common careless
        payloads but is trivially bypassable by an adversarial prompt
        (obfuscation, env-var expansion, heredocs, aliasing, etc.). It is
        NOT a substitute for running shell commands inside a real sandbox
        (Docker / nsjail / gVisor). For untrusted input, ALWAYS configure
        ``ctx.sandbox_container``.
    """
    return any(re.search(p, cmd, re.IGNORECASE) for p in _DANGEROUS_PATTERNS)


def _looks_like_secret(key: str) -> bool:
    """Heuristic: does this env var name suggest it's a secret?"""
    secret_patterns = [
        "API_KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "PASSWD",
        "CREDENTIAL",
        "PRIVATE_KEY",
    ]
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


# ============================================================
# SSRF protection — full DNS resolution
# ============================================================

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


async def _check_ssrf_async(url: str) -> tuple[str | None, str | None]:
    """Full SSRF check with DNS resolution.

    Returns ``(error_message, resolved_ip)``:

    - On success: ``(None, ip_str)`` — ``ip_str`` is the resolved IP that
      the caller should pin into the actual HTTP request to defeat
      DNS-rebinding TOCTOU attacks.
    - On failure: ``(error_message, None)``.

    The caller is responsible for using ``resolved_ip`` when issuing the
    request (see :func:`_build_ip_pinned_url`). Returning the IP here
    means the SSRF check and the request share the same DNS resolution
    result.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return f"Invalid URL: {url}", None

    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme}", None

    if not parsed.hostname:
        return "No hostname in URL", None

    hostname = parsed.hostname.lower()

    # Block obvious internal hostnames
    if hostname in _BLOCKED_HOSTS:
        return f"Blocked internal host: {hostname}", None

    # Try to parse as IP first — if the URL already contains an IP, we
    # validate it but don't need to resolve DNS. The IP itself is the
    # pinned IP.
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_blocked_ip(ip):
            return f"Blocked private/loopback IP: {hostname}", None
        return None, str(ip)
    except ValueError:
        pass

    # It's a hostname — resolve DNS and validate ALL resolved IPs.
    # We also pick the FIRST safe IP to pin for the request.
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except socket.gaierror:
        return f"DNS resolution failed for: {hostname}", None

    safe_ip: str | None = None
    for _, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return f"Blocked: {hostname} resolves to private IP {ip_str}", None
        if safe_ip is None:
            safe_ip = str(ip_str)

    if safe_ip is None:
        return f"No usable IPs resolved for: {hostname}", None
    return None, safe_ip


def _build_ip_pinned_url(url: str, resolved_ip: str | None) -> tuple[str, str, str]:
    """Rewrite ``url`` to use ``resolved_ip`` as the host.

    Returns ``(pinned_url, original_hostname, scheme)``.

    - The path / query / fragment / port / scheme are preserved.
    - The hostname is replaced by the resolved IP (IPv6 is bracketed per
      RFC 3986 so httpx parses it correctly).
    - The original hostname is returned separately so the caller can set
      the ``Host`` header (HTTP) and ``sni_hostname`` extension (HTTPS)
      for TLS cert validation + virtual-host routing.

    Raises ``ValueError`` if the URL cannot be parsed or no IP is given.
    """
    if resolved_ip is None:
        raise ValueError("No resolved IP available to pin")
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()

    # Bracket IPv6 literals per RFC 3986.
    ip_for_url = resolved_ip
    if ":" in resolved_ip and not resolved_ip.startswith("["):
        ip_for_url = f"[{resolved_ip}]"

    # Reconstruct netloc: [user[:pass]@]host[:port]
    netloc = ip_for_url
    if parsed.port is not None:
        netloc = f"{ip_for_url}:{parsed.port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    pinned = urllib.parse.urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return pinned, hostname, scheme


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


__all__ = [
    "_BLOCKED_HOSTS",
    "_BLOCKED_IPS",
    "_DANGEROUS_PATTERNS",
    "_build_ip_pinned_url",
    "_check_ssrf_async",
    "_is_blocked_ip",
    "_is_dangerous_command",
    "_looks_like_secret",
    "_validate_path",
]
