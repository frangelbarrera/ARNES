# JUDGE-DEV-R3 — ARNES Development Quality Re-Evaluation

**Auditor:** Senior Python Engineer (judge role)
**Date:** 2026-07-31
**Subject:** ARNES v0.1.0a1 — re-evaluation after Round-3 fixes
**Prior scores:** R1 = 69 (NO-GO for world-class bar) → R2 = 80 (CONDITIONAL GO)
**Method:** Full source-tree re-read of changed modules. Ran `uv run mypy arnes/ --strict` (0 errors), `uv run ruff check arnes/` (clean), `uv run pytest` (184/184 pass, 71.81% coverage), reproduced the `get_provider("anthropic/...", api_key="sk-test")` call live, ran `scripts/demo.sh` end-to-end.

---

## 0. Verification of claimed Round-2 fixes

| # | Claimed fix | Verified? | Evidence |
|---|---|---|---|
| 1 | `LiteLLMProvider.__init__` accepts kwargs | ✅ **YES** | `arnes/llm/litellm_provider.py:59–72` declares `def __init__(self, **kwargs: Any) -> None`, stores `self._init_kwargs: dict[str, Any] = dict(kwargs)`, and forwards them to every `litellm.acompletion` call at line 97 (`call_kwargs: dict[str, Any] = {**self._init_kwargs}`). Reproduced live: `get_provider("anthropic/claude-sonnet-4-20250514", api_key="sk-test")` returns `LiteLLMProvider` (no `TypeError`). The R2 dimension-#3 "unfixed" item is now closed. |
| 2 | `mcp/server.py` test coverage 0% → 64% | ✅ **YES** | `tests/unit/test_mcp_server.py` (608 lines, 39 tests) covers the JSON-RPC dispatcher, all 4 tools, path-traversal guards on all endpoints, `_RateLimiter`, `_constant_time_eq`, `_validate_playbook_path`. `pytest --cov=arnes/mcp tests/unit/test_mcp_server.py` shows `arnes/mcp/server.py: 64%` (was 0% in R2). The R2 "claim is false" finding is now closed. |
| 3 | `asyncio.gather` parallelism | ✅ **YES** | `arnes/playbooks/executor.py:533–641` `_execute_parallel` builds `coros = [self._execute_step(...) for sub_step in step.parallel]` and runs them via `await asyncio.gather(*coros, return_exceptions=True)` at line 588. The R2 dimension-#5 "still sequential" finding is now closed. Each sub-step gets its own `thread_holder` snapshot; deltas are merged back in timestamp order. Stable sort preserves intra-sub-step ordering. |
| 4 | Sandbox auto-detection | ✅ **YES** | `arnes/playbooks/executor.py:56–77, 141–161` defines `_is_docker_available()` and wires `sandbox_enabled=True` + `sandbox_container="arnes-sandbox:latest"` when Docker is on PATH. Verified live: `--mock` run without Docker produces `sandbox_docker_unavailable` warning with `ARNES_DEV_MODE=1` fallback hint. |
| 5 | CostGuard 95% pause + HITL event | ✅ **YES** | `arnes/middleware/cost_guard.py:256–318` in interactive mode sets `self._paused = True`, emits `HumanApprovalRequestedEvent` (with question, options, ttl, spent_usd, budget_usd, threshold_level), and raises `BudgetExceeded(level="pause")`. Non-interactive falls through to the 100% hard stop (documented as the intentional contract). |
| 6 | All 5 specialists use `pydantic_model` | ✅ **YES** | Verified by direct read: `planner.py:99` (`PlannerOutput`), `coder.py:94` (`CoderOutput`), `reviewer.py:97` (`ReviewerOutput`), `tester.py:112` (`TesterOutput`), `debugger.py:98` (`DebuggerOutput`). Each specialist declares both `output_schema` (sent to the LLM) and `pydantic_model` (validates the parsed response at the specialist layer). Each pydantic model enforces type-safe enum validation (`Literal["create", "modify"]`, `Literal["approve", "request_changes", "reject"]`, etc.) and nested model validation (`CoderFile`, `ReviewerIssue`, `TestFailure`, `DebuggerFix`). |
| 7 | `LiteLLMProvider.complete` kwargs bug | ✅ **YES** (preserved from R2) | `litellm_provider.py:80–112` builds `call_kwargs: dict[str, Any] = {**self._init_kwargs}` then `call_kwargs.update(kwargs)`, then applies explicit named params last. Order of precedence documented in the class docstring (lines 50–57). |
| 8 | Dangling-symlink fix in `fs_write` | ✅ **YES** | `arnes/tools/builtin.py:380–384` checks `safe_path.is_symlink()` ALONE with an 9-line inline comment (`FIX-R3-SEC`) explaining why `Path.exists()` follows the link and returns False for dangling symlinks. Same fix in `fs_read` at lines 325–329. |
| 9 | `mypy --strict` clean (preserved) | ✅ **YES** | `uv run mypy arnes/ --strict` → `Success: no issues found in 36 source files`. CI step at `.github/workflows/ci.yml:50` runs `uv run mypy arnes/ --strict` (no `\|\| true`). |
| 10 | 184 tests pass, 71.81% coverage | ✅ **YES** | `pytest -q` → `184 passed in 11.71s`. `--cov-fail-under=65` reached. Total coverage: 71.81% (up from 65.18% in R2 — +6.6 points). |

**Bonus fixes I observed that weren't claimed:**
- `_execute_parallel` correctly uses `return_exceptions=True` so a single sub-step failure doesn't cancel siblings. Each sub-step gets an isolated `thread_holder` (snapshot of parent at parallel-point) so appends are race-free; deltas merged back by stable timestamp sort.
- `_attach_serve_methods()` (mcp/server.py:515–529) is now clearly documented as a deliberate runtime pattern with `# type: ignore[attr-defined]` — the smell is still there but it's no longer a mystery.
- CostGuard `_propagate_event_sink()` shares one `_events` list across the middleware chain (preserved from R2, still working).
- `examples/` directory now has 4 numbered example scripts (`01_hello_world.py` … `04_mcp_server.py`) with a README — a real "next step" after the quickstart.
- `scripts/demo.sh` (166 lines) produces a clean narrated demo with optional `vhs`/`agg` recording hooks — closes the R2 "no demo GIF" gap (the script is the asset; the GIF is a `vhs demo.tape` away).

---

## 1. Scorecard

| # | Dimension | R1 | R2 | R3 | Δ(R2→R3) | Notes |
|---|---|---:|---:|---:|---:|---|
| 1 | Code organization | 82 | 85 | **87** | +2 | Async gather + per-sub-step thread snapshot is clean. `_attach_serve_methods` still a monkey-patch but documented. Empty `playbooks/library/__init__.py` stub still present. |
| 2 | Type safety | 45 | 92 | **93** | +1 | `mypy --strict` still 0 errors across 36 files. `LiteLLMProvider.__init__(**kwargs)` fixes the R2 runtime `TypeError` that mypy couldn't see (opaque `**kwargs`). Only remaining type hole: `_attach_serve_methods` runtime patching. |
| 3 | Error handling | 70 | 80 | **84** | +4 | R2-C1 (kwargs) and R2-C3 (max_iterations) preserved. CostGuard pause now raises `BudgetExceeded(level="pause")` cleanly. `LiteLLMProvider.__init__` kwargs no longer `TypeError`. **Still open**: `Harness.run` swallows `Exception` into a dict (loses traceback); tool-level HITL auto-rejects in non-interactive; retry policy still not executed. |
| 4 | Test coverage & quality | 60 | 68 | **76** | +8 | 184 tests (was 133). Overall coverage 71.81% (was 65.18%). `mcp/server.py` 0%→64% (39 new tests). `cost_guard.py` 60%→92%. `verification.py` 60%→89%. `token_optimizer.py` 60%→85%. `playbooks/compiler.py` 17%→88%. `specialists/base.py` 20%→82%. **Still weak**: `cli/main.py` 33%, `litellm_provider.complete()` body 0%, `tools/builtin.py` 47% (sandbox path 0%), `llm/factory.py` 26%. |
| 5 | Async correctness | 78 | 80 | **88** | +8 | **The headline R3 win.** `asyncio.gather(*coros, return_exceptions=True)` with per-sub-step thread snapshots is correct concurrency. Stable timestamp sort preserves intra-sub-step ordering. **Still open**: `TokenOptimizer._cache` mutation has no `asyncio.Lock` (concurrent cache writes can race); `thread_holder: list[Thread] = [Thread.create()]` mutable-singleton anti-pattern preserved; `serve_http` blocks on `asyncio.Event().wait()` with no shutdown signal. |
| 8 | API design | 75 | 82 | **83** | +1 | Middleware Liskov-substitutable (preserved). `ToolResult.ok/fail` factories clean (preserved). **Still open**: `Agent = Harness` deprecated alias still shipped in `arnes/__init__.py:131`; specialists return untyped `dict[str, Any]` instead of pydantic `SpecialistResult`; magic `__skip_steps_until` / `__resolved_str__` keys still leaked into user-visible `outputs` dict. |
| 7 | Documentation | 78 | 75 | **76** | +1 | Docstrings on changed modules are excellent (`peek_cost`, `_clean_json_response`, `_attach_serve_methods`, `_execute_parallel` all explain *why*). CONTRIBUTING.md project structure now matches reality (`arnes/events/` reference removed). **But README is partially stale**: lines 222, 454 still claim "parallel branches sequential" — they're not; line 460 still claims "Docker sandbox not wired" — auto-detect wires it. PR template line 32 still says "we are not yet at --strict in CI" — it IS enforced. CONTRIBUTING.md lines 168, 172 still reference `docs/specialists.md` and `docs/playbook-dsl.md` which don't exist. |
| 8 | CI/CD pipeline | 65 | 78 | **79** | +1 | mypy blocking (preserved). Coverage floor 65% at step level (preserved). Separate security + build jobs (preserved). `release.yml` publishes to PyPI on tag (preserved). **Still open**: `pip-audit \|\| true` non-blocking (line 90); `PYSEC-2026-1845` ignored without justification; no `pre-commit run --all-files` step in CI; no SBOM / SLSA provenance; actions pinned to floating major-version tags; `arnes eval` subcommand never exercised in CI. |
| 9 | Dependency management | 70 | 85 | **85** | 0 | `aiohttp` in `mcp` extra (preserved). `uv.lock` committed (preserved). Upper-bounded ranges maintained. **Still open**: `litellm` and `mcp` SDK are core deps but only needed for optional features; no Renovate/Dependabot config; `pytest 8.4.2` has known vuln `PYSEC-2026-1845` (ignored in CI). |
| 10 | Maintainability | 70 | 78 | **80** | +2 | mypy --strict passing (preserved). Middleware inheritance clean (preserved). Docstrings explain *why* (preserved). **Still open**: **O(N²) `Thread.append` NOT fixed** — `thread.py:70` still does `Thread(id=self.id, events=[*self.events, event])` full list copy on every append. Stress test confirms 50-step run takes 323 ms (compile + execute); the structural-sharing recommendation from R1/R2 (`pyrsistent.pvector`) is still not implemented. `_arnes_wrapped` magic marker still present. `Agent = Harness` alias still shipped. 8+ separate `*_AUDIT*.md` files at repo root. |

### Weighted overall score

Equal-weight average: **(87 + 93 + 84 + 76 + 88 + 83 + 76 + 79 + 85 + 80) / 10 = 83.1 → 83 / 100**

R1 was 69. R2 was 80. **R3 is 83.** That is a **+3 point improvement**, driven by the `asyncio.gather` correctness win (+8 on async), the LiteLLM kwargs fix (closes the R2 dimension-#3 unfixed item), and the MCP test coverage gain (+8 on test coverage, +6.6 points overall coverage).

---

## 2. Top 3 remaining issues

### R1. `Thread.append` is still O(N) per call → O(N²) for N events — **Medium (performance)**

**File:** `arnes/thread/thread.py:64–70`

```python
def append(self, event: Event) -> Thread:
    """Append an event, returning a new Thread (immutability preserved)."""
    if event.thread_id != self.id:
        raise ValueError(...)
    return Thread(id=self.id, events=[*self.events, event])  # ← full list copy
```

`tests/stress/test_large_playbook.py` confirms a 50-step playbook takes 323 ms total wall clock — most of it in the compile/execute loop where appends dominate. A 10k-step playbook would still take minutes just on appends. The R1/R2 recommendation (`pyrsistent.pvector` for structural sharing, O(log N) append) is still not implemented. The R3 fixes did not touch this; it remains the single longest-standing quality issue.

**Fix:** switch `events: list[Event]` to `events: pyrsistent.PVector[Event]` (or any structural-sharing persistent vector). The immutable contract is preserved; append cost drops from O(N) to O(log N).

---

### R2. `Harness.run` swallows `Exception` into a dict — **Medium (debuggability)**

**File:** `arnes/agent/agent.py:124–126`

```python
try:
    result = await specialist_obj.run(input_data, ctx, provider=wrapped_provider, ...)
    return result
except Exception as e:
    logger.exception("harness_run_failed", specialist=specialist, error=str(e))
    return {"success": False, "error": str(e)}
```

The original traceback is logged via `logger.exception`, but the caller gets a `dict` with just the stringified error — no exception type, no chained cause, no way to programmatically catch a specific failure mode. The PlaybookExecutor catches `BudgetExceeded` (good), but `Harness.run`'s blanket `except Exception` hides everything else.

**Fix:** return a typed `SpecialistResult` pydantic model with `error_type: str`, `error_message: str`, `error_cause: str | None`. Or re-raise after logging. Or both: log + re-raise, and let the caller decide.

---

### R3. README "Known Limitations" and PR template are stale — **Low (consistency)**

**Files:** `README.md:222, 454, 460`, `.github/PULL_REQUEST_TEMPLATE.md:32`

Three claims in the README contradict the R3 code:
- Line 222 (features table): "Parallel branches (sequential in MVP) | ⚠️ v0.1 (true parallelism in v0.2)" — `asyncio.gather` IS now implemented.
- Line 454 (Known Limitations): "Parallel branches execute sequentially in v0.1 (true `asyncio.gather` comes in v0.2)" — same.
- Line 460: "Docker sandbox is not wired up by default. Local shell execution requires `ARNES_DEV_MODE=1`" — auto-detection wires it when Docker is on PATH.

And one in the PR template:
- Line 32: "Types pass — `uv run mypy arnes/` (we are not yet at `--strict` in CI; new code should not add mypy errors)" — `mypy --strict` IS now blocking in CI.

`CONTRIBUTING.md:168, 172` still references `docs/specialists.md` and `docs/playbook-dsl.md` which don't exist (no `docs/` files other than `logo.svg`, `social-card.svg`, `social-card.png`).

A new contributor following the CONTRIBUTING map or the PR checklist will see claims that contradict the code — exactly the failure mode the R2 doc-honesty win was supposed to prevent. These are 5-minute fixes; they should not survive a release.

---

## Verdict

### **GO** for public alpha release.

R1 was NO-GO at 69. R2 was CONDITIONAL GO at 80. R3 is **83** and a clean GO for public alpha.

**All R2 critical issues are closed:**
1. ✅ `LiteLLMProvider.__init__` accepts kwargs (verified live).
2. ✅ `mcp/server.py` 0% → 64% coverage (39 new tests).
3. ✅ True `asyncio.gather` parallelism with per-sub-step thread snapshots.
4. ✅ `mypy --strict` still passes (preserved).

**Remaining caveats (do not block alpha release):**
- `Thread.append` O(N²) — fix with `pyrsistent.pvector` or any structural-sharing persistent vector.
- `Harness.run` blanket `except Exception` — return a typed result or re-raise.
- Stale README "Known Limitations" and PR template — refresh to match the R3 code.

**Release posture:** Suitable for a **public alpha** (`0.1.0a1`) targeted at developers who want a typed, tested, async-correct agent harness. The trajectory from R1 (69) → R2 (80) → R3 (83) shows sustained investment in the dimensions that matter most (type safety +47 over two rounds, async correctness +10, test coverage +16).

**Expected score after the 3 remaining items are remediated:** 88–92.

---

*End of report. — JUDGE-DEV-R3*
