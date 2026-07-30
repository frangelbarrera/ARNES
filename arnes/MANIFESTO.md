# ARNES Manifesto

> *The harness, not the horse.*

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

We believe the agent era will be written by developers who refuse to cede
control. Who choose verbs over magic. Who prefer 50 lines they understand
over 5 lines they don't.

ARNES was born south of the equator, where doing more with less is not
aesthetic — it is survival.

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
