"""ARNES CLI helpers — async runners + mock LLM provider.

This module owns the support code for the click command definitions in
``main.py`` (keeping ``main.py`` slim):

- :class:`_SchemaValidMockLLMProvider` — the mock LLM used by
  ``arnes run --mock`` / ``arnes eval`` / ``arnes stream --mock``.
- :func:`_run_playbook` / :func:`_run_playbook_streaming` — execute a
  playbook (buffered or streaming) and render the result.
- :func:`_stream_specialist` — token-by-token specialist streaming via
  :meth:`Harness.stream_with_audit`, with audit log persistence.
- :func:`_run_benchmark` — run the basic benchmark suite and print/save
  results.
- :func:`_serve_mcp` — start the MCP server (stdio or http transport).

Project scaffolding (``arnes init`` / ``arnes init --manual``) lives in
:mod:`arnes.cli.scaffolding`.

The shared :data:`console` and :data:`logger` are defined here so the
command definitions in ``main.py`` can import them without re-instantiating.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor, PlaybookRunResult
from arnes.playbooks.schema import Playbook

console = Console()
logger = structlog.get_logger(__name__)


# ============================================================
# Mock LLM provider for `arnes run --mock` / `arnes eval` / `arnes stream --mock`
# ============================================================


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
            content = (
                '{"files": [{"path": "out.py", "language": "python", '
                '"content": "# Mock code\\npass"}], "summary": "Mock implementation", '
                '"assumptions": [], "warnings": []}'
            )
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "Mock review: looks good"}'
        elif "@tester" in sys_content:
            content = (
                '{"test_files": [{"path": "test_mock.py", '
                '"content": "def test_mock():\\n    pass"}], '
                '"test_results": {"passed": 1, "failed": 0, "skipped": 0, "failures": []}, '
                '"summary": "Mock tests pass", "coverage_pct": 100.0}'
            )
        elif "@debugger" in sys_content:
            content = (
                '{"root_cause": "Mock root cause identified", "confidence": 0.95, '
                '"fix": {"file": "src/app.py", "line": 42, "original": "broken()", '
                '"fixed": "fixed()", "explanation": "Mock fix applied"}, '
                '"verification": "Run tests to verify", "alternative_causes": []}'
            )
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


# ============================================================
# Playbook execution helpers
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
    captured from the last yield for stats + audit-log persistence.
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

    # Save run log
    if output:
        Path(output).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Run log saved to:[/cyan] {output}")
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = f"arnes-run-{playbook.metadata.name}-{ts}.md"
        Path(default_path).write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"\n[cyan]Run log saved to:[/cyan] {default_path}")


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


# ============================================================
# Specialist streaming helper (CLI `arnes stream`)
# ============================================================


async def _stream_specialist(specialist: str, task: str, model: str, mock: bool) -> None:
    """Stream a specialist's response token-by-token and save a run log.

    Uses :meth:`Harness.stream_with_audit` so the audit trail is recorded in
    a real ``Thread`` (mutated in place as the stream is consumed) and the
    run log is rendered via :meth:`Thread.to_markdown`. This keeps the
    streaming CLI output consistent with the markdown produced by
    ``arnes run`` / ``PlaybookRunResult.to_markdown``.
    """
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

    # stream_with_audit returns (chunks, thread) where the thread is
    # mutated in place as the chunks are consumed. After the stream ends,
    # the thread carries a single AssistantMessageEvent with the full
    # accumulated content + final usage — exactly what the rest of the
    # audit-log system records for non-streaming runs.
    chunks_iter, thread = harness.stream_with_audit(specialist, {"task": task})

    total_in = 0
    total_out = 0
    total_cost = 0.0
    chunks_received = 0

    async for chunk in chunks_iter:
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

    # Save run log — same format as ``arnes run`` (Thread.to_markdown)
    # so streaming runs can be diffed against non-streaming runs.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_log_path = f"arnes-stream-{specialist.lstrip('@')}-{ts}.md"

    Path(run_log_path).write_text(thread.to_markdown(), encoding="utf-8")
    console.print(f"\n[cyan]Run log saved to:[/cyan] {run_log_path}")


# ============================================================
# Benchmark runner helper
# ============================================================


async def _run_benchmark(seeds: int, concurrent: int, manuals_dir: str | None, output: str) -> None:
    """Run the basic benchmark suite and print/save results.

    Pulls in :class:`arnes.benchmarks.BenchmarkRunner` lazily so the
    CLI startup cost stays low — ``arnes --version`` doesn't pay for
    importing the benchmark harness.
    """
    from arnes.benchmarks import BenchmarkRunner
    from arnes.benchmarks.suites.basic import BasicBenchmarkSuite

    suite_manuals = Path(manuals_dir) if manuals_dir else None
    suite = BasicBenchmarkSuite(manuals_dir=suite_manuals)

    playbooks = suite.playbooks()
    if not playbooks:
        manuals_display = manuals_dir or "<repo>/manuals"
        console.print(f"[red]✗[/red] No playbooks found in {manuals_display}")
        sys.exit(1)

    console.print(
        Panel.fit(
            f"[bold cyan]ARNES[/bold cyan] — Benchmark suite: {suite.name}\n"
            f"  [dim]Playbooks:[/dim] {len(playbooks)}\n"
            f"  [dim]Seeds:[/dim] {seeds}\n"
            f"  [dim]Concurrent:[/dim] {concurrent}\n"
            f"  [dim]Total runs:[/dim] {len(playbooks) * seeds}",
            border_style="cyan",
        )
    )

    runner = BenchmarkRunner()
    seed_values = list(range(seeds))
    with console.status("[cyan]Running benchmarks...[/cyan]"):
        results = await runner.run_suite(suite, seeds=seed_values, concurrent=concurrent)

    # Print results as a rich table.
    table = Table(title=f"Benchmark Results — {suite.name} suite")
    table.add_column("Playbook", style="cyan")
    table.add_column("Runs", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Avg dur (s)", justify="right")
    table.add_column("P95 dur (s)", justify="right")
    table.add_column("Avg tokens", justify="right")
    table.add_column("Avg cost", justify="right")

    for m in results.per_playbook:
        avg_tokens = m.avg_tokens_in + m.avg_tokens_out
        table.add_row(
            m.playbook_name,
            str(m.runs),
            f"{m.success_rate:.0%}",
            f"{m.avg_duration_s:.4f}",
            f"{m.p95_duration_s:.4f}",
            str(avg_tokens),
            f"${m.avg_cost_usd:.6f}",
        )

    console.print(table)
    console.print(
        f"\n[bold]Overall:[/bold] success={results.overall_success_rate:.0%}, "
        f"avg_dur={results.overall_avg_duration_s:.4f}s, "
        f"avg_tokens={results.overall_avg_tokens_in + results.overall_avg_tokens_out}, "
        f"avg_cost=${results.overall_avg_cost_usd:.6f}"
    )

    # Save JSON results.
    Path(output).write_text(results.to_json(), encoding="utf-8")
    console.print(f"\n[cyan]Results saved to:[/cyan] {output}")


# ============================================================
# MCP serve helper
# ============================================================


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


__all__ = [
    # Mock provider
    "_SchemaValidMockLLMProvider",
    # Benchmark
    "_run_benchmark",
    # Playbook execution
    "_run_playbook",
    "_run_playbook_streaming",
    # MCP
    "_serve_mcp",
    # Specialist streaming
    "_stream_specialist",
    # Shared infra
    "console",
    "logger",
]
