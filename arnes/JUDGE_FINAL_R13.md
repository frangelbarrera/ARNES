# JUDGE_FINAL_R13 — ARNES Round 13 Evaluation (9-Judge Consolidated Panel)

**Auditor:** Combined 9-judge panel (Security, Development, Data, AI, Marketing, Competitive, Philosopher, Scientific Tester, Over-engineering)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Cycle:** Round 13 — verification round after the R12 Tier-2 feature sweep (executor split + benchmark suite + vcrpy cassettes)
**Trajectory (9-judge):** R11 85.4 → R12 87.6 → **R13 88.9**

---

## Method

Static re-review of all source under `arnes/` (9 158 LOC across 44 files — was 8 341 / 36 files in R12), all 279 tests under `tests/` (7 949 LOC — was 7 495 / 251 tests in R12), `examples/`, `manuals/`, `README.md` (547 lines, unchanged), `CHANGELOG.md` (unchanged since R11), `CITATION.cff`, `MANIFESTO.md`, `AGENTS.md`, `CONTRIBUTING.md`, `pyproject.toml`, `.github/workflows/`. Verified each R12 fix claim against the current tree, then scored all 9 categories on 10 dimensions each.

Gates re-run:

- `pytest tests/` → **279/279 pass** in 15.61 s, coverage **74.04 %** (65 % gate met; +0.79 pp vs R12 73.25 %)
- `mypy --strict arnes/` → **Success: 0 issues in 44 source files** (was 36 in R12 — +8 files from the executor split + benchmark suite)
- `ruff check arnes/` → **All checks passed** (2 deprecated ANN101/ANN102 warnings inert)
- `bandit -r arnes/ -c pyproject.toml` → **0 / 0 / 0 / 0** at Low / Medium / High / Undefined (B101 skipped by config — 8 assert_used hits are type-narrowing asserts after schema validation, not security-relevant)
- `arnes benchmark --seeds 2 --concurrent 2` → end-to-end clean, 10 playbooks × 2 seeds = 20 runs, 100 % success, p95 durations reported, JSON saved to `benchmark-results.json`
- `pytest tests/snapshot/ tests/test_benchmark.py -q` → 28/28 pass (11 cassette tests + 17 benchmark tests)

---

## 0. R12 Fix Verification (all 7 claimed fixes confirmed applied)

| # | R12 claimed fix | Verified | Notes |
|---|---|---|---|
| 1 | `executor.py` split into 4 modules (result.py, sandbox.py, template.py, events.py) — 1 145 → 1 015 lines | ✅ | All 4 helper modules exist: `result.py` (37 lines, `PlaybookRunResult`), `sandbox.py` (41 lines, `DEFAULT_SANDBOX_CONTAINER` + `_is_docker_available`), `template.py` (166 lines, `_TEMPLATE_RE` + `_resolve_input` / `_resolve_template` / `_resolve_expr`), `events.py` (65 lines, `_drain_middleware_events` + `_filter_internal_keys`). `executor.py` is now 1 015 lines (down 130). **Caveat**: the executor retains backwards-compat delegating wrappers as class methods (`_resolve_input`, `_resolve_template`, `_resolve_expr`, `_TEMPLATE_RE = _TEMPLATE_RE`) plus an `__all__` re-export list — the *logic* is split but the *file size* is only marginally reduced. The AGENTS.md 500-line rule is still violated. |
| 2 | Benchmark suite: `BenchmarkRunner` with multi-seed, concurrent, p95 metrics | ✅ | `arnes/benchmarks/runner.py` (473 lines) implements `BenchmarkRunner.run_suite(suite, seeds, concurrent)` with `asyncio.Semaphore` for concurrency, nearest-rank p95 (max-fallback for n<20), `PlaybookBenchmarkResult` / `PlaybookMetrics` / `BenchmarkResults` pydantic models. `BenchmarkSuite` is a `Protocol` (`runtime_checkable`). `BasicBenchmarkSuite` (`suites/basic.py`, 272 lines) runs all `manuals/*.yaml` with a deterministic `SeededMockLLMProvider`. |
| 3 | `arnes benchmark` CLI command | ✅ | `cli/main.py:312-398` — full CLI with `--seeds` (1-20), `--concurrent`, `--manuals-dir`, `--output` flags. Renders a rich `Table` to the terminal + writes JSON to `benchmark-results.json` (default). Verified end-to-end: 10 playbooks × 2 seeds × 2-way concurrent = 20 runs, 100 % success, ~3 ms avg, p95 reported per playbook. |
| 4 | VCRpy cassette infrastructure (11 tests + sample cassette) | ✅ | `tests/snapshot/test_litellm_cassette.py` (455 lines, 11 tests across 3 classes: `TestLiteLLMCassetteReplay`, `TestSpecialistWithCassette`, `TestCassetteSanity`) + `tests/snapshot/cassettes/test_planner_basic.yaml` (hand-authored OpenAI response). `_VCR` configured with `record_mode='none'`, `filter_headers=['authorization']`, `match_on=['method', 'uri']`. `test_cassette_has_no_real_api_key` defense-in-depth check. Autouse `_silence_litellm_logging_worker` fixture prevents `PytestUnraisableExceptionWarning` from litellm's background worker (well-engineered). |
| 5 | Inline imports hoisted in `agent.py` and `cli/main.py` | ✅ | `agent/agent.py:12` has top-level `import json` (was inline at lines 176, 307). `cli/main.py:23` has top-level `from datetime import datetime` (was inline at lines 254, 420). **Remaining** inline imports (cli/main.py:206 `from arnes import Harness, HarnessConfig`, cli/main.py:336-339 benchmark lazy-load, cli/main.py:554 streaming events) are intentional lazy-loading patterns for CLI startup-cost optimization — NOT the R12 finding. |
| 6 | Docstring honesty: retry/HITL marked as v0.2 | ✅ | `playbooks/executor.py:9-10` now reads "Retry execution: v0.2 (schemas defined)" and "HITL execution: v0.2 (schemas defined)". `schema.py:49-57` (`RetryPolicy`) and `schema.py:65-74` (`HITLGate`) both say "Schema defined; execution in v0.2. The executor currently does not read `step.retry` / `step.human_approval`". The R12 Security/Dev/Over-eng finding about the executor docstring overstating retry+HITL-gate execution is **closed**. |
| 7 | 279 tests (was 251, +28), mypy --strict clean (44 files), ruff clean, bandit clean | ✅ | All four gates re-verified above. +28 tests = 17 benchmark tests (`tests/test_benchmark.py`) + 11 cassette tests (`tests/snapshot/test_litellm_cassette.py`). Coverage 73.25 % → 74.04 % (+0.79 pp). mypy clean on 44 files (was 36). |

**All 7 R12 fix claims verified applied.** The R12 cycle delivered real Tier-2 leverage: the benchmark suite + vcrpy cassettes are net-new infrastructure, not just cleanup.

---

## 1. The 9 Judges — Dimension-by-Dimension Scoring

### Judge 1 — Security: **90 / 100** (R12: 89, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Input validation | 81 | Pydantic on every tool Args + every event + every config. **R13 improvement**: `BenchmarkRunner.run_suite` validates `seeds` (non-empty) + `concurrent` (≥1) + suite playbooks (non-empty) explicitly. **Preserved**: `ShellTool.Args.cwd` is still free-form `str` at `builtin.py:68` (no allowlist). |
| 2 | Secret handling | 93 | `_looks_like_secret` heuristic + filtered subprocess env + no API key storage. **R13 improvement**: vcrpy cassette test has `filter_headers=['authorization']` + a `test_cassette_has_no_real_api_key` defense-in-depth regex check (`sk-[A-Za-z0-9]{40,}`) — the cassette infrastructure is engineered to never leak a real key even if a maintainer accidentally records one. |
| 3 | Sandbox isolation | 90 | Docker Tier 1 auto-detect on PATH; `--security-opt=no-new-privileges`, `--cap-drop=ALL`, `--network=none`, `--read-only`, tmpfs `/workspace`; `ARNES_DEV_MODE=1` double-gate; `Dockerfile.sandbox` ships. **R13 note**: `BenchmarkRunner._run_single` correctly sets `sandbox_enabled=False` (benchmarks don't shell out). gVisor Tier 2 is v0.4. |
| 4 | SSRF | 94 | DNS resolution + ALL-IPs validation + IP pinning + Host header + SNI preservation + `follow_redirects=False` + cloud-metadata blocklist. Single-implementation (R12 dead-code removal preserved). Best-in-class. |
| 5 | Path traversal | 93 | `_validate_path` + symlink escape detection. MCP server centralises the policy in `_validate_playbook_path` shared by 3 entry points. **R13 note**: `BasicBenchmarkSuite._default_manuals_dir` uses `Path(__file__).resolve().parents[3] / "manuals"` — standard pattern, no traversal risk (the path is computed from `__file__`, not from user input). |
| 6 | Budget / DoS | 95 | Hierarchical CostGuard, temporal circuit breaker, pre-flight abort via `peek_cost`, hard-stop at 100 %, HITL pause at 95 %, `BudgetExceeded` separated from generic `Exception`. **R13 improvement**: `BenchmarkRunner` accepts a `playbook_timeout_s` parameter (defaults to None for mock, real-LLM suites should set it) — prevents a hung model stalling CI. Strongest dimension. |
| 7 | HITL | 87 | HITL as a typed tool, `argsFingerprint` rug-pull defense, auto-reject in non-interactive (fail-safe). Real interactive HITL (pause + resume via MCP transport) is v0.2. |
| 8 | MCP server | 88 | Path validation shared across 3 endpoints; bearer-token auth (constant-time `hmac.compare_digest`); per-IP sliding-window rate limiter (100 req/min); 1 MiB body cap; loopback-only binding when no token. Minimal HTTP transport (no SSE) is the gap. |
| 9 | CI / CD | 85 | 5 SHA-pinned actions; 3 OS × 3 Python matrix; blocking `bandit`; blocking `pip-audit` (1 documented ignore: PYSEC-2026-1845); CodeQL workflow. **Preserved R8→R13**: `release.yml:46` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (TODO at line 31 acknowledges). |
| 10 | Doc honesty | 93 | README "Known Limitations in v0.1 (Alpha)" is explicit. Every v0.2+ feature is marked 🚧 in the feature table. **R13 improvement**: the R12 finding that `executor.py:1-16` module docstring overstated retry+HITL-gate execution is **fixed** — the docstring now reads "Retry execution: v0.2 (schemas defined)" / "HITL execution: v0.2 (schemas defined)". **New minor finding**: `schema.py:8` module docstring still says "Each step has: id, specialist OR tool, input, conditionals, retry, HITL gate" — the class-level docstrings (`RetryPolicy`, `HITLGate`) are honest about v0.2, but the module-level summary still implies retry/HITL are first-class step attributes. Tiny gap. |

**Top issue (Security):** `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (preserved R8→R13). Secondary: `ShellTool.Args.cwd` free-form string (preserved R1→R13); `schema.py:8` module docstring slightly stale (says "retry, HITL gate" without v0.2 caveat — the class docstrings are honest, the module summary is not). **GO** for public alpha; not yet production-grade.

---

### Judge 2 — Development: **94 / 100** (R12: 93, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Code organisation | 86 | **R13 improvement**: `executor.py` logic extracted into 4 dedicated modules (`result.py`, `sandbox.py`, `template.py`, `events.py`) — each with a focused docstring explaining its responsibility. The `playbooks/` package now has 8 files (was 4) with clear separation. **Caveat**: `executor.py` is still 1 015 lines (only −130 from R12's 1 145) because the executor retains backwards-compat delegating wrappers as class methods + an `__all__` re-export list. The AGENTS.md 500-line rule is still violated. 5 more files over 500: `cli/main.py` 771 (was 656 — grew from the benchmark command), `specialists/base.py` 680, `tools/builtin.py` 664, `middleware/cost_guard.py` 611, `mcp/server.py` 533. |
| 2 | Type safety | 98 | `mypy --strict` clean on 44 files (was 36 in R12). `pydantic.mypy` plugin enabled. `init_typed = True`, `init_forbid_extra = True`. `BenchmarkSuite` is a `Protocol` with `@runtime_checkable` — clean duck-typing. `BenchmarkResults` / `PlaybookMetrics` / `PlaybookBenchmarkResult` are fully-typed pydantic models. |
| 3 | Error handling | 91 | **R13 improvement**: `BenchmarkRunner._run_single` wraps each playbook run in a `try/except Exception` so a single failure (compile error, specialist timeout, budget exceeded) doesn't abort the whole benchmark — the failure is recorded as `success=False` with `error=f"{type(e).__name__}: {e}"` and the run continues. Matches the semantics of `tests/stress/test_concurrent.py`. `run_suite` validates inputs (`seeds` non-empty, `concurrent` ≥1, suite has playbooks) with clear `ValueError`s. |
| 4 | Test coverage | 84 | 279 tests (was 251, +28), 74.04 % overall (R12 73.25 %, +0.79 pp). **R13 improvement**: +28 tests across benchmark (17) + cassette (11). `tests/test_benchmark.py` covers single-seed, multi-seed (statistical distinguishability assertion), concurrent (correctness + non-regression on speed), JSON round-trip, save/load round-trip. `tests/snapshot/test_litellm_cassette.py` covers replay (content/usage/cost extraction), end-to-end specialist invocation, cassette sanity (YAML validity, no real API key, 200 status, OpenAI endpoint target). **Preserved**: `tools/builtin.py` at 52 % (unchanged R12→R13). `playbooks/template.py` at 73 % — well-covered since the extraction. |
| 5 | Async correctness | 96 | `asyncio.Lock` for cache mutations, `asyncio.gather(..., return_exceptions=True)` for parallel branches, proper async generators. **R13 improvement**: `BenchmarkRunner.run_suite` uses `asyncio.Semaphore(concurrent)` correctly — the semaphore is shared across all (playbook × seed) tasks so `seeds=3, concurrent=2` runs 2 of N×3 at a time, not 2 per seed. The docstring is explicit about this. |
| 6 | API design | 89 | Clean public surface. `Harness` (simple) + `PlaybookExecutor` (advanced) + `BenchmarkRunner` (research). `BenchmarkSuite` Protocol enables custom suites without inheritance. **Preserved**: `Harness.stream()` returns `None` (silent) on missing specialist instead of a structured error. |
| 7 | Docs (code-level) | 92 | Google-style docstrings everywhere. Module docstrings explain the "why" (e.g. `benchmarks/runner.py:1-37` covers reproducibility + statistical-meaningfulness + concurrency goals before any code). **R13 improvement**: the executor split modules each have a focused docstring explaining what was extracted and why (SPLIT-R12 marker). `executor.py:1-28` now correctly points at the 4 helper modules. |
| 8 | CI / CD | 92 | 3×3 matrix, security job (bandit + pip-audit), build job, all SHA-pinned. Coverage gate at 65 % (currently 74 %, +9 pp headroom). `mypy --strict` is a hard gate. |
| 9 | Deps | 88 | Pinned with `<` upper bounds. LiteLLM universal adapter. Optional extras (ollama / anthropic / openai / mcp / dev). `vcrpy>=6.0,<9` correctly in the dev extra. One documented pip-audit ignore. |
| 10 | Maintainability | 85 | **R13 improvement**: inline `import json` x2 in agent.py + inline `from datetime import datetime` x2 in cli/main.py hoisted to top-level — the R12 finding is closed. `build_middleware_stack()` helper remains the single source of truth. **Preserved minor finding**: `_emit_stream_audit_event` (agent.py:367) + `_emit_assistant_message` (base.py:452) still duplicate the duck-typed `getattr(provider, "_events")` pattern — a candidate for a shared `_drain_event_to_sink(provider, event)` helper. |

**Top issue (Development):** `executor.py` is still 1 015 lines despite the R12 split — the *logic* was extracted into 4 modules but the *file* retained backwards-compat delegating wrappers + an `__all__` re-export list, so the line count barely dropped (1 145 → 1 015, −11 %). 5 more files over 500 lines (including `cli/main.py` which *grew* from 656 → 771 because the benchmark command was added). Secondary: `tools/builtin.py` at 52 % coverage (preserved R12→R13); `_emit_stream_audit_event` + `_emit_assistant_message` duplication. **GO** for public alpha — highest-scoring category, 2nd consecutive round ≥ 93.

---

### Judge 3 — Data: **90 / 100** (R12: 89, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Event log | 94 | 18 typed `EventType`s (unchanged). Immutable `Event` (frozen pydantic), `Thread` append-only with O(1) per append. Thread explicitly documented as not thread-safe — executor copies before sharing. |
| 2 | State management | 93 | Stateless reducer `_reduce_event(state, event) → state` is a pure function. **R13 improvement**: `BenchmarkRunner` is stateless between `run_suite` calls — each call returns an independent `BenchmarkResults`. The runner holds no mutable state across runs (only the constructor params `_budget_usd` / `_playbook_timeout_s`). |
| 3 | Observability | 91 | `structlog` everywhere. Middleware event sink drained by executor after each step. **R13 improvement**: `BenchmarkRunner._run_single` logs `benchmark_playbook_failed` with `playbook=path.name, seed=seed, error=str(e)` on failure — structured key=value fields, consistent with the rest of the codebase. |
| 4 | Audit trail | 90 | Bitácora on all 3 CLI paths. **Preserved R10→R13**: `arnes stream` bitácora is still hand-rolled markdown (`cli/main.py:259-271`), not `Thread.to_markdown()` — the R12 Data finding is unchanged. **R13 improvement**: `BenchmarkResults.to_markdown()` produces a clean table with per-playbook + overall metrics — a new auditable artifact for benchmark runs. |
| 5 | Data flow | 89 | YAML → `PlaybookCompiler` → `Playbook` → `PlaybookExecutor` → `Specialist.run` → middleware → `LLMProvider`. **R13 improvement**: the benchmark data flow is `Playbook → BenchmarkRunner.run_suite → _run_single → PlaybookExecutor.run → PlaybookRunResult → PlaybookBenchmarkResult → PlaybookMetrics → BenchmarkResults`. Every hop is typed; per-seed results are retained in `per_seed_results` for forensic inspection. |
| 6 | Cache | 72 | `TokenOptimizer._cache` is in-memory only, process-local. LRU + TTL + `asyncio.Lock`. **Preserved R9→R13**: no `CacheBackend` protocol, no Redis impl — cache is lost on every MCP server restart. The benchmark runner doesn't help here (it doesn't persist anything between runs either, but that's by design — benchmarks are stateless). |
| 7 | Cost tracking | 95 | Hierarchical CostBudget, per-call tracking on `AssistantMessageEvent`, per-step aggregate on `StepCompletedEvent`, per-run total on `RunCompletedEvent`. **R13 improvement**: `BenchmarkResults` adds a per-playbook + overall `avg_cost_usd` field — cost is now first-class in benchmark reports (always $0 for the mock suite, but the field exists for real-LLM suites). |
| 8 | Performance | 89 | O(1) `Thread.append`, O(1) `deque` spend history, LRU cache, `asyncio.gather` for true parallelism. **R13 improvement**: `BenchmarkRunner` pre-compiles playbooks once (`compiled: list[tuple[Path, Playbook]]` before the seed loop) — compilation is deterministic and doesn't depend on the seed, so doing it N×M times would add noise to the duration measurement. Good experimental hygiene. |
| 9 | Validation | 92 | Pydantic v2 everywhere. **R13 improvement**: `BenchmarkResults.to_json()` uses `model_dump_json(indent=2)` with sorted keys (default pydantic behaviour) — two runs of the same benchmark with the same seed produce byte-identical JSON (modulo timestamps and wall-clock durations), enabling stable CI diffs. |
| 10 | Persistence | 80 | `Thread.save(path)` / `Thread.load(path)` exist but aren't invoked automatically. **R13 improvement**: `BenchmarkResults` can be saved/loaded via `save_results(results, path)` / `load_results(path)` — the JSON round-trip is tested (`TestSaveLoadResults.test_save_load_round_trip`). Cache is still not persisted. No SQLite/Postgres backend. |

**Top issue (Data):** Cache is in-memory only — no `CacheBackend` protocol + Redis impl (preserved R9→R13). Secondary: `arnes stream` bitácora is hand-rolled markdown, not `Thread.to_markdown()` (preserved R10→R13). **GO** for public alpha.

---

### Judge 4 — AI: **89 / 100** (R12: 87, Δ +2)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Specialist prompts | 90 | 5 specialists, each with detailed system prompt (role, job, rules, JSON schema, "respond with ONLY valid JSON"). Prompts are visible files on disk (manifesto #6). Unchanged. |
| 2 | ReAct loop | 84 | Implemented in `Specialist.run` with `max_iterations` default 5. **Preserved gap**: `Specialist.stream()` deliberately bypasses the ReAct loop (streaming is read-only / generation only) — the R12 AI top issue is unchanged. |
| 3 | Structured outputs | 93 | JSON-mode forcing, strong `pydantic_model` validation preferred over weak JSON-schema check, `_clean_json_response` strips fences. **R13 improvement**: `TestSpecialistWithCassette.test_planner_specialist_invoked_with_recorded_response` proves the full chain `specialist → middleware → LiteLLMProvider → litellm → httpx → vcrpy → cassette` produces a `@planner` result that validates against `PlannerOutput` — structured output validation now has a real-LLM-shape test, not just mock tests. |
| 4 | Tool use | 85 | 5 built-in tools (shell, http, fs_read, fs_write, human_approval) with SSRF + path traversal + symlink escape + dangerous-command defenses. Tool registry + ReAct loop. |
| 5 | Streaming | 88 | 5-layer streaming (Provider → TokenOptimizer → VerificationLayer → CostGuard → CLI/specialist). **R13 improvement**: `tests/snapshot/test_litellm_cassette.py` documents that vcrpy cassettes CAN record real streaming responses (the `SeededMockLLMProvider.stream_complete` yields the full response in one chunk; the pattern extends to real `LiteLLMProvider.stream_complete` cassettes). |
| 6 | Anti-hallucination | 87 | Refusal pattern (hedging detection forces "I don't know" over fabrication) + structured-output forcing. 3 of 5 verification layers (confidence gate, critic loop, grounding RAG) are v0.2+ placeholders. |
| 7 | Model routing | 90 | `TokenOptimizer._ROUTING_RULES` routes short no-tool inputs to `ollama/llama3.2` (free, local) or `anthropic/claude-3-5-haiku` (cheap). **R13 note**: the cassette test correctly disables routing (`enable_routing=False`) so the `@planner` call stays on `openai/gpt-4o` and hits the OpenAI cassette — the test author understood the routing-vs-cassette interaction. |
| 8 | Budget enforcement | 95 | Hierarchical CostGuard with circuit breaker + pre-flight abort + hard-stop + HITL pause. Strongest AI dimension. |
| 9 | Multi-agent | 80 | Single-agent default. Crew / A2A are v0.4/v0.5. Unchanged. |
| 10 | Real-LLM tests | 78 | **R13 improvement**: 1 vcrpy cassette (`test_planner_basic.yaml`) covers `LiteLLMProvider.complete()` against a recorded OpenAI response — usage extraction, cost calculation from local pricing table, raw response preservation, end-to-end specialist invocation. **Preserved gap**: only 1 cassette (1 provider, 1 specialist, 1 happy-path response). No cassettes for Anthropic / Ollama / streaming / error paths / tool-use responses. The pattern is established; comprehensive coverage is the next step. |

**Top issue (AI):** `Specialist.stream()` still bypasses the ReAct tool-use loop (streaming is read-only — unchanged R11→R13). Secondary: only 1 vcrpy cassette (need more providers, more specialists, error paths, tool-use responses); no SSE/AG-UI HTTP endpoint. **GO** for public alpha (caveat) — the vcrpy cassette closes the "no real-LLM tests" gap partially and establishes the pattern for full coverage.

---

### Judge 5 — Marketing: **91 / 100** (R12: 91, Δ 0)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | README | 92 | 547 lines (unchanged). Logo at top, badges, social-card OG/Twitter meta, "Why ARNES exists" narrative, YAML example, terminal output sample, bitácora sample, feature table with v0.1/v0.2/v0.3/v0.4 status, competitive comparison table, 12-factor-agents alignment, architecture diagram, roadmap, community, sponsors, license, citation section, acknowledgments, known limitations, demo-GIF recording instructions, star history. **R13 finding**: README feature table does NOT mention the benchmark suite, the `arnes benchmark` CLI command, or the vcrpy cassette infrastructure — three net-new R12 features are invisible to a README reader. The `arnes --help` output shows `benchmark` but the README's "Quickstart" and "Features" sections don't. |
| 2 | Description / topics | 90 | Crisp one-liner. 19 PyPI keywords. Unchanged. |
| 3 | Visual identity | 87 | Logo + social-card + ASCII art. **Preserved gap**: no demo GIF committed (the `vhs`/`agg` pipeline is documented but the asset isn't in the repo). |
| 4 | Narrative | 93 | Manifesto is powerful and unchanged. |
| 5 | Contributor experience | 90 | CONTRIBUTING.md, AGENTS.md, CODE_OF_CONDUCT.md, PR template, 2 issue templates, `good-first-issue` label, `.pre-commit-config.yaml`. Unchanged. |
| 6 | Docs | 84 | README + AGENTS + CONTRIBUTING + MANIFESTO + CHANGELOG + SECURITY + PUBLISHING_GUIDE + CITATION.cff + examples/README. **R13 finding**: CHANGELOG.md ends at R11 — there is NO "Added in Round 12" or "Added in Round 13" section. The 7 R12 fixes (executor split, benchmark suite, `arnes benchmark` CLI, vcrpy cassettes, inline imports hoisted, docstring honesty, +28 tests) are all undocumented in the CHANGELOG. This is a regression in the changelog discipline that R12 fixed for R10/R11. **Preserved gap**: no docs site, no API reference, no tutorials beyond 5 examples. |
| 7 | Community | 80 | GitHub Discussions, Sponsors section, Latam wedge narrative. **Preserved gap**: Discord "coming soon", no Twitter/X, no YouTube. |
| 8 | Release readiness | 80 | PUBLISHING_GUIDE.md, alpha honestly labeled. **R13 finding**: CHANGELOG R12/R13 sections missing (was added for R10/R11 in R12 — the discipline lapsed). **Preserved**: PyPI "not yet published" badge, no OIDC, no signed releases. |
| 9 | Social proof | 70 | Star history chart, acknowledgments. **Preserved gap**: no testimonials, no adoption logos, no conference talks, no blog posts (alpha — expected). |
| 10 | Viral potential | 89 | Manifesto is shareable. "ARNES vs the rest" comparison table. **R13 missed opportunity**: the benchmark suite + `arnes benchmark` CLI command is a gifable / shareable asset (deterministic, fast, no API spend) — but it's not in the README, not in the changelog, and there's no demo GIF of it. A `arnes benchmark --seeds 3 --concurrent 4` recording would be a strong viral asset. |

**Top issue (Marketing):** Three net-new R12 features (benchmark suite, `arnes benchmark` CLI, vcrpy cassette infrastructure) are shipped but NOT mentioned in the README feature table, the README Quickstart, or the CHANGELOG. This is a marketing-visibility gap — the work is done but the story isn't told. Secondary: no demo GIF (preserved R12→R13); CHANGELOG R12/R13 sections missing (regression in changelog discipline). **GO** for public alpha.

---

### Judge 6 — Competitive: **85 / 100** (R12: 84, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Feature completeness | 82 | 5 specialists (planned 12), 10 playbooks (planned 30-50), 9 CLI commands (was 8 — `benchmark` added), MCP server (4 tools), 5-layer streaming, CostGuard, VerificationLayer, TokenOptimizer. **R13 improvement**: `arnes benchmark` CLI command + `BenchmarkRunner` is a feature no major agent framework ships (LangChain / CrewAI / OpenAI Agents SDK / OpenHands / browser-use don't bundle a benchmark harness). v0.1 ships ~75 % of the v0.1.0 roadmap. |
| 2 | Code quality | 91 | `mypy --strict` clean (44 files), 279 tests, 74.04 % coverage, ruff clean, bandit 0/0/0/0. **R13 improvement**: executor split into 4 modules + benchmark suite is well-typed + well-tested (28 new tests). **Preserved**: 6 files over 500 lines; `tools/builtin.py` at 52 % coverage. |
| 3 | README | 92 | Best-in-class (see Judge 5). |
| 4 | Docs | 82 | Comprehensive but no docs site, no API reference. CITATION.cff is a plus. **R13 finding**: CHANGELOG missing R12/R13 sections. |
| 5 | Examples | 85 | 5 runnable example scripts + 10 playbook manuals + `examples/README.md`. **R13 missed opportunity**: no `examples/06_benchmark.py` showing how to use `BenchmarkRunner` programmatically — the API is documented in the runner docstring but not in an example. |
| 6 | Unique value | 91 | Declarative YAML → DAG with true parallelism + typed boundary events; hierarchical CostGuard with hard-stop AND HITL-pause AND streaming pre-flight abort; markdown bitácora on all CLI paths; native MCP server; `mypy --strict` clean; anti-hallucination middleware stack; shippable Docker sandbox; SHA-pinned CI; "no hosted version" manifesto declaration. **R13 improvement**: bundled `BenchmarkRunner` with multi-seed + concurrent + p95 + per-seed retention is genuinely novel — most agent frameworks make you bring your own eval harness. |
| 7 | Market timing | 88 | 2024-2026 agent-framework gap is real. MCP protocol gaining traction. Local-first ethos matches the "AI sovereignty" wave. Unchanged. |
| 8 | Production readiness | 71 | Alpha. PyPI not published. No OIDC. No memory. No multi-agent. No SSE/AG-UI. **R13 improvement**: vcrpy cassette infrastructure demonstrates that real-LLM integration testing is possible without API spend — a production-readiness signal for adopters evaluating the project. 1 cassette is a starting point, not comprehensive coverage. |
| 9 | Community potential | 80 | Manifesto resonates. Bilingual EN/ES. `good-first-issue` label. Apache 2.0. But: 0 external contributors, 0 stars (not yet public), Discord not live. |
| 10 | Overall position | 78 | Niche but differentiated. The benchmark suite + vcrpy cassettes reinforce the "ARNES takes testing/evaluation seriously" positioning — a credible signal vs LangChain/CrewAI which have larger ecosystems but weaker eval discipline. |

**Top issue (Competitive):** No end-user-facing live UX via a browser (LangGraph Studio / CrewAI Canvas / OpenHands Web UI all let users watch an agent think). ARNES streams via 5 layers but no SSE/AG-UI HTTP endpoint and no live UI. Secondary: PyPI not published; only 1 vcrpy cassette; CHANGELOG missing R12/R13 sections. **GO** for public alpha.

---

### Judge 7 — Philosopher: **87 / 100** (R12: 87, Δ 0)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Real problem? | 92 | Yes. Agent frameworks in 2024-2026 are black boxes, vendor-locked, and don't respect money. ARNES attacks all three. Unchanged. |
| 2 | Value proposition clarity | 95 | "Write the manual. ARNES compiles it into a team of specialists that follows it to the letter." + "The harness, not the horse." Crystal clear. |
| 3 | User benefit | 90 | Visible prompts, swappable models, budget enforcement, audit trail, local-first default. Unchanged. |
| 4 | Ethical considerations | 78 | "No hosted version" prevents lock-in. Local-first reduces vendor power. Bilingual EN/ES serves underserved Latam. HITL as a tool respects human agency. Anti-hallucination middleware. **Preserved gap**: no explicit AI-safety policy, no model-bias discussion, no content-moderation layer, no data-retention policy, no red-team documentation. **R13 note**: the benchmark suite could surface fairness/bias metrics (e.g. differential success rates across specialist prompts) but currently only tracks success/duration/tokens/cost — no equity dimensions. |
| 5 | Accessibility | 80 | Bilingual EN/ES. Local-first (Ollama) makes it free. Apache 2.0. **Preserved gap**: Python 3.11+ only; no JS/TS port; no GUI; no screen-reader CLI docs. |
| 6 | Long-term vision | 85 | 5-version roadmap. Manifesto is immutable. **Preserved gap**: no vision beyond v1.0. |
| 7 | Community values | 88 | Apache 2.0, CODE_OF_CONDUCT.md, `good-first-issue` label, Latam identity, Sponsors, Discussions. **Preserved gap**: no governance model. |
| 8 | Manifesto resonance | 90 | "Control the agent. Don't worship it." is a rallying cry. **Preserved gap**: the manifesto is more *reactive* (against existing frameworks' defects) than *constructive* (what world ARNES builds). |
| 9 | Target audience fit | 88 | Developers who want control, who prefer 50 lines they understand over 5 lines they don't. Clear. **Preserved gap**: may alienate developers who want magic/abstraction. |
| 10 | Problem-solution fit | 92 | The 3 problems map cleanly to 3 solutions. Unchanged. |

**Top issue (Philosopher):** Manifesto is reactive (anti-existing) not constructive (pro-future). Secondary: no explicit AI-safety/ethics policy (the benchmark suite could surface fairness metrics but doesn't). **GO** — strong philosophical foundation, reactive posture preserved R11→R13.

---

### Judge 8 — Scientific Tester: **87 / 100** (R12: 82, Δ +5)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Rigorous research use | 82 | **R13 improvement**: `BenchmarkRunner` is a real experiment runner — `seeds x playbooks` matrix, deterministic mock provider per seed, per-seed results retained for forensic inspection, JSON output with sorted keys for stable CI diffs. A researcher can run `arnes benchmark --seeds 5 --concurrent 4` and get a reproducible, statistically-meaningful result without paying for LLM calls. **Preserved gap**: no `ExperimentRunner` class with hypothesis tracking, no experiment-config schema, no comparison harness (`Experiment.compare(config_a, config_b)`). |
| 2 | Reproducibility | 89 | `Thread` is JSON-serializable. Events are immutable + timestamped. Mock LLM is deterministic per seed. **R13 improvement**: `SeededMockLLMProvider` is byte-reproducible — same seed + same playbook ⇒ same `tokens_in` / `tokens_out` / content (verified by `test_same_seed_produces_same_tokens_out`). Different seed ⇒ different `tokens_out` (verified by `test_different_seed_produces_different_tokens_out`). The seed is *proven* to propagate to the provider (verified by `test_multi_seed_tokens_out_differs_across_seeds` — at least 2 distinct values across 5 seeds). |
| 3 | Experiment control | 76 | `HarnessConfig` + `CostBudget` + `Playbook` YAML allow parameterization. **R13 improvement**: `BenchmarkRunner` adds `seeds`, `concurrent`, `budget_usd`, `playbook_timeout_s` parameters — the experimenter can now control statistical power (via seeds) and concurrency (via the semaphore) without writing custom code. **Preserved gap**: no hyperparameter sweep utility, no A/B comparison harness, no dataset loader. |
| 4 | Data integrity | 92 | Append-only `Thread`, immutable `Event`, `model_validator(mode="after")` for cross-field invariants. **R13 improvement**: `BenchmarkResults` is a pydantic model with `model_validate` round-trip tested (`test_json_serialisation_round_trips` + `test_save_load_round_trip`). Per-seed results are immutable once recorded. |
| 5 | Methodological soundness | 82 | Specialists are stateless; reducer is pure; HITL is fail-safe; budget is enforced. **R13 improvement**: `BenchmarkRunner` pre-compiles playbooks once (deterministic compilation shouldn't count toward per-seed duration measurement) — good experimental hygiene. **Preserved gap**: real-LLM calls are non-deterministic by default (temperature=0 mitigates); no formal verification of the reducer; no property-based testing (hypothesis). |
| 6 | Citation readiness | 73 | `CITATION.cff` (CFF 1.2.0). Apache 2.0, versioned, CHANGELOG maintained. **Preserved gap**: no DOI (CITATION.cff not registered on Zenodo), ORCID is still placeholder `0000-0000-0000-0000`, no archival on Software Heritage, no academic paper, no related-work section. A researcher can cite ARNES in BibTeX form via `cffconvert`, but a peer-reviewed paper still wants a DOI. |
| 7 | Benchmark support | 72 | **R13 improvement**: `BenchmarkRunner` + `BasicBenchmarkSuite` ship — this is a real benchmark *harness* with multi-seed / concurrent / p95 / per-seed retention. **But**: it runs against the 10 internal `manuals/*.yaml` playbooks with a deterministic mock LLM, NOT against standard suites (HumanEval, MBPP, SWE-bench, GAIA, AgentBench). It's a benchmark *harness* (you can plug in any suite via the `BenchmarkSuite` Protocol), not a benchmark *suite*. The harness is the harder part to build; the standard-suite integration is now a tractable next step. **Preserved gap**: no standard-suite integrations; no pass@k / F1 / EM / BLEU / cost-per-task / latency-percentile metrics beyond what `PlaybookBenchmarkResult` already captures. |
| 8 | Statistical rigor | 68 | **R13 improvement**: multi-seed runs are now first-class (`--seeds N`). `p95_duration_s` is computed via the nearest-rank method (ceil(0.95 × n) − 1) for n ≥ 20, with a documented max-fallback for n < 20. `success_rate` is a proper ratio. `avg_*` fields are means over per-seed results. **Preserved gap**: no confidence intervals, no significance tests (e.g. Mann-Whitney U for comparing two configurations), no effect-size reporting, no power analysis. A researcher running `--seeds 5` gets 5 numbers + a mean + a p95 — better than one number, but not a full statistical picture. |
| 9 | Peer-review readiness | 75 | README + docs are good. CITATION.cff is the academic-packaging baseline. **R13 improvement**: the benchmark runner is a credible artifact for a "we evaluated ARNES on N playbooks across M seeds" methodology section — it produces a stable JSON artifact that can be referenced in a paper. **Preserved gap**: no academic paper, no formal evaluation against baselines, no related-work section, no threat-to-validity discussion, no IRB/ethics-review documentation. |
| 10 | Documentation for academics | 80 | README has architecture; AGENTS.md has coding standards; CHANGELOG has version history; MANIFESTO has philosophy; CITATION.cff has citation metadata. **R13 improvement**: `benchmarks/runner.py:1-37` module docstring covers the design goals (reproducibility, statistical meaning, concurrency) and the usage example — a researcher can understand the harness without reading the implementation. **Preserved gap**: no methodology section, no experimental protocol, no "how to reproduce our results" guide, no data-sheet for the specialists. |
| 11 | (Bonus) Traceability | 92 | Every LLM call → `AssistantMessageEvent` with model/tokens/cost. Every step → `StepStartedEvent` + `StepCompletedEvent`. Every middleware decision → `CACHE_HIT` / `MODEL_ROUTED` / `REFUSAL_TRIGGERED` / `COST_THRESHOLD` / `RUN_PAUSED`. **R13 improvement**: every benchmark run → `BenchmarkResults` JSON with per-playbook + per-seed breakdown. ARNES's strongest research-grade dimension. |

**Top issue (Scientific Tester):** The benchmark *harness* is now shipped (multi-seed / concurrent / p95 / per-seed retention / stable JSON diffs) — this is the harder half of the R12 top issue. **But**: (a) no standard-suite integration (HumanEval / MBPP / SWE-bench / GAIA / AgentBench — the harness runs against 10 internal playbooks with a mock LLM); (b) no DOI (CITATION.cff not registered on Zenodo); (c) no statistical rigor beyond p95 (no CIs, no significance tests). **CONDITIONAL GO → GO (with caveats)** — the benchmark harness is sufficient for an alpha; standard-suite integration + DOI + statistical-rigor tooling are the path to a peer-review-ready artifact.

---

### Judge 9 — Over-engineering: **87 / 100** (R12: 86, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Code duplication | 88 | **R13 improvement**: inline `import json` x2 in agent.py + inline `from datetime import datetime` x2 in cli/main.py hoisted to top-level — the R12 finding is closed. **Preserved**: `_emit_stream_audit_event` (agent.py:367) + `_emit_assistant_message` (base.py:452) still duplicate the duck-typed `getattr(provider, "_events", None) + isinstance + append` pattern. **R13 new finding**: `executor.py` retains backwards-compat delegating wrappers as class methods (`_resolve_input`, `_resolve_template`, `_resolve_expr`, `_TEMPLATE_RE = _TEMPLATE_RE` class attribute) plus an `__all__` re-export list — the *logic* was extracted but the *indirection* was added. This is defensible (preserves the public API for `from arnes.playbooks.executor import X` and `unittest.mock.patch("arnes.playbooks.executor.X")` callers) but it means executor.py is still 1 015 lines instead of the ~600 the AGENTS.md rule would suggest. |
| 2 | Abstraction abuse | 85 | Mostly appropriate. Pydantic models are justified (data crosses boundaries). `LLMProvider` ABC is justified. **R13 improvement**: `BenchmarkSuite` is a `Protocol` with `@runtime_checkable` — duck-typed, no inheritance required. The shipped `BasicBenchmarkSuite` doesn't inherit from `BenchmarkSuite`; it just implements the protocol. Clean. |
| 3 | Premature optimization | 91 | `Thread.append` O(1) (justified). `asyncio.Lock` for cache (justified). `deque(maxlen=1000)` (justified). LRU eviction (justified). `asyncio.gather(return_exceptions=True)` (justified). **R13 improvement**: `BenchmarkRunner` pre-compiles playbooks once (justified — avoids N×M redundant compilations that would add noise to duration measurements). `asyncio.Semaphore(concurrent)` shared across all (playbook × seed) tasks (justified — correct concurrency semantics). |
| 4 | Dead code | 84 | **R13 improvement**: the R12 executor docstring honesty fix removes the schema-vs-emission drift — `RetryPolicy` and `HITLGate` schemas are now explicitly documented as v0.2 placeholders in both the schema class docstrings AND the executor module docstring. **Preserved**: `CostBudget.org_budget_usd` / `project_budget_usd` / `agent_budget_usd` fields exist but only `task_budget_usd` is set in practice (documented as hierarchical-but-unused). `VerificationConfig.confidence_gate` / `critic_loop` / `grounding_rag` are v0.2-v0.4 placeholders (documented). |
| 5 | Over-abstraction | 85 | `LLMProvider.peek_cost` with default `None` + duck-typed `getattr` in CostGuard is a reasonable hook. `CostBudget` has 7 fields but only `task_budget_usd` is used in practice. `VerificationConfig` has 6 fields, 3 are v0.2+ placeholders. **R13 note**: `BenchmarkRunner.__init__` takes 2 params (`budget_usd`, `playbook_timeout_s`) — lean, no over-abstraction. `BenchmarkResults` has 11 fields — all justified (suite_name, started_at, duration_s, total_runs, seeds, concurrent, 5 overall metrics, per_playbook list). |
| 6 | Redundant middleware | 95 | 3 middleware layers (CostGuard, VerificationLayer, TokenOptimizer) — all documented, all tested, no redundancy. `_arnes_wrapped` marker prevents double-wrapping. Unchanged. |
| 7 | Unnecessary indirection | 83 | **R13 improvement**: inline imports hoisted (closes the R12 finding). **R13 new finding**: `executor.py:962-1015` retains 3 delegating wrapper methods (`_resolve_input`, `_resolve_template`, `_resolve_expr`) + 1 class attribute (`_TEMPLATE_RE = _TEMPLATE_RE`) purely for backwards compat — documented as SPLIT-R12 preservation. The wrappers add ~54 lines of indirection. A cleaner split would have updated the 5 internal call sites to call the module-level functions directly and dropped the wrappers. **Preserved**: `_attach_serve_methods()` monkey-patch in `mcp/server.py:515-529`. |
| 8 | Config bloat | 75 | `CostBudget`: 7 fields (4 budget levels + 3 thresholds), only `task_budget_usd` used. `VerificationConfig`: 6 fields, 3 are v0.2+ placeholders. `HarnessConfig`: 5 fields (lean). `PlaybookStep`: 11 fields, 2 (`retry`, `human_approval`) are dead (executor never reads them — v0.2 placeholders, now honestly documented). `BenchmarkRunner.__init__`: 2 params (lean). `PlaybookBenchmarkResult`: 9 fields (all populated). The bloat is concentrated in `CostBudget` and `VerificationConfig` — preserved R11→R13. |
| 9 | Test over-engineering | 93 | 279 tests for 9 158 LOC = 1 test per 33 LOC. Reasonable ratio. **R13 improvement**: the 28 new tests (17 benchmark + 11 cassette) are well-targeted — they cover the new infrastructure without over-testing implementation details. `test_multi_seed_tokens_out_differs_across_seeds` is a particularly good test (asserts the seed is actually being applied, not silently dropped). The cassette tests include sanity checks (`test_cassette_has_no_real_api_key`, `test_cassette_response_is_200`, `test_cassette_targets_openai_endpoint`) — defence-in-depth, not over-engineering. |
| 10 | Docs bloat | 82 | 38 audit reports in `docs/audits/` are process artifacts (R1→R11 journey). README is 547 lines but well-organized. CHANGELOG is comprehensive through R11. **R13 finding**: CHANGELOG missing R12/R13 sections — the new features (benchmark, cassette, executor split) are documented in module docstrings but not in the user-facing CHANGELOG. This is under-documentation, not bloat. **Preserved gap**: the 38 audit reports could be moved to `docs/audits/archive/` to declutter. |

**Top issue (Over-engineering):** `executor.py` is still 1 015 lines despite the R12 split — the *logic* was extracted but backwards-compat delegating wrappers + `__all__` re-export list + the `_TEMPLATE_RE = _TEMPLATE_RE` class-attribute alias kept the file size nearly unchanged (1 145 → 1 015, −11 %). The split is a half-measure: real cognitive load dropped (the 4 helper modules are focused and self-documenting) but the AGENTS.md 500-line rule is still violated. Secondary: `_emit_stream_audit_event` + `_emit_assistant_message` duplication (preserved R12→R13); CHANGELOG missing R12/R13 sections (under-documentation, not over-engineering). **GO** — the codebase continues to get leaner; the executor split is the next leverage point.

---

## 2. Score Summary

| # | Judge | Score (R13) | Score (R12) | Δ R12→R13 | GO / NO-GO |
|---|---|---|---|---|---|
| 1 | Security | **90** | 89 | +1 | GO (public alpha) |
| 2 | Development | **94** | 93 | +1 | GO (public alpha) — highest category, 2nd consecutive round ≥ 93 |
| 3 | Data | **90** | 89 | +1 | GO (public alpha) |
| 4 | AI | **89** | 87 | +2 | GO (public alpha, caveat) |
| 5 | Marketing | **91** | 91 | 0 | GO (public alpha) — features shipped but not in README/CHANGELOG |
| 6 | Competitive | **85** | 84 | +1 | GO (public alpha) |
| 7 | Philosopher | **87** | 87 | 0 | GO (strong foundation, reactive posture) |
| 8 | Scientific Tester | **87** | 82 | +5 | **GO** (was CONDITIONAL GO in R12) — benchmark harness shipped |
| 9 | Over-engineering | **87** | 86 | +1 | GO |
| | **AVERAGE (9 judges)** | **88.9** | 87.6 | **+1.3** | — |
| | Average (6 original judges, comparable to R10/R11/R12) | **89.8** | 88.7 | +1.1 | — |

**The 9-judge average climbed from 87.6 → 88.9 (+1.3)**, driven by:
- **Scientific Tester +5** (biggest single gain — `BenchmarkRunner` ships with multi-seed / concurrent / p95 / per-seed retention, closing the harder half of the R12 top issue)
- **AI +2** (vcrpy cassette closes the "no real-LLM tests" gap partially and establishes the pattern)
- **Security +1, Development +1, Data +1, Competitive +1, Over-eng +1** (small gains from docstring honesty, inline imports hoisted, executor split, +28 tests, coverage +0.79 pp)
- **Marketing 0, Philosopher 0** (features shipped but not in README/CHANGELOG; no manifesto change, no AI-safety policy — preserved)

**R12 Scientific Tester CONDITIONAL GO is now upgraded to GO** (with caveats): the benchmark harness is sufficient for an alpha; standard-suite integration + DOI + statistical-rigor tooling remain as the path to peer-review readiness.

---

## 3. Top Issue Per Category

| Category | Top Issue | Severity | Effort |
|---|---|---|---|
| Security | `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (preserved R8→R13). Secondary: `ShellTool.Args.cwd` free-form string (preserved R1→R13); `schema.py:8` module docstring slightly stale. | Medium | 30 min (OIDC) + 30 min (cwd allowlist) + 5 min (schema docstring) |
| Development | `executor.py` is still 1 015 lines despite the R12 split — backwards-compat delegating wrappers + `__all__` re-export list kept the file size nearly unchanged (1 145 → 1 015, −11 %). 5 more files over 500 lines (`cli/main.py` 771 grew, `specialists/base.py` 680, `tools/builtin.py` 664, `middleware/cost_guard.py` 611, `mcp/server.py` 533). Secondary: `tools/builtin.py` at 52 % coverage; `_emit_stream_audit_event` + `_emit_assistant_message` duplication. | Medium-High | 1 day (finish the executor split — update 5 internal call sites, drop wrappers) + 1 day (cover builtin) + 20 min (extract `_drain_event_to_sink` helper) |
| Data | Cache is in-memory only — no `CacheBackend` protocol + Redis impl (preserved R9→R13). Secondary: `arnes stream` bitácora is hand-rolled markdown, not `Thread.to_markdown()` (preserved R10→R13). | Medium | 1-2 days (CacheBackend + Redis) + 30 min (switch CLI to `stream_with_audit` + `to_markdown`) |
| AI | `Specialist.stream()` bypasses the ReAct tool-use loop (streaming is read-only — preserved R11→R13). Secondary: only 1 vcrpy cassette (need more providers, specialists, error paths, tool-use responses); no SSE/AG-UI HTTP endpoint. | High | 2-3 days (wire streaming into ReAct) + 1 day (more cassettes) + 2-3 days (SSE) |
| Marketing | Three net-new R12 features (benchmark suite, `arnes benchmark` CLI, vcrpy cassette infrastructure) are shipped but NOT in README/CHANGELOG. Secondary: no demo GIF (preserved R12→R13); Discord "coming soon"; PyPI "not yet published". | Medium | 30 min (CHANGELOG R12/R13 sections) + 30 min (README feature table + Quickstart) + 30 min (demo GIF) |
| Competitive | No end-user-facing live UX via browser. Secondary: PyPI not published; only 1 vcrpy cassette. | High | 2-3 days (SSE + live UI) + 1 hour (PyPI publish after OIDC) |
| Philosopher | Manifesto is reactive (anti-existing) not constructive (pro-future). Secondary: no explicit AI-safety/ethics policy. | Medium | 1 day (constructive addendum) + 1 day (AI-safety policy) |
| Scientific Tester | No standard-suite integration (HumanEval / MBPP / SWE-bench / GAIA / AgentBench — the harness runs against 10 internal playbooks with a mock LLM). Secondary: no DOI (CITATION.cff not on Zenodo); no statistical rigor beyond p95 (no CIs, no significance tests). | High | 3-5 days (1-2 standard suites) + 30 min (Zenodo DOI) + 2-3 days (statistical tooling) |
| Over-engineering | `executor.py` still 1 015 lines (backwards-compat delegating wrappers + `__all__` re-export list kept the file size nearly unchanged). Secondary: `_emit_stream_audit_event` + `_emit_assistant_message` duplication; CHANGELOG missing R12/R13 sections. | Medium | 1 day (finish the executor split) + 20 min (extract helper) + 30 min (CHANGELOG) |

---

## 4. GO / NO-GO Verdict Per Category

| Category | Verdict | Rationale |
|---|---|---|
| Security | **GO** (public alpha) | All gates green. Sandbox auto-detects Docker, SSRF is single-implementation, path traversal + symlink escape covered, CostGuard enforces budget. R12 docstring honesty fix landed. R13 vcrpy cassette infrastructure adds defense-in-depth against accidental API-key leakage. Not yet production-grade (no OIDC, no gVisor Tier 2, `ShellTool.Args.cwd` free-form). |
| Development | **GO** (public alpha) — highest category, 2nd consecutive round ≥ 93 | `mypy --strict` clean (44 files), 279 tests, 74.04 % coverage, ruff clean, bandit 0/0/0/0. R12 fixes landed: executor split (4 modules), inline imports hoisted, docstring honesty, +28 tests. **Caveats**: `executor.py` still 1 015 lines (split is a half-measure), `tools/builtin.py` at 52 % coverage, `_emit_stream_audit_event` + `_emit_assistant_message` duplication. |
| Data | **GO** (public alpha) | Bitácora on all 3 CLI paths. Stateless reducer, append-only Thread (O(1)), hierarchical cost tracking. R13 adds `BenchmarkResults` (typed pydantic model with stable-JSON diffs). **Caveats**: cache in-memory only, `arnes stream` bitácora hand-rolled. |
| AI | **GO** (public alpha, caveat) | 5-layer streaming, structured outputs with pydantic validation, anti-hallucination stack (2 of 5 layers), hierarchical CostGuard, true parallel execution. R13 vcrpy cassette closes the "no real-LLM tests" gap partially (1 cassette for OpenAI @planner). **Caveats**: `Specialist.stream()` bypasses ReAct loop, no SSE/AG-UI, only 1 cassette. |
| Marketing | **GO** (public alpha) | README best-in-class, logo placed, narrative strong, contributor experience solid, examples + 10 playbooks, CITATION.cff. **Caveats**: 3 new R12 features not in README/CHANGELOG; no demo GIF; Discord not live; PyPI not published; no docs site. |
| Competitive | **GO** (public alpha) | Differentiated on control, auditability, local-first, budget enforcement, Latam identity. R13 benchmark suite + vcrpy cassettes reinforce the "ARNES takes eval seriously" positioning. **Caveats**: no live UX, only 1 cassette, PyPI not published, narrow feature breadth vs LangChain/CrewAI. |
| Philosopher | **GO** | Strong manifesto, clear value prop, real problem, ethical stance. **Caveats**: reactive posture, narrow audience, no explicit AI-safety policy. |
| Scientific Tester | **GO** (was CONDITIONAL GO in R12) | R13 ships `BenchmarkRunner` with multi-seed / concurrent / p95 / per-seed retention — the harder half of the R12 top issue. Excellent traceability + data integrity + reproducibility foundation. **Caveats**: no standard-suite integration (HumanEval/MBPP/SWE-bench/GAIA), no DOI (CITATION.cff not on Zenodo), no statistical rigor beyond p95 (no CIs, no significance tests). A researcher can now run a reproducible, statistically-meaningful benchmark without writing custom code; they still cannot run a standardised evaluation. |
| Over-engineering | **GO** | R12 fixes landed cleanly. Codebase continues to get leaner: inline imports hoisted, executor logic extracted, docstring honesty closed the schema-vs-execution drift. **Caveats**: `executor.py` still 1 015 lines (split is a half-measure — wrappers retained for backwards compat); `_emit_stream_audit_event` + `_emit_assistant_message` duplication. |

**All 9 categories are GO. No NO-GOs.** The R12 Scientific Tester CONDITIONAL GO is upgraded to GO (with caveats). This is the cleanest state ARNES has ever been in.

---

## 5. Is 95 / 100 Reached?

**No.** 9-judge average is **88.9 / 100** — still **6.1 points below 95**.

**Distance to 95:**
- Currently at 800 / 900 across 9 judges.
- Need 855 / 900 to reach 95 average.
- Need **+55 points across 9 judges = avg +6.1 per judge**.
- Or alternatively: need **+36 points across the 6 original judges = avg +6.0 per judge** to reach 95 on the 6-judge panel (currently 539 / 600).

**The path to 95/100 (ordered by leverage, with R13 starting point 88.9):**

### Tier 1 — Quick wins (3-4 hours, +3 to +5 average)
1. **Add CHANGELOG R12/R13 sections** documenting the executor split, benchmark suite, `arnes benchmark` CLI, vcrpy cassettes, inline imports hoisted, docstring honesty, +28 tests. → Marketing +1, Competitive +1, Over-eng +1. **~30 min.**
2. **Add benchmark row to README feature table + Quickstart example** (`arnes benchmark --seeds 3 --concurrent 4`). → Marketing +1, Competitive +1. **~30 min.**
3. **Migrate `release.yml` to PyPI OIDC Trusted Publishing** (preserved R8→R13). → Security +2. **~30 min.**
4. **Add `cwd` allowlist to `ShellTool.Args`** (or validate against the sandbox workspace root). → Security +1. **~30 min.**
5. **Fix `schema.py:8` module docstring** to add the v0.2 caveat on retry/HITL (the class docstrings are honest, the module summary isn't). → Security +1, Over-eng +1. **~5 min.**
6. **Register CITATION.cff on Zenodo for a DOI** + replace ORCID placeholder. → Scientific +3, Marketing +1, Competitive +1. **~30 min + Zenodo wait.**
7. **Embed a `vhs`-recorded `docs/demo.gif`** in the README (include a `arnes benchmark` recording). → Marketing +2, Competitive +1. **~30 min.**
8. **Extract `_drain_event_to_sink(provider, event)` helper** to consolidate `_emit_stream_audit_event` + `_emit_assistant_message` duplication. → Over-eng +1, Dev +1. **~20 min.**
9. **Move 38 audit reports to `docs/audits/archive/`** to declutter. → Over-eng +1. **~10 min.**
10. **Switch `arnes stream` CLI bitácora to `Thread.to_markdown()`** via `Harness.stream_with_audit()`. → Data +1, Dev +1. **~30 min.**

**Tier 1 total: ~3-4 hours of work, +5 to +8 average points.** Brings 9-judge average from 88.9 → ~91-93.

### Tier 2 — Multi-day features (1-2 weeks, +3 to +5 average)
11. **Finish the `executor.py` split** — update the 5 internal call sites to call the module-level functions directly, drop the backwards-compat delegating wrappers + `_TEMPLATE_RE = _TEMPLATE_RE` class attribute + the `__all__` re-export list. File should drop from 1 015 → ~600 lines. → Dev +2, Over-eng +2. **1 day.**
12. **Cover `tools/builtin.py`** (52 % → 85 %). → Dev +2. **1 day.**
13. **Add more vcrpy cassettes** — Anthropic / Ollama providers, `@coder` / `@reviewer` / `@tester` / `@debugger` specialists, error paths (4xx, 5xx, timeout), tool-use responses. → AI +2, Competitive +1, Scientific +1. **1-2 days.**
14. **Wire streaming into the ReAct tool-use loop** (`Specialist.stream()` should support tool calls). → AI +3. **2-3 days.**
15. **Add SSE/AG-UI HTTP endpoint on the MCP server + a minimal live UI**. → AI +2, Competitive +3. **2-3 days.**
16. **Add a `CacheBackend` protocol + Redis impl**. → Data +3. **1-2 days.**
17. **Publish to PyPI** (after OIDC migration). → Marketing +2, Competitive +2. **1 hour + review wait.**
18. **Add 1-2 standard benchmark suites** (HumanEval for code, GAIA for general agents) as `BenchmarkSuite` implementations. → Scientific +4, Competitive +2. **3-5 days.**

**Tier 2 total: ~2 weeks, +6 to +10 average points.** Brings 9-judge average from ~92 → ~94-95.

### Tier 3 — Research-grade + philosophical depth (2-4 weeks, +2 to +4 average)
19. **Add statistical rigor tooling** (multiple-seed runner with CIs, significance tests like Mann-Whitney U, effect-size reporting, power analysis). → Scientific +3. **2-3 days.**
20. **Write a constructive manifesto addendum** ("What world ARNES builds"). → Philosopher +3. **1 day.**
21. **Add an AI-safety / ethics policy** (content moderation opt-in, data retention defaults, model-bias disclosure template, fairness metrics in the benchmark harness). → Philosopher +3, Scientific +1. **1-2 days.**
22. **Stand up a docs site** (MkDocs Material with API reference generated from docstrings). → Marketing +2, Competitive +1. **1-2 days.**
23. **Write a peer-review-ready methodology paper** + threat-to-validity discussion + related-work section. → Scientific +3, Marketing +1. **1-2 weeks.**

**Tier 3 total: ~2-4 weeks, +5 to +8 average points.** Brings 9-judge average from ~95 → ~96-97. **Solidly crosses 95/100 on the 9-judge panel.**

### Realistic timeline to 95/100
- **Tier 1 alone (3-4 hours)**: 88.9 → ~91-93 (9-judge). Crosses 93 on the 6-judge panel.
- **Tier 1 + Tier 2 (~2 weeks)**: ~92 → ~94-95 (9-judge). Crosses 95 on the 6-judge panel; touches 95 on the 9-judge panel.
- **Tier 1 + Tier 2 + Tier 3 (~4-6 weeks)**: ~95 → ~96-97 (9-judge). **Solidly reaches 95/100 on the 9-judge panel.**

**The single highest-leverage next action**: a **3-4 hour sweep** — add CHANGELOG R12/R13 sections + add benchmark to README feature table + migrate to OIDC + add `cwd` allowlist + fix `schema.py:8` docstring + register Zenodo DOI + record demo GIF (including a `arnes benchmark` clip) + extract `_drain_event_to_sink` helper + archive old audits + switch `arnes stream` to `Thread.to_markdown()`. This would bring the 9-judge average from 88.9 to ~91-93 and the 6-judge average from 89.8 to ~93-94.

---

## 6. Final Assessment

**Trajectory (9-judge):** R11 (85.4) → R12 (87.6) → **R13 (88.9)**.
**Trajectory (6-judge comparable):** R10 (86.8) → R11 (87.7) → R12 (88.7) → **R13 (89.8)**.

**Honest characterization of R13:**
- ✅ **All 7 R12 fix claims verified applied** — executor split into 4 modules (`result.py`, `sandbox.py`, `template.py`, `events.py`); `BenchmarkRunner` with multi-seed / concurrent / p95; `arnes benchmark` CLI command works end-to-end; 11 vcrpy cassette tests + sample cassette; inline imports hoisted in `agent.py` + `cli/main.py`; docstring honesty (retry/HITL marked as v0.2); 279 tests, mypy --strict clean (44 files), ruff clean, bandit clean (with B101 skip in config).
- ✅ **All quality gates green** — 279/279 tests pass, `mypy --strict` clean (44 files), `ruff` clean, `bandit -c pyproject.toml` 0/0/0/0, coverage 74.04 % (+0.79 pp).
- ✅ **R12 Scientific Tester CONDITIONAL GO upgraded to GO** (with caveats) — 82 → 87. The benchmark harness is the harder half of the R12 top issue; standard-suite integration + DOI + statistical rigor remain.
- ✅ **7 of 9 judges improved** (Security +1, Development +1, Data +1, AI +2, Competitive +1, Scientific +5, Over-eng +1). The other 2 (Marketing, Philosopher) preserved.
- ⚠️ **`executor.py` still 1 015 lines** (was 1 145 in R12) — the split extracted the *logic* into 4 modules but retained backwards-compat delegating wrappers + `__all__` re-export list, so the file size only dropped 11 %. The AGENTS.md 500-line rule is still violated by 6 files. This is now the top Dev + top Over-eng issue.
- ⚠️ **`Specialist.stream()` still bypasses ReAct loop** (unchanged R11→R13). Top AI issue.
- ⚠️ **Cache still in-memory only** (no `CacheBackend` + Redis; unchanged R9→R13). Top Data issue.
- ⚠️ **No standard-suite integration** (HumanEval / MBPP / SWE-bench / GAIA / AgentBench — the harness runs against 10 internal playbooks with a mock LLM) + no DOI (CITATION.cff not on Zenodo). Top Scientific issue.
- ⚠️ **Manifesto still reactive** + no AI-safety policy (unchanged). Top Philosopher issue.
- ⚠️ **`release.yml` still uses long-lived `PYPI_API_TOKEN`** (preserved R8→R13). Top Security issue.
- ⚠️ **`arnes stream` bitácora still hand-rolled markdown** (not `Thread.to_markdown()`). Secondary Data issue.
- ⚠️ **Marketing regression**: 3 net-new R12 features (benchmark suite, `arnes benchmark` CLI, vcrpy cassette infrastructure) are shipped but NOT in README feature table, README Quickstart, or CHANGELOG. The CHANGELOG ends at R11 — the R12/R13 sections are missing (the same discipline R12 fixed for R10/R11 has lapsed). Marketing score preserved at 91 because the underlying README/narrative/logo quality is unchanged at high quality, but the visibility gap is real.
- ⚠️ **Only 1 vcrpy cassette** — `test_planner_basic.yaml` covers OpenAI + `@planner` + happy-path 200 response. No cassettes for Anthropic / Ollama, no `@coder` / `@reviewer` / `@tester` / `@debugger` cassettes, no error paths, no tool-use responses, no streaming cassettes. The pattern is established; comprehensive coverage is the next step.

**Bottom line:** R13 is a feature round that delivers real Tier-2 leverage — the benchmark harness is the most consequential single addition since the v0.1.0a1 release (it converts ARNES from "a tool you can use" to "a tool you can evaluate"). The 9-judge average climbs from 87.6 → 88.9 (+1.3), driven overwhelmingly by the Scientific Tester recovery (+5, CONDITIONAL GO → GO) and the AI partial recovery (+2, vcrpy cassette). **All 9 categories are GO** — no NO-GOs, no CONDITIONAL GOs. The path to 95/100 is now a 4-6 week effort (Tier 1 + Tier 2 + Tier 3 above) — with Tier 1 (3-4 hours) delivering +3 to +5 average points and crossing 91 on the 9-judge panel.

**Final GO/NO-GO: GO for public alpha release as `0.1.0a1` on all 9 dimensions.** The R12 Scientific Tester CONDITIONAL GO is upgraded to GO (with standard-suite + DOI caveats for v0.2). ARNES at R13 is the cleanest pre-public-release state in the project's history, and now has the benchmark infrastructure to *prove* its claims.

---

*End of report. — JUDGE_FINAL_R13 (9-judge consolidated panel)*
