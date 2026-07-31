# ARNES vs Competitors — Detailed Comparison

## Feature Matrix

| Feature | ARNES | LangChain | CrewAI | OpenAI Agents SDK | AutoGen | Pydantic AI |
|---|---|---|---|---|---|---|
| **Agent definition** | Declarative YAML | Python procedural | Python classes | Python decorator | Python classes | Python functions |
| **Distribution** | MCP server + library | Library | Library | Library (OpenAI-only) | Library | Library |
| **Pre-built specialists** | ✅ 5 (planner, coder, reviewer, tester, debugger) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Curated playbooks** | ✅ 10 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Token optimization** | ✅ Routing + cache + compaction (v0.2) | Manual | ❌ | ❌ | ❌ | ❌ |
| **Anti-hallucination** | ✅ 5 layers (structured, refusal, hedging, confidence, critic) | DIY | ❌ | ❌ | ❌ | Partial (structured) |
| **Budget enforcement** | ✅ Hierarchical + circuit breaker + pre-flight | `max_tokens` | `max_tokens` | ❌ | ❌ | ❌ |
| **Vendor-neutral** | ✅ Default Ollama local | Partial | ✅ | ❌ | ✅ | ✅ |
| **Prompts visible** | ✅ On disk | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Streaming** | ✅ 5 layers (provider → specialist → harness → executor → CLI) | ✅ | ❌ | ✅ | ❌ | ✅ |
| **MCP server** | ✅ Native (stdio + HTTP + SSE) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Audit trail** | ✅ Markdown audit log | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Benchmark suite** | ✅ Multi-seed + concurrent | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CITATION.cff** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

## What ARNES Does Differently

### 1. The Manual Is the Code
Every other framework defines agents in Python. ARNES compiles YAML manuals
into executable DAGs. This means:
- Playbooks are diffable in PRs
- Non-developers can review and modify agent workflows
- Version control tracks agent behavior changes
- Playbooks can be shared, forked, and remixed

### 2. Cost Guardrails as a First-Class Citizen
No other framework implements hierarchical budget enforcement with:
- Org → project → agent → task inheritance
- Temporal circuit breaker (max USD/minute)
- Pre-flight cost estimation (via `peek_cost()`)
- HITL pause at 95% of budget
- Hard stop at 100%

### 3. Auditable by Design
The markdown audit log is not a log file — it's a document you can `git diff`.
For regulated industries (banking, health, government), this is non-negotiable.

### 4. MCP-Native
ARNES is the only framework that ships as an MCP server, making playbooks
invocable from Claude Desktop, Cursor, Cline, and Zed without writing Python.

## Where Competitors Are Still Ahead

| Gap | Who's ahead | ARNES plan |
|---|---|---|
| Multi-agent coordination (Crews) | CrewAI, AutoGen | v0.4 |
| Agent memory (cross-session) | Letta, MemGPT | v0.3 |
| Web UI / visual builder | Dify, Flowise | Not planned (ARNES is code-first) |
| Marketplace | LangChain Hub | v0.5 |
| Production deployments | All (k8s, helm) | v0.4 (Docker sandbox → k8s) |
| Community size | LangChain (142k★) | Growing |

## Honest Assessment

ARNES is NOT a LangChain killer. It occupies a different niche: **declarative
agent infrastructure for developers who value control, auditability, and cost
predictability.** If you want a visual builder or 500 integrations, use Dify
or LangChain. If you want your agent workflows in git, auditable, and budget-
controlled, use ARNES.
