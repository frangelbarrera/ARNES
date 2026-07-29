# ARNES Architecture Audit

**Task ID:** AUDIT-ARCH
**Auditor:** Senior Software Architect
**Date:** 2026-07-29
**Scope:** Full source tree under `/home/z/my-project/arnes/arnes/`, `pyproject.toml`, `MANIFESTO.md`, `README.md`, `tests/`, `manuals/`
**Method:** Static review of all 5,187 LOC of source + 1,343 LOC of tests + 4 YAML manuals. Targeted dynamic verification of two suspected bugs (conditional branches and parallel-step template resolution) — both confirmed broken at runtime.
**Companion docs:** `AI_AUDIT.md` (AI-pattern defects), `COMPETITIVE_AUDIT.md` (market positioning), `SECURITY_AUDIT.md`, `DX_AUDIT.md` — this audit focuses narrowly on **architecture**, with minimal overlap.

---

## 1. Executive summary

ARNES has a **conceptually clean four-layer architecture** (Thread → Specialist → Playbook → Executor) layered over a middleware stack (CostGuard → Verification → TokenOptimizer → Provider) and exposed via an MCP server. The dependency graph is **acyclic**, the module boundaries are **sensible**, and the stateless-reducer foundation is **architecturally sound**. As a 5,200-line alpha, the shape of the system is more disciplined than most frameworks at the same stage.

However, the architecture has **one P0 defect that breaks a headline feature, two structural inconsistencies that violate the manifesto, and several scalability cliffs that will prevent production deployment** without refactoring before v1.0:

1. **Conditional branch execution is non-functional.** `PlaybookExecutor._handle_conditional_branch` (executor.py:439-483) reads Spanish attribute names (`branch.accion`, `branch.especialista`, `branch.saltar_a`, `branch.terminar`) from a `ConditionalBranch` pydantic model whose fields are English (`action`, `specialist`, `skip_to`, `terminate`). The Spanish keys are translated away in `PlaybookCompiler._translate_keys` at compile time, so by the time the model is constructed, only English fields exist. Accessing `branch.accion` raises `AttributeError` — verified at runtime. Every step with `if_not_met` that fails aborts the run instead of executing the fallback. No test exercises this path; `test_conditional_branch_terminate` only checks a successful step whose conditional never fires.

2. **Parallel-step template resolution is broken.** The README's flagship `audit-pr.yaml` example uses `{{ steps.parallel.lint.output }}` to feed synthesis — verified at runtime, this returns the **literal template string** instead of the lint output, because `_resolve_expr` walks `outputs["parallel"]["lint"]["output"]` but `outputs["parallel"]["lint"]` IS the output (no nested `["output"]` key). The synthesis step receives literal `"{{ steps.parallel.lint.output }}"` as its `lint` input and "succeeds" only because the mock reviewer returns `approve` regardless of input.

3. **Middleware wrapping is structurally inconsistent and double-wraps on the high-level path.** `Specialist.run()` (base.py:111-122) uses `if not hasattr(provider, "_provider")` to detect already-wrapped providers — but **none of the three middleware classes define `_provider`** (they all use `self.provider`). The detection always returns False, so the specialist always re-wraps. The `Harness` path produces `VerificationLayer(TokenOptimizer(CostGuard(VerificationLayer(TokenOptimizer(provider)))))` — six layers, two caches, two verification layers. The `PlaybookExecutor` path produces `VerificationLayer(TokenOptimizer(CostGuard(provider)))` — different order, no double-wrap, but with CostGuard innermost (contradicting the README claim that CostGuard is outermost).

4. **The MCP server is not decoupled from the core.** `mcp/server.py` directly imports `PlaybookExecutor`, `get_provider`, `get_default_specialist_registry`, and `CostBudget`. There is no protocol/interface boundary — the MCP server is a thin JSON-RPC dispatcher glued to the runtime. Worse, it **hand-rolls JSON-RPC** instead of using the official `mcp` Python SDK (which IS listed as a dependency in `pyproject.toml`), and `_patch_server_class()` monkey-patches `serve_stdio`/`serve_http` methods onto the class after definition — an architectural smell. The HTTP transport uses `aiohttp` which is **not in dependencies** (would ImportError at runtime).

5. **The "Agent" class still exists** despite manifesto declaration #2 ("ARNES will never have a class named `Runnable`, `Chain`, `Workflow`, or `Agent`"). `arnes/agent/__init__.py` exports `Agent` and `AgentConfig`; `arnes/agent/agent.py:131` defines `Agent = Harness`. The file is named `agent.py` and the directory is `agent/`. This is a manifesto violation in letter (the name `Agent` is exposed publicly) and spirit (the directory layout encourages contributors to keep using it).

**Scalability cliffs:** the in-memory `TokenOptimizer._cache` is a plain `dict` with no locking (concurrent playbook runs will race on eviction), `CostGuard.spent_usd` is a plain `float` mutated without synchronization (lost updates under concurrency), `PlaybookExecutor` uses `thread_holder: list[Thread] = [Thread.create()]` as a mutable cell (an anti-pattern that prevents safe concurrent step execution), and parallel branches run **sequentially** in v0.1 (acknowledged in README but the YAML keyword `parallel:` is misleading).

**Maintainability:** adding a specialist requires editing **two** files (`specialists/__init__.py` and `get_default_specialist_registry()` in `specialists/base.py`) — DRY violation. Adding a tool has the same two-file requirement. Adding an LLM provider requires editing `llm/factory.py`'s if/elif chain — no plugin discovery via `entry_points` despite `ToolRegistry`'s docstring claiming it.

**Verdict (preview):** The architecture is **conceptually right** but **operationally wrong**. Three of the seven "features" the README claims (conditionals, parallelism, MCP-native) are either broken or misleading. The architecture *can* be fixed without rewriting the foundation — but it cannot ship as v1.0 in its current state. **GO for private alpha with documented caveats; NO-GO for public alpha** until P0/P1 issues land.

---

## 2. Architectural strengths (what's done right)

### 2.1 Clean dependency graph, no circular imports

Verified by exhaustively grepping `^from arnes|^import arnes` across the source tree. The layering is strict and acyclic:

```
thread (events, thread)            ← bottom, depends on nothing internal
   ↑
llm (base, mock, factory, ollama, litellm_provider)  ← depends on nothing internal
   ↑
middleware (cost_guard, token_optimizer, verification)  ← depends only on llm
   ↑
tools (base, builtin, registry)    ← depends on nothing internal
   ↑
specialists (base + 5 specialists) ← depends on llm, middleware, tools
   ↑
playbooks (schema, compiler, executor)  ← depends on specialists, middleware, llm, thread, tools
   ↑
agent (Harness)                    ← depends on specialists, middleware, llm, tools, thread
   ↑
mcp (server)                       ← depends on playbooks, specialists, llm, middleware
   ↑
cli (main)                         ← depends on playbooks, specialists, llm, middleware
   ↑
__init__.py                        ← top-level package
```

This is **textbook layering**. A change to `thread/` cannot break `llm/`. A change to `middleware/` cannot break `tools/`. New contributors can read the codebase layer-by-layer and build a mental model in under an hour.

### 2.2 Stateless reducer pattern is correctly implemented

`Thread.reduce()` (thread.py:108-131) is a **pure function** `(state, event) → state`. The reducer `_reduce_event` is a closed `if/elif` chain over `EventType` values — no side effects, no I/O, no mutation of input state. Combined with `Thread.append()` returning a new `Thread` (immutability preserved via `events=[*self.events, event]`), this means:

- **Replay is free**: `Thread.from_events(events).reduce()` always produces the same state.
- **Time-travel debugging** is possible — you can fork a thread at any event.
- **Persistence** is just `thread.to_json()` / `Thread.from_json()` — a single round-trip.

This is **architecturally superior** to LangChain's mutable `RunnableConfig` or CrewAI's `Task.output` mutation. It is the single best design decision in the codebase.

### 2.3 Middleware composition via wrapping (decorator pattern)

`CostGuard`, `VerificationLayer`, and `TokenOptimizer` all implement `LLMProvider.complete()` and wrap another `LLMProvider`. This is the **decorator pattern done right** — each middleware is composable, swappable, and independently testable. The fact that you can write `CostGuard(VerificationLayer(TokenOptimizer(provider)))` and get a fully-instrumented provider is elegant.

The *execution* of this pattern is buggy (see §3.2), but the *pattern itself* is correct and should be preserved.

### 2.4 Separation of compilation from execution

`PlaybookCompiler` (YAML → Pydantic) and `PlaybookExecutor` (Pydantic → run) are cleanly separated. This means:

- `arnes lint` can validate a playbook without running it.
- `arnes validate_playbook` (MCP tool) is essentially free.
- Compilation errors are caught before any LLM call.
- The compiler can do semantic checks (duplicate IDs, missing `skip_to` targets, specialist-name format) that would otherwise surface at runtime.

This is **better than LangChain** where graph validation happens at runtime inside `compile()`.

### 2.5 Pydantic-v2 everywhere for typed boundaries

Every data structure that crosses a module boundary is a pydantic `BaseModel`: `Event`, `Thread`, `Playbook`, `PlaybookStep`, `ConditionalBranch`, `RetryPolicy`, `HITLGate`, `ToolResult`, `ToolContext`, `LLMMessage`, `LLMResponse`, `LLMUsage`, `SpecialistConfig`, `HarnessConfig`, `VerificationConfig`, `CostBudget`, `CacheEntry`, `PlaybookRunResult`. This means:

- Serialization to JSON is free (every model has `.model_dump_json()`).
- Validation happens at every boundary.
- `mypy --strict` can verify types across boundaries.
- The CLI/MCP server can serialize any return value with `json.dumps(..., default=str)`.

This is the right call. The codebase consistently avoids `dataclass` for boundary types as `AGENTS.md` mandates.

### 2.6 Auto-registry via `__init_subclass__`

Both `Tool` and `Specialist` use `__init_subclass__` to auto-register subclasses into a class-level `_registry` dict. Adding a new specialist is one file + one import. This is **better than CrewAI's** explicit `Agents()` registry and **better than LangChain's** string-based tool lookup.

(Caveat: the auto-registry is currently bypassed by `get_default_specialist_registry()` which manually instantiates each class. So the auto-registry is dead code. See §3.5.)

### 2.7 Specialists are config-driven, not code-driven

Each specialist is a `(system_prompt + tools + output_schema + temperature + max_iterations)` bundle declared as a `ClassVar[SpecialistConfig]`. There is no specialist "logic" — they all use the same `Specialist.run()` ReAct loop. This means:

- Adding a specialist is declarative (a config, not a class with custom methods).
- Specialists are diffable (the system prompt is a string, not a function).
- The README's "manual as code" philosophy extends to specialists — they are also "code as config".

This is architecturally aligned with the manifesto's "no magic" declaration.

### 2.8 Bitácora as a first-class artifact

`Thread.to_markdown()` produces a human-readable, diffable markdown audit log of every event in a run. This is **unique among agent frameworks** — LangSmith gives you a dashboard, ARNES gives you a file you can `git diff`. For regulated industries (banking, health, gov), this is the single most defensible architectural decision.

---

## 3. Architectural weaknesses (what's wrong)

### 3.1 P0: Conditional branch execution is non-functional

**Severity:** P0 — breaks a headline feature
**Location:** `arnes/playbooks/executor.py:439-483`

`_handle_conditional_branch` reads Spanish attribute names from a `ConditionalBranch` pydantic model that has English field names:

```python
# executor.py:454-480 (abbreviated)
"branch": branch.accion,                    # ❌ AttributeError (field is `action`)
if branch.accion == "llamar" and branch.especialista:   # ❌ both attrs missing
    fallback_step = PlaybookStep(
        id=f"{step.id}__fallback",
        especialista=branch.especialista,   # ❌ PlaybookStep rejects extra kwargs
        input=branch.input or {},
    )
if branch.accion == "terminar":             # ❌ AttributeError
    return {"terminar": branch.terminar}     # ❌ AttributeError (field is `terminate`)
if branch.accion == "saltar" and branch.saltar_a:  # ❌ both attrs missing
    skip_set[branch.saltar_a] = True        # ❌ AttributeError (field is `skip_to`)
```

The `PlaybookCompiler._translate_keys` (compiler.py:103-129) translates Spanish YAML keys to English **at compile time**, so by the time the `ConditionalBranch` pydantic model is constructed, only English fields exist. The executor's Spanish attribute access raises `AttributeError`.

**Verified at runtime:**

```
$ python3 -c "..."  # FailingProvider returns invalid JSON → step fails → if_not_met fires
AttributeError: 'ConditionalBranch' object has no attribute 'accion'. Did you mean: 'action'?
```

**Why no test catches this:** `test_conditional_branch_terminate` (test_executor.py:299-315) only verifies that a *successful* planner step with an `if_not_met` clause completes. The conditional branch is never invoked because the step succeeds. The test passes vacuously.

**Impact:** Every playbook that declares `if_not_met:` on a step that *actually fails* will crash instead of executing the fallback. This is the exact scenario conditionals exist for. The README's `audit-pr.yaml` example uses `if_not_met` on the security_audit step — if security_audit fails (which it can, e.g. on rate limits), the entire playbook crashes.

**Fix:** Replace all Spanish attribute access with English. One-pass refactor of ~10 lines.

### 3.2 P0: Parallel-step template resolution returns literal template strings

**Severity:** P0 — the flagship `audit-pr.yaml` example is non-functional
**Location:** `arnes/playbooks/executor.py:403-437, 557-581`

`_execute_parallel` stores sub-step outputs in `outputs_map[sub_step.id] = result.get("output")`, then the parent step's output becomes `outputs_map`. So `outputs["parallel"] = {"lint": <reviewer output dict>, "tests": <tester output dict>}`.

When a downstream step references `{{ steps.parallel.lint.output }}`, `_resolve_expr` walks:
1. `outputs["parallel"]` → `{"lint": ..., "tests": ...}` ✓
2. `["lint"]` → `<reviewer output dict {"verdict":"approve",...}>` ✓
3. `["output"]` → ❌ the reviewer dict has no `"output"` key → returns the literal `"{{ steps.parallel.lint.output }}"`

**Verified at runtime:** the synthesis step's user message contains:
```json
{
  "lint": "{{ steps.parallel.lint.output }}",
  "tests": "{{ steps.parallel.tests.output }}"
}
```

The playbook "succeeds" only because the mock reviewer returns `approve` regardless of input. In production with a real LLM, the synthesis step would receive literal template strings as its `lint` and `tests` inputs, producing garbage verdicts.

**Impact:** Any playbook that uses parallel branches and feeds their outputs to a later step is broken. This includes the README's hero example. The README explicitly advertises parallel branches as a v0.1 feature with a ✅.

**Fix:** Either (a) change `_execute_parallel` to store `outputs_map[sub_step.id] = {"output": result.get("output")}` so the `.output` suffix resolves, or (b) change `_resolve_expr` to also try the value directly when the final `.output` key is missing. Option (a) is more consistent with how non-parallel steps store `outputs[step.id] = step_result.get("output")` (which is the raw output, not wrapped in `{"output": ...}`) — so actually the *non-parallel* path has the same bug if a template says `{{ steps.s1.output }}` and `outputs["s1"]` is the raw output dict without an `"output"` key.

Let me verify: in `run()` line 146, `outputs[step.id] = step_result.get("output")`. So `outputs["s1"]` is the specialist's output dict (e.g. `{"verdict":"approve"}`). Then `{{ steps.s1.output }}` walks `outputs["s1"]["output"]` — but `outputs["s1"]` is `{"verdict":"approve"}` which has no `"output"` key. So **the same bug affects non-parallel steps too**. The test `test_multi_step_playbook` passes because the mock specialist returns the right JSON shape regardless of whether the template resolved.

This means **template resolution with `.output` suffix is universally broken** — the suffix only works if the upstream step's output happens to have an `"output"` key (which the specialist output schemas do not).

**Fix:** Strip the trailing `.output` (and `.salida`) suffix in `_resolve_expr` and return the value directly. The current code already does `.replace("salida", "output")` which converts `.salida` → `.output` — but then it still tries to walk `.output` as a dict key. The fix is to detect when the final part is `"output"` and skip it.

### 3.3 P1: Middleware double-wrapping and inconsistent ordering

**Severity:** P1 — produces different middleware stacks depending on entry point
**Location:** `arnes/specialists/base.py:111-122`, `arnes/agent/agent.py:97-107`, `arnes/playbooks/executor.py:108`

`Specialist.run()` uses `hasattr(provider, "_provider")` to detect already-wrapped providers:

```python
# specialists/base.py:111-122
wrapped_provider = provider
if not hasattr(provider, "_provider"):
    # Fresh wrapping
    wrapped_provider = TokenOptimizer(provider, enable_cache=True)
    if self.config.output_schema or self.config.pydantic_model:
        wrapped_provider = VerificationLayer(wrapped_provider, ...)
```

But **none of the three middleware classes define `_provider`** — they all use `self.provider`. Verified:

```
CostGuard has _provider? False
TokenOptimizer has _provider? False
VerificationLayer has _provider? False
```

So the detection always returns False, and the specialist **always re-wraps**. Combined with the `Harness` path which wraps the provider before passing it to the specialist, the resulting stack is:

```
VerificationLayer(              ← added by specialist (outer)
  TokenOptimizer(               ← added by specialist
    CostGuard(                  ← added by Harness
      VerificationLayer(        ← added by Harness
        TokenOptimizer(         ← added by Harness
          raw_provider
        )
      )
    )
  )
)
```

Six layers, two caches, two verification layers, two cost guards. The inner CostGuard accumulates spend but the outer CostGuard never sees it (and vice versa). Budget enforcement is effectively doubled or halved depending on which CostGuard trips first.

The `PlaybookExecutor` path is different — it only wraps `CostGuard`, then passes it as `provider=cost_guard` to `specialist.run()`. The specialist then wraps it as `VerificationLayer(TokenOptimizer(cost_guard))`. So the executor path produces:

```
VerificationLayer(              ← added by specialist
  TokenOptimizer(               ← added by specialist
    CostGuard(                  ← added by executor
      raw_provider
    )
  )
)
```

Three layers, one of each. **Different from the Harness path.** The README claims "CostGuard → Verification → TokenOptimizer → Provider" (CostGuard outermost), but the executor path has CostGuard **innermost**.

**Impact:**
- Budget enforcement is inconsistent across entry points.
- Two caches mean stale reads (outer cache hits while inner cache has fresher data — though this is rare in practice).
- Two verification layers mean hedging detection runs twice, replacing the response with the refusal message twice.
- The "no magic" manifesto declaration is violated — a developer cannot predict the middleware stack without tracing two code paths.

**Fix:** Define a `MiddlewareProvider` base class with a `_provider` attribute. Have all three middleware classes inherit from it. Update `Specialist.run()` to check `isinstance(provider, MiddlewareProvider)` instead of `hasattr`. Or, better: **remove the auto-wrapping from `Specialist.run()` entirely** and require the caller (Harness or Executor) to wrap once. This centralizes middleware construction.

### 3.4 P1: MCP server is not decoupled from the core

**Severity:** P1 — limits deployment flexibility and violates separation of concerns
**Location:** `arnes/mcp/server.py`

The MCP server is supposed to be a **transport adapter** — it should accept JSON-RPC requests, translate them to calls on a core API, and serialize responses. Instead, it **directly imports and instantiates core runtime objects**:

```python
# mcp/server.py:30-34
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry
```

There is no `ArnesCore` or `ArnesAPI` interface between the MCP server and the runtime. The server's `_run_playbook` method constructs a fresh `PlaybookExecutor` per request — no shared state, no thread pool, no connection pooling.

Additional issues:
- **Hand-rolled JSON-RPC** instead of using the official `mcp` Python SDK (which IS in `pyproject.toml` dependencies). The README claims "MCP-native" but the implementation is a custom reimplementation of a subset of MCP.
- **`_patch_server_class()`** monkey-patches `serve_stdio` and `serve_http` methods onto `ArnesMCPServer` after class definition. This is a code smell — the methods should be defined as `@staticmethod` or `@classmethod` directly.
- **HTTP transport uses `aiohttp`** which is **not in dependencies**. Running `arnes mcp serve --transport http` will raise `ImportError: No module named 'aiohttp'`.
- **No HTTP/SSE transport** despite the README claiming "🚧 v0.2" — actually the CLI accepts `--transport http` and tries to import `aiohttp`, which will fail. The CLI should reject `--transport http` until v0.2.
- **No `arnes_get_events` tool** despite the README listing it as one of the 4 MCP tools. The actual `TOOLS` list has `arnes_run_playbook`, `arnes_list_specialists`, `arnes_list_playbooks`, `arnes_validate_playbook` — `arnes_get_events` (which would let a client inspect a thread's event log) is missing. And `arnes_resume` (mentioned in the README architecture diagram) is also missing.

**Fix:** Define an `ArnesRuntime` facade that exposes `run_playbook()`, `list_specialists()`, `list_playbooks()`, `validate_playbook()`, `get_events()`, `resume()`. The MCP server should depend only on this facade. Use the official `mcp` SDK for transport.

### 3.5 P1: Auto-registry is dead code; DRY violations in registration

**Severity:** P1 — adding a specialist requires editing two files
**Location:** `arnes/specialists/base.py:69-74, 390-401`, `arnes/tools/base.py:97-100`

Both `Specialist` and `Tool` define `_registry: ClassVar[dict[str, type[...]]]` and use `__init_subclass__` to auto-populate it. But the auto-registry is **never read**:

```python
# specialists/base.py:390-401 — get_default_specialist_registry
def get_default_specialist_registry() -> SpecialistRegistry:
    registry = SpecialistRegistry()
    from arnes.specialists.coder import Coder
    from arnes.specialists.debugger import Debugger
    from arnes.specialists.planner import Planner
    from arnes.specialists.reviewer import Reviewer
    from arnes.specialists.tester import Tester

    for cls in [Planner, Coder, Reviewer, Tester, Debugger]:
        registry.register_class(cls)
    return registry
```

This manually imports and registers each specialist — bypassing the auto-registry entirely. Same pattern in `tools/registry.py:13-24`. So:
- Adding a specialist requires editing `specialists/__init__.py` (for the public export) AND `specialists/base.py` (for the registry).
- Adding a tool requires editing `tools/__init__.py` AND `tools/registry.py`.
- Forgetting either file means the specialist/tool is importable but not registered (silent failure).

**Fix:** Use the auto-registry. Replace `get_default_specialist_registry()` with:

```python
def get_default_specialist_registry() -> SpecialistRegistry:
    # Ensure all specialist modules are imported (triggers __init_subclass__)
    import arnes.specialists  # noqa: F401  — imports all submodules
    registry = SpecialistRegistry()
    for cls in Specialist._registry.values():
        registry.register_class(cls)
    return registry
```

Bonus: support plugin discovery via `importlib.metadata.entry_points(group="arnes.specialists")` so third-party packages can register specialists.

### 3.6 P1: LLM provider factory is not extensible

**Severity:** P1 — adding a provider requires editing core
**Location:** `arnes/llm/factory.py:20-52`

`get_provider()` is a hard-coded if/elif chain over vendor prefixes. Adding a new provider (e.g. `together/`, `fireworks/`, `perplexity/`) requires editing this file. There is no plugin discovery.

```python
if vendor == "ollama":
    from arnes.llm.ollama import OllamaProvider
    return OllamaProvider(**kwargs)
if vendor in ("anthropic", "openai", "google", "groq", "mistral", "cohere", "azure"):
    from arnes.llm.litellm_provider import LiteLLMProvider
    return LiteLLMProvider(**kwargs)
```

**Fix:** Use `importlib.metadata.entry_points(group="arnes.llm_providers")` to discover providers. Each provider registers a `(vendor_prefix, factory_callable)` entry. The default `LiteLLMProvider` becomes the fallback.

### 3.7 P1: `Agent` alias violates manifesto declaration #2

**Severity:** P1 — manifesto violation
**Location:** `arnes/agent/__init__.py:3`, `arnes/agent/agent.py:131-132`

Manifesto declaration #2: "ARNES will never have a class named `Runnable`, `Chain`, `Workflow`, or `Agent`."

But:
```python
# agent/__init__.py:3
from arnes.agent.agent import Agent, AgentConfig, Harness, HarnessConfig

# agent/agent.py:131-132
Agent = Harness
AgentConfig = HarnessConfig
```

The `Agent` name is publicly exported and is an alias for `Harness`. The directory is `agent/` and the file is `agent.py`. The AGENTS.md acknowledges this ("The `Harness` class is the high-level wrapper, NOT named `Agent`") but the code contradicts the doc.

**Fix:** Remove the `Agent`/`AgentConfig` aliases and the `agent/` directory. Move `Harness` into `arnes/harness.py` (a single file, not a package). Update `__init__.py` to export `Harness` from the new location. This is a breaking change but the alpha period is the time to make it.

### 3.8 P2: `PlaybookExecutor` is a God object (581 LOC)

**Severity:** P2 — maintainability cliff
**Location:** `arnes/playbooks/executor.py`

The executor does **seven** things in one class:
1. Run-level orchestration (the `run()` method)
2. Step dispatch (`_execute_step`)
3. Specialist invocation (`_execute_specialist`)
4. Tool invocation (`_execute_tool`)
5. Parallel branch execution (`_execute_parallel`)
6. Conditional branch handling (`_handle_conditional_branch`)
7. Template resolution (`_resolve_input`, `_resolve_template`, `_resolve_expr`)

AGENTS.md says "if a file is >500 lines, it's doing too much." The executor is 581 lines and violates this rule. The template resolution logic (lines 485-581, ~100 lines) should be extracted to `arnes/playbooks/template_resolver.py`. The conditional branch handler should be extracted to `arnes/playbooks/branch_handler.py`.

### 3.9 P2: `Specialist` base class is doing too much (401 LOC)

**Severity:** P2 — God class
**Location:** `arnes/specialists/base.py`

`Specialist` does:
1. ReAct tool-use loop (`run`)
2. Tool execution (`_execute_tool_call`)
3. HITL approval check (inside `_execute_tool_call`)
4. Schema validation (`_parse_and_validate_output`)
5. Input formatting (`_format_input`)
6. Tool-to-schema conversion (`_tool_to_schema`)
7. Middleware wrapping (the broken `hasattr(_provider)` logic)
8. Registry (`SpecialistRegistry` class — should be its own file)

The registry should move to `arnes/specialists/registry.py`. The schema validation should move to `arnes/specialists/validation.py`. The ReAct loop should stay in `Specialist.run()` but call helpers.

### 3.10 P2: Thread is immutable but executor mutates a holder

**Severity:** P2 — anti-pattern
**Location:** `arnes/playbooks/executor.py:101, 253, 282, 299, 449`

The executor uses `thread_holder: list[Thread] = [Thread.create()]` as a mutable cell to work around Thread's immutability:

```python
thread_holder[0] = thread_holder[0].append(StepStartedEvent(...))
```

This is a **code smell** — it admits that the executor's control flow doesn't fit the immutable-thread model. The reason is that step helpers need to append events, but Python doesn't have ergonomics for "threaded state" (no monadic `do` notation).

**Fix options:**
- (a) Pass `thread` as a return value from each helper: `thread, result = await self._execute_step(step, thread, ...)`. Verbose but explicit.
- (b) Introduce a `ThreadMutator` class that wraps a `Thread` and provides `append()` / `extend()` methods that mutate an internal reference. Less verbose, hides the mutation.
- (c) Use a `contextvars.ContextVar[Thread]` so helpers can access the current thread without explicit passing. Magic, but Pythonic.

Option (a) is the most aligned with the "no magic" manifesto.

### 3.11 P2: Concurrency safety is absent

**Severity:** P2 — blocks true parallelism and multi-tenant deployment
**Location:** multiple

- `CostGuard.spent_usd` is a `float` mutated via `self.spent_usd += cost` with no lock. Two concurrent `complete()` calls will lose updates.
- `CostGuard._spend_history` is a `deque` mutated without a lock.
- `TokenOptimizer._cache` is a `dict` mutated without a lock. Eviction races can leave the cache in an inconsistent state.
- `PlaybookExecutor.thread_holder` is a `list[Thread]` mutated without a lock.
- `Specialist._registry` and `Tool._registry` are `ClassVar[dict]` mutated at class-definition time — safe for single-threaded import but not for concurrent `__init_subclass__` calls (unlikely in practice).

None of this matters today because parallel branches run sequentially. But the moment v0.2 ships `asyncio.gather`, these become race conditions.

**Fix:** Wrap all mutable middleware state in `asyncio.Lock`. Or, better, make the middleware stateless and pass `spent_usd` / `cache` as explicit context (aligns with the stateless-reducer philosophy).

### 3.12 P2: In-memory cache will cause OOM in long-running processes

**Severity:** P2 — production readiness
**Location:** `arnes/middleware/token_optimizer.py:62-69, 202-210`

The cache:
- Default `cache_max_entries = 1000`.
- Each entry stores a full `LLMResponse` including `raw` (the vendor's raw response, which can be 100-500 KB for long completions).
- Worst case: 1000 × 500 KB = **500 MB** per `TokenOptimizer` instance.
- The `Harness` path creates **two** `TokenOptimizer` instances (due to double-wrapping) — so up to **1 GB** of cache per Harness instance.
- Eviction is O(n log n) sort on every eviction (line 207) — slow at 1000 entries.

For a CLI invocation this is fine. For a long-running MCP server processing 100 playbooks/day, this will OOM.

**Fix:**
- Add a `cache_max_bytes` option and evict based on serialized size.
- Use `cachetools.LRUCache` (O(1) eviction) instead of dict+sort.
- Consider making the cache optional and off by default for server deployments.
- Add a `cache.flush()` method and call it between runs.

### 3.13 P2: No persistence layer

**Severity:** P2 — no resume across process restarts
**Location:** `arnes/thread/thread.py:146-153`

`Thread.save()` and `Thread.load()` exist but are **never called by the executor**. The MCP server's `_run_playbook` creates a fresh `PlaybookExecutor` per request, runs the playbook, returns the result, and discards the thread. There is no way to:
- Resume a paused playbook after process restart.
- Inspect a past run's event log from the MCP server (`arnes_get_events` is advertised but not implemented).
- Replay a run from a specific step.

The README's architecture diagram advertises `arnes_get_events(thread_id)` and `resume` as MCP tools — neither exists.

**Fix:**
- Add a `ThreadStore` protocol with `save(thread)`, `load(thread_id)`, `list()`.
- Ship a `SQLiteThreadStore` as the default (zero-config, file-based).
- Add a `PostgresThreadStore` for multi-tenant deployments.
- Wire `PlaybookExecutor` to accept a `ThreadStore` and persist after each event.
- Implement `arnes_get_events` and `arnes_resume` MCP tools.

### 3.14 P2: Observability is insufficient for production

**Severity:** P2 — no OTel, no metrics, no distributed tracing
**Location:** `structlog` calls scattered throughout

The codebase uses `structlog.get_logger(__name__)` everywhere, which is good. But:
- **No structlog configuration** — by default, structlog logs to stderr in human-readable format. There is no JSON formatter configured, no log level set, no output routing.
- **No OpenTelemetry** — promised for v0.3, but the spans/traces that LangSmith/Logfire provide are absent. The bitácora is a post-hoc markdown dump, not a live observability feed.
- **No metrics** — no Prometheus exporter, no counters for `llm_calls_total`, `cache_hits_total`, `budget_exceeded_total`. The `stats()` methods on middleware are dicts returned on demand, not scraped.
- **No distributed tracing** — if ARNES is deployed as an MCP server behind a load balancer, there is no trace context propagation.

**Fix:**
- Configure structlog with `structlog.configure(...)` in `arnes/__init__.py` or a `arnes.logging` module.
- Add `opentelemetry-sdk` as an optional dependency. Wrap `PlaybookExecutor.run` and each middleware `complete()` in spans.
- Expose `/metrics` endpoint when running as HTTP MCP server.

### 3.15 P2: No streaming support

**Severity:** P2 — UX cliff
**Location:** `arnes/llm/base.py:66-77`

`LLMProvider.complete()` returns a single `LLMResponse`. There is no `stream()` method. The README acknowledges this (🚧 v0.2). In 2026, no streaming means:
- No token-by-token UX in CLI.
- No AG-UI streaming to MCP clients.
- Long playbooks appear to "hang" until completion.

**Fix:** Add `async def stream(...) -> AsyncIterator[LLMChunk]` to `LLMProvider`. Add a `StreamingPlaybookExecutor` that yields events as they occur. This is a significant refactor but necessary for v0.2.

### 3.16 P3: Schema validation is bypassed in production

**Severity:** P3 (already covered in AI_AUDIT §2.2 but flagged here for architectural implications)
**Location:** `arnes/specialists/base.py:128-139`

`Specialist.run()` calls `wrapped_provider.complete(messages, ..., response_format={"type": "json_object"})` but never passes `response_schema=self.config.output_schema`. The `VerificationLayer` accepts `response_schema` as a kwarg but never receives it from the specialist. Result: structured-output validation is dead code in the production path.

**Architectural fix:** Pass `response_schema` explicitly from `Specialist.run()` through the middleware chain. Or, have the `VerificationLayer` read the schema from a `ContextVar` set by the specialist.

---

## 4. Scalability assessment

### 4.1 Can this architecture handle 100 specialists? 1000 playbooks?

**100 specialists:** Yes, structurally. `SpecialistRegistry` is a dict lookup, O(1). Memory: each specialist instance is ~1 KB (config + class), so 100 KB total. The bottleneck is the `for cls in [Planner, Coder, ...]` list in `get_default_specialist_registry()` — adding 100 specialists means editing this list 100 times. **Fix §3.5 (auto-registry) before scaling past 5 specialists.**

**1000 playbooks:** The compiler is fast (~1 ms per playbook for YAML parse + pydantic validation). The MCP server's `_list_playbooks` globs the directory and compiles each playbook — at 1000 playbooks this is ~1 second, acceptable. The bottleneck is the lack of a playbook index — there is no `playbooks/index.json` or catalog. The MCP server recompiles every playbook on every `list_playbooks` call. **Fix: cache compiled playbooks by file mtime.**

### 4.2 Will the event log become a bottleneck for long-running playbooks?

**Yes, eventually.** `Thread.events` is a `list[Event]`. `Thread.reduce()` is O(n) over events. `Thread.to_markdown()` is O(n). `Thread.to_json()` is O(n) with full serialization.

For a 100-step playbook with 10 events per step (step_started, specialist_invoked, assistant_message, tool_call, tool_result, step_completed), that's 1000 events. `reduce()` takes ~1 ms. Acceptable.

For a 10,000-step playbook (long-running agent), that's 100,000 events. `reduce()` takes ~100 ms. `to_json()` produces ~50 MB of JSON. The bitácora markdown is ~20 MB. **This will block the event loop.**

**Fix:** Implement incremental reduction (cache the reduced state at a checkpoint event, only reduce events after the checkpoint). Implement streaming `to_markdown()` that yields chunks.

### 4.3 Will the in-memory cache cause OOM in production?

**Yes, in long-running MCP server mode.** See §3.12. The cache is unbounded by size (only by count), stores full `LLMResponse` including `raw`, and the double-wrapping bug doubles the cache count.

For CLI invocations (run-once-then-exit), this is fine. For a persistent MCP server processing 100 playbooks/day, expect OOM within a week.

**Fix:** §3.12.

### 4.4 Can multiple playbooks run concurrently safely?

**No.** Three blockers:
1. `CostGuard.spent_usd` is unsynchronized (§3.11).
2. `TokenOptimizer._cache` is unsynchronized (§3.11).
3. The MCP server creates a fresh `PlaybookExecutor` per request — which means **no shared budget enforcement** across concurrent playbooks. If two playbooks each have a $0.50 budget, they can collectively spend $1.00, not $0.50. The "hierarchical budget" claim (org → project → agent → task) is not implemented — there is no shared `OrgBudget` that aggregates spend across executors.

**Fix:** Introduce a `BudgetRegistry` singleton that tracks spend per (org, project, agent, task) tuple. Inject the appropriate `CostBudget` into each `PlaybookExecutor`. Add `asyncio.Lock` around `spent_usd` mutations.

---

## 5. Maintainability assessment

### 5.1 How easy is it to add a new specialist?

**Moderate.** Required steps:
1. Create `arnes/specialists/my_specialist.py` with a `Specialist` subclass and `config` ClassVar. (~30 lines.)
2. Add an import to `arnes/specialists/__init__.py`. (1 line.)
3. Add the class to the list in `get_default_specialist_registry()` in `arnes/specialists/base.py`. (1 line.)
4. Add tests in `tests/unit/test_my_specialist.py`. (~50 lines.)
5. Add a YAML example in `manuals/`. (~20 lines.)

**Two-file DRY violation** (steps 2 and 3) — easy to forget one. The auto-registry (§3.5) should eliminate step 3.

**Time estimate for a new contributor:** 30-60 minutes, including reading the existing specialist code as a template. **Acceptable for v0.1.**

### 5.2 How easy is it to add a new tool?

**Easy.** Required steps:
1. Create `arnes/tools/my_tool.py` with a `Tool` subclass, `name`/`description` ClassVars, an `Args` inner pydantic model, and an `async execute()` method. (~40 lines.)
2. Add an import to `arnes/tools/__init__.py`. (1 line.)
3. Add the class to the list in `get_default_registry()` in `arnes/tools/registry.py`. (1 line.)
4. Add tests in `tests/unit/test_tools.py` or a new test file. (~30 lines.)

**Same two-file DRY violation.** The auto-registry is dead code.

**Time estimate:** 20-40 minutes. **Good.**

### 5.3 How easy is it to add a new LLM provider?

**Hard.** Required steps:
1. Create `arnes/llm/my_provider.py` with an `LLMProvider` subclass. (~80 lines.)
2. Add an `if vendor == "myvendor":` branch to `arnes/llm/factory.py`. (3 lines.)
3. If the provider has a pricing table, add entries to `_PRICING_USD_PER_1M_TOKENS` in `litellm_provider.py`. (Variable.)
4. Add tests. (~50 lines.)

**Not pluggable** — requires editing core. No `entry_points` discovery. **Fix §3.6 before third-party providers are expected.**

**Time estimate:** 1-2 hours. **Acceptable for v0.1 but won't scale.**

### 5.4 Is the code DRY or are there copy-paste patterns?

**Mostly DRY, with three notable violations:**

1. **Specialist registration** (§3.5): two files to edit.
2. **Mock LLM provider duplicated three times**: `arnes/llm/mock.py:MockLLMProvider`, `arnes/cli/main.py:304-365:_SchemaValidMockLLMProvider`, `tests/unit/test_executor.py:13-64:SchemaValidMockProvider`, `tests/integration/test_e2e.py:15-57:SchemaValidMockProvider`. Four near-identical implementations. Should be one shared `MockLLMProvider` with specialist-aware responses.
3. **Conditional branch attribute access** (§3.1): the Spanish/English split is a translation leak — the compiler translates Spanish YAML to English, but the executor reads Spanish attributes. The DRY violation is that the field-name mapping is defined in two places (`_KEY_MAP` in compiler.py and the `branch.accion` accesses in executor.py) that must stay in sync.

### 5.5 Are abstractions at the right level? Too leaky? Too thick?

**Mostly right, with two leaks:**

1. **The `LLMProvider` abstraction is slightly too thick.** It has `complete()` returning a single `LLMResponse`, but the underlying providers (Ollama, LiteLLM) all support streaming. The abstraction prevents streaming from being added without a breaking change. **Fix: add `stream()` to the ABC with a default implementation that wraps `complete()`.**

2. **The `Tool` abstraction is slightly leaky.** `Tool.execute()` takes `args: dict[str, Any]` and re-validates against `self.Args` inside the method. The validation should happen at the registry level, not inside each tool. Currently every tool's `execute()` starts with `try: validated = self.Args.model_validate(args) except Exception as e: return ToolResult.fail(...)`. **Fix: move validation to `ToolRegistry.call(name, args, ctx)` which validates, then calls `tool.execute(validated, ctx)`.**

3. **The `Thread` abstraction is right-sized.** Immutable, append-only, serializable. No leaks.

4. **The `Playbook` abstraction is right-sized.** Declarative YAML → pydantic → DAG. No leaks.

5. **The `Specialist` abstraction is too thick.** It bundles system_prompt + tools + schema + ReAct loop + middleware wrapping + schema validation. The ReAct loop and middleware wrapping should be separated. **Fix: extract `ReActLoop` and `MiddlewareStack` as separate classes that `Specialist.run()` composes.**

### 5.6 Will new contributors understand the codebase in <1 hour?

**Yes, for the core flow.** The README's architecture diagram (YOU → MCP → Playbook Runtime → Specialist Registry → Middleware → Providers) matches the code layout. A contributor can:

- Read `MANIFESTO.md` (5 min) — understand the philosophy.
- Read `README.md` architecture section (5 min) — understand the layers.
- Read `arnes/__init__.py` (2 min) — see the public API.
- Read `arnes/thread/thread.py` (10 min) — understand the state model.
- Read `arnes/specialists/base.py` (15 min) — understand the agent loop.
- Read `arnes/playbooks/executor.py` (20 min) — understand the orchestration.

Total: ~57 minutes. **Meets the manifesto's "time to I understand this codebase" goal.**

The two things that will trip up new contributors:
1. The middleware double-wrapping (§3.3) — non-obvious and undocumented.
2. The conditional branch bug (§3.1) — a contributor following the README example will be confused when their playbook crashes.

---

## 6. Competitive analysis

### 6.1 ARNES vs LangChain vs CrewAI vs OpenAI Agents SDK

| Dimension | LangChain + LangGraph | CrewAI | OpenAI Agents SDK | **ARNES** |
|---|---|---|---|---|
| **Primary abstraction** | Python graph nodes / `create_agent` | `Agent`/`Crew`/`Task` classes | `@agent` decorator | **Declarative YAML → DAG** |
| **Layering cleanliness** | Mixed (LC has 100+ integrations in one package) | Clean (3 classes) | Clean (decorator + handoff) | **Clean (4 layers, acyclic)** |
| **State model** | Mutable `RunnableConfig` + LangGraph checkpoint | Mutable `Task.output` | Session-based | **Immutable Thread + stateless reducer** (architecturally superior) |
| **Middleware composition** | Callbacks (side effects, not wrapping) | None | None | **Decorator-pattern wrapping** (correct concept, buggy execution) |
| **Cost enforcement** | `max_tokens` only | `max_tokens` only | None | **Hierarchical USD + circuit breaker** (design is unique; impl broken under default model) |
| **MCP integration** | Via adapter | Via adapter | Native | **Native server** (but hand-rolled, not using official SDK) |
| **Streaming** | ✅ | ✅ | ✅ | ❌ (v0.2) |
| **Multi-agent** | ✅ LangGraph | ✅ flagship | ✅ handoffs | ❌ (v0.4 Crew) |
| **Persistence** | ✅ checkpointing | ✅ mem0 | ✅ sessions | ❌ (save/load exist, never called) |
| **Observability** | ✅ LangSmith (hosted) | ✅ | ✅ traces | ⚠️ structlog + bitácora (no OTel) |
| **Plugin extensibility** | ✅ entry_points | ❌ | ❌ | ❌ (factory if/elif) |
| **Test coverage** | High | Medium | Medium | 66% (claimed), **conditional branches untested** |
| **Concurrent-safe** | ✅ (LangGraph) | ⚠️ | ✅ | ❌ (unsynchronized middleware state) |
| **Auditable artifact** | LangSmith dashboard | ❌ | Traces | ✅ **Markdown bitácora** (unique) |
| **Lines of code** | ~500k (LC+LG) | ~30k | ~15k | **~5.2k** (alpha) |
| **Time-to-understand** | Days | Hours | Hours | **<1 hour** (per manifesto goal) |

### 6.2 What does ARNES do architecturally that competitors don't?

1. **Stateless reducer as the state model.** LangChain, CrewAI, and OpenAI SDK all use mutable state. ARNES's `(state, event) → state` pure function is architecturally superior for replay, debugging, and auditability. **This is the single biggest architectural advantage.**

2. **Declarative YAML playbooks compiled to a DAG.** Every competitor is Pythonic-procedural. ARNES treats agent workflows as infrastructure (Ansible-style). This resonates with platform/DevOps engineers who distrust magic classes. **Genuine differentiation.**

3. **Middleware as decorator-pattern wrapping.** LangChain uses callbacks (side effects). CrewAI and OpenAI SDK have no middleware. ARNES's `CostGuard(Verification(TokenOptimizer(provider)))` composition is the right pattern — even though the execution is buggy.

4. **Hierarchical USD budget with circuit breaker.** No competitor ships this. The design (org → project → agent → task with USD/min breaker) is what enterprises ask for. **Design is right; implementation is broken under the default free model.**

5. **Auditable markdown bitácora as a first-class artifact.** LangSmith/Logfire give you dashboards. ARNES gives you a file you can `git diff`. **Unique and defensible.**

### 6.3 What do competitors do that ARNES should learn from?

1. **Streaming is table stakes.** LangChain, CrewAI, OpenAI SDK, AutoGen, Pydantic AI, Browser-use all ship streaming. ARNES has none. **P0 for v0.2.**

2. **Plugin discovery via `entry_points`.** LangChain's entire ecosystem is built on this. ARNES has no plugin story. **P1 for v0.3.**

3. **Persistence is not optional.** LangGraph checkpointing, CrewAI's mem0, OpenAI SDK sessions — all persist state across process restarts. ARNES has `Thread.save()`/`load()` but never calls them. **P1 for v0.2.**

4. **Use the official SDKs.** LangChain uses `langchain-mcp-adapters`. CrewAI uses `mcp` SDK. ARNES hand-rolls JSON-RPC. **P1 — switch to the `mcp` SDK that's already a dependency.**

5. **Concurrent execution requires synchronization primitives.** LangGraph uses `asyncio.Lock` around graph state. AutoGen uses actors. ARNES has no locks. **P1 before shipping parallel branches.**

6. **Observability requires more than logs.** LangSmith, Logfire, OpenTelemetry — all competitors have structured tracing. ARNES has structlog calls and a markdown dump. **P2 for v0.3.**

### 6.4 Is the "manual as code" YAML DSL a competitive advantage or a liability?

**Both, depending on the audience.**

**Advantage for:**
- Platform/DevOps engineers who already use Ansible/Terraform/Helm.
- Teams that want to diff agent workflows in code review.
- Non-Python developers who want to define agents without learning Python.
- Regulated industries that need auditable workflow definitions.

**Liability for:**
- Python developers who can write a 10-line script faster than a 30-line YAML.
- Teams that need conditional logic beyond what the DSL supports (no `for` loops, no `try/except`, no arbitrary Python).
- The DSL is a new language to learn — and it's a small one, which means it has sharp edges (the `{{ steps.X.output }}` template syntax, the `if_not_met` semantics, the `parallel:` keyword that doesn't actually parallelize).

**Verdict:** The DSL is a **net advantage** for ARNES's target audience (platform engineers, regulated industries, Latam wedge). It is a **liability** for the broader Python-AI-developer market that LangChain/CrewAI serve. ARNES should lean into the "Ansible for AI agents" positioning rather than trying to compete head-on with Pythonic frameworks.

### 6.5 Is being MCP-native a real differentiator?

**Today: yes. In 12 months: no.**

Every major framework has shipped or announced MCP support in 2025-2026. LangChain, CrewAI, OpenAI SDK, AutoGen, Pydantic AI, Browser-use all have MCP adapters. The "MCP-native" label will be table stakes by 2027.

**ARNES's real differentiator is not "MCP-native" but "MCP-server-first":** ARNES is the only framework that ships as an MCP server exposing playbooks as tools, rather than as a library that consumes MCP tools. This means ARNES playbooks are invocable from Claude Desktop / Cursor / Cline / Zed without writing any Python. **This is the wedge.** But it requires the MCP server to actually work (§3.4) and to use the official SDK for protocol compliance.

---

## 7. Top 5 architectural improvements needed before v1.0

### 7.1 Fix the conditional branch executor (P0, ~2 hours)

Replace all Spanish attribute access in `_handle_conditional_branch` with English. Add a regression test that actually triggers the `if_not_met` branch (force a step to fail, verify the fallback executes). This is a one-pass refactor of ~10 lines plus a test.

### 7.2 Fix template resolution for `.output` suffix (P0, ~3 hours)

The `_resolve_expr` method walks `outputs["step_id"]["output"]` but `outputs["step_id"]` IS the output (no nested `"output"` key). Fix: detect when the final path component is `"output"` (or `"salida"`) and return the parent value. Add tests for: non-parallel step output, parallel sub-step output, nested dict output, missing step reference.

### 7.3 Centralize middleware construction (P1, ~4 hours)

Remove the auto-wrapping logic from `Specialist.run()`. Define a `MiddlewareStack` builder that takes a raw `LLMProvider` and returns a wrapped one with a documented order: `CostGuard(VerificationLayer(TokenOptimizer(provider)))`. Both `Harness` and `PlaybookExecutor` use this builder. Specialists receive an already-wrapped provider and never re-wrap. This eliminates double-wrapping and ensures consistent middleware order across entry points.

### 7.4 Replace hand-rolled MCP with official SDK + extract `ArnesRuntime` facade (P1, ~8 hours)

Define `arnes/runtime.py` with an `ArnesRuntime` class that exposes `run_playbook()`, `list_specialists()`, `list_playbooks()`, `validate_playbook()`, `get_events(thread_id)`, `resume(thread_id)`. Rewrite `mcp/server.py` to use the official `mcp` Python SDK (`from mcp.server import Server`) and depend only on `ArnesRuntime`. Add `aiohttp` to optional dependencies or remove the HTTP transport option until v0.2. Implement the missing `arnes_get_events` and `arnes_resume` tools.

### 7.5 Add persistence and concurrency safety (P1, ~16 hours)

Define a `ThreadStore` protocol (`save`, `load`, `list`). Ship `SQLiteThreadStore` as the default. Wire `PlaybookExecutor` to accept a `ThreadStore` and persist after each event. Add `asyncio.Lock` around `CostGuard.spent_usd` and `TokenOptimizer._cache`. Introduce a `BudgetRegistry` for cross-executor budget enforcement. This unlocks: resume across process restarts, concurrent playbook execution, and the `arnes_resume` MCP tool.

**Bonus (post-v1.0):**
- Extract `PlaybookExecutor` into `Executor` + `TemplateResolver` + `BranchHandler` (§3.8).
- Extract `Specialist` into `Specialist` + `ReActLoop` + `SchemaValidator` + `SpecialistRegistry` (§3.9).
- Add streaming support (§3.15).
- Add OpenTelemetry instrumentation (§3.14).
- Switch to `entry_points` for plugin discovery (§3.5, §3.6).
- Remove the `Agent` alias and `agent/` directory (§3.7).

---

## 8. Verdict: can this architecture compete with Microsoft?

**In 2026: No.** The architecture is conceptually sound but operationally incomplete. Microsoft's AutoGen (39k stars) and OpenAI Agents SDK (22k stars) have shipping implementations of streaming, multi-agent, persistence, observability, and plugin ecosystems. ARNES has none of these. Head-to-head, ARNES loses on every production dimension.

**In 2027-2028: Possibly, in a niche.** If ARNES executes on the v0.2-v1.0 roadmap AND fixes the P0/P1 issues in this audit, it can carve a defensible niche as the **"Ansible for AI agents"** — the only framework that treats agent workflows as declarative infrastructure runnable from any MCP client. This niche is unfilled today and resonates with platform engineers, regulated industries, and the Latam wedge. It is not the same niche LangChain/CrewAI occupy (Pythonic-procedural agent composition), so ARNES is not directly competing with them — it is **adjacent**.

**The architecture supports this niche.** The stateless reducer, the YAML DSL, the bitácora, the MCP-server-first deployment model — these are the right primitives for "declarative agent infrastructure." The middleware composition (CostGuard + Verification + TokenOptimizer) is the right pattern for "enterprise-grade guardrails." The bugs are in the execution, not the design.

**The architecture does NOT support head-to-head competition with Microsoft.** ARNES lacks the multi-agent orchestration (AutoGen's actors), the handoff primitive (OpenAI SDK), the streaming UX (everyone), and the hosted observability (LangSmith). Attempting to match these feature-for-feature would dilute the "harness, not the horse" identity. ARNES should lean into the niche, not chase the leaders.

**Bottom line:** The architecture is a **good foundation for a niche product, not a general-purpose framework**. Fix the P0s, ship v0.2 with persistence + streaming + the official MCP SDK, and ARNES can be the canonical choice for "declarative agent infrastructure" by 2027. Try to compete with Microsoft on breadth, and ARNES will be one of 50 forgotten agent frameworks by 2028.

---

## Appendix A: Architectural issue summary table

| ID | Severity | Issue | Location | Fix effort |
|---|---|---|---|---|
| 3.1 | P0 | Conditional branch execution broken (Spanish attrs on English model) | executor.py:439-483 | 2h |
| 3.2 | P0 | Parallel-step template resolution returns literal strings | executor.py:403-437, 557-581 | 3h |
| 3.3 | P1 | Middleware double-wrapping + inconsistent ordering | base.py:111-122, agent.py:97-107 | 4h |
| 3.4 | P1 | MCP server not decoupled; hand-rolled JSON-RPC; missing tools | mcp/server.py | 8h |
| 3.5 | P1 | Auto-registry dead code; DRY violation in registration | base.py:69-74, 390-401 | 2h |
| 3.6 | P1 | LLM provider factory not extensible (no entry_points) | llm/factory.py | 4h |
| 3.7 | P1 | `Agent` alias violates manifesto declaration #2 | agent/__init__.py, agent.py:131 | 1h |
| 3.8 | P2 | `PlaybookExecutor` is a God object (581 LOC) | playbooks/executor.py | 8h |
| 3.9 | P2 | `Specialist` base class doing too much (401 LOC) | specialists/base.py | 8h |
| 3.10 | P2 | Thread is immutable but executor mutates a holder | executor.py:101 | 4h |
| 3.11 | P2 | No concurrency safety (unsynchronized middleware state) | cost_guard.py, token_optimizer.py | 8h |
| 3.12 | P2 | In-memory cache will OOM in long-running processes | token_optimizer.py:62-69 | 4h |
| 3.13 | P2 | No persistence layer (save/load never called) | thread.py:146-153 | 16h |
| 3.14 | P2 | Observability insufficient (no OTel, no metrics) | throughout | 16h |
| 3.15 | P2 | No streaming support | llm/base.py:66-77 | 24h |
| 3.16 | P3 | Schema validation bypassed in production | base.py:128-139 | 2h |

**Total estimated effort to reach v1.0:** ~114 hours (~3 weeks of focused engineering).

---

## Appendix B: Files audited

**Source (5,187 LOC):**
- `arnes/__init__.py` (55 LOC)
- `arnes/agent/__init__.py`, `arnes/agent/agent.py` (137 LOC)
- `arnes/cli/__init__.py`, `arnes/cli/main.py` (462 LOC)
- `arnes/llm/__init__.py`, `base.py`, `factory.py`, `litellm_provider.py`, `mock.py`, `ollama.py` (424 LOC)
- `arnes/mcp/__init__.py`, `server.py` (327 LOC)
- `arnes/middleware/__init__.py`, `cost_guard.py`, `token_optimizer.py`, `verification.py` (718 LOC)
- `arnes/playbooks/__init__.py`, `compiler.py`, `executor.py`, `schema.py`, `library/__init__.py` (1,001 LOC)
- `arnes/specialists/__init__.py`, `base.py`, `coder.py`, `debugger.py`, `planner.py`, `reviewer.py`, `tester.py` (672 LOC)
- `arnes/thread/__init__.py`, `events.py`, `thread.py` (520 LOC)
- `arnes/tools/__init__.py`, `base.py`, `builtin.py`, `registry.py` (815 LOC)

**Tests (1,343 LOC):**
- `tests/unit/test_thread.py` (195 LOC)
- `tests/unit/test_executor.py` (315 LOC)
- `tests/unit/test_middleware.py` (159 LOC)
- `tests/unit/test_playbook_compiler.py` (168 LOC)
- `tests/unit/test_tools.py` (199 LOC)
- `tests/integration/test_e2e.py` (307 LOC)

**Config & docs:**
- `pyproject.toml`, `MANIFESTO.md`, `README.md`, `AGENTS.md`, `CHANGELOG.md`
- `manuals/hello-world.yaml`, `manuals/audit-pr.yaml`, `manuals/debug-python-issue.yaml`, `manuals/write-feature-tdd.yaml`

**Dynamic verification:**
- Confirmed conditional branch crash via `python3 -c "..."` reproducer (§3.1).
- Confirmed parallel template resolution returns literal strings via reproducer (§3.2).
- Confirmed middleware classes do not define `_provider` via `hasattr()` check (§3.3).
- Confirmed `Agent` is exported and is an alias for `Harness` (§3.7).

---

*Audit complete. Findings are based on source code as of commit at audit date. Dynamic verification was performed in a Python 3.12 environment with the project's `pyproject.toml` dependencies installed.*
