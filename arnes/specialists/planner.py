"""@planner — breaks down a task into atomic steps."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_PLANNER_SYSTEM_PROMPT = """You are @planner, a specialist at decomposing complex tasks into atomic, executable steps.

Your job:
1. Read the user's task description.
2. Identify what needs to be done.
3. Break it into 3-7 concrete steps that another specialist can execute.
4. For each step, specify:
   - The specialist who should handle it (@coder, @reviewer, @tester, @debugger, etc.)
   - The exact input that specialist will need
   - Any dependencies on previous steps' outputs
   - Success criteria

Rules:
- Each step must be atomic (one specialist, one action).
- Steps must be ordered by dependency.
- If a step might fail, specify what to do if it does (retry, fallback, abort, continue, skip).
- Be specific. "Review the code" is bad. "Review PR #123 for security vulnerabilities, focusing on auth flows" is good.

Return JSON matching this schema:
{
  "steps": [
    {
      "id": "step-1",
      "specialist": "@coder",
      "input": { ... },
      "depends_on": [],
      "success_criteria": "...",
      "on_failure": "retry|fallback|abort|continue|skip"
    }
  ]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (specialist, on_failure), which the
# weak JSON-schema `output_schema` check cannot do.
# ============================================================


PlannerOnFailure = Literal["retry", "fallback", "abort", "continue", "skip"]


class PlannerStep(BaseModel):
    """A single atomic step produced by the planner."""

    id: str
    specialist: str
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: str | None = None
    on_failure: PlannerOnFailure | None = None


class PlannerOutput(BaseModel):
    """Structured output for the @planner specialist."""

    steps: list[PlannerStep] = Field(default_factory=list)


class Planner(Specialist):
    """@planner — decomposes tasks into atomic, executable steps."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@planner",
        description="Breaks down a task into atomic steps with specialist assignments and dependencies.",
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        tools=[],  # Planner doesn't need tools — it only thinks
        output_schema={
            "type": "object",
            "required": ["steps"],
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "specialist", "input"],
                    },
                }
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (on_failure: retry|fallback|abort|continue|skip) — a malformed value like
        # `on_failure: "delete"` is rejected here even though it would slip
        # past the weak JSON-schema `required`-fields check.
        pydantic_model=PlannerOutput,
        default_model="ollama/llama3.2",
        temperature=0.1,  # Slight creativity for planning
    )
