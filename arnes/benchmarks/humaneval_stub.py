"""HumanEval-style benchmark stub.

ARNES does not ship the real HumanEval dataset (164 problems, OpenAI
non-commercial license — see ``docs/benchmarks.md`` for the rationale).
This module ships a **3-problem stub** that demonstrates the minimum
shape a standard-suite adapter must have to plug into ARNES, plus the
``check`` helper that runs the test assertions against a generated
completion.

The stub is the reference implementation of the integration pattern
documented in ``docs/benchmarks.md`` §4 ("How to add a real
standard-suite integration"). MBPP / SWE-bench / GAIA adapters
should follow the same shape:

- A ``problems()`` method returning a list of dicts with the
  canonical suite fields.
- A ``check(problem, completion)`` method that returns ``True`` /
  ``False`` for a single (problem, completion) pair.
- A ``pass_at_k(results, k)`` helper that computes the suite's
  canonical metric.

The stub is **not** wired into ``arnes benchmark`` — HumanEval
requires a real LLM (the mock LLM cannot generate Python code from
a docstring). Operators who want to run real HumanEval download the
real dataset from https://github.com/openai/human-eval and adapt
this stub.
"""

from __future__ import annotations

from typing import Any

# Three hand-authored HumanEval-style problems. Each carries the
# canonical HumanEval fields: ``task_id``, ``prompt``,
# ``canonical_solution``, ``test``, ``entry_point``. The problems
# are intentionally simple (sorting, fibonacci, parity) so a small
# LLM can solve them and the stub is useful for smoke-testing a
# provider integration.
_HUMANEVAL_STUB_PROBLEMS: list[dict[str, Any]] = [
    {
        "task_id": "HumanEval/0",
        "prompt": (
            "from typing import List\n\n"
            "def sort_numbers(numbers: List[int]) -> List[int]:\n"
            '    """Sort a list of integers in ascending order.\n'
            "\n"
            "    Args:\n"
            "        numbers: List of integers to sort.\n"
            "\n"
            "    Returns:\n"
            "        A new list with the integers in ascending order.\n"
            '    """\n'
        ),
        "canonical_solution": ("    return sorted(numbers)\n"),
        "test": (
            "def check(candidate):\n"
            "    assert candidate([3, 1, 2]) == [1, 2, 3]\n"
            "    assert candidate([]) == []\n"
            "    assert candidate([5]) == [5]\n"
            "    assert candidate([1, 1, 1]) == [1, 1, 1]\n"
            "    assert candidate([-1, 0, 1]) == [-1, 0, 1]\n"
        ),
        "entry_point": "sort_numbers",
    },
    {
        "task_id": "HumanEval/1",
        "prompt": (
            "def fibonacci(n: int) -> int:\n"
            '    """Return the n-th Fibonacci number (0-indexed).\n'
            "\n"
            "    Args:\n"
            "        n: The index in the Fibonacci sequence.\n"
            "\n"
            "    Returns:\n"
            "        The n-th Fibonacci number (fibonacci(0)=0,\n"
            "        fibonacci(1)=1, fibonacci(2)=1, ...).\n"
            '    """\n'
        ),
        "canonical_solution": (
            "    if n <= 0:\n"
            "        return 0\n"
            "    if n == 1:\n"
            "        return 1\n"
            "    a, b = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        a, b = b, a + b\n"
            "    return b\n"
        ),
        "test": (
            "def check(candidate):\n"
            "    assert candidate(0) == 0\n"
            "    assert candidate(1) == 1\n"
            "    assert candidate(2) == 1\n"
            "    assert candidate(10) == 55\n"
            "    assert candidate(20) == 6765\n"
        ),
        "entry_point": "fibonacci",
    },
    {
        "task_id": "HumanEval/2",
        "prompt": (
            "def is_even(n: int) -> bool:\n"
            '    """Return True if n is even, False otherwise.\n'
            "\n"
            "    Args:\n"
            "        n: The integer to test.\n"
            "\n"
            "    Returns:\n"
            "        True if n is even, False otherwise.\n"
            '    """\n'
        ),
        "canonical_solution": ("    return n % 2 == 0\n"),
        "test": (
            "def check(candidate):\n"
            "    assert candidate(0) is True\n"
            "    assert candidate(1) is False\n"
            "    assert candidate(2) is True\n"
            "    assert candidate(-1) is False\n"
            "    assert candidate(-2) is True\n"
        ),
        "entry_point": "is_even",
    },
]


class HumanEvalStub:
    """3-problem HumanEval-style stub.

    The shape mirrors the canonical HumanEval dataset: each problem
    has a ``task_id``, a ``prompt`` (function signature + docstring),
    a ``canonical_solution``, a ``test`` (assertions), and an
    ``entry_point`` (function name to call).

    The ``check`` method runs the test assertions against a generated
    completion and returns ``True`` if all assertions pass. The
    execution is sandboxed in a fresh ``exec`` scope — the generated
    code is *not* run in a Docker sandbox because HumanEval tests
    are pure-Python and don't touch the filesystem. (SWE-bench-style
    adapters that *do* touch the filesystem must use a Docker
    sandbox.)

    Production caveat: ``exec`` is dangerous if the generated code
    is untrusted. ARNES's Docker sandbox (Tier-1) is the right
    defence for arbitrary code execution. This stub uses ``exec``
    only because the 3 hand-authored problems above have known-safe
    test assertions. A real HumanEval adapter that runs the full
    164-problem suite should use the Docker sandbox, not ``exec``
    directly.
    """

    def problems(self) -> list[dict[str, Any]]:
        """Return the 3 hand-authored HumanEval-style problems.

        The list is a fresh copy each call so the caller can mutate
        it without affecting the module-level constant.
        """
        return [dict(p) for p in _HUMANEVAL_STUB_PROBLEMS]

    def check(self, problem: dict[str, Any], completion: str) -> bool:
        """Run the test assertions against the generated completion.

        The completion is the LLM-generated code that should define
        the function named in ``problem["entry_point"]``. The test
        assertions in ``problem["test"]`` are exec'd in a fresh
        scope with the candidate function bound — same shape as the
        canonical HumanEval runner.

        Returns ``True`` if all assertions pass, ``False`` otherwise.
        Catches ``Exception`` (syntax error, runtime error, assertion
        error) and returns ``False`` — a failure is a failure,
        regardless of cause.
        """
        entry_point = problem["entry_point"]
        test_code = problem["test"]
        # Combined source: the completion (defines the function) +
        # the test code (defines ``check``) + a call to ``check``.
        # ``exec`` runs in a fresh namespace so the candidate function
        # doesn't leak across problems.
        namespace: dict[str, Any] = {}
        try:
            # ``exec`` is required here because HumanEval test
            # assertions are Python source that must be run in the
            # same namespace as the candidate function. This is the
            # same pattern the canonical HumanEval runner uses
            # (github.com/openai/human-eval). The 3 hand-authored
            # problems above have known-safe test assertions; a real
            # HumanEval adapter that runs the full 164-problem suite
            # should use the Docker sandbox (Tier-1) instead of
            # bare ``exec``.
            exec(completion, namespace)  # noqa: S102  # nosec B102 - HumanEval runner pattern
            exec(test_code, namespace)  # noqa: S102  # nosec B102 - HumanEval runner pattern
            check_fn = namespace.get("check")
            candidate = namespace.get(entry_point)
            if check_fn is None or candidate is None:
                return False
            check_fn(candidate)
            return True
        except Exception:
            return False

    def pass_at_k(self, results: list[bool], k: int) -> float:
        """Compute pass@k for a list of per-problem pass/fail results.

        ``results`` is a list of booleans — one per problem (or per
        sample, if you ran the same problem k times). ``pass@k`` is
        the fraction of problems for which at least one of the top-k
        samples passed.

        For the simple case where each problem was run once (k=1),
        this is just ``sum(results) / len(results)``. For k>1, the
        caller should pass a list with ``k`` entries per problem and
        this method will compute the fraction of *problems* (not
        samples) that had at least one pass.
        """
        if not results:
            return 0.0
        if k <= 1:
            return sum(1 for r in results if r) / len(results)
        # For k>1, the caller is expected to pass results in groups
        # of k (one group per problem). We count a problem as passed
        # if any sample in its group passed.
        if len(results) % k != 0:
            # Misaligned — fall back to the k=1 interpretation.
            return sum(1 for r in results if r) / len(results)
        problems_passed = 0
        problems_total = len(results) // k
        for i in range(problems_total):
            group = results[i * k : (i + 1) * k]
            if any(group):
                problems_passed += 1
        return problems_passed / problems_total if problems_total > 0 else 0.0


__all__ = ["HumanEvalStub"]
