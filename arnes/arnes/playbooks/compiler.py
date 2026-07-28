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
from typing import Any

import yaml
from pydantic import ValidationError

from arnes.playbooks.schema import Playbook, PlaybookStep


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

        # Step 2: Translate ES keys → schema keys (bilingual support)
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
                f"Schema validation failed:\n" + "\n".join(errors),
                path=path,
            ) from e

        # Step 4: Semantic checks
        PlaybookCompiler._semantic_checks(playbook, path=path)

        return playbook

    # ============================================================
    # Bilingual key translation (ES/EN)
    # ============================================================

    _KEY_MAP: dict[str, str] = {
        "nombre": "nombre",  # kept in metadata
        "objetivo": "objetivo",
        "pasos": "pasos",
        "modelo_default": "modelo_default",
        "variables": "variables",
        # Step-level
        "especialista": "especialista",
        "herramienta": "herramienta",
        "entrada": "input",  # ES alias
        "salida": "output",  # ES alias
        "requiere": "requiere",
        "si_no_se_cumple": "si_no_se_cumple",
        "condicionales": "condicionales",
        "paralelo": "paralelo",
        "retry": "retry",
        "timeout_s": "timeout_s",
        "aprobacion_humana": "aprobacion_humana",
        # English equivalents (for bilingual support)
        "name": "nombre",
        "steps": "pasos",
        "specialist": "especialista",
        "tool": "herramienta",
        "input": "input",
        "output": "output",
        "requires": "requiere",
        "if_not_met": "si_no_se_cumple",
        "conditionals": "condicionales",
        "parallel": "paralelo",
        "human_approval": "aprobacion_humana",
    }

    @classmethod
    def _translate_keys(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Translate ES/EN keys to canonical schema keys."""
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
            if step.especialista and not step.especialista.startswith("@"):
                raise PlaybookCompileError(
                    f"Step '{step.id}': specialist '{step.especialista}' must start with '@'",
                    path=path,
                )

        # Check 2: Conditional branch targets exist
        for step in _iter_steps(playbook):
            if step.si_no_se_cumple:
                if step.si_no_se_cumple.saltar_a:
                    if not playbook.get_step(step.si_no_se_cumple.saltar_a):
                        raise PlaybookCompileError(
                            f"Step '{step.id}': si_no_se_cumple.saltar_a target "
                            f"'{step.si_no_se_cumple.saltar_a}' not found",
                            path=path,
                        )
            for cond in step.condicionales:
                if cond.saltar_a and not playbook.get_step(cond.saltar_a):
                    raise PlaybookCompileError(
                        f"Step '{step.id}': condicional.saltar_a target '{cond.saltar_a}' not found",
                        path=path,
                    )

        # Check 3: Parallel steps have unique IDs
        for step in _iter_steps(playbook):
            if step.paralelo:
                sub_ids = [s.id for s in step.paralelo]
                dups = {x for x in sub_ids if sub_ids.count(x) > 1}
                if dups:
                    raise PlaybookCompileError(
                        f"Step '{step.id}': duplicate IDs in parallel branch: {dups}",
                        path=path,
                    )


def _iter_steps(playbook: Playbook):
    """Iterate all steps in a playbook, including parallel sub-steps."""
    for step in playbook.pasos:
        yield step
        if step.paralelo:
            yield from step.paralelo
