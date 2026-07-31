"""@security-auditor — proactive security audits of code and configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_SECURITY_AUDITOR_SYSTEM_PROMPT = """You are @security-auditor, an application security engineer who treats every \
codebase as if it is one bug away from a breach.

Your job:
1. Read the code, configs, dependency manifests, and infrastructure files.
2. Scan for OWASP Top 10 vulnerabilities (injection, broken auth, sensitive data exposure, \
XXE, broken access control, security misconfiguration, XSS, insecure deserialization, \
known-vulnerable components, insufficient logging).
3. Check dependency vulnerabilities (CVEs, advisories, pinned vs floating versions).
4. Audit authentication and authorization flows (session handling, password storage, \
JWT handling, OAuth scopes, RBAC/ABAC enforcement, privilege escalation paths).
5. PROACTIVELY flag security risks the user did not ask about. If you see something, say something.

Operating principles:
- Be paranoid and proactive. Default to assuming the attacker is smart and motivated.
- Cite the exact file:line of every finding. "Unsafe SQL in users.py" is bad; \
"users.py:142 — string-formatted SQL on `user_input` enables SQL injection" is good.
- Provide a concrete remediation for every finding, not just a description.
- Rank findings by exploitability * impact, not just CVSS score.
- Distinguish confirmed vulnerabilities from suspicious patterns that warrant a closer look.
- If the audit surface is incomplete (e.g. no tests, no threat model), call it out as a gap.
- Never advise "add a WAF" or "use HTTPS" as a fix for an application-layer bug.

Return JSON matching this schema:
{
  "verdict": "pass|pass_with_warnings|fail",
  "summary": "Executive summary of the security posture",
  "findings": [
    {
      "id": "SEC-001",
      "severity": "critical|high|medium|low|info",
      "category": "owasp_a01_injection | owasp_a02_broken_auth | ...",
      "title": "Short title",
      "file": "src/auth/login.py",
      "line": 142,
      "description": "What is wrong and why it is exploitable",
      "remediation": "Concrete fix (code or config)",
      "cwe": "CWE-89"
    }
  ],
  "dependency_issues": [
    {
      "package": "requests",
      "installed_version": "2.20.0",
      "fixed_in": "2.31.0",
      "advisory": "CVE-2023-32681",
      "severity": "high"
    }
  ],
  "auth_flow_issues": ["List of authentication/authorization issues, if any"],
  "coverage_gaps": ["What you could not audit and why"],
  "recommendations": ["Prioritized, action-oriented hardening steps"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (verdict, severity) and
# enforces required nested fields, which the weak JSON-schema
# `output_schema` check cannot do.
# ============================================================


SecurityVerdict = Literal["pass", "pass_with_warnings", "fail"]
SecuritySeverity = Literal["critical", "high", "medium", "low", "info"]


class SecurityFinding(BaseModel):
    """A single security finding produced by the auditor."""

    id: str
    severity: SecuritySeverity
    category: str
    title: str
    file: str
    line: int | None = None
    description: str
    remediation: str | None = None
    cwe: str | None = None


class DependencyIssue(BaseModel):
    """A vulnerable or outdated dependency."""

    package: str
    installed_version: str | None = None
    fixed_in: str | None = None
    advisory: str | None = None
    severity: SecuritySeverity = "info"


class SecurityAuditorOutput(BaseModel):
    """Structured output for the @security-auditor specialist."""

    verdict: SecurityVerdict
    summary: str
    findings: list[SecurityFinding] = Field(default_factory=list)
    dependency_issues: list[DependencyIssue] = Field(default_factory=list)
    auth_flow_issues: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class SecurityAuditor(Specialist):
    """@security-auditor — audits code, configs, and dependencies for security vulnerabilities."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@security-auditor",
        description=(
            "Security specialist that audits code/configs for OWASP Top 10 vulnerabilities, "
            "dependency CVEs, and broken auth/authz flows. Proactively flags security risks."
        ),
        system_prompt=_SECURITY_AUDITOR_SYSTEM_PROMPT,
        tools=["fs_read", "shell"],
        output_schema={
            "type": "object",
            "required": ["verdict", "summary"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["pass", "pass_with_warnings", "fail"],
                },
                "summary": {"type": "string"},
                "findings": {"type": "array"},
                "dependency_issues": {"type": "array"},
                "auth_flow_issues": {"type": "array"},
                "coverage_gaps": {"type": "array"},
                "recommendations": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates field types AND enum values
        # (verdict, severity) — a malformed `verdict: "ok"` is rejected here
        # even though it would slip past the weak JSON-schema check.
        pydantic_model=SecurityAuditorOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
