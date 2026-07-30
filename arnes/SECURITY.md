# Security Policy

## Supported Versions

ARNES follows semantic versioning. Only the latest minor version receives
security updates.

| Version | Security Support |
|---------|-----------------|
| 0.1.x   | ✅ Active         |
| < 0.1   | ❌ Not supported  |

## Reporting a Vulnerability

**DO NOT open a public GitHub issue to report security vulnerabilities.**

ARNES uses
[GitHub Security Advisories](https://github.com/frangelbarrera/ARNES/security/advisories/new)
to receive private vulnerability reports.

### Process

1. **Report** via [private GitHub Security Advisory](https://github.com/frangelbarrera/ARNES/security/advisories/new)
   or email `frangelbarrera@users.noreply.github.com`.
2. **Acknowledge**: we respond within 72 hours confirming receipt.
3. **Investigation**: we will keep you informed of progress every 7 days.
4. **Fix**: if the vulnerability is valid, we publish a patch within 30 days
   (or an immediate workaround if the fix is complex).
5. **Disclosure**: we publish a public advisory on GitHub + CVE if applicable.
6. **Credit**: we give you credit in the advisory (unless you prefer to
   remain anonymous).

## Security Scope

ARNES executes code (via `shell`, `fs_write` tools) and calls external APIs.
Any issue that allows:

- Arbitrary code execution outside the sandbox
- Leakage of API keys, tokens, or secrets
- Bypass of CostGuard (denial-of-wallet)
- Bypass of verification layer (forced hallucinations)
- Path traversal in `fs_*` tools or MCP playbook endpoints
- SSRF in `http` tool
- Persistent prompt injection that survives between sessions

is a security vulnerability and must be reported privately.

## Implemented Security Measures (v0.1.x)

The following measures are **implemented and tested today**:

### Secret Broker

API keys **never** enter the LLM context window. ARNES reads them from the
environment and injects them just-in-time into HTTP calls. The agent only
sees `<api_key_set: true>`. Environment variables whose names match a secret
pattern (`API_KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `CREDENTIAL`,
`PRIVATE_KEY`) are filtered out before being passed to subprocesses.

### Input Validation

All tools accept inputs validated by pydantic schemas. The `fs_read` /
`fs_write` tools validate paths against the working directory allow-list
and reject symlinks that escape it.

### SSRF Protection (http tool)

The `http` tool validates URLs against an SSRF block-list:

- Blocked schemes (only `http` / `https` allowed).
- Blocked hostnames: `localhost`, `ip6-localhost`, `ip6-loopback`, cloud
  metadata hostnames.
- DNS resolution is performed and **every** resolved IP is checked against:
  loopback, private, link-local, multicast, reserved, unspecified, and the
  cloud metadata IPs (`169.254.169.254`, `100.100.100.200`, `fd00:ec2::254`).
- The resolved IP is pinned for the actual httpx request (URL rewritten to
  the IP) to mitigate DNS-rebinding TOCTOU. The original `Host` header is
  preserved for virtual-host routing.

### Shell Tool — Defense-in-Depth

The `shell` tool:

- Requires `ARNES_DEV_MODE=1` to execute locally (default: disabled).
- Filters secret-named env vars from the subprocess environment.
- Strips `PATH` / `LD_PRELOAD` / `LD_LIBRARY_PATH` / `PYTHONPATH` from
  user-provided env (PATH is re-injected from the parent process for
  usability).
- Applies a regex deny-list (`rm -rf /`, `mkfs`, `dd if=`, fork bombs,
  `curl|sh`, reverse shells, `python -c`, `eval(`/`exec(`,
  `find … -delete`, `base64 -d`, suspiciously indented chained commands).
  This is **defense-in-depth only** and is not a substitute for sandboxing
  — see "Current Limitations" below.

### MCP HTTP Transport Hardening

`serve_http` (HTTP transport for the MCP server) enforces:

- **Bearer token auth** — when `ARNES_MCP_TOKEN` is set, every request must
  carry `Authorization: Bearer <token>` (constant-time comparison).
- **Loopback-only binding** — when no token is configured, the server
  refuses to bind on anything other than `127.0.0.1` / `::1` / `localhost`.
- **Rate limiting** — max 100 requests/minute per client IP (sliding
  window, in-memory).
- **Request size cap** — bodies > 1 MiB are rejected with HTTP 413.
- **Generic error responses** — exceptions are logged server-side but the
  client receives a generic `Internal server error` (no path / stack
  leakage).
- **Path validation on all playbook endpoints** — `arnes_run_playbook`,
  `arnes_validate_playbook`, and `arnes_list_playbooks` all share the same
  path-traversal guard (rejects `/etc`, `/root`, `/var`, `/proc`, `/sys`,
  `/dev`).

### Cost Guard

Each run has a declared USD budget. At 100% spend, ARNES aborts the run.
A temporal circuit breaker aborts if per-call spend is implausibly high.

### Human-in-the-Loop (HITL)

Tools marked `requires_approval=True` (e.g. `shell`, `fs_write`) require
explicit human approval in interactive mode and are **auto-rejected** in
non-interactive mode. Approved argument fingerprints are persisted in the
run's `ToolContext.metadata` and used to detect "rug-pull" attempts where
the LLM tries to call the same tool with different arguments after
approval.

### Audit Log

Every LLM call, every tool execution, every CostGuard decision is logged to
the markdown bitácora. The bitácora is auditable and re-executable.

## Current Limitations

The following are **explicitly not** security guarantees of v0.1.x. They
are planned for v0.2 and tracked in the security audits:

### 1. No Default Sandbox (Tier 1 Docker sandbox is NOT wired up by default)

Although the `shell` tool has the *code path* for a Docker-hardened
container (`--security-opt=no-new-privileges`, `--cap-drop=ALL`,
`--network=none`, `--read-only`, tmpfs `/workspace`), **the sandbox is not
configured by default** in v0.1.x. Local shell execution requires the
`ARNES_DEV_MODE=1` environment variable as a double-gate safety measure.
Full Docker sandbox integration (auto-spawn, image pinning, network
egress policy) lands in v0.2. **Do not enable `ARNES_DEV_MODE=1` on
untrusted inputs in v0.1.x.**

### 2. CostGuard does not pause at 95%

The v0.1.x CostGuard aborts at 100% budget exhaustion. The "pause at 95%
and ask for human approval" behavior is **planned for v0.2**, not
implemented today. There is also no temporal circuit breaker in v0.1.x.

### 3. SSRF check is best-effort, not bulletproof

- The DNS-rebinding TOCTOU is mitigated by rewriting the request URL to
  the resolved IP and preserving the Host header. This works for the
  common case but does **not** cover HTTP redirects (httpx may follow a
  `Location` header to a brand-new hostname, re-resolving DNS through the
  same check). Set `follow_redirects=False` (or audit each redirect) if
  this matters for your deployment.
- IPv6 scope IDs and edge-case resolver behaviors are not exhaustively
  tested.
- The block-list is a static allow/deny list; it does not consume threat
  feeds.

### 4. Shell regex is defense-in-depth, not a sandbox

The dangerous-command regex catches the common payloads (`rm -rf /`,
`mkfs`, `curl|sh`, `python -c`, `eval()`, `base64 -d`, etc.) but is
**trivially bypassable** by an attacker who controls the command string
(obfuscation, environment variable expansion, heredocs, etc.). The only
reliable mitigation is to run shell commands inside a real sandbox
(Docker / nsjail / gVisor). The regex exists to catch careless prompts,
not adversarial ones.

### 5. MCP HTTP transport is single-process

The rate limiter is in-process and per-instance. A multi-worker
deployment (e.g. behind gunicorn with N workers) gets N× the configured
limit. Use a real reverse proxy (nginx, Caddy) with shared-state rate
limiting for production deployments. CSRF protection is also not
implemented at the protocol layer — rely on the bearer token + the
same-origin policy of the consuming client.

### 6. No mTLS / HMAC request signing

Authentication is a single bearer token. There is no mutual TLS, no
per-request HMAC signature, and no token rotation protocol. Treat the
HTTP transport as suitable for trusted local networks only.

### 7. Playbook path validation is prefix-based

The MCP playbook path check rejects a fixed list of system prefixes
(`/etc`, `/root`, `/var`, `/proc`, `/sys`, `/dev`). It does **not**
implement a chroot-style allow-list of the user's playbook directory. A
path like `/home/otheruser/secret.yaml` would pass the check today. Bind
the MCP server's working directory to a jail / container if you need a
harder guarantee.

## Acknowledgments

We thank those who report vulnerabilities responsibly. List of reports in
[SECURITY_CREDITS.md](SECURITY_CREDITS.md).
