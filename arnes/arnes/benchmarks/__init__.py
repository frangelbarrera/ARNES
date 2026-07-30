"""ARNES Benchmark Suite — repeatable performance + correctness harness.

Public API:

* :class:`BenchmarkRunner` — runs a suite ``seeds x playbooks`` times
  and aggregates results (success rate, avg/p95 duration, tokens, cost).
* :class:`BenchmarkSuite` (Protocol) — what a suite must implement.
* :class:`BenchmarkResults` / :class:`PlaybookMetrics` — pydantic
  result models with ``to_json`` and ``to_markdown`` serialisation.

The basic suite (:mod:`arnes.benchmarks.suites.basic`) runs all
``manuals/*.yaml`` playbooks with a deterministic seeded mock LLM.

Usage::

    from arnes.benchmarks import BenchmarkRunner
    from arnes.benchmarks.suites.basic import BasicBenchmarkSuite

    runner = BenchmarkRunner()
    results = await runner.run_suite(
        BasicBenchmarkSuite(),
        seeds=(0, 1, 2),
        concurrent=4,
    )
    print(results.to_markdown())

CLI::

    arnes benchmark --seeds 3 --concurrent 4
"""

from __future__ import annotations

from arnes.benchmarks.runner import (
    BenchmarkResults,
    BenchmarkRunner,
    BenchmarkSuite,
    PlaybookBenchmarkResult,
    PlaybookMetrics,
    load_results,
    save_results,
)

__all__ = [
    "BenchmarkResults",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "PlaybookBenchmarkResult",
    "PlaybookMetrics",
    "load_results",
    "save_results",
]
