# JUDGE-DATA-R1 — ARNES Data Quality Audit

**Auditor:** Senior Data Engineer (judge role)
**Date:** 2026-01
**Scope:** `/home/z/my-project/arnes/` — data handling, observability, analytics
**Method:** Static review of 5,187 LOC source + 1,343 LOC tests + 10 YAML manuals. Cross-checked against `ARCHITECTURE_AUDIT.md`, `AI_AUDIT_V2.md`, `SECURITY_AUDIT_V2.md`. Dynamic verification of reducer consistency, event emission coverage, and cache key correctness.

---

## TL;DR

ARNES has a **conceptually clean event-sourced foundation** (immutable `Thread`, pure reducer, typed `Event` pydantic models). But the **data layer is operationally incomplete**: 14 of 24 declared `EventType`s are never emitted by any code path, the bitácora omits token/cost/cache decisions, pre-flight cost checking only works with mock providers, and `Thread.append` is O(N²). The headline differentiators (semantic cache, hierarchical budget, audit trail) are **architecturally present but data-incomplete**.

**Overall data quality score: 63/100**
**Verdict: NO-GO for public release** (GO for private alpha with documented caveats). Three of the top five critical issues are <1 day fixes each.

---

## Scorecard

| # | Dimension | Score | Weight | Weighted |
|---|-----------|------:|-------:|---------:|
| 1 | Event log design | 72 | 15% | 10.80 |
| 2 | State management (reducer) | 65 | 12% | 7.80 |
| 3 | Observability | 58 | 10% | 5.80 |
| 4 | Audit trail (bitácora) | 55 | 12% | 6.60 |
| 5 | Data flow (templates) | 70 | 10% | 7.00 |
| 6 | Cache design | 55 | 8% | 4.40 |
| 7 | Cost tracking | 65 | 10% | 6.50 |
| 8 | Performance data | 72 | 5% | 3.60 |
| 9 | Data validation | 65 | 10% | 6.50 |
| 10 | Persistence | 50 | 8% | 4.00 |
| | **OVERALL** | | 100% | **63.0/100** |

---

## Dimension-by-Dimension

### 1. Event log design — 72/100

**Files:** `arnes/thread/events.py`, `arnes/thread/thread.py`

**Strengths**
- `Event` is pydantic `frozen=True` → truly immutable (`events.py:85`).
- `Thread.append()` returns a new `Thread` (immutability preserved, `thread.py:64-70`).
- 24 `EventType` values cover conversation, tools, specialists, steps, control flow, HITL, cost, token optimization, verification, run lifecycle.
- Every `Event` has `id: UUID`, `timestamp: datetime`, `thread_id: UUID`, `step_id`, `specialist`, `data`. Universal foreign keys.
- `_utc_now()` returns naive UTC (`events.py:20-22`) — sidesteps pydantic tz pitfalls, deterministic for replay.
- `Thread.from_events()` supports replay from any event sequence.
- JSON round-trip tested (`tests/unit/test_thread.py::test_to_json_roundtrip`).

**Issues**
- **`data: dict[str, Any]` is unstructured.** Each subclass documents its expected keys in comments only (`events.py:103, 113, 118, …`). No pydantic validation of payload shape. A misspelled `tokens_in` key silently breaks the reducer's accumulation.
- **`EventUnion` discriminated union declared but unused** (`events.py:204-220`). The reducer accepts the base `Event` class and dispatches on `event.type`, throwing away the type-safety the union would provide.
- **14 of 24 event types are dead code.** A grep for emission sites confirms: `AssistantMessageEvent`, `UserMessageEvent`, `CostThresholdEvent`, `MODEL_ROUTED`, `CACHE_HIT`, `CONTEXT_COMPACTED`, `REFUSAL_TRIGGERED`, `CONFIDENCE_SCORED`, `PARALLEL_BRANCH_STARTED`, `PARALLEL_BRANCH_COMPLETED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_PAUSED`, `RUN_RESUMED` are **never instantiated by any production code**. They appear only in tests and the type union.
- **No event schema versioning.** A field rename in `data` would silently break replay of old saved threads.
- **No event ordering invariant enforced.** Nothing prevents appending a `STEP_COMPLETED` for a `step_id` whose `STEP_STARTED` was never emitted.

### 2. State management (reducer purity, consistency) — 65/100

**Files:** `arnes/thread/thread.py:108-259`

**Strengths**
- `_reduce_event(state, event) -> state` is a **pure function** — no I/O, no side effects, no mutation of input state.
- Reducer state initialized fresh each `reduce()` call (`thread.py:114-126`).
- Closed `if/elif` chain over `EventType` — exhaustive and readable.
- Step state machine: `running → completed` / `running → failed` is correctly modeled.

**Issues**
- **Reducer state is an untyped `dict[str, Any]`** — easy to typo keys (`"messages"` vs `"message"`). No pydantic schema for the reduced state.
- **Reducer returns mutable dicts/lists** — callers can mutate `state["messages"]` and corrupt future reductions. Not pure in practice.
- **`STEP_COMPLETED` reducer ignores tokens/cost.** The reducer only aggregates tokens from `ASSISTANT_MESSAGE` events (`thread.py:197-199`), but the executor never emits those events. Result: `thread.reduce()["total_tokens_in"]` is always `0` after a real run, even though `PlaybookRunResult.total_tokens_in` is correct. **Data inconsistency between result and thread.**
- **`STEP_COMPLETED.data` schema omits token fields.** Even if the reducer wanted to track per-step spend, the executor populates only `step_id`, `output`, `duration_s` (`executor.py:287-292`). Token/cost data is collected in `run()` but discarded.
- **`current_step_id` can go stale** if `STEP_STARTED` fires but `STEP_COMPLETED`/`STEP_FAILED` is skipped (e.g., unhandled exception in step body).
- **`Thread.append` is O(N) per call** → building an N-event thread is O(N²). The stress test (`tests/stress/test_large_playbook.py:351-385`) explicitly surfaces this and prints timings, but it's unfixed.
- **Executor uses `thread_holder: list[Thread]` mutable cell** (`executor.py:101`) to work around Thread immutability — code smell that admits the control flow doesn't fit the immutable model.
- **No structural sharing.** `events=[*self.events, event]` copies the entire list each append.

### 3. Observability — 58/100

**Files:** `arnes/middleware/*.py`, `arnes/playbooks/executor.py`

**Strengths**
- `structlog` used consistently across all modules.
- Each middleware exposes a `stats()` method (`token_optimizer.py:218-232`, `cost_guard.py:302-314`, `verification.py:223-228`) returning a typed dict.
- Rich log event vocabulary: `cache_hit`, `model_routed`, `llm_call_tracked`, `cost_guard_warn`, `cost_guard_abort`, `cost_guard_preflight_abort`, `verification_failed`, `step_failed`, `saltar_a_reached`, `step_skipped`, `mcp_request_failed`.
- Budget edge-case logging includes `pct`, `spent`, `budget`, `level` — good for post-incident review.
- Stress tests print structured reports with RSS, tracemalloc, p95 latencies.

**Issues**
- **No OpenTelemetry, no spans, no distributed tracing.** Just structlog lines.
- **No metrics export** (no Prometheus, statsd, or OTLP). `stats()` is in-memory only and lost on process restart.
- **No correlation/request IDs.** structlog isn't bound to a context var, so log lines from concurrent runs (see `tests/stress/test_concurrent.py`) interleave without a way to filter one run.
- **Middleware decisions are NOT in the Thread.** Cache hits, model routing, refusals, cost warnings exist only in structlog. To audit them you need a log sink; the bitácora can't show them.
- **No log levels documented.** Most calls are `info`/`warning`/`error`/`exception` — no policy on what each level means.
- **No streaming/observer pattern.** Consumers can't subscribe to live Thread updates; they must poll `thread.events`.
- **No sampling.** A long run produces a structlog line per LLM call — fine for dev, noisy in prod.
- **`TokenOptimizer.estimated_savings_usd`** uses a flat `$3/1M tokens` rate (`token_optimizer.py:231`) — wildly inaccurate (ranges from $0.15 for gpt-4o-mini to $75 for opus-4 output). Misleading observability.

### 4. Audit trail (bitácora quality, completeness) — 55/100

**Files:** `arnes/thread/thread.py:155-176`, `arnes/playbooks/executor.py:63-65`, `arnes/mcp/server.py:222-224`

**Strengths**
- `Thread.to_markdown()` produces a structured chronological bitácora with per-event headers (timestamp, type, step_id, specialist) and JSON-dumped `data`.
- `PlaybookRunResult.to_markdown()` delegates to `thread.to_markdown()` — single source of truth.
- MCP server returns `bitacora_preview` in run result so MCP clients (Claude Desktop, Cursor) can show it.
- UTF-8 safe (`ensure_ascii=False`).
- Human-readable ISO timestamps.

**Issues**
- **Bitácora is just a chronological event dump.** No header summary: total cost, total tokens, success/failure, duration, steps-executed/steps-failed counts. A reviewer must read every event to know if the run succeeded.
- **Token/cost data absent from bitácora.** Because `STEP_COMPLETED` events don't carry tokens and `ASSISTANT_MESSAGE` events are never emitted, the bitácora shows zero spend even on runs that consumed real budget.
- **Cache/routing/refusal decisions missing.** These middleware events aren't in the Thread; the bitácora can't answer "was this answer cached?" or "was the model routed to Haiku?".
- **MCP `bitacora_preview` truncated to 500 chars** (`server.py:222-224`) — too short to be useful; most useful info is past the truncation point.
- **No structured (JSON) bitácora export.** Only markdown. Programmatic consumers must re-parse markdown or load the Thread JSON separately.
- **No query API.** Can't ask "show me all errors" or "show me all tool calls" without iterating all events.
- **No security annotations.** A step that called a tool with destructive args isn't flagged in the bitácora.
- **`ConditionalBranchEvent.data` is sparse** (`executor.py:454-463`): only `condition` and `action` — doesn't record the evaluated boolean or which branch was taken.
- **No reducer state snapshot at end of run.** A good audit trail would include the final reduced state (messages list, steps with status, totals).

### 5. Data flow (input/output passing, template resolution) — 70/100

**Files:** `arnes/playbooks/executor.py:494-633`, `tests/stress/test_template_resolution.py`

**Strengths**
- Template engine handles `{{ variables.X }}`, `{{ steps.X.output }}`, legacy ES `{{ pasos.X.salida }}`.
- Multiple templates in one string resolve correctly (`executor.py:559-570`).
- Deep nesting works: `{{ steps.s1.output.steps.s2.output.steps.s3.output }}` — only the **leading** prefix is stripped, interior `steps.` keys are preserved (`executor.py:600-611`). This is non-trivial and correctly implemented.
- Missing template returns the literal string (graceful, no crash) — tested in `test_template_resolution.py::test_case5_*`.
- Empty template `{{ }}` round-trips verbatim (`test_case6_*`).
- Parallel sub-step templates resolve (`test_case4_parallel_substep_template`).
- Virtual `output` accessor handles both raw and wrapped output storage (`executor.py:619-627`).
- Bilingual ES→EN key translation in compiler (`compiler.py:103-146`).

**Issues**
- **Templates are string-substitution, not Jinja2.** No expressions (`{{ a + b }}`), no filters (`{{ x | upper }}`), no conditionals (`{% if %}`). Limits playbook expressiveness.
- **`str(resolved)` coercion for embedded templates** (`executor.py:568`) — a dict variable produces `"{'key': 'val'}"` (Python repr, not JSON). Ugly and inconsistent.
- **No type coercion.** A variable holding `1234` (int) becomes `"1234"` (str) when interpolated into a larger string. Downstream LLM sees a string, not a number.
- **Internal sentinel keys leak into outputs.** `_resolve_input` injects `__resolved_str__` and `__input__` (`executor.py:510, 532`). `_handle_conditional_branch` injects `__skip_steps_until` (`executor.py:484`). The MCP server filters only `__`-prefixed keys (`server.py:220`), but these sentinels shouldn't be in user-visible outputs at all.
- **Parallel execution is sequential** (`executor.py:421-442`). Docstring admits "For MVP: sequential execution of 'parallel' steps (correctness > parallelism)". The promise of parallelism is unfulfilled.
- **`saltar_a` (skip-to) implementation mutates `outputs` dict in place** (`executor.py:484-485`) — breaks the immutability claim.
- **No template validation at compile time.** A typo like `{{ steps.read_dif.output }}` (missing 'f') isn't caught until runtime, and even then it silently returns the literal.

### 6. Cache design (semantic cache, TTL, eviction, key correctness) — 55/100

**Files:** `arnes/middleware/token_optimizer.py`

**Strengths**
- LRU eviction: when cache exceeds `cache_max_entries`, removes oldest 10% by `created_at` (`token_optimizer.py:204-212`).
- TTL based on `created_at + cache_ttl_s` (`_is_fresh`, `token_optimizer.py:199-202`).
- Cache key is SHA-256 of `{messages, model, tools, kwargs}` (`_cache_key`, `token_optimizer.py:178-197`). Sort-keys-stable, deterministic.
- Stats: `cache_hits`, `cache_misses`, `cache_hit_rate`, `cache_size`, `routing_decisions`, `tokens_saved`, `estimated_savings_usd` (`stats()`, `token_optimizer.py:218-232`).
- `reset_stats()` for clean test runs.

**Issues**
- **Not actually a "semantic" cache.** The docstring (`token_optimizer.py:8`) and README call it a "semantic cache", but it's an **exact-match hash cache**. Two semantically equivalent prompts with different whitespace produce different keys. Misleading naming.
- **Cache key excludes `temperature`** (`token_optimizer.py:191`) — comment says "varies". But this means a cached response from `temperature=0.7` (non-deterministic) gets served to a `temperature=0.0` (deterministic) request. **Correctness bug.**
- **Cache is in-memory only.** Lost on process restart; not shared across processes/instances. Useless for the MCP server use case (each invocation is a fresh process).
- **Not thread-safe.** `cached.hit_count += 1` and `cached.response.usage.cached = True` (`token_optimizer.py:99-101`) mutate the cached `CacheEntry` and its `LLMResponse` under concurrent access. Python's GIL prevents corruption but allows logical races (two callers see `hit_count=1` instead of `2`).
- **Stores full `LLMResponse` including `raw`** (`token_optimizer.py:124`) — `raw` can be a multi-KB vendor payload. Memory bloat.
- **No size cap on individual entries.** A 10 MB response takes 10 MB in cache.
- **No cache invalidation API.** Can't flush a specific key, can't flush all, can't invalidate by model.
- **`estimated_savings_usd` uses flat `$3/1M tokens`** (`token_optimizer.py:231`) — inaccurate. Real models range $0.15–$75/1M tokens.
- **Refusals are cached.** `VerificationLayer` sets `response.usage.cached = False` after a refusal (`verification.py:124`), but the **`TokenOptimizer` runs OUTSIDE the VerificationLayer** in the default middleware stack (`specialists/base.py:120-126`), so the cache stores the LLM's original response before verification replaces it. Worse: if `TokenOptimizer` wraps `VerificationLayer`, the refusal message (non-empty content) gets cached on the next call, and subsequent identical requests get the refusal from cache — preventing retries. **The middleware ordering determines correctness, and the ordering is inconsistent** (see `ARCHITECTURE_AUDIT.md` §3.3).

### 7. Cost tracking (accuracy, granularity, reporting) — 65/100

**Files:** `arnes/middleware/cost_guard.py`, `arnes/llm/litellm_provider.py`

**Strengths**
- Hierarchical budget: `org → project → agent → task` with `effective_budget()` returning the most specific non-None value (`cost_guard.py:70-79`).
- Pre-flight check via `peek_cost` (duck-typed, `cost_guard.py:265-296`) — rejects calls before they're made when projected spend would breach budget.
- Circuit breaker: `max_usd_per_minute` enforced via `_spend_history` deque (maxlen=1000, `cost_guard.py:255-263`).
- Multiple abort levels: `hard_stop`, `preflight`, `circuit_breaker`, `pause`, `specialist` — all surfaced in `BudgetExceeded.level`.
- `CostBudget` is a pydantic model with `warn_at_pct`, `pause_at_pct`, `abort_at_pct` — configurable thresholds.
- `LiteLLMProvider` has a real pricing table for 11 models across Anthropic/OpenAI/Google/Groq (`litellm_provider.py:11-22`).
- Edge-case tests cover zero budget, free model, circuit breaker, exact-limit, pre-flight (`tests/stress/test_budget_edge_cases.py`).

**Issues**
- **`LiteLLMProvider` does NOT override `peek_cost`.** The pre-flight check is a "killer differentiator" but only works with the test mock (`ConfigurableCostProvider`). Real LLM calls can't be rejected before spend. **The differentiator is unimplemented for real providers.**
- **Pricing table is hardcoded** with a "as of 2026-01" comment (`litellm_provider.py:9-10`). No auto-update mechanism; will silently drift as vendors change pricing.
- **Fallback for unknown models: `$1/1M tokens`** (`litellm_provider.py:30`) — could be 10× wrong (e.g., a new cheap model would be over-charged, blocking legitimate runs).
- **Cost tracking is at middleware level, NOT in Thread events.** `thread.reduce()["total_cost_usd"]` always returns `0` because `ASSISTANT_MESSAGE` events are never emitted. `PlaybookRunResult.total_cost_usd` is correct (tracked in `run()`), but the Thread is wrong. **Data inconsistency.**
- **No per-step cost breakdown** in `PlaybookRunResult`. Just a single `total_cost_usd` field.
- **No cost reporting API** beyond `stats()` dict. No CSV/JSON export, no per-specialist breakdown, no per-model breakdown.
- **`CostGuard.spent_usd` mutated without lock** (`cost_guard.py:239`). The concurrent stress test passes only because the GIL prevents the specific interleavings tested; a real LLM with non-trivial `complete()` body could race.
- **`max_usd_per_minute` window is not a true sliding window.** `_check_circuit_breaker` filters `_spend_history` by `now - ts < 60s` (`cost_guard.py:262`), but the deque has fixed maxlen=1000. Under sustained high spend, old entries get evicted before they expire — the breaker could trip late or never.
- **`CostGuard.stats()["pct_used"]`** divides by `effective_budget` without zero-check (`cost_guard.py:307`) — `effective_budget` can be `None` (unlimited), in which case the conditional returns `0.0`, masking actual spend.
- **`reset()` clears spend but not config** (`cost_guard.py:316-322`) — fine, but no `reset_between_runs()` documented pattern.

### 8. Performance data (benchmarks, scaling characteristics) — 72/100

**Files:** `tests/stress/test_concurrent.py`, `tests/stress/test_large_playbook.py`, `tests/stress/test_budget_edge_cases.py`, `tests/stress/test_template_resolution.py`

**Strengths**
- **STRESS-1**: 50 concurrent playbook runs in <10 s, with race detection (unique thread IDs, run_id distribution check, max_concurrent_calls high-water mark). Memory ceiling 200 MB.
- **STRESS-2**: 50-step playbook in <30 s wall clock, with per-step p95/stdev durations, peak tracemalloc, event-type breakdown.
- **STRESS-3**: 6 budget edge cases (zero budget, exact-at-limit, pre-flight, circuit breaker, free model, very-large budget) — all pass.
- **STRESS-4**: 9 template resolution stress cases (30 refs, deep nesting, parallel sub-steps, missing refs, empty templates, special chars, legacy ES).
- Memory baseline + delta tracked via both RSS (`resource.getrusage`) and `tracemalloc`.
- `test_thread_append_scaling` explicitly surfaces the O(N²) `Thread.append` cost — honest about the limitation.
- Compile-only and dict-validate paths benchmarked separately to isolate YAML parse cost.
- Standalone runner (`python tests/stress/test_*.py`) prints reports without pytest.

**Issues**
- **All stress tests use mock providers** (`SchemaValidMockProvider`, `ConfigurableCostProvider`). No real-LLM latency data, no real cost data, no real token counts.
- **No CI performance regression baseline.** Tests assert `< 10s` / `< 30s` but don't track trend over time.
- **No comparison against other frameworks** (LangChain, CrewAI, AutoGen) — can't claim "fastest".
- **No long-running soak test.** Memory leak over hours is unmeasured.
- **No cache-hit-rate benchmark.** TokenOptimizer's `40-65% token reduction` claim (`token_optimizer.py:13`) is unverified.
- **Thread.append O(N²) known but unfixed** — acknowledged in test comment, not in roadmap.
- **No profiling data** (cProfile, py-spy) showing where time goes.

### 9. Data validation (pydantic schemas, structured outputs) — 65/100

**Files:** `arnes/playbooks/schema.py`, `arnes/thread/events.py`, `arnes/middleware/verification.py`, `arnes/specialists/base.py`

**Strengths**
- All models use **pydantic v2** `BaseModel` — fast, type-checked.
- `PlaybookStep.validate_step_type` enforces "exactly one of specialist/tool/parallel" (`schema.py:114-122`).
- `Playbook.validate_step_ids` rejects duplicate step IDs (`schema.py:175-182`).
- `Event` base is `frozen=True` (`events.py:85`).
- `SpecialistConfig` supports both `output_schema` (JSON Schema dict) and `pydantic_model` (stronger, type-safe) (`specialists/base.py:42-43`).
- `Specialist._parse_and_validate_output` does strong pydantic validation when `pydantic_model` is set (`specialists/base.py:335-353`), falls back to weak `required`-fields check.
- `CostBudget` uses `Field(ge=, le=)` constraints (`schema.py:53-55, 64`).
- `RetryPolicy`, `HITLGate`, `ConditionalBranch` all pydantic-validated.
- Compiler runs **semantic checks** after pydantic validation: specialist name format, `skip_to` target existence, parallel ID uniqueness (`compiler.py:152-189`).

**Issues**
- **`Event.data: dict[str, Any]` is completely unstructured.** The schema is documented in comments only (`events.py:103, 113, 118, …`). No pydantic validation of payload. A misspelled `tokens_in` key silently breaks the reducer.
- **`VerificationLayer._validate_structured` is shallow** (`verification.py:172-189`): only checks `required` fields exist, doesn't validate types, doesn't follow nested schema. Real JSON Schema validation would catch more.
- **Most specialists use `output_schema` (JSON Schema dict), not `pydantic_model`.** The stronger path is rarely used.
- **`Specialist._parse_and_validate_output` returns failure as a dict, not an exception** (`specialists/base.py:323-330, 345-353, 358-367`). Callers must check `success` field — easy to forget.
- **`LLMResponse.usage.cost_usd` has no validation that it's `>= 0`.** A buggy provider returning negative cost would corrupt `CostGuard.spent_usd`.
- **`LiteLLMProvider` accepts `response_schema` but ignores it** (`litellm_provider.py:59` comment: "Accepted but ignored"). Structured outputs aren't actually enforced for real LLMs.
- **No schema registry.** Specialists define their own schemas; no central place to discover or validate them.
- **`HITLGate.ttl_s` has `ge=60, le=604800`** — but no enforcement that the TTL is actually respected (no timeout mechanism in executor).
- **No schema evolution story.** A field rename breaks old saved Threads.

### 10. Persistence — 50/100

**Files:** `arnes/thread/thread.py:137-176`, `arnes/playbooks/executor.py`

**Strengths**
- `Thread.to_json()` / `from_json()` use pydantic `model_dump_json` / `model_validate_json` — proven round-trip.
- `Thread.save(path)` / `load(path)` file-based API (`thread.py:146-153`).
- JSON is human-readable (`indent=2`), UTF-8 encoded.
- Tests verify round-trip (`test_to_json_roundtrip`, `test_save_load_disk`).
- `Thread.from_events()` supports replay from any sequence.

**Issues**
- **File-based only.** No SQLite, no Postgres, no Redis. The README claims "persisted to SQLite/Postgres" (`thread.py:9`) — **not implemented**.
- **No thread index.** Can't query "all threads from today" or "all failed runs" without scanning the filesystem.
- **No incremental save.** Whole thread serialized each time — O(N) per save.
- **No compression.** A 1000-event thread with full `data` dicts could be megabytes.
- **No encryption at rest.** Threads may contain sensitive user data (PII, code, secrets in diffs).
- **No versioning.** Schema changes break old saved threads. No migration path.
- **No resume across process restarts.** `Thread.save/load` exist but the executor never calls them. A crashed run can't be resumed.
- **No multi-process safe writes.** No `flock`, no atomic rename — concurrent writers can corrupt files.
- **No archive/compact API.** Threads grow unbounded; no way to drop `STEP_STARTED` events after the corresponding `STEP_COMPLETED`.
- **No content hashing for deduplication.** Two identical runs produce two full thread files.
- **`arnes_get_events` MCP tool advertised in README but not implemented** (per `ARCHITECTURE_AUDIT.md` §3.4) — clients can't fetch a thread's event log over MCP.

---

## Top 5 Critical Data Issues

1. **14 of 24 `EventType` values are never emitted.** `AssistantMessageEvent`, `UserMessageEvent`, `CostThresholdEvent`, `MODEL_ROUTED`, `CACHE_HIT`, `CONTEXT_COMPACTED`, `REFUSAL_TRIGGERED`, `CONFIDENCE_SCORED`, `PARALLEL_BRANCH_STARTED`, `PARALLEL_BRANCH_COMPLETED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_PAUSED`, `RUN_RESUMED` are defined, the reducer handles them, but **no production code instantiates them**. Result: `thread.reduce()` returns 0 for tokens/cost/messages even after a real run. The bitácora can't answer "what did the LLM say?" or "was this cached?". **Impact: audit trail fundamentally incomplete.** (Fix: wire CostGuard/TokenOptimizer/VerificationLayer/Specialist to emit these events into the Thread. ~1 day.)

2. **Token/cost data exists in `PlaybookRunResult` but not in `Thread`.** The executor accumulates `total_tokens_in`, `total_tokens_out`, `total_cost_usd` in `run()` (`executor.py:113-114, 149-151`) but only writes them to the `RunCompletedEvent.data` as an aggregate. Per-step `StepCompletedEvent.data` carries only `step_id`, `output`, `duration_s` — no tokens, no cost. The reducer has no way to reconstruct per-step spend from the Thread. **Impact: cannot answer "which step cost the most?" from the audit trail.** (Fix: extend `StepCompletedEvent.data` schema to include `tokens_in`, `tokens_out`, `cost_usd`; update reducer. ~2 hours.)

3. **`LiteLLMProvider` doesn't implement `peek_cost`.** Pre-flight budget checking — advertised as the "killer differentiator" vs OpenHands/browser-use/CrewAI — only works with the test mock. Real LLM calls can't be rejected before spend. The 6 edge-case tests in `tests/stress/test_budget_edge_cases.py` all pass with `ConfigurableCostProvider`, but real providers (Ollama, LiteLLM) return `None` from `peek_cost`, so the pre-flight path is skipped. **Impact: false sense of safety — users think they have budget enforcement but they don't.** (Fix: implement `peek_cost` in `LiteLLMProvider` using the existing pricing table + `tiktoken` for token estimation. ~4 hours.)

4. **Middleware ordering is inconsistent and breaks cache correctness.** Per `ARCHITECTURE_AUDIT.md` §3.3, the middleware stack order differs depending on entry point (executor wraps with `CostGuard(provider)` only; specialist auto-wraps with `CostGuard(Verification(TokenOptimizer(provider)))`). When `TokenOptimizer` is outside `VerificationLayer`, refusals get cached (the LLM's pre-refusal response is stored, then verification replaces the content but the cache already has the original). Subsequent identical requests get the unverified response from cache. **Impact: refusals silently bypassed; potential hallucination/P0 data integrity bug.** (Fix: standardize middleware order to `CostGuard(Verification(TokenOptimizer(provider)))` everywhere; never cache refusal responses. ~4 hours.)

5. **`Thread.append` is O(N) per call → O(N²) for N events.** Building a 1000-event thread does ~500k list copies. The stress test (`tests/stress/test_large_playbook.py:351-385`) explicitly benchmarks this and prints timings, but it's unfixed. A 10k-step playbook would take minutes just on append. **Impact: scaling cliff; long playbooks become prohibitively slow.** (Fix: use `pyrsistent.pvector` for structural sharing, or batch appends via `extend` with a single copy, or switch to an append-friendly persistent data structure. ~1 day.)

---

## Top 5 Improvements Needed

1. **Wire middleware to emit Thread events.** Add `CostGuard.emit_event(thread)`, `TokenOptimizer.emit_event(thread)`, `VerificationLayer.emit_event(thread)` hooks (or pass a `thread_holder` into middleware constructors). Emit `CACHE_HIT`, `MODEL_ROUTED`, `REFUSAL_TRIGGERED`, `COST_THRESHOLD`, `ASSISTANT_MESSAGE` on every decision. This single change makes the bitácora complete and the reducer accurate. ~1 day.

2. **Add per-step token/cost to `StepCompletedEvent`.** Extend the data schema; update the reducer to aggregate. Add a `cost_breakdown: dict[str, float]` to `PlaybookRunResult`. ~2 hours.

3. **Implement `peek_cost` in `LiteLLMProvider` and `OllamaProvider`.** Use the pricing table + `tiktoken` (or `litellm.token_counter`) for input token estimation. Output tokens are unknowable pre-call — estimate as `max_tokens * output_price` (conservative upper bound) or skip output cost in pre-flight. ~4 hours.

4. **Replace `Thread.append` O(N) copy with a persistent data structure.** Either `pyrsistent.pvector` (O(log N) append via structural sharing) or a simpler internal `events: tuple` with batched `extend`. Add a benchmark in CI to prevent regression. ~1 day.

5. **Add a `ThreadStore` persistence abstraction with SQLite implementation.** Interface: `save(thread)`, `load(thread_id)`, `list(filter)`, `delete(thread_id)`. Implementations: `FileThreadStore` (current), `SqliteThreadStore` (new), `PostgresThreadStore` (future). Index by `thread_id`, `created_at`, `status`. Add resume API to executor: `executor.resume(thread)`. ~2 days.

---

## Verdict

**NO-GO for public release.**

The data layer has the right **shape** (event-sourced, immutable, pydantic-validated, pure reducer) but is **operationally incomplete**:

- The audit trail (bitácora) is missing token/cost data, cache decisions, refusals, and model routing — five of the most important things to audit in an agent run.
- The "killer differentiator" (pre-flight budget check) doesn't work with real LLM providers.
- Thread state and `PlaybookRunResult` disagree on token/cost totals (data inconsistency).
- `Thread.append` has a known O(N²) scaling cliff.
- Persistence is file-only with no index, no resume, no encryption.

**Three of the top five issues are <1 day fixes each** (emit missing events, add token/cost to StepCompletedEvent, implement peek_cost). With those three fixes the score would jump from 63 to ~75 and the bitácora would become genuinely useful.

**Recommendation:** GO for private alpha with documented caveats ("audit trail incomplete; pre-flight budget check requires mock provider; persistence is file-only"). NO-GO for public v1.0 until at least the top 3 critical issues land.

---

## Appendix: Cross-References to Prior Audits

This data-focused audit confirms and extends findings from:
- `ARCHITECTURE_AUDIT.md` §3.10 (Thread immutable but executor mutates holder) — confirmed, see Dimension 2.
- `ARCHITECTURE_AUDIT.md` §3.12 (In-memory cache will cause OOM) — confirmed, see Dimension 6.
- `ARCHITECTURE_AUDIT.md` §3.13 (No persistence layer) — confirmed, see Dimension 10.
- `ARCHITECTURE_AUDIT.md` §3.14 (Observability insufficient for production) — confirmed, see Dimension 3.
- `ARCHITECTURE_AUDIT.md` §3.4 (`arnes_get_events` MCP tool missing) — confirmed, see Dimension 10.

Novel findings not in prior audits:
- 14/24 event types are dead code (Dimension 1).
- Token/cost data inconsistency between `PlaybookRunResult` and `Thread.reduce()` (Dimension 2 + 7).
- Cache key excludes `temperature` — correctness bug (Dimension 6).
- Refusals get cached when `TokenOptimizer` is outside `VerificationLayer` (Dimension 6).
- `LiteLLMProvider` doesn't implement `peek_cost` — pre-flight check broken for real providers (Dimension 7).
- `estimated_savings_usd` uses flat $3/1M tokens — misleading (Dimension 3 + 6).
- Internal sentinel keys (`__resolved_str__`, `__input__`, `__skip_steps_until`) leak into MCP outputs (Dimension 5).
