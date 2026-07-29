<div align="center">

# ARNES

### The Open Agent Harness

**Write the manual. ARNES compiles it into a team of specialists that follows it to the letter.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://img.shields.io/github/actions/workflow/status/frangelbarrera/ARNES/ci.yml?branch=main&label=CI)](https://github.com/frangelbarrera/ARNES/actions)
[![Coverage](https://img.shields.io/endpoint?url=.coverage.json)](https://github.com/frangelbarrera/ARNES)
[![PyPI](https://img.shields.io/pypi/v/arnes.svg)](https://pypi.org/project/arnes/)
[![Discord](https://img.shields.io/discord/ARNES.svg?label=Discord)](https://discord.gg/ARNES)
[![GitHub stars](https://img.shields.io/github/stars/frangelbarrera/ARNES?style=social)](https://github.com/frangelbarrera/ARNES)

[Manifesto](MANIFESTO.md) · [Documentation](https://arnes.dev) · [Examples](examples/) · [Contributing](CONTRIBUTING.md)

</div>

---

> **If your framework needs a debugger for your debugger, it is the wrong framework.**

ARNES is not a framework. It is a **harness**: the control layer that lets you
orchestrate AI agents without surrendering your prompts, your context, your
model, or your money.

We do not ask you to learn magic classes. We ask you to write a manual in
YAML. We compile it into a DAG of specialists, run it with cost guardrails
and anti-hallucination middleware, and return an auditable bitácora.

```bash
pip install arnes
arnes run manuals/debug-python-issue.yaml
```

---

## Why ARNES exists

Agent frameworks in 2024–2026 share three defects:

1. **They are black boxes.** You cannot read the prompt sent to the LLM. You
   cannot see what decision the model router made. You cannot diff your agent
   stack.
2. **They have vendor lock-in.** If a feature only exists in OpenAI or only
   in Anthropic, they expose it as a first-class API. Your code gets tied
   to that vendor.
3. **They do not respect your money.** Without real budget enforcement, an
   agent can burn $50 in 90 seconds without you knowing until the bill
   arrives.

ARNES attacks all three. And it adds something nobody else does: **the
manual is the code.**

---

## What it looks like

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

You run it:

```bash
arnes run manuals/audit-pr.yaml
```

ARNES compiles the manual into a DAG, wakes the specialists in sequence,
applies token optimization and verification layer on every LLM call, and
returns:

```
✅ Manual executed in 23.4s
   3 specialists activated
   4 steps executed (1 conditional triggered)
   Tokens: 1,247 (47% savings vs baseline)
   Cost: $0.0042 USD
   Bitácora: ./bitacora-audit-pr-20260728-164523.md
```

The bitácora is a markdown file with every step, every decision, every prompt
sent, every response received. You can diff it, version it, share it.

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
| | Parallel branches (sequential in MVP) | ⚠️ v0.1 (true parallelism in v0.2) |
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
| **Sandbox** | Docker hardened (Tier 1 dev-local) | ⚠️ v0.1 (wiring pending, requires ARNES_DEV_MODE=1) |
| | gVisor (Tier 2 production) | 🚧 v0.4 |
| **Multi-agent** | Single-agent default | ✅ v0.1 |
| | Crew (sequential/hierarchical) | 🚧 v0.4 |
| | A2A with trust | 🚧 v0.5 |
| **Observability** | Structured event log | ✅ v0.1 |
| | Auditable markdown bitácora | ✅ v0.1 |
| | OpenTelemetry exporter | 🚧 v0.3 |

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

```bash
# With pip
pip install arnes

# With uv (recommended)
uv add arnes

# With extras for specific vendors
pip install "arnes[ollama,anthropic,openai]"
```

## Quickstart (60 seconds)

```bash
# 1. Install
pip install arnes

# 2. Create your first manual
arnes init --manual debug-python-issue

# 3. Run it (uses Ollama local by default, $0 cost)
arnes run manuals/debug-python-issue.yaml
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

## Roadmap

- **v0.1.0 (Q1 2026)** — MVP: 5 specialists, 10 playbooks, basic DSL, MCP server, Token Optimizer v0, Verification v0, Cost Guard.
- **v0.2.0** — Bidirectional MCP client, HITL as tool, AG-UI streaming, Docker sandbox.
- **v0.3.0** — Episodic memory, context compaction, critic loop, 5 more specialists.
- **v0.4.0** — Multi-agent Crew, PolicyEngine, gVisor sandbox.
- **v0.5.0** — ARNES as MCP server exposing playbooks to Cursor/Claude Desktop.
- **v1.0.0** — A2A with trust, auto-learning skills, playbook marketplace.

---

## Community

- **Discord:** [discord.gg/ARNES](https://discord.gg/ARNES) — channels `#general`, `#español`, `#help`, `#showcase`
- **Discussions:** [GitHub Discussions](https://github.com/frangelbarrera/ARNES/discussions)
- **Issues:** [Bug reports and feature requests](https://github.com/frangelbarrera/ARNES/issues)
- **Contributing:** read [CONTRIBUTING.md](CONTRIBUTING.md) — we accept PRs from day one.

### Latam wedge

500M Spanish-speaking developers underserved by the current offering. ARNES
is born bilingual: README, docs, quickstart, and Discord in EN and ES. If
you want to contribute translations, open an issue with the `i18n` label.

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

- **Parallel branches** execute sequentially in v0.1 (true `asyncio.gather`
  comes in v0.2).
- **HITL gates** auto-reject in non-interactive mode. Real interactive HITL
  via MCP comes in v0.2.
- **Docker sandbox** is not wired up by default. Local shell execution
  requires `ARNES_DEV_MODE=1`. Full sandbox integration lands in v0.2.
- **MCP HTTP transport** is a minimal implementation (no auth, no rate
  limiting). Use stdio transport for production. Full HTTP/SSE in v0.2.
- **Retry policy** schema is defined but execution is not yet implemented.
- **Context compaction** and **few-shot pruning** are not yet implemented.
- **Confidence gate** and **critic loop** are not yet implemented.
- **Coverage** is at 66% (target: 80% by v0.2).
- **mypy --strict** is not yet enforced in CI (46 errors to fix).

**What does work in v0.1:**
- ✅ Thread + stateless reducer pattern
- ✅ 5 specialists with ReAct tool-use loop
- ✅ Playbook DSL with conditionals and template resolution
- ✅ CostGuard with budget enforcement and circuit breaker
- ✅ VerificationLayer with structured outputs and refusal pattern
- ✅ TokenOptimizer with model routing and semantic cache
- ✅ MCP server (stdio transport)
- ✅ CLI (init, run, lint, eval, list, mcp serve)
- ✅ SSRF protection with DNS resolution
- ✅ Path traversal + symlink escape detection
- ✅ Secret filtering from subprocess env
- ✅ argsFingerprint for HITL rug-pull detection
