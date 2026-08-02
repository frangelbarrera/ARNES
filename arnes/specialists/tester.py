"""@tester — writes and runs tests."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_TESTER_SYSTEM_PROMPT = """You are @tester, a QA engineer who writes comprehensive tests and runs them.

Your job:
1. Read the code under test.
2. Identify edge cases, happy paths, error paths.
3. Write tests (unit, integration as appropriate).
4. Run the tests.
5. Report results.

Rules:
- Cover happy path + at least 2 edge cases + 1 error case per function.
- Use the project's existing test framework (pytest, jest, etc.).
- If a test fails, analyze the failure and report whether it's a bug in the code or the test.
- Don't write trivial tests (e.g. `assert add(1, 1) == 2` for a function called `add`).
- Mock external dependencies.

Return JSON matching this schema:
{
  "test_files": [
    {
      "path": "tests/test_foo.py",
      "content": "..."
    }
  ],
  "test_results": {
    "passed": 5,
    "failed": 1,
    "skipped": 0,
    "failures": [
      {
        "test": "test_foo_edge_case",
        "error": "...",
        "is_bug": true
      }
    ]
  },
  "coverage_pct": 87.5,
  "summary": "..."
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types for the nested TestResults / TestFailure models,
# which the weak JSON-schema `output_schema` check cannot do.
# ============================================================


class TesterFile(BaseModel):
    """A single test file produced by the tester."""

    path: str
    content: str


class TestFailure(BaseModel):
    """A single test failure record."""

    test: str
    error: str
    is_bug: bool = False


class TestResults(BaseModel):
    """Aggregate results of running the test suite."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[TestFailure] = Field(default_factory=list)


class TesterOutput(BaseModel):
    """Structured output for the @tester specialist."""

    test_files: list[TesterFile] = Field(default_factory=list)
    test_results: TestResults = Field(default_factory=TestResults)
    summary: str
    coverage_pct: float | None = None


class Tester(Specialist):
    """@tester — writes comprehensive tests, runs them, reports results with coverage."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@tester",
        description="Writes comprehensive tests, runs them, reports results with coverage.",
        system_prompt=_TESTER_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write", "shell"],
        output_schema={
            "type": "object",
            "required": ["test_files", "test_results", "summary"],
        },
        # Strong validation: pydantic validates nested TestResults /
        # TestFailure models (types + required fields) — a malformed
        # payload like `test_results: "ok"` or a failure missing `test`
        # is rejected here even though it would slip past the weak
        # JSON-schema `required`-fields check.
        pydantic_model=TesterOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
