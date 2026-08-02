"""TaskTemplate — a domain-specific playbook blueprint.

Each template encodes the institutional knowledge of *how to approach* a
class of task: which specialists to call, in what order, with which tools,
what to ask the user upfront, and what risks to flag.

Templates are consumed by :class:`arnes.proactive.ProactivePlanner` and by
the ``arnes plan`` CLI command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SpecialistStep:
    """One step in a domain playbook.

    The ``specialist`` field is the ``@name`` of the specialist to invoke.
    ``tools`` is the subset of the tool registry to expose to that
    specialist for this step (``None`` means "use the specialist's default
    tool set"). ``purpose`` is a short human-readable description of why
    this specialist is called at this point in the flow.
    """

    specialist: str
    purpose: str
    tools: list[str] | None = None
    input_hint: str = ""


@dataclass(frozen=True)
class TaskTemplate:
    """A complete domain-specific playbook blueprint.

    Attributes:
        name: Canonical template identifier (matches :class:`TaskDomain` value).
        title: Human-readable title for display.
        description: One-paragraph summary of when to use this template.
        specialists: Ordered list of :class:`SpecialistStep` — the execution
            sequence. This is the "action graph" for the domain.
        clarifying_questions: Questions the planner should surface to the
            user before executing, when the request is too vague. Empty list
            means "no clarification needed, proceed".
        domain_context: Extra system-prompt text injected into each
            specialist's context for this run. Encodes domain conventions,
            common pitfalls, reference repos, standard tools, etc.
        risks: Known risks / failure modes for this domain. The planner
            includes these in its risk assessment.
        estimated_duration_h: Rough wall-clock estimate for a typical run.
        suggested_budget_usd: Suggested USD budget cap for a typical run.
    """

    name: str
    title: str
    description: str
    specialists: list[SpecialistStep]
    clarifying_questions: list[str] = field(default_factory=list)
    domain_context: str = ""
    risks: list[str] = field(default_factory=list)
    estimated_duration_h: float = 4.0
    suggested_budget_usd: float = 1.0

    def to_playbook_yaml(
        self,
        name: str = "generated-playbook",
        objective: str = "",
        budget_usd: float | None = None,
    ) -> str:
        """Render this template as an executable ARNES playbook YAML.

        The generated playbook has one step per :class:`SpecialistStep`,
        with ``id`` derived from the specialist name and an ``input`` block
        that references the previous step's output where applicable.
        """
        lines: list[str] = [
            f"# {name}.yaml — generated from template '{self.name}'",
            f"# {self.title}",
            f"# {self.description}",
            "",
            f"name: {name}",
            f"objective: {objective or self.title}",
            f"budget_usd: {budget_usd if budget_usd is not None else self.suggested_budget_usd}",
            "",
            "steps:",
        ]
        prev_id: str | None = None
        for i, step in enumerate(self.specialists, start=1):
            step_id = f"step_{i}_{step.specialist.lstrip('@')}"
            lines.append(f"  - id: {step_id}")
            lines.append(f'    specialist: "{step.specialist}"')
            if step.input_hint:
                input_val = step.input_hint
                if prev_id and "{{" not in input_val:
                    input_val = f"{step.input_hint} Context: {{{{ steps.{prev_id}.output }}}}"
                lines.append("    input:")
                lines.append(f'      task: "{input_val}"')
            elif prev_id:
                lines.append(f'    input: "{{{{ steps.{prev_id}.output }}}}"')
            else:
                lines.append("    input:")
                lines.append('      task: "See domain context in system prompt"')
            if step.tools:
                lines.append(f"    # Tools: {', '.join(step.tools)}")
            if i < len(self.specialists):
                lines.append(f"    requires: [{prev_id}]" if prev_id else "")
            prev_id = step_id
            lines.append("")
        return "\n".join(lines)

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a compact dict suitable for CLI display / JSON output."""
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "specialists": [s.specialist for s in self.specialists],
            "clarifying_questions": self.clarifying_questions,
            "risks": self.risks,
            "estimated_duration_h": self.estimated_duration_h,
            "suggested_budget_usd": self.suggested_budget_usd,
        }
