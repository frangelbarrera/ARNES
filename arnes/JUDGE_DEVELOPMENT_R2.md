# JUDGE-DEV-R2 — ARNES Development Quality Re-Evaluation

**Auditor**: Senior Python Engineer (JUDGE)
**Date**: 2026-07-31
**Subject**: ARNES v0.1.0a1 — re-evaluation after Round-1 fixes
**Round 1 score**: 69 / 100 (NO-GO for "world-class" bar; GO as documented alpha)
**Method**: Full source-tree re-read of changed modules, `mypy --strict` run, `ruff check`, `bandit`, `pytest --cov`, targeted reproduction of each Round-1 critical issue (C1–C5) and each claimed fix.

---

## 0. Verification of claimed Round-1 fixes

| # | Claimed fix | Verified? | Evidence |
|---|---|---|---|
| 1 | `mypy --strict` now passes (was 50 errors, now 0) | ✅ **YES** | `uv run mypy arnes/ --strict` → `Success: no issues found in 36 source files` |
| 2 | CI mypy is now blocking (removed `\|\| true`) | ✅ **YES** | `.github/workflows/ci.yml:50` runs `uv run mypy arnes/ --strict` with no `\|\| true`. Inline comment explains the change. |
| 3 | `TokenOptimizer` cache_key now includes `response_schema` | ✅ **YES** | `arnes/middleware/token_optimizer.py:103` calls `self._cache_key(messages, effective_model, tools, response_schema, kwargs)`; `_cache_key` payload (line 230-241) hashes `response_schema` explicitly. Cache-poisoning repro from R1 no longer reproduces. |
| 4 | `aiohttp` added to `mcp` optional deps | ✅ **YES** | `pyproject.toml:66` → `mcp = ["aiohttp>=3.9,<4"]`. The CLI error message in `_serve_mcp` now points at a real extra. |
| 5 | `LiteLLMProvider` kwargs fixed | ⚠️ **PARTIAL** | The `complete()` `kwargs`-redefinition bug (R1-C1) **is** fixed: `litellm_provider.py:80` builds `call_kwargs` instead of reassigning `kwargs`. **BUT** the `__init__(self)` still accepts no kwargs while `factory.py:48` calls `LiteLLMProvider(**kwargs)` → `TypeError` for any user-supplied kwarg. Reproduced: `get_provider("anthropic/claude-...", api_key="sk-test")` → `TypeError: __init__() got an unexpected keyword argument 'api_key'`. R1 dimension #3 listed this as a separate error-handling bug; it remains unfixed. |
| 6 | New tests added for `litellm_provider`, `ollama`, `mcp_server` | ⚠️ **PARTIAL / FALSE for MCP** | `tests/unit/test_fix_ai.py` adds 3 `OllamaProvider` tests (now 67% covered, was 0%) and 3 `LiteLLMProvider.peek_cost` tests (now 34% covered — only `peek_cost`/`__init__`, the `complete()` body that calls `litellm.acompletion` is still 0%). **No tests for `mcp/server.py` exist** — coverage is still 0% on lines 21-529. The MCP JSON-RPC dispatcher (`handle_request`), path-traversal guards, and HTTP bearer-auth/rate-limiter are completely untested. |

**Bonus fixes I observed that weren't claimed:**

- `CostGuard`, `TokenOptimizer`, `VerificationLayer` now inherit from `LLMProvider` (R1-C5 done) — eliminates 9+ `# type: ignore[arg-type]` comments in `agent.py` and `executor.py`.
- `LLMProvider.complete` ABC now declares `response_schema: dict[str, Any] | None = None` (R1 dimension #2 contract gap closed).
- `Specialist.run` now has an explicit `max_iterations`-exceeded branch (R1-C3 done) — `specialists/base.py:219-236` returns `{"success": False, "error": "Specialist exceeded max_iterations (N) without producing a final response"}`. Reproduced: `_AlwaysToolCallProvider` test passes.
- Path-traversal protection extended from `_run_playbook` to `_list_playbooks` and `_validate_playbook` (security hardening).
- HTTP MCP transport gained bearer-token auth, 1 MiB request-size cap, and per-IP sliding-window rate limiter (R1 dimension #8 untested, but the code is now substantially more defensible than R1 described).
- `CostGuard` now does a pre-flight `peek_cost` check before the call (was dead code in R1; `LiteLLMProvider.peek_cost` implements it).
- 28 new tests total (105 → 133 passing).
- `uv.lock` now committed.

---

## 1. Scorecard

| # | Dimension | R1 | R2 | Δ | Notes |
|---|---|---:|---:|---:|---|
| 1 | Code organization | 82 | **85** | +3 | Middleware classes now inherit from `LLMProvider` (cleaner contract). `_patch_server_class()` renamed to `_attach_serve_methods()` and documented (still a runtime monkey-patch with `# type: ignore[attr-defined]`). Empty `playbooks/library/__init__.py` stub still present. CONTRIBUTING.md still references non-existent `arnes/events/` directory (events live in `arnes/thread/events.py`). |
| 2 | Type safety | 45 | **92** | +47 | **The headline win.** `mypy --strict` passes with 0 errors across 36 source files. CI is now blocking. Middleware inherits from ABC. `LLMProvider.complete` declares `response_schema`. `list` shadowing fixed (renamed `list_models`/`list_names`). `kwargs` redefinition in `LiteLLMProvider.complete` fixed. `PlaybookMetadata \| None` narrowed with `assert` + non-None checks. Only remaining type hole: `LiteLLMProvider.__init__` doesn't accept kwargs but factory.py passes them — mypy can't see this because `**kwargs: Any` is opaque, but it's a runtime TypeError. |
| 3 | Error handling | 70 | **80** | +10 | R1-C1 (kwargs redefinition) and R1-C3 (max_iterations branch) fixed. Path-traversal guards extended to all MCP entrypoints. HTTP transport hardened with auth + rate-limit + size-cap. Pre-flight `peek_cost` wired through. **Still open**: `LiteLLMProvider.__init__` TypeError on user kwargs (NOT fixed); `Harness.run` still swallows `Exception` into a dict (loses traceback); HITL pause still schema-only (`cost_guard.py:279` has `# TODO v0.2: emit HumanApprovalRequestedEvent and block`); retry policy still not executed. |
| 4 | Test coverage & quality | 60 | **68** | +8 | 133 tests pass (was 105). `ollama.py` 0%→67%, `litellm_provider.py` 0%→34% (peek_cost only), `specialists/base.py` `_parse_and_validate_output` branches covered. **Still critical**: `mcp/server.py` **0%** despite the claim; `litellm_provider.complete()` body still untested; `cli/main.py` 33%; `tools/builtin.py` 47% (sandbox path 0%); `llm/factory.py` 26% (only mock branch). Overall coverage 65.18% — barely above the 65% floor, **no improvement** over R1's 65.37%. Same `SchemaValidMockProvider` copy-pasted across 4+ test files. No VCR cassettes despite vcrpy in dev deps. Claim "new tests added for mcp_server" is **false**. |
| 5 | Async correctness | 78 | **80** | +2 | 50-concurrent stress test still passes. `_propagate_event_sink()` cleanly shares the event sink across the middleware chain. **Still open**: `TokenOptimizer._cache` mutation has no `asyncio.Lock` (concurrent cache writes can race); "parallel" branches still execute sequentially (acknowledged v0.2 limitation, comment in `executor.py:471-472`); `thread_holder: list[Thread] = [Thread.create()]` mutable-singleton anti-pattern; `serve_http` still blocks forever on `asyncio.Event().wait()` with no shutdown signal. |
| 6 | API design | 75 | **82** | +7 | Middleware is now Liskov-substitutable for `LLMProvider`. `LLMProvider.complete` ABC reflects the real signature. `ToolResult.ok/fail` factories are clean. **Still open**: `Agent = Harness` deprecated alias still in `arnes/__init__.py` (violates manifesto rule #2); specialists return untyped `dict[str, Any]` instead of pydantic `SpecialistResult`; tool-call dicts accessed via `tc.get("function", {}).get("name")` instead of a typed `ToolCall` model; magic `__skip_steps_until` / `__resolved_str__` keys still leaked into the user-visible `outputs` dict. |
| 7 | Documentation | 78 | **75** | -3 | **Regression on consistency.** Docstrings on the changed modules are now substantially better (e.g., `peek_cost`, `_clean_json_response`, `_attach_serve_methods` all explain *why*). **But the README is now stale and misleading**: line 390 still says "mypy --strict is not yet enforced in CI (46 errors to fix)" — it IS enforced and passes; line 384 says "MCP HTTP transport is a minimal implementation (no auth, no rate limiting)" — the code now HAS bearer auth + rate limit + size cap. CONTRIBUTING.md still references non-existent `arnes/events/` directory (line 37). No API reference site. `arnes.dev` linked but unreachable. Stale claims that contradict the code are worse than no claim. |
| 8 | CI/CD pipeline | 65 | **78** | +13 | mypy is now blocking (the big one). Coverage gate is now explicit at the CI step level (`--cov-fail-under=65` on line 61, not just in `addopts`). Separate `security` and `build` jobs. `release.yml` publishes to PyPI on tag. Codecov upload. **Still open**: `pip-audit … \|\| true` on line 90 (security audit non-blocking); **no `pre-commit run --all-files` step** despite a `.pre-commit-config.yaml` existing; no SBOM / SLSA provenance; `arnes eval` subcommand (mock mode) never exercised in CI. |
| 9 | Dependency management | 70 | **85** | +15 | `aiohttp` declared in `mcp` extra (R1-C4 done). `uv.lock` now committed (was a 3-line `requirements.txt` stub). Upper-bounded ranges maintained. Optional extras still well-organized. **Still open**: `litellm` and `mcp` SDK are core deps but only needed for optional features (should be extras, mirroring the `ollama`/`anthropic`/`openai` pattern); no Renovate/Dependabot config visible; `pytest 8.4.2` has known vuln `PYSEC-2026-1845` (ignored in CI). |
| 10 | Maintainability | 70 | **78** | +8 | mypy --strict passing reduces future maintenance burden substantially. Middleware inheritance removes 9+ `# type: ignore` smells. Docstrings now explain *why* not just *what*. **Still open**: **O(N²) `Thread.append` NOT fixed** — stress test confirms `append x1000: 41.95 ms` (R1 was 42.42 ms; no change). `_attach_serve_methods()` still a runtime monkey-patch. `_arnes_wrapped` magic marker still present. 8+ separate `*_AUDIT*.md` files at repo root (now with V2 versions, audit fatigue worse). Same mock provider duplicated across test files. `Agent = Harness` alias still shipped. |

### Weighted overall score

Equal-weight average: **(85 + 92 + 80 + 68 + 80 + 82 + 75 + 78 + 85 + 78) / 10 = 80.3 → 80 / 100**

Round 1 was 69. **Round 2 is 80.** That is an **+11 point improvement**, driven almost entirely by the type-safety dimension (+47) and the knock-on effects of `mypy --strict` enforcement (better middleware inheritance, cleaner ABC, removed `# type: ignore` smells, blocked CI).

---

## 2. Top 3 remaining issues

### R1. `LiteLLMProvider.__init__` does not accept kwargs — factory.py still passes them

**File**: `arnes/llm/litellm_provider.py:51-58`, `arnes/llm/factory.py:48`

```python
# litellm_provider.py
class LiteLLMProvider(LLMProvider):
    def __init__(self) -> None:           # ← no **kwargs
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(...) from e

# factory.py
return LiteLLMProvider(**kwargs)          # ← propagates any caller kwargs
```

**Reproduced**:
```bash
$ uv run python -c "from arnes.llm.factory import get_provider; \
    get_provider('anthropic/claude-sonnet-4-20250514', api_key='sk-test')"
TypeError: LiteLLMProvider.__init__() got an unexpected keyword argument 'api_key'
```

The user's R2 narrative said "LiteLLMProvider kwargs fixed" — that fix applied to the `complete()` `kwargs`-redefinition bug (R1-C1), which IS fixed. The `__init__` kwargs issue (listed separately under R1 dimension #3) is **not** fixed. Any user who passes `api_key`, `timeout`, `base_url`, or any other configuration kwarg to `get_provider` for a paid vendor hits an immediate `TypeError`. mypy can't catch this because `**kwargs: Any` is opaque.

**Fix**: either accept and ignore unknown kwargs (`def __init__(self, **_: Any) -> None`) or accept the meaningful ones (`def __init__(self, *, api_key: str | None = None, timeout: float | None = None) -> None`) and forward to `litellm`.

---

### R2. `mcp/server.py` is still 0% covered — the "new tests added for mcp_server" claim is false

**File**: `arnes/mcp/server.py` (203 statements, 0 covered)

The R2 narrative claimed "New tests added for litellm_provider, ollama, mcp_server". Searching the test tree:

```
$ uv run pytest tests/ --co -q | grep -i -E "(lite|ollama|mcp|server)"
tests/unit/test_fix_ai.py::TestOllamaProvider::test_tools_passed_to_ollama_payload
tests/unit/test_fix_ai.py::TestOllamaProvider::test_tool_calls_parsed_from_response
tests/unit/test_fix_ai.py::TestOllamaProvider::test_no_tool_calls_returns_empty_list
tests/unit/test_fix_ai.py::TestLiteLLMPeekCost::test_peek_cost_returns_non_none_for_known_model
tests/unit/test_fix_ai.py::TestLiteLLMPeekCost::test_peek_cost_returns_non_none_for_unknown_model
tests/unit/test_fix_ai.py::TestLiteLLMPeekCost::test_peek_cost_zero_for_empty_messages
```

Zero tests touch `ArnesMCPServer.handle_request`, `_call_tool`, `_run_playbook`, `_list_specialists`, `_list_playbooks`, `_validate_playbook`, `serve_stdio`, `serve_http`, `_RateLimiter`, `_constant_time_eq`, or `_validate_playbook_path`. The path-traversal guards added during R2 are **untested**. The bearer-auth middleware is **untested**. The rate limiter is **untested**. The JSON-RPC dispatcher is **untested**. This is the highest-risk module in the codebase (it accepts untrusted input over HTTP/stdio and executes playbooks) and it has **zero tests**.

**Fix**: add a `tests/unit/test_mcp_server.py` covering at minimum: (a) `handle_request` dispatch for `initialize` / `tools/list` / `tools/call` / unknown method; (b) `_validate_playbook_path` blocks `/etc/`, `/root/`, etc.; (c) `_RateLimiter.allow` returns False after N requests; (d) `_constant_time_eq` rejects unequal strings; (e) `serve_http` rejects non-loopback binding without a token.

---

### R3. README is stale and contradicts the code

**File**: `README.md:380-390`

```
- **MCP HTTP transport** is a minimal implementation (no auth, no rate
  limiting). Use stdio transport for production. Full HTTP/SSE in v0.2.
...
- **Coverage** is at 66% (target: 80% by v0.2).
- **mypy --strict** is not yet enforced in CI (46 errors to fix).
```

All three of these claims are now **false**:

1. **MCP HTTP transport**: `serve_http` now has bearer-token auth (constant-time comparison via `hmac.compare_digest`), 1 MiB request-size cap, per-IP sliding-window rate limiter (100 RPM default), and refuses non-loopback binding without a token. The README claim "no auth, no rate limiting" is wrong.
2. **Coverage**: actual is **65.18%**, not 66%. (And the floor is 65%, so this is "barely passing" not "comfortably above target".)
3. **mypy --strict**: passes with 0 errors and is now a hard CI gate (no `|| true`). The README claim "not yet enforced in CI (46 errors to fix)" is wrong.

A user reading the README in August 2026 will believe the project is less mature than it actually is, and may avoid the HTTP transport unnecessarily. **Stale claims that contradict the code are worse than no claim** — they erode trust in every other claim the README makes.

**Fix**: update lines 384, 389, 390 to reflect current reality. While you're there, also fix `CONTRIBUTING.md:37` which still lists a non-existent `arnes/events/` directory (events live in `arnes/thread/events.py`).

---

## 3. Other notable issues (not in top 3, but worth fixing)

- **O(N²) `Thread.append`** (`thread/thread.py:70`) — confirmed unchanged: `append x1000: 41.95 ms` (R1: 42.42 ms). Stress test `test_thread_append_scaling` documents the cliff but the fix (structural-sharing / pyrsistent) wasn't applied. A 1000-step playbook spends ~40 ms just on `append`.
- **`pip-audit … || true`** (`ci.yml:90`) — security audit still non-blocking. The ignored vuln `PYSEC-2026-1845` (pytest 8.4.2 → fix in 9.0.3) is dev-only, but the `|| true` pattern is the same anti-pattern R1 flagged for mypy.
- **No `pre-commit run --all-files` step in CI** — `.pre-commit-config.yaml` exists with ruff + mypy + bandit + codespell + commitizen hooks, but CI never runs them. Contributors can push code that fails pre-commit and CI won't catch it.
- **`Agent = Harness` deprecated alias** (`arnes/__init__.py` / `agent/agent.py:131`) — still shipped, still violates manifesto rule #2 ("No classes named `Runnable`, `Chain`, `Workflow`, or `Agent`").
- **HITL pause still not implemented** — `cost_guard.py:279` has `# TODO v0.2: emit HumanApprovalRequestedEvent and block`. The `_paused` flag is set nowhere (grep confirms). README still over-promises ("HITL gates (pause and request approval) ✅ v0.1" was the R1 claim; the v0.1 reality is auto-reject).
- **`Harness.run` swallows `Exception` into a dict** (`agent/agent.py:124-126`) — `except Exception as e: return {"success": False, "error": str(e)}`. Loses traceback, hides programming errors as user-facing "error" strings.
- **Magic keys leaked into `outputs`** — `__skip_steps_until` and `__resolved_str__` still leak into the user-visible `outputs` dict. `mcp/server.py:243` strips them with a comprehension, but `Harness.run` doesn't.
- **8+ `*_AUDIT*.md` files at repo root** — now with V2 versions (AI_AUDIT, AI_AUDIT_V2, SECURITY_AUDIT, SECURITY_AUDIT_V2, DX_AUDIT, DX_AUDIT_V2, ARCHITECTURE_AUDIT, COMPETITIVE_AUDIT) plus 5 `JUDGE_*_R1.md` files. Audit fatigue. Move to `docs/audits/` or `.archive/`.
- **`_attach_serve_methods()` runtime monkey-patch** (`mcp/server.py:515-529`) — renamed from `_patch_server_class()` in R1, but same pattern: assigns `serve_stdio` / `serve_http` to `ArnesMCPServer` after class definition, with `# type: ignore[attr-defined]`. Cleaner would be to declare them as `@staticmethod` returning the module function, or to make `ArnesMCPServer` lazy-import the transport fns.

---

## 4. Verdict

### **GO** for public release as an explicit alpha with the existing "Known Limitations" section in README (updated to match reality).

### **NO-GO** for the creator's stated "world-class code quality" bar — but **only barely**. Three concrete fixes would clear it:

1. Fix `LiteLLMProvider.__init__` to accept (and forward or ignore) kwargs — **30 minutes**.
2. Add `tests/unit/test_mcp_server.py` covering `handle_request`, path-traversal guards, rate limiter, and auth middleware — **1 day**.
3. Update README lines 384/389/390 to match the code, and fix `CONTRIBUTING.md:37` — **30 minutes**.

After those three: **84-86 / 100**, comfortably in "world-class alpha" territory.

### Reasoning

Round 1's three hard blockers were:

1. **Type safety not enforced** → **RESOLVED**. `mypy --strict` passes (0 errors, 36 files). CI is blocking. The ABC is now Liskov-substitutable. This is the single biggest credibility win of the round.
2. **Real correctness bugs ship in v0.1** → **3 of 4 resolved**. R1-C1 (kwargs redefinition) ✅, R1-C2 (cache poisoning) ✅, R1-C3 (max_iterations misleading error) ✅, R1-C4 (aiohttp missing) ✅. R1-C5 (middleware inheritance) ✅. The **remaining** correctness bug is `LiteLLMProvider.__init__` kwargs — `TypeError` for any user-supplied config kwarg. That's bad, but it's one localized fix.
3. **CI does not gate on quality** → **PARTIALLY RESOLVED**. mypy is now a hard gate. Coverage gate is now visible at the CI step. But `pip-audit || true` remains, and `pre-commit run --all-files` is still absent.

The architecture was genuinely good in R1 and is still genuinely good in R2 — stateless reducer, declarative YAML, vendor-neutral provider abstraction, hierarchical cost guard, SSRF/path-traversal defenses, MCP integration. The Round-2 fixes removed the type-safety drag that was the largest credibility gap. The remaining gaps are localized (one provider bug, one untested module, one stale README) rather than systemic.

**Recommended path from 80 → 85+ (world-class bar):**

1. Fix top-3 issues above. Estimated 1.5 days.
2. Add `pre-commit run --all-files` to CI and remove `|| true` from pip-audit. Estimated 1 hour.
3. Bring `cli/main.py` from 33% → 70% and `tools/builtin.py` from 47% → 70% (esp. the sandbox path). Estimated 1 day.
4. Switch `Thread.append` from `[*self.events, event]` to a structural-sharing data structure. Estimated 0.5 days.
5. Replace `dict[str, Any]` specialist results with a pydantic `SpecialistResult`. Estimated 1 day.
6. Reconcile the README feature matrix with reality (HITL pause, retry execution, sandbox wiring). Estimated 0.5 days.

Total: ~5 days of focused work to clear 80 → 87.

---

## 5. Appendix — reproduction commands

```bash
# All 133 tests pass; coverage 65.18%
cd /home/z/my-project/arnes && uv run pytest tests/ -q
# → 133 passed in 6.02s, coverage 65.18%

# mypy --strict passes (was 50 errors in R1)
uv run mypy arnes/ --strict
# → Success: no issues found in 36 source files

# Ruff and bandit are clean
uv run ruff check arnes/ tests/   # → All checks passed!
uv run bandit -r arnes/ -c pyproject.toml  # → No issues identified

# Reproduce R1 (LiteLLMProvider __init__ kwargs bug — STILL OPEN)
uv run python -c "
from arnes.llm.factory import get_provider
get_provider('anthropic/claude-sonnet-4-20250514', api_key='sk-test')
"
# → TypeError: LiteLLMProvider.__init__() got an unexpected keyword argument 'api_key'

# Verify R1-C2 fix (cache poisoning — FIXED)
uv run python -c "
import asyncio
from arnes.llm.base import LLMMessage
from arnes.llm.mock import MockLLMProvider
from arnes.middleware.token_optimizer import TokenOptimizer
async def main():
    p = MockLLMProvider(default_response='{\"result\":\"hi\"}')
    opt = TokenOptimizer(p, enable_cache=True)
    msgs = [LLMMessage(role='user', content='hi')]
    r1 = await opt.complete(msgs, model='mock', response_schema={'required':['result']})
    r2 = await opt.complete(msgs, model='mock', response_schema={'required':['OTHER']})
    print('r1 cached:', r1.usage.cached, '| r2 cached:', r2.usage.cached)
    # → r1 cached: True | r2 cached: False  (FIXED in R2)
asyncio.run(main())
"

# Verify mcp/server.py is still 0% covered (CLAIM FALSE)
uv run pytest tests/unit/test_fix_ai.py --cov=arnes/mcp/server --cov-report=term
# → arnes/mcp/server.py   203   203   50   0   0%   21-529

# Confirm O(N²) Thread.append unchanged
uv run pytest tests/stress/test_thread_append_scaling.py -v -s
# → append x1000: 41.95 ms (R1: 42.42 ms — no change)
```

---

**Re-evaluation complete. Overall development score: 80 / 100. Verdict: GO as a documented alpha; one more focused sprint (fix LiteLLMProvider.__init__, add MCP server tests, refresh README) clears the world-class bar.**
