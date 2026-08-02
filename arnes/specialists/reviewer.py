"""@reviewer — reviews code for quality, security, and correctness."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_REVIEWER_SYSTEM_PROMPT = """You are @reviewer, a senior code reviewer with 15+ years of experience.

Your job:
1. Read the code (file paths or inline content).
2. Review for: correctness, security, performance, readability, idioms.
3. Identify issues and rank by severity (critical, major, minor, nit).
4. Suggest specific fixes with code snippets.

Rules:
- Be specific. "Improve performance" is bad. "Replace O(n²) loop with O(n) dict lookup" is good.
- Cite line numbers or code blocks.
- Don't suggest stylistic changes unless they violate project conventions.
- Flag security issues explicitly (SQL injection, XSS, path traversal, etc.).
- If the code is good, say so. Don't invent issues.

Return JSON matching this schema:
{
  "verdict": "approve|request_changes|reject",
  "issues": [
    {
      "severity": "critical|major|minor|nit",
      "file": "src/foo.py",
      "line": 42,
      "issue": "Description",
      "suggestion": "Code or text suggestion"
    }
  ],
  "summary": "Overall assessment"
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — used as the strong `pydantic_model`
# validator on SpecialistConfig. This is the demonstration that
# the `pydantic_model` field on SpecialistConfig is actually
# plumbed end-to-end: stronger than the JSON-schema `output_schema`
# check (which only verifies required fields exist) because pydantic
# also validates types and enum values.
# ============================================================


Severity = Literal["critical", "major", "minor", "nit"]
Verdict = Literal["approve", "request_changes", "reject"]


class ReviewerIssue(BaseModel):
    """A single issue found during code review."""

    severity: Severity
    file: str
    line: int | None = None
    issue: str
    suggestion: str | None = None


class ReviewerOutput(BaseModel):
    """Structured output for the @reviewer specialist."""

    verdict: Verdict
    issues: list[ReviewerIssue] = Field(default_factory=list)
    summary: str


class Reviewer(Specialist):
    """@reviewer — reviews code for correctness, security, performance, and readability."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@reviewer",
        description="Reviews code for correctness, security, performance, and readability.",
        system_prompt=_REVIEWER_SYSTEM_PROMPT,
        tools=["fs_read"],
        output_schema={
            "type": "object",
            "required": ["verdict", "issues", "summary"],
            "properties": {
                "verdict": {"type": "string", "enum": ["approve", "request_changes", "reject"]},
                "issues": {"type": "array"},
                "summary": {"type": "string"},
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (verdict / severity), so a malformed `verdict: "ok"` is rejected
        # here even though it would slip past the weak JSON-schema check.
        pydantic_model=ReviewerOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
