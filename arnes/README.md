<!--
  Social preview metadata. GitHub uses the repo's social card (set in
  Settings → Social preview) for link unfurls; this PNG is the asset we
  upload there. The Open Graph / Twitter tags below are also picked up by
  some third-party renderers that parse the raw README.
-->
<meta property="og:title" content="ARNES — The Open Agent Harness" />
<meta property="og:description" content="Write the manual. ARNES compiles it into a team of specialists that follows it to the letter." />
<meta property="og:image" content="https://raw.githubusercontent.com/frangelbarrera/ARNES/main/docs/social-card.png" />
<meta property="og:url" content="https://github.com/frangelbarrera/ARNES" />
<meta property="og:type" content="website" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="ARNES — The Open Agent Harness" />
<meta name="twitter:description" content="Write the manual. ARNES compiles it into a team of specialists that follows it to the letter." />
<meta name="twitter:image" content="https://raw.githubusercontent.com/frangelbarrera/ARNES/main/docs/social-card.png" />

<div align="center">

<img src="docs/logo-ARNES.png" alt="ARNES logo" width="100" />

# ARNES

### The Open Agent Harness

**Write the manual. ARNES compiles it into a team of specialists that follows it to the letter.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://img.shields.io/github/actions/workflow/status/frangelbarrera/ARNES/ci.yml?branch=main&label=CI)](https://github.com/frangelbarrera/ARNES/actions)
[![PyPI: not yet published](https://img.shields.io/badge/PyPI-not%20yet%20published-lightgrey.svg)](https://github.com/frangelbarrera/ARNES#readme)
[![Discord: coming soon](https://img.shields.io/badge/Discord-coming%20soon-lightgrey.svg)](https://github.com/frangelbarrera/ARNES/discussions)
[![GitHub stars](https://img.shields.io/github/stars/frangelbarrera/ARNES?style=social)](https://github.com/frangelbarrera/ARNES)

[Manifesto](MANIFESTO.md) · [Documentation](https://github.com/frangelbarrera/ARNES#readme) · [Examples](examples/) · [Contributing](CONTRIBUTING.md)

</div>

---

> **If your framework needs a debugger for your debugger, it is the wrong framework.**

## Why ARNES?

Agent frameworks in 2024-2026 share three defects that ARNES fixes:

1. **They are black boxes.** You can't read the prompt sent to the LLM. You can't
   see what decision the model router made. You can't diff your agent stack.
   **ARNES fixes this:** every prompt is a file on disk, every decision is in
   the bitácora, every run is replayable.

2. **They have vendor lock-in.** If a feature only exists in OpenAI or only in
   Anthropic, they expose it as a first-class API. Your code gets tied to that
   vendor.
   **ARNES fixes this:** vendor-neutral by design. Default model is local
   (Ollama, $0). Switching providers is one line. No vendor-only features.

3. **They don't respect your money.** Without real budget enforcement, an agent
   can burn $50 in 90 seconds without you knowing until the bill arrives.
   **ARNES fixes this:** hierarchical CostGuard with circuit breaker, pre-flight
   cost estimation, HITL pause at 95%, hard stop at 100%.

## Who is ARNES for?

- **Platform engineers** who want agent workflows in git, reviewable in PRs
- **DevOps teams** who need cost predictability and audit trails
- **Researchers** who need reproducible experiments and citation-ready software
- **Indie developers** who want local-first AI without API bills
- **Regulated industries** (banking, health, gov) that require full audit trails

ARNES is NOT for you if you want a visual drag-and-drop builder, 500+ pre-built
integrations, or a hosted SaaS. ARNES is code-first, local-first, and control-first.

## What it looks like

```bash
git clone https://github.com/frangelbarrera/ARNES.git
cd ARNES
uv sync --all-extras --dev
uv run arnes run manuals/hello-world.yaml --mock
```

---

## Why ARNES?

Modern agent frameworks ship features; ARNES ships control. If you have
ever lost a Friday night to "why did the agent send *that* prompt?",
waited a month for a "$50 surprise" credit-card bill, or refused to
upgrade a model because you weren't sure which call sites would silently
change behaviour, ARNES was built for you.

**The real-world problem ARNES solves**

Teams building with LLMs in 2024–2026 hit the same four walls:

1. **Opacity.** Most frameworks send prompts you can't see, route through
   model selectors you can't diff, and persist state in objects you can't
   print. When a run goes sideways, you reverse-engineer it from logs that
   were never designed for replay.
2. **Vendor capture.** Vendor-only features (OpenAI function-calling
   shapes, Anthropic prompt-caching, Google grounding) get promoted to
   first-class APIs. Switching providers means rewriting agent code, not
   swapping a string.
3. **Spend denial-of-service.** Without real budget enforcement, an
   agent can burn $50 in 90 seconds in a retry loop. `max_tokens` is a
   per-call cap, not a budget. By the time you notice, the bill is in.
4. **Audit amnesia.** Compliance, security review, and academic
   reproducibility all demand a transcript: what was asked, what was
   returned, what tools were called, what it cost. Most frameworks treat
   this as a logging afterthought rather than a primary artifact.

ARNES treats the **manual** (a YAML playbook) as the source of truth
and the **bitácora** (an append-only markdown transcript) as the audit
trail. The manual is the spec; the bitácora is the proof. Both are
files on disk — versionable, diffable, shareable.

**What ARNES attacks directly**

- **Opacity → transparency.** Every prompt sent is in the bitácora.
  Every model-routed decision is a `MODEL_ROUTED` event. Every cost
  threshold is a `COST_THRESHOLD` event. The thread is the audit log.
- **Vendor capture → vendor neutrality.** Vendor-only features are not
  promoted to first-class APIs. The provider is a string. Switching
  from `openai/gpt-4o` to `anthropic/claude-sonnet-4-20250514` to
  `ollama/llama3.2` is a one-line change.
- **Spend DoS → CostGuard.** Hierarchical budget (org → project → agent
  → task), temporal circuit breaker (max USD/minute), pre-flight
  projection (reject calls guaranteed to overshoot), HITL pause at 95%,
  hard stop at 100%.
- **Audit amnesia → bitácora.** Every run emits an append-only
  markdown transcript with every prompt, every response, every tool
  call, every cost. Diffable across commits. Citeable in a paper.

**Why now**

The agent era is being written by people who can't fully explain what
their agent did. That is a problem in production (compliance, security,
cost). It is a bigger problem in research (reproducibility, peer
review, scientific credit). ARNES makes the agent loop as inspectable
as a Unix pipeline — because inspectable agents are the only ones
worth shipping.

---

## Who is ARNES for?

ARNES is built for builders who refuse to cede control of their agent
loop to a black box. Concretely:

- **Backend engineers shipping production agents.** You need budgets
  that fail closed, prompts you can paste into a code review, and an
  audit trail that satisfies compliance. ARNES is the harness between
  your HTTP handler and the LLM.
- **ML / AI engineers benchmarking models.** You need the *same* agent
  loop to run reproducibly across providers, with per-call token and
  cost telemetry, and a cassette-replayable test suite. ARNES ships
  vcrpy cassettes, multi-seed benchmarking, and p95 reporting out of
  the box.
- **Researchers studying agent behaviour.** You need a transcript you
  can cite, a deterministic mock LLM for control runs, and a
  thread-replay primitive that lets you resume from any event.
  ARNES treats the thread as the unit of state — `(state, event) →
  state` — so every run is replayable from any checkpoint.
- **Tooling / DX teams integrating agents into IDEs.** You need an MCP
  server you can stand up in one command, with bearer-token auth,
  per-IP rate limits, and an SSE endpoint your UI can subscribe to.
  ARNES ships `arnes mcp serve` (stdio + HTTP+SSE transport) with
  auth and rate limiting built in.
- **Latin-American and Global-South developers.** 500M
  Spanish-speaking developers are underserved by current tools. ARNES
  is born bilingual (README, docs, quickstart in EN + ES), defaults to
  Ollama on `localhost` (no API key, no network, no spend), and is
  Apache-2.0 so it can be forked, hosted, and extended without asking.

**Who ARNES is NOT for (yet)**

- **No-code users.** If you want a chat UI to drag-and-drop agents,
  ARNES is not your tool today (v0.4 may add a Studio UI on top of
  the SSE endpoint).
- **Multi-agent crew orchestration.** Single-agent default in v0.1.
  Crew / A2A land in v0.4 / v0.5.
- **Hosted SaaS.** ARNES will never have a hosted version (Manifesto
  declaration #4). Self-host only.

---

## What it looks like

```
    ___
   /   |  _________ ___   _______
  / /| | / ___/ __ `__ \ / ___/ /
 / ___ |/ /  / / / / / // /__/ /
/_/  |_/_/  /_/ /_/ /_/ \____/_/
        The Open Agent Harness
```

A manual in YAML:

```yaml
# manuals/audit-pr.yaml
name: audit-pr
objective: Audit a Pull Request in a structured way
budget_usd: 0.50

steps:
  - id: read_diff
    specialist: "@reviewer"
    input:
      pr_number: 1234
      repo: "my-org/my-repo"
      focus: "Read the diff and structure it for analysis"

  - id: security_audit
    specialist: "@reviewer"
    input: "{{ steps.read_diff.output }}"
    focus: "Security review: auth flows, SQL injection, XSS, path traversal"
    if_not_met:
      action: call
      specialist: "@reviewer"
      input:
        focus: "Comment that the PR is blocked by security review"

  - id: parallel
    parallel:
      - id: lint
        specialist: "@reviewer"
        input:
          code: "{{ steps.read_diff.output }}"
          focus: "Code quality: idioms, naming, complexity"
      - id: tests
        specialist: "@tester"
        input:
          code: "{{ steps.read_diff.output }}"
          focus: "Verify tests cover the PR changes"

  - id: synthesis
    specialist: "@reviewer"
    input:
      diff: "{{ steps.read_diff.output }}"
      security: "{{ steps.security_audit.output }}"
      lint: "{{ steps.parallel.lint.output }}"
      tests: "{{ steps.parallel.tests.output }}"
      focus: "Synthesize into a final verdict: approve / request_changes / reject"
```

You run it (mock LLM, no network, $0 cost):

```bash
$ arnes run manuals/hello-world.yaml --mock
```

ARNES compiles the manual into a DAG, wakes the specialists in sequence,
applies token optimization and verification layer on every LLM call, and
returns:

```
╭────────────────────────────────────────────────────────────────────╮
│ ARNES — Executing playbook                                         │
│   Name: hello-world                                                │
│   Objective: Demonstrate the basic ARNES flow with a simple manual │
│   Model: ollama/llama3.2                                           │
│   Budget: $0.50                                                    │
╰────────────────────────────────────────────────────────────────────╯
2026-07-30 16:42:44 [info] llm_call_tracked  budget=0.5 cost_usd=0.0 \
      model=ollama/llama3.2 tokens_in=335 tokens_out=15 total_spent=0.0
2026-07-30 16:42:44 [info] llm_call_tracked  budget=0.5 cost_usd=0.0 \
      model=ollama/llama3.2 tokens_in=370 tokens_out=38 total_spent=0.0

✅ Manual executed

Steps executed: 2
Steps failed: 0
Duration: 0.01s
Tokens in/out: 705/53
Total cost: $0.0000

Bitácora saved to: bitacora-hello-world-20260730-164244.md
```

The bitácora is a markdown file with every step, every decision, every prompt
sent, every response received. You can diff it, version it, share it:

````markdown
# Bitácora ARNES — Thread 0b6ac82e-2600-42f5-a6ca-62e016df7961

**Total events:** 7

## [2026-07-30T16:42:44] step_started
**Step:** `plan`  ·  **Specialist:** `@planner`

## [2026-07-30T16:42:44] assistant_message
**Step:** `plan`  ·  **Specialist:** `@planner`
```json
{
  "model": "ollama/llama3.2",
  "tokens_in": 335,
  "tokens_out": 15,
  "cost_usd": 0.0,
  "cached": false
}
```

## [2026-07-30T16:42:44] step_completed
...
````

Want to see the whole flow end-to-end? Run the narrated demo script:

```bash
./scripts/demo.sh            # print to terminal
./scripts/demo.sh --record demo.tape && vhs demo.tape   # render a GIF
```

See [Recording a demo GIF](#recording-a-demo-gif) below for the `vhs` and
`agg` recipes.

---

## Features

| Category | Feature | Status |
|---|---|---|
| **Agent loop** | Stateless reducer `(state, event) → state` | ✅ v0.1 |
| | ReAct tool-use loop in specialists | ✅ v0.1 |
| | AG-UI streaming compatible | 🚧 v0.2 |
| **Specialists** | 5 pre-built (planner, coder, reviewer, tester, debugger) | ✅ v0.1 |
| | 5 more (security, devops, researcher, writer, optimizer) | 🚧 v0.3 |
| **Playbook DSL** | Declarative YAML compiled to DAG | ✅ v0.1 |
| | Conditional branches (`if_not_met`) | ✅ v0.1 |
| | Parallel branches (true `asyncio.gather`) | ✅ v0.1 |
| | Retry with backoff | 🚧 v0.2 (schema defined, execution pending) |
| | HITL gates (pause and request approval) | ⚠️ v0.1 (auto-reject in non-interactive) |
| **MCP** | ARNES as MCP server (Claude Desktop, Cursor, Cline, Zed) | ✅ v0.1 |
| | ARNES as MCP client (consume external MCP servers) | 🚧 v0.2 |
| | HTTP/SSE transport | 🚧 v0.2 (stdio only in v0.1) |
| **Token Optimization** | Automatic model routing by complexity | ✅ v0.1 |
| | Semantic cache | ✅ v0.1 |
| | Context compaction | 🚧 v0.2 |
| | Few-shot pruning | 🚧 v0.3 |
| **Verification Layer** | Structured outputs with pydantic | ✅ v0.1 |
| | Refusal pattern (no hallucination, says "I don't know") | ✅ v0.1 |
| | Confidence gate | 🚧 v0.2 |
| | Critic loop (second opinion) | 🚧 v0.3 |
| | Grounding RAG optional | 🚧 v0.4 |
| **Cost Guard** | Hierarchical budget (org → project → agent → task) | ✅ v0.1 |
| | Temporal circuit breaker (max USD/min) | ✅ v0.1 |
| | Automatic model fallback | ✅ v0.1 |
| | Cost HITL (pause at X% exceeded) | ⚠️ v0.1 (log warning, auto-pause pending) |
| **Sandbox** | Docker hardened (Tier 1 dev-local) | ✅ v0.1 (auto-detected when `docker` is on PATH; falls back to gated local exec via `ARNES_DEV_MODE=1`) |
| | gVisor (Tier 2 production) | 🚧 v0.4 |
| **Multi-agent** | Single-agent default | ✅ v0.1 |
| | Crew (sequential/hierarchical) | 🚧 v0.4 |
| | A2A with trust | 🚧 v0.5 |
| **Observability** | Structured event log | ✅ v0.1 |
| | Auditable markdown bitácora | ✅ v0.1 |
| | OpenTelemetry exporter | 🚧 v0.3 |
| **Benchmarks** | BenchmarkRunner with multi-seed + concurrent + p95 | ✅ v0.1 |

---

## ARNES vs the rest

| Dimension | LangChain | CrewAI | OpenAI Agents SDK | **ARNES** |
|---|---|---|---|---|
| How you define agents | Python procedural | `Agent/Crew/Task` classes | `@agent` decorator | **Declarative YAML** |
| Distribution | pip library | pip library | pip library (OpenAI-only) | **MCP server + library** |
| Pre-built specialists | ❌ | ❌ | ❌ | **✅ 5–12 ready** |
| Curated playbooks | ❌ | ❌ | ❌ | **✅ 30–50 manuals** |
| Token optimization | Manual | ❌ | ❌ | **✅ Automatic middleware** |
| Anti-hallucination | DIY | ❌ | ❌ | **✅ 5 opt-in layers** |
| Budget enforcement | `max_tokens` basic | `max_tokens` basic | ❌ | **✅ Hierarchical + circuit breaker** |
| Vendor-neutral | Partial | ✅ | ❌ | **✅ 100% (default Ollama local)** |
| Prompts visible | ❌ | ❌ | ❌ | **✅ Files on disk** |
| Latam identity | ❌ | ❌ | ❌ | **✅ Born in Latam, built for the world** |

---

## Alignment with the 12-factor-agents manifesto

ARNES aligns explicitly with the [12 factors](https://github.com/humanlayer/12-factor-agents):

| Factor | Description | ARNES |
|---|---|---|
| 1 | Natural language > structured language | ✅ Declarative YAML |
| 2 | Tools are structured outputs | ✅ Pydantic schemas |
| 3 | Give agents composable, discrete tools | ✅ Specialist registry |
| 4 | Agents are switching loops, not while loops | ✅ Event-driven reducer |
| 5 | Simple but powerful primitives | ✅ Thread + Specialist + Tool |
| 6 | Use the right tool for the job | ✅ Model routing |
| 7 | Humans are tools, not gates | ✅ HITL as a typed tool call |
| 8 | Make agents easy to debug | ✅ Markdown bitácora |
| 9 | Make agents observable | ✅ Event log + OTel (v0.3) |
| 10 | Replayable from any point | ✅ Stateless reducer + checkpoint |
| 11 | Be a state machine, not a DAG | ⚠️ We are a DAG by design (declarative) |
| 12 | Deploy as a server, not a library | ✅ Native MCP server |

---

## Installation

ARNES is not yet on PyPI. Install from source with `uv` (recommended) or `pip`:

```bash
# With uv (recommended)
git clone https://github.com/frangelbarrera/ARNES.git
cd ARNES
uv sync --all-extras --dev

# With pip (editable)
git clone https://github.com/frangelbarrera/ARNES.git
cd ARNES
pip install -e ".[dev]"
```

## Quickstart (60 seconds)

```bash
# 1. Clone and install (see Installation above)

# 2. Create your first manual
arnes init --manual hello-world

# 3. Run it with the mock LLM (no network, $0 cost)
arnes run manuals/hello-world.yaml --mock

# 4. Stream a specialist's response token-by-token
arnes stream @planner --task "Plan a blog post about ARNES" --mock

# 5. Run it with Ollama local (free, requires `ollama pull llama3.2`)
arnes run manuals/hello-world.yaml

# 6. Stream playbook step events as they complete
arnes run manuals/hello-world.yaml --mock --stream

# 7. Benchmark every playbook (multi-seed, p95, concurrent)
arnes benchmark --seeds 5 --concurrent 4
```

If you do not have Ollama installed, ARNES detects it and guides you. To use
Anthropic/OpenAI, set the env var and ARNES does the rest:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
arnes run manuals/audit-pr.yaml --model anthropic/claude-sonnet-4-20250514
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│   YOU (Claude Desktop / Cursor / CLI / Cline / Zed)            │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   ARNES MCP SERVER (1 install, 4 tools)                       │
│   run · list · events · resume                                │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   PLAYBOOK RUNTIME                                            │
│   YAML → Pydantic → DAG → Executor (conditional/parallel/HITL)│
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   SPECIALIST REGISTRY (5–12 pre-built agents)                 │
│   planner · coder · reviewer · tester · debugger · ...        │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   CROSS-CUTTING MIDDLEWARE (all LLM calls pass through it)    │
│   🧠 Token Optimizer  🛡️ Verification  💰 Cost Guard          │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   LLM PROVIDERS (vendor-neutral, default Ollama local)        │
│   ollama · anthropic · openai · google · groq                 │
└──────────────────────────────────────────────────────────────┘
```

---

## Benchmark

ARNES ships a built-in benchmark runner that executes every playbook in
`manuals/` against a deterministic seeded mock LLM (no network, $0 spend)
and reports per-playbook success rate, avg/p95 duration, tokens, and cost.
Multi-seed runs give you statistical significance; concurrent runs let
you stress-test the executor's parallel-branch path.

```bash
# 1 seed, 1 concurrent (default — quick smoke test)
arnes benchmark

# 5 seeds per playbook (catch flaky playbooks)
arnes benchmark --seeds 5

# 4 playbooks at once (stress the asyncio.gather path)
arnes benchmark --concurrent 4

# Combined: 5 seeds × 4-way parallelism
arnes benchmark --seeds 5 --concurrent 4
```

Example output:

```
              Benchmark Results — basic suite
┏━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Playbook       ┃ Runs ┃ Success ┃ Avg dur   ┃ P95 dur   ┃ Avg tokens ┃ Avg cost  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ hello-world    │    5 │    100% │    0.0089 │    0.0112 │        705 │ $0.000000 │
│ audit-pr       │    5 │    100% │    0.0241 │    0.0298 │       2104 │ $0.000000 │
│ debug-python   │    5 │    100% │    0.0187 │    0.0233 │       1583 │ $0.000000 │
│ write-feature  │    5 │    100% │    0.0312 │    0.0367 │       2431 │ $0.000000 │
└────────────────┴──────┴─────────┴───────────┴───────────┴────────────┴───────────┘

Overall: success=100%, avg_dur=0.0207s, avg_tokens=1706, avg_cost=$0.000000

Results saved to: benchmark-results.json
```

The JSON dump (default: `benchmark-results.json`, override with `--output`)
is suitable for diffing across commits or pasting into a PR description.

### Benchmark results (R15 reference run)

The numbers below are from the bundled reference run
(`docs/benchmark-results.json`, captured 2026-07-30 on the v0.1.0a1
mock LLM, 2 seeds × 2-way concurrency, 10 playbooks, 20 total runs).
The mock LLM is deterministic, so re-running with the same seeds on
the same commit reproduces these numbers bit-for-bit.

| Playbook                  | Runs | Success | Avg dur (s) | P95 dur (s) | Avg tok in | Avg tok out |
|---------------------------|------|---------|-------------|-------------|------------|-------------|
| `audit-pr`                  | 2    | 100 %   | 0.00783     | 0.01040     | 1 172      | 78          |
| `code-review-security`      | 2    | 100 %   | 0.00209     | 0.00219     | 1 754      | 130         |
| `debug-python-issue`        | 2    | 100 %   | 0.00284     | 0.00343     | 1 329      | 150         |
| `hello-world`               | 2    | 100 %   | 0.00130     | 0.00133     | 705        | 74          |
| `incident-postmortem`       | 2    | 100 %   | 0.00320     | 0.00324     | 2 196      | 234         |
| `migrate-config`            | 2    | 100 %   | 0.00277     | 0.00287     | 1 481      | 157         |
| `refactor-extract-function` | 2    | 100 %   | 0.00266     | 0.00275     | 1 481      | 157         |
| `summarize-paper`           | 2    | 100 %   | 0.00148     | 0.00152     | 1 399      | 101         |
| `write-blog-post`           | 2    | 100 %   | 0.00261     | 0.00264     | 1 530      | 151         |
| `write-feature-tdd`         | 2    | 100 %   | 0.00363     | 0.00376     | 2 111      | 215         |
| **Overall**                 | 20   | **100 %** | **0.00304** | —           | **1 515**  | **144**     |

**Cost:** `$0.000000` across all 20 runs (mock LLM, no network).

Why the durations are tiny: the mock LLM has no network round-trip,
no model inference latency, no token streaming. Real-LLM runs (with
`--model openai/gpt-4o` etc.) will be orders of magnitude slower but
should preserve the relative ordering of playbooks (parallel branches
remain faster than sequential ones of equivalent work).

The full JSON (with per-seed, per-playbook, and per-step results) is
checked into the repo so any regression in playbook success rate,
token usage, or cost shows up in `git diff`.

---

## Reproducibility

ARNES is built so that the *same* inputs produce the *same* outputs,
byte-for-byte, on every run. This is a hard requirement for both
production audit and scientific reproducibility.

**What is reproducible**

- **Mock-LLM runs.** The bundled `_SchemaValidMockLLMProvider` is fully
  deterministic: same input → same output, no time-of-day variation,
  no network calls, no API keys. `arnes run manuals/hello-world.yaml
  --mock` produces a bit-for-byte identical bitácora across runs,
  machines, and OSes.
- **Benchmark results.** `arnes benchmark --seeds N` runs each
  playbook N times with deterministic seeds. The resulting
  `benchmark-results.json` is diffable across commits — a regression
  in playbook success rate, token count, or p95 duration is visible
  in `git diff`.
- **vcrpy cassettes.** Real-LLM HTTP traffic is recorded once with
  vcrpy and replayed on every test run. Tests that exercise
  `@planner`, `@coder`, and `@reviewer` against `openai/gpt-4o`
  replay the cassette — no API spend, no network, fully deterministic.
  See `docs/benchmarking.md` for the cassette inventory and the
  regeneration procedure.
- **Thread replay.** The stateless reducer pattern `(state, event) →
  state` means any Thread can be replayed from its event log. Given
  the same event sequence, the final state is identical. This is the
  primitive that v0.2 will use for HITL resume-after-pause and the
  primitive that v0.3 will use for episodic memory.

**What is NOT reproducible (yet)**

- **Real-LLM runs.** OpenAI / Anthropic / Ollama models are
  non-deterministic by design (temperature > 0, model-side sampling).
  ARNES cannot make a non-deterministic model deterministic. What
  ARNES *can* do is record every real-LLM call into the bitácora
  so a non-deterministic run is at least *auditable* after the fact.
- **Real-time wall-clock durations.** Durations depend on machine
  load, network latency, and OS scheduling. The benchmark harness
  reports p95 *relative* durations (which are stable across runs on
  the same machine) but absolute durations are not portable.
- **Statistical significance.** v0.1 reports p95 only. Multi-seed
  runs give you the raw samples; running a Mann-Whitney U test or
  bootstrap CI on them is the caller's responsibility today. See
  `docs/statistics.md` for the recommended methodology and the
  v0.2 plan to ship a `arnes benchmark --stats` flag that does the
  analysis in-process.

**Citation**

If you use ARNES in published research, cite the version you used
(see [CITATION.cff](CITATION.cff)) and include the bitácora +
`benchmark-results.json` from your experimental runs as supplementary
material. The bitácora is the auditable artifact that lets a reviewer
reproduce your agent's behaviour step-by-step.

---

## Roadmap

- **v0.1.0 (Q1 2026)** — MVP: 5 specialists, 10 playbooks, basic DSL, MCP server, Token Optimizer v0, Verification v0, Cost Guard, Docker sandbox auto-detect, parallel branches via `asyncio.gather`.
- **v0.2.0** — Bidirectional MCP client, HITL as tool, AG-UI streaming, retry execution, full HTTP/SSE MCP transport.
- **v0.3.0** — Episodic memory, context compaction, critic loop, 5 more specialists.
- **v0.4.0** — Multi-agent Crew, PolicyEngine, gVisor sandbox.
- **v0.5.0** — ARNES as MCP server exposing playbooks to Cursor/Claude Desktop.
- **v1.0.0** — A2A with trust, auto-learning skills, playbook marketplace.

---

## Community

- **Discord:** coming soon — meanwhile, use GitHub Discussions for chat-style threads.
- **Discussions:** [GitHub Discussions](https://github.com/frangelbarrera/ARNES/discussions)
- **Issues:** [Bug reports and feature requests](https://github.com/frangelbarrera/ARNES/issues)
- **Contributing:** read [CONTRIBUTING.md](CONTRIBUTING.md) — we accept PRs from day one.

### Latam wedge

500M Spanish-speaking developers underserved by the current offering. ARNES
is born bilingual: README, docs, and quickstart in EN and ES. If you want
to contribute translations, open an issue with the `i18n` label.

---

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR:

1. Fork + clone
2. `uv sync --all-extras` for dev setup
3. `pre-commit install`
4. Create your branch: `feat/my-feature`
5. Conventional commits: `feat: ...`, `fix: ...`, `docs: ...`
6. `pytest` must pass with >65% coverage
7. Open PR — review within 48h

**Good first issues:** look for issues labeled `good-first-issue`.

---

## Sponsors

ARNES is 100% open-source under Apache 2.0. If it saves you money or time:

- [GitHub Sponsors](https://github.com/sponsors/frangelbarrera)
- [Open Collective](https://opencollective.com/arnes)
- [BuyMeACoffee](https://buymeacoffee.com/frangelbarrera)

<div align="center">

*Sponsors here*

</div>

---

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Citation

If you use ARNES in academic research, please cite it. See [CITATION.cff](CITATION.cff) for the preferred citation format.

## Acknowledgments

ARNES stands on the shoulders of:
- [LangGraph](https://github.com/langchain-ai/langgraph) — DAG engine inspiration
- [LiteLLM](https://github.com/BerriAI/litellm) — provider abstraction
- [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) — protocol
- [12-factor-agents](https://github.com/humanlayer/12-factor-agents) — manifesto
- [Pydantic](https://github.com/pydantic/pydantic) — structured data

---

<div align="center">

**[⭐ Star the repo](https://github.com/frangelbarrera/ARNES)** if this resonates.

*From Latam to the world. 🌎*

</div>

---

## Known Limitations in v0.1 (Alpha)

This is an **alpha release**. The following features are documented but have
known issues that will be fixed in v0.2:

- **HITL gates** auto-reject in non-interactive mode. Real interactive HITL
  (pausing execution and resuming on human input via the MCP transport)
  comes in v0.2. Until then, calling a HITL-gated tool without
  `interactive=True` returns a structured rejection rather than blocking.
- **LLM streaming** is implemented for all providers. `LLMProvider` declares
  `stream_complete()` (returns `AsyncIterator[LLMResponse]`). `MockLLMProvider`
  yields a single full-response chunk; `OllamaProvider` and `LiteLLMProvider`
  yield real token-by-token chunks. `CostGuard.stream_complete` tracks cost
  on the final chunk. Full per-chunk verification and semantic-cache
  population from streaming lands in v0.2.
- **MCP HTTP transport** is minimal (simple POST endpoint, no SSE). It
  *does* ship with bearer-token auth (`ARNES_MCP_TOKEN`), per-IP rate
  limiting (100 req/min), and a 1 MiB request size cap — but for production
  use the stdio transport is still recommended until full HTTP/SSE lands
  in v0.2.
- **Retry policy** schema is defined but execution is not yet implemented.
- **Context compaction** and **few-shot pruning** are not yet implemented.
- **Confidence gate** and **critic loop** are not yet implemented.

**What does work in v0.1:**
- ✅ Thread + stateless reducer pattern (append-only, O(1) per event)
- ✅ 5 specialists with ReAct tool-use loop
- ✅ Playbook DSL with conditionals and template resolution
- ✅ Parallel branches (true `asyncio.gather` concurrency, isolated Threads)
- ✅ CostGuard with budget enforcement and circuit breaker
- ✅ VerificationLayer with structured outputs and refusal pattern
- ✅ TokenOptimizer with model routing and semantic cache
- ✅ MCP server (stdio transport + minimal HTTP transport with auth/rate limits)
- ✅ CLI (init, run, run --stream, stream, lint, eval, benchmark, list, mcp serve)
- ✅ Docker sandbox auto-detected when `docker` is on PATH (Tier 1 dev-local)
- ✅ SSRF protection with DNS resolution
- ✅ Path traversal + symlink escape detection
- ✅ Secret filtering from subprocess env
- ✅ argsFingerprint for HITL rug-pull detection
- ✅ `mypy --strict` enforced in CI and passing on all source files
- ✅ Test coverage above the 65% PR gate (unit + integration + stress)

---

## Recording a demo GIF

The repo ships `scripts/demo.sh`, a narrated, deterministic demo of the
ARNES flow (run a manual → show the bitácora → list specialists → lint a
playbook). Two ways to turn it into a GIF for the README or a tweet:

**Option A — [vhs](https://github.com/charmbracelet/vhs) (recommended, deterministic):**

```bash
# Install once
brew install vhs          # macOS
# or:  go install github.com/charmbracelet/vhs@latest

# Record the tape, then render the GIF
./scripts/demo.sh --record demo.tape
vhs demo.tape             # produces demo.gif
```

**Option B — [agg](https://github.com/nathanbabcock/agg) (asciinema → GIF):**

```bash
# Install once
cargo install --git https://github.com/nathanbabcock/agg
# or:  brew install asciinema agg

# Record and convert
asciinema rec demo.cast -c "./scripts/demo.sh"
agg demo.cast demo.gif --speed 1.5 --font-family "JetBrains Mono"
```

Drop the resulting `demo.gif` into `docs/` and reference it from this README:

```markdown
![ARNES demo](docs/demo.gif)
```

> Tip: `scripts/demo.sh` uses the **mock LLM**, so the recording is fully
> offline and reproducible. No API keys, no network, $0 cost.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=frangelbarrera/ARNES&type=Date)](https://star-history.com/#frangelbarrera/ARNES&Date)

