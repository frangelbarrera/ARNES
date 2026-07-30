"""ARNES Concurrent Execution Stress Test (STRESS-1).

Runs 50 playbooks concurrently via ``asyncio.gather`` with the
``SchemaValidMockProvider`` pattern (lifted from ``tests/integration/test_e2e.py``).

Each playbook is a 3-step manual: planner -> coder -> reviewer.

Asserts:
- All 50 runs complete successfully.
- No exceptions leak out of ``asyncio.gather``.
- Total wall-clock time < 10s.
- Each run's Thread has a unique ID (race-condition guard).
- Each run executes exactly 3 steps with 0 failures.
- The shared mock provider was invoked exactly 150 times (3 x 50).

Run via:
    pytest tests/stress/test_concurrent.py -s --no-cov
or:
    python tests/stress/test_concurrent.py
"""

from __future__ import annotations

import asyncio
import gc
import resource
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# Make `arnes` importable when running the file directly (python tests/stress/...).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage  # noqa: E402
from arnes.middleware.cost_guard import CostBudget  # noqa: E402
from arnes.playbooks.compiler import PlaybookCompiler  # noqa: E402
from arnes.playbooks.executor import PlaybookExecutor  # noqa: E402

# ============================================================
# Constants
# ============================================================

N_RUNS = 50
TIME_BUDGET_S = 10.0
STEPS_PER_RUN = 3
EXPECTED_LLM_CALLS = N_RUNS * STEPS_PER_RUN
# 3 step_started + 3 assistant_message + 3 step_completed + 1 run_completed = 10
# (each specialist makes exactly one LLM call against the mock provider,
# which returns no tool_calls, so exactly one AssistantMessageEvent per step)
EXPECTED_EVENTS_PER_THREAD = STEPS_PER_RUN * 3 + 1


# ============================================================
# Playbook (3-step manual: planner -> coder -> reviewer)
# ============================================================

PLAYBOOK_YAML_TEMPLATE = """
name: stress_3step_{run_id}
objective: 3-step manual for stress test run {run_id}
budget_usd: 1.0
variables:
  run_id: {run_id}
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan feature for run {run_id}"
  - id: code
    specialist: "@coder"
    input:
      spec: "Implement feature for run {run_id}"
      context: "{{{{ steps.plan.output }}}}"
  - id: review
    specialist: "@reviewer"
    input:
      code: "{{{{ steps.code.output }}}}"
      focus: "Review for run {run_id}"
"""


# ============================================================
# Schema-valid mock provider (shared across all concurrent runs)
# ============================================================


class SchemaValidMockProvider(LLMProvider):
    """Mock provider that returns schema-valid JSON for each specialist.

    Shared across all 50 concurrent runs. Carries instrumentation to detect
    re-entrancy / race conditions:
    - ``call_count``: total ``complete()`` invocations
    - ``active_calls``: in-flight count at any moment
    - ``max_concurrent_calls``: high-water mark of in-flight calls
    - ``per_run_call_counts``: dict tracking LLM calls per run_id (read from messages)
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.active_calls = 0
        self.max_concurrent_calls = 0
        # Track how many times we saw each run_id in the user message — used to
        # verify that runs don't get tangled (each run should produce exactly 3
        # LLM calls with its own run_id in the user content).
        self.run_id_seen: dict[str, int] = {}

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        response_schema: dict | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # ---- Instrumentation: count active calls (race detector) ----
        self.call_count += 1
        self.active_calls += 1
        self.max_concurrent_calls = max(self.max_concurrent_calls, self.active_calls)

        try:
            # Yield to the event loop to force interleaving across the 50 runs.
            # Without this, asyncio.gather might run each coroutine to completion
            # before starting the next, hiding real races.
            await asyncio.sleep(0)

            sys_msg = next((m for m in messages if m.role == "system"), None)
            sys_content = sys_msg.content if sys_msg else ""

            user_msg = next((m for m in messages if m.role == "user"), None)
            user_content = user_msg.content if user_msg else ""

            # Extract run_id from the user message ("run N" appears in input data)
            run_id = _extract_run_id(user_content)
            if run_id is not None:
                self.run_id_seen[run_id] = self.run_id_seen.get(run_id, 0) + 1

            # ---- Schema-valid content per specialist ----
            if "@planner" in sys_content:
                content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
            elif "@coder" in sys_content:
                content = (
                    '{"files": [{"path": "out.py", "language": "python", '
                    '"content": "pass"}], "summary": "ok", '
                    '"assumptions": [], "warnings": []}'
                )
            elif "@reviewer" in sys_content:
                content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
            elif "@tester" in sys_content:
                content = (
                    '{"test_files": [{"path": "test.py", "content": "pass"}], '
                    '"test_results": {"passed": 1, "failed": 0, "skipped": 0, '
                    '"failures": []}, "summary": "ok"}'
                )
            elif "@debugger" in sys_content:
                content = (
                    '{"root_cause": "x", "confidence": 0.9, "fix": {"file": "f.py", '
                    '"line": 1, "original": "x", "fixed": "y", "explanation": "ok"}, '
                    '"verification": "v", "alternative_causes": []}'
                )
            else:
                content = '{"result": "ok"}'

            return LLMResponse(
                content=content,
                tool_calls=[],
                usage=LLMUsage(
                    tokens_in=sum(len(m.content) // 4 for m in messages),
                    tokens_out=len(content) // 4,
                    cost_usd=0.0,
                    model=model,
                    cached=False,
                ),
                model=model,
            )
        finally:
            self.active_calls -= 1

    def list_models(self) -> list[str]:
        return ["mock"]


def _extract_run_id(user_content: str) -> str | None:
    """Extract the run id from a user message body.

    The planner/coder/reviewer inputs embed 'run N' literally. We pick the
    first match. Returns None if not found.
    """
    import re

    match = re.search(r"run (\d+)", user_content)
    return match.group(1) if match else None


# ============================================================
# Helpers
# ============================================================


def _get_rss_kb() -> int:
    """Return current process RSS in KB (Linux resource module)."""
    # ru_maxrss is in KB on Linux, in bytes on macOS — we're on Linux per spec.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _format_kb(kb: int) -> str:
    if kb < 1024:
        return f"{kb} KB"
    return f"{kb / 1024:.2f} MB"


# ============================================================
# Test
# ============================================================


class TestConcurrentStress:
    """STRESS-1: 50 concurrent playbook executions."""

    @pytest.mark.asyncio
    async def test_50_concurrent_playbooks(self) -> None:
        # ============================================================
        # Setup: one shared provider + one shared executor (hardest case
        # for finding shared-state bugs).
        # ============================================================
        provider = SchemaValidMockProvider()
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=10.0),
        )

        # Pre-compile 50 distinct playbooks (different run_id → race detector).
        playbooks = [
            PlaybookCompiler.from_string(PLAYBOOK_YAML_TEMPLATE.format(run_id=i))
            for i in range(N_RUNS)
        ]
        assert len(playbooks) == N_RUNS

        # ============================================================
        # Memory baseline
        # ============================================================
        gc.collect()
        tracemalloc.start()
        # Take a traced snapshot before
        snapshot_before = tracemalloc.take_snapshot()
        rss_before_kb = _get_rss_kb()

        # ============================================================
        # Run 50 playbooks concurrently via asyncio.gather
        # ============================================================
        start = time.perf_counter()
        # return_exceptions=True so a single failure doesn't kill the whole
        # gather — we want to inspect all results.
        raw_results = await asyncio.gather(
            *(executor.run(pb) for pb in playbooks),
            return_exceptions=True,
        )
        elapsed_s = time.perf_counter() - start

        # ============================================================
        # Memory after
        # ============================================================
        gc.collect()
        rss_after_kb = _get_rss_kb()
        traced_current, traced_peak = tracemalloc.get_traced_memory()
        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # ============================================================
        # Assertions
        # ============================================================

        # 1. No exceptions leaked from gather
        exceptions = [r for r in raw_results if isinstance(r, BaseException)]
        assert not exceptions, (
            f"{len(exceptions)} runs raised exceptions. First: "
            f"{type(exceptions[0]).__name__}: {exceptions[0]}"
        )

        results = raw_results  # now known to be all PlaybookRunResult

        # 2. All 50 must complete successfully
        successes = [r for r in results if r.success]
        assert len(successes) == N_RUNS, (
            f"Only {len(successes)}/{N_RUNS} runs succeeded. "
            f"First failure: {next((r.error for r in results if not r.success), 'n/a')}"
        )

        # 3. Each run executed exactly 3 steps with 0 failures
        for i, r in enumerate(results):
            assert r.steps_executed == STEPS_PER_RUN, (
                f"Run {i}: expected {STEPS_PER_RUN} steps executed, "
                f"got {r.steps_executed}. Error: {r.error}"
            )
            assert r.steps_failed == 0, f"Run {i}: {r.steps_failed} failed steps"

        # 4. Each thread should have exactly 10 events
        #    (3 step_started + 3 assistant_message + 3 step_completed + 1 run_completed)
        for i, r in enumerate(results):
            assert len(r.thread) == EXPECTED_EVENTS_PER_THREAD, (
                f"Run {i}: expected {EXPECTED_EVENTS_PER_THREAD} thread events, got {len(r.thread)}"
            )

        # 5. RACE CHECK: all thread IDs must be unique
        thread_ids = [r.thread.id for r in results]
        unique_thread_ids = set(thread_ids)
        assert len(unique_thread_ids) == N_RUNS, (
            f"RACE DETECTED: only {len(unique_thread_ids)} unique thread IDs "
            f"for {N_RUNS} runs — threads are being shared across runs"
        )

        # 6. RACE CHECK: outputs must be present for each run (no cross-run leakage
        #    would erase them)
        for i, r in enumerate(results):
            assert "plan" in r.outputs, f"Run {i}: missing 'plan' output"
            assert "code" in r.outputs, f"Run {i}: missing 'code' output"
            assert "review" in r.outputs, f"Run {i}: missing 'review' output"

        # 7. RACE CHECK: mock provider was invoked exactly 150 times (3 per run × 50)
        assert provider.call_count == EXPECTED_LLM_CALLS, (
            f"Expected {EXPECTED_LLM_CALLS} LLM calls ({STEPS_PER_RUN} x {N_RUNS}), "
            f"got {provider.call_count}"
        )

        # 8. RACE CHECK: each run_id should have been seen exactly 3 times
        #    (planner + coder + reviewer each embed the run_id)
        #    If runs are tangled, this distribution will be off.
        expected_per_run = STEPS_PER_RUN  # one LLM call per step
        wrong_distribution = {
            rid: count for rid, count in provider.run_id_seen.items() if count != expected_per_run
        }
        # Some LLM calls may not contain "run N" (e.g. if a template was left
        # unresolved). We only assert on the runs we DID see — and each seen
        # run_id must appear exactly 3 times.
        assert not wrong_distribution, (
            f"RACE DETECTED: run_id call distribution is off. "
            f"Expected each run_id to appear {expected_per_run} times. "
            f"Off: {wrong_distribution}"
        )
        # And we should have seen at least N_RUNS distinct run_ids (one per run)
        # — actually each run contributes 3 calls with the same run_id, so
        # distinct count == N_RUNS.
        assert len(provider.run_id_seen) == N_RUNS, (
            f"RACE DETECTED: expected {N_RUNS} distinct run_ids in mock provider, "
            f"got {len(provider.run_id_seen)}: {sorted(provider.run_id_seen.keys())[:10]}..."
        )

        # 9. Performance: total time < 10s
        assert elapsed_s < TIME_BUDGET_S, (
            f"Total time {elapsed_s:.3f}s exceeded budget of {TIME_BUDGET_S}s"
        )

        # 10. Memory growth sanity check (informational — soft assert via print,
        #     hard assert at 200 MB to catch egregious leaks)
        rss_delta_kb = rss_after_kb - rss_before_kb
        # 200 MB is a generous ceiling for 50 small runs
        assert rss_delta_kb < 200 * 1024, (
            f"RSS grew by {_format_kb(rss_delta_kb)} — possible memory leak"
        )

        # ============================================================
        # Report
        # ============================================================
        # Top memory allocations diff
        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")[:5]

        print("\n" + "=" * 70)
        print("ARNES Concurrent Stress Test — STRESS-1")
        print("=" * 70)
        print(f"Concurrent runs:       {N_RUNS}")
        print(f"Steps per run:         {STEPS_PER_RUN}")
        print(f"Successful:            {len(successes)}/{N_RUNS}")
        print(f"Exceptions leaked:     {len(exceptions)}")
        print(f"Total wall time:       {elapsed_s:.3f}s  (budget: {TIME_BUDGET_S}s)")
        print(f"Avg per run:           {elapsed_s * 1000 / N_RUNS:.2f} ms")
        print(f"LLM calls (mock):      {provider.call_count}  (expected {EXPECTED_LLM_CALLS})")
        print(f"Max concurrent calls:  {provider.max_concurrent_calls}")
        print(f"Unique thread IDs:     {len(unique_thread_ids)}/{N_RUNS}")
        print(f"Distinct run_ids seen: {len(provider.run_id_seen)}/{N_RUNS}")
        print("-" * 70)
        print(f"RSS before:            {_format_kb(rss_before_kb)}")
        print(f"RSS after:             {_format_kb(rss_after_kb)}")
        print(
            f"RSS delta:             {_format_kb(rss_delta_kb) if rss_delta_kb >= 0 else '-' + _format_kb(abs(rss_delta_kb))}"
        )
        print(f"Traced current:        {_format_kb(traced_current // 1024)}")
        print(f"Traced peak:           {_format_kb(traced_peak // 1024)}")
        print("-" * 70)
        print("Top 5 memory allocations (diff before -> after):")
        for stat in top_stats:
            print(f"  {stat}")
        print("=" * 70)
        print("RESULT: PASS — no races, no exceptions, within time + memory budget")
        print("=" * 70)


# ============================================================
# STRESS-2: verify _execute_parallel runs sub-steps TRULY concurrently
# (not sequentially as in the pre-fix for-loop implementation).
# ============================================================


class TestParallelBranchConcurrent:
    """STRESS-2: parallel branch sub-steps must run concurrently.

    Before FIX-R3-AI, ``_execute_parallel`` ran sub-steps in a sequential
    for-loop — correct but not concurrent. This test verifies the
    ``asyncio.gather`` rewrite actually overlaps sub-step execution by
    checking the shared mock provider's ``max_concurrent_calls`` watermark.
    """

    @pytest.mark.asyncio
    async def test_parallel_substeps_run_concurrently(self) -> None:
        provider = SchemaValidMockProvider()
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=10.0),
        )

        yaml_str = """
name: parallel_concurrent
objective: Verify true parallelism in _execute_parallel
steps:
  - id: parallel
    parallel:
      - id: sub1
        specialist: "@planner"
        input: {task: "Subtask 1"}
      - id: sub2
        specialist: "@coder"
        input: {spec: "Subtask 2"}
      - id: sub3
        specialist: "@reviewer"
        input: {code: "Subtask 3"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"
        # The outer parallel step counts as 1 executed step; the 3
        # sub-steps do NOT increment steps_executed (they run inside
        # _execute_parallel, not the main run() loop).
        assert result.steps_executed == 1
        # All 3 sub-steps must have made an LLM call.
        assert provider.call_count == 3, (
            f"Expected 3 LLM calls (one per sub-step), got {provider.call_count}"
        )
        # CRITICAL: at least 2 sub-steps must have been in-flight at the
        # same time. If _execute_parallel is sequential,
        # max_concurrent_calls == 1. The SchemaValidMockProvider does
        # `await asyncio.sleep(0)` inside complete() to force interleaving,
        # so a truly concurrent gather will see active_calls > 1.
        assert provider.max_concurrent_calls >= 2, (
            f"Parallel sub-steps did NOT run concurrently: "
            f"max_concurrent_calls={provider.max_concurrent_calls} (expected >= 2). "
            f"This means _execute_parallel is still sequential."
        )

        # All 3 sub-step outputs must be present in the outputs map.
        parallel_output = result.outputs.get("parallel", {})
        assert isinstance(parallel_output, dict)
        for sub_id in ("sub1", "sub2", "sub3"):
            assert sub_id in parallel_output, (
                f"Missing sub-step output '{sub_id}' in parallel branch result"
            )
            assert parallel_output[sub_id]["success"] is True, (
                f"Sub-step '{sub_id}' did not succeed"
            )


# ============================================================
# Standalone runner (python tests/stress/test_concurrent.py)
# ============================================================


async def _run_standalone() -> int:
    """Run the stress test outside pytest. Returns exit code (0=pass, 1=fail)."""
    instance = TestConcurrentStress()
    try:
        await instance.test_50_concurrent_playbooks()
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    instance2 = TestParallelBranchConcurrent()
    try:
        await instance2.test_parallel_substeps_run_concurrently()
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_standalone()))
