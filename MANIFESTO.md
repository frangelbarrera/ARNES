# ARNES Manifesto

> *The harness, not the horse.*

## Problem statement

The agent layer of 2024–2026 is being shipped without reins. Teams
build with LLMs that hallucinate, vendors that lock-in, frameworks
that hide the prompt, and budgets that nobody enforces. The four
symptoms repeat across every team we have talked to:

1. **Opacity.** You cannot read the prompt the framework sent. You
   cannot diff the model-router decision. You cannot print the state
   object. When a run goes wrong, you reverse-engineer it from logs
   that were never designed for replay.
2. **Vendor capture.** Vendor-only features (OpenAI function-calling
   shapes, Anthropic prompt-caching, Google grounding) get promoted
   to first-class APIs. Switching providers means rewriting agent
   code, not swapping a string.
3. **Spend denial-of-service.** Without real budget enforcement an
   agent can burn $50 in 90 seconds in a retry loop. `max_tokens` is
   a per-call cap, not a budget. By the time the bill arrives, the
   run is long over.
4. **Audit amnesia.** Compliance, security review, and academic
   reproducibility all demand a transcript: what was asked, what was
   returned, what tools were called, what it cost. Most frameworks
   treat this as a logging afterthought rather than a primary artifact.

The cost of these symptoms is real: production incidents that can't
be reconstructed, research results that can't be peer-reviewed, and
credit-card bills that can't be explained. ARNES exists to make the
agent loop as inspectable as a Unix pipeline — because inspectable
agents are the only ones worth shipping.

Today's agent frameworks ask three things of you: abstract your logic behind
opaque classes, depend on a single LLM vendor, and trace through magic
functions you can't debug. In return they offer "productivity." What they
deliver is debt.

An agent should not be a black box. Your prompts, your context, your choice
of model, your money — all of it should be visible, substitutable, and yours.

ARNES is not a framework. It is a **harness**: the control layer that lets
you orchestrate AI agents without surrendering the reins. Designed so you can
read every call, switch providers in one line, and reason about your system
the way you reason about any procedural code.

## Constructive vision — the world ARNES builds

A reactive manifesto names what is wrong; a constructive one names what
should exist. ARNES is for the world where:

- **Every agent run leaves a paper trail.** An audit log that compliance
  can audit, security can review, and a researcher can cite. The
  transcript is the unit of trust — not the framework's promise.
- **Budgets fail closed by default.** No agent ships to production
  without a hard USD ceiling, a temporal circuit breaker, and a
  pre-flight projection that refuses to spend money it cannot afford.
  Denial-of-wallet is a real attack class; treating it as optional is
  malpractice.
- **Vendors are interchangeable.** A provider is a string. Switching
  from OpenAI to Anthropic to a self-hosted Ollama is a one-line
  change, not a rewrite. Vendor-only features stay opt-in and
  second-class.
- **Local-first is the default.** A 14-year-old with a hand-me-down
  laptop and `ollama pull llama3.2` should be able to build and ship
  agents without an API key or a credit card. Developers without access
  to enterprise infrastructure are not a market segment; they are half
  the world's developers.
- **Reproducibility is a primitive, not a goal.** The stateless
  reducer `(state, event) → state` means any run can be replayed
  from its event log. HITL resume, episodic memory, and academic
  peer-review all build on the same primitive.

ARNES is for builders who refuse to cede control — engineers who want
their prompts visible, their budgets enforced, and their vendors
replaceable. The constructive vision is not "catch up to Silicon
Valley." It is "build the tool the next generation of developers
deserves, and give it away."

---

**Control the agent. Don't worship it.**

---

## Ten declarations we will not break

1. **ARNES does not expose vendor-only features as first-class APIs.**
   If it only exists in OpenAI or only in Anthropic, it is a leak, not a feature.

2. **ARNES will never have a class named `Runnable`, `Chain`, `Workflow`, or `Agent`.**
   Composition = functions. Inheritance is debt.

3. **ARNES ships with a token counter by default.**
   If you don't know what you spent, you didn't ship.

4. **ARNES will never have a hosted version.**
   The day we host, we lose the moral right to argue against lock-in.

5. **ARNES does not optimize for "time to hello world."**
   It optimizes for "time to I understand this codebase."

6. **ARNES does not hide the LLM prompt.**
   Every prompt sent is a file on disk you can open, diff, and version.

7. **ARNES has no magic.**
   If a line does something you can't explain, it is a bug. Report it.

8. **ARNES will not support vendors that cannot do structured outputs.**
   If your model cannot return valid JSON, it is not a model for production.

9. **ARNES will never ask for your API key.**
   API keys live in your environment. ARNES reads them, it does not store them.

10. **ARNES will die before it changes the manifesto.**
    If we ever break one of these lines, it is because ARNES stopped being ARNES.

---

*Manifesto v1.0 — Fixed on the first commit. Immutable.*
