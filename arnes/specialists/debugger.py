"""@debugger — diagnoses and fixes bugs."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_DEBUGGER_SYSTEM_PROMPT = """You are @debugger, a senior debugger who diagnoses root causes and proposes minimal fixes.

Your job:
1. Read the error (traceback, log, symptom).
2. Reproduce or understand the failure mode.
3. Identify the root cause (not just the symptom).
4. Propose a minimal fix (don't refactor unrelated code).
5. Verify the fix would work.

Methodology:
- Read the traceback bottom-up to find the failing line.
- Read the failing line's context (function, class, module).
- Form a hypothesis about the root cause.
- Verify by reading related code or running diagnostics.
- Propose a fix that addresses the root cause, not the symptom.

Rules:
- Don't propose "add a try/except" unless catching a specific, expected exception.
- Don't propose "restart the server" or "clear the cache" — find the real cause.
- If you can't diagnose with the given info, list what additional info you need.
- If multiple root causes, address the most likely one first.

Return JSON matching this schema:
{
  "root_cause": "Description of the actual cause",
  "confidence": 0.0-1.0,
  "fix": {
    "file": "src/foo.py",
    "line": 42,
    "original": "broken code",
    "fixed": "fixed code",
    "explanation": "Why this fix addresses the root cause"
  },
  "verification": "How to verify the fix works",
  "alternative_causes": ["Other possible causes, if any"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enforces that the nested `fix` object carries
# all required fields (file, line, original, fixed, explanation) —
# the weak JSON-schema `output_schema` check only verifies top-level
# required fields and would let a missing `fix.line` slip through.
# ============================================================


class DebuggerFix(BaseModel):
    """The minimal fix proposed by the debugger."""

    file: str
    line: int | None = None
    original: str
    fixed: str
    explanation: str


class DebuggerOutput(BaseModel):
    """Structured output for the @debugger specialist."""

    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    fix: DebuggerFix
    verification: str | None = None
    alternative_causes: list[str] = Field(default_factory=list)


class Debugger(Specialist):
    """@debugger — diagnoses root causes of bugs and proposes minimal, verified fixes."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@debugger",
        description="Diagnoses root causes of bugs and proposes minimal, verified fixes.",
        system_prompt=_DEBUGGER_SYSTEM_PROMPT,
        tools=["fs_read", "shell"],
        output_schema={
            "type": "object",
            "required": ["root_cause", "confidence", "fix"],
        },
        # Strong validation: pydantic validates that `confidence` is a
        # float in [0.0, 1.0] AND that the nested `fix` object carries
        # all required fields (file, original, fixed, explanation) —
        # both of which the weak JSON-schema `required`-fields check
        # would miss.
        pydantic_model=DebuggerOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
