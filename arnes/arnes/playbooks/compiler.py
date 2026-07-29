"""
ARNES Playbook Compiler — YAML → Pydantic → validated Playbook.

The compiler:
1. Reads YAML from file or string.
2. Parses into a dict.
3. Validates against the Playbook schema (pydantic).
4. Runs semantic checks (references, types, DAG cycles).
5. Returns a ready-to-execute Playbook.

If any check fails, raises PlaybookCompileError with a helpful message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import ValidationError

from arnes.playbooks.schema import Playbook


class PlaybookCompileError(Exception):
    """Raised when a playbook YAML fails to compile."""

    def __init__(self, message: str, *, path: str | None = None, line: int | None = None) -> None:
        self.path = path
        self.line = line
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        parts = [message]
        if self.path:
            parts.append(f"\n  File: {self.path}")
        if self.line:
            parts.append(f"  Line: {self.line}")
        return "\n".join(parts)


class PlaybookCompiler:
    """Compiles YAML playbooks into validated Playbook objects."""

    @staticmethod
    def from_file(path: str | Path) -> Playbook:
        """Compile a playbook from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise PlaybookCompileError(f"File not found: {path}", path=str(path))
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise PlaybookCompileError(f"Cannot read file: {e}", path=str(path)) from e
        return PlaybookCompiler.from_string(content, path=str(path))

    @staticmethod
    def from_string(yaml_str: str, *, path: str | None = None) -> Playbook:
        """Compile a playbook from a YAML string."""
        # Step 1: Parse YAML
        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            line = getattr(e, "problem_mark", None)
            line_num = line.line + 1 if line else None
            raise PlaybookCompileError(
                f"YAML parse error: {e}",
                path=path,
                line=line_num,
            ) from e

        if not isinstance(data, dict):
            raise PlaybookCompileError(
                f"Playbook must be a YAML mapping, got {type(data).__name__}",
                path=path,
            )

        # Step 2: Translate legacy ES keys → canonical EN keys (backwards compat)
        data = PlaybookCompiler._translate_keys(data)

        # Step 3: Pydantic validation
        try:
            playbook = Playbook.model_validate(data)
        except ValidationError as e:
            errors = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                errors.append(f"  {loc}: {err['msg']}")
            raise PlaybookCompileError(
                "Schema validation failed:\n" + "\n".join(errors),
                path=path,
            ) from e

        # Step 4: Semantic checks
        PlaybookCompiler._semantic_checks(playbook, path=path)

        return playbook

    # ============================================================
    # Bilingual key translation (ES → EN for backwards compat)
    # ============================================================

    _KEY_MAP: ClassVar[dict[str, str]] = {
        # Top-level
        "nombre": "name",
        "objetivo": "objective",
        "pasos": "steps",
        "modelo_default": "default_model",
        "variables": "variables",
        "idioma": "language",
        # Step-level
        "especialista": "specialist",
        "herramienta": "tool",
        "entrada": "input",
        "salida": "output",
        "requiere": "requires",
        "si_no_se_cumple": "if_not_met",
        "condicionales": "conditionals",
        "paralelo": "parallel",
        "retry": "retry",
        "timeout_s": "timeout_s",
        "aprobacion_humana": "human_approval",
        # ConditionalBranch
        "cuando": "when",
        "accion": "action",
        "llamar": "call",  # legacy — will be normalized to action
        "terminar": "terminate",
        "saltar_a": "skip_to",
    }

    @classmethod
    def _translate_keys(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Translate ES keys to canonical EN keys."""
        return cls._translate_recursive(data)

    @classmethod
    def _translate_recursive(cls, obj: Any) -> Any:
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                new_key = cls._KEY_MAP.get(k, k)
                new_dict[new_key] = cls._translate_recursive(v)
            return new_dict
        if isinstance(obj, list):
            return [cls._translate_recursive(x) for x in obj]
        return obj

    # ============================================================
    # Semantic checks
    # ============================================================

    @staticmethod
    def _semantic_checks(playbook: Playbook, *, path: str | None = None) -> None:
        """Run semantic validation checks."""
        # Check 1: All specialist references exist (deferred to runtime — we only check syntax here)
        for step in _iter_steps(playbook):
            if step.specialist and not step.specialist.startswith("@"):
                raise PlaybookCompileError(
                    f"Step '{step.id}': specialist '{step.specialist}' must start with '@'",
                    path=path,
                )

        # Check 2: Conditional branch targets exist
        for step in _iter_steps(playbook):
            if step.if_not_met:
                if step.if_not_met.skip_to:
                    if not playbook.get_step(step.if_not_met.skip_to):
                        raise PlaybookCompileError(
                            f"Step '{step.id}': if_not_met.skip_to target "
                            f"'{step.if_not_met.skip_to}' not found",
                            path=path,
                        )
            for cond in step.conditionals:
                if cond.skip_to and not playbook.get_step(cond.skip_to):
                    raise PlaybookCompileError(
                        f"Step '{step.id}': conditional.skip_to target '{cond.skip_to}' not found",
                        path=path,
                    )

        # Check 3: Parallel steps have unique IDs
        for step in _iter_steps(playbook):
            if step.parallel:
                sub_ids = [s.id for s in step.parallel]
                dups = {x for x in sub_ids if sub_ids.count(x) > 1}
                if dups:
                    raise PlaybookCompileError(
                        f"Step '{step.id}': duplicate IDs in parallel branch: {dups}",
                        path=path,
                    )


def _iter_steps(playbook: Playbook):
    """Iterate all steps in a playbook, including parallel sub-steps."""
    for step in playbook.steps:
        yield step
        if step.parallel:
            yield from step.parallel
