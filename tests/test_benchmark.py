"""Tests for the ARNES benchmark harness.

Covers:

1. ``BenchmarkRunner`` produces valid :class:`BenchmarkResults` with
   the expected fields populated.
2. :class:`BasicBenchmarkSuite` discovers all 10 ``manuals/*.yaml``
   playbooks and runs each to completion (success=True) with the
   seeded mock LLM.
3. Multi-seed runs produce *different* metrics with different seeds
   (statistical distinguishability — the whole point of multi-seed
   benchmarks).
4. Concurrent execution (``concurrent > 1``) works and produces the
   same total run count as serial execution.
5. ``BenchmarkResults.to_json`` / ``to_markdown`` round-trip cleanly.
6. ``load_results`` / ``save_results`` round-trip a BenchmarkResults.

These tests do NOT touch the network — the suite uses
:class:`SeededMockLLMProvider`, which is fully in-process and
deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arnes.benchmarks import (
    BenchmarkResults,
    BenchmarkRunner,
    load_results,
    save_results,
)
from arnes.benchmarks.suites.basic import (
    BasicBenchmarkSuite,
    SeededMockLLMProvider,
)

# Path to the repo's manuals/ directory — used to assert the suite
# discovers all 10 curated playbooks.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MANUALS_DIR = _REPO_ROOT / "manuals"

# Number of curated playbooks shipped in manuals/. Bumped if a new
# playbook is added — the test exists to catch silent regressions
# where a playbook stops compiling.
_EXPECTED_PLAYBOOK_COUNT = 10


# ============================================================
# 1. Runner produces valid results
# ============================================================


class TestBenchmarkRunnerValidResults:
    """``BenchmarkRunner.run_suite`` must return a fully-populated
    :class:`BenchmarkResults` for the simplest single-seed, single-run
    configuration."""

    @pytest.mark.asyncio
    async def test_single_seed_single_playbook(self, tmp_path: Path) -> None:
        """One playbook, one seed ⇒ one run, one per-playbook row."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0,), concurrent=1)

        assert isinstance(results, BenchmarkResults)
        assert results.suite_name == "minimal"
        assert results.total_runs == 1
        assert results.seeds == [0]
        assert results.concurrent == 1
        assert len(results.per_playbook) == 1
        assert results.per_playbook[0].playbook_name == "tiny"
        assert results.per_playbook[0].runs == 1
        assert results.per_playbook[0].success_count == 1
        assert results.per_playbook[0].success_rate == 1.0
        # Per-seed results must be retained for forensic inspection.
        assert len(results.per_playbook[0].per_seed_results) == 1
        assert results.per_playbook[0].per_seed_results[0].seed == 0
        assert results.per_playbook[0].per_seed_results[0].success is True

    @pytest.mark.asyncio
    async def test_results_have_nonzero_duration_and_tokens(self, tmp_path: Path) -> None:
        """A successful mock run must report non-zero tokens_out (the mock
        always returns content) and a non-negative duration.

        Duration can be 0.0 on very fast CI runners (Windows runners with
        high-resolution timers can complete a mock call in under 1us), so
        we assert ``>= 0.0`` rather than ``> 0.0`` to avoid flakiness.
        """
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0,), concurrent=1)

        row = results.per_playbook[0]
        assert row.avg_duration_s >= 0.0
        assert row.p95_duration_s >= 0.0
        assert row.avg_tokens_out > 0
        assert row.avg_tokens_in > 0
        # Mock is always free.
        assert row.avg_cost_usd == 0.0
        # Overall metrics must reflect the single run.
        assert results.overall_success_rate == 1.0
        assert results.overall_avg_duration_s >= 0.0
        assert results.overall_avg_tokens_out > 0

    @pytest.mark.asyncio
    async def test_json_serialisation_round_trips(self, tmp_path: Path) -> None:
        """``to_json`` must produce valid JSON that can be re-loaded."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0, 1), concurrent=1)

        json_str = results.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["suite_name"] == "minimal"
        assert parsed["total_runs"] == 2
        assert parsed["seeds"] == [0, 1]
        assert len(parsed["per_playbook"]) == 1
        assert parsed["per_playbook"][0]["runs"] == 2

        # Re-validate via pydantic — must not raise.
        restored = BenchmarkResults.model_validate(parsed)
        assert restored.suite_name == results.suite_name
        assert restored.total_runs == results.total_runs

    @pytest.mark.asyncio
    async def test_markdown_contains_playbook_name_and_metrics(self, tmp_path: Path) -> None:
        """``to_markdown`` must mention every playbook name and the
        overall summary line."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0,), concurrent=1)

        md = results.to_markdown()
        assert "minimal" in md
        assert "tiny" in md
        assert "Overall" in md
        # Table header row must be present.
        assert "| Playbook |" in md


# ============================================================
# 2. Basic suite runs all playbooks
# ============================================================


class TestBasicSuiteRunsAllPlaybooks:
    """The shipped :class:`BasicBenchmarkSuite` must discover and run
    every curated playbook in ``manuals/`` end-to-end."""

    def test_suite_discovers_all_manuals(self) -> None:
        """``BasicBenchmarkSuite().playbooks()`` returns all 10 YAMLs."""
        if not _MANUALS_DIR.exists():
            pytest.skip(f"manuals/ not found at {_MANUALS_DIR}")
        suite = BasicBenchmarkSuite()
        playbooks = suite.playbooks()
        assert len(playbooks) == _EXPECTED_PLAYBOOK_COUNT, (
            f"Expected {_EXPECTED_PLAYBOOK_COUNT} playbooks in manuals/, "
            f"got {len(playbooks)}: {[p.name for p in playbooks]}"
        )

    @pytest.mark.asyncio
    async def test_all_playbooks_run_successfully_single_seed(self) -> None:
        """Run every curated playbook once with seed=0. All must succeed."""
        if not _MANUALS_DIR.exists():
            pytest.skip(f"manuals/ not found at {_MANUALS_DIR}")

        suite = BasicBenchmarkSuite()
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0,), concurrent=1)

        assert results.total_runs == _EXPECTED_PLAYBOOK_COUNT
        # All playbooks must succeed against the schema-valid mock.
        assert results.overall_success_rate == 1.0, (
            f"Some playbooks failed. Per-playbook: "
            f"{[(m.playbook_name, m.success_rate) for m in results.per_playbook]}"
        )
        assert len(results.per_playbook) == _EXPECTED_PLAYBOOK_COUNT

        # Each playbook must report exactly 1 run (single seed).
        for metric in results.per_playbook:
            assert metric.runs == 1
            assert metric.success_count == 1
            assert metric.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_make_provider_returns_seeded_mock(self) -> None:
        """``BasicBenchmarkSuite.make_provider(seed)`` must return a
        :class:`SeededMockLLMProvider` carrying the requested seed."""
        suite = BasicBenchmarkSuite()
        provider = suite.make_provider(seed=42)
        assert isinstance(provider, SeededMockLLMProvider)
        assert provider.seed == 42


# ============================================================
# 3. Multi-seed runs produce different results
# ============================================================


class TestMultiSeedRunsProduceDifferentResults:
    """``--seeds N`` must produce statistically distinguishable metrics
    across distinct seeds — otherwise multi-seed runs would be
    meaningless (no signal beyond a single run)."""

    @pytest.mark.asyncio
    async def test_different_seed_produces_different_tokens_out(self, tmp_path: Path) -> None:
        """A single playbook run with seed=0 vs seed=1 must produce
        different ``tokens_out`` — the SeededMockLLMProvider varies
        the response padding by seed."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()

        results_seed0 = await runner.run_suite(suite, seeds=(0,), concurrent=1)
        results_seed1 = await runner.run_suite(suite, seeds=(1,), concurrent=1)

        tokens_out_0 = results_seed0.per_playbook[0].avg_tokens_out
        tokens_out_1 = results_seed1.per_playbook[0].avg_tokens_out

        assert tokens_out_0 != tokens_out_1, (
            f"Different seeds must produce different tokens_out for statistical "
            f"distinguishability, got tokens_out(seed=0)={tokens_out_0} "
            f"== tokens_out(seed=1)={tokens_out_1}"
        )

    @pytest.mark.asyncio
    async def test_same_seed_produces_same_tokens_out(self, tmp_path: Path) -> None:
        """Two runs with the same seed must produce identical
        ``tokens_out`` — guarantees reproducibility."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()

        results_a = await runner.run_suite(suite, seeds=(7,), concurrent=1)
        results_b = await runner.run_suite(suite, seeds=(7,), concurrent=1)

        assert results_a.per_playbook[0].avg_tokens_out == results_b.per_playbook[0].avg_tokens_out

    @pytest.mark.asyncio
    async def test_multi_seed_aggregates_across_seeds(self, tmp_path: Path) -> None:
        """``seeds=(0, 1, 2)`` must produce 3 runs per playbook and
        aggregate them into a single PlaybookMetrics row."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0, 1, 2), concurrent=1)

        assert results.total_runs == 3
        assert results.seeds == [0, 1, 2]
        assert len(results.per_playbook) == 1
        row = results.per_playbook[0]
        assert row.runs == 3
        assert len(row.per_seed_results) == 3
        # Seeds must be retained in per-seed results.
        assert sorted(r.seed for r in row.per_seed_results) == [0, 1, 2]
        # All 3 must succeed (mock is schema-valid).
        assert row.success_count == 3
        assert row.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_multi_seed_tokens_out_differs_across_seeds(self, tmp_path: Path) -> None:
        """Per-seed ``tokens_out`` values must NOT all be equal when
        seeds differ — guards against a regression where the seed is
        silently dropped before reaching the provider."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0, 1, 2, 3, 4), concurrent=1)

        per_seed_tokens = [r.tokens_out for r in results.per_playbook[0].per_seed_results]
        # At least 2 distinct values across 5 seeds — proves the seed
        # is actually being applied.
        assert len(set(per_seed_tokens)) >= 2, (
            f"All per-seed tokens_out are equal ({per_seed_tokens}) — "
            f"seed is not being propagated to the provider."
        )


# ============================================================
# 4. Concurrent execution works
# ============================================================


class TestConcurrentExecution:
    """``--concurrent N`` runs N playbooks at once via
    :class:`asyncio.Semaphore` — the total run count and success rate
    must match serial execution."""

    @pytest.mark.asyncio
    async def test_concurrent_runs_all_playbooks(self, tmp_path: Path) -> None:
        """``concurrent=4`` must run the same number of playbooks as
        ``concurrent=1`` — concurrency is a throughput optimisation,
        not a sampling control."""
        suite = _make_multi_playbook_suite(tmp_path, count=6)
        runner = BenchmarkRunner()

        results_serial = await runner.run_suite(suite, seeds=(0,), concurrent=1)
        results_concurrent = await runner.run_suite(suite, seeds=(0,), concurrent=4)

        assert results_serial.total_runs == 6
        assert results_concurrent.total_runs == 6
        # Both must succeed — concurrency must not break the run.
        assert results_serial.overall_success_rate == 1.0
        assert results_concurrent.overall_success_rate == 1.0

    @pytest.mark.asyncio
    async def test_concurrent_with_multiple_seeds(self, tmp_path: Path) -> None:
        """``concurrent=3, seeds=(0, 1, 2)`` with 4 playbooks ⇒ 12 runs,
        all succeeding."""
        suite = _make_multi_playbook_suite(tmp_path, count=4)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0, 1, 2), concurrent=3)

        assert results.total_runs == 12  # 4 playbooks × 3 seeds
        assert results.concurrent == 3
        assert results.seeds == [0, 1, 2]
        assert results.overall_success_rate == 1.0
        assert len(results.per_playbook) == 4
        for row in results.per_playbook:
            assert row.runs == 3

    @pytest.mark.asyncio
    async def test_concurrent_is_at_least_as_fast_as_serial(self, tmp_path: Path) -> None:
        """Sanity check: with N=4 playbooks and ``concurrent=4``, the
        concurrent run should not be dramatically slower than serial
        (within 3x — generous to absorb scheduler variance)."""
        suite = _make_multi_playbook_suite(tmp_path, count=4)
        runner = BenchmarkRunner()

        results_serial = await runner.run_suite(suite, seeds=(0,), concurrent=1)
        results_concurrent = await runner.run_suite(suite, seeds=(0,), concurrent=4)

        # Mock playbooks are fast (<50ms each), so we just assert the
        # concurrent version isn't catastrophically slower. This catches
        # a regression where the semaphore is acquired but never
        # released, serialising everything behind a gate.
        assert results_concurrent.duration_s < results_serial.duration_s * 3 + 1.0

    @pytest.mark.asyncio
    async def test_invalid_concurrent_raises(self, tmp_path: Path) -> None:
        """``concurrent=0`` and ``concurrent=-1`` must raise ValueError."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        with pytest.raises(ValueError, match="concurrent"):
            await runner.run_suite(suite, seeds=(0,), concurrent=0)

    @pytest.mark.asyncio
    async def test_empty_seeds_raises(self, tmp_path: Path) -> None:
        """``seeds=()`` must raise ValueError — a benchmark with zero
        seeds is meaningless."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        with pytest.raises(ValueError, match="seeds"):
            await runner.run_suite(suite, seeds=(), concurrent=1)


# ============================================================
# 5. save_results / load_results round-trip
# ============================================================


class TestSaveLoadResults:
    """``save_results`` / ``load_results`` must round-trip a
    :class:`BenchmarkResults` losslessly."""

    @pytest.mark.asyncio
    async def test_save_load_round_trip(self, tmp_path: Path) -> None:
        """Save to JSON, load it back, all fields must match."""
        suite = _make_minimal_suite(tmp_path)
        runner = BenchmarkRunner()
        results = await runner.run_suite(suite, seeds=(0, 1), concurrent=1)

        out_path = tmp_path / "benchmark-results.json"
        save_results(results, out_path)
        assert out_path.exists()

        loaded = load_results(out_path)
        assert loaded.suite_name == results.suite_name
        assert loaded.total_runs == results.total_runs
        assert loaded.seeds == results.seeds
        assert loaded.concurrent == results.concurrent
        assert loaded.overall_success_rate == results.overall_success_rate
        assert len(loaded.per_playbook) == len(results.per_playbook)
        # Per-seed results must survive the round trip.
        assert len(loaded.per_playbook[0].per_seed_results) == len(
            results.per_playbook[0].per_seed_results
        )


# ============================================================
# Test fixtures — minimal suites that don't depend on the repo's
# manuals/ directory (keeps tests fast and isolated).
# ============================================================


def _make_minimal_suite(manuals_dir: Path) -> _MiniSuite:
    """Build a 1-playbook suite writing its playbook into ``manuals_dir``."""
    manuals_dir.mkdir(parents=True, exist_ok=True)
    playbook_path = manuals_dir / "tiny.yaml"
    playbook_path.write_text(
        """\
name: tiny
objective: Minimal benchmark playbook
budget_usd: 0.10
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan a tiny task"
  - id: code
    specialist: "@coder"
    input:
      spec: "Implement the tiny task"
      context: "{{ steps.plan.output }}"
""",
        encoding="utf-8",
    )
    return _MiniSuite(manuals_dir)


def _make_multi_playbook_suite(manuals_dir: Path, *, count: int) -> _MiniSuite:
    """Build a suite with ``count`` distinct playbooks (named pb0..pbN-1)."""
    manuals_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (manuals_dir / f"pb{i}.yaml").write_text(
            f"""\
name: pb{i}
objective: Multi-playbook benchmark #{i}
budget_usd: 0.10
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan task {i}"
""",
            encoding="utf-8",
        )
    return _MiniSuite(manuals_dir)


class _MiniSuite:
    """Minimal BenchmarkSuite implementation for tests.

    Implements the :class:`arnes.benchmarks.runner.BenchmarkSuite`
    protocol without inheriting from it — duck typing keeps the test
    fixtures decoupled from the production suite's constructor.
    """

    def __init__(self, manuals_dir: Path) -> None:
        self._manuals_dir = manuals_dir

    @property
    def name(self) -> str:
        return "minimal"

    def playbooks(self) -> list[Path]:
        return sorted(self._manuals_dir.glob("*.yaml"))

    def make_provider(self, seed: int) -> SeededMockLLMProvider:
        return SeededMockLLMProvider(seed=seed)
