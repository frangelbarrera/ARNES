"""
ARNES Proactive Planner — auto-generates playbooks from natural language.

When a user asks "build me a dating app", ARNES doesn't just start coding.
It:
1. Calls @market-analyst to research market viability
2. Calls @cost-estimator to estimate token/dev/infra costs
3. Calls @product-manager to define requirements
4. Calls @planner to create a step-by-step execution plan
5. Generates a YAML playbook that the user can review, modify, and run

This makes ARNES proactive rather than reactive — it advises before executing.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMMessage, LLMProvider
from arnes.middleware import build_middleware_stack
from arnes.specialists.base import get_default_specialist_registry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)


PROACTIVE_PLANNER_PROMPT = """You are the ARNES Proactive Planner.

Your job: When a user describes what they want to build (e.g., "build a dating app for the Play Store"),
you DON'T just start coding. You think like a senior consultant:

1. RESEARCH: What does the market look like? Is this viable?
2. ESTIMATE: How much will it cost in tokens, dev time, and infrastructure?
3. PLAN: What specialists are needed? What's the execution order?
4. WARN: What risks should the user know about BEFORE starting?
5. PROPOSE: Generate a YAML playbook the user can review and approve.

You have access to 12 specialists:
- @researcher: Web/market research
- @market-analyst: Market analysis, competitor research, pricing
- @cost-estimator: Token/dev/infra cost estimation
- @product-manager: Product requirements, user stories, roadmap
- @planner: Task decomposition
- @coder: Code writing
- @reviewer: Code review
- @tester: Test writing and execution
- @debugger: Bug diagnosis
- @security-auditor: Security auditing
- @devops-engineer: Deployment, CI/CD, infrastructure
- @data-scientist: Data analysis, ML evaluation

Return JSON with this schema:
{
  "viability_assessment": {
    "score": 0-10,
    "market_size": "string",
    "competition_level": "low|medium|high|saturated",
    "recommendation": "proceed|proceed_with_caution|pivot|abort"
  },
  "cost_estimate": {
    "token_cost_usd": number,
    "dev_time_hours": number,
    "infra_cost_monthly_usd": number,
    "total_estimated_usd": number
  },
  "risks": ["List of risks the user should know about"],
  "recommended_specialists": ["@researcher", "@market-analyst", ...],
  "proposed_playbook": {
    "name": "string",
    "objective": "string",
    "budget_usd": number,
    "steps": [
      {
        "id": "step-1",
        "specialist": "@researcher",
        "input": {"task": "Research market for..."}
      }
    ]
  },
  "summary": "Brief explanation of what ARNES will do and why"
}

Be proactive. Warn about risks BEFORE the user commits. Estimate costs BEFORE executing.
"""


class ViabilityAssessment(BaseModel):
    score: float = Field(ge=0, le=10)
    market_size: str
    competition_level: str
    recommendation: str


class CostEstimate(BaseModel):
    token_cost_usd: float
    dev_time_hours: float
    infra_cost_monthly_usd: float
    total_estimated_usd: float


class ProposedStep(BaseModel):
    id: str
    specialist: str
    input: dict[str, Any]


class ProposedPlaybook(BaseModel):
    name: str
    objective: str
    budget_usd: float
    steps: list[ProposedStep]


class ProactivePlan(BaseModel):
    viability_assessment: ViabilityAssessment
    cost_estimate: CostEstimate
    risks: list[str]
    recommended_specialists: list[str]
    proposed_playbook: ProposedPlaybook
    summary: str


class ProactivePlanner:
    """Generates proactive plans from natural language requests.

    Usage:
        planner = ProactivePlanner(provider=get_provider("anthropic/claude-sonnet-4-20250514"))
        plan = await planner.plan("Build a dating app for the Play Store")
        if plan.viability_assessment.recommendation == "proceed":
            yaml = planner.to_yaml(plan)
            # User reviews yaml, then: arnes run generated-playbook.yaml
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        budget_usd: float = 5.0,
    ) -> None:
        from arnes.llm.factory import get_provider

        self.provider = provider or get_provider()
        self.budget_usd = budget_usd
        self.specialist_registry = get_default_specialist_registry()
        self.tool_registry = get_default_registry()

    async def plan(self, user_request: str) -> dict[str, Any]:
        """Analyze a user request and return a proactive plan.

        This does NOT execute anything — it researches, estimates, and proposes.
        The user reviews the plan before any code is written.
        """
        messages = [
            LLMMessage(role="system", content=PROACTIVE_PLANNER_PROMPT),
            LLMMessage(
                role="user",
                content=f"User request: {user_request}\n\nAnalyze this request and generate a proactive plan. Remember: research first, estimate costs, warn about risks, then propose a playbook.",
            ),
        ]

        wrapped_provider = build_middleware_stack(
            self.provider,
            enable_cache=False,
            enable_verification=True,
            budget_usd=self.budget_usd,
            output_schema=ProactivePlan.model_json_schema(),
            pydantic_model=ProactivePlan,
        )

        try:
            response = await wrapped_provider.complete(
                messages,
                model="anthropic/claude-sonnet-4-20250514",
                temperature=0.1,
                response_format={"type": "json_object"},
                response_schema=ProactivePlan.model_json_schema(),
            )

            try:
                parsed = json.loads(response.content)
                return dict(parsed)
            except json.JSONDecodeError:
                return {
                    "error": "Failed to parse proactive plan",
                    "raw_response": response.content[:500],
                }

        except Exception as e:
            logger.exception("proactive_plan_failed", error=str(e))
            return {"error": str(e)}

    @staticmethod
    def to_yaml(plan: dict[str, Any]) -> str:
        """Convert a proactive plan's proposed_playbook to YAML format."""
        pb = plan.get("proposed_playbook", {})
        lines = [
            f"name: {pb.get('name', 'generated-playbook')}",
            f"objective: {pb.get('objective', 'Auto-generated by ARNES Proactive Planner')}",
            f"budget_usd: {pb.get('budget_usd', 1.0)}",
            "",
            "steps:",
        ]

        for step in pb.get("steps", []):
            lines.append(f"  - id: {step.get('id', 'step')}")
            lines.append(f'    specialist: "{step.get("specialist", "@planner")}"')
            input_data = step.get("input", {})
            if input_data:
                lines.append("    input:")
                for k, v in input_data.items():
                    lines.append(f'      {k}: "{v}"')
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_plan_summary(plan: dict[str, Any]) -> str:
        """Format a plan as a human-readable summary for CLI output."""
        va = plan.get("viability_assessment", {})
        ce = plan.get("cost_estimate", {})
        risks = plan.get("risks", [])
        specialists = plan.get("recommended_specialists", [])
        summary = plan.get("summary", "")

        lines = [
            "=" * 60,
            "ARNES PROACTIVE PLAN",
            "=" * 60,
            "",
            f"Viability Score: {va.get('score', '?')}/10",
            f"Market Size: {va.get('market_size', '?')}",
            f"Competition: {va.get('competition_level', '?')}",
            f"Recommendation: {va.get('recommendation', '?').upper()}",
            "",
            f"Estimated Token Cost: ${ce.get('token_cost_usd', 0):.2f}",
            f"Estimated Dev Time: {ce.get('dev_time_hours', 0):.0f} hours",
            f"Estimated Infra Cost: ${ce.get('infra_cost_monthly_usd', 0):.2f}/month",
            f"Total Estimated Cost: ${ce.get('total_estimated_usd', 0):.2f}",
            "",
        ]

        if risks:
            lines.append("Risks:")
            for r in risks:
                lines.append(f"  - {r}")
            lines.append("")

        if specialists:
            lines.append(f"Recommended Specialists: {', '.join(specialists)}")
            lines.append("")

        if summary:
            lines.append(f"Summary: {summary}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)
