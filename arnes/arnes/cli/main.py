"""
ARNES CLI — command-line interface.

Commands:
    arnes init --manual <name>       Scaffold a new playbook
    arnes run <playbook.yaml>        Execute a playbook
    arnes run <playbook> --stream    Execute with real-time step streaming
    arnes stream <specialist>        Stream a specialist's response token-by-token
    arnes list specialists           List available specialists
    arnes list playbooks             List curated playbooks
    arnes lint <playbook.yaml>       Validate a playbook without executing
    arnes eval <playbook.yaml>       Run playbook with mock LLM for testing
    arnes mcp serve                  Start MCP server (stdio or http)
    arnes --version                  Print version
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arnes import __version__
from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor, PlaybookRunResult
from arnes.playbooks.schema import Playbook
from arnes.specialists.base import get_default_specialist_registry

console = Console()
logger = structlog.get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="arnes")
def cli() -> None:
    """ARNES — The Open Agent Harness. Write the manual, ARNES runs it."""
    pass


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
@click.option("--output", "-o", type=click.Path(), help="Save bitácora to file")
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


async def _stream_specialist(specialist: str, task: str, model: str, mock: bool) -> None:
    """Stream a specialist's response."""
    from arnes import Harness, HarnessConfig

    if mock or model.startswith("mock/"):
        provider: LLMProvider = _SchemaValidMockLLMProvider()
    else:
        provider = get_provider(model)

    harness = Harness(
        config=HarnessConfig(model=model, budget_usd=0.50),
        provider=provider,
    )

    # Normalize specialist name
    if not specialist.startswith("@"):
        specialist = "@" + specialist

    # Check specialist exists before streaming
    specialist_obj = harness.specialist_registry.get(specialist)
    if not specialist_obj:
        available = harness.specialist_registry.list_names()
        console.print(f"[red]✗[/red] Specialist '{specialist}' not found. Available: {available}")
        sys.exit(1)

    console.print(f"[cyan]Streaming[/cyan] {specialist}...")
    console.print("[dim]---[/dim]")

    total_in = 0
    total_out = 0
    total_cost = 0.0
    chunks_received = 0

    async for chunk in harness.stream(specialist, {"task": task}):
        chunks_received += 1
        if chunk.content:
            console.print(chunk.content, end="", style="white")
        total_in += chunk.usage.tokens_in
        total_out += chunk.usage.tokens_out
        total_cost += chunk.usage.cost_usd

    if chunks_received == 0:
        console.print("[yellow]No response received.[/yellow]")
        sys.exit(1)

    console.print()
    console.print("[dim]---[/dim]")
    console.print(f"[dim]Tokens: {total_in} in, {total_out} out. Cost: ${total_cost:.4f}[/dim]")

    # Save bitácora from the audit trail
    from datetime import datetime

    from arnes.thread import Thread

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bitacora_path = f"bitacora-stream-{specialist.lstrip('@')}-{ts}.md"
    # Use stream_with_audit to get the thread
    chunks_list = []
    async for chunk in harness.stream(specialist, {"task": task}):
        chunks_list.append(chunk)

    # For audit, we use the _events sink pattern — but for CLI simplicity,
    # we save the streaming output as a simple markdown log
    audit_content = f"# ARNES Stream Bitácora — {specialist}\n\n"
    audit_content += f"**Timestamp:** {ts}\n"
    audit_content += f"**Task:** {task}\n\n"
    audit_content += "## Response\n\n"
    audit_content += "```json\n"
    audit_content += "".join(c.content for c in chunks_list)
    audit_content += "\n```\n\n"
    audit_content += f"## Usage\n\n"
    audit_content += f"- Tokens in: {total_in}\n"
    audit_content += f"- Tokens out: {total_out}\n"
    audit_content += f"- Cost: ${total_cost:.4f}\n"

    Path(bitacora_path).write_text(audit_content, encoding="utf-8")
    console.print(f"\n[cyan]Bitácora saved to:[/cyan] {bitacora_path}")


@cli.command()
@click.argument("playbook_path", type=click.Path(exists=True))
def eval(playbook_path: str) -> None:
    """Run playbook with mock LLM for testing (no network, $0 cost)."""
    asyncio.run(
        _run_playbook(playbook_path, "mock/test", 0.0, mock=True, interactive=False, output=None)
    )


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


async def _serve_mcp(transport: str, host: str, port: int) -> None:
    """Run the MCP server."""
    try:
        from arnes.mcp.server import ArnesMCPServer
    except ImportError as e:
        console.print(f"[red]MCP server dependencies not installed:[/red] {e}")
        console.print("Install with: [cyan]pip install arnes[mcp][/cyan]")
        sys.exit(1)

    server = ArnesMCPServer()

    if transport == "stdio":
        sys.stderr.write("ARNES MCP server running on stdio\n")
        sys.stderr.flush()
        # serve_stdio is attached at runtime by ArnesMCPServer._attach_serve_methods.
        await server.serve_stdio()  # type: ignore[attr-defined]
    else:
        console.print(f"[cyan]ARNES MCP server[/cyan] running on http://{host}:{port}")
        await server.serve_http(host, port)  # type: ignore[attr-defined]


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
    stream: bool = False,
) -> None:
    """Execute a playbook and print results.

    When ``stream=True``, uses :meth:`PlaybookExecutor.stream` to yield
    step-level events as each step completes (instead of buffering the
    whole run behind a spinner). The final ``PlaybookRunResult`` is
    captured from the last yield for stats + bitácora persistence.
    """
    # Compile
    try:
        playbook = PlaybookCompiler.from_file(playbook_path)
    except PlaybookCompileError as e:
        console.print(f"[red]✗ Compile error:[/red]\n{e}")
        sys.exit(1)

    # The schema validator guarantees metadata is non-None after compile.
    assert playbook.metadata is not None

    console.print(
        Panel.fit(
            f"[bold cyan]ARNES[/bold cyan] — Executing playbook\n"
            f"  [dim]Name:[/dim] {playbook.metadata.name}\n"
            f"  [dim]Objective:[/dim] {playbook.metadata.objective}\n"
            f"  [dim]Model:[/dim] {model}\n"
            f"  [dim]Budget:[/dim] ${budget:.2f}",
            border_style="cyan",
        )
    )

    # Setup provider
    if mock or model.startswith("mock/"):
        provider: LLMProvider = _SchemaValidMockLLMProvider()
    else:
        provider = get_provider(model)

    # Execute
    executor = PlaybookExecutor(
        provider=provider,
        cost_budget=CostBudget(task_budget_usd=budget),
        interactive=interactive,
    )

    if stream:
        result = await _run_playbook_streaming(executor, playbook)
    else:
        with console.status("[cyan]Executing...[/cyan]"):
            result = await executor.run(playbook)

    # Print results
    if result.success:
        console.print("\n[green]✅ Manual executed[/green]")
    else:
        console.print("\n[red]❌ Execution failed[/red]")
        if result.error:
            console.print(f"  [red]Error:[/red] {result.error}")

    # Stats
    console.print(f"\n[dim]Steps executed:[/dim] {result.steps_executed}")
    console.print(f"[dim]Steps failed:[/dim] {result.steps_failed}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.2f}s")
    console.print(f"[dim]Tokens in/out:[/dim] {result.total_tokens_in}/{result.total_tokens_out}")
    console.print(f"[dim]Total cost:[/dim] ${result.total_cost_usd:.4f}")

    # Save bitácora
    if output:
        Path(output).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Bitácora saved to:[/cyan] {output}")
    else:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = f"bitacora-{playbook.metadata.name}-{ts}.md"
        Path(default_path).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Bitácora saved to:[/cyan] {default_path}")


async def _run_playbook_streaming(
    executor: PlaybookExecutor,
    playbook: Playbook,
) -> PlaybookRunResult:
    """Run a playbook in streaming mode, printing step events as they arrive.

    Uses :meth:`PlaybookExecutor.stream` to yield ``Event`` objects as each
    step completes, then captures the final ``PlaybookRunResult`` from the
    last yield. Best-effort: parallel branches stream in completion order,
    not definition order.
    """
    from arnes.thread.events import (
        RunCompletedEvent,
        RunFailedEvent,
        StepCompletedEvent,
        StepFailedEvent,
    )

    final_result: PlaybookRunResult | None = None
    console.print("[cyan]Streaming...[/cyan]\n[dim]---[/dim]")

    async for item in executor.stream(playbook):
        if isinstance(item, PlaybookRunResult):
            final_result = item
            break
        # Print step-level transitions as they happen
        if isinstance(item, StepCompletedEvent):
            console.print(f"  [green]✓[/green] step_completed: {item.step_id}")
        elif isinstance(item, StepFailedEvent):
            console.print(
                f"  [red]✗[/red] step_failed: {item.step_id} — {item.data.get('error', '')}"
            )
        elif isinstance(item, RunCompletedEvent):
            console.print("  [green]✓[/green] run_completed")
        elif isinstance(item, RunFailedEvent):
            console.print(f"  [red]✗[/red] run_failed — {item.data.get('error', '')}")
        else:
            # Other event types (StepStarted, AssistantMessage, CostThreshold, etc.)
            # are not printed to keep the streaming output focused on step transitions.
            console.print(f"  [dim]·[/dim] {item.type.value}")

    console.print("[dim]---[/dim]")
    assert final_result is not None, "stream() must yield a final PlaybookRunResult"
    return final_result


class _SchemaValidMockLLMProvider(LLMProvider):
    """Mock LLM provider that returns schema-valid JSON for each specialist.

    Used by `arnes run --mock` for testing without network calls.
    Detects which specialist is being invoked based on system prompt content.
    """

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1

        # Detect specialist from system prompt
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = '{"files": [{"path": "out.py", "language": "python", "content": "# Mock code\\npass"}], "summary": "Mock implementation", "assumptions": [], "warnings": []}'
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "Mock review: looks good"}'
        elif "@tester" in sys_content:
            content = '{"test_files": [{"path": "test_mock.py", "content": "def test_mock():\\n    pass"}], "test_results": {"passed": 1, "failed": 0, "skipped": 0, "failures": []}, "summary": "Mock tests pass", "coverage_pct": 100.0}'
        elif "@debugger" in sys_content:
            content = '{"root_cause": "Mock root cause identified", "confidence": 0.95, "fix": {"file": "src/app.py", "line": 42, "original": "broken()", "fixed": "fixed()", "explanation": "Mock fix applied"}, "verification": "Run tests to verify", "alternative_causes": []}'
        else:
            content = '{"result": "mock output"}'

        tokens_in = sum(len(m.content) // 4 for m in messages)
        tokens_out = len(content) // 4

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,
                model=model,
                cached=False,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock"]

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Default streaming: yield the full response in a single chunk.

        Matches the ``MockLLMProvider.stream_complete`` contract. Real
        token-by-token streaming is available in ``OllamaProvider`` and
        ``LiteLLMProvider``; this mock yields the full response on first
        iteration. AG-UI transport support lands in v0.2.
        """
        response = await self.complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_schema=response_schema,
            **kwargs,
        )
        yield response


def _scaffold_manual(name: str, lang: str) -> None:
    """Create a new playbook file from template."""
    path = Path("manuals") / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        console.print(f"[yellow]File already exists: {path}[/yellow]")
        sys.exit(1)

    template = _MANUAL_TEMPLATE_EN if lang == "en" else _MANUAL_TEMPLATE_ES
    path.write_text(template.format(name=name), encoding="utf-8")
    console.print(f"[green]✓[/green] Created: [cyan]{path}[/cyan]")
    console.print("\nEdit it and run with:")
    console.print(f"  [dim]arnes run {path}[/dim]")


def _init_project() -> None:
    """Initialize a new ARNES project structure."""
    console.print("[bold cyan]ARNES — Initializing project[/bold cyan]\n")

    dirs = ["manuals", "bitacoras"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
        console.print(f"  [green]✓[/green] Created: {d}/")

    # Create example playbook
    example = Path("manuals") / "hello-world.yaml"
    if not example.exists():
        example.write_text(_MANUAL_TEMPLATE_EN.format(name="hello-world"), encoding="utf-8")
        console.print(f"  [green]✓[/green] Created: {example}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit manuals/hello-world.yaml")
    console.print("  2. Run: [cyan]arnes run manuals/hello-world.yaml[/cyan]")
    console.print("  3. List specialists: [cyan]arnes list specialists[/cyan]")


_MANUAL_TEMPLATE_EN = """\
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


_MANUAL_TEMPLATE_ES = """\
# {name}.yaml — Manual de ARNES
# Documentación: https://github.com/frangelbarrera/ARNES#readme

name: {name}
objective: Describe qué hace este manual
budget_usd: 0.50

steps:
  - id: paso_1
    specialist: "@planner"
    input:
      task: "Describe la tarea a planificar"

  - id: paso_2
    specialist: "@coder"
    input: "{{{{ steps.paso_1.output }}}}"
    requires: [paso_1]

  - id: paso_3
    specialist: "@reviewer"
    input:
      code: "{{{{ steps.paso_2.output }}}}"
"""


if __name__ == "__main__":
    cli()
