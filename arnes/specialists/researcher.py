"""@researcher — proactive web/market research before any code is written."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_RESEARCHER_SYSTEM_PROMPT = """You are @researcher, a senior research analyst who de-risks product and engineering \
decisions BEFORE a single line of code is written.

Your job:
1. Search the web for market data, competitor analysis, prior art, and technical feasibility.
2. Evaluate whether the proposed idea is viable — technically, commercially, and operationally.
3. Provide data-backed recommendations, citing sources wherever possible.
4. PROACTIVELY warn about market risks, technical unknowns, and missing evidence.

Operating principles:
- Be proactive, not reactive. If you spot a risk the user did not ask about, surface it.
- Prefer primary sources (vendor docs, official stats, peer-reviewed papers) over secondary blogs.
- Quantify whenever possible (market size, latency, cost, adoption rate). Vague claims are useless.
- If feasibility hinges on an unverified assumption, list it as an explicit `risk` with severity.
- Never fabricate sources, numbers, or URLs. If you don't know, say "unknown" and propose how to find out.
- Distinguish between "we don't know" and "we can't know" — the latter is a hard blocker.

Return JSON matching this schema:
{
  "summary": "One-paragraph executive summary of the findings",
  "feasibility": "high|medium|low|not_viable",
  "findings": [
    {
      "topic": "Market size for X",
      "claim": "The market is $2.3B in 2024 growing at 12% CAGR",
      "evidence": "Source URL or citation",
      "confidence": 0.0-1.0
    }
  ],
  "competitors": [
    {
      "name": "Acme Corp",
      "positioning": "What they do",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "pricing": "Free / $X / mo / unknown"
    }
  ],
  "recommendations": [
    "Concrete, action-oriented recommendation",
    "Another recommendation"
  ],
  "risks": [
    {
      "severity": "critical|major|minor",
      "description": "What can go wrong",
      "mitigation": "How to reduce the risk"
    }
  ],
  "open_questions": ["Questions that must be answered before proceeding"],
  "sources": ["URLs or citations backing the findings above"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (feasibility, severity) and
# enforces the 0.0-1.0 confidence range, which the weak
# JSON-schema `output_schema` check cannot do.
# ============================================================


ResearcherFeasibility = Literal["high", "medium", "low", "not_viable"]
RiskSeverity = Literal["critical", "major", "minor"]


class ResearcherFinding(BaseModel):
    """A single research finding backed by evidence."""

    topic: str
    claim: str
    evidence: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ResearcherCompetitor(BaseModel):
    """A competitor profile discovered during research."""

    name: str
    positioning: str | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    pricing: str | None = None


class ResearcherRisk(BaseModel):
    """A risk identified by the researcher."""

    severity: RiskSeverity
    description: str
    mitigation: str | None = None


class ResearcherOutput(BaseModel):
    """Structured output for the @researcher specialist."""

    summary: str
    feasibility: ResearcherFeasibility
    findings: list[ResearcherFinding] = Field(default_factory=list)
    competitors: list[ResearcherCompetitor] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risks: list[ResearcherRisk] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Researcher(Specialist):
    """@researcher — proactively researches feasibility, market, and competitors before building."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@researcher",
        description=(
            "Proactive web/market research specialist. Searches the web, evaluates "
            "feasibility, profiles competitors, and warns about market risks before "
            "any code is written."
        ),
        system_prompt=_RESEARCHER_SYSTEM_PROMPT,
        tools=["http", "fs_read", "fs_write"],
        output_schema={
            "type": "object",
            "required": ["summary", "feasibility"],
            "properties": {
                "summary": {"type": "string"},
                "feasibility": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "not_viable"],
                },
                "findings": {"type": "array"},
                "competitors": {"type": "array"},
                "recommendations": {"type": "array"},
                "risks": {"type": "array"},
                "open_questions": {"type": "array"},
                "sources": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (feasibility, severity) AND enforces confidence in [0.0, 1.0] —
        # a malformed `feasibility: "great"` is rejected here even though
        # it would slip past the weak JSON-schema `required`-fields check.
        pydantic_model=ResearcherOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
