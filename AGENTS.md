# AGENTS.md — System prompt for AI coding agents contributing to ARNES

You are contributing to **ARNES**, an open-source agent harness for Python.

## Project Context

ARNES is NOT a framework. It is a **harness** — the control layer that lets
developers orchestrate AI agents without surrendering their prompts, context,
model choice, or budget. Read `MANIFESTO.md` for the full philosophy.

## Architecture in 30 seconds

- **Thread**: append-only event log (mutates in place for O(1) performance). State = reduce(events).
- **Specialist**: pre-built role-based agent (12 total: planner, coder, reviewer, tester, debugger, researcher, security-auditor, devops-engineer, data-scientist, product-manager, market-analyst, cost-estimator).
- **Playbook Library**: 13 domain templates (mobile_app, osint, financial_analysis, ...) + a TaskRouter that classifies natural-language requests into a domain without an LLM call.
- **Playbook**: YAML manual compiled to a DAG of steps. Each step invokes a specialist or tool. Steps can declare a `review:` config for actor-critic iterative refinement.
- **Executor**: walks the DAG, applies middleware (cost guard + verification + token optimizer), runs review loops when configured.
- **MCP server**: exposes playbooks as tools for Claude Desktop, Cursor, Cline, Zed.

## Non-negotiable rules (from MANIFESTO.md)

1. **No vendor-only features as first-class APIs.** If it only exists in OpenAI or
   only in Anthropic, it is a leak, not a feature.
2. **No classes named `Runnable`, `Chain`, `Workflow`, or `Agent`.** Composition = functions.
3. **Token counter is on by default.** If you don't know what you spent, you didn't ship.
4. **No hosted version. Ever.** If you add code that requires ARNES Cloud, you're breaking the manifesto.
5. **No hidden prompts.** Every prompt sent to an LLM is a file on disk.
6. **No magic.** If a line does something you can't explain, it's a bug.
7. **No API keys in code.** Read from env. Never log. Never store.

## Coding Standards

- **Python 3.11+** — use modern syntax (`match` statements, `type X = ...`, PEP 695 generics).
- **Pydantic v2** for all schemas. Never use `dataclass` for data that crosses a boundary.
- **async first** — all I/O is async. Sync wrappers only at the CLI boundary.
- **Type hints everywhere** — `mypy --strict` must pass.
- **Docstrings on all public functions** — Google style.
- **Tests required** — 65% coverage minimum. New code = new tests.
- **One responsibility per module** — if a file is >500 lines, it's doing too much.

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: add @security-auditor specialist`
- `fix: handle empty playbook steps in executor`
- `docs: update README with MCP install instructions`
- `refactor: extract template resolution to separate module`
- `test: add snapshot tests for @coder`
- `perf: cache specialist configs at registry init`
- `chore: bump pydantic to 2.11.2`

## PR Checklist

- [ ] Tests pass (`uv run pytest`)
- [ ] Lint passes (`uv run ruff check arnes/`)
- [ ] Types pass (`uv run mypy arnes/`)
- [ ] Coverage ≥ 65%
- [ ] No new dependencies without justification
- [ ] No vendor-only features
- [ ] Docs updated if API changed
- [ ] CHANGELOG.md entry added under `[Unreleased]`

## What NOT to Do

- Don't add a `langchain` dependency. We are the alternative to LangChain.
- Don't add an `Agent` class. Use `Specialist` and functions. (The `Harness` class is the high-level wrapper, NOT named `Agent`.)
- Don't add a `Chain` class. Use playbooks.
- Don't import `openai` directly. Use `litellm` via `arnes.llm`.
- Don't log API keys. Don't even log `os.environ["ANTHROPIC_API_KEY"]`.
- Don't add features that are only useful for one vendor's model.
- Don't break the manifesto. If you're unsure, ask in Discussions first.

## How to Add a New Specialist

1. Create `arnes/specialists/my_specialist.py`
2. Subclass `Specialist`, set `config` class var
3. Register in `arnes/specialists/__init__.py`
4. Add tests in `tests/unit/test_my_specialist.py`
5. Add example in `examples/`
6. Document inline in the specialist's module docstring. See also `docs/specialists.md` for the human-readable catalogue.

## How to Add a New Playbook

1. Create `manuals/my-playbook.yaml`
2. Test with `arnes lint manuals/my-playbook.yaml`
3. Test with `arnes run manuals/my-playbook.yaml --mock`
4. Use existing `manuals/*.yaml` files as the spec (see `docs/playbooks.md` for the format and `arnes/playbooks/library/` for domain templates)

## When in Doubt

Read `MANIFESTO.md`. If your change violates any of the 10 declarations, don't
make the change. Ask in GitHub Discussions first.
