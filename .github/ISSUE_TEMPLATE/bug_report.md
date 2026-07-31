---
name: Bug report
about: Report something that is broken or behaves unexpectedly in ARNES
title: "[bug] "
labels: ["bug", "triage"]
assignees: []
---

# Bug report

Thank you for taking the time to file a bug report! Please fill out the
sections below so we can reproduce and fix it as fast as possible.

## ARNES version

Run `arnes --version` and paste the output here.

```
arnes 0.1.0
```

## Python version

Run `python --version` and paste the output here.

```
Python 3.11.x
```

## Operating system

- OS: [e.g. Ubuntu 22.04, macOS 14.5, Windows 11]
- Architecture: [e.g. x86_64, arm64]

## Installation method

- [ ] `uv sync --all-extras --dev` (recommended)
- [ ] `pip install -e ".[dev]"`
- [ ] Other (please describe): <!-- e.g. Docker, Nix -->

## What happened?

A clear and concise description of what the bug is.

## Minimal reproduction

A minimal, copy-pasteable reproduction. The smaller, the faster we fix it.

```bash
# Steps to reproduce
arnes run manuals/hello-world.yaml --mock
```

If the bug involves a playbook, paste the **minimal** YAML that triggers it:

```yaml
name: reproduce-bug
objective: Minimal playbook that reproduces the bug
budget_usd: 0.10

steps:
  - id: step1
    specialist: "@planner"
    input:
      task: "..."
```

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened (panic, wrong output, silent failure, etc.).

## Logs / bitácora

Paste relevant logs or the bitácora content. If the bitácora file is large,
attach it or link to a gist. **Redact any secrets, tokens, or PII before
sharing.**

```
2026-07-30 12:00:00 [info     ] llm_call_tracked ...
✅ Manual executed
...
```

## Additional context

- LLM provider in use: [e.g. ollama, anthropic, openai, mock]
- Model: [e.g. ollama/llama3.2, anthropic/claude-sonnet-4-20250514]
- Environment variables set: [e.g. `ARNES_DEV_MODE=1`, `ANTHROPIC_API_KEY=set`]
- Anything else that might help us triage?

---

**Checklist before submitting:**

- [ ] I have searched [existing issues](https://github.com/frangelbarrera/ARNES/issues) for duplicates.
- [ ] I have redacted secrets / PII from logs.
- [ ] I can reproduce this on the latest `main` branch.
