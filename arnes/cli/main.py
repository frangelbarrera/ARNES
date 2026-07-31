"""
ARNES CLI — command-line interface.

Commands:
    arnes plan "<request>"           Proactively analyze a request, estimate costs,
                                     assess viability, and generate a playbook
    arnes init --manual <name>       Scaffold a new playbook
    arnes run <playbook.yaml>        Execute a playbook
    arnes run <playbook> --stream    Execute with real-time step streaming
    arnes stream <specialist>        Stream a specialist's response token-by-token
    arnes list specialists           List available specialists
    arnes list playbooks             List curated playbooks
    arnes lint <playbook.yaml>       Validate a playbook without executing
    arnes eval <playbook.yaml>       Run playbook with mock LLM for testing
    arnes benchmark [--seeds N]      Run benchmark suite with mock LLM
    arnes mcp serve                  Start MCP server (stdio or http)
    arnes --version                  Print version

The async runners, mock provider, scaffold helpers, and templates
live in :mod:`arnes.cli.helpers` so this file stays slim. The
command definitions here are thin click wrappers that delegate to
the helpers — adding a new command stays a 10-line change in this
file plus the helper in ``helpers.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from arnes import __version__
from arnes.cli.helpers import (
    _run_benchmark,
    _run_playbook,
    _serve_mcp,
    _stream_specialist,
    console,
)
from arnes.cli.scaffolding import _init_project, _scaffold_manual
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.specialists.base import get_default_specialist_registry


@click.group()
@click.version_option(__version__, prog_name="arnes")
def cli() -> None:
    """ARNES — The Open Agent Harness. Write the manual, ARNES runs it."""
    pass


@cli.command()
@click.argument("request")
@click.option(
    "--model", default="anthropic/claude-sonnet-4-20250514", help="LLM model for planning"
)
@click.option("--budget", type=float, default=5.0, help="Max USD budget for the planning call")
@click.option("--save", is_flag=True, help="Save generated playbook to manuals/")
def plan(request: str, model: str, budget: float, save: bool) -> None:
    """Proactively analyze a request and generate a playbook.

    ARNES doesn't just start coding. It researches market viability,
    estimates costs, warns about risks, and proposes a plan BEFORE executing.

    Examples:
        arnes plan "Build a dating app for the Play Store"
        arnes plan "Create a SaaS accounting tool" --save
        arnes plan "Build a REST API for a blog" --model ollama/llama3.2
    """
    asyncio.run(_run_proactive_plan(request, model, budget, save))


async def _run_proactive_plan(request: str, model: str, budget: float, save: bool) -> None:
    """Run the proactive planner."""
    from arnes.llm.factory import get_provider
    from arnes.proactive import ProactivePlanner

    provider = get_provider(model)
    planner = ProactivePlanner(provider=provider, budget_usd=budget)

    console.print(
        Panel.fit(
            f"[bold cyan]ARNES[/bold cyan] — Proactive Planning\n"
            f"  [dim]Request:[/dim] {request[:80]}{'...' if len(request) > 80 else ''}\n"
            f"  [dim]Model:[/dim] {model}\n"
            f"  [dim]Budget:[/dim] ${budget:.2f}",
            border_style="cyan",
        )
    )

    with console.status(
        "[cyan]Analyzing request... researching market, estimating costs, assessing risks...[/cyan]"
    ):
        plan_result = await planner.plan(request)

    if "error" in plan_result:
        console.print(f"[red]Error:[/red] {plan_result['error']}")
        sys.exit(1)

    summary = ProactivePlanner.format_plan_summary(plan_result)
    console.print(summary)

    if save:
        yaml_content = ProactivePlanner.to_yaml(plan_result)
        playbook_name = plan_result.get("proposed_playbook", {}).get("name", "generated")
        path = Path("manuals") / f"{playbook_name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml_content, encoding="utf-8")
        console.print(f"\n[cyan]Playbook saved to:[/cyan] {path}")
        console.print(f"[dim]Review it, then run: arnes run {path}[/dim]")


@cli.command()
@click.option("--manual", help="Name of the playbook to scaffold")
@click.option(
    "--lang",
    type=click.Choice(["en", "es"]),
    default="en",
    help="Language for the scaffolded playbook",
)
def init(manual: str | None, lang: str) -> None:
    """Scaffold a new playbook or initialize an ARNES project."""
    if manual:
        _scaffold_manual(manual, lang)
    else:
        _init_project()


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
@click.option("--model", default="ollama/llama3.2", help="LLM model to use")
@click.option("--budget", type=float, default=0.50, help="Max USD budget for this run")
@click.option("--mock", is_flag=True, help="Use mock LLM (no network, $0 cost)")
@click.option("--interactive", is_flag=True, help="Enable interactive HITL prompts")
@click.option("--output", "-o", type=click.Path(), help="Save run log to file")
@click.option(
    "--stream",
    is_flag=True,
    help="Stream step events as they complete (best-effort: parallel branches stream in completion order)",
)
def run(
    playbook_path: str,
    model: str,
    budget: float,
    mock: bool,
    interactive: bool,
    output: str | None,
    stream: bool,
) -> None:
    """Execute a playbook YAML."""
    asyncio.run(_run_playbook(playbook_path, model, budget, mock, interactive, output, stream))


# Spanish alias for backwards compat (will be deprecated in v0.2)
cli.add_command(run, name="ejecutar")


@cli.group()
def list_cmd() -> None:
    """List available specialists, playbooks, or tools."""
    pass


# Register ``list`` as an alias so the CLI command (``arnes list specialists``)
# keeps working — the Python function is renamed to ``list_cmd`` because a
# function named ``list`` shadows the builtin and breaks mypy type resolution
# for any sibling annotations using ``list[...]``.
cli.add_command(list_cmd, name="list")


@list_cmd.command("specialists")
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


@list_cmd.command("playbooks")
@click.option(
    "--dir",
    "playbooks_dir",
    type=click.Path(),
    default="manuals",
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

    for yaml_file in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
        try:
            playbook = PlaybookCompiler.from_file(yaml_file)
            # The schema validator guarantees metadata is non-None after compile.
            assert playbook.metadata is not None
            obj = playbook.metadata.objective
            table.add_row(
                yaml_file.name,
                playbook.metadata.name,
                obj[:60] + "..." if len(obj) > 60 else obj,
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
        assert playbook.metadata is not None
        console.print(f"[green]✓[/green] Playbook valid: [cyan]{playbook.metadata.name}[/cyan]")
        console.print(f"  Objective: {playbook.metadata.objective}")
        console.print(f"  Steps: {len(playbook.steps)}")
        console.print(f"  Budget: ${playbook.metadata.budget_usd:.2f}")

        for i, step in enumerate(playbook.steps, 1):
            action = step.specialist or step.tool or "parallel"
            console.print(f"  {i}. [cyan]{step.id}[/cyan] → {action}")
    except PlaybookCompileError as e:
        console.print(f"[red]✗[/red] Playbook invalid:\n{e}")
        sys.exit(1)


@cli.command()
@click.argument("specialist")
@click.option("--task", required=True, help="Task description for the specialist")
@click.option("--model", default="ollama/llama3.2", help="LLM model to use")
@click.option("--mock", is_flag=True, help="Use mock LLM (no network, $0 cost)")
def stream(specialist: str, task: str, model: str, mock: bool) -> None:
    """Stream a specialist's response token by token.

    Example:
        arnes stream @planner --task "Plan a blog post"
        arnes stream @planner --task "Plan a blog post" --mock
    """
    asyncio.run(_stream_specialist(specialist, task, model, mock))


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
def eval(playbook_path: str) -> None:
    """Run playbook with mock LLM for testing (no network, $0 cost)."""
    asyncio.run(
        _run_playbook(playbook_path, "mock/test", 0.0, mock=True, interactive=False, output=None)
    )


@cli.command()
@click.option(
    "--seeds",
    default=1,
    type=click.IntRange(min=1, max=20),
    help="Number of seeds to run each playbook with (statistical significance)",
)
@click.option(
    "--concurrent",
    default=1,
    type=click.IntRange(min=1, max=16),
    help="Number of playbooks to run concurrently",
)
@click.option(
    "--manuals-dir",
    "manuals_dir",
    type=click.Path(),
    default=None,
    help="Directory to scan for playbooks (default: repo manuals/)",
)
@click.option(
    "--output",
    "-o",
    "output",
    type=click.Path(),
    default="benchmark-results.json",
    help="Path to save JSON results (default: benchmark-results.json)",
)
def benchmark(seeds: int, concurrent: int, manuals_dir: str | None, output: str) -> None:
    """Run the basic benchmark suite against the mock LLM.

    Runs every playbook in ``manuals/`` ``--seeds`` times with a
    deterministic seeded mock LLM (no network, no API spend). Reports
    per-playbook success rate, avg/p95 duration, tokens, and cost.

    Examples:

        arnes benchmark                          # 1 seed, 1 concurrent
        arnes benchmark --seeds 3                # 3 seeds per playbook
        arnes benchmark --concurrent 4           # 4 playbooks at once
        arnes benchmark --seeds 5 --concurrent 4 # 5 seeds, 4-way parallel
    """
    asyncio.run(_run_benchmark(seeds, concurrent, manuals_dir, output))


@cli.group()
def mcp() -> None:
    """MCP server commands."""
    pass


@mcp.command("serve")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport mechanism (stdio for Claude Desktop, http for remote)",
)
@click.option("--host", default="127.0.0.1", help="HTTP host (only with --transport=http)")
@click.option("--port", default=8765, help="HTTP port (only with --transport=http)")
def mcp_serve(transport: str, host: str, port: int) -> None:
    """Start the ARNES MCP server.

    Use this to expose ARNES as an MCP server for Claude Desktop, Cursor,
    Cline, Zed, or any MCP-compatible client.

    For Claude Desktop, add to your config:
    {
      "mcpServers": {
        "arnes": {
          "command": "arnes",
          "args": ["mcp", "serve"]
        }
      }
    }
    """
    asyncio.run(_serve_mcp(transport, host, port))


if __name__ == "__main__":
    cli()
