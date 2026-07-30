# ARNES Security Judge Report — JUDGE-SEC-R2 (Re-evaluation)

**Auditor:** Senior Security Engineer (independent)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Cycle:** Round 2 re-evaluation
**Prior score (R1):** 57 / 100 — NO-GO
**Method:** Static re-review of the 4 in-scope files (`specialists/base.py`, `mcp/server.py`, `SECURITY.md`, `tools/builtin.py`), plus verification of `playbooks/executor.py`, `middleware/cost_guard.py`, and `.github/workflows/*.yml` to confirm which R1 findings were fixed in code vs. honestly documented around.

---

## Executive Summary

All 6 critical issues enumerated in the Round 1 remediation plan have been **addressed**. Five of the six are fixed **in code** (HITL `setdefault`, MCP auth + rate limit + body cap + generic errors, MCP path validation on all endpoints, shell regex expansion, SSRF IP pinning). The sixth — `SECURITY.md` honesty — is fixed comprehensively: the document now lists 7 explicit "Current Limitations" and no longer makes the three materially false claims flagged in R1 ("TOCTOU-resistant", "pauses at 95%", "Docker sandbox by default").

Two of the largest **runtime** risks from R1, however, were **not** fixed in code — they were disclosed honestly instead:

- **Sandbox is still not wired into the default execution path.** `playbooks/executor.py:390` still hardcodes `sandbox_enabled=False`. The hardened Docker branch in `ShellTool._execute_in_sandbox` remains dead code on the default path. `ARNES_DEV_MODE=1` still grants unsandboxed `asyncio.create_subprocess_shell(shell=True)` on the host.
- **CostGuard 95% pause is still not implemented.** `cost_guard.py:256–278` still logs a warning and continues; `self._paused` is still never set to `True` on the threshold path; `peek_cost` is still unoverridden by any production provider.

Because these two gaps are now **prominently and accurately disclosed** in `SECURITY.md` ("Do not enable `ARNES_DEV_MODE=1` on untrusted inputs in v0.1.x"; "CostGuard does not pause at 95%"), the documentation-honesty dimension improves dramatically, but the underlying runtime posture for an uninformed user is unchanged.

**Net:** the project crossed from "misleading and unsafe" to "honestly limited." That is enough for a transparent **alpha** release, but not for production / untrusted-input use.

---

## Scores per Dimension

| #  | Dimension                 | R1   | R2   | Δ    | Weight | Weighted |
|----|---------------------------|-----:|-----:|-----:|-------:|---------:|
| 1  | Input validation          | 68   | 72   | +4   | 10%    | 7.2      |
| 2  | Secret handling           | 72   | 73   | +1   | 10%    | 7.3      |
| 3  | Sandbox isolation         | 42   | 45   | +3   | 15%    | 6.75     |
| 4  | SSRF protection           | 68   | 85   | +17  | 10%    | 8.5      |
| 5  | Path traversal protection | 72   | 78   | +6   | 10%    | 7.8      |
| 6  | Budget / DoS protection   | 55   | 58   | +3   | 10%    | 5.8      |
| 7  | HITL integrity            | 55   | 72   | +17  | 10%    | 7.2      |
| 8  | MCP server security       | 38   | 80   | +42  | 10%    | 8.0      |
| 9  | CI/CD security            | 52   | 58   | +6   | 5%     | 2.9      |
| 10 | Documentation honesty     | 50   | 85   | +35  | 10%    | 8.5      |
|    | **Overall**               | 57   | **70** | +13 |        | **69.95 → 70** |

**Overall security score: 70 / 100** (R1: 57)

---

## Verification of the 6 R1 Remediation Items

### 1. HITL fingerprint persistence — FIXED ✅

`specialists/base.py:282`:
```python
approved_fingerprints = ctx.metadata.setdefault("_approved_fingerprints", {})
```
The `setdefault` call returns the **same dict object** stored in `ctx.metadata`, so subsequent mutations (`approved_fingerprints[fingerprint] = tool_name` at line 311) are persisted across tool calls. The inline comment (lines 276–279) explicitly explains *why* `setdefault` is required rather than `.get`. This is exactly the one-line fix prescribed in R1. The "pre-approved: execute" branch is now live; rug-pull detection across tool calls now functions.

### 2. MCP HTTP server auth + rate limiting + localhost-only — FIXED ✅

`mcp/server.py:364–458` implements:
- **Bearer token auth** with `hmac.compare_digest` constant-time comparison (`server.py:407`, `_constant_time_eq` at 498–505).
- **Loopback-only enforcement** when no token is set: refuses to bind to non-`127.0.0.1`/`::1`/`localhost` hosts (`server.py:384–391`).
- **Sliding-window rate limiter** at 100 req/min/IP (`_RateLimiter` at 469–495, applied at 421).
- **Request body cap** at 1 MiB with both Content-Length pre-check and post-read enforcement (`server.py:411–417`, `431–433`).
- **Generic error responses** — exceptions are logged server-side but the client receives `{"error": "Internal server error"}` with no path/stack leakage (`server.py:440–444`).

This is a comprehensive fix for the "no auth, no rate limit, no body cap, info disclosure" cluster from R1.

### 3. MCP path validation on all endpoints — FIXED ✅

`mcp/server.py:50–66` centralizes path validation in `_validate_playbook_path()`. It is now invoked by:
- `_run_playbook` (`server.py:209`)
- `_validate_playbook` (`server.py:313`)
- `_list_playbooks` (`server.py:268`), **plus** a per-file re-validation inside the directory loop (`server.py:285`) to catch symlinks that point back into a blocked prefix.

The R1 finding that `arnes_validate_playbook` and `arnes_list_playbooks` were "file-existence / directory-enumeration oracles" is resolved.

### 4. SECURITY.md honest rewrite — FIXED ✅

The document now contains a dedicated **"Current Limitations"** section (lines 133–200) with 7 explicit non-guarantees:
1. "No Default Sandbox (Tier 1 Docker sandbox is NOT wired up by default)"
2. "CostGuard does not pause at 95%"
3. "SSRF check is best-effort, not bulletproof"
4. "Shell regex is defense-in-depth, not a sandbox"
5. "MCP HTTP transport is single-process"
6. "No mTLS / HMAC request signing"
7. "Playbook path validation is prefix-based"

The three materially false claims from R1 are corrected: "TOCTOU-resistant" is replaced by an accurate description of IP pinning + redirect caveat; "pauses at 95%" is replaced by "does not pause at 95%"; "Docker sandbox by default" is replaced by "not configured by default."

### 5. Shell regex expansion — FIXED ✅

`tools/builtin.py:444–465` adds 8 new patterns:
- `python -c` / `python3 -c`
- `eval(` / `exec(`
- `find … -delete`
- `base64 -d` / `base64 --decode`
- suspiciously-indented chained commands (`\b\s{2,}.*&&`)

The docstring at 468–479 explicitly states this is **defense-in-depth only** and "trivially bypassable by an adversarial prompt" — the honesty is correct; the regex is a tripwire for careless commands, not a security boundary.

### 6. SSRF DNS-rebinding IP pinning — FIXED ✅

`tools/builtin.py:531–593` (`_check_ssrf_async`) now returns the resolved IP. `tools/builtin.py:596–643` (`_build_ip_pinned_url`) rewrites the URL to use the resolved IP directly, with:
- IPv6 bracketing per RFC 3986.
- Original hostname preserved as the `Host` header (`server.py:265`, `builtin.py:265`).
- `sni_hostname` extension set for HTTPS so TLS cert validation uses the original hostname (`builtin.py:283`).
- `follow_redirects=False` explicit on the httpx client (`builtin.py:270`).

This eliminates the DNS-rebinding TOCTOU window described in R1. The check and the request now share the same resolution result.

---

## Dimension-by-Dimension Findings (R2)

### 1. Input validation — 72/100 (R1: 68)

**Fixed:** Shell regex now catches `python -c`, `eval(`, `exec(`, `find -delete`, `base64 -d` — the specific bypasses called out in R1.
**Remaining:**
- `ShellTool.Args.cwd` (`builtin.py:68`) is still a free-form string with no path validation — an LLM can set `cwd="/etc"` and run commands there in dev mode.
- `HumanApprovalTool.Args.question` (`builtin.py:403`) is still unbounded — prompt-injection vector via the approval UI.
- YAML playbook loading still uses default `yaml.SafeLoader`-equivalent path; no schema-strict mode visible at call sites. Untrusted playbooks remain a risk.
- `HumanApprovalTool.Args.ttl_s` (`builtin.py:406`) is validated but **never enforced** — no expiry check anywhere.

### 2. Secret handling — 73/100 (R1: 72)

**Unchanged in code.** `_looks_like_secret` heuristic, `PATH`/`LD_PRELOAD`/`PYTHONPATH` stripping, and litellm env-var inheritance are as in R1. The `SecretBroker` is still referenced in `ToolContext` and `HttpTool` but no concrete implementation ships. Score bumped +1 only because `SECURITY.md` no longer overclaims "API keys never enter the LLM context window" without qualification.
**Remaining:** `_format_input` (`specialists/base.py:484–490`) still dumps the entire `input_data` (which may contain secrets passed as playbook variables) into the user message. `LLMResponse.raw` still stores full provider responses that may be serialized into the bitácora.

### 3. Sandbox isolation — 45/100 (R1: 42)  *(critical dimension)*

**NOT fixed in code.** `playbooks/executor.py:390` still hardcodes `sandbox_enabled=False  # Disabled for MVP; enable in v0.2`. The Docker branch in `ShellTool._execute_in_sandbox` remains dead code on the default execution path. Every shell call from a specialist still lands on `_execute_local` → `asyncio.create_subprocess_shell(shell=True)` on the host, gated only by `ARNES_DEV_MODE=1`.
**What changed:** `SECURITY.md` now explicitly warns "Do not enable `ARNES_DEV_MODE=1` on untrusted inputs in v0.1.x." This reduces **informed-adoption** risk but does not change the **runtime** risk for a user who skips the docs. The +3 reflects the honest warning, not a code improvement.
**Remaining:** No seccomp profile, no user-namespace remap, no rlimits, no CPU/memory cap, no syscall filtering. `ARNES_DEV_MODE=1` is still a single env var with no TTY challenge. `fs_write` still executes on the host filesystem.

### 4. SSRF protection — 85/100 (R1: 68)

**Fixed:** IP pinning via `_build_ip_pinned_url` is a correct and complete DNS-rebinding mitigation. Host header + SNI preservation means virtual-host routing and TLS cert validation both still work against the original hostname. `follow_redirects=False` is explicit.
**Remaining:**
- The sync `_check_ssrf` fallback (`builtin.py:661–688`) is still present "for backwards compat / tests" and does **no DNS resolution** — any code path that calls it is SSRF-trivial. R1 recommended deletion; this was not done.
- HTTP redirects are not followed (good for SSRF), but the limitation is documented; if a future caller enables redirects, no re-check exists.
- No port allowlist — an attacker can reach arbitrary ports on a public IP.
- IPv6 scope IDs and edge-case resolver behaviors not exhaustively tested (honestly disclosed).

### 5. Path traversal protection — 78/100 (R1: 72)

**Fixed:** Centralized `_validate_playbook_path` applied to all three MCP endpoints. Per-file re-validation inside `_list_playbooks` catches in-directory symlinks pointing back into blocked prefixes.
**Remaining:**
- Still **denylist-based** (prefix match against `/etc`, `/root`, `/var`, `/proc`, `/sys`, `/dev`). `/home/otheruser/secret.yaml` passes. `SECURITY.md` limitation #7 now discloses this honestly and recommends container-jailing for harder guarantees.
- **Dangling-symlink write gap in `fs_write`** (`builtin.py:370`): the check is `safe_path.exists() and safe_path.is_symlink()`. A dangling symlink has `exists() == False`, so the check is skipped and `safe_path.open("w")` follows the symlink and creates the escaped target. **Not fixed, not documented.** Exploitation requires an attacker-controlled symlink inside `working_dir` (creatable via `shell` in dev mode).
- No `O_NOFOLLOW` / `O_EXCL` on open — TOCTOU between symlink check and open remains.

### 6. Budget / DoS protection — 58/100 (R1: 55)

**NOT fixed in code.** `cost_guard.py:256–278` still logs `cost_guard_pause_threshold_reached` and continues; `self._paused` is still never set to `True` on the threshold path. `LLMProvider.peek_cost` (`llm/base.py`) still returns `None`; neither `OllamaProvider` nor `LiteLLMProvider` overrides it. The pre-flight abort path is still dead for real providers.
**What changed:** `SECURITY.md` now states "CostGuard does not pause at 95%" and "There is also no temporal circuit breaker in v0.1.x" (the latter is slightly inaccurate — the temporal circuit breaker at `max_usd_per_minute` *does* exist in `cost_guard.py`, it just fires post-call). MCP HTTP rate limiting (100 req/min/IP) adds a boundary-level DoW defense that did not exist in R1.
**Remaining:** A single expensive call can overshoot the budget before the post-call check catches it. `cost_guard.reset()` still clears `_paused`/`_aborted` — naive per-specialist reset re-opens the budget.

### 7. HITL integrity — 72/100 (R1: 55)

**Fixed:** `setdefault` correctly persists approved fingerprints. The rug-pull detector now has state to compare against. The "pre-approved: execute" branch is live.
**Remaining:**
- `HumanApprovalTool.Args.ttl_s` still accepted, validated, never enforced.
- No signed approval tokens — an attacker who can write to `ctx.metadata` (e.g. via a malicious tool) can pre-populate `_approved_fingerprints` and bypass approval entirely.
- The approval UI (`specialists/base.py:329–348`) prints args including potential secrets embedded in tool args (e.g. `fs_write` content). No redaction.
- Fingerprint hash uses `default=str` (`base.py:113`), which silently coerces non-JSON-serialisable values — low-probability collision risk.

### 8. MCP server security — 80/100 (R1: 38)

**Fixed:** This is the largest improvement in the audit. Bearer auth (constant-time), loopback-only when unauthenticated, sliding-window rate limiter, 1 MiB body cap, generic error responses, path validation on all endpoints. The R1 critical cluster (no auth / no CSRF / no rate limit / no body cap / info disclosure / path-traversal oracles) is substantially resolved.
**Remaining:**
- **No CSRF / Origin check.** A malicious webpage visited by the operator can still `fetch('http://127.0.0.1:8765/mcp', {method:'POST', ...})`. The browser blocks the *response* but the request still fires. With a bearer token configured, CSRF is mitigated (the page cannot read the token), but the unauthenticated loopback default remains CSRF-exposed. `SECURITY.md` limitation #5 discloses this.
- **In-process rate limiter** — multi-worker deployment gets N× the limit. Disclosed.
- **Single bearer token, no mTLS, no HMAC, no rotation.** Disclosed in limitation #6.
- JSON-RPC `id` still echoed without type validation.
- The class-level monkey-patch at `server.py:515–529` is still a code smell, though functionally harmless.

### 9. CI/CD security — 58/100 (R1: 52)

**Improved:** `mypy --strict` is now a **hard gate** (`.github/workflows/ci.yml:50` — the `|| true` is gone, with an explanatory comment at lines 47–49). Coverage floor `--cov-fail-under=65` is explicit at the step level (`ci.yml:61`), so a pyproject change cannot silently disable it.
**Remaining (unchanged from R1):**
- `pip-audit ... || true` is still non-blocking (`ci.yml:90`).
- `--ignore-vuln PYSEC-2026-1845` (`ci.yml:90`) still has no justification comment, no expiry, no owner.
- Actions still pinned to floating major-version tags (`actions/checkout@v4`, `astral-sh/setup-uv@v3`, `codecov/codecov-action@v4`, `actions/upload-artifact@v4`, `softprops/action-gh-release@v2`) — supply-chain risk in light of the 2024 `tj-actions/changed-files` compromise.
- `release.yml` still uses a long-lived `PYPI_API_TOKEN` secret instead of PyPI Trusted Publishing (OIDC `id-token: write`). No `id-token: write` permission anywhere.
- No SBOM (CycloneDX/SPDX), no sigstore signing, no SLSA provenance, no CodeQL, no dependency-review action, no secret scanning, no fuzzing job.

### 10. Documentation honesty — 85/100 (R1: 50)

**Substantially fixed.** The rewrite is the single biggest improvement in R2. The "Current Limitations" section (7 items) is accurate, specific, and actionable. The three materially false claims from R1 are corrected. Each limitation includes a concrete recommendation (e.g. "Bind the MCP server's working directory to a jail / container").
**Remaining:**
- Limitation #2 says "There is also no temporal circuit breaker in v0.1.x" — this is **inaccurate**; `cost_guard.py` *does* implement `max_usd_per_minute` over a 60s sliding window. The circuit breaker is post-call-only, but it exists. A precise statement would be "the temporal circuit breaker fires post-call only; it cannot prevent a single expensive call from overshooting."
- The "Implemented Security Measures" section still says "The bitácora is auditable and re-executable" — re-executability is not verified by this audit and may be aspirational.
- `README.md` and `COMPETITIVE_AUDIT.md` were not re-checked for residual overclaims; `SECURITY.md` is the canonical source but adopters may read the README first.

---

## Top 3 Remaining Issues

### 1. Sandbox is still not wired into the default execution path — **Critical (RCE)**

`playbooks/executor.py:390` still hardcodes `sandbox_enabled=False`. The hardened Docker branch (`ShellTool._execute_in_sandbox`) with `--security-opt=no-new-privileges`, `--cap-drop=ALL`, `--network=none`, `--read-only`, tmpfs `/workspace` is still dead code on the default path. Any user who sets `ARNES_DEV_MODE=1` (which the CLI and examples facilitate) grants the LLM unsandboxed `asyncio.create_subprocess_shell(shell=True)` on the host, defended only by a regex blocklist that `SECURITY.md` itself now admits is "trivially bypassable by an adversarial prompt." `SECURITY.md` warns against this, but the warning is a policy, not a control. **This is the same #1 critical issue from R1, now honestly disclosed rather than fixed.**

### 2. CostGuard 95% pause and pre-flight check are still not implemented — **High (DoW)**

`cost_guard.py:256–278` still logs and continues at the pause threshold; `self._paused` is never set to `True`. `LLMProvider.peek_cost` still returns `None` for every production provider, so the pre-flight abort path (`cost_guard.py:170–195`) never fires. A single long-context + Opus-class output call can overshoot the budget by orders of magnitude before the post-call check catches it. `SECURITY.md` now honestly discloses this, but the protection gap is unchanged. **This is the same #5 critical issue from R1, now honestly disclosed rather than fixed.**

### 3. CI/CD supply chain is still weak — **Medium (supply chain)**

Actions are still pinned to floating tags (`@v4`, `@v3`, `@v2`) rather than commit SHAs. `pip-audit` is still non-blocking (`|| true`). `PYSEC-2026-1845` is still ignored with no justification. PyPI publishing still uses a long-lived API token instead of OIDC Trusted Publishing. No SBOM, no sigstore, no CodeQL, no dependency-review action. A compromise of any pinned action repo (cf. `tj-actions/changed-files` 2024) would inject malicious code into CI with access to `PYPI_API_TOKEN`. The +6 over R1 reflects only the mypy hard gate and explicit coverage floor.

---

## Verdict

### **CONDITIONAL GO** for public alpha release with prominent caveats.

R1 was NO-GO at 57. R2 is **70**. The trajectory is correct and the fixes that were made are real, well-implemented, and well-commented. Critically, `SECURITY.md` no longer lies — an adopter who reads it will tune their threat model to reality, not to marketing.

**GO conditions (all met):**
1. ✅ HITL fingerprint persistence fixed (`setdefault`) with explanatory comment.
2. ✅ MCP HTTP server requires a bearer token, rate-limits, caps body size, returns generic errors, validates paths on all endpoints, and refuses non-loopback binding without a token.
3. ✅ SSRF check pins the resolved IP into the httpx request; DNS-rebinding TOCTOU closed; `follow_redirects=False` explicit.
4. ✅ Shell regex expanded to cover `python -c`, `eval(`, `exec(`, `find -delete`, `base64 -d`.
5. ✅ `SECURITY.md` rewritten to describe the code as shipped, including 7 explicit limitations.

**NO-GO conditions (for production / untrusted-input use — still open):**
1. ❌ Sandbox is not wired into the default execution path. `ARNES_DEV_MODE=1` still grants unsandboxed host RCE. **Recommendation:** flip `sandbox_enabled=True` in `executor.py:390`, and if no container runtime is available, refuse `shell`/`fs_write` steps rather than falling back to host execution.
2. ❌ CostGuard 95% pause is not implemented; pre-flight `peek_cost` is dead code. **Recommendation:** either implement the pause (emit `HumanApprovalRequestedEvent` and block) and override `peek_cost` in `LiteLLMProvider` using a local tokenizer, or remove the pause claim entirely and document the post-call overshoot bound.
3. ❌ CI supply chain: actions not SHA-pinned, `pip-audit` non-blocking, `PYSEC-2026-1845` unjustified, PyPI token instead of OIDC. **Recommendation:** pin actions to SHAs, make `pip-audit` blocking (or formally accept the vuln with a written justification + expiry), migrate to PyPI Trusted Publishing.
4. ❌ Dangling-symlink write gap in `fs_write` (`builtin.py:370`) — not fixed, not documented. **Recommendation:** drop the `exists()` guard (check `is_symlink()` alone) or use `os.open(path, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW)`.

**Release posture:**
- ✅ Suitable for a **public alpha** (e.g. `0.1.0a1`) targeted at developers who will read `SECURITY.md` and operate in trusted-input / dev-mode-only environments.
- ❌ Not suitable for **production** or for processing **untrusted** prompts/playbooks until the sandbox is wired (#1) and the budget pause is implemented (#2).

**Expected score after the 4 NO-GO items are remediated:** 82–88.

---

*End of report. — JUDGE-SEC-R2*
