# AGENTS.md — System prompt for AI coding agents contributing to ARNES

You are contributing to **ARNES**, an open-source agent harness for Python.

## Project context

ARNES is NOT a framework. It's an **arnés** — a harness that lets developers
orchestrate AI agents without ceding control of their prompts, context, model
choice, or budget. Read `MANIFESTO.md` for the full philosophy.

## Architecture in 30 seconds

- **Thread**: immutable, append-only event log. State = reduce(events).
- **Specialist**: pre-built role-based agent (planner, coder, reviewer, tester, debugger).
- **Playbook**: YAML manual compiled to a DAG of steps. Each step invokes a specialist or tool.
- **Executor**: walks the DAG, applies middleware (cost guard + verification + token optimizer).
- **MCP server**: exposes playbooks as tools for Claude Desktop, Cursor, Cline, Zed.

## Non-negotiable rules (from MANIFESTO.md)

1. **No vendor-only features as first-class APIs.** If it only exists in OpenAI or
   only in Anthropic, it's a leak, not a feature.
2. **No classes named `Runnable`, `Chain`, `Workflow`, or `Agent`.** Composition = functions.
3. **Token counter is on by default.** If you don't know what you spent, you didn't ship.
4. **No hosted version. Ever.** If you add code that requires ARNES Cloud, you're breaking the manifesto.
5. **No hidden prompts.** Every prompt sent to an LLM is a file on disk.
6. **No magic.** If a line does something you can't explain, it's a bug.
7. **No API keys in code.** Read from env. Never log. Never store.

## Coding standards

- **Python 3.11+** — use modern syntax (`match` statements, `type X = ...`, PEP 695 generics).
- **Pydantic v2** for all schemas. Never use `dataclass` for data that crosses a boundary.
- **async first** — all I/O is async. Sync wrappers only at the CLI boundary.
- **Type hints everywhere** — `mypy --strict` must pass.
- **Docstrings on all public functions** — Google style.
- **Tests required** — 70% coverage minimum. New code = new tests.
- **One responsibility per module** — if a file is >500 lines, it's doing too much.

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: add @security-auditor specialist`
- `fix: handle empty playbook steps in executor`
- `docs: update README with MCP install instructions`
- `refactor: extract template resolution to separate module`
- `test: add snapshot tests for @coder`
- `perf: cache specialist configs at registry init`
- `chore: bump pydantic to 2.11.2`

## PR checklist

- [ ] Tests pass (`uv run pytest`)
- [ ] Lint passes (`uv run ruff check arnes/`)
- [ ] Types pass (`uv run mypy arnes/`)
- [ ] Coverage ≥ 70%
- [ ] No new dependencies without justification
- [ ] No vendor-only features
- [ ] Docs updated if API changed
- [ ] CHANGELOG.md entry added under `[Unreleased]`

## What NOT to do

- Don't add a `langchain` dependency. We're the alternative to LangChain.
- Don't add an `Agent` class. Use `Specialist` and functions.
- Don't add a `Chain` class. Use playbooks.
- Don't import `openai` directly. Use `litellm` via `arnes.llm`.
- Don't log API keys. Don't even log `os.environ["ANTHROPIC_API_KEY"]`.
- Don't add features that are only useful for one vendor's model.
- Don't break the manifesto. If you're unsure, ask in Discussions first.

## How to add a new specialist

1. Create `arnes/specialists/mi_specialist.py`
2. Subclass `Specialist`, set `config` class var
3. Register in `arnes/specialists/__init__.py`
4. Add tests in `tests/unit/test_mi_specialist.py`
5. Add example in `examples/`
6. Update docs in `docs/specialists.md`

## How to add a new playbook

1. Create `manuales/mi-playbook.md.yaml`
2. Test with `arnes lint manuales/mi-playbook.md.yaml`
3. Test with `arnes ejecutar manuales/mi-playbook.md.yaml --mock`
4. Add to `docs/playbook-library.md`

## When in doubt

Read `MANIFESTO.md`. If your change violates any of the 10 declarations, don't
make the change. Ask in GitHub Discussions first.
