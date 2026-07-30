# JUDGE-AI-R4 — ARNES AI Layer Final Evaluation

**Auditor:** Senior AI Engineer (judge role, final round)
**Date:** 2026-07-31
**Cycle:** Round 4 — final evaluation
**Subject:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Prior scores:** R1 = 50 (NO-GO) → R2 = 67 (CONDITIONAL GO) → R3 = 73 (GO)
**Method:** Static re-review of `arnes/specialists/{base,planner,coder,reviewer,tester,debugger}.py`, `arnes/middleware/{verification,token_optimizer,cost_guard}.py`, `arnes/llm/{base,litellm_provider,ollama,mock,factory}.py`, `arnes/playbooks/executor.py`, `tests/unit/test_litellm_provider.py`. Ran the full suite (207/207 pass) and a live mock run.

---

## 0. Verification of Round-3 Critical Fixes

| # | R3 Critical Issue | R4 Status | Evidence |
|---|---|---|---|
| 1 | No streaming on `LLMProvider` ABC | ✅ **FIXED (abstract + mock; stubs for Ollama/LiteLLM)** | `llm/base.py:91–122` declares `@abstractmethod async def stream_complete(...) -> AsyncIterator[LLMResponse]` with the standard `...; yield  # type: ignore[misc]` pattern for an abstract async generator. The docstring (lines 104–122) honestly explains: "Streaming lands in v0.2 alongside AG-UI transport support. Until v0.2: `MockLLMProvider` provides a default implementation that yields the full response in a single chunk; `OllamaProvider` and `LiteLLMProvider` raise `NotImplementedError("Streaming coming in v0.2")` if iterated." `llm/mock.py:71–102` implements it (calls `self.complete(...)` then `yield response`). `llm/ollama.py:129–152` and `llm/litellm_provider.py:161–185` raise `NotImplementedError` with explanatory docstrings. `cli/main.py:381–410` `_SchemaValidMockLLMProvider.stream_complete` also yields a single chunk. The middleware `stream_complete` methods (`cost_guard.py:484–519`, `verification.py:302–335`, `token_optimizer.py:326–359`) are thin passthroughs with honest docstrings explaining what's deferred to v0.2 (per-chunk cost accounting, final-chunk verification, cache population from reassembled response, routing-decision emission). **The streaming contract is now real — callers can write streaming-style code today against the mock and get the real stream in v0.2.** |
| 2 | `LiteLLMProvider.complete()` body 0% covered | ✅ **FIXED (0% → 96%, claimed 84%)** | `tests/unit/test_litellm_provider.py` (612 lines, 20 tests across 7 test classes). Tests use real `litellm.types.utils.{ModelResponse,Choices,Message,Usage,ChatCompletionMessageToolCall,Function}` objects and patch `litellm.acompletion` via `monkeypatch.setattr` — never touch the network. Coverage: `TestLiteLLMCompleteBasics` (5 tests: content/model/usage, model+messages forwarding, temperature default, max_tokens forwarding, init+call kwargs merge), `TestLiteLLMCompleteToolCalls` (3: single tool call OpenAI-shape, multiple in order, none → empty list), `TestLiteLLMCompleteCostCalc` (3: known model, anthropic model, fallback pricing), `TestLiteLLMCompleteToolsForwarding` (2: passes tools, omits when None), `TestLiteLLMCompleteResponseFormat` (3: json_object passed, omitted when None, ignores non-json_object), `TestLiteLLMCompleteMissingUsage` (2: missing usage, None content), `TestLiteLLMStreamStub` (2: raises NotImplementedError when iterated, signature accepts standard kwargs). `pytest --cov=arnes/llm/litellm_provider tests/unit/test_litellm_provider.py` → **96% coverage** (only `ImportError` path at lines 64–65 and `list_models` at line 159 uncovered). |
| 3 | `MODEL_ROUTED` events never emitted | ✅ **FIXED** | `token_optimizer.py:176–204` `_emit_model_routed(...)` fires whenever routing actually downgrades the requested model (no event when the requested model is kept as-is). Payload: `from_model`, `to_model`, `reason`, `input_tokens_est`. Routed decisions are now visible in the bitácora. The R3 "routing-decision observability gap remains" finding is closed. |
| 4 | Confidence gate / critic loop / grounding RAG still v0.2/v0.3/v0.4 | ❌ **STILL OPEN** | `VerificationLayer._verify` still hardcodes `confidence = 0.8` default (`verification.py:190`). `confidence_gate` config field still `None` (disabled in v0.1). Critic loop and grounding RAG still v0.3/v0.4. |
| 5 | `OllamaProvider` no integration test against real daemon | ❌ **STILL OPEN** | `arnes/llm/ollama.py` is now 67% covered (preserved from R3). Still no integration test against a real Ollama daemon. |

**Bonus fixes observed:**
- `LiteLLMProvider.peek_cost` (`litellm_provider.py:187–213`) — preserved from R3. Pre-flight cost estimate based on input tokens only, conservative lower bound (output cost unknown), documented as a safe-direction choice for a budget guard.
- `OllamaProvider.complete` now passes `tools` through and parses `tool_calls` from Ollama v0.3.0+ responses (preserved from R3).
- `_clean_json_response` strips markdown fences before parsing (preserved from R3) — necessary for Llama 3.2 which ignores `response_format: json_object`.
- `VerificationLayer._verify` skips hedging detection when `json_mode_active=True` (preserved from R3) — schema validation is the real guard in JSON mode.
- `Specialist.run` tracks `final_response` separately from intermediate tool-call responses (preserved from R3).
- 207 tests pass (was 184 in R3 — +23 new tests, mostly in `test_litellm_provider.py`).

---

## 1. Scorecard

| # | Dimension | R1 | R2 | R3 | R4 | Δ(R3→R4) | Weight | Weighted |
|---|-----------|---:|---:|---:|---:|---:|-------:|---------:|
| 1 | Specialist prompt quality | 62 | 68 | 74 | **74** | 0 | 10% | 7.40 |
| 2 | ReAct tool-use loop | 48 | 72 | 78 | **78** | 0 | 12% | 9.36 |
| 3 | Structured output validation | 45 | 68 | 82 | **82** | 0 | 12% | 9.84 |
| 4 | Anti-hallucination layer | 38 | 70 | 72 | **72** | 0 | 10% | 7.20 |
| 5 | Token optimization | 52 | 68 | 70 | **74** | +4 | 8% | 5.92 |
| 6 | Cost guard | 58 | 70 | 84 | **86** | +2 | 10% | 8.60 |
| 7 | Playbook DSL expressiveness | 55 | 58 | 64 | **64** | 0 | 10% | 6.40 |
| 8 | LLM provider abstraction | 50 | 72 | 80 | **86** | +6 | 10% | 8.60 |
| 9 | Default model viability | 35 | 58 | 60 | **60** | 0 | 10% | 6.00 |
| 10 | AI pattern innovation | 65 | 68 | 70 | **72** | +2 | 8% | 5.76 |
| | **OVERALL** | **50** | **67** | **73** | **75** | **+2** | 100% | **75.08** |

**Overall AI score: 75 / 100** (R3: 73 — +2 points)

---

## 2. Dimension-by-Dimension (delta-only notes)

### 5. Token optimization — 70 → **74** (+4)

**Fixed:** `MODEL_ROUTED` event now emitted by `_emit_model_routed(...)` (token_optimizer.py:176–204). The routing decision is now visible in the bitácora — a user can answer "did the optimizer downgrade my Claude Sonnet call to Haiku?" without grep'ing structlog logs. Payload includes `from_model`, `to_model`, `reason`, `input_tokens_est`.

**Still weak:** `estimated_savings_usd` still uses the flat $3/1M-tokens heuristic (not per-model). Cache is still in-memory only. No context compaction (v0.2). No few-shot pruning (v0.3).

### 6. Cost guard — 84 → **86** (+2)

**Fixed:** `RUN_PAUSED` event now emitted at the 95% interactive-pause threshold (cost_guard.py:319–331). The audit log records both *what the user must do* (HumanApprovalRequestedEvent) AND *that the run is now paused* (RUN_PAUSED). The state machine's "paused" state is now genuinely reachable. Streaming path is a thin passthrough that bypasses the budget gate until v0.2 (documented in the `stream_complete` docstring).

**Still weak:** `OllamaProvider.peek_cost` still not overridden (acceptable since Ollama is $0). `cost_guard.reset()` still clears `_paused`/`_aborted`. The temporal circuit breaker fires post-call only.

### 8. LLM provider abstraction — 80 → **86** (+6)

**Fixed:** `stream_complete` added to the `LLMProvider` ABC as an `@abstractmethod` returning `AsyncIterator[LLMResponse]` (base.py:91–122). The contract mirrors `complete()` — same parameters, same `LLMResponse` shape — but the response is delivered as a sequence of partial chunks instead of a single fully-buffered object. `MockLLMProvider` provides a default implementation that yields the full response in a single chunk (so callers can write streaming-style code today against the mock and get the real stream for free in v0.2). `OllamaProvider` and `LiteLLMProvider` raise `NotImplementedError("Streaming coming in v0.2")` if iterated — clean fail-fast, no silent blocking. The middleware `stream_complete` methods are thin passthroughs with honest docstrings. `LiteLLMProvider.complete()` body now 96% covered (20 new tests with real litellm types).

**Still weak:** No real streaming implementation for Ollama/LiteLLM (only stubs). No batch API. No async context manager for connection pooling. `OllamaProvider` still has no integration test against a real daemon.

### 10. AI pattern innovation — 70 → **72** (+2)

**Fixed:** The streaming API contract lands ahead of v0.2 — callers can write `async for chunk in provider.stream_complete(...)` today and it works against the mock. The `MODEL_ROUTED` event makes the routing-decision observability story real. The `PARALLEL_BRANCH_STARTED/COMPLETED` events with `sub_step_outcomes` make the parallel-execution audit story real. The `RUN_PAUSED` event makes the cost-pause state-machine story real.

**Still weak:** The 5-layer anti-hallucination stack only implements 2 layers in v0.1 (structured outputs + refusal pattern). The other 3 (confidence gate, critic loop, grounding RAG) are roadmap items. The "killer differentiator" is real but partial.

### Dimensions 1, 2, 3, 4, 7, 9 — unchanged

- **Specialist prompt quality (74):** All 5 specialists have `pydantic_model` + `output_schema` (preserved). System prompts still include "You MUST respond with ONLY valid JSON matching the schema." Still no few-shot examples, no prompt-versioning, no A/B testing harness.
- **ReAct tool-use loop (78):** True `asyncio.gather` parallelism preserved. Loop structure unchanged. Still no streaming per iteration, no tool-result truncation, no "tool not found" recovery, no tool-call timeout.
- **Structured output validation (82):** All 5 specialists use `pydantic_model` (preserved). `VerificationLayer._validate_structured` still only checks `required` fields. No retry on validation failure.
- **Anti-hallucination layer (72):** Hedging-detection skip in JSON mode preserved. `REFUSAL_TRIGGERED` events emitted. Confidence still hardcoded at 0.8. Critic loop and grounding RAG still v0.3/v0.4.
- **Playbook DSL expressiveness (64):** Parallel branches execute concurrently (preserved). Still no loops, no imports, no `default_model` propagation, no retry policy execution, no `conditionals:` chain execution.
- **Default model viability (60):** Default is `ollama/llama3.2` (local, free, vendor-neutral). Mock provider returns schema-valid JSON. Still no model-recommendation engine, no automatic downgrade on rate-limit.

---

## Top 3 Remaining Issues

### 1. Streaming stubs raise `NotImplementedError` for real providers — **Medium (UX)**

The streaming API is on the ABC and the mock implements it, but `OllamaProvider.stream_complete` and `LiteLLMProvider.stream_complete` raise `NotImplementedError("Streaming coming in v0.2")` when iterated. This is honest (the docstring says so) and fail-fast (no silent blocking), but it means the streaming UX is not actually available for real LLM calls in v0.1. LangGraph Studio, CrewAI Canvas, OpenHands Web UI, Pydantic AI's FastAPI integration all let you watch an agent think with real models. ARNES gives you a markdown bitácora after the fact — a real differentiator for audits, but a regression for live UX.

**Fix:** implement `OllamaProvider.stream_complete` using Ollama's `/api/chat` with `"stream": true` (SSE). Implement `LiteLLMProvider.stream_complete` using `litellm.acompletion(stream=True)`. Wire to AG-UI in v0.2.

### 2. No real-LLM integration tests — **Medium (test gap)**

All 207 tests use mocks. `LiteLLMProvider.complete()` body is now 96% covered, but only via `monkeypatch.setattr(litellm, "acompletion", mock)` — no test ever calls a real LLM. A regression in the actual litellm response shape (e.g. a new litellm version that renames `usage.prompt_tokens` to `usage.input_tokens`) would not be caught by CI. `OllamaProvider` has no integration test against a real daemon. `vcrpy` is in dev deps but no cassettes are committed.

**Fix:** add `tests/integration/test_litellm_provider.py` that uses VCR.py cassettes to record a real `litellm.acompletion` response and replay it. Cover: basic completion, tool_calls parsing, response_format=json_object, error handling, kwargs forwarding. Add `tests/integration/test_ollama_provider.py` marked `@pytest.mark.integration` that runs against a real Ollama daemon (skipped in CI if `OLLAMA_HOST` not set).

### 3. Confidence gate / critic loop / grounding RAG still v0.2/v0.3/v0.4 — **Low (roadmap)**

The 5-layer anti-hallucination stack only implements 2 layers in v0.1 (structured outputs + refusal pattern). `VerificationLayer._verify` still hardcodes `confidence = 0.8` default. `confidence_gate` config field is still `None` (disabled). Critic loop (second-opinion agent) and grounding RAG (verify claims against knowledge base) are v0.3/v0.4. The "killer differentiator" claim is real but partial.

**Fix:** implement confidence gate in v0.2 (use the LLM's logprobs if available, or a separate confidence-scoring prompt). Implement critic loop in v0.3 (a second specialist reviews the first's response). Implement grounding RAG in v0.4 (verify claims against a knowledge base).

---

## Verdict

### **GO** for public alpha release.

R1 was NO-GO at 50. R2 was CONDITIONAL GO at 67. R3 was GO at 73. **R4 is 75** and a clean GO for public alpha.

**R3 critical issues closed:**
1. ✅ Streaming API on `LLMProvider` ABC (mock implements; stubs fail-fast).
2. ✅ `LiteLLMProvider.complete()` body 0% → 96% covered (20 new tests).
3. ✅ `MODEL_ROUTED` event emitted by `TokenOptimizer._route_model`.

**R3 critical issues still open:**
1. ❌ Streaming stubs raise `NotImplementedError` for real providers (Ollama/LiteLLM).
2. ❌ No real-LLM integration tests (all 207 use mocks).
3. ❌ Confidence gate / critic loop / grounding RAG still v0.2/v0.3/v0.4.
4. ❌ `OllamaProvider` no integration test against real daemon.

**Release posture:** Suitable for a **public alpha**. The AI layer now genuinely works: ReAct loop on the default model, structured outputs with strong pydantic validation on all 5 specialists, anti-hallucination stack with no false positives, hierarchical CostGuard with both hard-stop and HITL-pause (now with `RUN_PAUSED` event), true parallel execution (now with `PARALLEL_BRANCH_STARTED/COMPLETED` boundary events), streaming API contract (forward-compatible), `MODEL_ROUTED` event for routing-decision observability. The trajectory from R1 (50) → R2 (67) → R3 (73) → R4 (75) shows sustained investment in the dimensions that matter most (structured outputs +37 over three rounds, cost guard +28, ReAct loop +30, LLM provider abstraction +36).

**Expected score after the 3 remaining items are remediated:** 82–86.

---

*End of report. — JUDGE-AI-R4*
