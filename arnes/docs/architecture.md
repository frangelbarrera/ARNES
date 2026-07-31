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

1. The manual is the code.
2. Specialists are stateless; the Thread is the only state.
3. The harness never asks for API keys.
4. There is no hosted version of ARNES.
5. Local-first; cloud is opt-in.
6. The bitácora is the contract.
7. Budget is a hard constraint, not a hint.
8. No vendor lock-in.
9. No hidden prompts.
10. ARNES will die before it changes the manifesto.

## Streaming (R15)

The streaming path is 5-layer:

- `LLMProvider.stream_complete()` — async iterator of `LLMResponse` chunks.
- `TokenOptimizer.stream_complete()` — passthrough (cache is v0.2).
- `VerificationLayer.stream_complete()` — passthrough (per-chunk verification v0.2).
- `CostGuard.stream_complete()` — pre-flight abort + final-chunk accounting.
- `Specialist.stream()` — R15 ReAct loop: stream → emit audit event →
  if tool_calls, execute + iterate.

The CLI's `arnes stream` command uses `Harness.stream_with_audit()` which
returns `(chunks, thread)` so the audit trail is recorded in a real
`Thread` mutated in place as the stream is consumed.

## MCP server + SSE (R15)

The HTTP transport exposes:

- `POST /` and `POST /mcp` — JSON-RPC dispatcher (the MCP tools).
- `GET /events` and `GET /sse` — Server-Sent Events stream
  (`event: <name>\ndata: <json>\n\n` frames). R15 stub emits a
  `server_info` event up-front, then idles on `: ping` heartbeats. v0.2
  will wire it to `PlaybookExecutor.stream` so subscribers see step
  transitions in real time.

## Why a stateless reducer?

Every action (LLM call, tool call, cost threshold) is an `Event` appended
to a `Thread`. State is derived: `(state, event) → state`. This makes
ARNES:

- **Reproducible** — same input + same mock LLM ⇒ same bitácora.
- **Auditable** — the bitácora is the entire forensic record.
- **Parallel-safe** — `asyncio.gather` over parallel branches, no shared
  mutable state.
