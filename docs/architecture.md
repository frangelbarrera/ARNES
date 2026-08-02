# Architecture

ARNES is built on 5 layers, each with a single responsibility:

```
┌─────────────────────────────────────────────────────────┐
│  5. PlaybookExecutor  — runs the manual, step by step   │
├─────────────────────────────────────────────────────────┤
│  4. Specialist        — ReAct tool-use loop + schema     │
├─────────────────────────────────────────────────────────┤
│  3. Middleware        — CostGuard / Verification / Cache │
├─────────────────────────────────────────────────────────┤
│  2. LLM Provider      — Ollama / LiteLLM / Mock          │
├─────────────────────────────────────────────────────────┤
│  1. Thread + Events   — append-only audit trail          │
└─────────────────────────────────────────────────────────┘
```

## The manifesto

ARNES is governed by 10 immutable declarations (see
[`MANIFESTO.md`](https://github.com/frangelbarrera/ARNES/blob/main/MANIFESTO.md)):

1. ARNES does not expose vendor-only features as first-class APIs.
2. ARNES will never have a class named `Runnable`, `Chain`, `Workflow`, or `Agent`.
3. ARNES ships with a token counter by default.
4. ARNES will never have a hosted version.
5. ARNES does not optimize for "time to hello world."
6. ARNES does not hide the LLM prompt.
7. ARNES has no magic.
8. ARNES will not support vendors that cannot do structured outputs.
9. ARNES will never ask for your API key.
10. ARNES will die before it changes the manifesto.

## Playbook Library (knowledge layer)

ARNES ships a catalogue of 13 domain-specific task templates
(`arnes.playbooks.library`). When a user runs `arnes plan`, a
`TaskRouter` classifies the request into a domain (mobile app, OSINT,
financial analysis, design, ...) using keyword heuristics — no LLM call
needed. The matched template enriches the planner's system prompt with:

- The recommended specialist sequence (the "action graph")
- Clarifying questions to surface to the user
- Domain-specific context (tools, reference repos, conventions)
- Known risks for the domain

Templates: `mobile_app`, `web_app`, `cli_tool`, `rest_api`, `osint`,
`financial_analysis`, `security_audit`, `data_analysis`, `devops`,
`graphic_design`, `content_creation`, `academic_research`, `generic`.

## Review loops (actor-critic refinement)

When `--loops` is passed to `arnes run`, or a step declares a `review:`
config, the executor runs an actor-critic loop after each specialist
step:

1. **Actor**: the step's specialist produces an output.
2. **Critic**: `@reviewer` (by default) evaluates the output and returns
   a verdict (`approve` / `request_changes` / `reject`) + feedback.
3. If approved → continue to the next step.
4. If not approved → re-run the actor with the critic's feedback
   appended to its input.
5. Repeat up to `max_iterations` (default 3).

Each iteration emits `REVIEW_ITERATION` and `REVIEW_COMPLETED` events
to the Thread for audit.

## Streaming

The streaming path is 5-layer:

- `LLMProvider.stream_complete()` — async iterator of `LLMResponse` chunks.
- `TokenOptimizer.stream_complete()` — passthrough (cache is v0.2).
- `VerificationLayer.stream_complete()` — passthrough (per-chunk verification v0.2).
- `CostGuard.stream_complete()` — pre-flight abort + final-chunk accounting.
- `Specialist.stream()` — ReAct loop: stream → emit audit event →
  if tool_calls, execute + iterate.

## MCP server + SSE

The HTTP transport exposes:

- `POST /` and `POST /mcp` — JSON-RPC dispatcher (the MCP tools).
- `GET /events` and `GET /sse` — Server-Sent Events stream
  (`event: <name>\ndata: <json>\n\n` frames). The stub emits a
  `server_info` event up-front, then idles on `: ping` heartbeats. v0.2
  will wire it to `PlaybookExecutor.stream` so subscribers see step
  transitions in real time.

## Why a stateless reducer?

Every action (LLM call, tool call, cost threshold) is an `Event` appended
to a `Thread`. State is derived: `(state, event) → state`. This makes
ARNES:

- **Reproducible** — same input + same mock LLM ⇒ same audit log.
- **Auditable** — the audit log is the entire forensic record.
- **Parallel-safe** — `asyncio.gather` over parallel branches, no shared
  mutable state.
