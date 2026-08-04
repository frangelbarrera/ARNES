# Agentic Harness Ethics Policy

## Responsible AI Use

Agentic Harness is designed to give developers **control** over AI agents. We believe that
agent frameworks should be transparent, auditable, and respectful of user resources
(time, money, data).

## Core Principles

### 1. Transparency
Every prompt sent to an LLM is visible on disk. Every decision the agent makes
is logged to the audit log. No hidden behavior, no magic.

### 2. User Sovereignty
The user controls: which model to use, how much to spend, what tools the agent
can access, and when to pause for human approval. The agent never acts without
the user's configured boundaries.

### 3. Cost Consciousness
Agentic Harness enforces budget limits by default. An agent cannot silently burn through
the user's API budget. The CostGuard middleware is not optional — it is a
core feature, not an add-on.

### 4. Anti-Hallucination
The Verification Layer refuses to fabricate answers. If the LLM is uncertain,
Agentic Harness says "I don't know" rather than inventing facts. This is especially
important for research and production use cases.

### 5. No Vendor Lock-in
Agentic Harness is vendor-neutral. The default model is local (Ollama), and switching
providers is a one-line change. We will never accept vendor-only features as
first-class APIs.

## What Agentic Harness Will NOT Do

- **Agentic Harness will not auto-execute destructive actions** without human approval
  (when interactive mode is enabled). Tools like `shell`, `fs_write`, and
  `http` require explicit approval by default.

- **Agentic Harness will not hide costs.** Every run produces an audit log with exact
  token counts and USD costs. There is no "black box" billing.

- **Agentic Harness will not store your API keys.** Keys are read from environment
  variables, used just-in-time for API calls, and never persisted or logged.

- **Agentic Harness will not phone home.** No telemetry, no usage tracking, no analytics.
  Your data stays on your machine.

## Research Ethics

For researchers using Agentic Harness:

- **Reproducibility**: Use the benchmark suite with fixed seeds. Results are
  deterministic with the mock LLM provider. For real LLMs, use vcrpy cassettes
  to record and replay responses.

- **Citation**: If you use Agentic Harness in academic work, cite it using the
  [CITATION.cff](https://github.com/frangelbarrera/agentic-harness/blob/main/CITATION.cff)
  file.

- **Data integrity**: The immutable Thread event log provides a complete audit
  trail. Every run can be replayed from the event log.

## Security Disclosure

If you discover a security vulnerability in Agentic Harness, please report it privately
via GitHub Security Advisories. Do not open a public issue. See the
[Security Policy](https://github.com/frangelbarrera/agentic-harness/blob/main/SECURITY.md)
for the full policy.
