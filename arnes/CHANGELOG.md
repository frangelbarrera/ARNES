# Changelog

All notable changes to ARNES will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added in Round 4
- `LLMProvider.stream_complete()` abstract method for streaming responses (MockLLMProvider yields full response; Ollama and LiteLLM now support real token-by-token streaming).
- `Dockerfile.sandbox` + `scripts/build-sandbox.sh` for Tier 1 Docker sandbox image.
- CodeQL workflow (`.github/workflows/codeql.yml`) with `security-extended` query suite, weekly schedule.
- 20 new tests for `LiteLLMProvider.complete()` (0% → 96% coverage).
- GitHub issue templates (bug_report, feature_request), PR template, FUNDING.yml.
- `scripts/demo.sh` demo script with `--record` and `--save` flags.
- `docs/social-card.png` (1280×640) for social media previews.
- `docs/logo.svg` and `docs/social-card.svg`.
- Star History chart in README.
- 5 more EventType values now emitted: `MODEL_ROUTED`, `PARALLEL_BRANCH_STARTED`, `PARALLEL_BRANCH_COMPLETED`, `RUN_PAUSED`, `REFUSAL_TRIGGERED`.
- All 5 specialists now have `pydantic_model` for strong output validation.
- True `asyncio.gather` parallelism in `_execute_parallel` (was sequential for-loop).

### Changed in Round 4
- `Thread.append()`: O(N²) → O(1) by mutating in place (8.8x speedup at 1000 events). Documented as append-only, not immutable.
- Sandbox auto-detection: `PlaybookExecutor` now detects Docker via `shutil.which("docker")` and enables sandbox automatically.
- CostGuard 95% pause: now emits `HumanApprovalRequestedEvent` and `RUN_PAUSED` in interactive mode (was a no-op).
- All GitHub Actions pinned to commit SHAs (was floating @v4 tags) for supply chain security.
- `pip-audit` now blocking in CI (was `|| true`).
- `LiteLLMProvider.__init__` now accepts `**kwargs` (was TypeError when called with api_key).
- `LiteLLMProvider.complete()`: `getattr(response, "usage", None)` instead of `response.usage` (handles missing usage).
- Anti-hallucination: hedging detection now skipped in JSON mode (was false-positiving on honest hedging inside JSON values).
- Ollama provider: `tools` parameter now passed to API, `tool_calls` parsed from response (was hardcoded `[]`).
- MCP HTTP server: bearer token auth + rate limiting (100/min) + 1MB body cap + localhost-only enforcement.
- MCP path validation applied to all 3 endpoints (was only `_run_playbook`).
- HITL fingerprint: `setdefault` instead of `get` (was never persisted).
- SSRF: IP pinning with Host header + SNI to prevent DNS rebinding.
- Shell regex: added `python -c`, `eval`, `exec`, `find -delete`, `base64 -d` patterns.
- Dangling symlink: `is_symlink()` without `exists()` check (catches dangling symlinks).
- `_clean_json_response()` helper strips markdown fences before JSON parsing.
- `max_iterations` exceeded now returns clear error (was validating empty response).
- `peek_cost()` implemented on LiteLLMProvider for pre-flight budget check.
- README: removed stale claims, updated to match R4 reality, added real terminal output.
- `setup-and-push.sh` and `PUBLISHING_GUIDE.md`: fixed stale Spanish paths.

### Fixed in Round 4
- TokenOptimizer cache_key now includes `response_schema` (was cache poisoning across schemas).
- `aiohttp` added to `mcp` optional dependencies (was ImportError at runtime).
- Conditional branch executor: Spanish attrs (`branch.accion`, `branch.especialista`) → English (`action`, `specialist`).
- Parallel-step template resolution: outputs now wrapped in `{"output": ...}` structure.
- Middleware double-wrapping: replaced broken `hasattr(provider, "_provider")` with `_arnes_wrapped` marker.
- CostGuard 95% pause was a no-op (`_paused = True` then immediately `False`).
- HITL fingerprint was computed but never compared against approved set.
- MCP server path traversal in `_validate_playbook` and `_list_playbooks`.
- Windows CI: cross-platform PATH, SYSTEMROOT/COMSPEC, asyncio.to_thread for stdin.
- 133 ruff lint errors → 0. 50 mypy --strict errors → 0.

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
