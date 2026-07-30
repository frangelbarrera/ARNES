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
and reject symlinks (both dangling and non-dangling) that escape it.

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

- Is wired into the Docker sandbox by default when the `docker` CLI is on
  `PATH`. The `PlaybookExecutor` auto-detects Docker at construction time
  and sets `sandbox_enabled=True` + `sandbox_container="arnes-sandbox:latest"`
  on every `ToolContext` it creates. When Docker is NOT available, the
  executor falls back to `sandbox_enabled=False` and logs a warning — in
  that mode the shell tool requires `ARNES_DEV_MODE=1` to execute locally
  (double-gate safety measure).
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

Each run has a declared USD budget. ARNES enforces it at three thresholds:

- **75%** (`warn_at_pct`): emits a `CostThresholdEvent(level="warn")` and
  logs a warning. Execution continues.
- **95%** (`pause_at_pct`): emits a `CostThresholdEvent(level="pause")`.
  In interactive runs (`interactive=True` passed to `complete()`), the
  guard also sets `_paused=True`, emits a `HumanApprovalRequestedEvent`
  via the events sink, and raises `BudgetExceeded(level="pause")` so the
  executor halts the run for human approval. In non-interactive runs, the
  guard logs a warning and continues — the hard stop at 100% will catch
  the run if spend keeps growing.
- **100%** (`abort_at_pct`): hard stop. Sets `_aborted=True`, raises
  `BudgetExceeded(level="hard_stop")`.

A temporal circuit breaker also aborts if per-minute spend exceeds
`max_usd_per_minute` (denial-of-wallet defense), and a pre-flight check
rejects calls whose projected cost would push spend over the budget
before the provider is even invoked.

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

### 1. Sandbox auto-detection is CLI-presence only

The `PlaybookExecutor` enables the Docker sandbox when the `docker` CLI is
on `PATH` (see `_is_docker_available()`). It does **not** verify the
daemon is running, that the `arnes-sandbox:latest` image exists, or that
the container has network egress filtering. If the daemon is down or the
image is missing, `ShellTool._execute_in_sandbox` returns a
`ToolResult.fail(...)` at execution time — it does NOT silently fall
through to local execution. Operators must build and pin the
`arnes-sandbox:latest` image themselves. When Docker is entirely absent,
the executor falls back to `sandbox_enabled=False` and the shell tool
requires `ARNES_DEV_MODE=1` as a double-gate.

### 2. SSRF check is best-effort, not bulletproof

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

### 3. Shell regex is defense-in-depth, not a sandbox

The dangerous-command regex catches the common payloads (`rm -rf /`,
`mkfs`, `curl|sh`, `python -c`, `eval()`, `base64 -d`, etc.) but is
**trivially bypassable** by an attacker who controls the command string
(obfuscation, environment variable expansion, heredocs, etc.). The only
reliable mitigation is to run shell commands inside a real sandbox
(Docker / nsjail / gVisor). The regex exists to catch careless prompts,
not adversarial ones.

### 4. MCP HTTP transport is single-process

The rate limiter is in-process and per-instance. A multi-worker
deployment (e.g. behind gunicorn with N workers) gets N× the configured
limit. Use a real reverse proxy (nginx, Caddy) with shared-state rate
limiting for production deployments. CSRF protection is also not
implemented at the protocol layer — rely on the bearer token + the
same-origin policy of the consuming client.

### 5. No mTLS / HMAC request signing

Authentication is a single bearer token. There is no mutual TLS, no
per-request HMAC signature, and no token rotation protocol. Treat the
HTTP transport as suitable for trusted local networks only.

### 6. Playbook path validation is prefix-based

The MCP playbook path check rejects a fixed list of system prefixes
(`/etc`, `/root`, `/var`, `/proc`, `/sys`, `/dev`). It does **not**
implement a chroot-style allow-list of the user's playbook directory. A
path like `/home/otheruser/secret.yaml` would pass the check today. Bind
the MCP server's working directory to a jail / container if you need a
harder guarantee.

## Acknowledgments

We thank those who report vulnerabilities responsibly. List of reports in
[SECURITY_CREDITS.md](SECURITY_CREDITS.md).
