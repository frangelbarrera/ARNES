# JUDGE_FINAL_R5 — ARNES Final Round 5 Evaluation

**Auditor:** Final Judge (consolidated, all 6 categories)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Cycle:** Round 5 — final evaluation
**Prior scores:** R1 avg 59.7 → R2 avg 71.2 → R3 avg 76.2 → R4 avg 79.5
**Method:** Static re-review of all source under `arnes/`, all tests under `tests/`, `AGENTS.md`, `CHANGELOG.md`, `README.md`, `pyproject.toml`, `.github/workflows/`. Ran `pytest` (207/207 pass, 72.95% coverage), `mypy --strict arnes/` (clean), `ruff check arnes/` (clean), `bandit -r arnes/ -c pyproject.toml` (0 issues), `arnes run manuals/hello-world.yaml --mock` (works, bitácora produced), `arnes list specialists` (works), `arnes lint manuals/hello-world.yaml` (works). Verified each claimed R5 fix against current code, including direct runtime probes of `_filter_internal_keys` and `Harness.run` error paths.

---

## 0. Verification of Claimed R5 Fixes

| # | R5 Claimed Fix | Status | Evidence |
|---|---|---|---|
| 1 | Filter internal sentinel keys (`__skip_steps_until`, `__resolved_str__`, `__input__`, `_approved_fingerprints`) from `PlaybookRunResult.outputs` | ✅ **VERIFIED APPLIED** | `arnes/playbooks/executor.py:281, 307, 904–913` defines `_filter_internal_keys(outputs)` and applies it at both the success path (line 281) and the `BudgetExceeded` path (line 307). End-to-end probe: ran `executor.run(hello-world.yaml)` and inspected `result.outputs.keys()` — only `['plan']` returned, no sentinels. Closes R4 Data Top Issue #2. |
| 2 | `Harness.run` separated `BudgetExceeded` from generic `Exception`, added `error_type` field | ✅ **VERIFIED APPLIED** | `arnes/agent/agent.py:124–141` has two separate `except` clauses: `except BudgetExceeded` returns `{"success": False, "budget_exceeded": True, ...}` and `except Exception` returns `{"success": False, "error_type": type(e).__name__, ...}`. End-to-end probe with a `RaisingProvider` that throws `RuntimeError` returned `{'error_type': 'RuntimeError', 'success': False, ...}`. Closes R4 Dev Top Issue #1. |
| 3 | `CHANGELOG.md`: comprehensive Unreleased section documenting all R2-R4 changes | ⚠️ **PARTIAL** | `CHANGELOG.md:8–57` has a real "Unreleased" section with "Added in Round 4", "Changed in Round 4", "Fixed in Round 4" subsections covering ~40 distinct items. **But everything is grouped under "Round 4"** — no separate R2 or R3 sections. The changes ARE documented (claim of "comprehensive" is fair), but they are not distinguished by round (claim of "R2-R4" labeling is technically misleading). |
| 4 | `AGENTS.md`: fixed stale 'immutable' Thread claim → 'append-only (mutates in place)' | ❌ **NOT APPLIED** | `AGENTS.md:13` STILL reads: `**Thread**: immutable, append-only event log. State = reduce(events).` Direct `rg "immutable" AGENTS.md` returns line 13 unchanged. The fix was claimed but never actually applied to the file. `arnes/thread/thread.py:13` continues to say the opposite: `Thread is **append-only**, NOT immutable: append() mutates the internal events list in place`. This is a **false fix claim** — the most concrete finding of R5. |

**Net assessment of R5 fixes:** 2 of 4 cleanly applied (#1 sentinel filter, #2 error_type). 1 partially applied (#3 CHANGELOG). 1 not applied at all (#4 AGENTS.md) — and worse, claimed as applied. Three separate R4 judge reports (Security, Development, Marketing) had all flagged the AGENTS.md immutability contradiction as a Top Issue. The fix is a 5-minute edit. Its absence in R5 — combined with the false claim of having fixed it — is the single most significant finding of this final round.

---

## 1. Final Scores Per Dimension

### Security (10 dimensions)

| #  | Dimension                 | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|---------------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | Input validation          | 68 | 72 | 74 | 74 | **74** | 0 | `ShellTool.Args.cwd` still free-form; `_check_ssrf` sync fallback still preserved. |
| 2  | Secret handling           | 72 | 73 | 73 | 73 | **73** | 0 | `_looks_like_secret` heuristic preserved. `SecretBroker` still referenced but not implemented. |
| 3  | Sandbox isolation         | 42 | 45 | 70 | 84 | **84** | 0 | `Dockerfile.sandbox` + `scripts/build-sandbox.sh --check` preserved. No seccomp/user-namespace. |
| 4  | SSRF protection           | 68 | 85 | 86 | 86 | **86** | 0 | IP pinning + Host header + SNI preserved. |
| 5  | Path traversal protection | 72 | 78 | 82 | 82 | **82** | 0 | Dangling-symlink fix preserved. Denylist-based `/etc` `/root` etc. |
| 6  | Budget / DoS protection   | 55 | 58 | 82 | 84 | **84** | 0 | `RUN_PAUSED` producer preserved. Streaming path still bypasses budget gate (documented). |
| 7  | HITL integrity            | 55 | 72 | 74 | 74 | **74** | 0 | CostGuard 95% pause preserved. Tool-level HITL auto-rejects in non-interactive. |
| 8  | MCP server security       | 38 | 80 | 82 | 82 | **82** | 0 | Bearer auth, rate limit, 1 MiB body cap, path validation on all endpoints preserved. |
| 9  | CI/CD security            | 52 | 58 | 60 | 84 | **84** | 0 | SHA-pinned actions, blocking pip-audit, CodeQL preserved. `release.yml` still uses `PYPI_API_TOKEN`. |
| 10 | Documentation honesty     | 50 | 85 | 88 | 92 | **91** | -1 | The AGENTS.md immutability contradiction was *claimed fixed* in R5 but was **not** actually applied. A false fix claim is a small doc-honesty regression vs. R4's honest "we know this is stale." Offset partially by the sentinel-filter closing one Python-API internal-state exposure surface. |
|    | **Overall**               | 57 | 70 | 78 | 82 | **83** | **+1** | |

**Top remaining issue:** `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing — the last supply-chain hardening gap. (Not in R5 scope; preserved from R4.) Secondary: `AGENTS.md:13` "immutable" claim still contradicts `thread.py:13` "NOT immutable" — claimed fixed in R5, actually not.

**Verdict:** **GO** for public alpha. Not yet production-ready (no streaming budget enforcement, no memory, no multi-agent).

---

### Development (10 dimensions)

| #  | Dimension           | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|---------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | Code organization   | 60 | 78 | 82 | 84 | **84** | 0 | 36 source files, single responsibility per module preserved. `executor.py` still 914 lines. |
| 2  | Type safety         | 55 | 78 | 86 | 90 | **90** | 0 | `mypy --strict` clean on 36 source files. R5 introduced no new type issues. |
| 3  | Error handling      | 55 | 68 | 78 | 80 | **84** | +4 | R5 closes R4 Dev Top Issue #1: `Harness.run` now separates `BudgetExceeded` (returns `budget_exceeded: True`) from generic `Exception` (returns `error_type: type(e).__name__`). Caller can now programmatically distinguish failure modes. Verified end-to-end. |
| 4  | Test coverage       | 60 | 68 | 76 | 82 | **82** | 0 | 207 tests, 72.95% coverage. R5 introduced no new tests for the sentinel filter or error_type field — both fixes are untested. |
| 5  | Async correctness   | 65 | 80 | 86 | 88 | **88** | 0 | True `asyncio.gather` parallelism preserved. `TokenOptimizer._cache` mutation still has no `asyncio.Lock` (R4 Dev Top Issue #2, not addressed in R5). |
| 6  | API design          | 60 | 78 | 82 | 84 | **85** | +1 | Sentinel filter removes internal control-flow state from `PlaybookRunResult.outputs` — cleaner Python API surface. |
| 7  | Documentation       | 60 | 76 | 82 | 84 | **85** | +1 | `CHANGELOG.md` Unreleased section is genuinely comprehensive (~40 items). Slight knock: rounds are not distinguished (everything labeled "Round 4"). |
| 8  | CI/CD               | 65 | 80 | 84 | 88 | **88** | 0 | 3-OS × 3-Python matrix, blocking mypy/ruff/bandit/pip-audit, CodeQL weekly. Preserved. |
| 9  | Dependencies        | 70 | 80 | 84 | 86 | **86** | 0 | `uv.lock` committed. `litellm>=1.50,<2`, `pydantic>=2.11,<3`, etc. Preserved. |
| 10 | Maintainability     | 65 | 80 | 84 | 86 | **85** | -1 | R5 claim "AGENTS.md: fixed stale 'immutable' Thread claim" was **not applied** — a contributor reading AGENTS.md will still write code expecting immutability and hit the in-place mutation. This is a known-issue-but-claimed-fixed state, which is worse for maintainability than R4's known-issue-and-acknowledged. |
|    | **Overall**         | 69 | 80 | 83 | 87 | **88** | **+1** | |

**Top remaining issue:** `AGENTS.md:13` still says "Thread: immutable" — claimed fixed in R5 but actually not. A false fix claim is the single biggest maintainability hazard: contributors will trust the AGENTS.md claim and write code expecting immutability, then hit a real correctness bug. **5-minute fix**: change line 13 to "Thread: append-only event log (in-place mutation, O(1) per append). State = reduce(events)."

**Verdict:** **GO** for public alpha.

---

### Data (10 dimensions)

| #  | Dimension                | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|--------------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | Event log design         | 72 | 82 | 83 | 88 | **88** | 0 | 4 of 8 R3-dead event types still closed. 5 of 24 still never emitted: `CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_RESUMED`, `USER_MESSAGE`. |
| 2  | State management         | 65 | 82 | 84 | 86 | **87** | +1 | Sentinel keys no longer leak into `PlaybookRunResult.outputs` for Python consumers (R5 fix #1, verified). Cleaner state surface. |
| 3  | Observability            | 58 | 78 | 80 | 86 | **86** | 0 | `MODEL_ROUTED`, `PARALLEL_BRANCH_STARTED/COMPLETED`, `RUN_PAUSED`, `REFUSAL_TRIGGERED` producers preserved. |
| 4  | Audit trail (bitácora)   | 55 | 80 | 84 | 88 | **88** | 0 | Markdown bitácora preserved. Still no "decisions summary" section at the top. |
| 5  | Data flow (templates)    | 70 | 72 | 73 | 73 | **73** | 0 | Template resolver unchanged. MCP-boundary filter for sentinel keys still preserved (R5 fix #1 also adds Python-boundary filter). |
| 6  | Cache design             | 55 | 78 | 78 | 78 | **78** | 0 | `response_schema` in cache key preserved. Still in-memory only (R4 Data Top Issue #1, not addressed in R5). |
| 7  | Cost tracking            | 65 | 82 | 86 | 88 | **88** | 0 | Pre-flight `peek_cost` + hard stop + 95% pause + circuit breaker preserved. Streaming path bypasses budget gate (documented v0.2). |
| 8  | Performance data         | 72 | 72 | 72 | 88 | **88** | 0 | `Thread.append` O(1) preserved. 8.8x speedup vs R3 O(N²) still holds. |
| 9  | Data validation          | 65 | 68 | 78 | 78 | **78** | 0 | All 5 specialists use `pydantic_model`. `VerificationLayer._validate_structured` still only checks `required` fields. |
| 10 | Persistence              | 50 | 52 | 53 | 53 | **53** | 0 | `Thread.save/load` JSON to disk preserved. No SQLite/Postgres backend (v0.2 roadmap). |
|    | **Overall**              | 63 | 76 | 79 | 81 | **83** | **+2** | |

**Top remaining issue:** Cache is still in-memory only — `TokenOptimizer._cache: dict[str, CacheEntry] = {}` with no persistence across runs and no Redis/disk backend. A long-running MCP server loses all cache state on restart; cross-process sharing is impossible. (R4 Data Top Issue #1, not addressed in R5.)

**Verdict:** **GO** for public alpha.

---

### AI (10 dimensions)

| #  | Dimension                  | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|----------------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | Specialist prompt quality  | 62 | 68 | 74 | 74 | **74** | 0 | 5 specialists with `pydantic_model` + `output_schema` preserved. No few-shot examples. |
| 2  | ReAct tool-use loop        | 48 | 72 | 78 | 78 | **78** | 0 | `asyncio.gather` parallelism preserved. No streaming per iteration. |
| 3  | Structured output validation | 45 | 68 | 82 | 82 | **82** | 0 | All 5 specialists use `pydantic_model`. `VerificationLayer._validate_structured` still only checks required fields. |
| 4  | Anti-hallucination layer   | 38 | 70 | 72 | 72 | **72** | 0 | 2 of 5 layers implemented (structured outputs + refusal). Confidence gate, critic loop, grounding RAG still v0.2/v0.3/v0.4. |
| 5  | Token optimization         | 52 | 68 | 70 | 74 | **74** | 0 | Model routing + semantic cache preserved. `estimated_savings_usd` still flat $3/1M heuristic. |
| 6  | Cost guard                 | 58 | 70 | 84 | 86 | **86** | 0 | Hierarchical budget + circuit breaker + HITL pause preserved. |
| 7  | Playbook DSL expressiveness | 55 | 58 | 64 | 64 | **64** | 0 | Parallel branches, conditionals, `if_not_met` preserved. No loops, no imports, no retry policy execution. |
| 8  | LLM provider abstraction   | 50 | 72 | 80 | 86 | **86** | 0 | `LLMProvider` ABC + `stream_complete` abstract + `peek_cost` preserved. Real streaming still raises `NotImplementedError`. |
| 9  | Default model viability    | 35 | 58 | 60 | 60 | **60** | 0 | `ollama/llama3.2` default (local, free, vendor-neutral). No model-recommendation engine. |
| 10 | AI pattern innovation      | 65 | 68 | 70 | 72 | **72** | 0 | Manifesto, manual-is-code, bitácora, CostGuard killer differentiators all preserved. |
|    | **Overall**                | 50 | 67 | 73 | 75 | **75** | **0** | |

**R5 introduced no AI-layer changes.** The R5 fixes (sentinel filter, error_type, CHANGELOG, AGENTS.md) are all in the security/dev/data/marketing surfaces, not the AI surface. All three R4 AI Top Issues remain open:
1. Streaming stubs raise `NotImplementedError` for real providers (`OllamaProvider`/`LiteLLMProvider`).
2. No real-LLM integration tests (all 207 use mocks; `vcrpy` is in dev deps but no cassettes).
3. Confidence gate / critic loop / grounding RAG still v0.2/v0.3/v0.4.

**Top remaining issue:** No real streaming UX. `OllamaProvider.stream_complete` and `LiteLLMProvider.stream_complete` raise `NotImplementedError("Streaming coming in v0.2")` when iterated. LangGraph Studio, CrewAI Canvas, OpenHands Web UI, Pydantic AI's FastAPI integration all let users watch an agent think with real models. ARNES gives a markdown bitácora after the fact — a real differentiator for audits, but a regression for live UX. The single largest AI-layer gap.

**Verdict:** **GO** for public alpha (with explicit "no live streaming UX" caveat in release notes).

---

### Marketing (10 dimensions)

| #  | Dimension                | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|--------------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | README quality           | 50 | 72 | 80 | 88 | **88** | 0 | 541 lines, bilingual EN/ES, real terminal output, honest "Known Limitations" section. Preserved. |
| 2  | Description & topics     | 70 | 80 | 82 | 82 | **82** | 0 | 20 keywords in `pyproject.toml`. Preserved. |
| 3  | Visual identity          | 55 | 65 | 72 | 74 | **74** | 0 | `docs/social-card.png` + `docs/logo.svg` preserved. No demo GIF committed. No architecture diagram. |
| 4  | Narrative & positioning  | 80 | 88 | 92 | 92 | **92** | 0 | "Control the agent. Don't worship it." Manifesto best-in-class. At ceiling. |
| 5  | Contributor experience   | 60 | 75 | 82 | 86 | **85** | -1 | `AGENTS.md` claims to have fixed the Thread-immutability contradiction (R5 fix #4) but the file is unchanged. A contributor reading AGENTS.md will write code expecting immutability — actively misleading. |
| 6  | Documentation completeness | 50 | 65 | 68 | 70 | **72** | +2 | `CHANGELOG.md` Unreleased section is now comprehensive (~40 items, Added/Changed/Fixed in Round 4). Real improvement. Slight knock: rounds not distinguished (all labeled "Round 4"). |
| 7  | Community infrastructure | 55 | 75 | 78 | 80 | **80** | 0 | Issue templates, PR template, FUNDING.yml, CODE_OF_CONDUCT.md, CONTRIBUTING.md preserved. Discord "coming soon." |
| 8  | Release readiness        | 60 | 75 | 84 | 90 | **91** | +1 | CHANGELOG comprehensive + sentinel filter for cleaner Python API + error_type for clearer failures all improve the "is this safe to ship?" story. |
| 9  | Social proof             | 20 | 20 | 25 | 25 | **25** | 0 | Not yet public (or 0 stars / 0 forks). Star History chart renders empty. |
| 10 | Viral potential          | 60 | 70 | 78 | 80 | **80** | 0 | Social card + manifesto + `scripts/demo.sh --record` preserved. Still no actual GIF embedded in README. |
|    | **Overall**              | 64 | 72 | 76 | 80 | **81** | **+1** | |

**Top remaining issue:** No demo GIF embedded in the README. `scripts/demo.sh` supports `--record demo.tape` for `vhs`, but no `docs/demo.gif` is committed. A 30–60s terminal recording of `arnes run manuals/audit-pr.yaml --mock` producing a bitácora, embedded at the top of the README, would be the single highest-leverage viral asset. LangChain, CrewAI, OpenHands all have rich demo assets.

**Verdict:** **GO** for public alpha.

---

### Competitive (10 dimensions)

| #  | Dimension                    | R1 | R2 | R3 | R4 | **R5** | Δ(R4→R5) | Notes |
|----|------------------------------|---:|---:|---:|---:|-------:|---------:|-------|
| 1  | Feature completeness vs top 10 | 40 | 48 | 56 | 60 | **60** | 0 | No new competitive features in R5. Streaming, multi-agent, memory, docs site all still roadmap. |
| 2  | Code quality vs top 10       | 65 | 72 | 78 | 84 | **85** | +1 | Sentinel filter + error_type field both close small API-hygiene gaps that matter for adopters writing Python code against ARNES. |
| 3  | README and positioning       | 70 | 78 | 84 | 88 | **88** | 0 | Preserved. |
| 4  | Documentation completeness   | 35 | 42 | 44 | 50 | **52** | +2 | `CHANGELOG.md` Unreleased section is genuinely comprehensive — closes one of the two R4 competitive doc gaps. (Docs site still missing.) |
| 5  | Examples and playbooks       | 60 | 65 | 68 | 68 | **68** | 0 | 10 manuals + 4 examples preserved. |
| 6  | Unique value proposition     | 80 | 82 | 84 | 86 | **86** | 0 | Manifesto + manual-is-code + bitácora + CostGuard killer differentiators preserved. |
| 7  | Market timing                | 70 | 72 | 75 | 75 | **75** | 0 | MCP wave + agent-harness zeitgeist preserved. |
| 8  | Production readiness vs top 10 | 40 | 48 | 52 | 64 | **65** | +1 | Cleaner Python API (sentinel filter + error_type) marginally improves production readiness. No streaming, no memory, no multi-agent still block real production use. |
| 9  | Community building potential | 55 | 60 | 62 | 64 | **64** | 0 | Apache 2.0, CONTRIBUTING.md, issue templates preserved. Not yet public. |
| 10 | Overall competitive position | 48 | 55 | 62 | 68 | **68** | 0 | ARNES is "interesting thesis, competitive execution on the dimensions it chose to compete on, with a hardened supply chain and a shippable sandbox" — preserved from R4. |
|    | **Overall**                  | 55 | 62 | 68 | 72 | **73** | **+1** | |

**Top remaining issue:** No real streaming / live UX — still the largest competitive gap. LangGraph Studio, CrewAI Canvas, OpenHands Web UI, Pydantic AI's FastAPI integration all let users watch an agent think with real models. ARNES's markdown bitácora is a real differentiator for *audits*, but a regression for *live UX*. The streaming API contract is on the ABC (forward-compatible), but `OllamaProvider.stream_complete` and `LiteLLMProvider.stream_complete` raise `NotImplementedError` when iterated. Closing this in v0.2 is the single highest-leverage competitive move.

**Verdict:** **GO** for public alpha (positioned as "the typed, tested, auditable agent harness for developers who refuse to cede control").

---

## 2. R1 → R5 Progression Table

| Category      | R1 | R2 | R3 | R4 | **R5** | Δ(R1→R5) | Δ(R4→R5) | Verdict            |
|---------------|---:|---:|---:|---:|-------:|---------:|---------:|--------------------|
| Security      | 57 | 70 | 78 | 82 | **83** | +26      | +1       | GO (alpha)         |
| Development   | 69 | 80 | 83 | 87 | **88** | +19      | +1       | GO (alpha)         |
| Data          | 63 | 76 | 79 | 81 | **83** | +20      | +2       | GO (alpha)         |
| AI            | 50 | 67 | 73 | 75 | **75** | +25      | 0        | GO (alpha, caveats)|
| Marketing     | 64 | 72 | 76 | 80 | **81** | +17      | +1       | GO (alpha)         |
| Competitive   | 55 | 62 | 68 | 72 | **73** | +18      | +1       | GO (alpha)         |
| **Average**   | **59.7** | **71.2** | **76.2** | **79.5** | **80.5** | **+20.8** | **+1.0** | — |

---

## 3. Top Issue Per Category (if any remain)

| Category    | Top remaining issue | Severity | Fix effort |
|-------------|---------------------|----------|------------|
| Security    | `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing. Secondary: `AGENTS.md:13` "immutable" claim still contradicts `thread.py:13` — *claimed fixed in R5, actually not.* | Medium / Low | 30 min (OIDC migration) / 5 min (AGENTS.md edit) |
| Development | `AGENTS.md:13` "Thread: immutable" — claimed fixed in R5 but the file is unchanged. A false fix claim is the single biggest maintainability hazard: contributors will trust the claim and write code expecting immutability. Secondary: `TokenOptimizer._cache` mutation has no `asyncio.Lock` (R4 Dev Top Issue #2, not addressed in R5). | Low / Medium | 5 min / 30 min (lock + tests) |
| Data        | Cache is still in-memory only — `TokenOptimizer._cache: dict[str, CacheEntry] = {}` with no persistence across runs and no Redis/disk backend. A long-running MCP server loses all cache state on restart. | Medium | 1–2 days (CacheBackend protocol + InMemory + Redis impl) |
| AI          | No real streaming UX. `OllamaProvider.stream_complete` and `LiteLLMProvider.stream_complete` raise `NotImplementedError("Streaming coming in v0.2")`. LangGraph Studio / CrewAI Canvas / OpenHands Web UI / Pydantic AI FastAPI all let users watch an agent think with real models. ARNES gives a markdown bitácora after the fact. | High | 2–3 days (Ollama /api/chat stream + LiteLLM acompletion stream + middleware wiring) |
| Marketing   | No demo GIF embedded in the README. `scripts/demo.sh --record demo.tape && vhs demo.tape` is one command away from producing `docs/demo.gif`. Single highest-leverage viral asset. | Medium | 30 min |
| Competitive | No real streaming / live UX (same as AI Top Issue). The single largest competitive gap. Secondary: no multi-agent coordination (v0.4 Crews roadmap) and no docs site. | High | 2–3 days (streaming) / weeks (crews) / days (docs site) |

---

## 4. Final GO/NO-GO Verdict Per Category

| Category    | Verdict                | Rationale |
|-------------|------------------------|-----------|
| Security    | **GO** (public alpha)  | Sandbox image ships, CI/CD supply chain hardened (SHA-pinned, blocking pip-audit, CodeQL), SSRF/path-traversal/HITL/CostGuard all working. Not yet production-ready (no streaming budget enforcement, no memory, no multi-agent) but defensible for a public alpha targeted at trusted-input / dev-mode-only environments. |
| Development | **GO** (public alpha)  | `mypy --strict` clean on 36 source files, 207 tests passing, 72.95% coverage, `ruff`/`bandit` clean, async-correct, well-organized. R5 closes R4 Dev Top Issue #1 (`Harness.run` error_type). The AGENTS.md false-fix-claim is a real maintainability hazard but doesn't block alpha release — it's a 5-minute fix. |
| Data        | **GO** (public alpha)  | Bitácora is genuinely auditable (parallel branches with typed boundaries, cost thresholds, refusals, cache hits, model routing, assistant messages, run pauses). R5 closes R4 Data Top Issue #2 (sentinel keys no longer leak to Python consumers). Remaining gaps (in-memory cache, 5 dead event types, no SQLite backend) are typing/observability/persistence refinements, not blockers. |
| AI          | **GO** (public alpha, with caveats) | The AI layer genuinely works: ReAct loop on the default model, structured outputs with strong pydantic validation on all 5 specialists, anti-hallucination stack with no false positives, hierarchical CostGuard with hard-stop + HITL-pause, true parallel execution, streaming API contract (forward-compatible). Caveats: no real streaming UX for live models, no real-LLM integration tests, only 2 of 5 anti-hallucination layers implemented. |
| Marketing   | **GO** (public alpha)  | README is best-in-class, narrative is unique, CHANGELOG is now comprehensive. Single highest-leverage gap (demo GIF) is one `vhs` command away. |
| Competitive | **GO** (public alpha)  | ARNES is "interesting thesis, competitive execution on the dimensions it chose to compete on, with a hardened supply chain and a shippable sandbox." The competitive pitch is defensible: the only framework in the comparator set that ships (a) declarative YAML → DAG with true parallelism AND typed boundary events, (b) hierarchical CostGuard with both hard-stop and HITL-pause, (c) a markdown bitácora as a first-class audit artifact, (d) native MCP server, (e) `mypy --strict` clean, (f) anti-hallucination middleware stack, (g) shippable Docker sandbox, (h) SHA-pinned CI with blocking pip-audit + CodeQL. |

---

## 5. Overall Verdict: Did ARNES Reach 90/100?

**No.**

**Final scores:**
- Security: **83** / 100
- Development: **88** / 100
- Data: **83** / 100
- AI: **75** / 100
- Marketing: **81** / 100
- Competitive: **73** / 100

**Average: 80.5 / 100** (R4: 79.5 → R5: 80.5, +1.0 point)

**Did ARNES reach 90/100?** **No.** The average is 80.5, which is 9.5 points below the 90/100 bar. No single category reached 90 either (Development came closest at 88).

**Why R5 only moved +1.0 point on average:**
- R5 was a small-scope round (4 fixes), and only 2 of the 4 were cleanly applied (#1 sentinel filter, #2 error_type).
- 1 fix (#3 CHANGELOG) was partially applied — comprehensive content but rounds not distinguished.
- 1 fix (#4 AGENTS.md) was claimed but **not actually applied** — a false fix claim that introduces a small doc-honesty regression and a maintainability hazard. Three separate R4 judge reports (Security, Development, Marketing) had all flagged this same issue; the 5-minute edit is still missing.
- The R5 fixes that did land (#1 sentinel filter, #2 error_type) addressed Low-to-Medium severity items, not the High-severity items (streaming, multi-agent, real-LLM integration tests, OIDC publishing, in-memory cache, docs site) that would move scores by 5+ points each.

**What it would take to reach 90/100 average:**
1. Implement real streaming for `OllamaProvider` and `LiteLLMProvider` (closes AI Top Issue #1, Competitive Top Issue #1) — **+5 to +8 points across AI + Competitive**.
2. Add real-LLM integration tests with `vcrpy` cassettes (closes AI Top Issue #2) — **+2 to +3 points to AI**.
3. Add `asyncio.Lock` to `TokenOptimizer._cache` and a `CacheBackend` protocol with Redis impl (closes Dev Top Issue #2, Data Top Issue #1) — **+2 to +3 points across Dev + Data**.
4. Migrate `release.yml` to PyPI OIDC Trusted Publishing (closes Security Top Issue #1) — **+1 to +2 points to Security**.
5. Actually apply the AGENTS.md fix that was claimed in R5 (closes the false-fix-claim finding of this report) — **+1 point across Dev + Marketing + Security**.
6. Stand up a docs site (Mintlify or Docusaurus) (closes Marketing Top Issue #2, Competitive Top Issue #3) — **+2 to +4 points across Marketing + Competitive**.
7. Embed a demo GIF in the README (closes Marketing Top Issue #1) — **+1 to +2 points to Marketing**.

Closing items 1, 2, 3, 4, 5 alone would push the average to ~87–89. Adding item 6 (docs site) and item 7 (demo GIF) would clear 90.

**Release posture:** ARNES is **ready for public alpha release** as `0.1.0a1`. It is **not yet at the 90/100 "production-ready" bar**. The trajectory R1 (59.7) → R2 (71.2) → R3 (76.2) → R4 (79.5) → R5 (80.5) shows sustained, decelerating improvement: the easy wins are exhausted, and the remaining gaps (streaming, multi-agent, real-LLM tests, OIDC, docs site) require real engineering investment, not 5-minute edits.

**The single most actionable finding of this final round:** the R5 claim to fix `AGENTS.md:13` was **not actually applied**. This is a 5-minute edit that was claimed as done. Three R4 judge reports flagged it. Apply it before the next round.

---

*End of report. — JUDGE_FINAL_R5*
