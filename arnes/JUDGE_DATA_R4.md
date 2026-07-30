# JUDGE-DATA-R4 — ARNES Data Quality Final Evaluation

**Auditor:** Senior Data Engineer (judge role, final round)
**Date:** 2026-07-31
**Cycle:** Round 4 — final evaluation
**Subject:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Prior scores:** R1 = 63 (NO-GO) → R2 = 76 (CONDITIONAL GO) → R3 = 79 (GO)
**Method:** Static re-review of `arnes/thread/{events,thread}.py`, `arnes/playbooks/executor.py`, `arnes/middleware/{cost_guard,verification,token_optimizer}.py`, `arnes/llm/{base,litellm_provider,ollama,mock}.py`, `arnes/specialists/base.py`, `arnes/mcp/server.py`. Ran the full test suite (207/207 pass, 73.01% coverage), `pytest tests/stress/test_large_playbook.py` (Thread.append scaling), `pytest tests/stress/test_concurrent.py` (parallel branches), and a live mock run of `manuals/hello-world.yaml` to inspect the produced bitácora.

---

## 0. Verification of Round-3 Critical Fixes

| # | R3 Critical Issue | R4 Status | Evidence |
|---|---|---|---|
| 1 | `Thread.append` O(N) per call → O(N²) | ✅ **FIXED** | `arnes/thread/thread.py:84–99` now does `self.events.append(event); return self` — O(1) per call. The R1/R2/R3 longest-standing critical issue is finally closed. Stress test confirms: append x100 = 0.50 ms (5.04 us/append), x500 = 2.48 ms (4.97 us/append), x1000 = 5.12 ms (5.12 us/append) — **perfectly linear**, 8.8x speedup vs the R3 O(N²) implementation. The docstring (thread.py:13–27) explains the immutability→mutation tradeoff: in-place mutation is safe because ARNES is single-threaded async; coroutine interleaving cannot tear a `list.append` (atomic in CPython); `_drain_middleware_events` runs synchronously inside each step; callers needing isolation across coroutines (parallel sub-steps) explicitly copy via `Thread(id=..., events=list(...))`. `Thread.extend(events)` added (thread.py:101–109) for bulk-append. |
| 2 | 8 of 24 `EventType` values never emitted | ⚠️ **PARTIAL (4 of 8 closed)** | R4 closes 4: `MODEL_ROUTED` (`token_optimizer.py:176–204` `_emit_model_routed(...)`), `PARALLEL_BRANCH_STARTED` (`executor.py:588–600`), `PARALLEL_BRANCH_COMPLETED` (`executor.py:687–699` with `sub_step_outcomes`), `RUN_PAUSED` (`cost_guard.py:319–331` at 95% interactive pause). **5 remain dead:** `CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_RESUMED`, `USER_MESSAGE`. The R3 "8 remain dead" finding is now "5 remain dead." |
| 3 | `TokenOptimizer._route_model` doesn't emit `MODEL_ROUTED` | ✅ **FIXED** | `token_optimizer.py:176–204` `_emit_model_routed(...)` fires whenever routing actually downgrades the requested model (no event when the requested model is kept as-is). Payload: `from_model`, `to_model`, `reason`, `input_tokens_est`. Routed decisions are now visible in the bitácora. The R3 "routing-decision observability gap remains" finding is closed. |
| 4 | Estimated savings uses flat $3/1M heuristic | ❌ **STILL OPEN** | `token_optimizer.py:313` still uses `self._tokens_saved * 0.000003` (flat $3/1M-tokens heuristic). The per-model pricing table that `LiteLLMProvider` has (`litellm_provider.py:11–22`) is still not reused for accurate savings. |
| 5 | Cache is in-memory only | ❌ **STILL OPEN** | `token_optimizer.py:72` still `self._cache: dict[str, CacheEntry] = {}` with no persistence across runs. 1000-entry LRU eviction exists. No Redis/disk backend option. Long-running MCP servers accumulate up to `cache_max_entries=1000` then evict. |
| 6 | Internal sentinel keys leak into MCP outputs | ⚠️ **PARTIAL (preserved from R3)** | `mcp/server.py:243` filters `__`-prefixed keys from `outputs` (preserved). **But** `__skip_steps_until`, `__resolved_str__`, `__input__` still leak into the `PlaybookRunResult.outputs` dict returned to Python callers (`executor.py:271–282`). The filter is MCP-only. |

**Bonus fixes observed:**
- `Thread.extend(events)` (thread.py:101–109) — bulk-append companion to `append`, used by `_execute_parallel` to merge sub-step deltas back into the parent thread via `thread_holder[0] = thread_holder[0].extend(merged_events)` (executor.py:644). O(k) for k events.
- `PARALLEL_BRANCH_COMPLETED` payload (executor.py:687–699) includes `sub_step_outcomes` — a list of `{sub_step_id, success, error}` dicts for every sub-step. The audit log now records not just "a parallel block ran" but "which sub-steps succeeded, which failed, and what the errors were."
- The parallel-branch executor now snapshots the parent thread *after* emitting `PARALLEL_BRANCH_STARTED` (executor.py:600–604) so the STARTED event is part of every sub-step's `parent_event_count` baseline — a subtle correctness fix that prevents the STARTED event from being double-counted as a sub-step delta during merge.
- `RUN_PAUSED` event (cost_guard.py:319–331) carries `reason: "cost_pause_threshold"`, `spent_usd`, `budget_usd`, `pct_used`, `interactive: True` — the audit log now records *that* the run is paused (RUN_PAUSED) in addition to *what the user must do* (HumanApprovalRequestedEvent). The reducer's `RUN_PAUSED` branch (thread.py:299–300) sets `state["status"] = "paused"` — the state machine's "paused" state is now genuinely reachable.
- Coverage on `arnes/thread/events.py` is now 99% (preserved from R3). `arnes/thread/thread.py` is 81% (preserved). `arnes/middleware/cost_guard.py` 92% (preserved). `arnes/middleware/verification.py` 89% (preserved). `arnes/middleware/token_optimizer.py` 85% (preserved). `arnes/llm/litellm_provider.py` 0% → **96%** (20 new tests).

---

## 1. Scorecard

| # | Dimension | R1 | R2 | R3 | R4 | Δ(R3→R4) | Weight | Weighted |
|---|-----------|---:|---:|---:|---:|---:|-------:|---------:|
| 1 | Event log design | 72 | 82 | 83 | **88** | +5 | 15% | 13.20 |
| 2 | State management (reducer) | 65 | 82 | 84 | **86** | +2 | 12% | 10.32 |
| 3 | Observability | 58 | 78 | 80 | **86** | +6 | 10% | 8.60 |
| 4 | Audit trail (bitácora) | 55 | 80 | 84 | **88** | +4 | 12% | 10.56 |
| 5 | Data flow (templates) | 70 | 72 | 73 | **73** | 0 | 10% | 7.30 |
| 6 | Cache design | 55 | 78 | 78 | **78** | 0 | 8% | 6.24 |
| 7 | Cost tracking | 65 | 82 | 86 | **88** | +2 | 10% | 8.80 |
| 8 | Performance data | 72 | 72 | 72 | **88** | +16 | 5% | 4.40 |
| 9 | Data validation | 65 | 68 | 78 | **78** | 0 | 10% | 7.80 |
| 10 | Persistence | 50 | 52 | 53 | **53** | 0 | 8% | 4.24 |
| | **OVERALL** | **63** | **76** | **79** | **81** | **+2** | 100% | **81.46** |

**Overall data score: 81 / 100** (R3: 79 — +2 points)

---

## 2. Dimension-by-Dimension (delta-only notes)

### 1. Event log design — 83 → **88** (+5)

**Fixed:** 4 more event types now have producers:
- `MODEL_ROUTED` (`token_optimizer.py:176–204`) — fires when routing downgrades the requested model. Payload: `from_model`, `to_model`, `reason`, `input_tokens_est`.
- `PARALLEL_BRANCH_STARTED` (`executor.py:588–600`) — fires before `asyncio.gather`. Payload: `step_id`, `sub_step_ids`, `sub_step_count`.
- `PARALLEL_BRANCH_COMPLETED` (`executor.py:687–699`) — fires after merge. Payload: `step_id`, `all_success`, `sub_step_outcomes` (per-sub-step success/error), `merged_event_count`.
- `RUN_PAUSED` (`cost_guard.py:319–331`) — fires at 95% interactive pause. Payload: `reason: "cost_pause_threshold"`, `spent_usd`, `budget_usd`, `pct_used`, `interactive: True`.

R3 had 8 dead types; R4 closes 4. **5 remain dead:** `CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_RESUMED`, `USER_MESSAGE`. The `EventUnion` discriminated union (`events.py:206–222`) is still declared but unused — the reducer still dispatches on `event.type` with `if/elif` chains.

**Still weak:** The payload `data: dict[str, Any]` is still unstructured. The dead types are a maintenance smell — either implement them or remove them from the enum.

### 2. State management (reducer) — 84 → **86** (+2)

**Fixed:** `RUN_PAUSED` now has a producer. The reducer's `RUN_PAUSED` branch (thread.py:299–300) sets `state["status"] = "paused"` — the state machine's "paused" state is now genuinely reachable from the cost-guard middleware, not just a declared-but-unreachable enum value.

**Still weak:** Sentinel keys (`__skip_steps_until`, `__resolved_str__`, `__input__`) still leak into `PlaybookRunResult.outputs` for Python consumers (only filtered at the MCP boundary). The reducer's `step_id` lookup from `event.data` rather than `event.step_id` for cost events (because the executor patches `thread_id` but not always `step_id` on drained middleware events) is a minor attribution bug.

### 3. Observability — 80 → **86** (+6)

**Fixed:** Every cost decision (warn/pause/abort/preflight), every cache hit, every refusal, every assistant message, every human-approval-request, every model-routing decision, every parallel-branch boundary, AND every run-pause is now visible in the bitácora. The shared `_events` sink pattern (`cost_guard.py:118–135`) is preserved and working through the streaming path. A reader of the bitácora can now answer: "did the optimizer downgrade my Claude Sonnet call to Haiku?" (`MODEL_ROUTED`), "did the parallel block start and complete?" (`PARALLEL_BRANCH_STARTED/COMPLETED`), "did the run pause for cost approval?" (`RUN_PAUSED` + `HumanApprovalRequestedEvent`).

**Still missing:** `estimated_savings_usd` still flat $3/1M heuristic. No "decisions" summary section at the top of the bitácora — a reader has to scroll through every event to find cache hits, refusals, and cost thresholds.

### 4. Audit trail (bitácora) — 84 → **88** (+4)

**Fixed:** Parallel branches now produce explicit `PARALLEL_BRANCH_STARTED` and `PARALLEL_BRANCH_COMPLETED` boundary events with per-sub-step outcomes. The bitácora can now answer "what did each parallel sub-step do?" with typed boundary markers, not just interleaved `StepStarted`/`StepCompleted` events. The 95% pause produces both `HumanApprovalRequestedEvent` (what the user must do) AND `RUN_PAUSED` (that the run is paused) — a clearer audit signal than R3's HumanApprovalRequestedEvent alone.

**Still weak:** `assistant_message.content` is still the raw LLM response (JSON for specialists) — wrapping long JSON in collapsible `<details>` would improve readability. No "decisions" summary section.

### 7. Cost tracking — 86 → **88** (+2)

**Fixed:** `RUN_PAUSED` event gives a clearer audit signal for the cost-pause case. The reducer now records the "paused" state transition explicitly, not just via the `HumanApprovalRequestedEvent` side effect.

**Still weak:** `OllamaProvider.peek_cost` still not overridden (acceptable since Ollama is $0). `cost_guard.reset()` still clears `_paused`/`_aborted` — naive per-specialist reset re-opens the budget. The temporal circuit breaker fires post-call only. Streaming path is a thin passthrough that bypasses the budget gate until v0.2 (documented).

### 8. Performance data — 72 → **88** (+16) *(largest gain)*

**Fixed:** `Thread.append` is now O(1) per call. Stress test confirms linear scaling: 5.04 us/append at 100 events, 4.97 us/append at 500, 5.12 us/append at 1000. **8.8x speedup** vs the R3 O(N²) implementation. The R1/R2/R3 longest-standing critical issue is finally closed. A 10k-step playbook would take ~50 ms on appends alone (was minutes in R3).

**Still weak:** The 4-chars-per-token heuristic for `input_tokens_est` in `MODEL_ROUTED` is rough (acceptable for a routing decision, not for billing). The `estimated_savings_usd` flat $3/1M heuristic is still not per-model.

### Dimensions 5, 6, 9, 10 — unchanged

- **Data flow (73):** Template resolver still works (multi-`{{ }}` resolved correctly, virtual `output` accessor handles both raw and wrapped step outputs). MCP-boundary filter for sentinel keys preserved.
- **Cache design (78):** Cache key includes `response_schema` (preserved). Refusals set `cached=False` (preserved). 1000-entry LRU eviction exists. Still in-memory only, no persistence, no Redis/disk backend.
- **Data validation (78):** All 5 specialists declare `pydantic_model` (preserved from R3). `VerificationLayer._validate_structured` still only checks `required` fields — no type validation, no enum validation, no nested validation. No retry on validation failure.
- **Persistence (53):** `Thread.save(path)` and `Thread.load(path)` still exist (JSON to disk). No SQLite/Postgres backend. No checkpoint/resume from a specific event index. The parallel-branch snapshot pattern (preserved from R3) technically enables future checkpoint/resume.

---

## Top 3 Remaining Issues

### 1. Cache is still in-memory only — **Medium (persistence)**

`token_optimizer.py:72` still `self._cache: dict[str, CacheEntry] = {}`. No persistence across runs. A long-running MCP server accumulates up to `cache_max_entries=1000` then evicts — a restart loses all cache state. Cross-process sharing (multiple MCP workers) is impossible.

**Fix:** add a `CacheBackend` protocol with `InMemoryCache` (default) and `RedisCache` (optional) implementations. Wire via `TokenOptimizer(provider, cache_backend=RedisCache(url=...))`.

### 2. Sentinel keys leak into `PlaybookRunResult.outputs` for Python consumers — **Low (API hygiene)**

`__skip_steps_until`, `__resolved_str__`, `__input__` are filtered at the MCP boundary (`mcp/server.py:243`) but still surface in `PlaybookRunResult.outputs` for Python callers. A consumer iterating `result.outputs.items()` sees the sentinels.

**Fix:** move them to a separate `executor._internal_state` dict, or filter at the executor boundary too.

### 3. 5 of 24 event types still never emitted — **Low (observability typing)**

`CONTEXT_COMPACTED`, `CONFIDENCE_SCORED`, `HUMAN_APPROVAL_RECEIVED`, `RUN_RESUMED`, `USER_MESSAGE` are declared but never produced. R4 closed 4 of the 8 R3-dead types. Either implement the remaining 5 or remove them from the enum (dead types in a tagged-union are a maintenance smell).

**Fix:** `USER_MESSAGE` should fire when the executor starts a run with `initial_input`. `HUMAN_APPROVAL_RECEIVED` should fire when `cost_guard.reset()` is called after a pause. `RUN_RESUMED` should fire when the run resumes after a pause. `CONFIDENCE_SCORED` and `CONTEXT_COMPACTED` are v0.2/v0.3 features — remove from the enum until implemented.

---

## Verdict

### **GO** for public alpha release.

R1 was NO-GO at 63. R2 was CONDITIONAL GO at 76. R3 was GO at 79. **R4 is 81** and a clean GO for public alpha.

**R3 critical issues closed:**
1. ✅ `Thread.append` O(N²) → O(1) — the longest-standing quality issue across R1/R2/R3 is finally fixed. 8.8x speedup, perfectly linear scaling.
2. ✅ 4 of 8 dead event types now have producers (`MODEL_ROUTED`, `PARALLEL_BRANCH_STARTED/COMPLETED`, `RUN_PAUSED`).
3. ✅ `MODEL_ROUTED` emitted by `TokenOptimizer._route_model`.
4. ✅ Parallel branches produce typed boundary events with per-sub-step outcomes.

**R3 critical issues still open:**
1. ❌ `estimated_savings_usd` still flat $3/1M heuristic.
2. ❌ Cache still in-memory only.
3. ❌ Sentinel keys still leak into Python-consumer `outputs`.
4. ❌ 5 of 24 event types still never emitted.

**Release posture:** Suitable for a **public alpha**. The bitácora is now genuinely auditable for the common cases (sequential steps, parallel branches with typed boundaries, cost thresholds, refusals, cache hits, model routing, assistant messages, human-approval requests, run pauses). The remaining gaps are typing/observability refinements and one persistence issue — none block alpha release.

**Expected score after the 3 remaining items are remediated:** 86–90.

---

*End of report. — JUDGE-DATA-R4*
