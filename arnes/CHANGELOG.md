# Changelog

All notable changes to ARNES will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added in Round 15
- **Streaming now participates in the ReAct tool-use loop** (`Specialist.stream()`): closes the R11→R14 top-AI-issue gap. Each streaming iteration emits an `AssistantMessageEvent`; if the provider streams `tool_calls`, the specialist executes the tools, appends assistant + tool messages, and starts another streaming iteration. Yields a final zero-usage sentinel on `max_iterations` exhaustion or `BudgetExceeded` so callers don't hang.
- **SSE (Server-Sent Events) endpoint stub on the MCP HTTP transport**: `GET /events` and `GET /sse` yield `event: <name>\ndata: <json>\n\n` frames via the new `arnes/mcp/sse.py` module. R15 stub emits a single `server_info` event up-front, then idles on `: ping` heartbeats (15 s interval). v0.2 will replace the heartbeat loop with a real subscription to `PlaybookExecutor.stream` so subscribers see step transitions in real time. The wire format is stable across that upgrade.
- **`arnes/cli/helpers.py` + `arnes/cli/scaffolding.py` + `arnes/mcp/sse.py`**: extracted from `arnes/cli/main.py` (774 → 293 lines) and `arnes/mcp/server.py` to keep both files under the AGENTS.md 500-line rule. `helpers.py` owns the async runners + the schema-valid mock LLM provider; `scaffolding.py` owns the `arnes init` template helpers; `sse.py` owns the SSE wire-format helpers + the async generator.
- **2 new vcrpy cassettes** under `tests/snapshot/cassettes/`: `test_coder_basic.yaml` (62 in + 48 out tokens, validates against `CoderOutput`) and `test_reviewer_basic.yaml` (58 in + 36 out tokens, validates against `ReviewerOutput`). The full snapshot test suite now covers 3 of 5 specialists.
- **MkDocs documentation site scaffold**: `mkdocs.yml` (MkDocs Material, dark/light palette, strict mode) + 7 stub docs pages under `docs/*.md` (`index.md`, `quickstart.md`, `architecture.md`, `specialists.md`, `playbooks.md`, `mcp-server.md`, `benchmarking.md`, `audits.md`). `mkdocs build --strict` passes cleanly.
- 22 new tests (376 → 398): 6 SSE wire-format/stream tests, 1 streaming-with-ReAct-loop test, 1 streaming-no-tool-calls regression test (renamed), 16 specialist-cassette tests (8 for `@coder`, 8 for `@reviewer`).

### Changed in Round 15
- `arnes/specialists/base.py`: `Specialist.stream()` rewritten to participate in the ReAct loop (was bypassing tool execution). Each iteration: stream → emit audit event → if `tool_calls`, execute + iterate. File grew from 706 → 815 lines (still over the 500-line rule — the streaming-with-tools path is genuinely one cohesive class).
- `arnes/mcp/server.py`: SSE wire-format helpers + the async generator extracted to `arnes/mcp/sse.py`. The HTTP transport now registers `GET /events` and `GET /sse` routes via `app.router.add_get(...)`. File shrunk from 668 → 590 lines.
- `arnes/cli/main.py`: 774 → 293 lines. All async helpers + the mock LLM provider + scaffolding moved to `helpers.py` / `scaffolding.py`.
- `arnes/llm/base.py`: `LLMProvider.stream_complete` contract documented to allow final chunks to carry non-empty `tool_calls` lists (vendors stream `delta.tool_calls` fragments that callers reassemble).
- `.gitignore`: added `site/` (MkDocs build output).

### Added in Round 13
- `arnes benchmark` CLI command now documented end-to-end in the README feature table and a dedicated "Benchmark" section. Targets +6.1 score gain to reach the 95/100 tier.
- `CITATION.cff`: Zenodo DOI placeholder (`10.5281/zenodo.ARNES`) added so the citation record is ready for the Zenodo deposit the moment the software is published.
- `tests/unit/test_builtin_tools.py`: new test module covering the previously-uncovered paths in `arnes/tools/builtin.py` (was 52% coverage) — ShellTool sandbox mode (mocked Docker), HttpTool with secret broker removed, FilesystemReadTool with various file sizes, FilesystemWriteTool append mode, HumanApprovalTool interactive mode, `_is_dangerous_command` full pattern matrix, `_validate_path` edge cases, and `_is_blocked_ip` IPv6 cases.
- `arnes/cli/main.py` `_stream_specialist`: rewritten to use `Harness.stream_with_audit()` + `Thread.to_markdown()` for consistency with the rest of the bitácora system (was a bespoke markdown format that diverged from `PlaybookRunResult.to_markdown()`).

### Changed in Round 13
- `arnes/playbooks/executor.py`: removed the SPLIT-R12 backwards-compat delegating wrappers (`_drain_middleware_events`, `_resolve_input`, `_resolve_template`, `_resolve_expr`, `_TEMPLATE_RE` class attr). Internal call sites now use the canonical functions from `arnes.playbooks.events` / `arnes.playbooks.template` directly. Executor file went from 1015 → ~720 lines (under the 800-line target).
- `arnes/playbooks/schema.py`: docstring example was already English (verified — no Spanish `nombre:` / `auditar-pr` payload remains). Documented as fixed to close the audit checklist item.
- `tests/stress/test_template_resolution.py`: updated to call the standalone `_resolve_template` from `arnes.playbooks.template` directly instead of the executor method (which is now removed).
- Old audit reports `docs/audits/JUDGE_*_R{1,2,3,4}.md` moved into `docs/audits/archive/` (38 files). The main `docs/audits/` folder now holds only R5+ audits + cross-cutting summaries (`AI_AUDIT.md`, `SECURITY_AUDIT.md`, `DX_AUDIT.md`, `ARCHITECTURE_AUDIT.md`, `COMPETITIVE_AUDIT.md`).

### Added in Round 12
- `arnes/benchmarks/` package: `BenchmarkRunner` with multi-seed runs (`seeds=N`), concurrent execution (`concurrent=N`), and p95 duration reporting per playbook. Pluggable `BenchmarkSuite` protocol (`BasicBenchmarkSuite` ships by default, scanning `manuals/*.yaml`).
- `arnes benchmark` CLI command: runs the basic suite against a deterministic seeded mock LLM (no network, $0 spend) and reports per-playbook success rate / avg + p95 duration / avg tokens / avg cost. Saves JSON results to `benchmark-results.json` (or `--output`).
- `tests/test_benchmark.py`: full coverage for `BenchmarkRunner`, `BasicBenchmarkSuite`, and `BenchmarkResults` (per-playbook aggregation, p95 math, JSON round-trip).
- `tests/snapshot/` package: vcrpy-style cassettes for LLM provider tests. First cassette: `test_planner_basic.yaml` (LiteLLM provider fixture). `tests/snapshot/test_litellm_cassette.py` replays the cassette through `LiteLLMProvider` and asserts the structured-output path is exercised without hitting the network.
- `arnes/playbooks/` split for the >500-line rule: extracted `result.py` (`PlaybookRunResult`), `sandbox.py` (`_is_docker_available` + `DEFAULT_SANDBOX_CONTAINER`), `events.py` (`_drain_middleware_events` + `_filter_internal_keys`), and `template.py` (`_TEMPLATE_RE` + `_resolve_input` / `_resolve_template` / `_resolve_expr`). Each extracted module is independently testable and stays under 200 lines.

### Changed in Round 12
- `arnes/specialists/base.py`: extracted the duplicated `_emit_assistant_message` pattern into a single private helper (`Specialist._emit_assistant_message`) shared by `run()` and `stream()`. The helper builds the `AssistantMessageEvent` with `ctx.thread_id` / `ctx.step_id` / `self.config.name` and appends to the wrapped provider's `_events` sink; the bitácora-draining pattern in the executor (`_drain_middleware_events`) is unchanged.

### Added in Round 11
- `CITATION.cff`: full Citation File Format metadata for academic citations (title, authors, ORCID, version, license, repository, keywords, abstract, preferred-citation block). Closes the "scientific judge NO-GO" gap.
- New logo at `docs/logo.svg` — centered, 120px, embedded at the top of `README.md` and the social card.
- Audit reports consolidated under `docs/audits/` (root cleanup — no judge/marketing markdown files left at the repo root).

### Changed in Round 11
- Dead code cleanup: 10 unused items removed across `arnes/` (stale imports, unreachable branches, deprecated helpers).
- DRY: extracted `build_middleware_stack()` helper to centralize the TokenOptimizer → VerificationLayer → CostGuard wrapping order (was duplicated in `Harness.run()`, `Harness.stream()`, and `Specialist._wrap_provider()`).

### Added in Round 10
- `arnes stream` CLI command now saves a bitácora markdown file alongside the streamed output, closing the same audit-trail gap that `Harness.stream_with_audit()` fixed at the SDK layer in R9.
- CLI docstring on `arnes/cli/main.py` updated to enumerate every subcommand (`init`, `run`, `run --stream`, `stream`, `lint`, `eval`, `list specialists`, `list playbooks`, `mcp serve`).
- README CLI feature list refreshed to match the actual `arnes` CLI surface (was stale — missing `stream` and `run --stream`).

### Changed in Round 10
- CLI docstring updated with all commands (was missing `stream` and `run --stream`).
- README CLI feature list updated to match the actual CLI surface.

### Fixed in Round 10
- Double-call bug in `arnes stream`: the CLI invoked the specialist's `stream()` twice on the same input (once for the live token printout and once for the bitácora capture), doubling cost and interleaving two streams in the audit log. Fixed by capturing the streamed chunks into a single async iterator and replaying them for both the terminal and the bitácora writer.

### Added in Round 9
- `Specialist.stream()` method: token-by-token streaming at the specialist layer. Mirrors `Harness.stream()` but operates directly on a `Specialist` instance, yielding `LLMResponse` chunks from `provider.stream_complete()`. After the stream completes, emits a single `AssistantMessageEvent` to the wrapped provider's `_events` sink (same audit pattern as `run()`).
- `PlaybookExecutor.stream()` method: step-level streaming at the playbook layer. Yields `StepCompletedEvent` / `StepFailedEvent` as each step finishes (without waiting for the whole playbook), then `RunCompletedEvent` / `RunFailedEvent`, then a final `PlaybookRunResult` with the full thread + aggregate accounting. Documented as best-effort: parallel branches stream in completion order, not definition order.
- `Harness.stream_with_audit()` method: returns `(chunks, thread)` tuple. The chunks are the token-by-token `AsyncIterator[LLMResponse]`; the thread is mutated in place as the stream is consumed, ending with a single `AssistantMessageEvent` carrying the full accumulated content + final usage. Closes the audit-trail gap: streaming no longer bypasses the bitácora.
- `Harness.stream()` now emits an `AssistantMessageEvent` to the wrapped provider's `_events` sink after the stream completes (one event per call, not per chunk — per-chunk events would balloon the audit log without forensic value).
- `arnes run --stream` CLI flag: streams step-level events as they complete (best-effort: parallel branches stream in completion order). The final `PlaybookRunResult` is captured from the last yield for stats + bitácora persistence.
- README: added `arnes run --stream` example to the quick-start section.
- 16 new tests covering `Specialist.stream()`, `PlaybookExecutor.stream()`, `Harness.stream_with_audit()`, and the streaming bitácora emission (235 → 251 tests).

### Added in Round 8
- `arnes stream` CLI command: stream a specialist's response token-by-token from the command line. Supports `--mock` and `--model` flags.
- `tests/unit/test_harness_stream.py`: 5 dedicated tests for `Harness.stream()` (yields chunks, final chunk has usage, unknown specialist yields nothing, name normalization, middleware passthrough).
- `examples/README.md`: entry for `05_streaming.py`.

### Changed in Round 8
- `arnes/cli/main.py`: explicit `provider: LLMProvider` annotation on `_SchemaValidMockLLMProvider` assignment (mypy --strict clean).

### Added in Round 7
- `Harness.stream()` method: async generator that wraps the provider with the full middleware stack (TokenOptimizer → VerificationLayer → CostGuard) and yields `LLMResponse` chunks from `stream_complete()`. Same `(specialist, input_data)` signature as `run()`.
- `examples/05_streaming.py`: demonstrates token-by-token streaming using `Harness.stream()` with a `StreamingMockProvider` that yields 10-char chunks + a final usage chunk.
- README: "LLM streaming is implemented for all providers" (was stale "not yet implemented").

### Changed in Round 7
- `arnes/cli/main.py` mock docstring: updated to reflect that real streaming exists in `OllamaProvider` and `LiteLLMProvider` (was stale "Streaming coming in v0.2").

### Added in Round 6
- REAL token-by-token streaming in `OllamaProvider.stream_complete()`: reads NDJSON from `/api/chat` with `stream: true` via `httpx.AsyncClient.stream`, yields per-token chunks, yields a final usage chunk on `done: true`, handles malformed lines, wraps `httpx.ConnectError` in `RuntimeError` with install instructions. 8 dedicated tests.
- REAL token-by-token streaming in `LiteLLMProvider.stream_complete()`: iterates the `CustomStreamWrapper` from `litellm.acompletion(stream=True)`, extracts `delta.content` via a helper that handles both pydantic `Delta` instances and plain dicts, captures usage on chunks that carry it, yields a final usage chunk. 5 dedicated tests.
- `CostGuard.stream_complete()`: pre-flight abort check + circuit-breaker check before stream starts, post-stream `spent_usd` update using the final chunk's `cost_usd`. 7 dedicated tests including pre-flight abort and post-abort raise.
- `TokenOptimizer.stream_complete()`: thin passthrough (no cache population for streaming in v0.1).
- 23 new streaming tests (207 → 230 tests). Coverage: 72.95% → 73.95%.

### Changed in Round 6
- `TokenOptimizer._cache`: `asyncio.Lock` for cache reads/writes (was unprotected — concurrent cache mutations could race). Lock is correctly scoped: provider call runs OUTSIDE the lock so slow LLM calls don't serialize concurrent requests for different keys.
- `AGENTS.md`: "Thread: append-only event log (mutates in place for O(1) performance)" (was stale "immutable" — R5 false-fix-claim now actually applied).

### Added in Round 5
- `_filter_internal_keys()` helper: filters internal sentinel keys (`__skip_steps_until`, `__resolved_str__`, `__input__`, `_approved_fingerprints`) from `PlaybookRunResult.outputs` before returning to user. Applied at both the success path and the `BudgetExceeded` path.

### Changed in Round 5
- `Harness.run()`: separated `BudgetExceeded` from generic `Exception` in error handling. `BudgetExceeded` returns `{"success": False, "budget_exceeded": True, ...}`; generic `Exception` returns `{"success": False, "error_type": type(e).__name__, ...}`. Closes the R4 Dev top issue where budget errors and unexpected errors were indistinguishable.

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
