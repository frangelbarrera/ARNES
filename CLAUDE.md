# CLAUDE.md — Specific guidance for Claude Code / Claude Desktop contributing to Agentic Harness

This file extends `AGENTS.md` with Claude-specific notes.

## When You're Editing Agentic Harness Code

- Always read `MANIFESTO.md` first. Every PR must respect the 10 declarations.
- Use `arnes` idioms, not `langchain` idioms. No `Runnable`, `Chain`, `Agent` classes.
- Prefer functions over classes. State lives in `Thread`, not in objects.
- Use `pydantic` for all data that crosses a boundary. Never `dataclass`.
- Use `async def` for all I/O. The only sync code is at the CLI boundary.

## When You're Writing a Playbook

- YAML, not Python. The whole point is declarative.
- Use English keys (`name`, `objective`, `steps`, `specialist`) — they are canonical.
- Quote specialist names: `"@planner"`, not `@planner` (YAML quirk).
- Test with `arnes lint` and `arnes run --mock` before committing.

## When You're Adding a Specialist

- One responsibility per specialist. If you need 2 things, make 2 specialists.
- The `system_prompt` is the specialist's personality. Version it. Diff it.
- The `output_schema` is the contract. Never return data that doesn't match.
- Default model is `ollama/llama3.2`. Don't change unless you have a strong reason.

## When You're Fixing a Bug

- Write a test that reproduces the bug first.
- Fix the bug.
- Verify the test passes.
- Don't refactor unrelated code in the same PR.

## When You're Reviewing a PR

- Check manifesto compliance first.
- Check that no vendor-only features were introduced.
- Check that no API keys are logged or stored.
- Check that tests exist and pass.
- Check that the README/docs are updated if needed.

## Files to Never Touch Without Discussion

- `MANIFESTO.md` — immutable. If you want to change it, open a Discussion.
- `LICENSE` — Apache 2.0. Don't change.
- `SECURITY.md` — only update to add new security contacts or policies.
- `pyproject.toml` `[project]` section — only bump version, don't change metadata without release.

## Quick Reference

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
uv run arnes lint manuals/hello-world.yaml
uv run arnes run manuals/hello-world.yaml --mock

# List specialists
uv run arnes list specialists
```
