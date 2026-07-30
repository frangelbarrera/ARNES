# JUDGE-AI-R2 — ARNES AI Layer Re-Evaluation

**Auditor:** Senior AI Engineer (judge role)
**Date:** 2026-07-31
**Cycle:** Round 2 re-evaluation
**Subject:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Prior score (R1):** 50 / 100 — NO-GO for public release
**Method:** Static re-review of `arnes/specialists/base.py`, `arnes/specialists/{planner,coder,reviewer,tester,debugger}.py`, `arnes/middleware/{verification,token_optimizer,cost_guard}.py`, `arnes/llm/{base,ollama,litellm_provider}.py`. Ran `tests/unit/test_fix_ai.py` (26 tests, 26 pass after `pip install litellm`) and the full suite (133 tests pass). Verified each R1 critical issue individually.

---

## 0. Verification of Round-1 Critical Fixes

| # | R1 Critical Issue | Status | Evidence |
|---|---|---|---|
| 1 | Ollama provider cannot do tool use | ✅ **FIXED** | `ollama.py:52-53` now passes `tools` into the Ollama `/api/chat` payload. `ollama.py:75-101` parses `message.tool_calls` from the response, normalizes to OpenAI shape (`{"id": ..., "type": "function", "function": {"name": ..., "arguments": "<json-str>"}}`), and converts dict arguments to JSON strings (matching the OpenAI contract that `_execute_tool_call` in `specialists/base.py:258` expects). 3 tests in `tests/unit/test_fix_ai.py::TestOllamaProvider` verify tools-passed, tool_calls-parsed, no-tool-calls-returns-empty. The ReAct loop is no longer dead on the default model. |
| 2 | Anti-hallucination false positive on JSON | ✅ **FIXED** | `verification.py:108-116` tracks `json_mode_active` when `response_schema` is set. `verification.py:201` skips `_detect_hedging` when `json_mode_active=True` — the schema validation check (`verification.py:212-219`) is the real guard in JSON mode. The R1 repro (`{"summary": "I'm not sure about the auth flow"}`) no longer triggers a refusal. 2 tests in `tests/unit/test_fix_ai.py::TestHedgingJSONMode` verify both branches: hedging-skipped-in-JSON-mode and hedging-still-runs-without-JSON-mode. |
| 3 | 0% test coverage on Ollama/LiteLLM providers | ⚠️ **PARTIAL** | 3 Ollama tests added (`TestOllamaProvider`) and 3 LiteLLM `peek_cost` tests added (`TestLiteLLMPeekCost`). However: (a) `LiteLLMProvider.complete()` body (lines 60-133) is still 0% covered — no test calls `litellm.acompletion` against a real LLM. (b) `OllamaProvider.complete()` is covered only via monkey-patched `httpx` (no integration test against a real Ollama daemon). (c) `mcp/server.py` is still 0% covered. The R1 "0% coverage" finding is partially closed but the contract-test gap remains. |
| 4 | `pydantic_model` plumbed but unused | ⚠️ **PARTIAL** | Only `@reviewer` now uses `pydantic_model=ReviewerOutput` (`reviewer.py:95`) — type-safe enum validation for `verdict` and `severity` (rejects `verdict: "ok"` where the schema only allows `approve|request_changes|reject`). The other 4 specialists (`@planner`, `@coder`, `@tester`, `@debugger`) still use only `output_schema` (weak JSON-schema "required fields" check). The plumbing in `specialists/base.py:139-141, 438-456` is correct and works end-to-end when used. The "1/5 specialists" adoption is the gap. |
| 5 | `pause_at_pct` HITL not implemented | ❌ **NOT FIXED** | `cost_guard.py:279` still has `# TODO v0.2: emit HumanApprovalRequestedEvent and block`. The `_paused` flag (`cost_guard.py:110, 409`) is still never set to True on the threshold path. Only a `logger.warning` fires. The killer differentiator vs OpenHands/browser-use is still documented but not coded for the pause case. Hard-stop at 100% works; pause at 95% does not. |

**Bonus fixes observed:**
- `_clean_json_response` (`specialists/base.py:492-523`) strips ```` ```json ```` / ```` ``` ```` fences from LLM responses — necessary because Llama 3.2 ignores `response_format: json_object` and wraps output in markdown. 6 tests verify fenced, bare, single-line, language-tag, no-fences, non-string paths.
- `Specialist.run` has an explicit `max_iterations`-exceeded branch (`specialists/base.py:219-236`) — returns a clear error `"Specialist exceeded max_iterations (N) without producing a final response"` instead of validating an empty/intermediate tool-call payload. Test `TestSpecialistMaxIterations` confirms.
- `Specialist.run` tracks `final_response` separately from intermediate tool-call responses (`specialists/base.py:150-191`) — closes the "phantom output from intermediate tool-call" bug.
- `LiteLLMProvider.complete` no longer reassigns `kwargs` to a local dict (the `kwargs` shadowing bug from R1-C1 is fixed): now builds `call_kwargs` and updates with caller-supplied kwargs (`litellm_provider.py:80-92`).
- `LiteLLMProvider.peek_cost` implemented with the existing pricing table (`litellm_provider.py:138-164`). CostGuard pre-flight now fires for real paid providers (`cost_guard.py:216-254`).
- Middleware classes (`CostGuard`, `VerificationLayer`, `TokenOptimizer`) all inherit from `LLMProvider` and expose `peek_cost` via duck-typing delegation — the chain works end-to-end.
- `VerificationLayer` emits `REFUSAL_TRIGGERED` events (`verification.py:150-176`) with `original_content_preview` and `validation_errors` for observability.
- `TokenOptimizer` emits `CACHE_HIT` events (`token_optimizer.py:147-173`) with `tokens_saved` and `hit_count`.
- `CostGuard` emits `CostThresholdEvent` on warn/pause/abort/preflight thresholds (`cost_guard.py:194-298`).
- 26 new tests in `tests/unit/test_fix_ai.py` (105 → 133 total).

---

## 1. Scorecard

| # | Dimension | R1 | R2 | Δ | Weight | Weighted |
|---|-----------|---:|---:|---:|-------:|---------:|
| 1 | Specialist prompt quality | 62 | **68** | +6 | 10% | 6.80 |
| 2 | ReAct tool-use loop | 48 | **72** | +24 | 12% | 8.64 |
| 3 | Structured output validation | 45 | **68** | +23 | 12% | 8.16 |
| 4 | Anti-hallucination layer | 38 | **70** | +32 | 10% | 7.00 |
| 5 | Token optimization | 52 | **68** | +16 | 8% | 5.44 |
| 6 | Cost guard | 58 | **70** | +12 | 10% | 7.00 |
| 7 | Playbook DSL expressiveness | 55 | **58** | +3 | 10% | 5.80 |
| 8 | LLM provider abstraction | 50 | **72** | +22 | 10% | 7.20 |
| 9 | Default model viability | 35 | **58** | +23 | 10% | 5.80 |
| 10 | AI pattern innovation | 65 | **68** | +3 | 8% | 5.44 |
| | **OVERALL** | **50** | **67** | **+17** | 100% | **67.28** |

**Overall AI score: 67 / 100** (R1: 50 — **+17 points**)

---

## 2. Dimension-by-Dimension (delta-only notes)

### 1. Specialist prompt quality — 62 → **68** (+6)

`@reviewer` now has both a JSON-schema `output_schema` AND a `pydantic_model=ReviewerOutput` (`reviewer.py:78-98`). The dual declaration is belt-and-suspenders: the JSON schema is what's sent to the LLM as `response_schema`; the pydantic model is what validates the parsed response at the specialist layer. Type-safe enum validation for `verdict` (approve|request_changes|reject) and `severity` (critical|major|minor|nit) catches malformed responses the JSON-schema check would miss.

**Still weak:** only 1/5 specialists converted. `@planner`, `@coder`, `@tester`, `@debugger` still use only `output_schema`. The R1 critical issue #4 explicitly called out "convert all 5 specialists to use `pydantic_model`" — only `@reviewer` was converted. A `verdict: "ok"` would slip past validation on the other 4 (their schemas don't have enums, but they have arrays and nested objects that pydantic would type-check). **No specialist system prompt has been updated with "Return ONLY valid JSON, no prose, no code fences"** — the R1 improvement #2 is not implemented. The `_clean_json_response` helper compensates for fences, but adding the explicit instruction to every prompt would reduce the failure rate at the source.

### 2. ReAct tool-use loop — 48 → **72** (+24)

The biggest jump. Three fixes combine:
1. Ollama now passes `tools` through and parses `tool_calls` from the response — the loop is no longer dead on the default model.
2. `max_iterations` exceeded now returns a clear error (`specialists/base.py:219-236`) instead of validating an empty tool-call payload.
3. `final_response` is tracked separately from intermediate tool-call responses (`specialists/base.py:150, 189-191`) — closes the "phantom output from intermediate tool-call" bug.

The loop itself is unchanged structurally: `for iteration in range(self.config.max_iterations)` → call provider → if no `tool_calls`, set `final_response` and break → else execute each tool call, append result, continue. The `max_iterations=5` default is reasonable. The `_execute_tool_call` correctly resolves the tool by name from the available tools list, parses JSON arguments, and handles the HITL approval flow.

**Still weak:** no streaming (each iteration is a blocking `await`). No tool-result truncation (a 100KB tool result is sent back to the LLM verbatim — context bloat). No "tool not found" recovery (the LLM is told "Tool 'X' not available" but the loop doesn't re-prompt with the corrected tool list).

### 3. Structured output validation — 45 → **68** (+23)

Three fixes:
1. `_clean_json_response` strips markdown fences before parsing — necessary for Llama 3.2.
2. `pydantic_model` is actually used (on `@reviewer`): `model_validate(parsed)` runs full type+enum validation (`specialists/base.py:438-456`).
3. `effective_response_schema` falls back to `pydantic_model.model_json_schema()` when `output_schema` is None (`specialists/base.py:139-141`) — specialists that only declare a pydantic model still get JSON-mode forcing in the VerificationLayer.

**Still weak:** the 4 non-reviewer specialists use only `output_schema` (weak JSON-schema "required fields" check). No retry on validation failure — the specialist returns `{"success": False, "error": "LLM did not return valid JSON..."}` instead of retrying with a corrective prompt. `VerificationLayer._validate_structured` only checks `required` fields (`verification.py:239-256`) — no type validation, no enum validation, no nested validation. The pydantic-model path is the real guard; the JSON-schema path is cosmetic.

### 4. Anti-hallucination layer — 38 → **70** (+32)

The biggest percentage jump. The R1 false-positive bug (hedging detection on raw JSON content) is fixed by skipping hedging when `json_mode_active=True` (`verification.py:201`). The schema validation check is the real guard in JSON mode. `REFUSAL_TRIGGERED` events are now emitted with `original_content_preview`, `confidence`, and `validation_errors` (`verification.py:150-176`) — the audit trail shows why a response was refused. `response.usage.cached = False` is set on refusals (`verification.py:142`) — refusals are never cached.

**Still weak:** confidence is still hardcoded at 0.8 default (`verification.py:190`) — no actual confidence scoring. The `confidence_gate` config field is still `None` (disabled in v0.1) — the R1 roadmap item for v0.2. Critic loop (second-opinion agent) and grounding RAG are still v0.3/v0.4. The refusal message is a static string (`verification.py:53`) — no contextual information about why the response was refused.

### 5. Token optimization — 52 → **68** (+16)

The cache-poisoning bug from R1 Dimension 6 is closed: cache key now includes `response_schema` (`token_optimizer.py:230-242`). Two calls with the same messages but different output schemas can no longer return each other's cached responses. `CACHE_HIT` events are emitted (`token_optimizer.py:147-173`) with `tokens_saved` and `hit_count` — the audit trail shows cache decisions.

**Still weak:** routing still silently downgrades models (`token_optimizer.py:175-191`) — `MODEL_ROUTED` events are still never emitted (only structlog logs). The R1 finding "routing silently downgrades premium models" is partially addressed (the cache key is now correct) but the routing-decision observability gap remains. `estimated_savings_usd` still uses the flat $3/1M-tokens heuristic (`token_optimizer.py:276`) — the per-model pricing table that `LiteLLMProvider` has could be reused for accurate savings. Cache is still in-memory only — no persistence across runs.

### 6. Cost guard — 58 → **70** (+12)

Pre-flight cost checking now works for real paid providers via `LiteLLMProvider.peek_cost` (`litellm_provider.py:138-164`). `CostGuard._peek_cost` (`cost_guard.py:347-384`) uses duck-typing delegation so the chain works through `TokenOptimizer` and `VerificationLayer` middleware. The conservative lower-bound estimate (input-only) is documented as a safe-direction choice. `CostThresholdEvent` is emitted on warn/pause/abort/preflight thresholds — the audit trail shows every budget decision.

**Still weak:** `pause_at_pct` (95% threshold) is still not implemented — `_paused` is never set to True, only `logger.warning` fires (`cost_guard.py:256-278`). The `# TODO v0.2` comment at line 279 confirms this is deferred. The killer differentiator works for hard-stop (100%) but not for HITL pause (95%). `OllamaProvider.peek_cost` is not overridden (returns `None` from the base class) — local users get no pre-flight protection, though since Ollama is $0, this is acceptable. Circuit breaker (`max_usd_per_minute`) works but is untested against real traffic patterns.

### 7. Playbook DSL expressiveness — 55 → **58** (+3)

Unchanged from R1. The 5 schema fields (`requires`, `conditionals`, `RetryPolicy`, `timeout_s`, `HITLGate`) are still parsed but not enforced. Parallel branches still run sequentially (`executor.py:480` — explicit comment "For MVP: sequential execution of 'parallel' steps"). No loops, no imports, no `default_model` propagation. The DSL is still declarative YAML → DAG, which is genuinely differentiated, but the v0.1 implementation is still a subset of what the schema promises.

### 8. LLM provider abstraction — 50 → **72** (+22)

Three R1 bugs fixed:
1. Ollama now passes `tools` and parses `tool_calls` (closes the dead-tool-loop bug).
2. `LiteLLMProvider.complete` no longer reassigns `kwargs` (closes the kwargs-shadowing bug).
3. `LiteLLMProvider.peek_cost` is implemented (closes the dead-pre-flight-check bug).

The ABC is clean: `LLMProvider.complete` declares `response_schema` (R1 contract gap closed). All middleware inherit from `LLMProvider` (R1 dimension #8 issue closed). The `_arnes_wrapped` marker prevents double-wrapping.

**Still weak:** no streaming (`stream_complete` not declared on ABC). `OllamaProvider.peek_cost` not overridden (acceptable for $0 model). `response_schema` is "accepted but ignored" by both Ollama and LiteLLM providers (the JSON-mode forcing is done via `response_format`, not by sending the schema to the LLM). No retry-on-rate-limit. No batch API support.

### 9. Default model viability — 35 → **58** (+23)

The biggest practical improvement. The default path (`ollama/llama3.2`) is no longer inert:
- Tools are passed and parsed → ReAct loop works.
- `_clean_json_response` strips fences → JSON parsing succeeds on Llama 3.2's wrapped output.
- Hedging false-positive is skipped in JSON mode → honest hedging inside JSON fields doesn't trigger refusals.
- `@reviewer` uses pydantic_model → enum validation catches malformed verdicts.

**Still weak:** no "Return ONLY valid JSON" instruction in any specialist prompt. The mock provider returns perfect JSON every time (133 tests pass), but real Llama 3.2 success rate on specialist schemas is still likely ~50-70% (not measured — no integration tests against a real Ollama daemon). The R1 recommendation to switch example playbook defaults to `claude-3-5-haiku` for higher reliability is not implemented — all 5 specialists still default to `ollama/llama3.2`. The R1 recommendation to add `pytest.mark.integration` tests with `ARNES_LIVE_TEST=1` guard is not implemented.

### 10. AI pattern innovation — 65 → **68** (+3)

Small gain from event emission (the bitácora now shows cache/routing/refusal decisions, which is genuinely novel for an agent framework). The YAML DSL + hierarchical cost budget + tool fingerprinting combination remains differentiated. The anti-hallucination middleware stack (5-layer, 2 live) is still unique in the comparator set.

**Still weak:** the ReAct/structured-outputs/anti-hallucination patterns still lag LangChain/CrewAI/instructor in adoption and maturity. No novel pattern was added in this round — the work was catch-up, not innovation.

---

## 3. Top 5 Critical AI Issues (R2)

1. **`pause_at_pct` HITL is still not implemented.** The killer differentiator vs OpenHands/browser-use/CrewAI is documented in the README ("HITL: pause and ask for approval at 95% of budget") but not coded. `cost_guard.py:279` has a `# TODO v0.2` comment. The `_paused` flag is never set to True. Only `logger.warning` fires. The README's "Known Limitations" section honestly says "Cost HITL (pause at X% exceeded) — ⚠️ v0.1 (log warning, auto-pause pending)" — disclosure is honest, but the gap is the single biggest AI-side differentiator-vs-competitors claim that's not yet real. **Fix:** set `self._paused = True` at the 95% threshold, emit `HumanApprovalRequestedEvent`, raise `BudgetExceeded(level="pause")`. Non-interactive path raises; interactive resume can land in v0.2 with MCP support. ~1 day for non-interactive; ~3 days for MCP-interactive.

2. **Only 1/5 specialists use `pydantic_model`.** `@reviewer` has it (`reviewer.py:95`); `@planner`, `@coder`, `@tester`, `@debugger` still use only `output_schema` (weak "required fields" check). The R1 critical issue #4 explicitly called out "convert all 5 specialists to use `pydantic_model`" — only 1 was converted. The plumbing works end-to-end (verified by `_PydanticSpecialist` test), it's just not adopted. **Fix:** define `PlannerOutput`, `CoderOutput`, `TesterOutput`, `DebuggerOutput` pydantic models with full type/enum/nested validation; wire them into each specialist's config. ~1 day.

3. **No "Return ONLY valid JSON" instruction in specialist prompts.** Every specialist system prompt ends with "Return JSON matching this schema: {...}" but none explicitly says "Return ONLY valid JSON, no prose, no code fences." Llama 3.2 frequently wraps JSON in markdown despite `response_format: json_object` being set. The `_clean_json_response` helper compensates downstream, but adding the instruction to every prompt would reduce the failure rate at the source. **Fix:** add `"Return ONLY valid JSON. No prose, no markdown code fences, no commentary before or after the JSON object."` to every specialist system prompt. Add a one-shot example. ~2 hours.

4. **No real-LLM integration tests.** All 133 tests use mock providers that return perfect JSON. The R1 critical issue #3 ("0% test coverage on Ollama/LiteLLM providers") is partially closed: 3 Ollama tests (via monkey-patched httpx) and 3 LiteLLM `peek_cost` tests added. But `LiteLLMProvider.complete()` body is still 0% covered — no test calls `litellm.acompletion` against a real LLM. The test suite cannot detect a real-LLM output shape regression. **Fix:** add `pytest.mark.integration` tests with `ARNES_LIVE_TEST=1` guard that call real Ollama (free, local) and real Anthropic (paid, env-keyed) providers. Add property-based tests for JSON parsing of malformed/fenced/truncated responses. ~2 days.

5. **`MODEL_ROUTED` event is still never emitted.** `TokenOptimizer._route_model` logs routing decisions via structlog (`token_optimizer.py:183-188`) but does not emit a `MODEL_ROUTED` event. The bitácora can answer "what did the LLM say?" and "was this cached?" but not "was the model silently downgraded from Sonnet to Haiku?". This is the most-asked audit question for cost-conscious teams. **Fix:** add `_emit_model_routed(from_model, to_model, reason)` mirror of `_emit_cache_hit` in `TokenOptimizer`. ~30 minutes.

---

## 4. Top 5 Improvements Needed (R2)

1. **Implement `pause_at_pct` HITL (non-interactive first).** Set `_paused = True`, emit `HumanApprovalRequestedEvent`, raise `BudgetExceeded(level="pause")`. The executor already catches `BudgetExceeded`. The interactive resume path can land in v0.2 with MCP support. ~1 day.

2. **Convert the remaining 4 specialists to `pydantic_model`.** Define typed output models with enum/nested validation. Wire them into each `SpecialistConfig`. Run the existing test suite to verify no regression. ~1 day.

3. **Add "Return ONLY valid JSON" to every specialist system prompt.** Plus a one-shot example per specialist. This alone will roughly double success rates on Llama 3.2. ~2 hours.

4. **Add real-LLM integration tests.** `pytest.mark.integration` with `ARNES_LIVE_TEST=1` guard. Test against real Ollama (free) and real Anthropic (paid). Add property-based tests for malformed JSON parsing. ~2 days.

5. **Wire `MODEL_ROUTED` event emission.** Mirror `_emit_cache_hit` in `TokenOptimizer._route_model`. ~30 minutes.

---

## 5. Verdict

### **GO for public alpha (with documented caveats).**

R1 was NO-GO for public release. R2 is **GO for public alpha** — the default model path is no longer inert (tools work, JSON is cleaned, hedging false-positives are skipped), the pre-flight cost check works for real paid providers, the `@reviewer` specialist demonstrates the pydantic_model pattern end-to-end, and the audit trail shows cache/refusal/cost decisions.

The remaining gaps are honestly disclosed in the README's "Known Limitations in v0.1 (Alpha)" section:
- HITL pause not implemented (hard-stop works)
- Only 1/5 specialists use pydantic_model
- No real-LLM integration tests
- `MODEL_ROUTED` not emitted
- Parallel branches still sequential

**For production / untrusted-input use: NO-GO** until:
- `pause_at_pct` HITL is implemented (the killer differentiator)
- All 5 specialists use pydantic_model (closes the schema-validation gap)
- Real-LLM integration tests exist (catches real-LLM regressions)
- "Return ONLY valid JSON" is in every specialist prompt (reduces failure rate at the source)

**Path from 67 → 80:** implement `pause_at_pct` (+3), convert 4 more specialists to pydantic_model (+3), add JSON-only instruction to prompts (+2), add real-LLM integration tests (+3), wire `MODEL_ROUTED` (+1). All ~5 engineer-days total.

---

## 6. Cross-References to Round 1

| R1 Critical Issue | R2 Status | Score Δ |
|---|---|---|
| Ollama cannot do tool use | Fixed — tools passed, tool_calls parsed | +24 (Dim 2) |
| Anti-hallucination false positive on JSON | Fixed — hedging skipped in JSON mode | +32 (Dim 4) |
| 0% coverage on Ollama/LiteLLM | Partial — 6 tests added, complete() body still 0% | +22 (Dim 8) |
| `pydantic_model` plumbed but unused | Partial — 1/5 specialists converted | +23 (Dim 3) |
| `pause_at_pct` HITL not implemented | **Still open** | +12 (Dim 6, from peek_cost fix) |

**Net change: +17 points (50 → 67).** Two of the five R1 critical issues are fully fixed; two are partially fixed; one is unfixed (pause_at_pct). The AI layer crossed from "default model path is non-functional" to "default model path works for alpha."

---

*Prepared by JUDGE-AI-R2. All scores are defensible from the source code at `/home/z/my-project/arnes/` as of 2026-07-31. Re-run this audit after v0.2 ships `pause_at_pct` HITL, the remaining 4 pydantic_model conversions, and the real-LLM integration tests.*
