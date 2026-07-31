# ARNES — The Open Agent Harness

> Write the manual. ARNES compiles it into a team of specialists.

ARNES is a vendor-neutral, local-first, budget-guarded agent harness.
Write a YAML playbook that names the specialists you need and ARNES
runs it — compiling the manual into a typed, audited, cost-bounded run.

This is the docs site index. For the canonical README, see the
[GitHub repo](https://github.com/frangelbarrera/ARNES).

## Why ARNES?

- **Manual is the code.** Write what you want in YAML; ARNES runs it.
- **Local-first.** Default provider is Ollama on `localhost:11434`.
- **Vendor-neutral.** Anthropic, OpenAI, Google, Groq via LiteLLM.
- **Budget-guarded.** Hierarchical CostGuard with hard-stop + HITL pause.
- **Auditable.** Every LLM call → bitácora → Thread → JSON / Markdown.
- **Open.** Apache-2.0. No hosted version. No vendor-only first-class APIs.

## Quick links

- [Quickstart](quickstart.md) — install, scaffold, run your first playbook.
- [Architecture](architecture.md) — the 5-layer model + manifesto.
- [Specialists](specialists.md) — `@planner`, `@coder`, `@reviewer`, `@tester`, `@debugger`.
- [Playbooks](playbooks.md) — the YAML manual format.
- [MCP Server](mcp-server.md) — expose ARNES to Claude Desktop, Cursor, Zed.
- [Benchmarking](benchmarking.md) — multi-seed, concurrent, p95 metrics.
