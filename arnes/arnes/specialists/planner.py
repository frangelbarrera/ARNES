"""@planner — breaks down a task into atomic steps."""

from __future__ import annotations

from typing import ClassVar

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
- If a step might fail, specify what to do if it does (retry, fallback, abort).
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
      "on_failure": "retry|fallback|abort"
    }
  ]
}
"""


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
        default_model="ollama/llama3.2",
        temperature=0.1,  # Slight creativity for planning
    )
