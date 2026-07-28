# CLAUDE.md — Specific guidance for Claude Code / Claude Desktop contributing to ARNES

This file extends `AGENTS.md` with Claude-specific notes.

## When you're editing ARNES code

- Always read `MANIFESTO.md` first. Every PR must respect the 10 declarations.
- Use `arnes` idioms, not `langchain` idioms. No `Runnable`, `Chain`, `Agent` classes.
- Prefer functions over classes. State lives in `Thread`, not in objects.
- Use `pydantic` for all data that crosses a boundary. Never `dataclass`.
- Use `async def` for all I/O. The only sync code is at the CLI boundary.

## When you're writing a playbook

- YAML, not Python. The whole point is declarative.
- Use Spanish keys (`nombre`, `objetivo`, `pasos`, `especialista`) — they're canonical.
- Quote specialist names: `"@planner"`, not `@planner` (YAML quirk).
- Test with `arnes lint` and `arnes ejecutar --mock` before committing.

## When you're adding a specialist

- One responsibility per specialist. If you need 2 things, make 2 specialists.
- The `system_prompt` is the specialist's personality. Version it. Diff it.
- The `output_schema` is the contract. Never return data that doesn't match.
- Default model is `ollama/llama3.2`. Don't change unless you have a strong reason.

## When you're fixing a bug

- Write a test that reproduces the bug first.
- Fix the bug.
- Verify the test passes.
- Don't refactor unrelated code in the same PR.

## When you're reviewing a PR

- Check the manifesto compliance first.
- Check that no vendor-only features were introduced.
- Check that no API keys are logged or stored.
- Check that tests exist and pass.
- Check that the README/docs are updated if needed.

## Files to never touch without discussion

- `MANIFESTO.md` — immutable. If you want to change it, open a Discussion.
- `LICENSE` — Apache 2.0. Don't change.
- `SECURITY.md` — only update to add new security contacts or policies.
- `pyproject.toml` `[project]` section — only bump version, don't change metadata without release.

## Quick reference

```bash
# Setup
uv sync --all-extras --dev

# Test
uv run pytest

# Lint
uv run ruff check arnes/ tests/
uv run ruff format arnes/ tests/

# Type check
uv run mypy arnes/

# Run a playbook
uv run arnes lint manuales/hola-mundo.md.yaml
uv run arnes ejecutar manuales/hola-mundo.md.yaml --mock

# List specialists
uv run arnes list specialists
```
