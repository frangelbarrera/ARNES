"""Jinja2-style template resolution for playbook step inputs.

Extracted from ``arnes.playbooks.executor`` (SPLIT-R12).

Resolves ``{{ ... }}`` references against the run's ``outputs`` dict.
Supported forms:

    "steps.X.output"        -> outputs["X"]["output"] (or outputs["X"] if raw)
    "steps.X.output.field"  -> outputs["X"]["output"]["field"] (or outputs["X"]["field"])
    "variables.X"           -> outputs["X"]
    "pasos.X.salida"        -> legacy ES form of "steps.X.output"

Multiple templates in the same string are interpolated; a single template
that fills the whole string preserves the resolved value's type.
"""

from __future__ import annotations

import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+)\s*\}\}")


def _resolve_input(
    input_value: dict[str, Any] | str | None,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    """Resolve Jinja2-style template references in input.

    Example: "{{ pasos.leer_diff.salida }}" -> outputs["leer_diff"]["output"]
    Handles MULTIPLE templates in the same string.
    """
    if input_value is None:
        return {}

    if isinstance(input_value, str):
        return {"__resolved_str__": _resolve_template(input_value, outputs)}

    if isinstance(input_value, dict):
        resolved = {}
        for k, v in input_value.items():
            if isinstance(v, str):
                resolved[k] = _resolve_template(v, outputs)
            elif isinstance(v, dict):
                resolved[k] = _resolve_input(v, outputs)
            elif isinstance(v, list):
                resolved[k] = [
                    _resolve_template(item, outputs)
                    if isinstance(item, str)
                    else _resolve_input(item, outputs)
                    if isinstance(item, dict)
                    else item
                    for item in v
                ]
            else:
                resolved[k] = v
        return resolved

    # Unreachable: ``input_value`` is typed as ``dict[str, Any] | str | None``
    # and all three branches above return early. Kept as a defensive
    # fallback for callers that bypass the type system (defence-in-depth).
    return {"__input__": input_value}  # type: ignore[unreachable]


def _resolve_template(template: str, outputs: dict[str, Any]) -> Any:
    """Resolve a template string, handling MULTIPLE {{ }} references.

    Examples:
        "{{ pasos.X.salida }}" -> outputs["X"]["output"]
        "Plan: {{ variables.nombre }} for PR {{ variables.pr_number }}" -> "Plan: foo for PR 1234"
        "Diff: {{ pasos.leer_diff.salida }}, Sec: {{ pasos.auditoria.salida }}" -> "Diff: ..., Sec: ..."
        "{{ }}" -> "{{ }}"  (empty template body — returned as literal)
    """
    # Find ALL template references
    matches = list(_TEMPLATE_RE.finditer(template))

    if not matches:
        return template

    # If the entire string is ONE template, return the resolved value (preserve type)
    if len(matches) == 1 and matches[0].group(0) == template:
        expr = matches[0].group(1).strip()
        if not expr:
            # Empty template body (e.g. "{{ }}") — return the original
            # literal verbatim rather than re-rendering it with different
            # whitespace.
            return template
        return _resolve_expr(expr, outputs)

    # Otherwise, interpolate ALL matches into the string
    result = template
    # Process in reverse order to keep indexes valid
    for match in reversed(matches):
        expr = match.group(1).strip()
        if not expr:
            # Empty template body — leave the original match untouched
            continue
        resolved = _resolve_expr(expr, outputs)
        result = result[: match.start()] + str(resolved) + result[match.end() :]

    return result


def _resolve_expr(expr: str, outputs: dict[str, Any]) -> Any:
    """Resolve a single template expression like 'steps.X.output'.

    Supported forms:
        "steps.X.output"        -> outputs["X"]["output"] (or outputs["X"] if raw)
        "steps.X.output.field"  -> outputs["X"]["output"]["field"] (or outputs["X"]["field"])
        "variables.X"           -> outputs["X"]
        "pasos.X.salida"        -> legacy ES form of "steps.X.output"

    Two important behaviors:

    1. Only the LEADING prefix ("steps.", "variables.", "pasos.") is
       stripped. Interior occurrences of these substrings (e.g. when a
       step's output literally contains a key named "steps") are
       preserved. This makes deep nesting like
       ``{{ steps.s1.output.steps.s2.output }}`` work correctly.

    2. For STEP references (``steps.*`` / legacy ``pasos.*``), the
       "output" (and legacy "salida") segment is treated as a VIRTUAL
       accessor: if the current dict has an "output" key, it is
       dereferenced; if not, the segment is skipped (the current dict
       IS the output). This makes ``{{ steps.X.output }}`` work whether
       the step's output was stored raw (``outputs["X"] = output_dict``)
       or wrapped (``outputs["X"] = {"output": output_dict, ...}``).

       The virtual accessor does NOT apply to ``variables.*`` refs —
       variables are user-defined and a missing key is a real error.
    """
    # Strip leading prefix only — NOT all occurrences. Stripping all
    # occurrences of "steps." would corrupt paths whose intermediate
    # dicts literally contain a key named "steps" (deep nesting).
    stripped = expr.strip()
    is_step_ref = False
    for prefix in ("steps.", "pasos.", "variables."):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            # Only steps/pasos get the virtual "output" accessor;
            # variables use strict key lookup.
            is_step_ref = prefix in ("steps.", "pasos.")
            break

    parts = stripped.split(".")

    current: Any = outputs
    for raw_part in parts:
        # Legacy ES translation per-segment
        part = "output" if raw_part == "salida" else raw_part
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            elif is_step_ref and part == "output":
                # Virtual accessor: the current dict is itself the
                # step's output (stored raw). Skip this segment so
                # downstream segments (e.g. ".verdict") resolve against
                # the output dict directly.
                continue
            else:
                return f"{{{{ {expr} }}}}"  # Leave template as-is if not found
        else:
            return f"{{{{ {expr} }}}}"

    return current
