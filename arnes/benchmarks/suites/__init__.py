"""ARNES benchmark suites.

A *suite* is a collection of playbooks + a provider factory. The
:mod:`arnes.benchmarks.runner` module is suite-agnostic; this package
ships the canonical suites used by the CLI and CI.

Available suites:

* :class:`BasicBenchmarkSuite` — runs all ``manuals/*.yaml`` with a
  deterministic seeded mock LLM. Used by ``arnes benchmark`` and the
  ``test_benchmark.py`` test suite.
"""

from __future__ import annotations

from arnes.benchmarks.suites.basic import BasicBenchmarkSuite, SeededMockLLMProvider

__all__ = [
    "BasicBenchmarkSuite",
    "SeededMockLLMProvider",
]
