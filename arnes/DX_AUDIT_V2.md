# DX AUDIT V2 — ARNES v0.1.0a1 (post EN translation)

**Auditor:** Senior Python DX engineer (architecture + library ergonomics)
**Date:** 2026-07-29
**Task ID:** AUDIT-DX
**Scope:** Public API, CLI, Playbook DSL, MCP, Thread, Specialists, Tools, Middleware, Docs, Tests
**Method:** Full read of the 12 target files + tests + manuals + a real end-to-end run of `arnes init` → `arnes lint` → `arnes run --mock` + `mypy --strict` + `pytest --cov`
**Predecessor:** `DX_AUDIT.md` (pre-translation, in Spanish). This V2 re-audits the codebase **after** the Spanish→English translation pass.

---

## Executive summary

ARNES ships a genuinely compelling idea — declarative YAML manuals compiled into a DAG of specialists, with an immutable Thread, auditable bitácora, vendor-neutral LLM layer, and hierarchical cost guardrails. The architecture at the module level is sound: Thread + Specialist + Tool + Playbook + Middleware are the right primitives and the names map cleanly to the concepts.

**The Spanish→English translation pass fixed the user-facing surface (YAML keys, public API names, README) but left a landmine inside the executor.** The `PlaybookExecutor._handle_conditional_branch` method still references `ConditionalBranch` fields by their old Spanish names (`branch.accion`, `branch.especialista`, `branch.saltar_a`, `branch.cuando`, `branch.terminar`) — and constructs a `PlaybookStep` with the Spanish kwarg `especialista=...`. Pydantic raises `AttributeError: 'ConditionalBranch' object has no attribute 'accion'. Did you mean: 'action'?` the moment a step with `if_not_met` actually fails. The headline `audit-pr.yaml` example uses exactly this construct.

This bug is **invisible to the test suite** because the only conditional-branch test (`test_conditional_branch_terminate`) happens to make the step *succeed*, so `_handle_conditional_branch` is never entered. `mypy --strict` flags it (`arnes/playbooks/executor.py:462: error: Unexpected keyword argument "especialista" for "PlaybookStep"; did you mean "specialist"?`), but AGENTS.md's "mypy --strict must pass" rule is currently failing with **46 errors**, so the warning never blocked the build.

Beyond that, the translation pass also left behind:
- Spanish residue in module docstrings, comments, CLI output strings ("Bitácora", "manual", "si_no_se_cumple"), MCP defaults (`manuales/`), and a deprecated `Agent` alias kept "for early adopters who used the alpha within hours of release" — but no one is using a pre-release alpha.
- A self-admitted non-spec MCP server (`"This is a simplified stdio-based MCP server. For full MCP spec compliance, use the official mcp Python SDK and wrap this class."`) — despite README advertising `✅ MCP v0.1` for Claude Desktop / Cursor / Cline / Zed.
- `parallel` branches that run sequentially (executor comment admits it), `retry` policy parsed but never enforced, `human_approval` HITL gate parsed but never honored, `timeout_s` parsed but never enforced.
- `mcp>=1.0,<2` declared as a hard dependency (1+ MB installed) but **never imported** anywhere in the codebase.
- `aiohttp` imported by `mcp/server.py:serve_http` but not declared as a dependency.
- Spanish `ejecutar` CLI alias for `run` (claimed "backwards compat" — there is no prior release to be backwards compatible with).
- `Thread.reduce()` is O(n) per call with no caching; `executor.py` uses a `list[Thread]` mutable holder as an anti-pattern for what should be `nonlocal` or a class attribute.
- `Specialist.run` re-wraps the provider with `TokenOptimizer` + `VerificationLayer` because the duck-type check `hasattr(provider, "_provider")` is broken — middleware is applied 2x (or in a wrong order) on the Harness path.

**Good news:** the basic happy path (`arnes init → arnes lint → arnes run --mock`) works end-to-end. The scaffolded YAML is valid, the mock LLM produces schema-valid JSON for all 5 specialists, and the bitácora is written. The "60-second hello world" promise is *achievable* for a fresh dev — if the docs are cleaned up and the conditional-branch crash is fixed.

**Verdict:** **NO-GO for public alpha.** The conditional-branch AttributeError is a release blocker (a core feature is silently broken in a way the test suite doesn't catch). Add 5 mandatory fixes (detailed below) — most are <50 lines — and the DX is ready for a public alpha with a "known limitations" caveat for parallel/retry/HITL.

---

## Issue table

| #  | Severity | Title | File:line |
|----|----------|-------|-----------|
| 1  | CRITICAL | `PlaybookExecutor._handle_conditional_branch` references Spanish field names → `AttributeError` on first failing step with `if_not_met` | `arnes/playbooks/executor.py:439-483` |
| 2  | CRITICAL | `PlaybookStep(id=..., especialista=branch.especialista, ...)` — Spanish kwarg, pydantic rejects | `arnes/playbooks/executor.py:462-466` |
| 3  | CRITICAL | `mypy --strict` fails with 46 errors — AGENTS.md rule broken, blocks CI from catching issues #1 and #2 | `arnes/` (8 files) |
| 4  | CRITICAL | `Specialist.run` re-wraps provider with middleware (duck-type check `hasattr(provider, "_provider")` is broken — CostGuard stores as `provider` not `_provider`) → middleware applied 2x, wrong order on Harness path | `arnes/specialists/base.py:107-122`, `arnes/agent/agent.py:97-107` |
| 5  | CRITICAL | `arnes.mcp.server` advertises itself as ✅ v0.1 but admits non-spec compliance; `aiohttp` undeclared; `mcp` SDK declared but unused; `_patch_server_class()` monkey-patches methods instead of defining them | `arnes/mcp/server.py:40-44, 281-322`, `pyproject.toml:59` |
| 6  | HIGH     | `arnes/playbooks/executor.py:_handle_conditional_branch` is 100% uncovered by tests — only the success path is tested | `tests/unit/test_executor.py:299-316` |
| 7  | HIGH     | `step.retry` (`RetryPolicy`) parsed but never enforced — silent no-op | `arnes/playbooks/executor.py` (no retry logic in `_execute_step`), `arnes/playbooks/schema.py:49-55` |
| 8  | HIGH     | `step.human_approval` (`HITLGate`) parsed but never honored — `--interactive` flag is a no-op | `arnes/playbooks/executor.py`, `arnes/cli/main.py:66` |
| 9  | HIGH     | `step.timeout_s` parsed but never enforced | `arnes/playbooks/schema.py:109`, `arnes/playbooks/executor.py:244-307` |
| 10 | HIGH     | `arnes.mcp.server` has **0%** test coverage | `tests/` (no `test_mcp.py`) |
| 11 | HIGH     | `__init__.py` docstring still in Spanish; `agent/agent.py` docstring quotes manifesto in Spanish | `arnes/__init__.py:4-5`, `arnes/agent/agent.py:4-9` |
| 12 | HIGH     | `Agent = Harness` deprecated alias kept "for early adopters who used the alpha within hours of release" — pre-alpha, no users; violates manifesto #2 and confuses new readers | `arnes/agent/agent.py:129-132`, `arnes/agent/__init__.py:3,5` |
| 13 | HIGH     | `arnes/cli/main.py` defines a 60-line `_SchemaValidMockLLMProvider` class inside the CLI module; signature is fully untyped (`messages`, `tools=None`, `max_tokens=None`) | `arnes/cli/main.py:304-365` |
| 14 | HIGH     | `cli.add_command(run, name="ejecutar")` — Spanish CLI alias claimed "backwards compat (will be deprecated in v0.2)" but there's no prior release to be compat with | `arnes/cli/main.py:80-81` |
| 15 | HIGH     | User-facing CLI strings mix English and Spanish: `--output` help is "Save bitácora to file"; success line is "✅ Manual executed"; default file is `bitacora-<name>-<ts>.md` | `arnes/cli/main.py:67, 278, 294, 299-301` |
| 16 | HIGH     | `Thread.to_markdown()` writes `# Bitácora ARNES — Thread {id}` — Spanish in user-visible output (English-speaking users won't recognize "bitácora") | `arnes/thread/thread.py:155-176` |
| 17 | HIGH     | MCP server `arnes_list_playbooks` defaults to `dir="manuales"` (Spanish) — but README and CLI use `manuals/`. Reproduction: calling the tool with no args returns `{"error": "Directory not found: manuales"}` | `arnes/mcp/server.py:83, 169` |
| 18 | HIGH     | MCP `arnes_run_playbook` returns a key called `bitacora_preview` — Spanish key in a public JSON-RPC API consumed by Claude Desktop / Cursor | `arnes/mcp/server.py:204` |
| 19 | HIGH     | Spanish residue in code comments and docstrings: `si_no_se_cumple`, `saltar_a`, `manuales/`, `especialista` (in `_handle_conditional_branch` docstring) | `arnes/playbooks/executor.py:121, 154, 448, 460, 473, 476` |
| 20 | HIGH     | `arnes.llm.factory.get_provider()` raises `ValueError("Unknown LLM vendor: ...")` with no actionable fix; `OllamaProvider` raises `RuntimeError("Ollama not reachable")` — these bubble up as opaque failures via `Harness.run`'s `except Exception: return {"success": False, "error": str(e)}` | `arnes/llm/factory.py:50-52`, `arnes/agent/agent.py:124-126` |
| 21 | MEDIUM   | `Playbook.metadata` is `Optional` but every CLI/MCP/path accesses it without checking — 6 mypy `union-attr` errors | `arnes/playbooks/schema.py:150`, `arnes/cli/main.py:133-138`, `arnes/mcp/server.py:235-254` |
| 22 | MEDIUM   | `__skip_steps_until` magic key pollutes user-visible `result.outputs` dict; MCP server has to filter it out with `if not k.startswith("__")` (acknowledges the smell) | `arnes/playbooks/executor.py:121-122`, `arnes/mcp/server.py:202` |
| 23 | MEDIUM   | `executor.run` uses `thread_holder: list[Thread] = [Thread.create()]` as a mutable single-cell wrapper — anti-pattern; should be `nonlocal` or a small `_RunState` class | `arnes/playbooks/executor.py:101` |
| 24 | MEDIUM   | `executor._handle_conditional_branch` parameter `branch` is untyped (no annotation) | `arnes/playbooks/executor.py:439-446` |
| 25 | MEDIUM   | `executor.run` wraps `self.provider` in a fresh `CostGuard` *every call* (per-run state leaking into a stateless executor) | `arnes/playbooks/executor.py:108` |
| 26 | MEDIUM   | `CostGuard` doesn't implement the `LLMProvider` protocol — `provider=cost_guard` requires `# type: ignore[arg-type]` | `arnes/playbooks/executor.py:345`, `arnes/middleware/cost_guard.py:82` |
| 27 | MEDIUM   | `TokenOptimizer` and `VerificationLayer` also don't subtype `LLMProvider` — same `# type: ignore` story | `arnes/middleware/token_optimizer.py:47`, `arnes/middleware/verification.py:69` |
| 28 | MEDIUM   | `VerificationLayer.complete` passes `response_schema=...` to the underlying `LLMProvider.complete`, but `LLMProvider.complete` signature has no `response_schema` parameter → 3 mypy `call-arg` errors | `arnes/llm/base.py` (missing kwarg), `arnes/middleware/{cost_guard,token_optimizer,verification}.py` |
| 29 | MEDIUM   | `Tool.execute` abstract signature uses `args: dict[str, Any]` instead of the tool's `Args` schema — `validate_args` exists but is never called in the executor | `arnes/tools/base.py:120-123, 125-132`, `arnes/playbooks/executor.py:373-401` |
| 30 | MEDIUM   | `schema.validate_step_ids` uses `ids.count(x) > 1` inside a set comprehension — O(n²) for duplicate detection (use `collections.Counter`) | `arnes/playbooks/schema.py:179` |
| 31 | MEDIUM   | `Playbook.get_step` only descends one level of `parallel` branches; nested parallel (or `parallel` inside `parallel`) returns None silently | `arnes/playbooks/schema.py:184-193` |
| 32 | MEDIUM   | `Thread.reduce()` is O(n) on every call with no caching; the immutable `append` already returns a new `Thread`, so a cached `_reduced_state` invalidated on `append` is trivial | `arnes/thread/thread.py:108-131` |
| 33 | MEDIUM   | `Harness.run` swallows all exceptions into `{"success": False, "error": str(e)}` — traceback is lost (only structlog sees it, on stderr) | `arnes/agent/agent.py:116-126`, `arnes/playbooks/executor.py:297-307` |
| 34 | MEDIUM   | `pyproject.toml` declares `mcp>=1.0,<2` as a hard dependency but the codebase never imports it (1+ MB of dead weight on every install) | `pyproject.toml:59` |
| 35 | MEDIUM   | `arnes/mcp/server.py:serve_http` imports `aiohttp` but `aiohttp` is not in `pyproject.toml` dependencies or optional-dependencies | `arnes/mcp/server.py:287`, `pyproject.toml:50-65` |
| 36 | MEDIUM   | `_patch_server_class()` monkey-patches `serve_stdio` and `serve_http` onto `ArnesMCPServer` after class definition instead of just declaring them as `async def` methods | `arnes/mcp/server.py:311-322` |
| 37 | MEDIUM   | `arnes/mcp/server.py:265` uses `__import__("sys").stdin` instead of a normal `import sys` at the top of the file | `arnes/mcp/server.py:265` |
| 38 | MEDIUM   | `arnes/middleware/token_optimizer.py:125` uses `__import__("time").time()` instead of `import time` at module top | `arnes/middleware/token_optimizer.py:125` |
| 39 | MEDIUM   | Structlog logs to stderr by default with no configuration; `arnes run` mixes internal `llm_call_tracked` info logs with the rich CLI panel — noisy UX, no `--verbose/--quiet` flags | `arnes/cli/main.py:273-289` (no structlog config), any module `logger.info(...)` |
| 40 | MEDIUM   | README mismatches reality: claims "30-50 playbooks" and "10 playbooks" in v0.1 roadmap — only 4 ship; "5-12 specialists" — only 5 ship; "v0.5.0 — ARNES as MCP server" but README also says MCP is ✅ v0.1 | `README.md:148, 182, 286, 290` |
| 41 | MEDIUM   | README quickstart says `arnes init --manual debug-python-issue` then `arnes run manuals/debug-python-issue.yaml` — but `arnes init --manual` scaffolds a *template*, not the actual example. A new dev expecting the curated `debug-python-issue.yaml` from the README gets an empty stub instead | `README.md:226-237`, `arnes/cli/main.py:367-381` |
| 42 | MEDIUM   | `arnes lint` doesn't detect nonexistent specialists — only validates `@`-prefix syntax; users discover "Specialist '@nonexistent' not registered" only at runtime | `arnes/playbooks/compiler.py:152-189` (deferred-to-runtime comment), `arnes/cli/main.py:146-162` |
| 43 | MEDIUM   | `playbooks/library/__init__.py` exists but is empty — README and AGENTS.md reference a curated playbook library that doesn't exist | `arnes/playbooks/library/__init__.py` (empty), `README.md:182` |
| 44 | MEDIUM   | `executor._resolve_input` returns `{"__resolved_str__": ...}` or `{"__input__": ...}` when input is a string or non-dict — magic keys leaking into specialist input | `arnes/playbooks/executor.py:504-527` |
| 45 | MEDIUM   | `_resolve_expr` silently returns the literal template string `{{ expr }}` when a reference is missing instead of raising — typos in `{{ steps.tpyo.output }}` produce a string `{{ steps.tpyo.output }}` passed to the LLM as input, no warning | `arnes/playbooks/executor.py:577-579` |
| 46 | LOW      | `SpecialistConfig.pydantic_model` and `output_schema` overlap — unclear which wins; specialist code checks `pydantic_model` first, then `output_schema`, but the LLM call only sets `response_format=json_object` if *either* is set (no schema actually passed to the LLM) | `arnes/specialists/base.py:114-139, 256-331` |
| 47 | LOW      | `Specialist._tool_to_schema` uses `getattr(tool, "Args", None)` — runtime attr lookup instead of typed access | `arnes/specialists/base.py:345-357` |
| 48 | LOW      | `__init__.py` doesn't re-export `PlaybookExecutor`, `PlaybookRunResult`, `PlaybookStep`, `ConditionalBranch`, `HITLGate`, `RetryPolicy`, `ToolContext` — users have to know the submodule paths | `arnes/__init__.py:31-55` |
| 49 | LOW      | `agent/__init__.py` re-exports deprecated `Agent`, `AgentConfig` — keeps the manifesto violation alive in the public API surface | `arnes/agent/__init__.py:3-5` |
| 50 | LOW      | `arnes/__init__.py` docstring is a Spanish sentence; doesn't tell new users what to import | `arnes/__init__.py:1-6` |
| 51 | LOW      | `Event` base allows `data: dict[str, Any]` with no shape validation per event subtype (declared but unused `Literal` discriminated union) | `arnes/thread/events.py:74-220` |
| 52 | LOW      | `TokenOptimizer._is_fresh` does `import time` inside the function on every cache check | `arnes/middleware/token_optimizer.py:197-200` |
| 53 | LOW      | `CostGuard.complete` sets `self._paused = True` then immediately `self._paused = False` on the next line — the pause HITL is a no-op | `arnes/middleware/cost_guard.py:153-161` |
| 54 | LOW      | `executor.py` is 582 lines — AGENTS.md says ">500 lines = doing too much". Split: `_executor.py` (run loop), `_step.py` (step execution), `_templates.py` (input resolution), `_branches.py` (conditional/parallel/skip) | `arnes/playbooks/executor.py` |
| 55 | LOW      | `arnes list playbooks --dir <nonexistent>` prints a yellow warning and returns silently instead of exiting with code 1 — scripts can't detect failure | `arnes/cli/main.py:117-143` |
| 56 | LOW      | Test fixtures duplicate `SchemaValidMockProvider` across 3 files (CLI, test_executor, test_e2e) — should be `arnes.llm.testing.SchemaValidMockProvider` | `arnes/cli/main.py:304-365`, `tests/unit/test_executor.py:13-64`, `tests/integration/test_e2e.py:15-60` |
| 57 | LOW      | Tests don't cover: HITL gates, retry policy, real `conditionals` (when clause), cross-branch parallel dependencies, `saltar_a` skip semantics, MCP server, OllamaProvider, LiteLLMProvider | `tests/` |
| 58 | LOW      | Coverage is 65.37% — barely above the 65% gate; `arnes/mcp/server.py` is 0%, `arnes/llm/litellm_provider.py` is 0%, `arnes/llm/ollama.py` is 0%, `arnes/cli/main.py` is 33% | `pyproject.toml:195` (`--cov-fail-under=65`) |
| 59 | LOW      | `_MANUAL_TEMPLATE_EN` references `https://arnes.dev/playbook-dsl` — domain doesn't resolve; dead link in every scaffolded file | `arnes/cli/main.py:406` |
| 60 | LOW      | `CONTRIBUTING.md` references `examples/` and `docs/` directories that don't exist in the repo | `CONTRIBUTING.md`, `AGENTS.md:79-87` |

---

## Top 5 mandatory improvements before launch

### 1. Fix the broken conditional-branch executor (CRITICAL — release blocker)

**File:** `arnes/playbooks/executor.py:439-483`

Replace every Spanish field reference with the English one, and the Spanish action-string comparisons with the actual `Literal` values from `ConditionalBranch.action` (`"call"`, `"terminate"`, `"skip"`).

```python
async def _handle_conditional_branch(
    self,
    step: PlaybookStep,
    branch: ConditionalBranch,            # add the type
    thread_holder: list[Thread],
    outputs: dict[str, Any],
    cost_guard: CostGuard,
    playbook: Playbook,
) -> dict[str, Any]:
    thread_holder[0] = thread_holder[0].append(
        ConditionalBranchEvent(
            thread_id=thread_holder[0].id,
            step_id=step.id,
            data={
                "condition": branch.when or "if_not_met",
                "branch": branch.action,
            },
        )
    )

    if branch.action == "call" and branch.specialist:
        fallback_step = PlaybookStep(
            id=f"{step.id}__fallback",
            specialist=branch.specialist,        # was: especialista
            input=branch.input or {},
        )
        result = await self._execute_specialist(
            fallback_step, thread_holder, outputs, cost_guard, playbook
        )
        outputs[fallback_step.id] = result.get("output")
        return {"terminate": None, "result": result}

    if branch.action == "terminate":
        return {"terminate": branch.terminate}

    if branch.action == "skip" and branch.skip_to:
        skip_set = outputs.setdefault("__skip_steps_until", {})
        skip_set[branch.skip_to] = True
        return {"terminate": None}

    return {"terminate": None}
```

Also fix the call site at `executor.py:164` (`branch_result.get("terminar")` → `branch_result.get("terminate")`).

Add a regression test that **fails** a step with `if_not_met: action: terminate` and asserts the run aborts with the right reason. The existing `test_conditional_branch_terminate` only tests the success path and must not be the only conditional test.

### 2. Make `mypy --strict` actually pass (CRITICAL — would have caught #1)

**Files:** 8 files (see mypy output above)

The most important fixes:
- Add `response_schema: dict[str, Any] | None = None` to `LLMProvider.complete` in `arnes/llm/base.py` (or document it as `**kwargs` and propagate consistently).
- Make `TokenOptimizer`, `VerificationLayer`, `CostGuard` either subclass `LLMProvider` or register as structural protocols — eliminates the `# type: ignore[arg-type]` at `executor.py:345`.
- Fix `SpecialistRegistry.list` / `ToolRegistry.list` — they shadow the builtin `list` and confuse mypy (`valid-type` error). Rename to `names()` or `list_names()`.
- Type the `branch` parameter in `_handle_conditional_branch` (would have surfaced issue #1 at type-check time).
- Replace `playbook.metadata.name` accesses with an assert or `if playbook.metadata is None: raise ...` guard at the top of each consumer.
- Fix the 6 `union-attr` errors in `arnes/mcp/server.py` by guarding against `metadata is None`.
- Add `types-PyYAML` to dev dependencies to silence the yaml stubs error.
- Drop the deprecated `Agent = Harness` alias (issue #12) — removes one `valid-type` and one public-API violation in one stroke.

Once mypy passes, add `mypy arnes/` to the CI workflow and to `pre-commit`. AGENTS.md already mandates it; CI must enforce it.

### 3. Finish the Spanish→English cleanup across the user-visible surface (HIGH)

The YAML keys are translated; the runtime strings are not. The remaining Spanish residue makes the project look half-finished to an English-speaking alpha user.

Specific cleanups (one PR, ~30 lines):
- `arnes/__init__.py:4-5` — translate the module docstring to English.
- `arnes/agent/agent.py:4-9` — translate the manifesto quote to English (or remove it from the docstring and link to `MANIFESTO.md`).
- `arnes/agent/agent.py:129-132` — delete `Agent = Harness` and `AgentConfig = HarnessConfig`. Update `arnes/agent/__init__.py:3-5` to stop re-exporting them.
- `arnes/cli/main.py:67` — `--output` help → `"Save run log to file"`.
- `arnes/cli/main.py:80-81` — delete the `ejecutar` Spanish alias.
- `arnes/cli/main.py:278, 294, 299-301` — change `Bitácora saved to` and `bitacora-<name>-<ts>.md` filename to `Run log saved to` and `arnes-run-<name>-<ts>.md`.
- `arnes/cli/main.py:304-365` — move `_SchemaValidMockLLMProvider` to `arnes/llm/testing.py` (or `arnes/testing.py`), type its signature, deduplicate with the 3 copies in tests.
- `arnes/thread/thread.py:158` — `# Bitácora ARNES — Thread {id}` → `# ARNES run log — Thread {id}`. Keep "bitácora" only in `MANIFESTO.md` / Spanish docs as a Latam-identity nod.
- `arnes/mcp/server.py:83, 169` — default `dir` from `"manuales"` to `"manuals"`.
- `arnes/mcp/server.py:204` — `bitacora_preview` → `run_log_preview`.
- `arnes/playbooks/executor.py:121, 154, 448, 460, 473, 476` — Spanish comments/docstrings → English.

### 4. Replace the hand-rolled MCP server with the official `mcp` SDK (HIGH — currently false advertising)

**Files:** `arnes/mcp/server.py` (rewrite), `pyproject.toml:59`

The current `ArnesMCPServer` is a hand-rolled JSON-RPC-over-stdio implementation that the file's own docstring admits is not spec-compliant: `"For full MCP spec compliance, use the official mcp Python SDK and wrap this class."` README still advertises `✅ MCP v0.1` for Claude Desktop / Cursor / Cline / Zed — that's false.

`mcp>=1.0,<2` is already in `pyproject.toml:59` (1+ MB installed) but **never imported**. Either:

(a) **Recommended:** rewrite `ArnesMCPServer` on top of `mcp.server.Server` + `mcp.server.stdio.stdio_server`. Tools become `@server.call_tool()` handlers. This is ~80 lines and gets spec-compliant Claude Desktop support for free. Remove the `_patch_server_class()` hack, the `__import__("sys")` hack, and the `aiohttp` import (the SDK handles transports).

(b) **Minimum viable:** keep the hand-rolled server but (1) drop the `mcp` dependency from `pyproject.toml` since it's unused, (2) add `aiohttp` to `[project.optional-dependencies] mcp`, (3) explicitly downgrade the README claim from `✅ v0.1` to `⚠️ experimental stdio only — full SDK integration in v0.2`, (4) test that Claude Desktop can actually `tools/list` and `tools/call` against it.

Either path needs at least one smoke test in `tests/integration/test_mcp_stdio.py` that exercises `initialize` → `tools/list` → `tools/call` → response. The current `arnes/mcp/server.py` is at **0% coverage**.

### 5. Stop swallowing exceptions and start enforcing the schema-parsed-but-unused features (HIGH)

Three sub-fixes that together move the DSL from "looks declarative" to "is declarative":

**(a) Surface real errors instead of `{"success": False, "error": str(e)}`.**
`Harness.run` (`arnes/agent/agent.py:124-126`) catches `Exception` and returns the stringified message, dropping the traceback. New users debugging a failing playbook see only `"Connection refused"` with no clue where it came from. Either:
- Re-raise a typed `ArnesError` with context (specialist name, step id, last thread event) and let the CLI pretty-print it, OR
- Return `{"success": False, "error": str(e), "traceback": traceback.format_exc(), "last_event": ...}` so programmatic users can introspect.

Same pattern in `executor._execute_step:297-307`.

**(b) Implement `retry`, `timeout_s`, `human_approval` — or remove them from the schema.**
All three are parsed by pydantic, documented in the DSL, shown in `arnes lint` output, and silently ignored at runtime. A new dev who writes `retry: {max_attempts: 3}` thinks they have retries; they don't. Pick one:
- Implement: wrap `_execute_specialist` in a retry loop keyed on `step.retry.retry_on` substrings with `asyncio.sleep(step.retry.backoff_s)`. Wrap the whole step in `asyncio.wait_for(..., timeout=step.timeout_s)`. Honor `step.human_approval` by emitting `HumanApprovalRequestedEvent` and awaiting a callback (CLI prompts; MCP returns a "needs approval" response).
- Remove: delete `RetryPolicy`, `HITLGate`, `step.timeout_s` from `schema.py`, update README's feature table to `🚧 v0.2`, and update `arnes lint` to reject playbooks that use them.

Implementing is ~60 lines and unblocks the headline `audit-pr.yaml` example; removing is ~20 lines and honest. The current state — schema says yes, runtime says no — is the worst option.

**(c) Make `_resolve_expr` raise on missing references.**
`arnes/playbooks/executor.py:577-579` returns the literal template string `"{{ steps.tpyo.output }}"` when a step ID is misspelled, instead of erroring. The misspelled reference gets passed to the LLM as input. Compile-time detection in `PlaybookCompiler._semantic_checks` would be even better — validate that every `{{ steps.X.output }}` references a real step ID that runs before the current step.

---

## Verdict: is the DX ready for alpha?

**NO-GO for public alpha as-is.**

The headline feature demo (`audit-pr.yaml` from the README) crashes with `AttributeError: 'ConditionalBranch' object has no attribute 'accion'` the first time a step with `if_not_met` actually fails. The test suite passes because it only exercises the success path. The MCP server is advertised as ✅ v0.1 but the code itself says "for full spec compliance use the official SDK". `mypy --strict` fails with 46 errors (AGENTS.md mandates it pass). Spanish residue is scattered across user-visible strings, CLI output, MCP defaults, and module docstrings.

**GO for public alpha after the 5 mandatory fixes above.** They are individually small (the largest is the MCP rewrite at ~80 lines; the conditional-branch fix is ~20 lines). Together they take the project from "looks done but silently broken" to "honestly alpha with documented limitations". A reasonable scope for a 1–2 day focused PR sweep.

After the 5 fixes, ship with a "Known limitations in v0.1" section in the README that says:
- Parallel branches execute sequentially (true `asyncio.gather` in v0.2).
- HITL gates auto-reject in non-interactive mode (real pause/resume in v0.2).
- Retry policy is parsed but not yet enforced (v0.2).
- MCP HTTP/SSE transport is v0.2 (stdio only in v0.1).

That's an honest alpha. Ship it.
