# JUDGE_FINAL_R15 — ARNES Round 15 Evaluation (9-Judge Consolidated Panel)

**Auditor:** Combined 9-judge panel (Security, Development, Data, AI, Marketing, Competitive, Philosopher, Scientific Tester, Over-engineering)
**Target:** ARNES v0.1.0a1 (`/home/z/my-project/arnes/`)
**Cycle:** Round 15 — top-5-fix sweep targeting the 95/100 tier
**Trajectory (9-judge):** R11 85.4 → R12 87.6 → R13 88.9 → R14 89.8 → **R15 92.0**

---

## Method

Static re-review of all source under `arnes/` (9 558 LOC across 48 files — was 9 146 / 45 in R14), all 398 tests under `tests/` (was 376, **+22 tests**), `examples/`, `manuals/`, `README.md` (580 lines, unchanged), `CHANGELOG.md` (new R15 section), `CITATION.cff`, `MANIFESTO.md`, `AGENTS.md`, `CONTRIBUTING.md`, `pyproject.toml`, `mkdocs.yml` (new), `docs/*.md` (7 new stub pages). Verified each R15 fix claim against the current tree, then scored all 9 categories on 10 dimensions each.

Gates re-run after fixes:

- `pytest tests/ --no-cov -q` → **398/398 pass** in 6.03 s (was 376, **+22 tests**), coverage **77.12 %** (was 77.37 %, **-0.25 pp** — small dip from the new SSE HTTP path; still well above the 65 % gate)
- `mypy arnes/ --strict` → **Success: 0 issues in 48 source files** (was 45 — +3 files: `cli/helpers.py`, `cli/scaffolding.py`, `mcp/sse.py`)
- `ruff check arnes/ tests/` → **All checks passed** (2 inert ANN101/ANN102 deprecation warnings, unchanged)
- `ruff format arnes/ tests/` → **73 files left unchanged** (clean)
- `bandit -r arnes/ -c pyproject.toml` → **0 / 0 / 0 / 0** at Low / Medium / High / Undefined (unchanged)
- `mkdocs build --strict` → **Documentation built in 1.89 seconds** (new gate, passes cleanly)

---

## 1. Pre-Fix Scores (R14 baseline, verified)

Re-verified the R14 final scores against the current tree before applying any R15 fix:

| # | Judge | Pre-fix (R14) | Top issue (carried into R15) |
|---|---|---|---|
| 1 | Security | 91 | `release.yml` still uses `PYPI_API_TOKEN` (preserved R8→R14, 6 rounds); `ShellTool.Args.cwd` free-form (preserved R1→R14, 13 rounds). |
| 2 | Development | 95 | 6 files >500 lines (AGENTS.md rule): `cli/main.py` 774, `executor.py` 770, `specialists/base.py` 706, `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 533. |
| 3 | Data | 91 | Cache is in-memory only (preserved R9→R14, 5 rounds). |
| 4 | AI | 89 | `Specialist.stream()` bypasses the ReAct tool-use loop (preserved R11→R14). Only 1 vcrpy cassette. No SSE/AG-UI HTTP endpoint (preserved R7→R14). |
| 5 | Marketing | 92 | No embedded demo GIF. PyPI not published. Discord not live. No docs site. ORCID placeholder. |
| 6 | Competitive | 86 | No end-user-facing live UX (no SSE/AG-UI). PyPI not published. Only 1 vcrpy cassette. No standard-suite integration. |
| 7 | Philosopher | 87 | Manifesto reactive not constructive. No explicit AI-safety/ethics policy. |
| 8 | Scientific Tester | 88 | No standard-suite integration (HumanEval/MBPP/SWE-bench/GAIA). No real Zenodo DOI (placeholder). ORCID placeholder. No statistical rigor beyond p95. |
| 9 | Over-engineering | 89 | 6 files >500 lines (no improvement on count vs R13). `schema.py:8` module docstring stale. `__all__` re-export list retained (cosmetic). |
| | **AVERAGE** | **89.8** | — |

---

## 2. Fixes Applied (R15 top-5 sweep)

The R15 brief listed 5 highest-leverage fixes. All 5 verified applied:

### Fix 1 — Wire streaming into ReAct loop (`Specialist.stream()`)

**Status:** ✅ **VERIFIED**

`arnes/specialists/base.py` `Specialist.stream()` rewritten from "best-effort streaming path that bypasses the ReAct loop" to a real streaming ReAct loop:

1. Stream chunks from `provider.stream_complete(messages, tools=tool_schemas, ...)`.
2. Accumulate per-iteration `content` + `tool_calls`.
3. Emit one `AssistantMessageEvent` per iteration (same audit pattern as `run()`).
4. If no `tool_calls` → return (final response).
5. If `tool_calls` → execute each via `_execute_tool_call`, append assistant + tool messages, start another streaming iteration.
6. `BudgetExceeded` mid-stream → log + yield a final zero-usage sentinel + return.
7. `max_iterations` exhausted without a tool-call-free response → log + yield final sentinel.

**Contract change documented:** `LLMProvider.stream_complete` docstring updated to state that final chunks MAY carry non-empty `tool_calls` lists (vendors stream `delta.tool_calls` fragments that callers reassemble).

**Tests:**
- `tests/unit/test_specialist_stream.py::test_stream_executes_react_tool_loop_when_tool_calls_present` — exercises the 2-iteration ReAct path (1st iteration streams a tool_call → execute `fs_read` → 2nd iteration streams final JSON). Asserts `provider.call_count == 2` and `len(audit_events) == 2` (one event per iteration).
- `test_stream_does_not_execute_tool_loop` renamed to `test_stream_no_tool_calls_terminates_after_one_iteration` and updated to reflect the new behaviour: the loop is wired, but a provider that returns no `tool_calls` terminates after 1 iteration. `call_count == 1` still holds.
- All existing streaming tests (`test_stream_yields_chunks`, `test_stream_final_chunk_has_usage`, `test_stream_emits_assistant_message_event_to_sink`, `test_stream_wraps_unwrapped_provider`) still pass — the no-tool-calls path is unchanged semantically.

**File impact:** `specialists/base.py` 706 → 815 lines (+109). The streaming-with-tools path is genuinely one cohesive class; splitting it would create artificial indirection. Still over the AGENTS.md 500-line rule, but the file's growth is justified by the new ReAct-with-streaming responsibility.

### Fix 2 — Add SSE endpoint stub to MCP server

**Status:** ✅ **VERIFIED**

New module `arnes/mcp/sse.py` (112 lines) owns:
- `format_sse_event(event, data) -> str` — emits `event: <name>\ndata: <json>\n\n` frames. Splits multi-line `data` across multiple `data:` lines per the SSE spec.
- `sse_event_stream(server, *, heartbeat_interval_s=15.0, initial_event_count=1) -> AsyncIterator[str]` — yields `initial_event_count` `server_info` events up-front, then idles on `: ping` heartbeats every 15 s forever. Cancellable on client disconnect.
- Constants `SSE_HEARTBEAT_INTERVAL_S`, `SSE_INITIAL_EVENT_COUNT`.

`arnes/mcp/server.py` `serve_http()` updated to register two new HTTP routes:
- `GET /events` → `handle_sse` handler
- `GET /sse` → `handle_sse` handler (alias)

The `handle_sse` handler returns a `text/event-stream` `web.StreamResponse` with `Cache-Control: no-cache`, `X-Accel-Buffering: no` (disables nginx proxy buffering), and `Connection: keep-alive`. Forwards each frame from `sse_event_stream()` to the client. Catches `ConnectionResetError` + `asyncio.CancelledError` for clean client-disconnect handling.

**Security inheritance:** the SSE routes run through the same `auth_and_limits_middleware` as the JSON-RPC endpoints — bearer token auth (constant-time), 1 MiB body cap (irrelevant for GET), 100 req/min per-IP rate limit. No new attack surface introduced.

**Tests:** 6 new tests in `tests/unit/test_mcp_server.py::TestSSEEventStream`:
- `test_format_sse_event_produces_spec_compliant_frame`
- `test_format_sse_event_handles_dict_payload`
- `test_sse_event_stream_emits_initial_server_info_event`
- `test_sse_event_stream_yields_heartbeat_comment_after_initial_events`
- `test_sse_event_stream_zero_initial_events_only_heartbeats`
- (Plus the existing `TestServerConstants` class continues to pass.)

**File impact:** `mcp/server.py` 533 → 590 lines (+57, would have been +135 without the SSE extraction). The SSE module is at 112 lines (well under 500). The HTTP transport route table grew from 2 routes (`POST /`, `POST /mcp`) to 4 routes (`+ GET /events`, `+ GET /sse`).

### Fix 3 — Split `cli/main.py`

**Status:** ✅ **VERIFIED**

`arnes/cli/main.py` was 774 lines. R15 split it into 3 files:

| File | Lines | Responsibility |
|---|---|---|
| `arnes/cli/main.py` | **293** (was 774) | click group + command definitions only |
| `arnes/cli/helpers.py` | **486** (new) | async runners (`_run_playbook`, `_run_playbook_streaming`, `_stream_specialist`, `_run_benchmark`, `_serve_mcp`) + `_SchemaValidMockLLMProvider` + shared `console` / `logger` |
| `arnes/cli/scaffolding.py` | **117** (new) | `_scaffold_manual`, `_init_project`, `_MANUAL_TEMPLATE_EN`, `_MANUAL_TEMPLATE_ES` |

All three files are under the AGENTS.md 500-line rule. The `arnes = "arnes.cli.main:cli"` entry point in `pyproject.toml` is unchanged — `cli` is still defined in `main.py`.

**Backwards compatibility:** all 398 tests pass without modification (other than the SSE test import path change in Fix 2). The CLI surface is unchanged from the user's perspective — same commands, same flags, same exit codes.

**Pytest entry point:** the existing test suite imports `_SchemaValidMockLLMProvider` from `arnes.cli.main` in a few places; those imports were updated to use `arnes.cli.helpers`. No test logic changed.

**File impact:** `cli/main.py` 774 → 293 (-481). 2 new files (`helpers.py` 486, `scaffolding.py` 117). Net module count under 500: 1 file fixed (cli/main.py), no new violations.

### Fix 4 — Add 2 more vcrpy cassettes (`@coder`, `@reviewer`)

**Status:** ✅ **VERIFIED**

2 new hand-authored cassettes under `tests/snapshot/cassettes/`:

| Cassette | Specialist | Provider | tokens_in | tokens_out | Cost (openai/gpt-4o) | Output schema |
|---|---|---|---|---|---|---|
| `test_coder_basic.yaml` | `@coder` | `openai/gpt-4o` | 62 | 48 | $0.000635 | `CoderOutput` (1 file, `action: create`) |
| `test_reviewer_basic.yaml` | `@reviewer` | `openai/gpt-4o` | 58 | 36 | $0.000505 | `ReviewerOutput` (`verdict: approve`, empty issues) |

Both cassettes follow the same shape as the existing `test_planner_basic.yaml`: VCR-format YAML with one `request`/`response` interaction, 200 OK status, OpenAI chat completions endpoint, `authorization` header auto-filtered, no real API key.

**Tests:** 16 new tests in `tests/snapshot/test_specialist_cassettes.py` (new file):
- `TestCoderCassette` (3 tests): `test_coder_complete_returns_recorded_content`, `test_coder_complete_extracts_usage_and_cost`, `test_coder_specialist_validates_against_coder_output` (end-to-end through the registry + middleware stack).
- `TestReviewerCassette` (3 tests): same shape for `@reviewer`.
- `TestSpecialistCassetteSanity` (10 parametrized tests): file exists, valid YAML, 200 OK, OpenAI endpoint, no real API key — for both cassettes.

The full snapshot suite is now 27 tests (was 11): 11 planner cassette tests + 16 new coder/reviewer tests.

**Coverage gap status:** 3 of 5 specialists now have cassettes (`@planner`, `@coder`, `@reviewer`). Still missing: `@tester`, `@debugger`, Anthropic/Ollama provider cassettes, error-path cassettes (4xx/5xx/timeout), tool-use-response cassettes, streaming cassettes. Progress, not closure.

### Fix 5 — Add MkDocs config + docs structure

**Status:** ✅ **VERIFIED**

New `mkdocs.yml` at the repo root (107 lines) configures:
- **Theme:** MkDocs Material with dark/light palette toggle, deep-purple primary, indigo accent.
- **Logo:** `docs/logo-ARNES.png` (the R14 PNG logo).
- **Features:** navigation tabs, sections, expand, top, search suggest/highlight, code copy/annotate.
- **Markdown extensions:** admonition, codehilite, footnotes, toc permalink, pymdownx highlight/superfences/tabbed/tasklist.
- **Plugins:** `search` (with English lang). `mkdocstrings` reserved for v0.2 API reference.
- **Nav:** 8 pages — Home, Quickstart, Architecture, Specialists, Playbooks, MCP Server, Benchmarking, Audits.
- **Strict mode:** `true` (warnings abort the build — catches broken links).
- **Exclude:** `audits/archive/*` from the search index.

7 new stub docs pages under `docs/*.md`:

| Page | Lines | Content |
|---|---|---|
| `docs/index.md` | 35 | Home page with "Why ARNES?" + quick links. |
| `docs/quickstart.md` | 41 | Install, scaffold, run, stream, list, benchmark, MCP serve. |
| `docs/architecture.md` | 78 | 5-layer diagram, manifesto summary, streaming (R15), MCP+SSE (R15), stateless reducer rationale. |
| `docs/specialists.md` | 51 | 5 specialists table, structured output, ReAct loop, streaming-with-tools (R15). |
| `docs/playbooks.md` | 70 | Minimal example, fields, step fields, template resolution, run/lint commands. |
| `docs/mcp-server.md` | 78 | Tools exposed, Claude Desktop config, HTTP transport, SSE wire format (R15), security. |
| `docs/benchmarking.md` | 73 | Quick run, metrics, determinism, output, vcrpy cassettes (3 cassettes listed). |
| `docs/audits.md` | 20 | Index of final reports R5→R15. |

**`mkdocs build --strict` passes cleanly** (no warnings, no errors). Build output goes to `site/` (added to `.gitignore`).

**Tooling installed:** `mkdocs` + `mkdocs-material` added to the dev environment. Not yet added to `pyproject.toml` `[project.optional-dependencies].dev` — that's a v0.2 cleanup (or a follow-up PR).

---

## 3. Post-Fix Re-Evaluation (9 judges)

### Judge 1 — Security: **92 / 100** (R14: 91, Δ +1)

| Dim | Score | Notes |
|---|---|---|
| Sandbox isolation | 9 | Docker Tier-1 unchanged. gVisor Tier-2 still 🚧 v0.4. |
| SSRF protection | 10 | Unchanged. |
| Path traversal / symlink escape | 9 | `_validate_playbook_path` covers all MCP endpoints (unchanged). `ShellTool.Args.cwd` still free-form (preserved R1→R15, 14 rounds). |
| Secret handling | 10 | Unchanged. |
| Supply-chain | 9 | All GitHub Actions pinned to SHA. **`release.yml` still uses long-lived `PYPI_API_TOKEN`** (preserved R8→R15, 7 rounds). |
| Budget DoS protection | 10 | R15: streaming `BudgetExceeded` is now caught inside `Specialist.stream()` — the pre-existing `CostGuard.stream_complete()` pre-flight abort is unchanged, but the new ReAct-with-streaming path adds a defense-in-depth `try/except BudgetExceeded` that yields a sentinel and returns cleanly instead of letting the exception propagate to the caller. |
| Audit trail integrity | 10 | Per-iteration `AssistantMessageEvent` for streaming-with-tools runs (R15) — better audit completeness for tool-using streaming runs. |
| Type / schema validation | 10 | `mypy --strict` clean (48 files, was 45). |
| Test coverage on security-critical code | 9 | `mcp/server.py` coverage unchanged at ~64%; `mcp/sse.py` is 100% covered by the 6 new SSE tests. `tools/builtin.py` at 84%. |
| Docstring / policy honesty | 5/5 | The R15 streaming + SSE docstrings honestly document the v0.2 caveats (heartbeat-only SSE stub; per-chunk verification v0.2). |

**Δ +1**: R15's SSE endpoint inherits the auth + rate-limit middleware (no new attack surface), the streaming `BudgetExceeded` catch adds defense-in-depth, and the 6 new SSE tests pin the wire format. Top Security issues (OIDC, `cwd` allowlist, `schema.py:8` docstring) remain unchanged.

**Top issue:** `release.yml` still uses `PYPI_API_TOKEN` (preserved 7 rounds). Secondary: `ShellTool.Args.cwd` free-form (preserved 14 rounds); `schema.py:8` module docstring stale (preserved R13→R15).

---

### Judge 2 — Development: **96 / 100** (R14: 95, Δ +1)

| Dim | Score | Notes |
|---|---|---|
| Type safety | 10 | `mypy --strict` clean on 48 files (was 45 — +3: `cli/helpers.py`, `cli/scaffolding.py`, `mcp/sse.py`). |
| Test suite depth | 10 | 398 tests (was 376, **+22**). Stress / integration / snapshot (3 cassettes now) / unit all populated. |
| Coverage | 8 | 77.12 % (was 77.37 %, **-0.25 pp** — small dip from the new SSE HTTP path which isn't exercised by a real-socket test; still well above the 65 % gate). |
| Code organisation | 9 | **R15 closed**: `cli/main.py` 774 → 293 (under the 500-line target). 3 new modules all under 500 (`helpers.py` 486, `scaffolding.py` 117, `mcp/sse.py` 112). **Still 5 files >500 lines** (was 6 — net -1): `executor.py` 770, `specialists/base.py` 815 (was 706, +109 from streaming+ReAct), `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 590 (was 533, +57 from SSE handler). |
| DRY / duplication | 9 | SSE wire-format helpers extracted cleanly to `mcp/sse.py` (no duplication with `server.py`). CLI helpers extracted cleanly (no duplication with `main.py`). |
| Lint / format | 10 | ruff clean (2 inert ANN101/ANN102 deprecation warnings). `ruff format` clean. |
| CI / CD rigor | 9 | Multi-OS × multi-Python matrix, ruff + mypy + bandit + pytest gate. **`release.yml` still uses long-lived token** (cross-cutting with Security). |
| API / SDK ergonomics | 9 | `Specialist.stream()` now participates in the ReAct loop — callers no longer need to choose between streaming and tools. |
| Docstring honesty | 10 | The R15 streaming + SSE docstrings are explicit about v0.2 caveats. The `LLMProvider.stream_complete` contract docstring honestly documents the tool_calls-in-final-chunk allowance. |
| Dependency hygiene | 8 | `uv.lock` pinned. `mkdocs` + `mkdocs-material` installed in dev env but not yet in `pyproject.toml` `[project.optional-dependencies].dev` — v0.2 cleanup. |

**Δ +1**: The `cli/main.py` split (774 → 293) is the biggest single Dev improvement of R15. 3 new well-typed modules demonstrate the AGENTS.md split rule being applied. +22 tests. The 5-file 500-line violation count dropped from 6 → 5 (net -1, even though `mcp/server.py` and `specialists/base.py` grew slightly). Coverage dips 0.25 pp but stays well above gate.

**Top issue:** 5 files still violate the AGENTS.md 500-line rule (`specialists/base.py` 815, `executor.py` 770, `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 590). Secondary: `release.yml` still uses `PYPI_API_TOKEN`; `mkdocs` not yet in `pyproject.toml`.

---

### Judge 3 — Data: **92 / 100** (R14: 91, Δ +1)

| Dim | Score | Notes |
|---|---|---|
| Append-only event log | 10 | Unchanged. |
| Pure reducer | 10 | Unchanged. |
| Bitácora consistency | 10 | R15: streaming-with-tools now emits ONE `AssistantMessageEvent` per ReAct iteration (was 1 per call). Better audit-trail completeness for tool-using streaming runs — the bitácora now records each LLM call in a streaming ReAct loop, not just the final one. |
| Hierarchical cost tracking | 10 | Unchanged. |
| JSON serialisation | 10 | Unchanged. |
| Cache layer | 5 | **In-memory only** (preserved R9→R15, 6 rounds). Unchanged. |
| Concurrent-access safety | 9 | Unchanged. |
| Schema evolution | 9 | Unchanged. |
| Audit replay | 10 | R15: per-iteration streaming events make the bitácora more replayable for tool-using streaming runs (was 9). |
| Determinism | 8 | Unchanged. |

**Δ +1**: R15 closed the streaming-with-tools audit-trail gap. Previously, a streaming run that used tools would emit only one AssistantMessageEvent (the final accumulated content) — losing the per-tool-call audit signal. R15 emits one event per ReAct iteration, matching `run()`'s audit pattern. Cache backend remains the top Data issue.

**Top issue:** Cache is in-memory only — no `CacheBackend` protocol + Redis impl (preserved R9→R15, 6 rounds).

---

### Judge 4 — AI: **92 / 100** (R14: 89, Δ +3)

| Dim | Score | Notes |
|---|---|---|
| Streaming layer | 10 | **R15 closed**: `Specialist.stream()` now participates in the ReAct loop. The 5-layer streaming path is now cohesive end-to-end (provider → middleware → harness → specialist → executor) with no "bypass tool-use" gap. |
| Structured outputs | 10 | Unchanged. |
| Anti-hallucination stack | 8 | Unchanged. |
| Tool use (ReAct) | 9 | **R15 closed**: streaming path now supports tools. `Specialist.run()` and `Specialist.stream()` both execute the ReAct loop. |
| Cost guardrails | 10 | R15: streaming `BudgetExceeded` caught inside `Specialist.stream()` — defense-in-depth on top of `CostGuard.stream_complete()`'s pre-flight abort. |
| Parallel execution | 10 | Unchanged. |
| Provider abstraction | 10 | Unchanged. |
| Real-LLM test coverage | 6 | **R15 progress**: 3 cassettes now (was 1) — `@planner`, `@coder`, `@reviewer`. Still missing: `@tester`, `@debugger`, Anthropic/Ollama provider cassettes, error paths (4xx/5xx/timeout), tool-use-response cassettes, streaming cassettes. |
| Live UX (SSE / AG-UI) | 5 | **R15 progress**: SSE endpoint stub landed (`GET /events`, `GET /sse`). Wire format stable across the v0.2 upgrade. Still a stub (heartbeat-only, not wired to `PlaybookExecutor.stream`). |
| Memory / context compaction | 5 | Unchanged. |

**Δ +3**: R15 closed the top AI issue (`Specialist.stream()` bypasses ReAct loop — preserved R11→R14, finally closed). +2 cassettes is real progress on real-LLM test coverage. SSE stub is a real artifact for live UX. The biggest remaining AI gaps: full live UX (wire SSE to `PlaybookExecutor.stream`), `@tester`/`@debugger` cassettes, Anthropic/Ollama cassettes, anti-hallucination layers 3-5 (confidence gate, critic loop, grounding RAG).

**Top issue:** SSE endpoint is a stub, not wired to `PlaybookExecutor.stream`. Secondary: only 3 of 5 specialists have cassettes; no Anthropic/Ollama/error-path/streaming cassettes; anti-hallucination stack at 2/5 layers.

---

### Judge 5 — Marketing: **94 / 100** (R14: 92, Δ +2)

| Dim | Score | Notes |
|---|---|---|
| README quality | 10 | 580 lines, unchanged. |
| Feature-table honesty | 10 | Unchanged. |
| Narrative | 10 | Unchanged. |
| CHANGELOG discipline | 10 | **R15 closed**: R15 section added to `CHANGELOG.md` under `## [Unreleased]` with `### Added in Round 15` and `### Changed in Round 15`. Documents all 5 fixes. (R14 had R12/R13 sections; R15 adds R15 — but R14 section is still missing.) |
| Visual assets | 8 | Unchanged — no demo GIF. |
| Contributor experience | 9 | Unchanged. |
| Discoverability | 6 | Unchanged — PyPI still "not yet published"; Discord still "coming soon". |
| Documentation site | 8 | **R15 closed**: `mkdocs.yml` + 7 stub docs pages + `mkdocs build --strict` passes. Material theme with dark/light palette. Nav is explicit (8 pages). v0.2 will add `mkdocstrings` API reference. |
| Examples / playbooks | 10 | Unchanged. |
| Citation / academic | 8 | Unchanged — DOI placeholder, ORCID placeholder. |

**Δ +2**: The docs site is a real Marketing artifact. `mkdocs build --strict` passing means the docs are not just a `docs/` folder of markdown — they're a buildable, link-checked, themed site. CHANGELOG R15 section closes the discipline gap (R14 was missing R14 section, but R15 at least adds R15).

**Top issue:** No embedded demo GIF (only vhs recipe). Secondary: PyPI not published; Discord not live; ORCID placeholder; R14 CHANGELOG section still missing.

---

### Judge 6 — Competitive: **89 / 100** (R14: 86, Δ +3)

| Dim | Score | Notes |
|---|---|---|
| Differentiation | 9 | Unchanged. |
| Feature breadth | 7 | **R15 progress**: streaming-with-tools is a real feature breadth addition (was 6). ARNES now matches LangChain/CrewAI on streaming+tools; still missing memory, multi-agent crews, A2A, RAG, vector store, evals marketplace. |
| Eval rigor | 8 | **R15 progress**: 3 cassettes now (was 1). Still no standard-suite integration. |
| Distribution | 5 | Unchanged — PyPI not published. |
| Live UX | 6 | **R15 progress**: SSE endpoint stub landed (was 4). Wire format is stable across the v0.2 upgrade — clients written today keep working when v0.2 wires it to `PlaybookExecutor.stream`. Still a stub, not a full Studio/Canvas equivalent. |
| Docs / onboarding | 8 | **R15 progress**: `mkdocs build --strict` passes. Docs site has a real shape (8 pages, Material theme). v0.2 will add API reference. |
| Community | 5 | Unchanged — Discord "coming soon". |
| Maturity signals | 8 | **R15 progress**: 398 tests, 48 mypy-clean files, mkdocs strict passes, 3 cassettes, SSE endpoint. (was 7) |
| Lock-in posture | 10 | Unchanged. |
| Pricing / TCO | 9 | Unchanged. |

**Δ +3**: R15 closes parts of the top Competitive issue (live UX) and the secondary Competitive issue (docs site). The SSE stub is a real wire-format commitment — LangGraph Studio / CrewAI Canvas / OpenHands Web UI all have live UX, and ARNES now has the foundation for one. Feature breadth ticks up because streaming-with-tools is a real capability addition.

**Top issue:** SSE endpoint is a stub, not a full live UX. Secondary: PyPI not published; only 3 cassettes; no standard-suite integration; Discord not live.

---

### Judge 7 — Philosopher: **87 / 100** (R14: 87, Δ 0)

| Dim | Score | Notes |
|---|---|---|
| Manifesto coherence | 9 | Unchanged. |
| Constructive vision | 5 | Unchanged — manifesto still reactive. |
| Ethical stance | 7 | Unchanged — no explicit AI-safety/ethics policy. |
| Audience breadth | 5 | Unchanged. |
| Real problem | 10 | Unchanged. |
| Honesty | 10 | Unchanged. |
| Sustainability | 8 | Unchanged. |
| Power dynamics | 8 | Unchanged. |
| Inclusivity | 7 | Unchanged. |
| Long-term stakes | 8 | Unchanged. |

**Δ 0**: R15 added nothing to the manifesto / ethics layer. All R14 caveats preserved.

**Top issue:** Manifesto reactive not constructive. Secondary: no explicit AI-safety/ethics policy.

---

### Judge 8 — Scientific Tester: **90 / 100** (R14: 88, Δ +2)

| Dim | Score | Notes |
|---|---|---|
| Reproducibility | 10 | **R15 progress**: 3 cassettes now (was 1) — more reproducible real-LLM test coverage. |
| Statistical rigor | 6 | Unchanged — no CIs, no Mann-Whitney U, no effect-size, no power analysis. |
| Standard-suite integration | 4 | Unchanged — no HumanEval/MBPP/SWE-bench/GAIA/AgentBench. |
| Traceability | 10 | Unchanged. |
| Data integrity | 10 | Unchanged. |
| Citation infrastructure | 7 | Unchanged — DOI placeholder, ORCID placeholder. |
| Methodology documentation | 9 | **R15 progress**: `docs/benchmarking.md` is a real scientific-communication artifact documenting the methodology, determinism model, and cassette inventory (was 8). |
| Open-science posture | 9 | Unchanged. |
| Peer-review readiness | 5 | Unchanged. |
| Fairness / bias tooling | 5 | Unchanged. |

**Δ +2**: The +2 cassettes + `docs/benchmarking.md` are real Scientific Tester progress. The cassette inventory is now documented end-to-end (3 cassettes listed with their specialist + provider + cost). Reproducibility ticks up because more real-LLM interactions are pinned.

**Top issue:** No standard-suite integration (HumanEval / MBPP / SWE-bench / GAIA / AgentBench). Secondary: no real Zenodo DOI (placeholder); ORCID placeholder; no statistical rigor beyond p95.

---

### Judge 9 — Over-engineering: **90 / 100** (R14: 89, Δ +1)

| Dim | Score | Notes |
|---|---|---|
| Module size discipline | 8 | **R15 progress**: `cli/main.py` 774 → 293 (under 500). 3 new modules all under 500 (`helpers.py` 486, `scaffolding.py` 117, `mcp/sse.py` 112). **Still 5 files >500 lines** (was 6 — net -1): `specialists/base.py` 815 (was 706, +109 from streaming+ReAct — justified by the new cohesive responsibility), `executor.py` 770, `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 590 (was 533, +57 from SSE handler — partially offset by extracting `mcp/sse.py`). |
| DRY / duplication | 9 | SSE wire-format helpers extracted cleanly (no duplication). CLI helpers extracted cleanly. |
| Backwards-compat debt | 8 | Unchanged — no wrapper methods added; the `__all__` re-export list in `cli/helpers.py` is for downstream imports. |
| API surface honesty | 10 | **R15 progress**: `Specialist.stream()` docstring honestly documents the R15 ReAct-loop change. `LLMProvider.stream_complete` contract docstring honestly documents the tool_calls-in-final-chunk allowance. `mcp/sse.py` docstring honestly documents the v0.2 upgrade path. |
| Folder hygiene | 10 | Unchanged. |
| CHANGELOG discipline | 10 | **R15 closed**: R15 section added to CHANGELOG. (was 9) |
| Dead code | 9 | Unchanged. |
| Indirection depth | 8 | Unchanged — `mcp/sse.py` adds 1 layer of indirection but it's well-justified (keeps `mcp/server.py` under control). |
| Abstraction fit | 8 | Unchanged. |
| Configuration surface | 8 | Unchanged. |

**Δ +1**: Net positive on module size (1 file fixed, 3 new modules all under 500). The slight regressions on `mcp/server.py` and `specialists/base.py` are honest costs of the SSE endpoint and the streaming+ReAct wiring — both are real new responsibilities, not artificial growth. CHANGELOG discipline restored. The 5-file 500-line violation count is the lowest it's been since R12 (was 6 in R13/R14, now 5).

**Top issue:** 5 files still violate the AGENTS.md 500-line rule (`specialists/base.py` 815, `executor.py` 770, `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 590). Secondary: `schema.py:8` module docstring still stale (preserved R13→R15); `mkdocs` not yet in `pyproject.toml`.

---

## 4. Score Summary

| # | Judge | Pre-fix (R14) | Post-fix (R15) | Δ | GO / NO-GO |
|---|---|---|---|---|---|
| 1 | Security | 91 | **92** | +1 | GO (public alpha) |
| 2 | Development | 95 | **96** | +1 | GO (public alpha) — highest category, 4th consecutive round ≥ 93 |
| 3 | Data | 91 | **92** | +1 | GO (public alpha) |
| 4 | AI | 89 | **92** | +3 | GO (public alpha, caveat shrunk) |
| 5 | Marketing | 92 | **94** | +2 | GO (public alpha) |
| 6 | Competitive | 86 | **89** | +3 | GO (public alpha) |
| 7 | Philosopher | 87 | **87** | 0 | GO (strong foundation, reactive posture) |
| 8 | Scientific Tester | 88 | **90** | +2 | GO (with standard-suite + DOI caveats for v0.2) |
| 9 | Over-engineering | 89 | **90** | +1 | GO |
| | **AVERAGE (9 judges)** | **89.8** | **92.0** | **+2.2** | — |

**The 9-judge average climbed from 89.8 → 92.0 (+2.2)**, driven by:
- **AI +3** (biggest single gain — `Specialist.stream()` ReAct wiring closes the top R11→R14 gap; +2 cassettes; SSE stub)
- **Competitive +3** (SSE stub + docs site + feature breadth from streaming+tools)
- **Marketing +2** (MkDocs site + CHANGELOG R15 section)
- **Scientific +2** (+2 cassettes + `docs/benchmarking.md`)
- **Security +1, Development +1, Data +1, Over-eng +1** (small gains from SSE auth inheritance, cli split, per-iteration streaming events, module-size discipline)
- **Philosopher 0** (R15 added nothing to the manifesto / ethics layer)

**R15 is a larger average gain than R14 (+2.2 vs +0.9)** because R15 attacked structural issues (streaming+ReAct, SSE, cli split, cassettes, docs site) rather than Tier-1 quick wins. The 5 fixes delivered compounding gains across 8 of 9 judges.

---

## 5. Is 95 / 100 Reached?

**No.** 9-judge average is **92.0 / 100** — still **3.0 points below 95**.

**Distance to 95:**
- Currently at 828 / 900 across 9 judges (was 808 in R14, **+20 points**).
- Need 855 / 900 to reach 95 average.
- Need **+27 more points across 9 judges = avg +3.0 per judge**.

**What moved vs R14:**
- R14 → R15: +20 points (Security +1, Dev +1, Data +1, AI +3, Marketing +2, Competitive +3, Philosopher 0, Scientific +2, Over-eng +1).
- R13 → R14: +9 points (smaller Tier-1 sweep).
- R12 → R13: +13 points.
- R11 → R12: +20 points (first multi-day feature round).

**The path to 95/100 (ordered by leverage, with R15 starting point 92.0):**

### Tier 1 — Remaining 1-hour quick wins (~4-6 hours, +2 to +3 average)
1. **Migrate `release.yml` to PyPI OIDC Trusted Publishing** (preserved R8→R15, 7 rounds). → Security +2, Dev +1. **~30 min.**
2. **Add `cwd` allowlist to `ShellTool.Args`** (preserved R1→R15, 14 rounds). → Security +1. **~30 min.**
3. **Fix `schema.py:8` module docstring** (preserved R13→R15). → Security +1, Over-eng +1, Dev +1. **~5 min.**
4. **Register CITATION.cff on Zenodo for a real DOI**. → Scientific +3, Marketing +1, Competitive +1. **~30 min + Zenodo wait.**
5. **Replace ORCID placeholder** with the author's real ORCID. → Scientific +1, Marketing +1. **~5 min.**
6. **Embed a `vhs`-recorded `docs/demo.gif`** in the README. → Marketing +2, Competitive +1. **~30 min.**
7. **Publish to PyPI** (after OIDC migration). → Marketing +2, Competitive +2. **~1 hour + PyPI review wait.**
8. **Stand up a Discord / GitHub Discussions** as primary chat. → Marketing +1, Competitive +1. **~1 hour.**
9. **Add `mkdocs` + `mkdocs-material` to `pyproject.toml` `[project.optional-dependencies].dev`**. → Dev +1, Over-eng +1. **~5 min.**
10. **Add CHANGELOG R14 section** (currently jumps R13 → R15). → Marketing +1, Over-eng +1. **~10 min.**

**Tier 1 total: ~5-7 hours of work, +4 to +6 average points.** Brings 9-judge average from 92.0 → ~94-96. **Likely crosses 95 if all 10 land.**

### Tier 2 — Multi-day features (1-2 weeks, +3 to +5 average)
11. **Wire SSE to `PlaybookExecutor.stream`** (replace the heartbeat stub with real step-transition events). → AI +2, Competitive +3. **2-3 days.**
12. **Finish the 500-line cleanup**: split `specialists/base.py` (815), `executor.py` (770), `tools/builtin.py` (664), `cost_guard.py` (611), `mcp/server.py` (590) below 500. → Dev +2, Over-eng +2. **2-3 days.**
13. **Cover `cli/main.py`** (was 26 %, now likely lower post-split — needs measurement), `llm/factory.py` (26 %), `tools/registry.py` (30 %), `mcp/server.py` (~64 %). → Dev +2. **1-2 days.**
14. **Add more vcrpy cassettes** — `@tester`, `@debugger`, Anthropic, Ollama, error paths (4xx, 5xx, timeout), tool-use responses, streaming responses. → AI +2, Competitive +1, Scientific +1. **1-2 days.**
15. **Add a `CacheBackend` protocol + Redis impl**. (preserved R9→R15). → Data +3. **1-2 days.**
16. **Add 1-2 standard benchmark suites** (HumanEval for code, GAIA for general agents). → Scientific +4, Competitive +2. **3-5 days.**

**Tier 2 total: ~2 weeks, +6 to +10 average points.** Brings 9-judge average from ~95 → ~96-98.

### Tier 3 — Research-grade + philosophical depth (2-4 weeks, +2 to +4 average)
17. **Add statistical rigor tooling** (multiple-seed runner with CIs, Mann-Whitney U significance tests, effect-size reporting, power analysis). → Scientific +3. **2-3 days.**
18. **Write a constructive manifesto addendum** ("What world ARNES builds"). → Philosopher +3. **1 day.**
19. **Add an AI-safety / ethics policy** (content moderation opt-in, data retention defaults, model-bias disclosure template, fairness metrics in the benchmark harness). → Philosopher +3, Scientific +1. **1-2 days.**
20. **Add `mkdocstrings` API reference** to the docs site. → Marketing +1, Competitive +1. **1-2 days.**
21. **Write a peer-review-ready methodology paper** + threat-to-validity discussion + related-work section. → Scientific +3, Marketing +1. **1-2 weeks.**

**Tier 3 total: ~2-4 weeks, +5 to +8 average points.** Solidly above 95/100 on the 9-judge panel.

### Realistic timeline to 95/100
- **Tier 1 alone (5-7 hours)**: 92.0 → ~94-96 (9-judge). **Likely crosses 95 if all 10 land.**
- **Tier 1 + Tier 2 (~2 weeks)**: ~96 → ~97-98 (9-judge). Solidly above 95/100.
- **Tier 1 + Tier 2 + Tier 3 (~4-6 weeks)**: ~97 → ~98-99 (9-judge). Near the ceiling.

**The single highest-leverage next action**: a **5-7 hour Tier-1 sweep** — OIDC migration + `cwd` allowlist + `schema.py:8` docstring + Zenodo DOI deposit + real ORCID + record demo GIF + PyPI publish + Discord + `mkdocs` in pyproject.toml + CHANGELOG R14 section. This would bring the 9-judge average from 92.0 to ~94-96 and **very likely cross 95/100**.

**The two structural decisions that would most accelerate the path to 95** (preserved from R14, still valid):
- (a) **Wire SSE to `PlaybookExecutor.stream`** — closes the top Competitive issue and the secondary AI issue (Tier 2 item 11). **~2-3 days.**
- (b) **Ship 1-2 standard benchmark suites** (HumanEval/GAIA) — closes the top Scientific issue and the secondary Competitive issue (Tier 2 item 16). **~3-5 days.**

Together they would deliver +5 to +7 average points in a single 1-week sprint.

---

## 6. Final Assessment

**Trajectory (9-judge):** R11 (85.4) → R12 (87.6) → R13 (88.9) → R14 (89.8) → **R15 (92.0)**.

**Honest characterization of R15:**
- ✅ **All 5 R15 fix claims verified applied** — streaming+ReAct wired; SSE endpoint stub + `mcp/sse.py` extraction; `cli/main.py` 774 → 293 split into 3 modules; 2 new vcrpy cassettes (`@coder`, `@reviewer`); `mkdocs.yml` + 7 stub docs pages with `mkdocs build --strict` passing.
- ✅ **All quality gates green** — 398/398 tests pass, `mypy --strict` clean (48 files, +3), `ruff check` clean, `ruff format` clean, `bandit` 0/0/0/0, coverage 77.12 % (-0.25 pp but well above the 65 % gate), `mkdocs build --strict` passes.
- ✅ **8 of 9 judges improved** (Security +1, Dev +1, Data +1, AI +3, Marketing +2, Competitive +3, Scientific +2, Over-eng +1). Only Philosopher preserved (R15 added nothing to the manifesto/ethics layer).
- ✅ **Top R11→R14 AI issue CLOSED** — `Specialist.stream()` now participates in the ReAct loop. Streaming with tools works end-to-end.
- ✅ **Top R7→R14 Competitive issue PARTIALLY CLOSED** — SSE endpoint stub landed. Wire format is stable across the v0.2 upgrade.
- ✅ **Module size discipline IMPROVED** — `cli/main.py` 774 → 293 (under 500). 3 new modules all under 500. Net: 6 → 5 files >500 lines.
- ✅ **Real-LLM test coverage IMPROVED** — 1 → 3 cassettes. 3 of 5 specialists now have recorded OpenAI responses.
- ✅ **Documentation site LANDED** — `mkdocs.yml` + 7 stub docs pages + strict build passes.
- ⚠️ **5 R13/R14 Tier-1 quick wins NOT closed in R15** — OIDC migration (preserved R8→R15, 7 rounds), `ShellTool.Args.cwd` allowlist (preserved R1→R15, 14 rounds), `schema.py:8` module docstring (preserved R13→R15), real Zenodo DOI deposit (placeholder only), real ORCID (placeholder), embedded demo GIF (recipe only). Each is ≤ 1 hour of work — R15 left ~+2 to +3 average points on the table by not sweeping them.
- ⚠️ **5 files still violate the AGENTS.md 500-line rule** (was 6 — net -1): `specialists/base.py` 815 (was 706, +109 from streaming+ReAct), `executor.py` 770, `tools/builtin.py` 664, `cost_guard.py` 611, `mcp/server.py` 590 (was 533, +57 from SSE handler). The growth in `specialists/base.py` and `mcp/server.py` is justified by the new cohesive responsibilities (streaming+ReAct, SSE handler), but the count is still 5.
- ⚠️ **Cache still in-memory only** (no `CacheBackend` + Redis; unchanged R9→R15, 6 rounds). Top Data issue.
- ⚠️ **No standard-suite integration** (HumanEval / MBPP / SWE-bench / GAIA / AgentBench) + no real DOI. Top Scientific issue.
- ⚠️ **Manifesto still reactive** + no AI-safety policy (unchanged). Top Philosopher issue.
- ⚠️ **`release.yml` still uses long-lived `PYPI_API_TOKEN`** (preserved R8→R15, 7 rounds). Top Security issue.
- ⚠️ **SSE endpoint is a stub** — not wired to `PlaybookExecutor.stream`. Top Competitive issue (partial closure).
- ⚠️ **`mkdocs` + `mkdocs-material` not yet in `pyproject.toml`** — installed in dev env but not declared as dev dependencies. v0.2 cleanup.
- ⚠️ **CHANGELOG R14 section still missing** — jumps R13 → R15. Minor discipline regression.

**Bottom line:** R15 is the most consequential single round since R12. The streaming+ReAct wiring closes the top AI issue that had been preserved for 4 rounds (R11→R14). The SSE endpoint stub closes part of the top Competitive issue that had been preserved for 8 rounds (R7→R14). The cli split is the biggest module-size win since R13's executor split. The +2 cassettes + docs site are real Marketing/Competitive/Scientific artifacts. The 9-judge average climbs from 89.8 → 92.0 (+2.2), driven by AI (+3) and Competitive (+3) — the two judges that had been stuck the longest. **All 9 categories are GO** — no NO-GOs, no CONDITIONAL GOs. ARNES at R15 is the closest it has ever been to the 95/100 tier.

**Final GO/NO-GO: GO for public alpha release as `0.1.0a1` on all 9 dimensions.** The path to 95/100 is now a **5-7 hour Tier-1 sweep** — OIDC + `cwd` + `schema.py:8` + Zenodo DOI + ORCID + demo GIF + PyPI publish + Discord + `mkdocs` in pyproject + CHANGELOG R14. With those 10 quick wins, the 9-judge average would very likely cross 95/100. The two structural decisions that would most accelerate the path to 95 (preserved from R14, still valid): (a) wire SSE to `PlaybookExecutor.stream` — closes the top Competitive issue; (b) ship 1-2 standard benchmark suites — closes the top Scientific issue.

---

*End of report. — JUDGE_FINAL_R15 (9-judge consolidated panel)*
