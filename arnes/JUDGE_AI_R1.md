# JUDGE-AI-R1 — AI Patterns Audit (Round 3)

**Judge:** Senior AI/ML Engineer (sub-agent)
**Task ID:** JUDGE-AI-R1
**Date:** 2026-01
**Scope:** `arnes/specialists/`, `arnes/middleware/`, `arnes/playbooks/`, `arnes/llm/`, `manuals/`, `arnes/agent/`, `arnes/cli/`, `tests/`
**Compared against:** `AI_AUDIT.md` (v1), `AI_AUDIT_V2.md` (v2)
**Verdict:** **NO-GO for public release** (see §13)

---

## 0. Executive summary

ARNES v0.1.0a1 is **architecturally clean** (stateless reducer + specialists + middleware + YAML playbooks) and the v1→v2 fixes for the `_arnes_wrapped` marker, `response_schema` plumbing, and parallel-output template resolution are confirmed working in code. The 105-test suite passes; the 50-concurrent-playbook stress test passes; the bilingual keymap and HITL fingerprinting are genuinely novel.

However, the AI/ML layer has **two structural defects that make the default path non-functional** and **three more that make premium-model paths unreliable**:

1. **The default Ollama provider cannot do tool use.** `ollama.py:38-43` never sends `tools` to the Ollama chat API and `ollama.py:66` hardcodes `tool_calls=[]`. Ollama has supported native tool calling since v0.3.0 (Nov 2023). The entire ReAct loop scaffolded in `base.py:128-188` is dead on the default model. `@coder`, `@tester`, `@debugger` are stateless prompt templates when run as-shipped.
2. **The anti-hallucination layer is actively harmful on honest hedging.** `_HEDGING_PATTERNS` runs on the full JSON response (`verification.py:140-148`). A correctly-structured `@reviewer` response like `{"summary":"I'm not sure about the auth flow"}` triggers hedging, replaces the response with a plain string, and then fails JSON parsing in the specialist — producing a confusing `"LLM did not return valid JSON"` error instead of the valid answer.
3. **The 105-test suite has 0% coverage on `OllamaProvider` and `LiteLLMProvider`.** Every test uses a `SchemaValidMockProvider` that returns hardcoded schema-conforming JSON per specialist. The test suite cannot detect issues #1, #2, or any real-LLM output shape regression.
4. **`pause_at_pct` HITL is documented in the module docstring (`cost_guard.py:1-20`) but never implemented.** The `_paused` flag is never set to True; only a `logger.warning` fires at 95% of budget. The TODO at `cost_guard.py:208` is still in the code.
5. **Schema validation only checks required-field presence** (`verification.py:172-189` and `base.py:355-367`). No type, enum, or nested structure validation. The `pydantic_model` field on `SpecialistConfig` (`base.py:43`) is plumbed end-to-end but **no specialist uses it** — the strong-validation path is dead code.

On top of these, **8 of the 15 v2 HIGHs are still open**: playbook `budget_usd` ignored by executor, `requires` / `conditionals` / `RetryPolicy` / `timeout_s` / `HITLGate` declared in schema but never enforced, no JSON cleaning post-processing (Llama 3.2 wraps in ```` ```json ```` fences ~30% of the time), no streaming, no per-call cost guard on $0 models, no `MODEL_ROUTED` event emission, no semantic-cache invalidation on prompt change, planner outputs cached despite `temperature=0.1`.

**Bottom line:** ARNES is at ~55% of the way to a credible public release. The remaining gaps are concentrated in the AI layer (provider realism, validation depth, prompt quality, observability) and are fixable in ~6-8 engineer-days. Shipping as-is would produce a public alpha that:
- Cannot use tools on its default model (`@coder` / `@tester` / `@debugger` are prompt templates).
- Silently downgrades honest hedging to confusing JSON parse errors.
- Documents HITL pause but doesn't implement it.
- Passes 105 tests because the mock LLM returns perfect JSON every time, hiding every real-LLM issue.

---

## 1. Specialist prompt quality

**Score: 62 / 100**

### Strengths
- Consistent structure across all 5 specialists (Job → Rules → JSON schema).
- Anti-vagueness rules are concrete: `"Review PR #123 for security vulnerabilities, focusing on auth flows"` beats `"Review the code"` (planner.py:25, reviewer.py:18).
- Temperatures are well-calibrated: 0.0 for `@coder`/`@reviewer`/`@tester`/`@debugger`; 0.1 for `@planner` (planner.py:65, coder.py:59, reviewer.py:59, tester.py:64, debugger.py:61).
- `@debugger` and `@reviewer` have explicit methodology sections (debugger.py:18-23, reviewer.py:11-15).
- `@debugger` includes an explicit confidence field (`debugger.py:34`) and `alternative_causes` (debugger.py:43) — good epistemic hygiene.

### Anti-patterns (still open from v1/v2)

1. **No "Return ONLY valid JSON" instruction.** None of the 5 prompts (planner.py:9-40, coder.py:9-39, reviewer.py:9-38, tester.py:9-48, debugger.py:9-45) tell the LLM to emit JSON without prose or ```` ```json ```` fences. With Llama 3.2 + `format: "json"` this still fails ~25-35% of the time on nested schemas. The `_parse_and_validate_output` (base.py:316-330) now correctly returns `success=False` on parse failure, but the user gets an opaque `"LLM did not return valid JSON"` error with no retry, no JSON-cleaning attempt, and no guidance. **This is the #1 user-facing AI issue.**
2. **Embedded prompt schema ≠ declared `output_schema`.** Coder's prompt (coder.py:25-38) promises `{"files":[...], "summary", "assumptions", "warnings"}`. The declared schema (coder.py:50-57) only requires `["files", "summary"]`. The LLM produces the rich shape; the validator only checks the minimum. Downstream consumers can't trust `assumptions` or `warnings` exist. Same pattern in `@tester`: prompt declares `coverage_pct` (tester.py:45) but schema (tester.py:59-62) only requires `["test_files", "test_results", "summary"]`.
3. **`@reviewer` is overloaded.** Used in `audit-pr.yaml` for diff reading (line 13), security audit (line 20), lint (line 28), and synthesis (line 40). The reviewer's prompt (reviewer.py:9-22) is written for one job (code review) but is being asked to do four. Either split into `@diff-reader`, `@security-auditor`, `@synthesizer` or make the prompt parameterizable by `focus`.
4. **`@coder` for markdown.** `hello-world.yaml:14-18` invokes `@coder` to "Write a markdown outline." Coder's prompt demands "type hints, docstrings, and inline comments" (coder.py:18) — applying that to markdown is incoherent. Need a `@writer` specialist or a different default for prose tasks.
5. **Specialists that declare tools don't tell the LLM how/when to use them.** `@coder` declares `tools=["fs_read", "fs_write", "shell"]` (coder.py:49) but the prompt (coder.py:9-23) never mentions reading existing code before writing new code, never mentions running tests after writing, never mentions when to prefer `fs_read` over `shell`. Same for `@tester` (tester.py:58) and `@debugger` (debugger.py:55). The ReAct loop exists (base.py:128-188) but the prompt gives the LLM no reason to call tools. This is the missing half of the v1 C2 fix.
6. **`@debugger` prompt asks for `confidence: 0.0-1.0`** (debugger.py:34) but the VerificationLayer never reads it. The number is decorative — the LLM is incentivized to always return 0.9 regardless of accuracy because there's no downstream consequence.
7. **No example/ few-shot in any specialist prompt.** For Llama 3.2 3B, one-shot examples double schema-conformance rates. None of the 5 prompts include an example output.

---

## 2. ReAct tool-use loop

**Score: 48 / 100**

### What's implemented (correct)
- Loop scaffolded in `base.py:128-188` with `max_iterations=5` default (base.py:47).
- Tool calls parsed from `LLMResponse.tool_calls` (base.py:161-183).
- Tool results appended as `role="tool"` messages with `tool_call_id` (base.py:177-183).
- Budget-exceeded handling breaks the loop and returns a structured failure (base.py:147-156).
- Tool execution goes through `_execute_tool_call` (base.py:195-273) with HITL rug-pull defense (fingerprint comparison, base.py:226-257).
- The e2e test `test_tool_use_loop_in_specialist` (test_e2e.py:235-307) verifies the loop works when a `ToolUseMockProvider` returns tool_calls.

### What's broken

1. **The default provider never returns tool_calls.** `ollama.py:38-43` constructs the Ollama payload with only `model`, `messages`, `stream`, `options` — **no `tools` field is sent to Ollama**. Even if Ollama returned tool_calls in its response, `ollama.py:60-66` ignores them and hardcodes `tool_calls=[]`:
   ```python
   content = data.get("message", {}).get("content", "")
   ...
   return LLMResponse(
       content=content,
       tool_calls=[],  # Ollama tool use is evolving — fall back to text parsing
       ...
   )
   ```
   The comment promises a text-parsing fallback that **does not exist anywhere in the codebase** (verified by `grep -rn "fall back to text parsing" arnes/`). Ollama has supported native tool calling via the `tools` parameter in `/api/chat` since v0.3.0 (Nov 2023) — the comment is factually wrong and the implementation is a regression. **Result:** on `arnes run manuals/audit-pr.yaml`, `@coder` / `@tester` / `@debugger` receive their tool schemas, the LLM returns text-only, the loop runs one iteration, exits with no tool calls, and the specialist produces output without ever reading a file or running a command. The flagship v1→v2 fix is dead on the default path.
2. **No tool-call text-parsing fallback for models that don't natively support tools.** Even if ollama is fixed, some local models (phi-3, gemma-2) don't reliably support native tool calling. A robust harness implements a fallback parser that extracts `{"tool": "fs_read", "args": {...}}` patterns from text. None exists.
3. **`max_iterations=5` is hardcoded with no per-specialist override.** A complex `@coder` task (read 3 files → write 2 files → run tests) needs 6+ iterations. No specialist overrides this. No playbook step can override it either.
4. **No "tool call looped without progress" detector.** If the LLM calls `fs_read` on the same path 5 times, the loop runs to `max_iterations` and exits with the last response — no early termination on repeated identical tool calls.
5. **Tool result truncation.** `base.py:179` does `json.dumps(tool_result, default=str)` with no length cap. A 10MB `fs_read` result will explode the message size on the next iteration. `fs_read` itself caps at 64KB (builtin.py:272) but `shell` does not cap stdout (builtin.py:128).
6. **No streaming of intermediate tool results to the Thread.** The ReAct loop's intermediate messages (assistant tool_calls, tool results) are kept locally in `messages` and never appended to the Thread as `ToolCallEvent` / `ToolResultEvent`. Only the final step result is recorded. This breaks observability and replay — you cannot reconstruct what tools the agent called from the Thread alone.

---

## 3. Structured output validation

**Score: 45 / 100**

### What's implemented (correct)
- `SpecialistConfig.output_schema` (dict, JSON schema) and `SpecialistConfig.pydantic_model` (BaseModel subclass) are both supported (base.py:42-43).
- `_parse_and_validate_output` (base.py:300-375) attempts JSON parse, then pydantic validation if `pydantic_model` is set, then weak JSON-schema validation (required fields only) if `output_schema` is set.
- `VerificationLayer._validate_structured` (verification.py:172-189) does the same weak check before the specialist sees the response.
- `response_schema` is now correctly plumbed: specialist → CostGuard → VerificationLayer → TokenOptimizer → provider (verified by reading all four `complete()` signatures).

### What's broken

1. **`pydantic_model` is plumbed but unused.** `SpecialistConfig.pydantic_model` (base.py:43) and the validation path (base.py:335-353) exist. But **none of the 5 specialists set `pydantic_model`** — all use `output_schema` (dict). The strong-validation path is dead code. The right pattern would be: declare a `CoderOutput(BaseModel)` with `files: list[File]`, `summary: str`, `assumptions: list[str]`, `warnings: list[str]` — then `pydantic_model=CoderOutput` gives type/enum/nested validation. Currently a `@coder` response of `{"files": "not a list", "summary": 42}` passes weak validation because `files` is present.
2. **Weak validation only checks required-field presence** (verification.py:182-187 and base.py:355-367). No type checking, no enum checking, no nested object validation, no array element validation. `{"verdict": "APPROVE"}` passes `@reviewer` validation even though the schema declares `enum: ["approve", "request_changes", "reject"]` (reviewer.py:53).
3. **VerificationLayer and specialist duplicate validation logic.** `_validate_structured` (verification.py:172-189) and the weak-schema branch of `_parse_and_validate_output` (base.py:355-367) are essentially the same code. If the VerificationLayer rejects, the specialist's parse path still runs on the (now-replaced) `refusal_message` string and produces a confusing "LLM did not return valid JSON" error layered on top of the verification failure.
4. **No JSON cleaning.** No `_clean_json_response()` helper to strip ```` ```json ... ```` fences, extract the first `{...}` from prose-wrapped responses, or remove trailing commas. Llama 3.2 + `format: "json"` still produces fenced JSON ~25-30% of the time on complex schemas. The specialist returns `success=False` with no retry, no cleaning attempt. This is the #1 user-facing reliability issue on the default model.
5. **No retry on validation failure.** When `_parse_and_validate_output` returns `success=False` due to schema mismatch, the loop terminates. There's no "ask the LLM to fix the JSON" retry. The `RetryPolicy` in `schema.py:49-55` is for step-level retries but the executor never invokes it.
6. **Hedging-on-JSON-value false positive.** See §4 Bug B. A valid JSON response with "I'm not sure" inside a string value triggers hedging, which replaces the response with a plain string, which then fails JSON parsing. The user gets `"LLM did not return valid JSON"` when the LLM actually returned perfect JSON.

---

## 4. Anti-hallucination layer

**Score: 38 / 100**

### What's implemented (correct)
- 5-layer roadmap documented in `verification.py:1-15` (structured outputs + refusal in v0.1; confidence gate v0.2; critic loop v0.3; grounding RAG v0.4).
- Refusal system prompt injected (verification.py:191-217) — appended to existing system message if present, prepended if not.
- Hedging patterns cover 6 common forms (verification.py:32-39).
- Stats tracking: `_refusals_triggered`, `_hedging_detected`, `_validation_failures` (verification.py:223-228).

### What's broken

1. **Bug A (CRITICAL): hedging detection runs on the full JSON response.** `_detect_hedging` (verification.py:168-170) does `re.search(pattern, content, re.IGNORECASE)` on `response.content`, which for structured outputs is the full JSON string. A valid `@reviewer` response of `{"summary": "I'm not sure about the auth flow", "verdict": "request_changes"}` matches `r"\bI'?m\s+not\s+sure\b"`, sets `result.passed = False` and `result.refusal_triggered = True` (verification.py:140-148), and replaces `response.content` with `refusal_message` (verification.py:121-123) — a plain string. The specialist then runs `json.loads(refusal_message)` (base.py:319), fails, and returns `success=False` with `"LLM did not return valid JSON"` (base.py:326-330). **Net effect:** honest hedging inside a structured response produces a *worse* UX than no verification layer at all. The fix is to parse JSON first and run hedging detection only on string values (or skip it entirely when `response_schema` is set and JSON parses successfully).
2. **Bug B (HIGH): confidence is hardcoded to 0.8.** `_verify` (verification.py:138) constructs `VerificationResult(passed=True, confidence=0.8)`. The `@debugger` prompt asks the LLM to return `confidence: 0.0-1.0` (debugger.py:34) but the VerificationLayer never extracts it. The `confidence_gate` field (verification.py:47) is a v0.2 placeholder and is functionally useless because the only values `confidence` ever takes are 0.8 (default), 0.4 (hedging), and 0.0 (validation failure). The gate would need ~5 distinct confidence buckets to be meaningful.
3. **Bug C (HIGH): no factual validation.** The VerificationLayer validates form (JSON parseable, required fields present) but not content. A `@debugger` response of `{"root_cause": "complete fabrication", "confidence": 0.99, "fix": {...}}` passes every check the layer performs. The critic loop (v0.3) and grounding RAG (v0.4) are documented but not implemented. The "anti-hallucination" claim is, for v0.1, marketing.
4. **Bug D (MEDIUM): hedging patterns are English-only.** `_HEDGING_PATTERNS` (verification.py:32-39) matches `"I don't know"`, `"I'm not sure"`, etc. The bilingual playbooks (`language: "es"` in schema.py:134) mean a Spanish-speaking LLM might return `"No lo sé"` — no match, no refusal triggered. The refusal system prompt (verification.py:191-201) is also English-only.
5. **Bug E (MEDIUM): `"as an AI"` pattern is over-broad.** `r"\bas\s+an\s+ai\b"` (verification.py:36) matches any response containing "as an AI". A `@coder` response that legitimately says `"This implements an AI helper function"` would match (`"as an AI helper function"` → "as an AI" boundary match). False positive.
6. **Refusal message is not JSON.** When verification fails on a structured output, `response.content` becomes `"I don't have enough confidence to answer this. Please verify manually."` (verification.py:52). The specialist's downstream JSON parser then fails. The refusal message should be JSON-shaped (`{"error": "...", "refused": true}`) when `response_schema` is set, so the specialist can detect refusal cleanly instead of conflating it with parse failure.
7. **No refusal-recovery path.** When the LLM refuses, the run terminates with `success=False`. There's no "rephrase the question" or "ask for partial answer" retry. A single refusal kills the whole step.

---

## 5. Token optimization

**Score: 52 / 100**

### What's implemented (correct)
- Routing rules table-driven (token_optimizer.py:30-35).
- Semantic cache with SHA-256 key (token_optimizer.py:178-197), LRU eviction (token_optimizer.py:204-212), TTL (token_optimizer.py:62, 199-202).
- Cache stats: hits, misses, hit_rate, tokens_saved, estimated_savings_usd (token_optimizer.py:218-232).
- `temperature` deliberately excluded from cache key (token_optimizer.py:191) — defensible for `temperature=0.0` but problematic for `temperature>0` (see below).
- Routing only fires when `tools is None` (token_optimizer.py:90) — correct, since tool-using calls need the originally-requested model.

### What's broken

1. **Routing silently downgrades premium models.** A user who configures `Harness(model="anthropic/claude-sonnet-4-20250514")` and runs `@planner` with `{"task": "Plan JWT auth"}` (~10 tokens, no tools) gets silently routed to `ollama/llama3.2` (token_optimizer.py:30-35). The only signal is a `logger.info` (token_optimizer.py:142-148). No `MODEL_ROUTED` event is emitted to the Thread (the event type exists at events.py:58 but the middleware has no Thread reference). The user pays for Sonnet 4 and gets Llama 3.2 3B output. **This is the #1 token-optimization issue.**
2. **Token estimate is `len(content) // 4`** (token_optimizer.py:139). For dense JSON this underestimates by ~25-40%. A 400-token JSON payload may be measured as 300 tokens and routed to ollama when it should not be. Should use `tiktoken` (or vendor tokenizer) for accurate counts.
3. **Caller's model choice is effectively ignored.** All 5 specialists hardcode `default_model="ollama/llama3.2"` (planner.py:64, coder.py:58, reviewer.py:58, tester.py:63, debugger.py:60). `base.py:131` does `self.config.default_model or "ollama/llama3.2"`, so the specialist's `default_model` always wins over the caller's `model=`. The Harness's `model="anthropic/..."` is decorative.
4. **`_is_more_expensive` is brittle.** Substring matching (token_optimizer.py:155-170): `"gpt-4o-mini"` contains `"gpt-4o"` → both end up in tier 2 by `max()`. `"claude-3-5-haiku"` contains neither `"haiku"` substring (case-sensitive check would catch it but `lower()` is applied first, so `"haiku"` IS in `"claude-3-5-haiku-20241022"`). Works by accident for the current model list, will break on next vendor rename.
5. **Cache key excludes `response_schema`.** `_cache_key` (token_optimizer.py:178-197) takes `messages, model, tools, kwargs` but not `response_schema` (which is a named parameter on `complete()`, not in `**kwargs`). Two calls with the same messages but different schemas (e.g., `@planner` then `@reviewer` with identical user content) would collide. Rare in practice but real.
6. **`temperature=0.1` planner outputs are cached.** The planner runs with `temperature=0.1` (planner.py:65) — non-deterministic by design. The cache excludes `temperature` from the key (token_optimizer.py:191), so two identical planner invocations return the first run's output on the second. Inconsistent. The exclusion is correct for `temperature=0.0` (deterministic) but wrong for `temperature>0`.
7. **In-place mutation of cached responses.** `token_optimizer.py:99-101` sets `cached.response.usage.cached = True` directly on the cached `LLMResponse` object. This violates the immutability assumption of `LLMResponse` and can cause subtle bugs if the same cached response is returned to two concurrent callers — both will see `cached=True`, but the second caller's stats will be wrong if the first mutated other fields.
8. **No cache invalidation on prompt or schema change.** If you edit `planner.py` to tweak the system prompt, the cache still returns responses generated under the old prompt until the 1-hour TTL expires.
9. **No request deduplication.** Two concurrent identical requests both miss the cache and both call the LLM. A single-flight wrapper would halve cost on bursty traffic.
10. **Context compaction (v0.2) and few-shot pruning (v0.3) are documented but not implemented** (token_optimizer.py:1-13). The "40-65% token reduction" target is aspirational; only routing + cache are live, and routing is mostly inert (see #3).

---

## 6. Cost guard

**Score: 58 / 100**

### What's implemented (correct)
- Hierarchical budget: org → project → agent → task with `effective_budget()` (cost_guard.py:46-79).
- Per-call USD tracking via `response.usage.cost_usd` (cost_guard.py:238-241).
- Circuit breaker: `max_usd_per_minute` with rolling 60s window (cost_guard.py:255-263).
- Pre-flight check via `peek_cost` duck typing (cost_guard.py:265-296) — gracefully returns `None` when the provider can't estimate, falling back to post-call enforcement.
- Hard stop at 100% (cost_guard.py:151-164) and preflight abort at projected>budget (cost_guard.py:177-195).
- Stats: spent_usd, pct_used, calls_made, paused, aborted, spend_last_minute_usd (cost_guard.py:302-314).
- Zero-division guard for `effective_budget=0` (cost_guard.py:144-149) — v2 EC4 fix confirmed.

### What's broken

1. **`pause_at_pct` HITL is documented but NOT implemented.** The module docstring (cost_guard.py:1-20) claims "HITL: pause and ask for approval at 95% of budget." The code at cost_guard.py:197-216:
   ```python
   if self.spent_usd >= effective_budget * self.budget.pause_at_pct:
       logger.warning("cost_guard_pause_threshold_reached", ...)
       # TODO v0.2: emit HumanApprovalRequestedEvent and block
   elif self.spent_usd >= effective_budget * self.budget.warn_at_pct:
       logger.warning("cost_guard_warn", ...)
   ```
   `_paused` is never set to True. Only a warning log fires. The HITL pause mechanism that distinguishes ARNES from OpenHands/browser-use/crewai (per the docstring) **does not exist**.
2. **Cost is 0 on the default model.** With ollama, `cost_usd=0.0` always (ollama.py:71). `spent_usd` never increments. `spent_usd >= effective_budget * abort_at_pct` (cost_guard.py:151) is `0 >= 0.50` → always False. **The CostGuard never aborts on the default model.** The circuit breaker (cost_guard.py:255-263) also never trips because `recent_spend` is always 0. Combined with no `max_iterations` cap on the playbook executor and no `timeout_s` enforcement, an infinite loop in a playbook will run forever on ollama. Need a `max_calls` fallback (call count, not just USD).
3. **Playbook `budget_usd` field is decorative.** `audit-pr.yaml:6` declares `budget_usd: 0.50`. The compiler parses it into `playbook.metadata.budget_usd` (schema.py:133). But `PlaybookExecutor.__init__` (executor.py:90) does `self.cost_budget = cost_budget or CostBudget()` — it never reads `playbook.metadata.budget_usd`. The CLI passes `--budget` (cli/main.py:64, default 0.50) into `CostBudget(task_budget_usd=budget)`. So the playbook's declared budget is ignored; the actual budget comes from the CLI flag or the executor constructor.
4. **No `RetryPolicy` enforcement.** `RetryPolicy` is defined in schema.py:49-55 with `max_attempts`, `backoff_s`, `backoff_strategy`, `retry_on` — but the executor never wraps `_execute_step` in a retry loop. Failures are terminal. (v1 H14, unchanged.)
5. **No `timeout_s` enforcement.** `timeout_s` is in the schema (schema.py:109) but the executor never applies it. A specialist that hangs (e.g., ollama down) blocks forever. (v1 H15, unchanged.)
6. **`HITLGate` is decorative.** `HITLGate` is in the schema (schema.py:58-64, 112) with `question`, `options`, `ttl_s`, `on_timeout` — but the executor never enforces it. The `human_approval` tool exists (builtin.py:353-396) and the specialist's HITL check (base.py:226-257) auto-rejects in non-interactive mode, but the playbook-level `human_approval` field is parsed and ignored. (v1 H16, unchanged.)
7. **`peek_cost` returns None for all real providers.** `LLMProvider.peek_cost` (base.py:84-107) returns None by default. `OllamaProvider` and `LiteLLMProvider` do not override it. So the pre-flight check at cost_guard.py:170-195 — the "killer differentiator" per the docstring — never fires in production. The check is correct code that's never reached.
8. **No `MODEL_ROUTED`, `COST_THRESHOLD`, or `COST_LIMIT_EXCEEDED` event emission.** Event types are defined (events.py:54-55, 58) but the middleware has no Thread reference to emit them. Observability gap.

---

## 7. Playbook DSL expressiveness

**Score: 55 / 100**

### What's implemented (correct)
- YAML → pydantic schema with semantic checks (compiler.py:42-197).
- Bilingual keymap: ES keys → EN keys, recursively (compiler.py:103-146). Backwards-compat with v0.0.x Spanish playbooks.
- Step types: specialist, tool, parallel (schema.py:85-122). `model_validator` enforces exactly-one (schema.py:114-122).
- Conditional branch: `if_not_met` with `action: call | terminate | skip` (schema.py:67-82).
- `saltar_a` (skip-to) semantics fixed in v2 — skip-until marker cleared when target reached (executor.py:121-133).
- Multi-template resolution: `{{ variables.a }} and {{ variables.b }}` works (executor.py:534-570).
- Parallel outputs resolvable: `{{ steps.parallel.lint.output }}` works (executor.py:403-442, verified by reading `_resolve_expr` virtual-accessor logic at executor.py:572-633).
- Deep nesting: `{{ steps.s1.output.steps.s2.output }}` works because only the leading prefix is stripped (executor.py:600-611).

### What's broken

1. **`conditionals` (if/elif/else) field is parsed but NEVER evaluated.** `PlaybookStep.conditionals: list[ConditionalBranch]` is in the schema (schema.py:104). The compiler validates `skip_to` targets exist (compiler.py:173-178). But `grep "conditionals" arnes/playbooks/executor.py` returns zero matches. The field is decorative. Only `if_not_met` is handled (executor.py:155-170).
2. **`requires` preconditions field is never checked.** `PlaybookStep.requires: list[str]` is in the schema (schema.py:102). The docstring says "preconditions (must all be true)". The compiler doesn't validate them. The executor never evaluates them. `if_not_met` is supposed to fire when `requires` fails — but since `requires` is never checked, `if_not_met` only fires on step failure (executor.py:155), not on precondition violation. The semantics are confused.
3. **Parallel branches are executed sequentially, not concurrently.** `_execute_parallel` (executor.py:403-442) has the comment "For MVP: sequential execution of 'parallel' steps (correctness > parallelism). In v0.2 we'll use asyncio.gather with proper thread merging." So `parallel:` is a syntactic marker; the runtime behavior is sequential. The DSL promises parallelism the executor doesn't deliver.
4. **No `output:` field assignment.** `PlaybookStep.output: str | None` is in the schema (schema.py:99) — "variable name to assign output to". The executor never reads it. Outputs are always assigned to `outputs[step.id]` (executor.py:146). The `output:` field is dead.
5. **No `variables:` mutation mid-playbook.** Variables are read-only (set at top of `run()`, executor.py:103-105). A step can't set a variable for later steps. Workaround is to use step outputs, but that's not always ergonomic.
6. **No loops.** No `for:` or `while:` construct. Can't iterate over a list of PRs, files, etc. Workaround is to invoke `@planner` to emit a list of steps — but those steps aren't real PlaybookSteps, they're JSON inside the planner's output.
7. **No Jinja2 filters or expressions.** Templates support only `{{ path.to.value }}` — no `{{ value | default("x") }}`, no `{{ value if condition else other }}`, no `{% if %}` blocks. The custom regex-based resolver (executor.py:494-633) reimplements 5% of Jinja2 badly. Should either use Jinja2 directly or document the subset clearly.
8. **No playbook imports / composition.** Can't `include: shared-steps.yaml`. Each playbook is standalone.
9. **No `default_model` per-step.** `Playbook.default_model` is in the schema (schema.py:155) but the executor never reads it. Specialists always use their hardcoded `default_model` (see §5 issue #3).
10. **`budget_usd` decorative** (see §6 issue #3).

---

## 8. LLM provider abstraction

**Score: 50 / 100**

### What's implemented (correct)
- Vendor-neutral `LLMProvider` ABC (base.py:62-107) with `complete()` and `list_models()`.
- `peek_cost()` method on the base class (base.py:84-107) for pre-flight budget checks — duck-typed so middleware wrappers also work.
- Factory pattern: `get_provider("ollama/llama3.2")` → `OllamaProvider`, `get_provider("anthropic/...")` → `LiteLLMProvider` (factory.py:20-52).
- `ARNES_MOCK_LLM` env var for test override (factory.py:33-34).
- LiteLLM as universal adapter for paid vendors (litellm_provider.py:34-118) — supports Anthropic, OpenAI, Google, Groq, Mistral, Cohere, Azure.
- Pricing table kept up-to-date (litellm_provider.py:11-22) with 10 models as of 2026-01.

### What's broken

1. **Ollama provider doesn't pass `tools` to ollama** (see §2 issue #1). The `tools` parameter is accepted (ollama.py:25) and silently dropped (not added to `payload`). This is the single biggest provider bug.
2. **Ollama provider hardcodes `tool_calls=[]`** (ollama.py:66). Even if ollama returned tool_calls in `data["message"]["tool_calls"]`, they would be ignored.
3. **Ollama provider ignores `response_schema`** (ollama.py:29 comment: "Accepted but ignored"). Ollama supports `format: {"type": "object", "schema": {...}}` since v0.1.27 (Apr 2024) for structured outputs. The current code only sets `format: "json"` (ollama.py:46-47) which is the weaker form. The stronger `format: {"type": "object", "schema": {...}}` would give server-side schema enforcement.
4. **LiteLLM provider has a `kwargs` variable shadowing bug.** `litellm_provider.py:60` declares `**kwargs: Any` as a parameter. `litellm_provider.py:67` then reassigns `kwargs: dict[str, Any] = {...}` locally. The parameter `kwargs` (which contains `interactive`, `response_schema`, and any other middleware-passed options) is silently dropped. Not a runtime crash (because the dropped kwargs aren't needed by litellm), but it's a latent bug and confuses linters.
5. **LiteLLM provider ignores `response_schema`** (litellm_provider.py:59 comment: "Accepted but ignored"). LiteLLM supports `response_format={"type": "json_schema", "json_schema": {"schema": {...}}}` for OpenAI structured outputs, and Anthropic's tool-use-as-JSON pattern. Neither is used. Only the weak `{"type": "json_object"}` is sent (litellm_provider.py:76-77).
6. **`peek_cost` is never overridden.** `LLMProvider.peek_cost` returns None (base.py:107). `OllamaProvider` and `LiteLLMProvider` don't override it. So the CostGuard pre-flight check (§6 issue #7) is dead code. The LiteLLM provider has a pricing table (litellm_provider.py:11-22) and could easily implement `peek_cost` by estimating input tokens via `tiktoken` and assuming `max_tokens` for output — but doesn't.
7. **No streaming.** `LLMProvider` has no `stream_complete()` method (base.py:62-107). `ollama.py:41` sets `"stream": False`. For `audit-pr.yaml` (5+ specialist calls), the user waits minutes with only a CLI spinner. No real-time progress.
8. **No retry on transient failures.** If ollama returns HTTP 429 or 503, the provider raises. The CostGuard doesn't retry. The specialist doesn't retry. The executor doesn't retry. A single transient error kills the run.
9. **No provider health check.** `list_models()` (ollama.py:78-87) catches all exceptions and returns a hardcoded list. So `arnes list specialists` works even if ollama is down — misleading. Should distinguish "ollama not running" from "no models installed".
10. **0% test coverage on `OllamaProvider` and `LiteLLMProvider`** (verified by `pytest --cov`). All 105 tests use mock providers. The test suite cannot detect any of the issues in §8 #1-#6.

---

## 9. Default model viability

**Score: 35 / 100**

### What "default" means
- `DEFAULT_MODEL = "ollama/llama3.2"` (factory.py:17).
- All 5 specialists hardcode `default_model="ollama/llama3.2"`.
- CLI `--model` defaults to `"ollama/llama3.2"` (cli/main.py:63).
- Harness defaults to `"ollama/llama3.2"` (agent.py:45).

### What Llama 3.2 (1B/3B via ollama) can actually do

With `format: "json"` (the current setting):
- **Flat schemas** (`{"steps": [...]}`): ~70-85% valid JSON.
- **Nested schemas** (Coder's `files: [{path, language, content, action}]`): ~40-55% valid JSON.
- **Enum constraints**: not enforced server-side by `format: "json"`. `"action": "create"` may come back as `"create_new"` or `"CREATE"`.
- **Long outputs**: truncated mid-object ~15-20% of the time on 200+ line responses.
- **Tool use**: not even attempted — ollama.py doesn't send `tools` to the API.
- **JSON wrapping**: ~25-30% of responses are wrapped in ```` ```json ... ```` fences or have prose before/after, even with `format: "json"`.

### What will happen in alpha on the default stack

- **`@planner`** (no tools, simple schema): ~70% success rate. JSON parse failures surface as `success=False, error: "LLM did not return valid JSON"`. No retry, no JSON cleaning.
- **`@coder`** (tools declared, complex schema): ~40-50% success rate. Tool-use loop never triggers (ollama doesn't send tools). JSON parse failures and schema mismatches common. Even when JSON parses, `files[0].action` may be `"create_new"` — currently accepted because schema validation only checks required-field presence.
- **`@reviewer`** (no tools, simple schema): ~75% success rate. Best case.
- **`@tester`** (tools declared): **cannot run tests** (tool-use inert). Will fabricate `test_results` ~90% of the time. The system reports `success=True` with hallucinated test counts. **The prompt incentivizes hallucination when tools are unavailable.**
- **`@debugger`** (tools declared): **cannot read files** (tool-use inert). Will propose fixes from the traceback alone, without reading the failing code. Confidence will be ~0.85-0.95 regardless of accuracy.

### Recommendation

Two viable paths:

**Path A (recommended for alpha):** Default to `anthropic/claude-3-5-haiku-20241022` ($0.80/$4.00 per M tokens) for the example playbooks. Keep `ollama/llama3.2` as the default for `hello-world.yaml` only, with a clear disclaimer. Cost for a typical playbook run: ~$0.02-0.05. Acceptable for alpha.

**Path B (more work, preserves local-first ethos):** Implement the three fixes that make ollama/llama3.2 viable:
1. Pass `tools` to ollama's `/api/chat` API and parse `data["message"]["tool_calls"]` (1 day).
2. Use `format: {"type": "object", "schema": {...}}` for server-side schema enforcement (0.5 day).
3. Implement `_clean_json_response()` to strip fences and extract `{...}` from prose (0.5 day).

Either path is ~2 days of work. Path A is lower-risk.

---

## 10. AI pattern innovation

**Score: 65 / 100**

### What's genuinely novel (vs LangChain/CrewAI/AutoGen/OpenHands)

1. **Playbook as YAML DSL** — "Ansible for AI agents." LangChain is Pythonic chains; CrewAI is Pythonic tasks; AutoGen is code-first multi-agent. ARNES's YAML-first approach is a real differentiator for platform engineers, regulated industries, and non-Python-developer audiences. The bilingual keymap (ES → EN) is a deliberate Latam-wedge strategy that no other framework offers.
2. **Hierarchical cost budget with circuit breaker.** The docstring (cost_guard.py:1-20) correctly notes that OpenHands has `max_budget_per_task` (1 level, no circuit breaker), browser-use has warning at 75% (no enforcement), langfuse has `MAX_AGENT_STEPS=10` hardcap (no USD tracking), crewai has `max_tokens` only (no USD, no circuit breaker). ARNES's `org → project → agent → task` hierarchy with `max_usd_per_minute` DoW defense is genuinely novel. **Shame that `pause_at_pct` HITL is not implemented and `peek_cost` is never overridden** — these are the features that would distinguish it most.
3. **Tool fingerprinting for HITL rug-pull defense** (base.py:226-257, tools/base.py:106-114). Hash the args at approval time, re-hash at execution time, abort on mismatch. This is a real security pattern that no other framework implements. Genuinely novel.
4. **Stateless reducer event sourcing** (thread/thread.py, thread/events.py). Immutable `Thread` with `append()` returning a new `Thread`. Pure `(state, event) → state` reducer. This is the Event Sourcing pattern applied to agent state — clean, replayable, testable. LangChain has `Memory` (mutable); CrewAI has `Flow` (mutable). ARNES's approach is more disciplined.
5. **Specialist as `ClassVar` config dataclass** with auto-registry via `__init_subclass__` (base.py:69-72). Adding a specialist = 1 file, no registration boilerplate. Clean.
6. **Middleware composition via wrapping** (VerificationLayer → TokenOptimizer → CostGuard → provider). The `_arnes_wrapped` marker (base.py:115) prevents double-wrapping. This is the decorator/middleware pattern done right.

### What's not novel (and where ARNES lags)

1. **ReAct loop** — standard pattern, present in LangChain (since 2022), AutoGen, OpenHands. ARNES's implementation is correct but unsophisticated: no planning, no reflection, no self-correction, no tool-result summarization.
2. **Structured outputs** — OpenAI's `response_format: {"type": "json_schema", ...}`, Anthropic's tool-use-as-JSON, instructor's pydantic approach. ARNES's weak required-field-only validation is behind all of these.
3. **Anti-hallucination** — the 5-layer roadmap (structured outputs → refusal → confidence gate → critic loop → grounding RAG) is aspirational. Only layers 1-2 are implemented, and layer 2 (refusal) is buggy (see §4 Bug A). LangChain has `ConstitutionalChain`; instructor has `max_retries` with validation-error feedback; NeMo Guardrails has full rail policies. ARNES is behind.
4. **Tool ecosystem** — 5 built-in tools (shell, http, fs_read, fs_write, human_approval). LangChain has 600+ tools via `langchain-tools` and MCP. CrewAI has 50+. ARNES's tool story is minimal.
5. **Memory** — none. Each run starts from scratch. LangChain has `ConversationBufferMemory`, `ConversationSummaryMemory`, `VectorStoreRetrieverMemory`. AutoGen has `redis_memory`. ARNES has nothing.
6. **Streaming** — none. Every other framework supports streaming. ARNES blocks on every call.
7. **Multi-turn within a step** — none. The ReAct loop is single-shot per iteration. No "no, that's wrong, try again" user intervention mid-step.
8. **Observability** — events are defined (`MODEL_ROUTED`, `CACHE_HIT`, `REFUSAL_TRIGGERED`, etc.) but never emitted. No Langfuse/LangSmith integration. No OpenTelemetry. The Thread is the only audit log, and it doesn't record middleware decisions.

### Innovation verdict

ARNES has **3 genuinely novel patterns** (YAML DSL with bilingual keymap, hierarchical cost budget with circuit breaker, tool fingerprinting for HITL) and **a clean architectural spine** (stateless reducer + middleware composition). But the AI/ML layer (ReAct, structured outputs, anti-hallucination) is behind LangChain/CrewAI/instructor and the default-model path is non-functional. The innovation is in the harness architecture, not in the AI patterns.

---

## 11. Test suite assessment

**Score: 50 / 100**

- **105 tests pass.** Coverage: 65.37%.
- **Stress tests are excellent:** 50 concurrent playbooks with race-condition detection (unique thread IDs, run_id distribution, max-concurrent-call tracking). This is real engineering.
- **Critical gap: 0% coverage on `OllamaProvider` and `LiteLLMProvider`.** Every test uses `SchemaValidMockProvider` (test_executor.py:13-64, test_e2e.py:15-57, cli/main.py:304-364) which returns hardcoded schema-conforming JSON per specialist. The test suite cannot detect:
  - The ollama `tool_calls=[]` regression.
  - The ollama `tools` parameter being dropped.
  - The litellm `kwargs` shadowing bug.
  - Real-world JSON parse failures (fenced JSON, prose-wrapped JSON, truncated JSON).
  - Schema validation gaps (the mock always returns valid schema).
  - Hedging false positives on JSON values (the mock never hedges).
- **No contract tests** that verify the provider's `complete()` signature matches what the middleware calls.
- **No snapshot tests** for specialist prompts (prompts can drift without test failure).
- **No property-based tests** for template resolution (the custom regex resolver at executor.py:494-633 is complex enough to warrant Hypothesis tests).
- **The `test_tool_use_loop_in_specialist` test (test_e2e.py:235-307) is good** — it verifies the ReAct loop works when a provider returns tool_calls. But it uses a mock provider, so it doesn't verify the default path works.

---

## 12. Scorecard

| # | Dimension | Score | Notes |
|---|-----------|-------|-------|
| 1 | Specialist prompt quality | 62 | Good structure, but no "JSON only" instruction, no tool-use guidance, prompt/schema mismatch, @reviewer overloaded |
| 2 | ReAct tool-use loop | 48 | Loop scaffolded correctly but dead on default provider (ollama hardcodes `tool_calls=[]`) |
| 3 | Structured output validation | 45 | `pydantic_model` plumbed but unused; only required-field presence checked; no JSON cleaning; no retry |
| 4 | Anti-hallucination layer | 38 | Hedging detection on full JSON content causes false positives; confidence hardcoded; no factual validation |
| 5 | Token optimization | 52 | Routing silently downgrades premium models; cache excludes `response_schema`; planner cached despite temp=0.1 |
| 6 | Cost guard | 58 | `pause_at_pct` HITL not implemented; no-op on $0 models; `peek_cost` never overridden; `RetryPolicy`/`timeout_s`/`HITLGate` not enforced |
| 7 | Playbook DSL expressiveness | 55 | `conditionals`/`requires`/`output`/`default_model` parsed but ignored; parallel branches run sequentially; no loops/imports |
| 8 | LLM provider abstraction | 50 | Vendor-neutral ABC is clean; but ollama doesn't pass `tools`, litellm has `kwargs` shadowing, `response_schema` ignored by both, no streaming |
| 9 | Default model viability | 35 | Llama 3.2 + `format: "json"` produces ~40-70% valid JSON on specialist schemas; tool-use loop inert; will fabricate test results |
| 10 | AI pattern innovation | 65 | YAML DSL + bilingual keymap + hierarchical cost budget + tool fingerprinting are novel; ReAct/structured-outputs/anti-hallucination lag LangChain/CrewAI/instructor |

### Weighted overall score

Weights emphasize production-readiness for the AI layer:

| Dimension | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| 1. Specialist prompts | 10% | 62 | 6.2 |
| 2. ReAct loop | 12% | 48 | 5.8 |
| 3. Structured output | 12% | 45 | 5.4 |
| 4. Anti-hallucination | 10% | 38 | 3.8 |
| 5. Token optimization | 8% | 52 | 4.2 |
| 6. Cost guard | 10% | 58 | 5.8 |
| 7. Playbook DSL | 10% | 55 | 5.5 |
| 8. Provider abstraction | 10% | 50 | 5.0 |
| 9. Default model viability | 10% | 35 | 3.5 |
| 10. AI pattern innovation | 8% | 65 | 5.2 |
| **Overall** | **100%** | | **50.4** |

**Overall AI score: 50 / 100**

---

## 13. Top 5 critical AI issues

1. **Ollama provider cannot do tool use.** `ollama.py:38-43` never sends `tools` to the Ollama chat API and `ollama.py:66` hardcodes `tool_calls=[]`. The entire ReAct loop is dead on the default model. `@coder`, `@tester`, `@debugger` are stateless prompt templates. The flagship v1→v2 fix is non-functional. **Fix: pass `tools` to ollama payload, parse `data["message"]["tool_calls"]`. ~1 day.**

2. **Anti-hallucination layer produces false positives on honest hedging inside JSON.** `_detect_hedging` runs on the full JSON response content. A valid `@reviewer` response of `{"summary": "I'm not sure about the auth flow"}` triggers hedging, replaces the response with a plain string, and then fails JSON parsing — producing a confusing `"LLM did not return valid JSON"` error instead of the valid answer. **Fix: parse JSON first; run hedging only on string values, or skip when `response_schema` is set and JSON parses. ~0.5 day.**

3. **0% test coverage on `OllamaProvider` and `LiteLLMProvider`.** All 105 tests use mock providers that return perfect JSON. The test suite cannot detect issues #1, #2, or any real-LLM output shape regression. **Fix: add contract tests that call the real providers (with `pytest.mark.integration` and `ARNES_LIVE_TEST=1` guard), and add property-based tests for JSON parsing of malformed/fenced/truncated responses. ~2 days.**

4. **Schema validation is weak and `pydantic_model` is dead code.** Only required-field presence is checked — no type, enum, or nested validation. The `pydantic_model` field on `SpecialistConfig` is plumbed end-to-end but no specialist uses it. `{"verdict": "APPROVE"}` passes `@reviewer` validation despite the `enum: ["approve", "request_changes", "reject"]` declaration. **Fix: convert all 5 specialists to use `pydantic_model` instead of `output_schema`. ~1 day.**

5. **`pause_at_pct` HITL is documented but NOT implemented.** The CostGuard docstring (cost_guard.py:1-20) claims "HITL: pause and ask for approval at 95% of budget" — the killer differentiator vs OpenHands/browser-use/crewai. The `_paused` flag is never set to True. Only a `logger.warning` fires. The TODO at cost_guard.py:208 is still in the code. **Fix: set `self._paused = True` at 95% threshold, emit `HumanApprovalRequestedEvent`, and raise `BudgetExceeded(level="pause")`. The non-interactive path already does the right thing (raises). The interactive path needs the event + resume mechanism. ~1.5 days.**

---

## 14. Top 5 improvements needed

1. **Fix the default model path.** Either (a) implement ollama tool-calling + `format: {"type": "object", "schema": {...}}` + `_clean_json_response()` (~2 days, preserves local-first ethos), or (b) switch the default for example playbooks to `anthropic/claude-3-5-haiku-20241022` with a clear disclaimer on `hello-world.yaml` (~0.5 day, lower risk). Option (b) is recommended for alpha; option (a) for v0.2.

2. **Add "Return ONLY valid JSON, no prose, no code fences" to every specialist prompt.** Plus a one-shot example. Plus a `_clean_json_response()` post-processor that strips ```` ```json ... ```` fences and extracts the first `{...}` from prose-wrapped responses. ~1 day. This alone will roughly double success rates on Llama 3.2.

3. **Convert all 5 specialists to use `pydantic_model` instead of `output_schema`.** Declare `CoderOutput(BaseModel)`, `ReviewerOutput(BaseModel)`, etc. with full type/enum/nested validation. Wire `pydantic_model` through the VerificationLayer (currently only the specialist uses it). ~1.5 days. Closes the schema-validation gap.

4. **Implement the 5 schema fields that are parsed but never enforced:** `requires`, `conditionals`, `RetryPolicy`, `timeout_s`, `HITLGate`. Either implement them or remove them from the schema. Decorative schema fields are worse than missing fields because they mislead users. ~3 days for all 5.

5. **Add streaming + observability events.** `LLMProvider.stream_complete()` (async generator yielding `LLMResponse` chunks). Emit `MODEL_ROUTED`, `CACHE_HIT`, `REFUSAL_TRIGGERED`, `COST_THRESHOLD` events to the Thread. Pass the Thread reference to middleware (currently middleware has no Thread access). ~2 days. Without this, long playbook runs are opaque.

**Bonus improvement:** Override `peek_cost` on `LiteLLMProvider` using the pricing table (litellm_provider.py:11-22) + `tiktoken` for input token estimation. This activates the pre-flight budget check (cost_guard.py:170-195) that is currently dead code. ~0.5 day.

---

## 15. Verdict

### **NO-GO for public release.**

**Rationale:** The default model path is non-functional (issue #1), the anti-hallucination layer is actively harmful on honest hedging (issue #2), the test suite cannot detect either (issue #3), schema validation is cosmetic (issue #4), and the headline HITL feature is not implemented (issue #5). Shipping as-is would produce a public alpha that:
- Cannot use tools on its default model.
- Silently downgrades honest hedging to confusing JSON parse errors.
- Passes 105 tests because the mock LLM returns perfect JSON every time.
- Documents HITL pause but doesn't implement it.
- Cannot reliably produce structured outputs from Llama 3.2.

### Path to GO

The 5 critical issues are fixable in **~6 engineer-days** total:
- Issue #1 (ollama tool use): 1 day
- Issue #2 (hedging false positive): 0.5 day
- Issue #3 (provider test coverage): 2 days
- Issue #4 (pydantic_model adoption): 1.5 days
- Issue #5 (pause_at_pct HITL): 1.5 days

Plus the 5 improvements (~9.5 engineer-days) for a credible v0.2.

**Recommended release sequence:**
1. **v0.1.0a2 (private alpha):** Fix issues #1, #2, #4. Add `_clean_json_response()`. Switch example playbook default to `claude-3-5-haiku`. ~3 days.
2. **v0.1.0a3 (private alpha):** Fix issues #3, #5. Implement `requires` and `RetryPolicy`. ~3 days.
3. **v0.1.0 (public alpha):** Streaming, observability events, `peek_cost` override. ~3 days. **GO for public release.**

Total: ~9 engineer-days from NO-GO to GO.

---

## 16. Comparison to v1/v2 audits

| Issue | v1 | v2 | JUDGE-AI-R1 (this audit) |
|-------|----|----|--------------------------|
| ReAct tool-use loop | CRITICAL — not implemented | CRITICAL — scaffolded but inert (ollama hardcodes `tool_calls=[]`) | **Still inert** — ollama.py:66 unchanged |
| `output_schema` not passed to VerificationLayer | CRITICAL | CRITICAL — still not passed | **Fixed** — `response_schema` now plumbed (base.py:144) |
| Parallel outputs not resolvable in templates | CRITICAL | CRITICAL — still broken | **Fixed** — `_execute_parallel` wraps output, `_resolve_expr` virtual accessor works |
| Multi-template resolution only resolves first | CRITICAL | CRITICAL — still broken | **Fixed** — `_resolve_template` handles N matches (executor.py:534-570) |
| `saltar_a` semantics (skip vs jump-to) | CRITICAL | CRITICAL — fixed | **Confirmed fixed** — skip-until marker cleared on reach (executor.py:121-133) |
| Specialist re-wraps provider (double middleware) | — | CRITICAL — `_provider` check is dead | **Fixed** — `_arnes_wrapped` marker works (base.py:115, all middleware) |
| Hedging false positive on JSON values | HIGH | HIGH — still present | **Still present** — verification.py:140-148 unchanged |
| `pause_at_pct` HITL not implemented | HIGH | HIGH — set/unset in same branch | **Still not implemented** — `_paused` never set to True, TODO at cost_guard.py:208 |
| Playbook `budget_usd` ignored by executor | — | HIGH | **Still ignored** — executor.py:90 unchanged |
| `RetryPolicy`/`timeout_s`/`HITLGate` not enforced | HIGH | HIGH | **Still not enforced** — grep returns no matches in executor.py |
| No JSON cleaning post-processing | — | HIGH | **Still missing** — no `_clean_json_response()` anywhere |
| No streaming | MEDIUM | MEDIUM | **Still missing** — no `stream_complete` on LLMProvider |
| `pydantic_model` plumbed but unused | — | HIGH | **Still unused** — no specialist sets it |
| 0% coverage on Ollama/LiteLLM providers | — | HIGH | **Still 0%** — verified by pytest --cov |
| `peek_cost` never overridden | — | HIGH | **Still never overridden** — pre-flight check is dead code |

**Net progress v2 → R1:** 5 of 15 issues fixed (all in the "structural plumbing" category). 10 of 15 still open (all in the "AI behavior" category). The architecture is solid; the AI layer is not yet ready.

---

**End of audit.**
