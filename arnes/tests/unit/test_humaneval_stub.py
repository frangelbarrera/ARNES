"""Tests for the HumanEval-style benchmark stub (R16).

The stub at ``arnes.benchmarks.humaneval_stub`` ships 3 hand-authored
HumanEval-style problems and a ``check`` helper. These tests pin:

- The 3 problems exist with the canonical HumanEval fields.
- The ``check`` helper correctly accepts a valid completion and
  rejects an invalid one.
- The ``pass_at_k`` helper computes the right fraction for k=1 and
  k>1.
- The canonical solutions pass their own tests (sanity check).
"""

from __future__ import annotations

import pytest

from arnes.benchmarks.humaneval_stub import HumanEvalStub


class TestHumanEvalStubProblems:
    """Tests for ``HumanEvalStub.problems()``."""

    def test_returns_three_problems(self) -> None:
        """The stub ships exactly 3 hand-authored problems — small enough
        to fit in the repo, large enough to exercise the check loop."""
        stub = HumanEvalStub()
        problems = stub.problems()
        assert len(problems) == 3

    def test_problems_have_canonical_humaneval_fields(self) -> None:
        """Each problem must carry the 5 canonical HumanEval fields:
        ``task_id``, ``prompt``, ``canonical_solution``, ``test``,
        ``entry_point``. A missing field breaks the adapter contract."""
        stub = HumanEvalStub()
        for problem in stub.problems():
            assert "task_id" in problem, f"missing task_id: {problem}"
            assert "prompt" in problem, f"missing prompt: {problem}"
            assert "canonical_solution" in problem
            assert "test" in problem
            assert "entry_point" in problem

    def test_task_ids_follow_humaneval_convention(self) -> None:
        """HumanEval task IDs are ``HumanEval/N`` strings. The stub
        follows the same convention so a real HumanEval adapter can
        drop in without renaming."""
        stub = HumanEvalStub()
        for i, problem in enumerate(stub.problems()):
            assert problem["task_id"] == f"HumanEval/{i}"

    def test_problems_returns_fresh_copy(self) -> None:
        """``problems()`` returns a fresh list of fresh dicts each call —
        callers can mutate without affecting the module-level constant
        or other callers."""
        stub = HumanEvalStub()
        first = stub.problems()
        first[0]["task_id"] = "mutated"
        second = stub.problems()
        assert second[0]["task_id"] == "HumanEval/0"


class TestHumanEvalStubCheck:
    """Tests for ``HumanEvalStub.check()``."""

    @pytest.fixture
    def stub(self) -> HumanEvalStub:
        return HumanEvalStub()

    def test_canonical_solution_passes_its_own_tests(self, stub: HumanEvalStub) -> None:
        """Sanity check: the canonical solution for each problem must
        pass that problem's test assertions. If this fails, the stub
        itself is broken."""
        for problem in stub.problems():
            completion = problem["prompt"] + problem["canonical_solution"]
            assert stub.check(problem, completion), (
                f"Canonical solution failed for {problem['task_id']}"
            )

    def test_check_accepts_valid_alternative_completion(self, stub: HumanEvalStub) -> None:
        """A correct alternative implementation must pass — the checker
        must not be over-fitted to the canonical solution."""
        problem = stub.problems()[0]  # sort_numbers
        alt_completion = (
            "from typing import List\n\n"
            "def sort_numbers(numbers: List[int]) -> List[int]:\n"
            "    result = list(numbers)\n"
            "    result.sort()\n"
            "    return result\n"
        )
        assert stub.check(problem, alt_completion) is True

    def test_check_rejects_broken_completion(self, stub: HumanEvalStub) -> None:
        """An incorrect implementation must fail — the checker must
        actually run the assertions, not just check syntax."""
        problem = stub.problems()[0]  # sort_numbers
        broken_completion = (
            "from typing import List\n\n"
            "def sort_numbers(numbers: List[int]) -> List[int]:\n"
            "    return numbers  # not sorted!\n"
        )
        assert stub.check(problem, broken_completion) is False

    def test_check_rejects_syntax_error(self, stub: HumanEvalStub) -> None:
        """A completion with a syntax error must return ``False``, not
        raise — the checker catches ``Exception`` and converts to
        ``False``."""
        problem = stub.problems()[0]
        syntax_error_completion = "def sort_numbers(:\n    pass\n"
        assert stub.check(problem, syntax_error_completion) is False

    def test_check_rejects_runtime_error(self, stub: HumanEvalStub) -> None:
        """A completion that raises at runtime (e.g. division by zero
        inside the function) must return ``False``."""
        problem = stub.problems()[2]  # is_even
        runtime_error_completion = "def is_even(n: int) -> bool:\n    return 1 / 0 == 0\n"
        assert stub.check(problem, runtime_error_completion) is False

    def test_check_rejects_missing_entry_point(self, stub: HumanEvalStub) -> None:
        """A completion that defines a different function name must
        return ``False`` — the entry_point must be present in the
        exec'd namespace."""
        problem = stub.problems()[2]  # is_even
        wrong_name_completion = "def is_odd(n: int) -> bool:\n    return n % 2 != 0\n"
        assert stub.check(problem, wrong_name_completion) is False


class TestHumanEvalStubPassAtK:
    """Tests for ``HumanEvalStub.pass_at_k()``."""

    @pytest.fixture
    def stub(self) -> HumanEvalStub:
        return HumanEvalStub()

    def test_pass_at_1_with_all_passes(self, stub: HumanEvalStub) -> None:
        """``pass@1`` for a list of all-True results is 1.0."""
        assert stub.pass_at_k([True, True, True], k=1) == 1.0

    def test_pass_at_1_with_all_failures(self, stub: HumanEvalStub) -> None:
        """``pass@1`` for a list of all-False results is 0.0."""
        assert stub.pass_at_k([False, False, False], k=1) == 0.0

    def test_pass_at_1_with_mixed_results(self, stub: HumanEvalStub) -> None:
        """``pass@1`` for 2 passes out of 3 is 2/3."""
        assert stub.pass_at_k([True, False, True], k=1) == 2 / 3

    def test_pass_at_k_with_groups(self, stub: HumanEvalStub) -> None:
        """``pass@k`` with k=2 counts a problem as passed if ANY of its
        k samples passed. Two problems, 2 samples each:
        problem 0: [True, False] -> passed (any True)
        problem 1: [False, False] -> failed
        => pass@2 = 1/2 = 0.5"""
        results = [True, False, False, False]
        assert stub.pass_at_k(results, k=2) == 0.5

    def test_pass_at_k_empty_results(self, stub: HumanEvalStub) -> None:
        """Empty results list -> 0.0 (avoid ZeroDivisionError)."""
        assert stub.pass_at_k([], k=1) == 0.0

    def test_pass_at_k_misaligned_falls_back_to_k1(self, stub: HumanEvalStub) -> None:
        """If ``len(results) % k != 0``, the helper falls back to the
        k=1 interpretation rather than crashing — defensive against
        a caller passing the wrong shape."""
        # 3 results with k=2 -> 3 % 2 != 0 -> fallback to k=1
        # => 2/3
        assert stub.pass_at_k([True, False, True], k=2) == 2 / 3
