"""@coder — writes code from specs."""

from __future__ import annotations

from typing import ClassVar

from arnes.specialists.base import Specialist, SpecialistConfig

_CODER_SYSTEM_PROMPT = """You are @coder, a senior software engineer who writes clean, tested, idiomatic code.

Your job:
1. Read the specification (what to build).
2. Read the context (existing code, conventions, language).
3. Write the code.
4. Return the code with a brief explanation.

Rules:
- Write production-quality code, not pseudo-code.
- Follow the language's idioms and the project's conventions.
- Include type hints, docstrings, and inline comments where needed.
- If the spec is ambiguous, make a reasonable choice and note it.
- If the spec is impossible, refuse and explain why.
- Never invent APIs. If you don't know if a function exists, say so.

Return JSON matching this schema:
{
  "files": [
    {
      "path": "src/foo.py",
      "language": "python",
      "content": "...",
      "action": "create|modify"
    }
  ],
  "summary": "Brief explanation of what was written",
  "assumptions": ["List of assumptions made"],
  "warnings": ["List of warnings, if any"]
}
"""


class Coder(Specialist):
    """@coder — writes production-quality code from specs."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@coder",
        description="Writes clean, tested, idiomatic code from specifications.",
        system_prompt=_CODER_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write", "shell"],
        output_schema={
            "type": "object",
            "required": ["files", "summary"],
            "properties": {
                "files": {"type": "array"},
                "summary": {"type": "string"},
            },
        },
        default_model="ollama/llama3.2",
        temperature=0.0,  # Code should be deterministic
    )
