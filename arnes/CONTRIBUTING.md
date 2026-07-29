# Contributing to ARNES

Thank you for considering contributing to ARNES! This document guides you through the process.

## Code of Conduct

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). TL;DR: be respectful, inclusive, and professional. ARNES was born in Latam and we especially welcome Spanish-speaking contributors.

## Development Setup

```bash
# 1. Fork + clone
git clone https://github.com/YOUR-USERNAME/ARNES.git
cd ARNES

# 2. Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install dependencies
uv sync --all-extras --dev

# 4. Install pre-commit hooks
uv run pre-commit install

# 5. Verify everything works
uv run pytest
```

## Project Structure

```
arnes/
├── arnes/
│   ├── agent/           # Harness class (high-level wrapper)
│   ├── thread/          # Thread + Event[] stateless reducer
│   ├── tools/           # Tool registry + BaseTool + 5 built-in tools
│   ├── events/          # Event types (Pydantic)
│   ├── llm/             # LLM provider abstraction (Ollama, LiteLLM, Mock)
│   ├── middleware/      # Token Optimizer, Verification, Cost Guard
│   ├── mcp/             # MCP server (stdio + HTTP)
│   ├── specialists/     # 5+ pre-built specialists
│   ├── playbooks/       # Playbook DSL + compiler + executor
│   └── cli/             # arnes CLI
├── tests/
├── manuals/             # Example playbooks
├── docs/
└── pyproject.toml
```

## Conventional Commits

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: ...` — new feature
- `fix: ...` — bug fix
- `docs: ...` — documentation only
- `style: ...` — formatting, no code changes
- `refactor: ...` — refactor without behavior changes
- `perf: ...` — performance improvement
- `test: ...` — adds tests
- `chore: ...` — build, deps, etc.

Example: `feat(specialists): add @security-auditor with SAST integration`

## Types of Contributions Welcome

### 🥇 High Priority
- **New specialists** — open an issue first to discuss the role
- **New playbooks** — curated, non-trivial
- **Bug fixes** with test that reproduces it
- **Performance improvements** with before/after benchmark

### 🥈 Medium Priority
- **Translations** — README, docs, quickstart to other languages
- **DX improvements** — better error messages, better CLI UX
- **More tests** — look for `# pragma: no cover` and cover those paths

### 🥉 Low Priority (but welcome)
- **Typo fixes**
- **Doc improvements**
- **Cosmetic refactors**

## Pull Request Process

1. **Open an issue first** for large features (beyond "good first issue" scope)
2. **Fork + branch**: `feat/my-feature` or `fix/issue-123`
3. **Tests**: all PRs must maintain >65% coverage
4. **Docs**: update README/docs if your feature requires it
5. **Changelog**: add entry in `CHANGELOG.md` under `[Unreleased]`
6. **CLA**: on first PR, sign the CLA (automatic via cla-assistant)

## Testing

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit

# With coverage report
uv run pytest --cov=arnes --cov-report=html
open htmlcov/index.html

# Specific tests
uv run pytest tests/unit/test_thread.py -v

# Slow tests (that call real LLMs)
uv run pytest -m slow
```

### Snapshot Tests with VCRpy

ARNES uses [vcrpy](https://github.com/kevin1024/vcrpy) to record LLM responses
and replay them in tests. This enables reproducible tests without spending tokens.

```python
@pytest.mark.snapshot
def test_specialist_responds(vcr):
    with vcr.use_cassette("tests/snapshot/cassettes/specialist_basic.yaml"):
        result = my_specialist.run("Hello")
        assert result.confidence > 0.7
```

To regenerate cassettes (when you change a prompt), delete the file and re-run
the test with `--record-mode=new`.

## Linting and Type Checking

```bash
# Ruff (lint + format)
uv run ruff check arnes/
uv run ruff format arnes/

# Mypy (types)
uv run mypy arnes/

# Bandit (security)
uv run bandit -r arnes/

# pip-audit (vulnerabilities)
uv run pip-audit
```

Pre-commit runs all of these automatically.

## Adding a New Specialist

1. Create `arnes/specialists/my_specialist.py`:

```python
from arnes.specialists.base import Specialist, SpecialistConfig

class MySpecialist(Specialist):
    """Description of what this specialist does."""

    config = SpecialistConfig(
        name="@my-specialist",
        description="Does X",
        system_prompt="You are an expert in X...",
        tools=["shell", "fs_read"],
        output_schema=MyOutput,  # pydantic
    )
```

2. Register it in `arnes/specialists/__init__.py`
3. Add test in `tests/unit/test_my_specialist.py`
4. Add example in `examples/use_my_specialist.py`
5. Document in `docs/specialists.md`

## Adding a New Playbook

1. Create `manuals/my-playbook.yaml` (follow the spec in `docs/playbook-dsl.md`)
2. Add test in `tests/integration/test_my_playbook.py`
3. Validate with `arnes lint manuals/my-playbook.yaml`

## Reporting Bugs

Open an [issue](https://github.com/frangelbarrera/ARNES/issues/new?template=bug_report.md) with:

1. **ARNES version**: `arnes --version`
2. **Python version**: `python --version`
3. **OS**: Linux/macOS/Windows + version
4. **Minimal reproduction**: minimal code that reproduces the bug
5. **Expected vs actual output**
6. **Logs**: paste the bitácora content if applicable

## Reporting Security Vulnerabilities

**DO NOT open a public issue for security vulnerabilities.**

Send an email to `security@arnes.dev` with:
- Description of the problem
- Steps to reproduce
- Estimated impact
- PoC if you have one

We respond within 72h. If the vulnerability is valid, we publish an advisory on
[GitHub Security Advisories](https://github.com/frangelbarrera/ARNES/security/advisories)
and give you credit (unless you prefer to remain anonymous).

## License

By contributing, you agree that your contributions are licensed under Apache 2.0.
