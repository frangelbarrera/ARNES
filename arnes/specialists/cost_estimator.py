"""@cost-estimator — proactive token, development, and infrastructure cost estimation."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_COST_ESTIMATOR_SYSTEM_PROMPT = """You are @cost-estimator, a senior engineer/analyst who treats every \
estimate as a forecast that will be checked against reality.

Your job:
1. Estimate LLM token costs for a given task — prompt size, expected completion size, calls per task, \
model price per 1K tokens (input + output), cache hit rate where applicable.
2. Calculate development time and cost estimates (engineering hours, rates, ramp-up, code review, \
testing, contingency).
3. Estimate infrastructure and hosting costs (compute, storage, bandwidth, managed services, \
egress, observability tooling) for both steady-state and peak.
4. PROACTIVELY suggest cost optimization strategies — model routing, prompt caching, batching, \
smaller/distilled models, spot/preemptible capacity, reserved instances, tiered storage.

Operating principles:
- Be proactive, not reactive. If a cost line item is suspiciously high or a budget assumption is \
optimistic, flag it as a risk with severity.
- Show every input to every estimate (rates, quantities, assumptions). Opaque numbers are useless.
- Provide best-case, expected, and worst-case ranges — never a single point estimate.
- Distinguish between one-time costs (setup, migration) and recurring costs (monthly run-rate).
- Always include a contingency buffer of at least 15% on engineering estimates.
- Cite current price sheets where possible (vendor docs, public model pricing). If a price is stale, \
say so.
- For LLM costs, distinguish between cached vs uncached tokens (most providers price cached input \
at a discount).

Return JSON matching this schema:
{
  "summary": "Executive summary of total estimated cost",
  "token_costs": {
    "model": "gpt-4o",
    "input_tokens_per_call": 1500,
    "output_tokens_per_call": 800,
    "calls_per_task": 12,
    "input_price_per_1k_usd": 0.0025,
    "output_price_per_1k_usd": 0.01,
    "cache_hit_rate": 0.3,
    "expected_cost_per_task_usd": 0.13,
    "assumptions": ["What we assume about prompt size and call count"]
  },
  "development_costs": {
    "engineering_hours": {
      "best_case": 80,
      "expected": 120,
      "worst_case": 180
    },
    "blended_rate_usd_per_hour": 95,
    "total_cost_usd": {
      "best_case": 7600,
      "expected": 11400,
      "worst_case": 17100
    },
    "contingency_pct": 15,
    "breakdown": [
      {"phase": "design", "hours": 16, "notes": "API design + review"},
      {"phase": "implementation", "hours": 60, "notes": "Core feature"}
    ]
  },
  "infrastructure_costs": {
    "monthly_run_rate_usd": {
      "best_case": 450,
      "expected": 720,
      "worst_case": 1200
    },
    "line_items": [
      {
        "name": "API gateway",
        "provider": "aws",
        "monthly_cost_usd": 120,
        "scaling": "fixed|usage_based",
        "notes": "Per-million-request pricing"
      }
    ],
    "one_time_costs_usd": [
      {"name": "Domain + TLS", "cost_usd": 50}
    ]
  },
  "total_estimates": {
    "one_time_usd": {"best_case": 8000, "expected": 12000, "worst_case": 18500},
    "monthly_recurring_usd": {"best_case": 450, "expected": 720, "worst_case": 1200},
    "per_task_usd": {"best_case": 0.10, "expected": 0.13, "worst_case": 0.20}
  },
  "optimizations": [
    {
      "title": "Route 70% of calls to a smaller model",
      "expected_savings_pct": 45,
      "effort": "low|medium|high",
      "risk": "Slight quality regression on complex prompts",
      "rationale": "Why this optimization is safe"
    }
  ],
  "risks": [
    {
      "severity": "critical|major|minor",
      "description": "What can blow the budget",
      "mitigation": "How to contain the cost"
    }
  ],
  "assumptions": ["All top-level assumptions that drive the numbers above"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (severity, scaling, effort)
# and enforces nested required fields, which the weak
# JSON-schema `output_schema` check cannot do.
# ============================================================


CostSeverity = Literal["critical", "major", "minor"]
CostScaling = Literal["fixed", "usage_based"]
CostEffort = Literal["low", "medium", "high"]


class TokenCosts(BaseModel):
    """LLM token cost estimate for a task."""

    model: str | None = None
    input_tokens_per_call: int | None = None
    output_tokens_per_call: int | None = None
    calls_per_task: int | None = None
    input_price_per_1k_usd: float | None = None
    output_price_per_1k_usd: float | None = None
    cache_hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_cost_per_task_usd: float | None = None
    assumptions: list[str] = Field(default_factory=list)


class EngineeringHours(BaseModel):
    """Best/expected/worst-case engineering hours."""

    best_case: float
    expected: float
    worst_case: float


class CostBreakdownItem(BaseModel):
    """A single phase or line item in the development cost breakdown."""

    phase: str
    hours: float | None = None
    notes: str | None = None


class DevelopmentCosts(BaseModel):
    """Development time and cost estimates."""

    engineering_hours: EngineeringHours | None = None
    blended_rate_usd_per_hour: float | None = None
    total_cost_usd: EngineeringHours | None = None
    contingency_pct: float | None = None
    breakdown: list[CostBreakdownItem] = Field(default_factory=list)


class InfraLineItem(BaseModel):
    """A single infrastructure line item."""

    name: str
    provider: str | None = None
    monthly_cost_usd: float | None = None
    scaling: CostScaling | None = None
    notes: str | None = None


class OneTimeCost(BaseModel):
    """A single one-time cost."""

    name: str
    cost_usd: float


class InfrastructureCosts(BaseModel):
    """Infrastructure and hosting cost estimates."""

    monthly_run_rate_usd: EngineeringHours | None = None
    line_items: list[InfraLineItem] = Field(default_factory=list)
    one_time_costs_usd: list[OneTimeCost] = Field(default_factory=list)


class CostRange(BaseModel):
    """Best/expected/worst-case cost range."""

    best_case: float
    expected: float
    worst_case: float


class TotalEstimates(BaseModel):
    """Total cost estimates aggregated across categories."""

    one_time_usd: CostRange | None = None
    monthly_recurring_usd: CostRange | None = None
    per_task_usd: CostRange | None = None


class CostOptimization(BaseModel):
    """A proactive cost optimization suggestion."""

    title: str
    expected_savings_pct: float | None = None
    effort: CostEffort | None = None
    risk: str | None = None
    rationale: str | None = None


class CostRisk(BaseModel):
    """A cost-related risk."""

    severity: CostSeverity
    description: str
    mitigation: str | None = None


class CostEstimatorOutput(BaseModel):
    """Structured output for the @cost-estimator specialist."""

    summary: str
    token_costs: TokenCosts = Field(default_factory=TokenCosts)
    development_costs: DevelopmentCosts = Field(default_factory=DevelopmentCosts)
    infrastructure_costs: InfrastructureCosts = Field(default_factory=InfrastructureCosts)
    total_estimates: TotalEstimates = Field(default_factory=TotalEstimates)
    optimizations: list[CostOptimization] = Field(default_factory=list)
    risks: list[CostRisk] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class CostEstimator(Specialist):
    """@cost-estimator — estimates token, development, and infrastructure costs with optimization strategies."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@cost-estimator",
        description=(
            "Cost estimation specialist. Estimates LLM token costs, development time/cost, "
            "and infrastructure/hosting costs. Proactively suggests cost optimization strategies."
        ),
        system_prompt=_COST_ESTIMATOR_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write"],
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "token_costs": {"type": "object"},
                "development_costs": {"type": "object"},
                "infrastructure_costs": {"type": "object"},
                "total_estimates": {"type": "object"},
                "optimizations": {"type": "array"},
                "risks": {"type": "array"},
                "assumptions": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates nested TokenCosts /
        # DevelopmentCosts / EngineeringHours / InfrastructureCosts /
        # CostRange / CostOptimization / CostRisk models (types + required
        # fields + enum values) AND enforces cache_hit_rate in [0.0, 1.0]
        # — a malformed `cache_hit_rate: 1.5` is rejected here even though
        # it would slip past the weak JSON-schema `required`-fields check.
        pydantic_model=CostEstimatorOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
