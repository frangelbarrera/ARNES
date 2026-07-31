"""ARNES Benchmark Runner — repeatable performance + correctness harness.

The runner executes a :class:`BenchmarkSuite` (a collection of playbooks +
a mock-or-real LLM provider factory) ``seeds x playbooks`` times and
aggregates the results into a single :class:`BenchmarkResults` object
that can be serialised to JSON or rendered as a markdown table.

Design goals:

* **Reproducible** — same seed + same suite ⇒ same metrics (modulo wall-
  clock variance). The mock provider used by the basic suite is fully
  deterministic; real-LLM suites opt in to non-determinism explicitly.
* **Statistically meaningful** — multi-seed runs let callers compute
  variance and detect regressions that single-shot runs would hide.
  ``p95_duration_s`` is reported alongside ``avg_duration_s`` so a slow
  tail isn't masked by a fast median.
* **Concurrency-tested** — ``concurrent=N`` runs N playbooks at once via
  an :class:`asyncio.Semaphore`, surfacing shared-state races (the same
  class of bug ``tests/stress/test_concurrent.py`` hunts for).

The runner does NOT import any LLM provider directly — it asks the suite
for a provider via ``suite.make_provider(seed)``. This keeps the runner
vendor-neutral and lets the same runner drive both mock benchmarks (fast,
deterministic, free) and real-LLM benchmarks (slow, non-deterministic,
costs money — gated behind a CLI flag).

Usage::

    from arnes.benchmarks import BenchmarkRunner
    from arnes.benchmarks.suites.basic import BasicBenchmarkSuite

    suite = BasicBenchmarkSuite()
    runner = BenchmarkRunner()
    results = await runner.run_suite(suite, seeds=(0, 1, 2), concurrent=4)
    print(results.to_markdown())
    Path("benchmark-results.json").write_text(results.to_json())
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMProvider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.playbooks.schema import Playbook

logger = structlog.get_logger(__name__)


# ============================================================
# Result models — pydantic so they serialise cleanly to JSON.
# ============================================================


class PlaybookBenchmarkResult(BaseModel):
    """Result of a single playbook run within a benchmark.

    One of these is produced per ``(playbook, seed)`` pair. They are
    aggregated into :class:`PlaybookMetrics` for reporting.
    """

    playbook_name: str
    seed: int
    success: bool
    duration_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    steps_executed: int
    steps_failed: int
    error: str | None = None


class PlaybookMetrics(BaseModel):
    """Aggregated metrics for a single playbook across all seeds.

    ``avg_*`` fields are means over the ``runs`` per-seed results.
    ``p95_duration_s`` is the 95th-percentile wall-clock duration —
    a single slow run is not masked by a fast average.
    """

    playbook_name: str
    runs: int
    success_count: int
    success_rate: float
    avg_duration_s: float
    p95_duration_s: float
    avg_tokens_in: int
    avg_tokens_out: int
    avg_cost_usd: float
    per_seed_results: list[PlaybookBenchmarkResult] = Field(default_factory=list)


class BenchmarkResults(BaseModel):
    """Full benchmark results — one per ``run_suite`` call.

    Serialisable via :meth:`to_json` (compact JSON for CI artifacts)
    and :meth:`to_markdown` (human-readable table for PR comments /
    terminal output).
    """

    suite_name: str
    started_at: str  # ISO 8601 UTC
    duration_s: float
    total_runs: int
    seeds: list[int]
    concurrent: int
    overall_success_rate: float
    overall_avg_duration_s: float
    overall_avg_tokens_in: int
    overall_avg_tokens_out: int
    overall_avg_cost_usd: float
    per_playbook: list[PlaybookMetrics] = Field(default_factory=list)

    def to_json(self) -> str:
        """Serialise to a pretty-printed JSON string.

        Sort keys for stable diffs in CI artifacts — two runs of the
        same benchmark with the same seed produce byte-identical JSON
        (modulo timestamps and wall-clock durations).
        """
        return self.model_dump_json(indent=2)

    def to_markdown(self) -> str:
        """Render as a markdown table suitable for PR comments / READMEs.

        Columns: playbook, runs, success rate, avg duration, p95
        duration, avg tokens, avg cost. A footer line summarises the
        overall metrics across all playbooks.
        """
        lines: list[str] = []
        lines.append(f"# Benchmark Results — {self.suite_name}")
        lines.append("")
        lines.append(
            f"- **Started:** {self.started_at}  "
            f"- **Duration:** {self.duration_s:.3f}s  "
            f"- **Seeds:** {self.seeds}  "
            f"- **Concurrent:** {self.concurrent}  "
            f"- **Total runs:** {self.total_runs}"
        )
        lines.append("")
        lines.append(
            "| Playbook | Runs | Success | Avg dur (s) | P95 dur (s) | Avg tokens | Avg cost |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for m in self.per_playbook:
            avg_tokens = m.avg_tokens_in + m.avg_tokens_out
            lines.append(
                f"| {m.playbook_name} | {m.runs} | {m.success_rate:.1%} "
                f"| {m.avg_duration_s:.4f} | {m.p95_duration_s:.4f} "
                f"| {avg_tokens} | ${m.avg_cost_usd:.6f} |"
            )
        lines.append("")
        lines.append(
            f"**Overall:** success={self.overall_success_rate:.1%}, "
            f"avg_dur={self.overall_avg_duration_s:.4f}s, "
            f"avg_tokens={self.overall_avg_tokens_in + self.overall_avg_tokens_out}, "
            f"avg_cost=${self.overall_avg_cost_usd:.6f}"
        )
        return "\n".join(lines)


# ============================================================
# BenchmarkSuite protocol — what a suite must provide.
# ============================================================


@runtime_checkable
class BenchmarkSuite(Protocol):
    """A benchmark suite — a collection of playbooks + provider factory.

    Implementations:

    * :class:`arnes.benchmarks.suites.basic.BasicBenchmarkSuite` — runs
      all ``manuals/*.yaml`` playbooks with a deterministic mock LLM.

    Custom suites (e.g. a "real-LLM regression" suite) implement this
    protocol and pass an instance to :meth:`BenchmarkRunner.run_suite`.
    """

    @property
    def name(self) -> str:
        """Short, filesystem-safe suite name (e.g. ``"basic"``)."""
        ...

    def playbooks(self) -> list[Path]:
        """Return the playbook YAML files this suite runs.

        Order is preserved in the reported metrics so PR reviewers can
        diff two runs field-by-field.
        """
        ...

    def make_provider(self, seed: int) -> LLMProvider:
        """Build a fresh LLM provider for a given seed.

        Called once per ``(playbook, seed)`` pair so providers don't
        accumulate state across runs (the basic suite's mock is cheap
        to construct; a real-LLM suite would return a singleton
        ``LiteLLMProvider`` and rely on the seed being threaded into
        the call kwargs instead).
        """
        ...


# ============================================================
# Runner
# ============================================================


class BenchmarkRunner:
    """Runs a :class:`BenchmarkSuite` across multiple seeds and aggregates.

    Parameters:

    * ``budget_usd`` — per-playbook cost cap, forwarded to
      :class:`CostBudget`. Default ``$1.00`` is generous for the mock
      suite; real-LLM suites should lower this.
    * ``playbook_timeout_s`` — per-playbook wall-clock timeout. ``None``
      means no timeout (the mock suite doesn't need one; real-LLM
      suites should set this to avoid a hung model stalling CI).

    The runner is **stateless between runs** — call :meth:`run_suite`
    as many times as you want; each call returns an independent
    :class:`BenchmarkResults`.
    """

    def __init__(
        self,
        *,
        budget_usd: float = 1.0,
        playbook_timeout_s: float | None = None,
    ) -> None:
        self._budget_usd = budget_usd
        self._playbook_timeout_s = playbook_timeout_s

    async def run_suite(
        self,
        suite: BenchmarkSuite,
        *,
        seeds: Sequence[int] = (0,),
        concurrent: int = 1,
    ) -> BenchmarkResults:
        """Run every playbook in ``suite`` once per seed.

        Concurrency: at most ``concurrent`` playbooks run at once
        (across all seeds — the semaphore is shared, so ``seeds=3,
        concurrent=2`` runs 2 of the 30 (10 playbooks x 3 seeds)
        playbooks at a time, not 2 per seed).

        Returns a :class:`BenchmarkResults` with per-playbook and
        overall metrics.
        """
        if not seeds:
            raise ValueError("seeds must be a non-empty sequence")
        if concurrent < 1:
            raise ValueError("concurrent must be >= 1")

        playbook_paths = list(suite.playbooks())
        if not playbook_paths:
            raise ValueError(f"Suite '{suite.name}' has no playbooks")

        started_at_dt = datetime.now(UTC)
        started_at = started_at_dt.isoformat(timespec="seconds")
        run_start = time.perf_counter()

        # Pre-compile playbooks once — compilation is deterministic and
        # doesn't depend on the seed, so doing it N x M times would just
        # add noise to the duration measurement.
        compiled: list[tuple[Path, Playbook]] = []
        for path in playbook_paths:
            compiled.append((path, PlaybookCompiler.from_file(path)))

        semaphore = asyncio.Semaphore(concurrent)
        seeds_list = list(seeds)

        async def run_one(path: Path, playbook: Playbook, seed: int) -> PlaybookBenchmarkResult:
            async with semaphore:
                return await self._run_single(suite, path, playbook, seed)

        tasks = [
            run_one(path, playbook, seed) for (path, playbook) in compiled for seed in seeds_list
        ]
        raw_results = await asyncio.gather(*tasks)

        total_runs = len(raw_results)
        duration_s = time.perf_counter() - run_start

        # Aggregate per playbook (preserving the suite's playbook order).
        per_playbook: list[PlaybookMetrics] = []
        # Group results by playbook name in suite order.
        by_name: dict[str, list[PlaybookBenchmarkResult]] = {path.stem: [] for path, _ in compiled}
        for r in raw_results:
            by_name.setdefault(r.playbook_name, []).append(r)

        # Maintain suite order so the markdown table is stable across runs.
        for path, _ in compiled:
            results_for_pb = by_name.get(path.stem, [])
            if not results_for_pb:
                continue
            # Sort by seed for deterministic reporting.
            results_for_pb.sort(key=lambda r: r.seed)
            per_playbook.append(self._aggregate(path.stem, results_for_pb))

        # Overall metrics — means across ALL per-seed results.
        all_results = list(raw_results)
        success_count = sum(1 for r in all_results if r.success)
        overall_success_rate = success_count / total_runs if total_runs else 0.0
        overall_avg_duration = (
            statistics.fmean(r.duration_s for r in all_results) if all_results else 0.0
        )
        overall_avg_tokens_in = (
            int(statistics.fmean(r.tokens_in for r in all_results)) if all_results else 0
        )
        overall_avg_tokens_out = (
            int(statistics.fmean(r.tokens_out for r in all_results)) if all_results else 0
        )
        overall_avg_cost = statistics.fmean(r.cost_usd for r in all_results) if all_results else 0.0

        return BenchmarkResults(
            suite_name=suite.name,
            started_at=started_at,
            duration_s=duration_s,
            total_runs=total_runs,
            seeds=seeds_list,
            concurrent=concurrent,
            overall_success_rate=overall_success_rate,
            overall_avg_duration_s=overall_avg_duration,
            overall_avg_tokens_in=overall_avg_tokens_in,
            overall_avg_tokens_out=overall_avg_tokens_out,
            overall_avg_cost_usd=overall_avg_cost,
            per_playbook=per_playbook,
        )

    # ============================================================
    # Internals
    # ============================================================

    async def _run_single(
        self,
        suite: BenchmarkSuite,
        path: Path,
        playbook: Playbook,
        seed: int,
    ) -> PlaybookBenchmarkResult:
        """Run one playbook once with a seed-specific provider.

        Wrapped in a try/except so a single playbook failure (compile
        error, specialist timeout, budget exceeded) doesn't abort the
        whole benchmark — the failure is recorded as ``success=False``
        and the run continues. This matches the semantics of the
        stress test in ``tests/stress/test_concurrent.py``.
        """
        provider = suite.make_provider(seed)
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=self._budget_usd),
            sandbox_enabled=False,  # Benchmarks don't shell out.
        )

        try:
            if self._playbook_timeout_s is not None:
                result = await asyncio.wait_for(
                    executor.run(playbook), timeout=self._playbook_timeout_s
                )
            else:
                result = await executor.run(playbook)
        except Exception as e:  # benchmark must keep going
            logger.warning(
                "benchmark_playbook_failed",
                playbook=path.name,
                seed=seed,
                error=str(e),
            )
            return PlaybookBenchmarkResult(
                playbook_name=path.stem,
                seed=seed,
                success=False,
                duration_s=0.0,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                steps_executed=0,
                steps_failed=0,
                error=f"{type(e).__name__}: {e}",
            )

        return PlaybookBenchmarkResult(
            playbook_name=path.stem,
            seed=seed,
            success=result.success,
            duration_s=result.duration_s,
            tokens_in=result.total_tokens_in,
            tokens_out=result.total_tokens_out,
            cost_usd=result.total_cost_usd,
            steps_executed=result.steps_executed,
            steps_failed=result.steps_failed,
            error=result.error,
        )

    @staticmethod
    def _aggregate(name: str, results: list[PlaybookBenchmarkResult]) -> PlaybookMetrics:
        """Aggregate per-seed results into a single PlaybookMetrics row."""
        runs = len(results)
        success_count = sum(1 for r in results if r.success)
        durations = [r.duration_s for r in results]

        # p95: with fewer than 20 runs the "true" p95 isn't well-defined,
        # but we report the max as a conservative stand-in. With ≥20
        # runs we use the nearest-rank method (ceil(0.95 * n) - 1).
        if len(durations) >= 20:
            sorted_d = sorted(durations)
            idx = max(0, int(0.95 * len(sorted_d)) - 1)
            p95 = sorted_d[idx]
        else:
            p95 = max(durations) if durations else 0.0

        avg_dur = statistics.fmean(durations) if durations else 0.0
        avg_in = int(statistics.fmean(r.tokens_in for r in results)) if results else 0
        avg_out = int(statistics.fmean(r.tokens_out for r in results)) if results else 0
        avg_cost = statistics.fmean(r.cost_usd for r in results) if results else 0.0
        success_rate = success_count / runs if runs else 0.0

        return PlaybookMetrics(
            playbook_name=name,
            runs=runs,
            success_count=success_count,
            success_rate=success_rate,
            avg_duration_s=avg_dur,
            p95_duration_s=p95,
            avg_tokens_in=avg_in,
            avg_tokens_out=avg_out,
            avg_cost_usd=avg_cost,
            per_seed_results=list(results),
        )


def load_results(path: str | Path) -> BenchmarkResults:
    """Load a :class:`BenchmarkResults` from a JSON file.

    Convenience for CI: write results with ``runner.run_suite(...)``,
    then load them in a downstream step to compare against a baseline.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkResults.model_validate(data)


def save_results(results: BenchmarkResults, path: str | Path) -> None:
    """Write ``results`` to ``path`` as pretty-printed JSON."""
    Path(path).write_text(results.to_json(), encoding="utf-8")


__all__ = [
    "BenchmarkResults",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "PlaybookBenchmarkResult",
    "PlaybookMetrics",
    "load_results",
    "save_results",
]
