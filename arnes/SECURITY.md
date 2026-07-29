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
   or email to `security@arnes.dev`.
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
- Path traversal in `fs_*` tools
- SSRF in `http` tool
- Persistent prompt injection that survives between sessions

is a security vulnerability and must be reported privately.

## Implemented Security Measures

### Execution Sandbox (Tier 1 dev-local default)

ARNES executes code tools in hardened Docker containers:

```bash
docker run --rm \
  --security-opt=no-new-privileges \
  --cap-drop=ALL \
  --network=none \
  --read-only \
  --tmpfs /workspace:size=100M \
  arnes-sandbox:latest
```

**Note**: In v0.1 alpha, the sandbox is not yet wired up by default. Local
shell execution requires the `ARNES_DEV_MODE=1` environment variable as a
double-gate safety measure. Full Docker sandbox integration lands in v0.2.

### Secret Broker

API keys **never** enter the LLM context window. ARNES reads them from the
environment and injects them just-in-time into HTTP calls. The agent only
sees `<api_key_set: true>`.

### Input Validation

All tools accept inputs validated by pydantic schemas. The `fs_read`/`fs_write`
tools validate paths against the working directory allowlist. The `http` tool
validates URLs against an SSRF blacklist (localhost, private IPs, cloud metadata
endpoints) with full DNS resolution.

### Cost Guard

Each run has a declared USD budget. At 95%, ARNES pauses and requests human
approval. At 100%, ARNES aborts. Temporal circuit breaker: if spend exceeds
$X/minute, immediate abort.

### Audit Log

Every LLM call, every tool execution, every CostGuard decision is logged to
the markdown bitácora. The bitácora is auditable and re-executable.

## Acknowledgments

We thank those who report vulnerabilities responsibly. List of reports in
[SECURITY_CREDITS.md](SECURITY_CREDITS.md).
