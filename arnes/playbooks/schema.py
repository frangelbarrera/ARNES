"""
ARNES Playbook DSL — declarative YAML schema.

A Playbook is a manual in YAML that ARNES compiles to an executable DAG.
Each playbook has:
- metadata (name, objective, budget)
- steps (ordered list of PlaybookStep)
- Each step has: id, specialist OR tool, input, conditionals, retry, HITL gate

Example:
    name: audit-pr
    objective: Audit a Pull Request
    budget_usd: 0.50

    steps:
      - id: read_diff
        specialist: "@reviewer"
        input:
          pr: 1234
          repo: my-org/my-repo

      - id: security_audit
        specialist: "@reviewer"
        input: "{{ steps.read_diff.output }}"
        requires: [commit_signed]
        if_not_met:
          action: call
          specialist: "@reviewer"
          input:
            focus: "Comment that the PR is blocked by security review"

      - id: parallel
        parallel:
          - id: lint
            specialist: "@reviewer"
          - id: tests
            specialist: "@tester"

This file defines the pydantic schemas that the YAML is parsed into.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RetryPolicy(BaseModel):
    """Retry configuration for a step.

    Schema defined; execution in v0.2. The executor currently does not read
    ``step.retry`` — failed steps raise and the playbook run aborts. When v0.2
    lands, the executor will honour ``max_attempts`` / ``backoff_s`` /
    ``backoff_strategy`` / ``retry_on`` and emit ``StepFailedEvent`` only after
    the policy is exhausted.
    """

    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_s: float = Field(default=1.0, ge=0.0, le=60.0)
    backoff_strategy: Literal["fixed", "exponential"] = "exponential"
    retry_on: list[str] = Field(default_factory=list)  # error substrings to retry on


class HITLGate(BaseModel):
    """Human-in-the-loop gate. Pauses execution until human approves.

    Schema defined; execution in v0.2. The executor currently does not read
    ``step.human_approval`` — step-level HITL is handled via the
    ``HumanApprovalTool`` (which specialists can call explicitly). When v0.2
    lands, the executor will emit ``HumanApprovalRequestedEvent`` before
    executing any step with a ``human_approval`` gate and resume from a
    ``RUN_RESUMED`` lifecycle event on approval.
    """

    question: str
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    ttl_s: int = Field(default=86400, ge=60, le=604800)
    on_timeout: Literal["approve", "reject", "abort"] = "reject"


class ConditionalBranch(BaseModel):
    """Conditional branch — executed if `when` evaluates truthy.

    For `if_not_met` (the implicit "else" of a step), `when` is optional
    because the branch fires when the step's `requires` conditions fail.
    """

    when: str | None = None  # None = implicit (if_not_met case)
    action: Literal["call", "terminate", "skip"]
    # If action == "call":
    specialist: str | None = None
    input: dict[str, Any] | None = None
    # If action == "terminate":
    terminate: Literal["approved", "rejected", "aborted"] | None = None
    # If action == "skip":
    skip_to: str | None = None  # step id to jump to


class PlaybookStep(BaseModel):
    """A single step in a playbook.

    A step is either:
    - A specialist invocation (specialist: "@planner")
    - A tool invocation (tool: github.create_comment)
    - A parallel branch (parallel: [...])
    - A conditional branch (conditionals: [...])
    """

    id: str
    specialist: str | None = None
    tool: str | None = None
    input: dict[str, Any] | str | None = None  # str = Jinja2-style template referencing prior steps
    output: str | None = None  # variable name to assign output to

    # Control flow
    requires: list[str] = Field(default_factory=list)  # preconditions (must all be true)
    if_not_met: ConditionalBranch | None = None
    conditionals: list[ConditionalBranch] = Field(default_factory=list)  # if/elif chain
    parallel: list[PlaybookStep] | None = None  # parallel sub-steps

    # Resilience
    retry: RetryPolicy | None = None
    timeout_s: float | None = None

    # HITL
    human_approval: HITLGate | None = None

    @model_validator(mode="after")
    def validate_step_type(self) -> PlaybookStep:
        """Exactly one of: specialist, tool, parallel must be set."""
        types_set = sum(1 for x in [self.specialist, self.tool, self.parallel] if x is not None)
        if types_set == 0:
            raise ValueError(f"Step '{self.id}' must have one of: specialist, tool, parallel")
        if types_set > 1:
            raise ValueError(f"Step '{self.id}' can only have one of: specialist, tool, parallel")
        return self


class PlaybookMetadata(BaseModel):
    """Metadata about a playbook."""

    name: str
    objective: str
    version: str = "1.0.0"
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    budget_usd: float = 0.50
    language: Literal["en", "es", "bilingual"] = "en"


class Playbook(BaseModel):
    """A complete playbook — the manual ARNES executes."""

    # Top-level metadata fields (canonical English keys)
    name: str | None = None
    objective: str | None = None
    version: str = "1.0.0"
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    budget_usd: float = 0.50
    language: Literal["en", "es", "bilingual"] = "en"

    # Allow either top-level metadata fields OR a nested metadata object
    metadata: PlaybookMetadata | None = None

    steps: list[PlaybookStep]

    # Globals
    default_model: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _build_metadata(self) -> Playbook:
        """If metadata is None, build it from top-level fields."""
        if self.metadata is None:
            if not self.name:
                raise ValueError("Playbook requires 'name' (or nested 'metadata.name')")
            self.metadata = PlaybookMetadata(
                name=self.name,
                objective=self.objective or "No objective",
                version=self.version,
                author=self.author,
                tags=self.tags,
                budget_usd=self.budget_usd,
                language=self.language,
            )
        return self

    @model_validator(mode="after")
    def validate_step_ids(self) -> Playbook:
        """Step IDs must be unique."""
        ids = [p.id for p in self.steps]
        duplicates = {x for x in ids if ids.count(x) > 1}
        if duplicates:
            raise ValueError(f"Duplicate step IDs: {duplicates}")
        return self

    def get_step(self, step_id: str) -> PlaybookStep | None:
        """Find a step by ID (searches recursively into parallel branches)."""
        for step in self.steps:
            if step.id == step_id:
                return step
            if step.parallel:
                for sub in step.parallel:
                    if sub.id == step_id:
                        return sub
        return None
