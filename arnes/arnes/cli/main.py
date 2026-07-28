"""
ARNES CLI — command-line interface.

Commands:
    arnes init --manual <name>       Scaffold a new playbook
    arnes ejecutar <playbook.yaml>   Execute a playbook
    arnes run <playbook.yaml>        Alias for ejecutar (EN)
    arnes list specialists           List available specialists
    arnes list playbooks             List curated playbooks
    arnes lint <playbook.yaml>       Validate a playbook without executing
    arnes eval <playbook.yaml>       Run playbook with mock LLM for testing
    arnes version                    Print version
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from arnes import __version__
from arnes.llm.factory import get_provider
from arnes.llm.mock import MockLLMProvider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler, PlaybookCompileError
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry

console = Console()
logger = structlog.get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="arnes")
def cli() -> None:
    """ARNES — The Open Agent Harness. Escribe el manual, ARNES lo ejecuta."""
    pass


@cli.command()
@click.option("--manual", help="Name of the playbook to scaffold")
@click.option(
    "--idioma",
    type=click.Choice(["es", "en"]),
    default="es",
    help="Language for the scaffolded playbook",
)
def init(manual: str | None, idioma: str) -> None:
    """Scaffold a new playbook or initialize an ARNES project."""
    if manual:
        _scaffold_manual(manual, idioma)
    else:
        _init_project()


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
@click.option("--model", default="ollama/llama3.2", help="LLM model to use")
@click.option("--budget", type=float, default=0.50, help="Max USD budget for this run")
@click.option("--mock", is_flag=True, help="Use mock LLM (no network, $0 cost)")
@click.option("--interactive", is_flag=True, help="Enable interactive HITL prompts")
@click.option("--output", "-o", type=click.Path(), help="Save bitácora to file")
def ejecutar(
    playbook_path: str,
    model: str,
    budget: float,
    mock: bool,
    interactive: bool,
    output: str | None,
) -> None:
    """Ejecutar un playbook YAML."""
    asyncio.run(_run_playbook(playbook_path, model, budget, mock, interactive, output))


# English alias
cli.commands["run"] = cli.commands["ejecutar"]


@cli.group()
def list() -> None:
    """List available specialists, playbooks, or tools."""
    pass


@list.command("specialists")
def list_specialists() -> None:
    """List available specialists."""
    registry = get_default_specialist_registry()
    table = Table(title="ARNES Specialists")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Default Model", style="dim")

    for config in registry.configs():
        table.add_row(
            config.name,
            config.description,
            config.default_model or "ollama/llama3.2",
        )

    console.print(table)


@list.command("playbooks")
@click.option(
    "--dir",
    "playbooks_dir",
    type=click.Path(),
    default="manuales",
    help="Directory to scan for playbooks",
)
def list_playbooks(playbooks_dir: str) -> None:
    """List curated playbooks in a directory."""
    path = Path(playbooks_dir)
    if not path.exists():
        console.print(f"[yellow]Directory not found: {path}[/yellow]")
        return

    table = Table(title=f"Playbooks in {path}/")
    table.add_column("File", style="cyan")
    table.add_column("Name")
    table.add_column("Objective")
    table.add_column("Budget", justify="right")

    for yaml_file in sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")):
        try:
            playbook = PlaybookCompiler.from_file(yaml_file)
            table.add_row(
                yaml_file.name,
                playbook.metadata.nombre,
                playbook.metadata.objetivo[:60] + "..." if len(playbook.metadata.objetivo) > 60 else playbook.metadata.objetivo,
                f"${playbook.metadata.budget_usd:.2f}",
            )
        except PlaybookCompileError as e:
            table.add_row(yaml_file.name, "[red]ERROR[/red]", str(e)[:60], "-")

    console.print(table)


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
def lint(playbook_path: str) -> None:
    """Validate a playbook without executing it."""
    try:
        playbook = PlaybookCompiler.from_file(playbook_path)
        console.print(f"[green]✓[/green] Playbook valid: [cyan]{playbook.metadata.nombre}[/cyan]")
        console.print(f"  Objective: {playbook.metadata.objetivo}")
        console.print(f"  Steps: {len(playbook.pasos)}")
        console.print(f"  Budget: ${playbook.metadata.budget_usd:.2f}")

        for i, step in enumerate(playbook.pasos, 1):
            specialist = step.especialista or step.herramienta or "parallel"
            console.print(f"  {i}. [cyan]{step.id}[/cyan] → {specialist}")
    except PlaybookCompileError as e:
        console.print(f"[red]✗[/red] Playbook invalid:\n{e}")
        sys.exit(1)


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
def eval(playbook_path: str) -> None:
    """Run playbook with mock LLM for testing (no network, $0 cost)."""
    asyncio.run(_run_playbook(playbook_path, "mock/test", 0.0, mock=True, interactive=False, output=None))


# ============================================================
# Helpers
# ============================================================


async def _run_playbook(
    playbook_path: str,
    model: str,
    budget: float,
    mock: bool,
    interactive: bool,
    output: str | None,
) -> None:
    """Execute a playbook and print results."""
    # Compile
    try:
        playbook = PlaybookCompiler.from_file(playbook_path)
    except PlaybookCompileError as e:
        console.print(f"[red]✗ Compile error:[/red]\n{e}")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold cyan]ARNES[/bold cyan] — Ejecutando playbook\n"
        f"  [dim]Nombre:[/dim] {playbook.metadata.nombre}\n"
        f"  [dim]Objetivo:[/dim] {playbook.metadata.objetivo}\n"
        f"  [dim]Modelo:[/dim] {model}\n"
        f"  [dim]Budget:[/dim] ${budget:.2f}",
        border_style="cyan",
    ))

    # Setup provider
    if mock or model.startswith("mock/"):
        provider = MockLLMProvider()
    else:
        provider = get_provider(model)

    # Execute
    executor = PlaybookExecutor(
        provider=provider,
        cost_budget=CostBudget(task_budget_usd=budget),
        interactive=interactive,
    )

    with console.status("[cyan]Ejecutando...[/cyan]"):
        result = await executor.run(playbook)

    # Print results
    if result.success:
        console.print("\n[green]✅ Manual ejecutado[/green]")
    else:
        console.print("\n[red]❌ Ejecución fallida[/red]")
        if result.error:
            console.print(f"  [red]Error:[/red] {result.error}")

    # Stats
    console.print(f"\n[dim]Steps ejecutados:[/dim] {result.steps_executed}")
    console.print(f"[dim]Steps fallidos:[/dim] {result.steps_failed}")
    console.print(f"[dim]Duración:[/dim] {result.duration_s:.2f}s")
    console.print(f"[dim]Tokens in/out:[/dim] {result.total_tokens_in}/{result.total_tokens_out}")
    console.print(f"[dim]Costo total:[/dim] ${result.total_cost_usd:.4f}")

    # Save bitácora
    if output:
        Path(output).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Bitácora guardada en:[/cyan] {output}")
    else:
        # Default: save to ./bitacora-<name>-<timestamp>.md
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = f"bitacora-{playbook.metadata.nombre}-{ts}.md"
        Path(default_path).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Bitácora guardada en:[/cyan] {default_path}")


def _scaffold_manual(name: str, idioma: str) -> None:
    """Create a new playbook file from template."""
    path = Path("manuales") / f"{name}.md.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        console.print(f"[yellow]File already exists: {path}[/yellow]")
        sys.exit(1)

    template = _MANUAL_TEMPLATE_ES if idioma == "es" else _MANUAL_TEMPLATE_EN
    path.write_text(template.format(name=name), encoding="utf-8")
    console.print(f"[green]✓[/green] Created: [cyan]{path}[/cyan]")
    console.print("\nEdit it and run with:")
    console.print(f"  [dim]arnes ejecutar {path}[/dim]")


def _init_project() -> None:
    """Initialize a new ARNES project structure."""
    console.print("[bold cyan]ARNES — Initializing project[/bold cyan]\n")

    dirs = ["manuales", "bitacoras"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
        console.print(f"  [green]✓[/green] Created: {d}/")

    # Create example playbook
    example = Path("manuales") / "hola-mundo.md.yaml"
    if not example.exists():
        example.write_text(_MANUAL_TEMPLATE_ES.format(name="hola-mundo"), encoding="utf-8")
        console.print(f"  [green]✓[/green] Created: {example}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit manuales/hola-mundo.md.yaml")
    console.print("  2. Run: [cyan]arnes ejecutar manuales/hola-mundo.md.yaml[/cyan]")
    console.print("  3. List specialists: [cyan]arnes list specialists[/cyan]")


_MANUAL_TEMPLATE_ES = """\
# {name}.md.yaml — Manual de ARNES
# Documentación: https://arnes.dev/playbook-dsl

nombre: {name}
objetivo: Describe qué hace este manual
budget_usd: 0.50

pasos:
  - id: paso_1
    especialista: @planner
    input:
      task: "Describe la tarea a planificar"

  - id: paso_2
    especialista: @coder
    input: "{{{{ pasos.paso_1.salida }}}}"
    requiere: [paso_1]

  - id: paso_3
    especialista: @reviewer
    input:
      codigo: "{{{{ pasos.paso_2.salida }}}}"
"""


_MANUAL_TEMPLATE_EN = """\
# {name}.yaml — ARNES playbook
# Docs: https://arnes.dev/playbook-dsl

nombre: {name}
objetivo: Describe what this playbook does
budget_usd: 0.50

pasos:
  - id: step_1
    especialista: @planner
    input:
      task: "Describe the task to plan"

  - id: step_2
    especialista: @coder
    input: "{{{{ pasos.step_1.salida }}}}"
    requiere: [step_1]
"""


if __name__ == "__main__":
    cli()
