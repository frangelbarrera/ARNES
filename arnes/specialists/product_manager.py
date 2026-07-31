"""@product-manager — proactive product strategy, user stories, and roadmap planning."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_PRODUCT_MANAGER_SYSTEM_PROMPT = """You are @product-manager, a senior product manager who turns vague ideas into \
shippable specs and ruthless roadmaps.

Your job:
1. Translate vague product descriptions into concrete product requirements (problem statement, \
target user, success metric, non-goals).
2. Write user stories with clear acceptance criteria (Given/When/Then where possible).
3. Prioritize features by impact vs. effort — explicitly, not by gut feel.
4. PROACTIVELY identify risks, dependencies, and assumptions that could derail delivery.

Operating principles:
- Be proactive, not reactive. If you spot a missing stakeholder, a hidden dependency, or a \
metric that will be gamed, surface it BEFORE work starts.
- Every feature must trace to a measurable outcome. "Improve UX" is not an outcome; \
"increase 7-day retention from 18% to 25%" is.
- Write user stories from the user's perspective, not the team's. "As a user…" not "As a team…".
- Acceptance criteria must be testable. If you can't write a test, the story isn't ready.
- Distinguish must-have vs nice-to-have explicitly. Avoid "everything is P0".
- Call out cross-team dependencies and external blockers — they kill schedules more than code does.
- If the user's brief is internally contradictory, say so and propose a resolution.

Return JSON matching this schema:
{
  "vision": {
    "problem": "The problem being solved, in one sentence",
    "target_user": "Who has this problem",
    "value_proposition": "Why this solution wins",
    "success_metric": "The single number that defines success",
    "non_goals": ["What we are explicitly NOT doing"]
  },
  "user_stories": [
    {
      "id": "US-001",
      "title": "User can reset password via email",
      "as_a": "registered user",
      "i_want": "to reset my password via an email link",
      "so_that": "I can regain access without contacting support",
      "acceptance_criteria": [
        "Given a user with a valid email, When they request a reset, Then an email is sent within 30s",
        "Reset links expire after 15 minutes"
      ],
      "priority": "p0|p1|p2|p3",
      "estimate_points": 5
    }
  ],
  "roadmap": [
    {
      "phase": "MVP",
      "goal": "Validate the core hypothesis",
      "stories": ["US-001", "US-002"],
      "duration_weeks": 4
    }
  ],
  "prioritization": {
    "method": "rice|ice|kano|weighted_impact_effort",
    "top_features": [
      {
        "story_id": "US-001",
        "impact": 8,
        "effort": 3,
        "score": 2.67,
        "rationale": "Blocks all auth-dependent features"
      }
    ]
  },
  "risks": [
    {
      "severity": "critical|major|minor",
      "description": "Risk description",
      "mitigation": "How to mitigate"
    }
  ],
  "dependencies": ["External API X", "Design system v2"],
  "assumptions": ["Assumption we are making without evidence"],
  "open_questions": ["Questions that must be answered before kickoff"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (priority, severity) and
# enforces nested required fields, which the weak JSON-schema
# `output_schema` check cannot do.
# ============================================================


ProductPriority = Literal["p0", "p1", "p2", "p3"]
ProductSeverity = Literal["critical", "major", "minor"]


class ProductVision(BaseModel):
    """The product vision derived from the user's brief."""

    problem: str
    target_user: str
    value_proposition: str | None = None
    success_metric: str | None = None
    non_goals: list[str] = Field(default_factory=list)


class UserStory(BaseModel):
    """A single user story with acceptance criteria."""

    id: str
    title: str
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: ProductPriority = "p2"
    estimate_points: int | None = None


class RoadmapPhase(BaseModel):
    """A single phase in the product roadmap."""

    phase: str
    goal: str | None = None
    stories: list[str] = Field(default_factory=list)
    duration_weeks: int | None = None


class PrioritizedFeature(BaseModel):
    """A prioritized feature with impact/effort scoring."""

    story_id: str
    impact: float
    effort: float
    score: float | None = None
    rationale: str | None = None


class Prioritization(BaseModel):
    """Feature prioritization summary."""

    method: str | None = None
    top_features: list[PrioritizedFeature] = Field(default_factory=list)


class ProductRisk(BaseModel):
    """A risk identified by the product manager."""

    severity: ProductSeverity
    description: str
    mitigation: str | None = None


class ProductManagerOutput(BaseModel):
    """Structured output for the @product-manager specialist."""

    vision: ProductVision
    user_stories: list[UserStory] = Field(default_factory=list)
    roadmap: list[RoadmapPhase] = Field(default_factory=list)
    prioritization: Prioritization = Field(default_factory=Prioritization)
    risks: list[ProductRisk] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ProductManager(Specialist):
    """@product-manager — turns vague ideas into specs, user stories, and prioritized roadmaps."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@product-manager",
        description=(
            "Product strategy specialist. Defines product requirements from vague descriptions, "
            "writes user stories with acceptance criteria, prioritizes features by impact/effort, "
            "and proactively identifies risks and dependencies."
        ),
        system_prompt=_PRODUCT_MANAGER_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write"],
        output_schema={
            "type": "object",
            "required": ["vision"],
            "properties": {
                "vision": {"type": "object"},
                "user_stories": {"type": "array"},
                "roadmap": {"type": "array"},
                "prioritization": {"type": "object"},
                "risks": {"type": "array"},
                "dependencies": {"type": "array"},
                "assumptions": {"type": "array"},
                "open_questions": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates nested ProductVision /
        # UserStory / RoadmapPhase / PrioritizedFeature / ProductRisk
        # models (types + required fields + enum values) — a malformed
        # `priority: "p9"` is rejected here even though it would slip
        # past the weak JSON-schema `required`-fields check.
        pydantic_model=ProductManagerOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
