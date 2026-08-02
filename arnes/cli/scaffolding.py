"""ARNES CLI scaffolding — project init + manual template helpers.

This module owns the scaffolding surface for the CLI:

- :func:`_scaffold_manual` — create a new playbook YAML from the standard
  template (used by ``arnes init --manual <name>``).
- :func:`_init_project` — bootstrap an empty ARNES project structure
  (``manuals/`` + ``run_logs/`` + a starter ``hello-world.yaml``).
- :data:`_MANUAL_TEMPLATE` — the playbook YAML template that ships with
  the CLI. Kept here (not in ``templates/``) so it's always importable
  without filesystem access.
"""

from __future__ import annotations

import sys
from pathlib import Path

from arnes.cli.helpers import console


def _scaffold_manual(name: str) -> None:
    """Create a new playbook file from template."""
    path = Path("manuals") / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        console.print(f"[yellow]File already exists: {path}[/yellow]")
        sys.exit(1)

    path.write_text(_MANUAL_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]✓[/green] Created: [cyan]{path}[/cyan]")
    console.print("\nEdit it and run with:")
    console.print(f"  [dim]arnes run {path}[/dim]")


def _init_project() -> None:
    """Initialize a new ARNES project structure."""
    console.print("[bold cyan]ARNES — Initializing project[/bold cyan]\n")

    dirs = ["manuals", "run_logs"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
        console.print(f"  [green]✓[/green] Created: {d}/")

    # Create example playbook
    example = Path("manuals") / "hello-world.yaml"
    if not example.exists():
        example.write_text(_MANUAL_TEMPLATE.format(name="hello-world"), encoding="utf-8")
        console.print(f"  [green]✓[/green] Created: {example}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit manuals/hello-world.yaml")
    console.print("  2. Run: [cyan]arnes run manuals/hello-world.yaml[/cyan]")
    console.print("  3. List specialists: [cyan]arnes list specialists[/cyan]")


_MANUAL_TEMPLATE = """\
# {name}.yaml — ARNES playbook
# Documentation: https://github.com/frangelbarrera/ARNES#readme

name: {name}
objective: Describe what this playbook does
budget_usd: 0.50

steps:
  - id: step_1
    specialist: "@planner"
    input:
      task: "Describe the task to plan"

  - id: step_2
    specialist: "@coder"
    input: "{{{{ steps.step_1.output }}}}"
    requires: [step_1]

  - id: step_3
    specialist: "@reviewer"
    input:
      code: "{{{{ steps.step_2.output }}}}"
"""


__all__ = [
    "_MANUAL_TEMPLATE",
    "_init_project",
    "_scaffold_manual",
]
