"""
ARNES Playbook DSL — declarative YAML schema.

A Playbook is a manual in YAML that ARNES compiles to an executable DAG.
Each playbook has:
- metadata (name, objective, budget)
- steps (ordered list of PlaybookStep)
- Each step has: id, specialist OR tool, input, conditionals, retry, HITL gate

Example:
    nombre: auditar-pr
    objetivo: Auditar un Pull Request
    budget_usd: 0.50

    pasos:
      - id: leer_diff
        especialista: @lector-de-diff
        input:
          pr: 1234
          repo: mi-org/mi-repo

      - id: auditoria_seguridad
        especialista: @auditor-de-seg
        input: "{{ pasos.leer_diff.salida }}"
        requiere: [commit_firmado]
        si_no_se_cumple:
          llamar: @comentarista-de-fallback
          terminar: rechazado

      - id: paralelo
        paralelo:
          - id: lint
            especialista: @reviewer
          - id: tests
            especialista: @tester

This file defines the pydantic schemas that the YAML is parsed into.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RetryPolicy(BaseModel):
    """Retry configuration for a step."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_s: float = Field(default=1.0, ge=0.0, le=60.0)
    backoff_strategy: Literal["fixed", "exponential"] = "exponential"
    retry_on: list[str] = Field(default_factory=list)  # error substrings to retry on


class HITLGate(BaseModel):
    """Human-in-the-loop gate. Pauses execution until human approves."""

    question: str
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    ttl_s: int = Field(default=86400, ge=60, le=604800)
    on_timeout: Literal["approve", "reject", "abort"] = "reject"


class ConditionalBranch(BaseModel):
    """Conditional branch — executed if `cuando` evaluates truthy.

    For `si_no_se_cumple` (the implicit "else" of a step), `cuando` is optional
    because the branch fires when the step's `requiere` conditions fail.
    """

    cuando: str | None = None  # None = implicit (si_no_se_cumple case)
    accion: Literal["llamar", "terminar", "saltar"]
    # If accion == "llamar":
    especialista: str | None = None
    input: dict[str, Any] | None = None
    # If accion == "terminar":
    terminar: Literal["aprobado", "rechazado", "abortado"] | None = None
    # If accion == "saltar":
    saltar_a: str | None = None  # step id to jump to


class PlaybookStep(BaseModel):
    """A single step in a playbook.

    A step is either:
    - A specialist invocation (especialista: @planner)
    - A tool invocation (herramienta: github.crear_comentario)
    - A parallel branch (paralelo: [...])
    - A conditional branch (condicionales: [...])
    """

    id: str
    especialista: str | None = None
    herramienta: str | None = None
    input: dict[str, Any] | str | None = None  # str = Jinja2 template referencing prior steps
    output: str | None = None  # variable name to assign output to

    # Control flow
    requiere: list[str] = Field(default_factory=list)  # preconditions (must all be true)
    si_no_se_cumple: ConditionalBranch | None = None
    condicionales: list[ConditionalBranch] = Field(default_factory=list)  # if/elif chain
    paralelo: list[PlaybookStep] | None = None  # parallel sub-steps

    # Resilience
    retry: RetryPolicy | None = None
    timeout_s: float | None = None

    # HITL
    aprobacion_humana: HITLGate | None = None

    @model_validator(mode="after")
    def validate_step_type(self) -> PlaybookStep:
        """Exactly one of: especialista, herramienta, paralelo must be set."""
        types_set = sum(
            1 for x in [self.especialista, self.herramienta, self.paralelo] if x is not None
        )
        if types_set == 0:
            raise ValueError(f"Step '{self.id}' must have one of: especialista, herramienta, paralelo")
        if types_set > 1:
            raise ValueError(f"Step '{self.id}' can only have one of: especialista, herramienta, paralelo")
        return self


class PlaybookMetadata(BaseModel):
    """Metadata about a playbook."""

    nombre: str
    objetivo: str
    version: str = "1.0.0"
    autor: str | None = None
    tags: list[str] = Field(default_factory=list)
    budget_usd: float = 0.50
    idioma: Literal["es", "en", "bilingual"] = "es"


class Playbook(BaseModel):
    """A complete playbook — the manual ARNES executes."""

    # Top-level metadata fields (bilingual: ES keys promoted to PlaybookMetadata)
    nombre: str | None = None
    objetivo: str | None = None
    version: str = "1.0.0"
    autor: str | None = None
    tags: list[str] = Field(default_factory=list)
    budget_usd: float = 0.50
    idioma: Literal["es", "en", "bilingual"] = "es"

    # Allow either top-level metadata fields OR a nested metadata object
    metadata: PlaybookMetadata | None = None

    pasos: list[PlaybookStep]

    # Globals
    modelo_default: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _build_metadata(self) -> Playbook:
        """If metadata is None, build it from top-level fields."""
        if self.metadata is None:
            if not self.nombre:
                raise ValueError("Playbook requires 'nombre' (or nested 'metadata.nombre')")
            self.metadata = PlaybookMetadata(
                nombre=self.nombre,
                objetivo=self.objetivo or "Sin objetivo",
                version=self.version,
                autor=self.autor,
                tags=self.tags,
                budget_usd=self.budget_usd,
                idioma=self.idioma,
            )
        return self

    @model_validator(mode="after")
    def validate_step_ids(self) -> Playbook:
        """Step IDs must be unique."""
        ids = [p.id for p in self.pasos]
        duplicates = {x for x in ids if ids.count(x) > 1}
        if duplicates:
            raise ValueError(f"Duplicate step IDs: {duplicates}")
        return self

    def get_step(self, step_id: str) -> PlaybookStep | None:
        """Find a step by ID (searches recursively into parallel branches)."""
        for step in self.pasos:
            if step.id == step_id:
                return step
            if step.paralelo:
                for sub in step.paralelo:
                    if sub.id == step_id:
                        return sub
        return None
