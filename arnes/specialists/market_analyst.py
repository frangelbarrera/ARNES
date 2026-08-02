"""@market-analyst — proactive market analysis, competitor research, and pricing strategy."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_MARKET_ANALYST_SYSTEM_PROMPT = """You are @market-analyst, a senior market analyst who sizes opportunities, \
profiles competitors, and designs pricing that the market will actually pay.

Your job:
1. Analyze market size (TAM/SAM/SOM), trends, and timing windows.
2. Research competitors: positioning, pricing, traction, strengths/weaknesses, switching costs.
3. Calculate ROI and break-even analysis for the proposed product or feature.
4. Design pricing strategy and PROACTIVELY warn about market saturation or timing risks.

Operating principles:
- Be proactive, not reactive. If the market is saturated, the trend is reversing, or the timing \
window is closing, surface it as a top-line risk — not a footnote.
- Always show your math: TAM = population * penetration * ARPU, with sources for each input.
- Distinguish between bottoms-up and tops-down sizing and prefer bottoms-up.
- Pricing is a hypothesis, not a number. State the assumptions behind each price point.
- Anchor ROI to a payback period, not just a multiple. A 5x return over 10 years is worse than \
2x over 6 months for most businesses.
- Be honest about negative signals (declining search interest, slowing category growth, regulatory risk).
- Never invent market sizes or competitor revenues. If unknown, label as "estimated" with confidence.

Return JSON matching this schema:
{
  "executive_summary": "One-paragraph verdict on the opportunity",
  "market_size": {
    "tam": {"value_usd": 10000000000, "source": "Gartner 2024", "method": "top_down"},
    "sam": {"value_usd": 1200000000, "source": "Bottoms-up from addressable accounts", "method": "bottoms_up"},
    "som": {"value_usd": 24000000, "source": "Year 3 capture target", "method": "bottoms_up"},
    "growth_rate_pct": 12.5,
    "growth_rate_source": "Industry report"
  },
  "trends": [
    {
      "name": "Shift to usage-based pricing",
      "direction": "rising|falling|stable",
      "evidence": "Source citation",
      "implication": "What it means for our product"
    }
  ],
  "competitors": [
    {
      "name": "Acme Corp",
      "positioning": "Enterprise-first SaaS",
      "pricing_model": "per_seat|usage_based|tiered|one_time|freemium",
      "price_range_usd": "49-499/mo",
      "estimated_revenue_usd": 50000000,
      "strengths": ["..."],
      "weaknesses": ["..."],
      "switching_cost": "low|medium|high"
    }
  ],
  "pricing_recommendation": {
    "model": "tiered",
    "tiers": [
      {"name": "Starter", "price_usd": 29, "target": "Solo founders"},
      {"name": "Growth", "price_usd": 99, "target": "Small teams"}
    ],
    "rationale": "Why this pricing wins",
    "assumptions": ["What we assume about willingness to pay"]
  },
  "financials": {
    "break_even_months": 18,
    "payback_months": 14,
    "roi_3yr": 2.4,
    "assumptions": ["CAC $120", "LTV $480", "Gross margin 78%"]
  },
  "risks": [
    {
      "severity": "critical|major|minor",
      "category": "saturation|timing|regulatory|competitive|economic",
      "description": "Risk description",
      "mitigation": "How to mitigate"
    }
  ],
  "recommendation": "go|no_go|conditional_go",
  "conditions": ["If go is conditional, list the conditions that must hold"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (direction, pricing_model,
# switching_cost, severity, category, recommendation) and
# enforces nested required fields, which the weak JSON-schema
# `output_schema` check cannot do.
# ============================================================


MarketDirection = Literal["rising", "falling", "stable"]
PricingModel = Literal["per_seat", "usage_based", "tiered", "one_time", "freemium"]
SwitchingCost = Literal["low", "medium", "high"]
MarketSeverity = Literal["critical", "major", "minor"]
MarketRiskCategory = Literal[
    "saturation",
    "timing",
    "regulatory",
    "competitive",
    "economic",
]
MarketRecommendation = Literal["go", "no_go", "conditional_go"]


class MarketSizeComponent(BaseModel):
    """A single market-size component (TAM, SAM, or SOM)."""

    value_usd: float | None = None
    source: str | None = None
    method: str | None = None


class MarketSize(BaseModel):
    """TAM/SAM/SOM market sizing."""

    tam: MarketSizeComponent = Field(default_factory=MarketSizeComponent)
    sam: MarketSizeComponent = Field(default_factory=MarketSizeComponent)
    som: MarketSizeComponent = Field(default_factory=MarketSizeComponent)
    growth_rate_pct: float | None = None
    growth_rate_source: str | None = None


class MarketTrend(BaseModel):
    """A single market trend."""

    name: str
    direction: MarketDirection
    evidence: str | None = None
    implication: str | None = None


class MarketCompetitor(BaseModel):
    """A competitor profile with pricing context."""

    name: str
    positioning: str | None = None
    pricing_model: PricingModel | None = None
    price_range_usd: str | None = None
    estimated_revenue_usd: float | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    switching_cost: SwitchingCost | None = None


class PricingTier(BaseModel):
    """A single pricing tier."""

    name: str
    price_usd: float | None = None
    target: str | None = None


class PricingRecommendation(BaseModel):
    """Pricing strategy recommendation."""

    model: str | None = None
    tiers: list[PricingTier] = Field(default_factory=list)
    rationale: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class MarketFinancials(BaseModel):
    """ROI and break-even financials."""

    break_even_months: float | None = None
    payback_months: float | None = None
    roi_3yr: float | None = None
    assumptions: list[str] = Field(default_factory=list)


class MarketRisk(BaseModel):
    """A market-level risk identified by the analyst."""

    severity: MarketSeverity
    category: MarketRiskCategory
    description: str
    mitigation: str | None = None


class MarketAnalystOutput(BaseModel):
    """Structured output for the @market-analyst specialist."""

    executive_summary: str
    market_size: MarketSize = Field(default_factory=MarketSize)
    trends: list[MarketTrend] = Field(default_factory=list)
    competitors: list[MarketCompetitor] = Field(default_factory=list)
    pricing_recommendation: PricingRecommendation = Field(default_factory=PricingRecommendation)
    financials: MarketFinancials = Field(default_factory=MarketFinancials)
    risks: list[MarketRisk] = Field(default_factory=list)
    recommendation: MarketRecommendation
    conditions: list[str] = Field(default_factory=list)


class MarketAnalyst(Specialist):
    """@market-analyst — analyzes market size, competitors, pricing, and ROI with proactive risk warnings."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@market-analyst",
        description=(
            "Market analysis specialist. Sizes markets (TAM/SAM/SOM), profiles competitors and "
            "pricing, calculates ROI and break-even, and proactively warns about market "
            "saturation or timing risks."
        ),
        system_prompt=_MARKET_ANALYST_SYSTEM_PROMPT,
        tools=["http", "fs_read", "fs_write"],
        output_schema={
            "type": "object",
            "required": ["executive_summary", "recommendation"],
            "properties": {
                "executive_summary": {"type": "string"},
                "market_size": {"type": "object"},
                "trends": {"type": "array"},
                "competitors": {"type": "array"},
                "pricing_recommendation": {"type": "object"},
                "financials": {"type": "object"},
                "risks": {"type": "array"},
                "recommendation": {
                    "type": "string",
                    "enum": ["go", "no_go", "conditional_go"],
                },
                "conditions": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (direction, pricing_model, switching_cost, severity, category,
        # recommendation) AND enforces nested MarketSize / MarketCompetitor
        # / PricingRecommendation / MarketFinancials required fields —
        # a malformed `recommendation: "maybe"` is rejected here even though
        # it would slip past the weak JSON-schema `required`-fields check.
        pydantic_model=MarketAnalystOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
