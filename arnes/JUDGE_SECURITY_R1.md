# ARNES Security Judge Report — JUDGE-SEC-R1

**Auditor:** Senior Security Engineer (independent)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Date:** 2026 audit cycle
**Method:** Static code review of 13 files across tools, middleware, llm, playbooks, mcp, cli, specialists, plus SECURITY.md and CI workflow. Runtime verification of `ipaddress` semantics and `pathlib` join behaviour.

---

## Executive Summary

ARNES shows clear security **ambition** — sandbox flags, SSRF DNS resolution, fingerprint-based HITL, hierarchical budgets — but a large fraction of the advertised defenses are either **not wired into the default execution path** or are **implemented in a way that does not deliver the property claimed in `SECURITY.md`**. The most damaging gap is the mismatch between documentation and reality: `SECURITY.md` claims "TOCTOU-resistant" SSRF validation, "pause + HITL at 95% budget", and a "Tier 1 dev-local default" sandbox, none of which are true in the code as shipped.

For a project that explicitly intends to compete with Microsoft / LangChain, the gap between marketed and actual posture is itself a security risk, because adopters will tune their threat models to the marketing.

---

## Scores per Dimension

| #  | Dimension                 | Score | Weight | Weighted |
|----|---------------------------|------:|-------:|---------:|
| 1  | Input validation          | 68    | 10%    | 6.8      |
| 2  | Secret handling           | 72    | 10%    | 7.2      |
| 3  | Sandbox isolation         | 42    | 15%    | 6.3      |
| 4  | SSRF protection           | 68    | 10%    | 6.8      |
| 5  | Path traversal protection | 72    | 10%    | 7.2      |
| 6  | Budget / DoS protection   | 55    | 10%    | 5.5      |
| 7  | HITL integrity            | 55    | 10%    | 5.5      |
| 8  | MCP server security       | 38    | 10%    | 3.8      |
| 9  | CI/CD security            | 52    | 5%     | 2.6      |
| 10 | Documentation honesty     | 50    | 10%    | 5.0      |
|    | **Overall**               |       |        | **56.7 → 57** |

**Overall security score: 57 / 100**

---

## Dimension-by-Dimension Findings

### 1. Input validation — 68/100

**Strengths**
- Every tool declares a pydantic `Args` model and validates before execution (`builtin.py:64`, `:223`, `:276`, `:321`, `:370`).
- HTTP method constrained by regex `^(GET|POST|PUT|DELETE|PATCH|HEAD)$` (`builtin.py:215`).
- `max_bytes` on `fs_read` bounded to ≤1 MiB (`builtin.py:272`); HTTP body truncated to 10 000 chars (`builtin.py:250`).
- Shell `timeout_s` bounded to 1–300 s (`builtin.py:58`).

**Weaknesses**
- Shell command "dangerous pattern" detection (`builtin.py:404–421`) is a regex **blocklist**, trivially bypassed: `rm -rf ~`, `find / -delete`, `python -c 'import os; os.system("...")'`, base64-encoded payloads, `eval()`, etc. The docstring honestly admits "Not exhaustive — combine with sandbox", but the sandbox is not enabled by default (see #3).
- YAML playbooks are loaded by `PlaybookCompiler.from_file` — not audited here in depth, but no schema-strict mode or `yaml.SafeLoader` enforcement was visible at the call sites. Untrusted playbooks remain a risk.
- `cwd` argument to `ShellTool.Args` is a free-form string with no path validation (`builtin.py:57`) — an LLM can set `cwd="/etc"` and run commands there.
- Human-approval `question` field is unbounded (`builtin.py:363`) — prompt-injection vector via the approval UI itself.

### 2. Secret handling — 72/100

**Strengths**
- `_looks_like_secret` heuristic filters `API_KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `PASSWD`, `CREDENTIAL`, `PRIVATE_KEY` from env vars passed to subprocess (`builtin.py:424–435`).
- Dangerous env vars `PATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `PYTHONPATH` are explicitly dropped (`builtin.py:100`, `:158`).
- `LiteLLMProvider` reads keys from environment via litellm and never logs them (`litellm_provider.py:38–39`).
- Cost-guard log line (`cost_guard.py:243–251`) logs only `model`, `cost_usd`, `tokens_in/out` — no prompt content, no keys.

**Weaknesses**
- `secret_broker` is referenced in `ToolContext` (`base.py:152`) and conditionally invoked in `HttpTool` (`builtin.py:234–235`), but **no concrete `SecretBroker` implementation exists** in the audited tree. The SECURITY.md claim "API keys never enter the LLM context window… injected just-in-time" is aspirational, not implemented for any provider except via env-var inheritance into litellm.
- `LLMResponse.raw` stores the full provider response (`litellm_provider.py:117`, `ollama_provider.py:75`). If a provider echoes headers or auth material, it lands in `raw` and may be serialized into the bitácora via `thread.to_markdown()`.
- `_format_input` (`specialists/base.py:381–387`) dumps the entire `input_data` (which may contain secrets passed as playbook variables) as JSON into the user message — secrets passed as playbook inputs **do** enter the LLM context.
- `OllamaProvider` falls back to a hardcoded list of model names when `/api/tags` fails (`ollama.py:87`) — minor, but a tampered endpoint could redirect.

### 3. Sandbox isolation — 42/100  *(critical dimension)*

**Strengths**
- Docker hardening flags are correct in spirit: `--security-opt=no-new-privileges`, `--cap-drop=ALL`, `--network=none`, `--read-only`, `--tmpfs /workspace` (`builtin.py:142–154`).
- Double-gate for local execution: `ARNES_DEV_MODE=1` **and** `ctx.sandbox_enabled=False` (`builtin.py:76–87`).
- `requires_approval=True` on `shell` and `fs_write`.

**Weaknesses — Critical**
- `PlaybookExecutor._execute_specialist` hardcodes `sandbox_enabled=False, # Disabled for MVP; enable in v0.2` (`executor.py:334`). The Docker branch (`_execute_in_sandbox`) is **dead code on the default execution path**. Every shell call from a specialist lands on `_execute_local` → `asyncio.create_subprocess_shell(shell=True)` on the host, gated only by `ARNES_DEV_MODE`.
- `ARNES_DEV_MODE=1` is a single env var with no TTY challenge, no per-invocation confirmation, no audit emit. A user who exports it once in `.envrc` / `.bashrc` permanently disables the only RCE gate. The README and CLI effectively tell users to set it.
- When dev mode is on, the only command defense is the bypassable regex blocklist (#1). There is **no seccomp profile, no user-namespace remap, no rlimit, no CPU/memory cap, no syscall filtering** — the Docker flags listed in `SECURITY.md` are never applied because the Docker branch is never reached.
- `fs_write` executes on the host filesystem (not in a sandbox) with only path-validation as defense; combined with the dangling-symlink gap (#5) this is a local write-anywhere primitive when dev mode is on.
- No timeout on the whole specialist run; only per-shell-call timeouts. A long-running playbook can hold subprocesses indefinitely.

### 4. SSRF protection — 68/100

**Strengths**
- `_check_ssrf_async` resolves DNS via `socket.getaddrinfo` and validates **every** returned address (`builtin.py:503–513`).
- IP block covers `is_private`, `is_loopback`, `is_link_local`, `is_multicast`, `is_reserved`, `is_unspecified` (`builtin.py:520–531`).
- Cloud-metadata IPs and hostnames blocked explicitly (`builtin.py:457–470`).
- Scheme allowlist: `http`, `https` only (`builtin.py:484`).
- Verified at runtime: `::ffff:127.0.0.1` is correctly classified as `is_loopback=True` / `is_private=True` by Python's `ipaddress` — the IPv4-mapped IPv6 bypass I initially suspected does **not** exist. Credit where due.

**Weaknesses**
- **DNS rebinding TOCTOU is real and the documentation lies about it.** `builtin.py:8` and `:204` claim "Prevents DNS rebinding via TOCTOU-resistant validation". The implementation resolves DNS once for validation, then `httpx.AsyncClient().request(url)` resolves DNS **again** for the actual request (`builtin.py:238–244`). An attacker controlling the DNS server can return a safe IP during `_check_ssrf_async` and `127.0.0.1` (or `169.254.169.254`) during the httpx request. The fix is to pin the resolved IP and pass it to httpx via a custom transport / `extensions={"target": ip}` — not done here.
- A **sync fallback** `_check_ssrf` (`builtin.py:535–562`) is kept "for backwards compat / tests" and does **no DNS resolution** — it only blocks literal IP hostnames. Any code path that calls the sync version is SSRF-trivial.
- `follow_redirects` is not explicitly set to `False` on the httpx client (`builtin.py:238`). httpx defaults to `False`, so this is currently safe, but there is no enforced invariant; a future change enabling redirects would inherit no SSRF check on the redirect target.
- No port allowlist — an attacker can reach `http://internal-service:8080` if it resolves to a non-private IP via DNS but is actually NAT'd internally. Edge case, but worth noting for cloud deployments.

### 5. Path traversal protection — 72/100

**Strengths**
- `_validate_path` (`builtin.py:438–453`) uses `Path.resolve(strict=False)` then `target.relative_to(base)` — runtime-verified to correctly reject absolute paths (`base / "/etc/passwd"` → `/etc/passwd`, `relative_to` raises).
- `..` traversal is canonicalized away by `resolve()`.
- Symlink check on `fs_read` (`builtin.py:285–289`) rejects symlinks whose `resolve()`d target escapes `working_dir`, including dangling symlinks (verified by reading `is_symlink()` semantics).
- Symlink check on `fs_write` (`builtin.py:330–334`) catches existing symlinks.

**Weaknesses**
- **Dangling-symlink write gap in `fs_write`**: the check is gated by `safe_path.exists() and safe_path.is_symlink()` (`builtin.py:330`). A dangling symlink (symlink exists, target does not) has `exists() == False`, so the check is skipped. `safe_path.open("w")` then **follows the symlink and creates the target file** at the escaped location. Exploitation requires an attacker-controlled symlink inside `working_dir`, but in dev mode (no sandbox) an LLM can `shell`-create such a symlink in one call and `fs_write` through it in the next.
- TOCTOU between the symlink check and `open()` — not mitigated by `O_NOFOLLOW` or `os.open(path, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW)`.
- MCP server `blocked_prefixes = ["/etc", "/root", "/var", "/proc", "/sys", "/dev"]` (`mcp/server.py:187`) is a **denylist**, not an allowlist. Paths under `/home`, `/tmp`, `/opt`, `/srv`, `/mnt`, `/media` are all accepted. An MCP client can run `manuales/../../home/user/.ssh/evil.yaml` (resolved, not relative-to-blocked-prefixes) — actually the check is on the resolved path string prefix, so `/home/user/secrets.yaml` passes. There is no `working_dir` confinement for MCP `arnes_run_playbook`.
- `arnes_validate_playbook` and `arnes_list_playbooks` have **no path validation at all** (`mcp/server.py:241–275`) — they are file-existence / directory-listing oracles available to any MCP client.

### 6. Budget / DoS protection — 55/100

**Strengths**
- Hierarchical `CostBudget` (org → project → agent → task) with inheritance (`cost_guard.py:46–79`).
- Temporal circuit breaker: `max_usd_per_minute` over a 60 s sliding window (`cost_guard.py:255–263`).
- Pre-flight check via `_peek_cost` (`cost_guard.py:170–195`) — good design.
- Pre-flight abort, hard-stop abort, and structured `BudgetExceeded` exception with `level` field.
- Zero-budget / negative-budget edge case handled (`cost_guard.py:145–149`).

**Weaknesses**
- **`_peek_cost` is dead code in production.** The base `LLMProvider.peek_cost` returns `None` (`llm/base.py:107`). Neither `OllamaProvider` nor `LiteLLMProvider` overrides it. The only override is in `tests/stress/test_budget_edge_cases.py`. So the entire "pre-flight abort" path never fires for real providers — the guard only learns the cost **after** the call returns, allowing overshoot equal to one (potentially very expensive) call.
- **The 95% pause is not implemented.** `cost_guard.py:197–208` reaches the pause threshold, logs a warning, and continues. The comment admits: `# TODO v0.2: emit HumanApprovalRequestedEvent and block`. `self._paused` is **never set to `True`** anywhere except by external code that does not exist; the `if self._paused:` branch (`cost_guard.py:128–137`) is unreachable. `SECURITY.md` line 84 ("At 95%, ARNES pauses and requests human approval") is **false**.
- Circuit breaker is **post-call only** — a single $5 call (long context + Claude Opus output) trips nothing because it's only one entry in the deque, and the abort fires on the *next* call. By then the money is spent.
- `max_usd_per_minute` default of $1.00/min is generous — a runaway loop can spend $60/hour before tripping.
- No integration with the OS-level resource limits (CPU, RSS, wall-clock) — only USD is bounded. A malicious LLM can spin infinite `asyncio` tasks or fork-bomb within the per-call shell timeout.
- `cost_guard.reset()` clears `_aborted` and `_paused` — if a caller naively resets between specialists in the same run, the budget effectively resets too.

### 7. HITL integrity — 55/100

**Strengths**
- `Tool.fingerprint` (`base.py:106–114`) uses SHA-256 of canonical JSON (`sort_keys=True`, `ensure_ascii=False`). 16-hex-char (64-bit) truncation is collision-safe for practical scale.
- `requires_approval` ClassVar on `shell` and `fs_write`.
- Auto-reject in non-interactive mode (`specialists/base.py:237–244`) — fail-safe.
- `Confirm.ask(..., default=False)` (`specialists/base.py:291`) — fail-safe default.
- Human-approval flow shows args + fingerprint to the operator.

**Weaknesses — Critical**
- **Rug-pull defense is broken on the default execution path.** `specialists/base.py:228`:
  ```python
  approved_fingerprints = ctx.metadata.get("_approved_fingerprints", {})
  ```
  This returns a **fresh dict** when the key is absent (which is always — `PlaybookExecutor` and the CLI initialise `metadata={"interactive": ...}` without `_approved_fingerprints`). The subsequent `approved_fingerprints[fingerprint] = tool_name` (`specialists/base.py:257`) mutates a throwaway local. The next tool call sees an empty dict again. **Approved fingerprints are never persisted**, so:
  - The "pre-approved: execute" branch (`specialists/base.py:230–236`) is dead code.
  - Rug-pull detection across tool calls does not function — every call re-prompts (annoying) and there is no record to compare against (insecure).
  - Fix: `approved_fingerprints = ctx.metadata.setdefault("_approved_fingerprints", {})`.
- The fingerprint hash uses `default=str` (`base.py:113`), which silently coerces non-JSON-serialisable values (e.g. `datetime`, custom objects) to `str`. Two distinct args that `str()` to the same representation collide. Low probability, but undermines the "cryptographic" framing.
- `human_approval` tool's `ttl_s` field (`builtin.py:366`) is accepted, validated, and then **never enforced** — no expiry check anywhere.
- The approval UI (`specialists/base.py:287–291`) prints args including potential secrets embedded in tool args (e.g. `fs_write` content). No redaction.
- No approval token / signed approval — an attacker who can write to `ctx.metadata` (e.g. via a malicious tool) can pre-populate `_approved_fingerprints`.

### 8. MCP server security — 38/100  *(critical dimension)*

**Strengths**
- Stdio transport is inherently local (only the parent process's stdin).
- HTTP transport defaults to `127.0.0.1` (`mcp/server.py:308`, `cli/main.py:187`).
- `arnes_run_playbook` has *some* path validation (denylist of system dirs).

**Weaknesses — Critical**
- **No authentication on the HTTP transport.** `serve_http` (`mcp/server.py:308–334`) binds a port and accepts any POST. If a user changes `--host` to `0.0.0.0` (a reasonable thing for remote MCP), any network peer can execute playbooks, list specialists, and validate arbitrary YAML paths. There is no token, no mTLS, no HMAC.
- **No CSRF protection.** A malicious webpage visited by the operator can `fetch('http://127.0.0.1:8765/mcp', {method:'POST', ...})` and trigger playbook execution (the browser will block the *response*, but the request still fires). No `Origin`/`Host` check, no CSRF token.
- **No rate limiting.** A single client can submit thousands of `arnes_run_playbook` requests, each of which spawns a `PlaybookExecutor` and a real LLM call — trivial denial-of-wallet against the operator's API keys.
- **No request size limit.** `await request.json()` (`mcp/server.py:318`) will buffer an arbitrarily large body — OOM vector.
- **Path validation is a denylist, not an allowlist** (`mcp/server.py:187`) — see #5. `arnes_validate_playbook` and `arnes_list_playbooks` have **no** path validation at all — they are file-existence / directory-enumeration oracles.
- JSON-RPC `id` is echoed back without type validation (`mcp/server.py:108`) — minor, but enables certain request-smuggling probes.
- No audit log of incoming MCP requests.
- `serve_http` swallows all exceptions into a 500 with `str(e)` (`mcp/server.py:321–322`) — information disclosure.
- The class-level monkey-patch at the bottom of `mcp/server.py:337–349` is a code smell that makes the security surface hard to audit.

### 9. CI/CD security — 52/100

**Strengths**
- `permissions: contents: read` at the workflow level (`.github/workflows/ci.yml:9–10`) — minimal default.
- Dedicated `security` job runs `bandit` and `pip-audit`.
- `build` job is gated on `test` and `security`.
- Multi-OS, multi-Python matrix.

**Weaknesses**
- **Security scans are non-blocking.** `pip-audit ... || true` (`.github/workflows/ci.yml:79`) and `echo "pip-audit completed (non-blocking...)"`. `mypy ... || true` (line 47). `fail_ci_if_error: false` on codecov (line 57). A failing security scan does not stop the build.
- **A specific vulnerability is ignored:** `--ignore-vuln PYSEC-2026-1845` (line 79) with no comment explaining what it is, why it's ignored, or when it will be revis. This is a security smell.
- **Actions are not pinned to SHAs.** `actions/checkout@v4`, `astral-sh/setup-uv@v3`, `codecov/codecov-action@v4`, `actions/upload-artifact@v4` are all major-version floating tags. A compromise of any of these repos (cf. the 2024 `tj-actions/changed-files` incident) would inject malicious code into every CI run with access to repository secrets.
- No `id-token: write` permission → no OIDC-based publishing, no keyless signing.
- No SBOM generation (CycloneDX / SPDX), no artifact signing (sigstore), no provenance attestation (SLSA).
- No secret scanning, no CodeQL, no dependency-review action on PRs.
- `bandit` runs with `-c pyproject.toml` but the config is not shown — may suppress findings.
- No fuzzing job for the YAML parser or the JSON-RPC handler.
- The `build` job uploads `dist/` as an artifact but does not publish to PyPI in CI — so release is manual, outside CI's controls.

### 10. Documentation honesty — 50/100

**Strengths**
- `SECURITY.md:64–66` honestly admits "In v0.1 alpha, the sandbox is not yet wired up by default."
- `README.md:377` repeats the dev-mode caveat.
- `CHANGELOG.md:62` acknowledges the sandbox is not wired up.
- The reporting process (private GitHub advisory, 72h acknowledgement, 30-day fix SLA) is reasonable.

**Weaknesses — the documentation makes at least three materially false security claims**
1. **"TOCTOU-resistant validation"** (`builtin.py:8`, `:204`, `SECURITY.md:79`): false. DNS is resolved twice (once in `_check_ssrf_async`, once in httpx). DNS rebinding works. See #4.
2. **"At 95%, ARNES pauses and requests human approval"** (`SECURITY.md:84`): false. The code logs a warning and continues; the `_paused` flag is never set; the `if self._paused:` branch is dead. See #6.
3. **"ARNES executes code tools in hardened Docker containers"** (`SECURITY.md:54`): misleading. The Docker branch exists in `ShellTool._execute_in_sandbox` but is unreachable on the default execution path because `PlaybookExecutor` hardcodes `sandbox_enabled=False`. The Docker flags are correct *in vitro* but never applied *in vivo*. See #3.

Additional misleading claims:
- "API keys never enter the LLM context window… injected just-in-time" (`SECURITY.md:71–72`) — the `SecretBroker` is referenced but not implemented; `_format_input` dumps playbook variables (which may contain secrets) into the user message. See #2.
- "Every LLM call, every tool execution, every CostGuard decision is logged to the markdown bitácora" (`SECURITY.md:90`) — CostGuard decisions are logged via structlog, not necessarily to the bitácora (which is `Thread.to_markdown()`); the mapping is not verified.
- `COMPETITIVE_AUDIT.md:50` lists "Docker Tier 1 — wiring pending" which is honest, but `README.md:164`'s "⚠️ v0.1 (wiring pending, requires ARNES_DEV_MODE=1)" understates the risk: it implies the sandbox exists but needs wiring, when in fact the entire default path bypasses it.

For a project whose differentiator is "honesty about hallucinations" (the verification layer), the security docs are themselves hallucinating capabilities.

---

## Top 5 Critical Security Issues

1. **Sandbox is not wired into the default execution path.** `PlaybookExecutor._execute_specialist` hardcodes `sandbox_enabled=False` (`executor.py:334`). The hardened Docker branch in `ShellTool._execute_in_sandbox` is dead code. Any user who sets `ARNES_DEV_MODE=1` (which the README and CLI actively encourage) grants the LLM unsandboxed `asyncio.create_subprocess_shell(shell=True)` on the host, defended only by a regex blocklist trivially bypassed by `python -c`, `find / -delete`, `eval`, base64, etc. **Severity: Critical (RCE).**

2. **HITL rug-pull defense is broken in the default path.** `specialists/base.py:228` uses `ctx.metadata.get("_approved_fingerprints", {})`, which returns a throwaway dict on every call (the key is never initialised). Approved fingerprints are never persisted, so the "pre-approved: execute" branch is dead and there is no record to detect a rug-pull against. The fix is one line: `setdefault` instead of `get`. **Severity: High (HITL bypass).**

3. **MCP HTTP server has no auth, no rate limiting, no CSRF protection.** `serve_http` (`mcp/server.py:308`) accepts any POST. A malicious webpage can CSRF-execute playbooks. A network peer (if `--host 0.0.0.0`) can run arbitrary playbooks and enumerate the filesystem via `arnes_validate_playbook` / `arnes_list_playbooks` (which have no path validation). Combined with #1, this is network-reachable RCE in dev-mode deployments. **Severity: Critical (RCE / DoW).**

4. **DNS rebinding TOCTOU in SSRF protection, despite documentation claiming otherwise.** `_check_ssrf_async` resolves DNS for validation, then `httpx` resolves again for the request (`builtin.py:228` vs `:238`). An attacker-controlled DNS server can return a public IP during validation and `169.254.169.254` (cloud metadata) during the request. `SECURITY.md` and the `HttpTool` docstring both falsely claim "TOCTOU-resistant". **Severity: High (SSRF to cloud metadata → credential theft).**

5. **Budget pause at 95% is not implemented; pre-flight cost check is dead code.** `cost_guard.py:197–208` logs a warning at the pause threshold and continues; `self._paused` is never set. `peek_cost` is never overridden by any production provider, so the pre-flight abort path (`cost_guard.py:170–195`) never fires. A single expensive call can overshoot the budget by orders of magnitude before the post-call check catches it. `SECURITY.md` falsely claims "At 95%, ARNES pauses and requests human approval." **Severity: High (denial-of-wallet).**

---

## Top 5 Improvements Needed

1. **Make the sandbox default-on.** Flip `sandbox_enabled=True` in `PlaybookExecutor._execute_specialist` and `_execute_tool`. Require `ARNES_DEV_MODE=1` to be confirmed via a TTY prompt at startup (not just an env var that can live in `.envrc`). If no container runtime is available, refuse to run `shell`/`fs_write` steps rather than silently falling back to host execution. Long-term, adopt gVisor / Firecracker for stronger isolation than Docker cap-drop.

2. **Fix the HITL fingerprint persistence bug.** Replace `ctx.metadata.get("_approved_fingerprints", {})` with `ctx.metadata.setdefault("_approved_fingerprints", {})` in `specialists/base.py:228`. Add a regression test that calls the same `requires_approval` tool twice with the same args and asserts the second call does not re-prompt. Sign approval tokens with a per-run HMAC so they cannot be forged by a malicious tool writing to `ctx.metadata`.

3. **Pin SSRF validation to the resolved IP.** After `_check_ssrf_async` resolves the hostname to a safe IP, pass that IP to httpx directly (e.g. via a custom `httpx.HTTPTransport` with `extensions={"target": ip_str}`) and set the `Host` header to the original hostname. This eliminates the DNS rebinding TOCTOU. Also: explicitly set `follow_redirects=False` (or re-run `_check_ssrf_async` on each redirect Location), delete the sync `_check_ssrf` fallback, and add a port allowlist (80/443 by default).

4. **Add authentication, rate-limiting, and CSRF protection to the MCP HTTP server.** Require a bearer token (read from env or a config file) on every request. Add a per-IP token-bucket rate limiter (e.g. `aiolimiter`). Check the `Origin` / `Host` header and reject cross-origin POSTs. Cap request body size to e.g. 1 MiB. Convert `arnes_validate_playbook` and `arnes_list_playbooks` to use the same path allowlist as `arnes_run_playbook` (and switch that allowlist from a denylist to a `working_dir`-rooted allowlist). Document that stdio is the only transport recommended for untrusted MCP clients.

5. **Make CI security checks blocking and tighten the supply chain.** Remove `|| true` from `pip-audit` and `mypy`. Either fix or formally accept (with a written justification and an expiry date) `PYSEC-2026-1845`. Pin all `actions/*` and third-party actions to commit SHAs (use `renovate` / `dependabot` to bump). Add `id-token: write` and publish to PyPI via OIDC + sigstore signing. Generate an SBOM (CycloneDX) and upload it as a build artifact. Add a `dependency-review-action` step on PRs. Add CodeQL. Add a fuzzing job for the JSON-RPC handler and the YAML loader.

---

## Verdict

### **NO-GO for public release.**

ARNES v0.1.0a1 is not safe to release as a public alpha, and is not safe to market as a competitor to Microsoft / LangChain in its current form. The combination of:

- An unreachable sandbox on the default path (#1),
- A broken HITL rug-pull defense (#2),
- An unauthenticated MCP HTTP server (#3),
- A falsely-claimed TOCTOU-resistant SSRF check (#4), and
- A falsely-claimed budget pause (#5),

…means that an adopter who reads `SECURITY.md` and tunes their threat model to it will be **materially misled** about the framework's posture. For a project whose entire value proposition is "honest agents that don't hallucinate", security-marketing hallucinations are an existential trust problem, not just a bug.

**Conditions for re-audit (GO criteria):**
1. `sandbox_enabled=True` by default in `PlaybookExecutor`, with `ARNES_DEV_MODE=1` requiring a TTY confirmation.
2. HITL fingerprint persistence fixed (`setdefault`) with a regression test.
3. MCP HTTP server requires a bearer token, rate-limits, and validates `Origin`.
4. SSRF check pins the resolved IP into the httpx request; sync `_check_ssrf` deleted.
5. Either implement the 95% pause (emit `HumanApprovalRequestedEvent` and block) or delete the claim from `SECURITY.md`.
6. At least one production provider (`LiteLLMProvider`) overrides `peek_cost` using a local tokenizer, or the pre-flight check is removed and the post-call overshoot is documented.
7. `SECURITY.md` rewritten to describe the code as shipped, not the code aspired to.
8. CI security scans are blocking; actions pinned to SHAs; `PYSEC-2026-1845` resolved or justified.

Re-audit after these are remediated. Expected score post-remediation: **78–85**.

---

*End of report. — JUDGE-SEC-R1*
