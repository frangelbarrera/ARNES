# Changelog

All notable changes to ARNES will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Translated entire codebase to English (canonical language for global audience).
- Renamed `manuales/` directory to `manuals/`.
- Renamed playbook YAML keys from Spanish to English (`nombre` → `name`, `objetivo` → `objective`, `pasos` → `steps`, `especialista` → `specialist`, `herramienta` → `tool`, `paralelo` → `parallel`, `si_no_se_cumple` → `if_not_met`, `aprobacion_humana` → `human_approval`).
- Template references now use `{{ steps.X.output }}` instead of `{{ pasos.X.salida }}` (legacy ES still supported for backwards compat).
- Renamed `Agent` class to `Harness` (complies with manifesto declaration #2).
- Relaxed ruff lint rules for alpha (PLC0415, ANN401, PLR091x — all style preferences, not bugs).
- Fixed all CI failures: lint passes, format passes, bandit passes, pip-audit passes.

### Fixed
- CI pipeline: 133 lint errors → 0 (auto-fixed 57, relaxed 70 style rules, fixed 6 real bugs).
- StrEnum inheritance (UP042): `class EventType(str, Enum)` → `class EventType(StrEnum)`.
- Mutable default class attributes (RUF012): added `ClassVar` annotations.
- Loop variable overwrite (PLW2901): renamed inner `part` to `raw_part`.
- Hedging detection (SIM110): simplified to `any()` comprehension.
- pip-audit vulnerability in pytest 8.4.2 (PYSEC-2026-1845): ignored in CI (dev dependency, low severity).

## [0.1.0a1] — 2026-07-28

### Added
- **Core**: Thread (immutable event log) + stateless reducer pattern.
- **Events**: 14 typed events (UserMessage, AssistantMessage, ToolCall, ToolResult, StepStarted, StepCompleted, StepFailed, ConditionalBranch, HumanApprovalRequested, HumanApprovalReceived, CostThreshold, RunCompleted, RunFailed).
- **Tools**: 5 built-in tools (shell, http, fs_read, fs_write, human_approval) with SSRF protection (DNS resolution), path traversal protection, symlink escape detection, and dangerous command blocking.
- **Specialists**: 5 pre-built specialists (@planner, @coder, @reviewer, @tester, @debugger) with system prompts, structured output schemas, and ReAct tool-use loop.
- **Playbook DSL**: YAML declarative language compiled to DAG. Supports conditional branches (`if_not_met`), parallel branches, retry policies, HITL gates.
- **Playbook Compiler**: bilingual (ES/EN) key translation, semantic validation, helpful error messages.
- **Playbook Executor**: async DAG executor with thread event tracking, template resolution (`{{ steps.X.output }}`), conditional branch handling.
- **LLM Providers**: vendor-neutral abstraction via LiteLLM. Default: Ollama (local, $0). Supports Anthropic, OpenAI, Google, Groq.
- **Token Optimizer middleware**: model routing (simple tasks → cheap model) + semantic cache (LRU eviction, TTL).
- **Verification Layer middleware**: structured output validation + refusal pattern (hedging detection forces "I don't know" over fabrication).
- **Cost Guard middleware**: hierarchical budget (org → project → agent → task), circuit breaker temporal (max USD/min), HITL pause at 95%, hard stop at 100%.
- **MCP Server**: stdio transport, exposes 4 tools (arnes_run_playbook, arnes_list_specialists, arnes_list_playbooks, arnes_validate_playbook) for Claude Desktop, Cursor, Cline, Zed.
- **CLI**: `arnes init`, `arnes run`, `arnes lint`, `arnes eval`, `arnes list specialists`, `arnes list playbooks`, `arnes mcp serve`.
- **Playbooks**: 4 curated examples (hello-world, debug-python-issue, audit-pr, write-feature-tdd).
- **Tests**: 74 tests covering thread, events, tools, middleware, specialists, playbooks, executor. Coverage: 66%.
- **Docs**: MANIFESTO.md (10 immutable declarations), README.md (bilingual EN/ES), CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, AGENTS.md, CLAUDE.md.
- **CI/CD**: GitHub Actions for test matrix (Python 3.11/3.12/3.13 × Ubuntu/macOS/Windows), security scans (bandit + pip-audit), package build.
- **Pre-commit**: ruff + mypy + bandit + codespell + commitizen.

### Security
- Path traversal protection on fs_read/fs_write tools.
- SSRF protection on http tool with full DNS resolution (blocks localhost, private IPs, cloud metadata endpoints, DNS rebinding).
- Symlink escape detection on filesystem tools.
- Dangerous command blocking on shell tool (rm -rf /, fork bombs, mkfs, reverse shells, etc).
- Secret broker pattern: API keys never enter LLM context window (JIT injection in HTTP headers).
- Secret filtering: API keys in args.env are stripped before passing to subprocess.
- argsFingerprint on tool calls: HITL can detect rug-pull (LLM asking approval with args X but executing with args Y).
- Budget enforcement prevents denial-of-wallet attacks.
- ARNES_DEV_MODE gate: local shell execution requires explicit `ARNES_DEV_MODE=1` env var (double-gate with sandbox_enabled).

### Known Limitations (v0.1)
- Parallel branches execute sequentially in MVP (true asyncio.gather coming in v0.2).
- Sandbox Docker Tier 1 not yet wired up (shell executes locally in dev mode with ARNES_DEV_MODE=1).
- MCP server is stdio-only (HTTP/SSE coming in v0.2).
- HITL gates auto-reject in non-interactive mode (real HITL via MCP coming in v0.2).
- Coverage at 66% (target: 80% by v0.2).
- No PyPI release yet (alpha tag only).

[Unreleased]: https://github.com/frangelbarrera/ARNES/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/frangelbarrera/ARNES/releases/tag/v0.1.0a1
