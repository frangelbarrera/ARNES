"""Stress test: a 50-step playbook compiled and executed against the mock LLM.

Verifies that ARNES can handle a realistically large playbook end-to-end:

1. Programmatically generate a playbook with 50 sequential @planner steps.
2. Compile it with PlaybookCompiler (YAML -> pydantic -> semantic checks).
3. Execute it with PlaybookExecutor + SchemaValidMockProvider.
4. Assert that:
   - All 50 steps complete successfully.
   - Total wall-clock time (compile + execute) is under 30s.
   - The thread ends with exactly 101 events:
        50 step_started + 50 step_completed + 1 run_completed.
5. Capture and print:
   - Compile time
   - Execution time
   - Total events in the thread
   - Peak memory usage during the run (tracemalloc)
   - Step duration statistics (min / mean / max / p95)

Any performance bottleneck detected is reported to stdout so the engineer
can decide whether to fix it in the ARNES source.
"""

from __future__ import annotations

import asyncio
import gc
import statistics
import time
import tracemalloc
from typing import Any

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.thread.events import EventType

# ============================================================
# Mock provider — same schema-valid pattern as tests/integration/test_e2e.py
# ============================================================


class SchemaValidMockProvider(LLMProvider):
    """Mock provider that returns schema-valid JSON for each specialist.

    Identical contract to the one in tests/integration/test_e2e.py — kept
    local so the stress test has no cross-file dependency.
    """

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
        **kwargs,
    ) -> LLMResponse:
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = (
                '{"files": [{"path": "out.py", "language": "python", "content": "pass"}], '
                '"summary": "ok", "assumptions": [], "warnings": []}'
            )
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
        elif "@tester" in sys_content:
            content = (
                '{"test_files": [{"path": "test.py", "content": "pass"}], '
                '"test_results": {"passed": 1, "failed": 0, "skipped": 0, "failures": []}, '
                '"summary": "ok"}'
            )
        elif "@debugger" in sys_content:
            content = (
                '{"root_cause": "x", "confidence": 0.9, '
                '"fix": {"file": "f.py", "line": 1, "original": "x", "fixed": "y", '
                '"explanation": "ok"}, "verification": "v", "alternative_causes": []}'
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

    def list_models(self) -> list[str]:
        return ["mock"]


# ============================================================
# Playbook generator
# ============================================================


def _generate_50_step_playbook_yaml() -> str:
    """Generate a YAML playbook with 50 sequential @planner steps.

    Each step is independent (no cross-step template refs) so we measure
    the executor's per-step overhead, not template resolution cost.
    """
    steps_yaml: list[str] = []
    for i in range(1, 51):
        steps_yaml.append(
            f"  - id: step_{i}\n"
            f'    specialist: "@planner"\n'
            f"    input:\n"
            f'      task: "Plan step {i} of 50 for the stress test"'
        )
    body = "\n".join(steps_yaml)
    return (
        "name: large_playbook_stress\n"
        "objective: Stress test with 50 sequential @planner steps\n"
        "budget_usd: 1.0\n"
        "steps:\n"
        f"{body}\n"
    )


def _generate_50_step_playbook_dict() -> dict[str, Any]:
    """Generate the same playbook as a plain dict (skips YAML parse step)."""
    return {
        "name": "large_playbook_stress",
        "objective": "Stress test with 50 sequential @planner steps",
        "budget_usd": 1.0,
        "steps": [
            {
                "id": f"step_{i}",
                "specialist": "@planner",
                "input": {"task": f"Plan step {i} of 50 for the stress test"},
            }
            for i in range(1, 51)
        ],
    }


# ============================================================
# Helpers for metrics extraction
# ============================================================


def _step_durations(thread) -> list[float]:
    """Pull per-step duration_s from StepCompletedEvent.data."""
    durations: list[float] = []
    for ev in thread:
        if ev.type == EventType.STEP_COMPLETED:
            d = ev.data.get("duration_s")
            if isinstance(d, (int, float)):
                durations.append(float(d))
    return durations


def _count_by_type(thread) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in thread:
        key = str(ev.type.value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


# ============================================================
# The stress test
# ============================================================


class TestLargePlaybookStress:
    """50-step playbook stress test."""

    @pytest.mark.asyncio
    async def test_50_step_playbook_completes_under_30s(self, capsys):
        """The headline stress test — 50 steps, 101 events, < 30s wall clock."""
        N_STEPS = 50
        EXPECTED_EVENTS = N_STEPS * 2 + 1  # started + completed + run_completed

        yaml_str = _generate_50_step_playbook_yaml()

        # ---------- Compile ----------
        gc.collect()
        tracemalloc.start()
        compile_t0 = time.perf_counter()
        playbook = PlaybookCompiler.from_string(yaml_str)
        compile_elapsed = time.perf_counter() - compile_t0

        # Sanity: the playbook actually has 50 steps
        assert len(playbook.steps) == N_STEPS, (
            f"Expected {N_STEPS} steps, got {len(playbook.steps)}"
        )

        # ---------- Execute ----------
        provider = SchemaValidMockProvider()
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=10.0),
        )

        exec_t0 = time.perf_counter()
        result = await executor.run(playbook)
        exec_elapsed = time.perf_counter() - exec_t0

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        total_wall = compile_elapsed + exec_elapsed
        type_counts = _count_by_type(result.thread)
        durations = _step_durations(result.thread)

        # ---------- Report ----------
        report = [
            "",
            "=" * 60,
            "STRESS-2: 50-step playbook — metrics",
            "=" * 60,
            f"Steps in playbook      : {len(playbook.steps)}",
            f"Compile time           : {compile_elapsed * 1000:.2f} ms",
            f"Execution time         : {exec_elapsed * 1000:.2f} ms ({exec_elapsed:.3f} s)",
            f"Total wall clock       : {total_wall * 1000:.2f} ms ({total_wall:.3f} s)",
            f"Total events in thread : {len(result.thread)}",
            f"Event type breakdown   : {type_counts}",
            f"Steps executed         : {result.steps_executed}",
            f"Steps failed           : {result.steps_failed}",
            f"Run success            : {result.success}",
            f"Run duration_s (result): {result.duration_s:.3f} s",
            f"Total tokens in        : {result.total_tokens_in}",
            f"Total tokens out       : {result.total_tokens_out}",
            f"Total cost USD         : ${result.total_cost_usd:.6f}",
            f"Peak tracemalloc       : {peak / 1024:.2f} KiB",
            f"Current tracemalloc    : {current / 1024:.2f} KiB",
        ]
        if durations:
            report += [
                f"Step duration min      : {min(durations) * 1000:.3f} ms",
                f"Step duration mean     : {statistics.mean(durations) * 1000:.3f} ms",
                f"Step duration median   : {statistics.median(durations) * 1000:.3f} ms",
                f"Step duration max      : {max(durations) * 1000:.3f} ms",
                f"Step duration p95      : {_percentile(durations, 95) * 1000:.3f} ms",
                f"Step duration stdev    : "
                f"{(statistics.pstdev(durations) if len(durations) > 1 else 0.0) * 1000:.3f} ms",
            ]
        report.append("=" * 60)
        report.append("")
        with capsys.disabled():
            print("\n".join(report))

        # ---------- Assertions ----------
        assert result.success is True, f"Playbook run failed: error={result.error!r}"
        assert result.steps_executed == N_STEPS, (
            f"Expected {N_STEPS} steps executed, got {result.steps_executed}"
        )
        assert result.steps_failed == 0, f"Expected 0 failures, got {result.steps_failed}"
        # 50 step_started + 50 step_completed + 1 run_completed = 101
        assert len(result.thread) == EXPECTED_EVENTS, (
            f"Expected {EXPECTED_EVENTS} events in thread, "
            f"got {len(result.thread)} (breakdown: {type_counts})"
        )
        assert type_counts.get("step_started", 0) == N_STEPS, (
            f"Expected {N_STEPS} step_started events, got {type_counts.get('step_started', 0)}"
        )
        assert type_counts.get("step_completed", 0) == N_STEPS, (
            f"Expected {N_STEPS} step_completed events, got {type_counts.get('step_completed', 0)}"
        )
        assert type_counts.get("run_completed", 0) == 1, (
            f"Expected 1 run_completed event, got {type_counts.get('run_completed', 0)}"
        )
        # Total wall clock (compile + execute) must be under 30s
        assert total_wall < 30.0, f"Total wall clock {total_wall:.3f}s exceeds 30s budget"

    @pytest.mark.asyncio
    async def test_compile_only_performance(self, capsys):
        """Compile-only path: 50-step YAML → validated Playbook in isolation.

        This isolates compiler cost from executor cost so we can see if the
        bottleneck is in YAML parsing, pydantic validation, or semantic checks.
        """
        yaml_str = _generate_50_step_playbook_yaml()

        # Warm-up (module imports, etc.)
        PlaybookCompiler.from_string(yaml_str)

        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        playbook = PlaybookCompiler.from_string(yaml_str)
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        with capsys.disabled():
            print(
                f"\n[compile-only] 50 steps: {elapsed * 1000:.2f} ms, "
                f"peak mem {peak / 1024:.2f} KiB\n"
            )

        assert len(playbook.steps) == 50
        # Compiler should be well under 1s for 50 simple steps
        assert elapsed < 1.0, f"Compile took {elapsed:.3f}s, expected < 1s"

    @pytest.mark.asyncio
    async def test_dict_input_skips_yaml_parse(self, capsys):
        """Playbook.model_validate(dict) bypasses YAML parsing.

        Useful to measure how much of compile time is YAML vs pydantic.
        """
        data = _generate_50_step_playbook_dict()

        from arnes.playbooks.schema import Playbook

        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        playbook = Playbook.model_validate(data)
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        with capsys.disabled():
            print(
                f"\n[dict-validate] 50 steps: {elapsed * 1000:.2f} ms, "
                f"peak mem {peak / 1024:.2f} KiB\n"
            )

        assert len(playbook.steps) == 50
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_thread_append_scaling(self, capsys):
        """Micro-benchmark: Thread.append() O(N) vs O(N^2) behavior.

        The current Thread.append() does `events=[*self.events, event]`,
        which is O(N) per append — so building a thread of N events is
        O(N^2) total. This test surfaces the cost so we can decide whether
        to optimize the data structure.
        """
        from arnes.thread import Thread
        from arnes.thread.events import StepStartedEvent

        sizes = [100, 500, 1000]
        results: list[str] = []
        for n in sizes:
            thread = Thread.create()
            tid = thread.id
            t0 = time.perf_counter()
            for i in range(n):
                thread = thread.append(
                    StepStartedEvent(
                        thread_id=tid,
                        step_id=f"s{i}",
                        data={"step_id": f"s{i}"},
                    )
                )
            elapsed = time.perf_counter() - t0
            results.append(
                f"  append x{n}: {elapsed * 1000:.2f} ms ({elapsed / n * 1_000_000:.2f} us/append)"
            )
            assert len(thread) == n

        with capsys.disabled():
            print("\n[thread.append scaling]")
            print("\n".join(results))
            print()


# ============================================================
# CLI entry point — run without pytest for a quick standalone report
# ============================================================


async def _run_standalone() -> None:
    """Standalone runner — prints the same report pytest would assert on."""
    yaml_str = _generate_50_step_playbook_yaml()

    gc.collect()
    tracemalloc.start()
    compile_t0 = time.perf_counter()
    playbook = PlaybookCompiler.from_string(yaml_str)
    compile_elapsed = time.perf_counter() - compile_t0

    provider = SchemaValidMockProvider()
    executor = PlaybookExecutor(
        provider=provider,
        cost_budget=CostBudget(task_budget_usd=10.0),
    )
    exec_t0 = time.perf_counter()
    result = await executor.run(playbook)
    exec_elapsed = time.perf_counter() - exec_t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    type_counts = _count_by_type(result.thread)
    durations = _step_durations(result.thread)
    total_wall = compile_elapsed + exec_elapsed

    print()
    print("=" * 60)
    print("STRESS-2 (standalone): 50-step playbook — metrics")
    print("=" * 60)
    print(f"Steps in playbook      : {len(playbook.steps)}")
    print(f"Compile time           : {compile_elapsed * 1000:.2f} ms")
    print(f"Execution time         : {exec_elapsed * 1000:.2f} ms ({exec_elapsed:.3f} s)")
    print(f"Total wall clock       : {total_wall * 1000:.2f} ms ({total_wall:.3f} s)")
    print(f"Total events in thread : {len(result.thread)}")
    print(f"Event type breakdown   : {type_counts}")
    print(f"Steps executed         : {result.steps_executed}")
    print(f"Steps failed           : {result.steps_failed}")
    print(f"Run success            : {result.success}")
    print(f"Peak tracemalloc       : {peak / 1024:.2f} KiB")
    if durations:
        print(
            f"Step duration min/mean/max/p95: "
            f"{min(durations) * 1000:.2f} / "
            f"{statistics.mean(durations) * 1000:.2f} / "
            f"{max(durations) * 1000:.2f} / "
            f"{_percentile(durations, 95) * 1000:.2f} ms"
        )
    print("=" * 60)

    # Hard assertions (mirror the pytest test)
    assert result.success, f"run failed: {result.error}"
    assert result.steps_executed == 50, f"steps_executed={result.steps_executed}"
    assert result.steps_failed == 0, f"steps_failed={result.steps_failed}"
    assert len(result.thread) == 101, f"events={len(result.thread)}"
    assert total_wall < 30.0, f"wall={total_wall:.3f}s"
    print("\nAll standalone assertions PASSED.")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_run_standalone())
