# Agentic Harness — The Open Agent Harness

> Write the manual. Agentic Harness compiles it into a team of specialists.

Agentic Harness is a vendor-neutral, local-first, budget-guarded agent harness.
Write a YAML playbook that names the specialists you need and Agentic Harness
runs it — compiling the manual into a typed, audited, cost-bounded run.

This is the docs site index. For the canonical README, see the
[GitHub repo](https://github.com/frangelbarrera/agentic-harness).

## Why Agentic Harness?

- **Manual is the code.** Write what you want in YAML; Agentic Harness runs it.
- **Local-first.** Default provider is Ollama on `localhost:11434`.
- **Vendor-neutral.** Ollama, OpenRouter, Anthropic, OpenAI, Google, Groq, Mistral, Cohere, Azure, Meta, DeepSeek, and more via LiteLLM.
- **Budget-guarded.** Hierarchical CostGuard with hard-stop + HITL pause.
- **Auditable.** Every LLM call → audit log → Thread → JSON / Markdown.
- **Knowledge layer.** 13 domain templates (mobile app, OSINT, financial analysis, design, ...) with a TaskRouter that classifies your request and enriches the plan.
- **Iterative refinement.** Actor-critic review loops (`--loops`) that re-run steps with critic feedback until they pass.
- **Open.** Apache-2.0. No hosted version. No vendor-only first-class APIs.

## Quick links

- [Quickstart](quickstart.md) — install, scaffold, run your first playbook.
- [Architecture](architecture.md) — the 5-layer model + manifesto + library + review loops.
- [Specialists](specialists.md) — 12 pre-built specialists.
- [Playbooks](playbooks.md) — the YAML manual format + review loop config.
- [MCP Server](mcp-server.md) — expose Agentic Harness to Claude Desktop, Cursor, Zed.
- [Benchmarking](benchmarking.md) — multi-seed, concurrent, p95 metrics.
