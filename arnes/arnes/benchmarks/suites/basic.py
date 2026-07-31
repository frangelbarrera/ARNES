"""Basic benchmark suite — runs all ``manuals/*.yaml`` with a seeded mock LLM.

The mock provider (:class:`SeededMockLLMProvider`) is **deterministic
per seed**:

* same seed + same playbook ⇒ same tokens_in, tokens_out, and content
* different seed ⇒ different tokens_out (varies a padding field's
  length) so multi-seed runs produce statistically distinguishable
  metrics

This lets ``tests/test_benchmark.py`` assert that
``runner.run_suite(suite, seeds=(0, 1))`` produces different
``avg_tokens_out`` than ``runner.run_suite(suite, seeds=(0, 0))``
without paying for real LLM calls.

The suite discovers playbooks from ``manuals/`` relative to the
repository root (the directory containing the ``arnes/`` package).
This matches the convention used by ``arnes list playbooks`` and
``tests/integration/test_e2e.py::test_real_playbook_files_compile_and_run``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

# ============================================================
# Seeded mock LLM provider
# ============================================================


# Per-specialist schema-valid responses. Mirrors the contract used by
# ``tests/integration/test_e2e.py::SchemaValidMockProvider`` and
# ``arnes.cli.main._SchemaValidMockLLMProvider`` so the same playbooks
# run successfully against this mock.
_SPECIALIST_RESPONSES: dict[str, dict[str, Any]] = {
    "@planner": {
        "steps": [{"id": "s1", "specialist": "@coder", "input": {}}],
    },
    "@coder": {
        "files": [
            {
                "path": "out.py",
                "language": "python",
                "content": "# benchmark mock output\npass\n",
            }
        ],
        "summary": "Mock implementation for benchmark",
        "assumptions": [],
        "warnings": [],
    },
    "@reviewer": {
        "verdict": "approve",
        "issues": [],
        "summary": "Mock review: looks good",
    },
    "@tester": {
        "test_files": [{"path": "test_mock.py", "content": "def test_mock():\n    pass\n"}],
        "test_results": {
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "failures": [],
        },
        "summary": "Mock tests pass",
        "coverage_pct": 100.0,
    },
    "@debugger": {
        "root_cause": "Mock root cause identified",
        "confidence": 0.95,
        "fix": {
            "file": "src/app.py",
            "line": 42,
            "original": "broken()",
            "fixed": "fixed()",
            "explanation": "Mock fix applied",
        },
        "verification": "Run tests to verify",
        "alternative_causes": [],
    },
}


class SeededMockLLMProvider(LLMProvider):
    """Schema-valid mock LLM with seed-dependent output length.

    Used by :class:`BasicBenchmarkSuite` to produce statistically
    distinguishable benchmark results across seeds without paying for
    real LLM calls.

    Contract:

    * Detects which specialist is being invoked from the system prompt
      (same heuristic as ``_SchemaValidMockLLMProvider`` in
      ``arnes/cli/main.py``).
    * Returns the specialist's schema-valid JSON response with one
      extra field ``_benchmark_seed`` whose string value's length
      scales with ``seed``. Pydantic specialist models don't forbid
      extra fields by default, so this field is accepted silently and
      the response validates.
    * ``tokens_in`` is computed from the input messages (4 chars ≈ 1
      token, same heuristic as :class:`MockLLMProvider`).
    * ``tokens_out`` is computed from the response content — because
      the ``_benchmark_seed`` padding varies with seed, ``tokens_out``
      varies with seed too. This is what makes multi-seed runs
      distinguishable.
    * ``cost_usd`` is always ``0.0`` (mock is free) — the benchmark
      reports it for parity with real-LLM suites, but it's expected
      to be flat at $0.

    Reproducibility: same ``seed`` + same ``messages`` ⇒ byte-identical
    response. The provider holds no mutable state between calls
    (``call_count`` is the only mutation and is not read by callers).
    """

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock-benchmark",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1

        # Detect specialist from system prompt
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        # Find the matching specialist response (default = generic).
        base: dict[str, Any] = {"result": "mock benchmark output"}
        for specialist_name, response in _SPECIALIST_RESPONSES.items():
            if specialist_name in sys_content:
                base = response
                break

        # Build a seed-dependent payload. We add a ``_benchmark_seed``
        # field whose string value's length grows with the seed — this
        # makes ``tokens_out`` vary across seeds so multi-seed runs
        # produce distinguishable metrics.
        #
        # Padding length: (seed * 17) mod 200 — gives 0..199 chars,
        # different for each distinct seed (until seed wraps at 200/17).
        data: dict[str, Any] = dict(base)
        padding_len = (self.seed * 17) % 200
        data["_benchmark_seed"] = f"seed-{self.seed}-" + ("x" * padding_len)

        content = json.dumps(data, separators=(",", ":"))

        tokens_in = sum(len(m.content) // 4 for m in messages)
        tokens_out = len(content) // 4

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,  # Mock is always free.
                model=model,
                cached=False,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock-benchmark"]

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock-benchmark",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Yield the full response in a single chunk.

        Matches the ``MockLLMProvider.stream_complete`` contract — real
        token-by-token streaming isn't needed for benchmarks (we only
        care about aggregate metrics), and yielding the whole response
        at once keeps the mock deterministic and fast.
        """
        response = await self.complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_schema=response_schema,
            **kwargs,
        )
        yield response


# ============================================================
# Basic suite
# ============================================================


def _default_manuals_dir() -> Path:
    """Return the default ``manuals/`` directory.

    Resolves to ``<repo_root>/manuals`` where ``<repo_root>`` is the
    directory containing the ``arnes/`` package (i.e. two parents up
    from this file: ``arnes/benchmarks/suites/basic.py`` →
    ``arnes/benchmarks/`` → ``arnes/`` → repo root).
    """
    return Path(__file__).resolve().parents[3] / "manuals"


class BasicBenchmarkSuite:
    """Runs all ``manuals/*.yaml`` with :class:`SeededMockLLMProvider`.

    The default ``manuals_dir`` is the repo's ``manuals/`` directory
    (auto-discovered via ``__file__``). Callers can override it to
    point at a fixtures directory (e.g. in tests).

    Implements the :class:`arnes.benchmarks.runner.BenchmarkSuite`
    protocol — duck-typed, no inheritance required.
    """

    def __init__(self, manuals_dir: Path | None = None) -> None:
        self._manuals_dir = manuals_dir or _default_manuals_dir()

    @property
    def name(self) -> str:
        """Suite name — filesystem-safe, used in result artifacts."""
        return "basic"

    def playbooks(self) -> list[Path]:
        """Return all ``*.yaml`` playbooks in ``manuals_dir``, sorted.

        Sorted by filename for stable ordering across runs and across
        machines (filesystem ordering is not portable).
        """
        if not self._manuals_dir.exists():
            return []
        return sorted(self._manuals_dir.glob("*.yaml"))

    def make_provider(self, seed: int) -> LLMProvider:
        """Build a fresh seeded mock provider for a given seed.

        A new instance per call so providers don't share ``call_count``
        across runs (makes per-run instrumentation meaningful if a
        suite ever wants to assert on call counts).
        """
        return SeededMockLLMProvider(seed=seed)


__all__ = [
    "BasicBenchmarkSuite",
    "SeededMockLLMProvider",
]
