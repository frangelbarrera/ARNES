# JUDGE_FINAL_R11 — ARNES Round 11 Evaluation (9-Judge Consolidated Panel)

**Auditor:** Combined 9-judge panel (6 prior + 3 new: Philosopher, Scientific Tester, Over-Engineering Auditor)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Cycle:** Round 11 — first evaluation under the expanded 9-judge panel
**Prior 6-judge scores:** R1 59.7 → R2 71.2 → R3 76.2 → R4 79.5 → R5 80.5 → R6 82.0 → R7 83.3 → R8 84.0 → R9 86.3 → R10 86.8

---

## Method

Static re-review of all source under `arnes/` (8 353 LOC across 36 files), all 251 tests under `tests/`, `examples/`, `manuals/`, `README.md`, `CHANGELOG.md`, `MANIFESTO.md`, `AGENTS.md`, `CONTRIBUTING.md`, `pyproject.toml`, `.github/workflows/`, plus the 3 new judge lenses (philosophy, research-grade rigor, over-engineering/debt). Ran:

- `pytest tests/` → **251/251 pass** in 13.05s, coverage **72.63 %** (65 % gate met)
- `mypy --strict arnes/` → **Success: 0 issues in 36 source files**
- `ruff check arnes/` → **All checks passed** (clean; 2 deprecated rules ANN101/ANN102 warned but inert)
- `bandit -r arnes/ -c pyproject.toml` → **0 / 0 / 0 / 0** at Low / Medium / High / Undefined
- `arnes stream @planner --task "Plan a tweet" --mock` → **single LLM call**, writes `bitacora-stream-planner-<ts>.md` (R10 double-call bug **confirmed fixed**: `arnes/cli/main.py:236` iterates `harness.stream()` once; `chunks_list` is collected during that single pass; the bitácora is built from `chunks_list`, not from a second call)
- `arnes run manuals/hello-world.yaml --mock` → end-to-end clean, bitácora persisted
- `arnes --help` → all 8 commands present (run, ejecutar, init, list, lint, stream, eval, mcp)
- Verified repo reorg: `docs/audits/` consolidates 35 historical reports; root is clean
- Verified logo: `docs/logo.svg` rendered at `width="120"` centered at top of README (line 19)

**Direct probes performed:**
- `rg "_arnes_wrapped" arnes/` → middleware-wrapping pattern duplicated in **5 places** (`Harness.run`, `Harness.stream`, `Harness._stream_into_thread`, `Specialist.run`, `Specialist.stream`)
- `rg "_check_ssrf\b" arnes/ tests/` → sync fallback defined at `tools/builtin.py:671`, **never called** by production code or tests (dead code; flagged in every prior security audit R1→R10)
- `rg "EventUnion|RUN_STARTED|COST_LIMIT_EXCEEDED|CONTEXT_COMPACTED|CONFIDENCE_SCORED" arnes/` → defined but **never instantiated** (5 dead enum/union members)
- `rg "HITLGate|RetryPolicy" arnes/playbooks/executor.py` → schemas defined in `playbooks/schema.py`, referenced as `PlaybookStep.retry` / `PlaybookStep.human_approval`, but **executor never reads either field** (dead schema, v0.2 placeholders)
- `rg "class SecretBroker" arnes/` → **no such class exists**; `ctx.secret_broker` is always `None`, the `if ctx.secret_broker:` branch in `HttpTool.execute` is unreachable
- `wc -l arnes/playbooks/executor.py` → **1 145 lines** (AGENTS.md rule: "if a file is >500 lines, it's doing too much")
- `wc -l arnes/tools/builtin.py arnes/mcp/server.py arnes/middleware/cost_guard.py arnes/specialists/base.py arnes/cli/main.py` → 698 / 533 / 611 / 682 / 656 (4 more files over the 500-line rule)
- Coverage on `tools/builtin.py` → **47 %** (lowest in the codebase; 142 of 295 statements uncovered)
- `__import__("time").time()` at `token_optimizer.py:156` + `import time` inline at `_is_fresh:300` — both should be a single top-level `import time`
- `release.yml` → still uses long-lived `PYPI_API_TOKEN` secret (TODO comment at line 31 acknowledges OIDC migration is v0.2)
- No `CITATION.cff` file; no `docs/demo.gif` committed; Discord "coming soon"; PyPI "not yet published"

---

## 1. Category Scores (9 judges × 10 dimensions each)

### Judge 1 — Security: **87 / 100** (R10: 86, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Input validation | 78 | Pydantic on every tool Args + every event + every config. But `ShellTool.Args.cwd` is still free-form `str` (no allowlist); `_check_ssrf` sync fallback still present as dead code (R1→R10 preserved). |
| 2 | Secret handling | 92 | `_looks_like_secret` heuristic + filtered subprocess env + no API key storage (manifesto #9). JIT injection hook (`ctx.secret_broker`) exists but `SecretBroker` class is unimplemented — the secret-broker abstraction is a promise, not a deliverable. |
| 3 | Sandbox isolation | 90 | Docker Tier 1 auto-detect on PATH; `--security-opt=no-new-privileges`, `--cap-drop=ALL`, `--network=none`, `--read-only`, tmpfs `/workspace`; `ARNES_DEV_MODE=1` double-gate; `Dockerfile.sandbox` ships. gVisor Tier 2 is v0.4. |
| 4 | SSRF | 92 | DNS resolution + ALL-IPs validation + IP pinning + Host header + SNI preservation + `follow_redirects=False` + cloud-metadata blocklist. Best-in-class. The dead sync `_check_ssrf` is the only blemish (preserved since R1). |
| 5 | Path traversal | 93 | `_validate_path` + symlink escape detection using `is_symlink()` alone (not `exists() and is_symlink()`, which misses dangling symlinks — R3 fix). MCP server centralises the policy in `_validate_playbook_path` shared by 3 entry points. |
| 6 | Budget / DoS | 95 | Hierarchical CostGuard (org→project→agent→task), temporal circuit breaker (`max_usd_per_minute`), pre-flight abort via `peek_cost`, hard-stop at 100 %, HITL pause at 95 %, `BudgetExceeded` separated from generic `Exception`. The strongest dimension in the whole project. |
| 7 | HITL | 87 | HITL as a typed tool (`HumanApprovalTool`), `argsFingerprint` rug-pull defense, auto-reject in non-interactive (fail-safe). But real interactive HITL (pause + resume via MCP transport) is v0.2; today's "pause" raises `BudgetExceeded`, which aborts rather than suspends. |
| 8 | MCP server | 88 | Path validation shared across `_run_playbook` / `_validate_playbook` / `_list_playbooks`; bearer-token auth (constant-time `hmac.compare_digest`); per-IP sliding-window rate limiter (100 req/min); 1 MiB body cap; loopback-only binding enforced when no token; generic 500 errors avoid leaking internals. Minimal HTTP transport (no SSE) is the gap. |
| 9 | CI / CD | 85 | SHA-pinned actions (5 actions, all pinned to 40-char SHA with tag comment); 3 OS × 3 Python matrix; blocking `bandit`; blocking `pip-audit` (with one documented ignore: PYSEC-2026-1845); CodeQL workflow. **Preserved**: `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (TODO at line 31 acknowledges this). |
| 10 | Doc honesty | 90 | README "Known Limitations in v0.1 (Alpha)" section is explicit (HITL auto-reject, retry schema defined but not executed, confidence gate not implemented, context compaction not implemented, critic loop not implemented). Every v0.2+ feature is marked 🚧 in the feature table. The R10 double-call bug is fixed, removing the contract-honesty gap. |

**Top issue (Security):** `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (preserved R8→R11). Secondary: dead `_check_ssrf` sync fallback (preserved R1→R11) and `ShellTool.Args.cwd` free-form string (preserved R1→R11). **GO** for public alpha; not yet production-grade.

---

### Judge 2 — Development: **92 / 100** (R10: 92, Δ 0)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Code organisation | 82 | Clean module separation (agent / cli / llm / middleware / playbooks / specialists / thread / tools / mcp). **But `playbooks/executor.py` is 1 145 lines** — violates AGENTS.md's own "if a file is >500 lines, it's doing too much" rule. 4 more files over 500 (builtin 698, cost_guard 611, base.py 682, cli/main 656). |
| 2 | Type safety | 98 | `mypy --strict` clean on 36 files. `pydantic.mypy` plugin enabled. Pydantic `init_typed = True`, `init_forbid_extra = True`. Excellent. |
| 3 | Error handling | 90 | Structured result dicts, `BudgetExceeded` separated from generic `Exception`, `logger.exception` with traceback, fail-safe auto-reject on HITL. `Harness.run` returns `{"success": False, "error": ..., "error_type": type(e).__name__}`. |
| 4 | Test coverage | 80 | 251 tests, 72.63 % overall (above 65 % gate). Stress + integration + snapshot (vcrpy) + unit. **But `tools/builtin.py` is at 47 %** (142/295 statements uncovered) — the most security-critical file has the lowest coverage. |
| 5 | Async correctness | 95 | `asyncio.Lock` for cache mutations, `asyncio.gather(..., return_exceptions=True)` for parallel branches, proper async generators with `yield`, `asyncio.to_thread` for blocking DNS + stdin readline. Thread explicitly copied before sharing across coroutines in `_execute_parallel`. |
| 6 | API design | 88 | Clean public surface in `__init__.py` (22 exports). `Harness` is the simple API, `PlaybookExecutor` is the advanced API. But `Harness.stream()` returns `None` (silent) on missing specialist instead of a structured error (preserved R9→R11). |
| 7 | Docs (code-level) | 90 | Google-style docstrings on every public function. Module-level docstrings explain the "why" not just the "what". AGENTS.md, CONTRIBUTING.md, MANIFESTO.md, CHANGELOG.md, SECURITY.md, PUBLISHING_GUIDE.md. |
| 8 | CI / CD | 92 | 3×3 matrix, security job (bandit + pip-audit), build job, all SHA-pinned. Coverage gate visible at the CI step level (not hidden in pyproject). `mypy --strict` is a hard gate (was previously `|| true`). |
| 9 | Deps | 88 | Pinned with `<` upper bounds. LiteLLM as universal adapter for paid providers. Optional extras (ollama / anthropic / openai / mcp / dev) keep the base install lean. One documented pip-audit ignore (PYSEC-2026-1845 in pytest transitive). |
| 10 | Maintainability | 78 | **Middleware-wrapping logic duplicated in 5 places** (`Harness.run`, `Harness.stream`, `Harness._stream_into_thread`, `Specialist.run`, `Specialist.stream`) — each is ~10 lines of the same `TokenOptimizer → VerificationLayer → CostGuard` pattern. A `_build_wrapped_provider()` helper would collapse this to 1. The R10 double-call fix is clean, but the DRY violation grew from 3 places (R9) to 5 (R11). |

**Top issue (Development):** Middleware-wrapping DRY violation in **5 places** (grew from 3 in R9). Secondary: `executor.py` at 1 145 lines violates the project's own 500-line rule; `tools/builtin.py` coverage at 47 %. **GO** for public alpha (highest-scoring category, second consecutive round above 90).

---

### Judge 3 — Data: **89 / 100** (R10: 88, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Event log | 94 | 22 typed `EventType`s, immutable `Event` (frozen pydantic), `Thread` append-only with O(1) per append (mutates in place; previously O(N²)). Thread explicitly documented as not thread-safe — executor copies before sharing. |
| 2 | State management | 92 | Stateless reducer `_reduce_event(state, event) → state` is a pure function. `Thread.reduce()` always produces the same state from the same event sequence. Authoritative token/cost accumulator is `StepCompletedEvent` (avoids double-counting with `AssistantMessageEvent`). |
| 3 | Observability | 90 | `structlog` everywhere with structured key=value fields. Middleware event sink (`CostGuard._events`) drained by executor after each step with nil-thread-id patching. CACHE_HIT, MODEL_ROUTED, REFUSAL_TRIGGERED, COST_THRESHOLD, RUN_PAUSED all observable. |
| 4 | Audit trail | 90 | Bitácora on all 3 CLI paths (`arnes run`, `arnes run --stream`, `arnes stream`). **R11 improvement**: the R10 double-call bug is fixed, so the `arnes stream` bitácora now reflects a single coherent call (content + usage from the same stream), not two calls spliced together. Still hand-rolled markdown in `arnes stream` (not `Thread.to_markdown()`), but the data is now coherent. |
| 5 | Data flow | 88 | YAML → `PlaybookCompiler` → `Playbook` (pydantic) → `PlaybookExecutor` (DAG walk) → `Specialist.run` (ReAct loop) → middleware (Cost→Verify→TokenOpt) → `LLMProvider`. Every hop emits events. Parallel branches get isolated Thread copies, merged back in timestamp order. |
| 6 | Cache | 72 | `TokenOptimizer._cache` is in-memory only, process-local. LRU eviction (drop oldest 10 %), TTL (default 1 h), max 1 000 entries, `asyncio.Lock` for concurrent safety. Cache key includes `response_schema` (cache-poisoning defense). **Preserved R9→R11**: no `CacheBackend` protocol, no Redis impl — cache is lost on every MCP server restart. |
| 7 | Cost tracking | 95 | Hierarchical CostBudget, per-call tracking on `AssistantMessageEvent`, per-step aggregate on `StepCompletedEvent`, per-run total on `RunCompletedEvent`. Circuit breaker deque (maxlen 1 000). Pre-flight `peek_cost` abort. The double-counting risk is explicitly documented and avoided. |
| 8 | Performance | 88 | O(1) `Thread.append`, O(1) `deque` spend history, LRU cache, `asyncio.gather` for true parallelism, `to_thread` for blocking I/O. The reducer is O(N) per call but only called on-demand. |
| 9 | Validation | 92 | Pydantic v2 everywhere, frozen events, `model_validator(mode="after")` for cross-field invariants (e.g. `validate_step_type`, `validate_step_ids`, `_build_metadata`). `_clean_json_response` handles Llama 3.2 fence-wrapping. |
| 10 | Persistence | 78 | `Thread.save(path)` / `Thread.load(path)` to JSON exist but are not invoked automatically — caller must persist. Bitácora markdown is auto-saved by CLI but not the JSON thread. Cache is not persisted. No SQLite/Postgres backend (documented as future). |

**Top issue (Data):** Cache is in-memory only — no `CacheBackend` protocol + Redis impl (preserved R9→R11). Secondary: `arnes stream` bitácora is hand-rolled markdown, not `Thread.to_markdown()` (R10 contract-honesty gap partially closed — the data is coherent now, but the format is still bespoke). **GO** for public alpha.

---

### Judge 4 — AI: **86 / 100** (R10: 85, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Specialist prompts | 90 | 5 specialists (planner, coder, reviewer, tester, debugger) each with a detailed system prompt: role, job, rules, JSON schema, "respond with ONLY valid JSON". Prompts are visible files on disk (manifesto #6). |
| 2 | ReAct loop | 84 | Implemented in `Specialist.run`: build messages → call LLM → if `tool_calls`, execute each, append results, repeat → validate against schema. `max_iterations` default 10, clear error when exceeded. **Gap**: `Specialist.stream()` deliberately bypasses the ReAct loop (streaming is read-only / generation only). |
| 3 | Structured outputs | 92 | JSON-mode forcing (`response_format={"type": "json_object"}`), strong `pydantic_model` validation preferred over weak JSON-schema `required`-fields check. `_clean_json_response` strips ```` ```json ```` fences. `VerificationLayer._validate_structured` does basic required-fields check. |
| 4 | Anti-hallucination | 85 | 2 of 5 layers shipped: structured outputs + refusal pattern (hedging detection with 6 regex patterns, skips in JSON mode to avoid false positives). 3 layers are v0.2-v0.4 placeholders (confidence gate, critic loop, grounding RAG). Refusal replaces content with `refusal_message` and emits `REFUSAL_TRIGGERED` event. |
| 5 | Token optimization | 87 | Model routing by input size + tier ranking (ollama=0, groq/haiku/mini/flash=1, sonnet/gpt-4o=2, opus/o1/pro=3). Semantic cache with LRU + TTL + cache-poisoning defense. Context compaction (v0.2) and few-shot pruning (v0.3) not yet implemented. |
| 6 | Cost guard | 95 | Best-in-class: hierarchical budgets, temporal circuit breaker, pre-flight abort, hard-stop + HITL-pause, streaming pre-flight abort (post-stream accounting). Documented as "THE killer differentiator of ARNES" — defensible claim. |
| 7 | Playbook DSL | 84 | Declarative YAML → pydantic → DAG. Conditionals (`if_not_met`), parallel branches (true `asyncio.gather`), `saltar_a` skip-to. **Gap**: `RetryPolicy` and `HITLGate` schemas are defined but the executor never reads them — retry and gate execution are v0.2. |
| 8 | Provider abstraction | 92 | `LLMProvider` ABC with `complete` / `stream_complete` / `list_models` / `peek_cost`. LiteLLM as universal adapter for paid providers. Native Ollama. Mock for tests. Vendor-neutral default (`ollama/llama3.2`). |
| 9 | Default model | 95 | `ollama/llama3.2` — local, free, vendor-neutral. Matches manifesto #4 (no hosted version) and the Latam "do more with less" ethos. The `_is_more_expensive` tier ranking correctly identifies ollama as tier 0. |
| 10 | Innovation | 88 | "Manual is the code" (YAML → DAG), Latam-born bilingual, "no hosted version" declaration, markdown bitácora as first-class audit artifact, manifesto with 10 immutable declarations. Genuinely differentiated. |

**Top issue (AI):** `Specialist.stream()` bypasses the ReAct tool-use loop (streaming is read-only). Secondary: 3 of 5 verification layers are placeholders; no SSE/AG-UI HTTP endpoint; no real-LLM integration tests (all 251 tests use mocks). **GO** for public alpha with caveat.

---

### Judge 5 — Marketing: **89 / 100** (R10: 88, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | README | 92 | 544 lines, well-structured: logo at top (120 px, centered), badges, social-card OG/Twitter meta, "Why ARNES exists" narrative, YAML example, terminal output sample, bitácora sample, feature table with v0.1/v0.2/v0.3/v0.4 status, competitive comparison table, 12-factor-agents alignment, architecture diagram, roadmap, community, sponsors, license, acknowledgments, known limitations, demo-GIF recording instructions, star history. Best-in-class for an alpha. |
| 2 | Description / topics | 90 | Crisp one-liner: "Write the manual. ARNES compiles it into a team of specialists that follows it to the letter." 19 PyPI keywords covering ai-agents, agent-framework, mcp, react-agent, a2a, hitl, stateless-reducer, token-optimization, anti-hallucination. |
| 3 | Visual identity | 87 | `docs/logo.svg` (centered, 120 px at README top), `docs/social-card.png` + `.svg`, ASCII art logo in README. Cohesive. **Gap**: no demo GIF committed (the `vhs`/`agg` pipeline is documented but the asset isn't in the repo). |
| 4 | Narrative | 93 | Manifesto is powerful: "The harness, not the horse", "If your framework needs a debugger for your debugger, it is the wrong framework", "Born south of the equator, where doing more with less is not aesthetic — it is survival", "Control the agent. Don't worship it." 10 immutable declarations. Strong story. |
| 5 | Contributor experience | 90 | CONTRIBUTING.md (TL;DR + 7-step workflow), AGENTS.md (system prompt for AI coding agents), CODE_OF_CONDUCT.md, PULL_REQUEST_TEMPLATE.md, 2 issue templates (bug_report, feature_request), `good-first-issue` label, `.pre-commit-config.yaml`, `uv sync --all-extras --dev` one-command setup. |
| 6 | Docs | 82 | README + AGENTS + CONTRIBUTING + MANIFESTO + CHANGELOG + SECURITY + PUBLISHING_GUIDE + examples/README. **Gap**: no docs site (just GitHub README), no API reference generated from docstrings, no tutorials beyond the 5 examples. |
| 7 | Community | 80 | GitHub Discussions enabled, Sponsors section (GitHub Sponsors + Open Collective + BuyMeACoffee), Latam wedge narrative (500 M Spanish-speaking developers). **Gap**: Discord "coming soon" (not live), no Twitter/X presence documented, no YouTube channel. |
| 8 | Release readiness | 78 | PUBLISHING_GUIDE.md exists, alpha state honestly labeled, CHANGELOG maintained through R9 (no R10/R11 section). **Gap**: PyPI "not yet published" badge, no OIDC publishing, no signed releases, no CHANGELOG R10/R11 entries. |
| 9 | Social proof | 70 | Star history chart embedded, acknowledgments section (LangGraph, LiteLLM, MCP SDK, 12-factor-agents, Pydantic). **Gap**: no testimonials, no adoption logos, no conference talks, no blog posts (alpha — expected). |
| 10 | Viral potential | 89 | Manifesto is shareable. "From Latam to the world 🌎" is a unique angle. The "ARNES vs the rest" comparison table is the kind of asset that gets retweeted. The `arnes stream` CLI demo (now single-call, coherent) is gifable. |

**Top issue (Marketing):** No demo GIF committed to the repo (the single highest-leverage marketing asset — `scripts/demo.sh --record` + `vhs` pipeline exists, just needs the GIF rendered and committed to `docs/`). Secondary: Discord "coming soon", PyPI "not yet published", no CHANGELOG R10/R11 section. **GO** for public alpha.

---

### Judge 6 — Competitive: **83 / 100** (R10: 82, Δ +1)

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Feature completeness | 80 | 5 specialists (planned 12), 10 playbooks (planned 30-50), 8 CLI commands, MCP server (4 tools), 5-layer streaming, CostGuard, VerificationLayer, TokenOptimizer. v0.1 ships ~70 % of the v0.1.0 roadmap. Retry/HITL-gate execution, context compaction, few-shot pruning, confidence gate, critic loop, grounding RAG, multi-agent Crew, A2A — all v0.2+. |
| 2 | Code quality | 88 | `mypy --strict` clean, 251 tests, 72.63 % coverage, ruff clean, bandit 0/0/0/0. **But** executor.py at 1 145 lines, middleware DRY violation in 5 places, `tools/builtin.py` at 47 % coverage, dead code (`_check_ssrf` sync, `EventUnion`, unused EventTypes). |
| 3 | README | 92 | Best-in-class (see Judge 5). |
| 4 | Docs | 80 | Comprehensive but no docs site, no API reference, no tutorials beyond 5 examples. |
| 5 | Examples | 85 | 5 runnable example scripts + 10 playbook manuals + `examples/README.md` index. Mock LLM means all examples run offline. Good but not great — no end-to-end "build a real thing" tutorial. |
| 6 | Unique value | 90 | Declarative YAML → DAG with true parallelism + typed boundary events; hierarchical CostGuard with hard-stop AND HITL-pause AND streaming pre-flight abort; markdown bitácora on all CLI paths; native MCP server; `mypy --strict` clean; anti-hallucination middleware stack; shippable Docker sandbox; SHA-pinned CI; "no hosted version" manifesto declaration. Genuinely differentiated. |
| 7 | Market timing | 88 | 2024-2026 agent-framework gap is real. 12-factor-agents manifesto alignment. MCP protocol gaining traction (Claude Desktop, Cursor, Cline, Zed). Local-first ethos matches the "AI sovereignty" wave. |
| 8 | Production readiness | 70 | Alpha. PyPI not published. No OIDC. No memory. No multi-agent. No SSE/AG-UI. No real-LLM integration tests. No Redis cache backend. HITL auto-rejects. Retry not executed. These are documented v0.2+ features, not hidden gaps — but they cap production readiness. |
| 9 | Community potential | 80 | Manifesto resonates. Bilingual EN/ES. `good-first-issue` label. Apache 2.0. But: 0 external contributors, 0 stars (not yet public), Discord not live, no adopters. |
| 10 | Overall position | 78 | Niche but differentiated. Not competing on breadth (LangChain/CrewAI have huge ecosystems and marketing). Competing on control, auditability, local-first, budget enforcement, Latam identity. The "harness, not the horse" positioning is defensible if the manifesto audience adopts. |

**Top issue (Competitive):** No end-user-facing live UX via a browser (LangGraph Studio / CrewAI Canvas / OpenHands Web UI all let users watch an agent think). ARNES streams via 5 layers but no SSE/AG-UI HTTP endpoint and no live UI. Secondary: no real-LLM integration tests; PyPI not published. **GO** for public alpha.

---

### Judge 7 — PHILOSOPHER (NEW): **87 / 100**

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Real problem? | 92 | Yes. Agent frameworks in 2024-2026 are black boxes (can't read prompts), vendor-locked (OpenAI-only features as first-class APIs), and don't respect money (no real budget enforcement). ARNES attacks all three. The problem is real and current. |
| 2 | Value proposition clarity | 95 | "Write the manual. ARNES compiles it into a team of specialists that follows it to the letter." + "The harness, not the horse." Crystal clear in one sentence. The 10 manifesto declarations make the value prop concrete. |
| 3 | User benefit | 90 | Visible prompts (manifesto #6), swappable models (manifesto #1), budget enforcement (manifesto #3), audit trail (bitácora), local-first default (manifesto #4 — no hosted version). Concrete developer benefits, not abstract claims. |
| 4 | Ethical considerations | 78 | "No hosted version" prevents lock-in (ethical stance). Local-first (Ollama default) reduces vendor power. Bilingual EN/ES serves underserved Latam. HITL as a tool (not a gate) respects human agency. Anti-hallucination middleware. **Gap**: no explicit AI-safety policy, no model-bias discussion, no content-moderation layer, no data-retention policy, no red-team documentation. |
| 5 | Accessibility | 80 | Bilingual EN/ES is excellent. Local-first (Ollama) makes it free. Apache 2.0 license. **Gap**: Python 3.11+ requirement excludes some ecosystems; no JS/TS port; no GUI for non-developers; no screen-reader-friendly CLI output documentation; English-first codebase (Spanish only in CLI alias `ejecutar` and bilingual playbook templates). |
| 6 | Long-term vision | 85 | 5-version roadmap (v0.1 → v1.0) is clear. Manifesto is immutable ("will die before it changes the manifesto"). Trajectory: MVP → bidirectional MCP → memory + critic → multi-agent + gVisor → A2A + marketplace. **Gap**: no vision beyond v1.0; no "what does ARNES look like in 5 years?" thinking. |
| 7 | Community values | 88 | Apache 2.0, CODE_OF_CONDUCT.md, `good-first-issue` label, "born south of the equator" identity, Sponsors section, Discussions enabled. **Gap**: no governance model documented, no steering committee, no decision-making process for manifesto amendments (which is the point — they're immutable — but contributors need to know how non-manifesto decisions are made). |
| 8 | Manifesto resonance | 90 | "Control the agent. Don't worship it." is a rallying cry. "If your framework needs a debugger for your debugger, it is the wrong framework" is quotable. The 10 declarations are concrete and testable. **Gap**: the manifesto is more *reactive* (against existing frameworks' defects) than *constructive* (what world ARNES builds). It says what ARNES won't do more vividly than what it will do. |
| 9 | Target audience fit | 88 | Developers who want control, who prefer 50 lines they understand over 5 lines they don't, who are skeptical of magic. Clear and consistent. **Gap**: may alienate developers who want magic/abstraction (a large market segment); no path for non-developer end-users; no enterprise sales narrative. |
| 10 | Problem-solution fit | 92 | The 3 problems (black box, vendor lock-in, no money respect) map cleanly to 3 solutions (visible prompts, vendor-neutral default, CostGuard hard-stop). The bitácora as audit artifact and the YAML-as-code pattern are well-matched to the problems. |
| 11 | (Bonus) Societal impact | 80 | Local-first + Latam-born reduces AI infrastructure colonialism (developers in low-bandwidth regions can run agents without paying OpenAI/Anthropic). Open-source auditability increases AI accountability. **Gap**: narrow impact (developers, not end-users); no measured outcomes; no partnerships with Latam universities or bootcamps. |

**Top issue (Philosopher):** The manifesto is more *anti-existing-frameworks* than *pro-future* — it vividly declares what ARNES won't do but only gesturally describes what world it builds. Secondary: no explicit AI-safety / ethics / content-moderation policy; narrow target audience (skeptical developers). **GO** — strong philosophical foundation, but the posture is reactive.

---

### Judge 8 — SCIENTIFIC TESTER (NEW): **78 / 100**

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Rigorous research use | 75 | Partial. The stateless reducer enables replay; the event log is deterministic; the mock LLM is reproducible. But there's no `ExperimentRunner` class, no hypothesis-tracking, no experiment-config schema, no seed control (temperature=0 default helps but isn't enforced). |
| 2 | Reproducibility | 85 | `Thread` is JSON-serializable (`to_json` / `from_json` / `save` / `load`). Events are immutable and timestamped. Mock LLM is deterministic. **Gap**: cache could break reproducibility (same input → cached response, but `enable_cache=False` is available); no built-in seed propagation to providers; no `reproducibility_mode` flag that disables cache + forces temperature=0 + pins model versions. |
| 3 | Experiment control | 72 | `HarnessConfig` (model, budget_usd, enable_cache, enable_verification, interactive) + `CostBudget` (4 levels + 4 thresholds) allow parameterization. `Playbook` YAML is itself an experiment config. **Gap**: no hyperparameter sweep utility, no A/B comparison harness, no `Experiment.compare(config_a, config_b, dataset)` API, no dataset loader. |
| 4 | Data integrity | 92 | Append-only `Thread`, immutable `Event` (frozen pydantic), `model_validator(mode="after")` for cross-field invariants, `Thread.append` raises `ValueError` on `thread_id` mismatch. Excellent. |
| 5 | Methodological soundness | 80 | Specialists are stateless; reducer is pure; HITL is fail-safe (auto-reject); budget is enforced. **Gap**: LLM calls are non-deterministic by default (temperature=0 mitigates but doesn't guarantee); no formal verification of the reducer; no property-based testing (hypothesis). |
| 6 | Citation readiness | 60 | Apache 2.0, versioned (`0.1.0a1`), CHANGELOG maintained. **Gap**: **no `CITATION.cff` file**, no DOI, no Zenodo integration, no archival on Software Heritage, no academic paper, no related-work section. A researcher cannot cite ARNES in a peer-reviewed paper without a DOI. |
| 7 | Benchmark support | 55 | 10 playbook manuals exist, but **no benchmark suite** (no HumanEval, no MBPP, no SWE-bench, no GAIA, no AgentBench integration). No standard metrics (no pass@k, no F1, no EM, no BLEU, no cost-per-task, no latency-percentile). No comparison harness against baselines. This is the weakest dimension. |
| 8 | Statistical rigor | 60 | 251 tests, coverage 72.63 %. **Gap**: no statistical significance testing, no confidence intervals, no multiple-seed runs, no effect-size reporting, no power analysis. A researcher running an experiment gets one number, not a distribution. |
| 9 | Peer-review readiness | 70 | README + docs are good (architecture diagram, 12-factor alignment, examples, limitations). **Gap**: no academic paper, no formal evaluation against baselines, no related-work section, no threat-to-validity discussion, no IRB/ethics-review documentation (relevant for HITL studies). |
| 10 | Documentation for academics | 75 | README has architecture; AGENTS.md has coding standards; CHANGELOG has version history; MANIFESTO has philosophy. **Gap**: no methodology section, no experimental protocol, no "how to reproduce our results" guide, no data-sheet for the specialists (what data were they tuned on? what are their failure modes?). |
| 11 | (Bonus) Traceability | 92 | Every LLM call → `AssistantMessageEvent` with model/tokens/cost. Every step → `StepStartedEvent` + `StepCompletedEvent` with duration/tokens/cost. Every middleware decision → `CACHE_HIT` / `MODEL_ROUTED` / `REFUSAL_TRIGGERED` / `COST_THRESHOLD` / `RUN_PAUSED`. A researcher can reconstruct exactly what happened in any run. This is ARNES's strongest research-grade dimension. |

**Top issue (Scientific Tester):** No benchmark suite (no HumanEval/MBPP/SWE-bench/AgentBench integration) and no `CITATION.cff` / DOI — a researcher cannot cite ARNES in a peer-reviewed paper, nor can they run a standardised evaluation. Secondary: no statistical rigor (no multiple-seed runs, no CIs, no significance tests). **NO-GO** for research-grade use today; the foundation (traceability, data integrity, reproducibility) is right, but the research tooling is missing.

---

### Judge 9 — OVER-ENGINEERING AUDITOR (NEW): **78 / 100**

| # | Dimension | Score | Notes |
|---|---|---|---|
| 1 | Code duplication | 72 | **Middleware-wrapping logic duplicated in 5 places**: `Harness.run` (agent.py:99-109), `Harness.stream` (agent.py:200-210), `Harness._stream_into_thread` (agent.py:333-343), `Specialist.run` (base.py:117-128), `Specialist.stream` (base.py:288-299). Each is ~10 lines of the identical `TokenOptimizer(provider) → VerificationLayer → CostGuard` pattern. A single `_build_wrapped_provider(provider, *, output_schema, pydantic_model, budget_usd, enable_cache, enable_verification)` helper would collapse this to 1. **Grew from 3 places (R9) to 5 (R11).** |
| 2 | Abstraction abuse | 82 | Mostly appropriate. Pydantic models are justified (data crosses boundaries). `LLMProvider` ABC is justified (multiple implementations). `Specialist` ABC with `__init_subclass__` auto-registry is clean. **Gap**: `EventUnion` discriminated union (events.py:206) is defined but never used — the reducer dispatches by `event.type` string match, not by `isinstance`. The union is dead abstraction. |
| 3 | Premature optimization | 88 | `Thread.append` O(1) (justified — was O(N²)). `asyncio.Lock` for cache (justified — concurrent safety). `deque(maxlen=1000)` for spend history (justified — bounded). LRU eviction (justified). `asyncio.gather(return_exceptions=True)` (justified — fault tolerance). **Gap**: `__import__("time").time()` at token_optimizer.py:156 is silly (should be top-level `import time`; the module already imports `asyncio`/`hashlib`/`json` at top — `time` is conspicuously absent and imported inline twice). |
| 4 | Dead code | 65 | **Significant dead code**: (a) `_check_ssrf` sync fallback (builtin.py:671-698) — flagged in every audit R1→R10, never called by production or tests; (b) `EventUnion` discriminated union (events.py:206-222) — defined, never used; (c) `EventType.RUN_STARTED` — defined, never instantiated; (d) `EventType.COST_LIMIT_EXCEEDED` — defined, never instantiated (executor uses `COST_THRESHOLD` with `threshold_level: "abort"`); (e) `EventType.CONTEXT_COMPACTED` — v0.2 placeholder; (f) `EventType.CONFIDENCE_SCORED` — v0.2 placeholder; (g) `HITLGate` schema (schema.py:58-64) — defined, referenced in `PlaybookStep.human_approval`, but executor never reads it; (h) `RetryPolicy` schema (schema.py:49-55) — defined, referenced in `PlaybookStep.retry`, but executor never reads it; (i) `ctx.secret_broker` hook (base.py:156, builtin.py:251-252) — `SecretBroker` class doesn't exist, the `if ctx.secret_broker:` branch is unreachable; (j) `Agent`/`AgentConfig` deprecated aliases (agent.py:426-427) — kept "for early adopters who used the alpha within hours of release". That's 10 distinct pieces of dead code. |
| 5 | Over-abstraction | 85 | `LLMProvider.peek_cost` with default `None` + duck-typed `getattr` in CostGuard is a reasonable hook. `CostBudget` has 7 fields but only `task_budget_usd` is used in practice (org/project/agent levels are inherited-but-never-set). `VerificationConfig` has 6 fields, 3 of which are v0.2+ placeholders (`confidence_gate`, `critic_loop`, `grounding_rag`). These are documented placeholders, not gratuitous abstraction, but they inflate the config surface. |
| 6 | Redundant middleware | 95 | 3 middleware layers (CostGuard, VerificationLayer, TokenOptimizer) — all are documented as needed, all have distinct responsibilities, all are tested. No redundancy. The `_arnes_wrapped` marker to prevent double-wrapping is a clean guard. |
| 7 | Unnecessary indirection | 80 | `_SchemaValidMockLLMProvider` is defined inline in `cli/main.py` instead of in `arnes/llm/mock.py` (where `MockLLMProvider` lives) — minor locality violation. `_attach_serve_methods()` monkey-patches `serve_stdio`/`serve_http` onto `ArnesMCPServer` at module load (mcp/server.py:515-529) — the comment explains the chicken-and-egg pattern, but regular methods would be cleaner. `Specialist._emit_assistant_message` uses `getattr(wrapped_provider, "_events", None)` duck typing instead of a typed interface — pragmatic but loose. |
| 8 | Config bloat | 75 | `CostBudget`: 7 fields (4 budget levels + 3 thresholds), only `task_budget_usd` used in practice. `VerificationConfig`: 6 fields, 3 are v0.2+ placeholders. `HarnessConfig`: 5 fields (lean). `PlaybookStep`: 11 fields, 2 (`retry`, `human_approval`) are dead. `TokenOptimizer.__init__`: 5 params (lean). The bloat is concentrated in `CostBudget` and `VerificationConfig`. |
| 9 | Test over-engineering | 92 | 251 tests for 8 353 LOC = 1 test per 33 LOC. Reasonable ratio. Stress tests (large playbook, concurrent, template resolution, budget edge cases). Snapshot tests (vcrpy). Integration tests (e2e). Unit tests per module. No over-engineering — the test suite is well-calibrated. |
| 10 | Docs bloat | 80 | 35+ audit reports in `docs/audits/` are process artifacts (not user docs) — they document the R1→R10 journey. README is 544 lines but well-organized. CHANGELOG is comprehensive. Docstrings are thorough but not bloated. **Gap**: the 35 audit reports could be moved to a `docs/audits/archive/` subdirectory to declutter `docs/audits/` (which currently mixes 6 categories × 4 rounds + finals). |

**Top issue (Over-engineering):** **10 distinct pieces of dead code** (sync `_check_ssrf`, `EventUnion`, `RUN_STARTED`, `COST_LIMIT_EXCEEDED`, `CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HITLGate` schema, `RetryPolicy` schema, `secret_broker` hook, `Agent`/`AgentConfig` aliases). Secondary: middleware-wrapping DRY violation in 5 places (grew from 3 in R9). **NO-GO** for "lean codebase" — the dead code should be deleted (or explicitly marked as `# v0.2 placeholder` with a tracking issue), and the middleware-wrapping should be extracted to a helper.

---

## 2. Score Summary

| # | Judge | Score (R11) | Δ from R10 | GO / NO-GO |
|---|---|---|---|---|
| 1 | Security | **87** | +1 | GO (public alpha) |
| 2 | Development | **92** | 0 | GO (public alpha) — highest category |
| 3 | Data | **89** | +1 | GO (public alpha) |
| 4 | AI | **86** | +1 | GO (public alpha, caveat) |
| 5 | Marketing | **89** | +1 | GO (public alpha) |
| 6 | Competitive | **83** | +1 | GO (public alpha) |
| 7 | Philosopher (NEW) | **87** | — | GO (strong foundation, reactive posture) |
| 8 | Scientific Tester (NEW) | **78** | — | **NO-GO** (research-grade) — no benchmark suite, no CITATION.cff |
| 9 | Over-engineering (NEW) | **78** | — | **NO-GO** (lean codebase) — 10 dead-code items, 5-place DRY violation |
| | **AVERAGE (9 judges)** | **85.4** | — | — |
| | Average (6 original judges, comparable to R10) | **87.7** | +0.9 | — |

**The 9-judge average (85.4) is below the 6-judge R10 average (86.8)** — not because ARNES regressed, but because the 3 new judges expose dimensions where ARNES is genuinely weaker (research rigor, code leanness, philosophical constructiveness). The original 6 judges improved from 86.8 → 87.7 (+0.9), driven by the R10 double-call bug fix (which was preserved as the R11 verified state) and the logo/repo-polish work.

---

## 3. Top Issue Per Category

| Category | Top Issue | Severity | Effort |
|---|---|---|---|
| Security | `release.yml` still uses long-lived `PYPI_API_TOKEN` instead of PyPI OIDC Trusted Publishing (preserved R8→R11). Secondary: dead `_check_ssrf` sync fallback (R1→R11). | Medium | 30 min (OIDC) + 5 min (delete `_check_ssrf`) |
| Development | Middleware-wrapping DRY violation in **5 places** (grew from 3 in R9). Secondary: `executor.py` at 1 145 lines violates the 500-line rule; `tools/builtin.py` at 47 % coverage. | Medium | 30 min (extract `_build_wrapped_provider()`) + 1-2 days (split executor) + 1 day (cover builtin) |
| Data | Cache is in-memory only — no `CacheBackend` protocol + Redis impl (preserved R9→R11). Secondary: `arnes stream` bitácora is hand-rolled markdown, not `Thread.to_markdown()`. | Medium | 1-2 days (CacheBackend + Redis) + 30 min (switch CLI to `stream_with_audit`) |
| AI | `Specialist.stream()` bypasses the ReAct tool-use loop (streaming is read-only). Secondary: 3 of 5 verification layers are placeholders; no SSE/AG-UI; no real-LLM tests. | High | 2-3 days (wire streaming into ReAct) + 2-3 days (SSE) + 1 day (vcrpy cassettes) |
| Marketing | No demo GIF committed to the repo. Secondary: Discord "coming soon", PyPI "not yet published", no CHANGELOG R10/R11 section. | Medium | 30 min (`vhs` recording) + 5 min (CHANGELOG) |
| Competitive | No end-user-facing live UX via browser. Secondary: no real-LLM integration tests; PyPI not published. | High | 2-3 days (SSE + live UI) + 1 day (vcrpy) |
| Philosopher | Manifesto is reactive (anti-existing) not constructive (pro-future). Secondary: no explicit AI-safety/ethics policy. | Medium | 1 day (write a constructive "What world ARNES builds" addendum) + 1 day (AI-safety policy) |
| Scientific Tester | No benchmark suite + no `CITATION.cff` / DOI. Secondary: no statistical rigor (no multiple-seed runs, no CIs). | High | 3-5 days (benchmark harness + 1-2 standard suites) + 30 min (CITATION.cff) + 2-3 days (statistical tooling) |
| Over-engineering | **10 distinct pieces of dead code**. Secondary: middleware-wrapping DRY violation in 5 places. | Medium | 1 hour (delete or explicitly mark all 10) + 30 min (extract `_build_wrapped_provider()`) |

---

## 4. GO / NO-GO Verdict Per Category

| Category | Verdict | Rationale |
|---|---|---|
| Security | **GO** (public alpha) | All gates green (bandit 0/0/0/0, pip-audit blocking, SHA-pinned CI, CodeQL). Sandbox auto-detects Docker, SSRF protection is best-in-class (IP pinning + SNI + no-redirects), path traversal + symlink escape covered, CostGuard enforces budget. R10 double-call bug is fixed. Not yet production-grade (no OIDC, no streaming mid-stream budget enforcement, no gVisor Tier 2). |
| Development | **GO** (public alpha) — highest category, 2nd consecutive round ≥ 92 | `mypy --strict` clean (36 files), 251 tests, 72.63 % coverage, ruff clean, bandit clean. All 8 CLI commands documented in 3 places. Double-call bug fixed. **Caveats**: middleware DRY violation in 5 places (grew from 3), `executor.py` at 1 145 lines violates own 500-line rule, `tools/builtin.py` at 47 % coverage. |
| Data | **GO** (public alpha) | Bitácora on all 3 CLI paths, now coherent (double-call fixed). Stateless reducer, append-only Thread (O(1)), hierarchical cost tracking, excellent traceability. **Caveats**: cache in-memory only (no Redis backend), `arnes stream` bitácora is hand-rolled markdown (not `Thread.to_markdown()`). |
| AI | **GO** (public alpha, caveat) | 5-layer streaming (provider → Harness → Specialist → PlaybookExecutor → CLI) all wired, structured outputs with strong pydantic validation, anti-hallucination stack (2 of 5 layers), hierarchical CostGuard, true parallel execution. **Caveats**: `Specialist.stream()` bypasses ReAct loop, no SSE/AG-UI, no real-LLM tests. |
| Marketing | **GO** (public alpha) | README best-in-class, logo placed, narrative strong, contributor experience solid, examples + 10 playbooks. **Caveats**: no demo GIF, Discord not live, PyPI not published. |
| Competitive | **GO** (public alpha) | Differentiated on control, auditability, local-first, budget enforcement, Latam identity. Hardened supply chain. **Caveats**: no live UX, no real-LLM tests, narrow feature breadth vs LangChain/CrewAI. |
| Philosopher | **GO** | Strong manifesto, clear value prop, real problem, ethical stance (no hosted version, local-first, Latam identity). **Caveats**: reactive posture, narrow audience, no explicit AI-safety policy. |
| Scientific Tester | **NO-GO** (research-grade) | Excellent traceability + data integrity + reproducibility foundation. **But**: no benchmark suite, no `CITATION.cff`/DOI, no statistical rigor, no experiment runner. A researcher cannot cite or standardly evaluate ARNES today. |
| Over-engineering | **NO-GO** (lean codebase) | 251 tests, mypy clean, ruff clean — but **10 distinct pieces of dead code** and middleware-wrapping DRY violation in 5 places (grew from 3). The codebase is correct but carries documented v0.2-v0.4 placeholders that should be either deleted or explicitly marked with tracking issues. |

---

## 5. Is 95 / 100 Reachable? What's Needed?

**Short answer: Not in 1-2 rounds. The 9-judge panel makes 95/100 substantially harder than the 6-judge panel did.**

**Why 95/100 is harder under 9 judges:**
- The 6-judge R10 average was 86.8. The 9-judge R11 average is 85.4 — *lower*, despite the original 6 judges improving to 87.7. The 3 new judges (Philosopher 87, Scientific 78, Over-eng 78) expose dimensions where ARNES is genuinely weaker.
- To reach 95/100 across 9 judges, total = 855. Currently at 769. Need **+86 points across 9 judges = avg +9.6 per judge**. That's a multi-quarter effort.
- To reach 95/100 across the original 6 judges, total = 570. Currently at 526. Need **+44 points across 6 judges = avg +7.3 per judge**. Still 2-3 focused rounds.

**The path to 95/100 (ordered by leverage):**

### Tier 1 — Quick wins (1-2 days, +5 to +8 average)
1. **Delete the 10 dead-code items** (`_check_ssrf` sync, `EventUnion`, `RUN_STARTED`, `COST_LIMIT_EXCEEDED`, `CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HITLGate` if not wiring in v0.2, `RetryPolicy` if not wiring in v0.2, `secret_broker` hook, `Agent`/`AgentConfig` aliases). → Over-eng +5, Dev +1, Security +1. **~1 hour.**
2. **Extract `_build_wrapped_provider()` helper** to collapse the 5-place middleware-wrapping duplication. → Dev +2, Over-eng +3. **~30 min.**
3. **Switch `arnes stream` CLI to `Harness.stream_with_audit()` + `thread.to_markdown()`** (produces structured bitácora, uses the project's own tested API). → Data +1, Dev +1. **~30 min.**
4. **Add `CITATION.cff` + register on Zenodo for a DOI**. → Scientific +3. **~30 min + Zenodo wait.**
5. **Embed a `vhs`-recorded `docs/demo.gif`** in the README. → Marketing +2, Competitive +1. **~30 min.**
6. **Add CHANGELOG R10 + R11 sections**. → Marketing +1, Dev +1. **~10 min.**
7. **Migrate `release.yml` to PyPI OIDC Trusted Publishing**. → Security +2. **~30 min.**
8. **Add `import time` at top of `token_optimizer.py`** (remove `__import__("time")` and inline `import time`). → Over-eng +1. **~2 min.**

**Tier 1 total: ~5 hours of work, +8 to +12 average points.** Brings average from 85.4 → ~88-90 (9-judge) or 87.7 → ~90-92 (6-judge).

### Tier 2 — Multi-day features (1-2 weeks, +5 to +8 average)
9. **Wire streaming into the ReAct tool-use loop** (`Specialist.stream()` should support tool calls, not just read-only generation). → AI +3. **2-3 days.**
10. **Add SSE/AG-UI HTTP endpoint on the MCP server + a minimal live UI** (browser-based agent watcher). → AI +2, Competitive +3. **2-3 days.**
11. **Add real-LLM integration tests with `vcrpy` cassettes** for Ollama + LiteLLM + all 5 streaming surfaces. → AI +2, Dev +1, Competitive +1. **1 day.**
12. **Add a `CacheBackend` protocol + Redis impl** for cache persistence across MCP server restarts. → Data +3. **1-2 days.**
13. **Cover `tools/builtin.py`** (currently 47 % → target 85 %). → Dev +2. **1 day.**
14. **Split `executor.py`** (1 145 lines) into `executor.py` (run loop) + `step_executor.py` (step dispatch) + `parallel.py` (parallel-branch logic) + `template.py` (input resolution). → Dev +2, Over-eng +2. **1-2 days.**
15. **Add CLI tests** for `arnes stream` and `arnes run --stream` (using `click.testing.CliRunner`). → Dev +1. **2 hours.**
16. **Publish to PyPI** (after OIDC migration). → Marketing +2, Competitive +2. **1 hour + review wait.**

**Tier 2 total: ~2 weeks, +8 to +12 average points.** Brings average from ~89 → ~92-94 (9-judge).

### Tier 3 — Research-grade + philosophical depth (2-4 weeks, +3 to +5 average)
17. **Add a benchmark harness** with 1-2 standard suites (HumanEval for code, GAIA for general agents) + standard metrics (pass@k, cost-per-task, latency-p50/p99). → Scientific +5, Competitive +2. **3-5 days.**
18. **Add statistical rigor tooling** (multiple-seed runner, confidence intervals, significance tests). → Scientific +3. **2-3 days.**
19. **Write a constructive manifesto addendum** ("What world ARNES builds" — not just what it refuses). → Philosopher +3. **1 day.**
20. **Add an AI-safety / ethics policy** (content moderation opt-in, data retention defaults, model-bias disclosure template). → Philosopher +3. **1-2 days.**
21. **Add a `docs/audits/archive/` subdirectory** to declutter `docs/audits/`. → Over-eng +1. **10 min.**

**Tier 3 total: ~2-4 weeks, +5 to +8 average points.** Brings average from ~93 → ~95-96 (9-judge).

### Realistic timeline to 95/100
- **Tier 1 alone (5 hours)**: 85.4 → ~89 (9-judge). Crosses 90 on the 6-judge panel.
- **Tier 1 + Tier 2 (~2 weeks)**: ~89 → ~93 (9-judge). Crosses 92 on the 6-judge panel.
- **Tier 1 + Tier 2 + Tier 3 (~4-6 weeks)**: ~93 → ~95-96 (9-judge). **Reaches 95/100 on the 9-judge panel.**

**The single highest-leverage action**: delete the 10 dead-code items + extract `_build_wrapped_provider()` + add `CITATION.cff` + embed `docs/demo.gif` + migrate to OIDC. **~3 hours of work, +6 to +8 average points**, bringing the 9-judge average from 85.4 to ~91-92 and clearing 2 of the 3 new judges' NO-GO verdicts (Over-engineering and partially Scientific Tester).

---

## 6. Final Assessment

**Trajectory (6-judge comparable):** R1 (59.7) → R2 (71.2) → R3 (76.2) → R4 (79.5) → R5 (80.5) → R6 (82.0) → R7 (83.3) → R8 (84.0) → R9 (86.3) → R10 (86.8) → **R11 (87.7, 6-judge) / 85.4 (9-judge)**.

**Honest characterization of R11:**
- ✅ **R10 double-call bug confirmed fixed** — `arnes/cli/main.py:236` iterates `harness.stream()` exactly once; `chunks_list` is collected during that single pass; the bitácora is built from the captured chunks, not from a second call. The R10 contract-honesty gap (comment said "use `stream_with_audit`" but code used `stream()` twice) is closed at the data-coherence level (the data is now coherent), though the CLI still uses hand-rolled markdown instead of `Thread.to_markdown()`.
- ✅ **Repo reorg clean** — 35 historical audit reports moved to `docs/audits/`; root is uncluttered; logo (`docs/logo.svg`, 120 px, centered) at top of README.
- ✅ **All quality gates green** — 251/251 tests pass, `mypy --strict` clean (36 files), `ruff` clean, `bandit` 0/0/0/0.
- ✅ **3 original-6 categories nudge +1** (Security, Data, AI, Marketing, Competitive all +1) — driven by the double-call fix and polish.
- ✅ **Development preserved at 92** (highest category, 2nd consecutive round ≥ 92).
- ⚠️ **3 new judges expose real gaps**: Scientific Tester (78 — no benchmarks, no CITATION.cff) and Over-engineering (78 — 10 dead-code items, 5-place DRY violation) are NO-GO; Philosopher (87) is GO but flags the reactive posture.
- ⚠️ **Middleware DRY violation grew from 3 places (R9) to 5 places (R11)** — each new streaming surface (`Harness.stream`, `Harness._stream_into_thread`, `Specialist.stream`) added another copy of the wrapping pattern. This is the R11 Dev top issue and the R11 Over-eng top issue.
- ⚠️ **`executor.py` at 1 145 lines** violates AGENTS.md's own 500-line rule (4 more files also over: builtin 698, cost_guard 611, base.py 682, cli/main 656).
- ⚠️ **`tools/builtin.py` at 47 % coverage** — the most security-critical file has the lowest coverage.
- ⚠️ **10 distinct pieces of dead code** documented (see Judge 9, dimension 4).
- ⚠️ **No CHANGELOG R10 or R11 section** (last entry is R9).

**Bottom line:** R11 is the first evaluation under the expanded 9-judge panel. The original 6 judges improved from 86.8 → 87.7 (+0.9), driven by the R10 double-call bug fix and polish work. The 3 new judges (Philosopher 87, Scientific 78, Over-eng 78) pull the 9-judge average to 85.4 — not because ARNES regressed, but because the new lenses expose dimensions where ARNES is genuinely weaker (research tooling, code leanness, philosophical constructiveness). **The path to 95/100 across 9 judges is a 4-6 week effort** (Tier 1 + Tier 2 + Tier 3 above), with the first 5 hours of work (Tier 1) delivering +6 to +8 average points and clearing 2 of the 3 NO-GO verdicts. **The single highest-leverage next action is a 3-hour sweep**: delete the 10 dead-code items, extract `_build_wrapped_provider()`, add `CITATION.cff`, embed `docs/demo.gif`, migrate to OIDC, add `import time` at the top of `token_optimizer.py`. This would bring the 9-judge average from 85.4 to ~91-92 and the 6-judge average from 87.7 to ~92-93.

**Final GO/NO-GO: GO for public alpha (6-judge panel); CONDITIONAL on the 9-judge panel** — Security, Development, Data, AI, Marketing, Competitive, and Philosopher all GO; Scientific Tester and Over-engineering are NO-GO until Tier 1 fixes land. ARNES at R11 is **ready for public alpha release as `0.1.0a1`** on the original 6 dimensions; the 3 new dimensions (research-grade, lean codebase, constructive philosophy) are well-scoped engineering and writing work for v0.2.

---

*End of report. — JUDGE_FINAL_R11 (9-judge consolidated panel)*
