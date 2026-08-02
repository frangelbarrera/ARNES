"""@devops-engineer — proactive DevOps for deployment, CI/CD, and infrastructure."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_DEVOPS_ENGINEER_SYSTEM_PROMPT = """You are @devops-engineer, a senior platform engineer who treats infrastructure as \
a product and CI/CD pipelines as the critical path.

Your job:
1. Read the project (language, framework, dependencies, existing infra files).
2. Create production-grade artifacts: Dockerfiles, CI/CD pipelines, Kubernetes manifests, \
Terraform/IaC modules, Helm charts, build scripts.
3. Optimize build and deploy times (layer caching, parallelism, build matrix pruning, \
dependency caching, image size reduction).
4. Set up monitoring, alerting, and observability (logs, metrics, traces, SLOs, runbooks).
5. PROACTIVELY suggest infrastructure improvements (cost, reliability, security, velocity).

Operating principles:
- Be proactive, not reactive. If you spot a reliability risk or a missing safeguard, surface it.
- Production-grade, not tutorial-grade. Multi-stage builds, non-root users, health checks, \
graceful shutdown, pinned digests, least-privilege IAM.
- Pin versions explicitly. Floating `:latest` tags are a defect.
- Prefer reproducible builds and immutable artifacts.
- Always include rollback and zero-downtime strategies (blue/green, canary, rolling).
- Estimate the cost/effort of every suggestion — a "great idea" that costs 3 weeks is a decision, not a default.
- If the project lacks observability, that is itself a critical finding.

Return JSON matching this schema:
{
  "summary": "What was created/modified and why",
  "artifacts": [
    {
      "path": "Dockerfile",
      "language": "dockerfile",
      "content": "...",
      "action": "create|modify",
      "purpose": "Multi-stage production image"
    }
  ],
  "pipeline_stages": [
    {
      "name": "build",
      "tools": ["docker", "uv"],
      "estimated_minutes": 3.5,
      "caching_strategy": "Layer cache + uv cache"
    }
  ],
  "monitoring": {
    "metrics": ["request_latency_p99", "error_rate"],
    "alerts": [
      {
        "name": "high_error_rate",
        "condition": "error_rate > 1% for 5m",
        "severity": "critical"
      }
    ],
    "slos": ["99.9% availability over 30 days"]
  },
  "improvements": [
    {
      "title": "Switch to distroless base image",
      "impact": "high|medium|low",
      "effort": "low|medium|high",
      "rationale": "Reduces image size by 60% and CVE surface"
    }
  ],
  "warnings": ["Risks, caveats, or assumptions the user should know"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (action, impact, effort,
# severity) and enforces nested required fields, which the
# weak JSON-schema `output_schema` check cannot do.
# ============================================================


DevOpsAction = Literal["create", "modify"]
DevOpsImpact = Literal["high", "medium", "low"]
DevOpsEffort = Literal["low", "medium", "high"]
DevOpsAlertSeverity = Literal["critical", "warning", "info"]


class DevOpsArtifact(BaseModel):
    """A single infra artifact produced by the DevOps engineer."""

    path: str
    language: str
    content: str
    action: DevOpsAction = "create"
    purpose: str | None = None


class DevOpsPipelineStage(BaseModel):
    """A single CI/CD pipeline stage."""

    name: str
    tools: list[str] = Field(default_factory=list)
    estimated_minutes: float | None = None
    caching_strategy: str | None = None


class DevOpsAlert(BaseModel):
    """A monitoring alert definition."""

    name: str
    condition: str
    severity: DevOpsAlertSeverity = "warning"


class DevOpsMonitoring(BaseModel):
    """Monitoring, alerting, and SLO configuration."""

    metrics: list[str] = Field(default_factory=list)
    alerts: list[DevOpsAlert] = Field(default_factory=list)
    slos: list[str] = Field(default_factory=list)


class DevOpsImprovement(BaseModel):
    """A proactive infrastructure improvement suggestion."""

    title: str
    impact: DevOpsImpact
    effort: DevOpsEffort
    rationale: str | None = None


class DevOpsEngineerOutput(BaseModel):
    """Structured output for the @devops-engineer specialist."""

    summary: str
    artifacts: list[DevOpsArtifact] = Field(default_factory=list)
    pipeline_stages: list[DevOpsPipelineStage] = Field(default_factory=list)
    monitoring: DevOpsMonitoring = Field(default_factory=DevOpsMonitoring)
    improvements: list[DevOpsImprovement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DevOpsEngineer(Specialist):
    """@devops-engineer — creates Dockerfiles, CI/CD pipelines, k8s manifests, and monitoring."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@devops-engineer",
        description=(
            "DevOps specialist for deployment, CI/CD pipelines, container images, "
            "Kubernetes manifests, and observability. Proactively suggests "
            "infrastructure improvements."
        ),
        system_prompt=_DEVOPS_ENGINEER_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write", "shell"],
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "artifacts": {"type": "array"},
                "pipeline_stages": {"type": "array"},
                "monitoring": {"type": "object"},
                "improvements": {"type": "array"},
                "warnings": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (action, impact, effort, severity) — a malformed `action: "delete"`
        # is rejected here even though it would slip past the weak
        # JSON-schema `required`-fields check.
        pydantic_model=DevOpsEngineerOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
