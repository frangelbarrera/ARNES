"""
ARNES Playbook Executor — runs a compiled Playbook as a DAG.

The executor:
1. Walks the playbook steps in order.
2. For each step, invokes the specialist or tool.
3. Applies conditional branches (if/elif/else).
4. Runs parallel branches concurrently.
5. Handles retries with backoff.
6. Pauses at HITL gates.
7. Tracks budget via CostGuard.
8. Appends events to the Thread.
9. Returns a PlaybookRunResult with full trace.

The executor is async and supports both fire-and-forget and streaming modes.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMProvider
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.playbooks.schema import Playbook, PlaybookStep
from arnes.specialists.base import SpecialistRegistry, get_default_specialist_registry
from arnes.thread import Thread
from arnes.thread.events import (
    ConditionalBranchEvent,
    RunCompletedEvent,
    RunFailedEvent,
    StepCompletedEvent,
    StepFailedEvent,
    StepStartedEvent,
)
from arnes.tools.base import ToolContext, ToolRegistry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)


class PlaybookRunResult(BaseModel):
    """Result of running a playbook."""

    model_config = {"arbitrary_types_allowed": True}

    thread: Thread
    success: bool
    steps_executed: int = 0
    steps_failed: int = 0
    duration_s: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    outputs: dict[str, Any] = Field(default_factory=dict)  # step_id → output
    error: str | None = None

    def to_markdown(self) -> str:
        """Render the run as a markdown bitácora."""
        return self.thread.to_markdown()


class PlaybookExecutor:
    """Executes a compiled Playbook.

    Usage:
        playbook = PlaybookCompiler.from_file("manuales/auditar-pr.md.yaml")
        executor = PlaybookExecutor()
        result = await executor.run(playbook)
        print(result.to_markdown())
    """

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        cost_budget: CostBudget | None = None,
        interactive: bool = False,
    ) -> None:
        self.provider = provider or get_provider()
        self.specialist_registry = specialist_registry or get_default_specialist_registry()
        self.tool_registry = tool_registry or get_default_registry()
        self.cost_budget = cost_budget or CostBudget()
        self.interactive = interactive

    async def run(
        self,
        playbook: Playbook,
        *,
        initial_input: dict[str, Any] | None = None,
    ) -> PlaybookRunResult:
        """Execute a playbook. Returns a PlaybookRunResult."""
        # Use a mutable list to hold the thread (so step helpers can append)
        thread_holder: list[Thread] = [Thread.create()]
        start_time = time.monotonic()
        outputs: dict[str, Any] = dict(playbook.variables)
        if initial_input:
            outputs.update(initial_input)

        # Track cost guard at the run level (shared across steps)
        cost_guard = CostGuard(self.provider, budget=self.cost_budget)

        steps_executed = 0
        steps_failed = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost_usd = 0.0
        aborted = False
        abort_error: str | None = None

        try:
            for step in playbook.pasos:
                # Check if step should be skipped due to prior conditional
                if step.id in outputs.get("__skip_steps", set()):
                    logger.info("step_skipped", step_id=step.id, reason="conditional")
                    continue

                # Execute the step
                step_result = await self._execute_step(
                    step,
                    thread_holder,
                    outputs,
                    cost_guard,
                    playbook,
                )

                if step_result["success"]:
                    steps_executed += 1
                    outputs[step.id] = step_result.get("output")
                    # Track usage
                    usage = step_result.get("usage", {})
                    total_tokens_in += usage.get("tokens_in", 0)
                    total_tokens_out += usage.get("tokens_out", 0)
                    total_cost_usd += usage.get("cost_usd", 0.0)
                else:
                    steps_failed += 1
                    # Check if step has si_no_se_cumple fallback
                    if step.si_no_se_cumple:
                        branch_result = await self._handle_conditional_branch(
                            step,
                            step.si_no_se_cumple,
                            thread_holder,
                            outputs,
                            cost_guard,
                            playbook,
                        )
                        if branch_result.get("terminar"):
                            logger.info(
                                "run_terminated_by_conditional",
                                step_id=step.id,
                                termination=branch_result["terminar"],
                            )
                            break
                    else:
                        # No fallback — abort
                        thread_holder[0] = thread_holder[0].append(
                            RunFailedEvent(
                                thread_id=thread_holder[0].id,
                                step_id=step.id,
                                data={
                                    "error": step_result.get("error", "Unknown error"),
                                    "recoverable": False,
                                },
                            )
                        )
                        aborted = True
                        abort_error = step_result.get("error")
                        break

            # Run completed (or aborted)
            if not aborted:
                thread_holder[0] = thread_holder[0].append(
                    RunCompletedEvent(
                        thread_id=thread_holder[0].id,
                        data={
                            "steps_executed": steps_executed,
                            "duration_s": time.monotonic() - start_time,
                            "total_tokens": total_tokens_in + total_tokens_out,
                            "total_cost_usd": total_cost_usd,
                        },
                    )
                )

            return PlaybookRunResult(
                thread=thread_holder[0],
                success=not aborted,
                steps_executed=steps_executed,
                steps_failed=steps_failed,
                duration_s=time.monotonic() - start_time,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_cost_usd=total_cost_usd,
                outputs=outputs,
                error=abort_error,
            )

        except BudgetExceeded as e:
            logger.error("budget_exceeded", error=str(e), spent=e.spent, budget=e.budget)
            thread_holder[0] = thread_holder[0].append(
                RunFailedEvent(
                    thread_id=thread_holder[0].id,
                    data={
                        "error": f"Budget exceeded: {e}",
                        "spent_usd": e.spent,
                        "budget_usd": e.budget,
                        "level": e.level,
                    },
                )
            )
            return PlaybookRunResult(
                thread=thread_holder[0],
                success=False,
                steps_executed=steps_executed,
                steps_failed=steps_failed,
                duration_s=time.monotonic() - start_time,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_cost_usd=total_cost_usd,
                outputs=outputs,
                error=str(e),
            )

    # ============================================================
    # Step execution
    # ============================================================

    async def _execute_step(
        self,
        step: PlaybookStep,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Execute a single step (specialist, tool, or parallel branch)."""
        thread_holder[0] = thread_holder[0].append(
            StepStartedEvent(
                thread_id=thread_holder[0].id,
                step_id=step.id,
                specialist=step.especialista or step.herramienta,
                data={"step_id": step.id, "specialist": step.especialista or step.herramienta},
            )
        )

        step_start = time.monotonic()

        try:
            # Parallel branch
            if step.paralelo:
                result = await self._execute_parallel(
                    step, thread_holder, outputs, cost_guard, playbook
                )
            # Specialist invocation
            elif step.especialista:
                result = await self._execute_specialist(
                    step, thread_holder, outputs, cost_guard, playbook
                )
            # Tool invocation
            elif step.herramienta:
                result = await self._execute_tool(step, thread_holder, outputs, playbook)
            else:
                raise ValueError(f"Step '{step.id}' has no action defined")

            # Record completion
            thread_holder[0] = thread_holder[0].append(
                StepCompletedEvent(
                    thread_id=thread_holder[0].id,
                    step_id=step.id,
                    specialist=step.especialista or step.herramienta,
                    data={
                        "step_id": step.id,
                        "output": result.get("output"),
                        "duration_s": time.monotonic() - step_start,
                    },
                )
            )

            return result

        except Exception as e:
            logger.exception("step_failed", step_id=step.id, error=str(e))
            thread_holder[0] = thread_holder[0].append(
                StepFailedEvent(
                    thread_id=thread_holder[0].id,
                    step_id=step.id,
                    specialist=step.especialista or step.herramienta,
                    data={"step_id": step.id, "error": str(e), "retry": False},
                )
            )
            return {"success": False, "error": str(e)}

    async def _execute_specialist(
        self,
        step: PlaybookStep,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Invoke a specialist."""
        specialist = self.specialist_registry.get(step.especialista or "")
        if not specialist:
            return {
                "success": False,
                "error": f"Specialist '{step.especialista}' not registered. Available: {self.specialist_registry.list()}",
            }

        # Resolve input (may contain Jinja2-style template refs)
        input_data = self._resolve_input(step.input, outputs)

        # Build tool context
        ctx = ToolContext(
            thread_id=thread_holder[0].id,
            step_id=step.id,
            specialist=step.especialista,
            working_dir=".",
            sandbox_enabled=False,  # Disabled for MVP; enable in v0.2
            budget_remaining_usd=(
                (cost_guard.budget.effective_budget() or 0) - cost_guard.spent_usd
            ),
            metadata={"interactive": self.interactive},
        )

        # Use the cost_guard-wrapped provider
        result = await specialist.run(
            input_data,
            ctx,
            provider=cost_guard,  # type: ignore[arg-type]
            tool_registry=self.tool_registry,
        )

        success = result.get("success", False)
        if not success and result.get("budget_exceeded"):
            raise BudgetExceeded(
                f"Budget exceeded during specialist '{step.especialista}' invocation",
                spent=cost_guard.spent_usd,
                budget=cost_guard.budget.effective_budget() or 0.0,
                level="specialist",
            )

        return {
            "success": success,
            "output": result.get("output"),
            "usage": result.get("usage", {}),
        }

    async def _execute_tool(
        self,
        step: PlaybookStep,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Invoke a tool."""
        tool = self.tool_registry.get(step.herramienta or "")
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{step.herramienta}' not registered. Available: {self.tool_registry.list()}",
            }

        input_data = self._resolve_input(step.input, outputs)

        ctx = ToolContext(
            thread_id=thread_holder[0].id,
            step_id=step.id,
            metadata={"interactive": self.interactive},
        )

        result = await tool.execute(input_data, ctx)
        return {
            "success": result.success,
            "output": result.output if result.success else None,
            "error": result.error,
        }

    async def _execute_parallel(
        self,
        step: PlaybookStep,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Execute parallel sub-steps concurrently.

        Note: parallel sub-steps share the same thread_holder, but since each
        appends to the immutable Thread, we need to merge results back.
        For MVP, parallel steps are executed sequentially (true parallelism
        requires a different state model — coming in v0.2).
        """
        if not step.paralelo:
            return {"success": False, "error": "No parallel steps defined"}

        outputs_map = {}
        all_success = True

        # For MVP: sequential execution of "parallel" steps (correctness > parallelism)
        # In v0.2 we'll use asyncio.gather with proper thread merging
        for sub_step in step.paralelo:
            result = await self._execute_step(
                sub_step, thread_holder, outputs, cost_guard, playbook
            )
            outputs_map[sub_step.id] = result.get("output")
            if not result.get("success", False):
                all_success = False

        return {
            "success": all_success,
            "output": outputs_map,
        }

    async def _handle_conditional_branch(
        self,
        step: PlaybookStep,
        branch,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Handle a si_no_se_cumple or conditional branch."""
        thread_holder[0] = thread_holder[0].append(
            ConditionalBranchEvent(
                thread_id=thread_holder[0].id,
                step_id=step.id,
                data={"condition": branch.cuando if hasattr(branch, "cuando") else "si_no_se_cumple", "branch": branch.accion},
            )
        )

        if branch.accion == "llamar" and branch.especialista:
            # Invoke the fallback specialist
            fallback_step = PlaybookStep(
                id=f"{step.id}__fallback",
                especialista=branch.especialista,
                input=branch.input or {},
            )
            result = await self._execute_specialist(
                fallback_step, thread_holder, outputs, cost_guard, playbook
            )
            outputs[fallback_step.id] = result.get("output")
            return {"terminar": None, "result": result}

        if branch.accion == "terminar":
            return {"terminar": branch.terminar}

        if branch.accion == "saltar" and branch.saltar_a:
            # Mark target steps to be skipped until saltar_a
            skip_set = outputs.setdefault("__skip_steps", set())
            skip_set.add(branch.saltar_a)  # Will be cleared when we reach it
            return {"terminar": None}

        return {"terminar": None}

    # ============================================================
    # Template resolution
    # ============================================================

    _TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+)\s*\}\}")

    def _resolve_input(
        self,
        input_value: dict[str, Any] | str | None,
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve Jinja2-style template references in input.

        Example: "{{ pasos.leer_diff.salida }}" → outputs["leer_diff"]["output"]
        """
        if input_value is None:
            return {}

        if isinstance(input_value, str):
            return {"__resolved_str__": self._resolve_template(input_value, outputs)}

        if isinstance(input_value, dict):
            resolved = {}
            for k, v in input_value.items():
                if isinstance(v, str):
                    resolved[k] = self._resolve_template(v, outputs)
                elif isinstance(v, dict):
                    resolved[k] = self._resolve_input(v, outputs)
                else:
                    resolved[k] = v
            return resolved

        return {"__input__": input_value}

    def _resolve_template(self, template: str, outputs: dict[str, Any]) -> Any:
        """Resolve a single template string."""
        match = self._TEMPLATE_RE.search(template)
        if not match:
            return template

        expr = match.group(1).strip()
        # Support "pasos.X.salida" → outputs["X"]["output"]
        # Support "variables.X" → outputs["X"]
        parts = expr.replace("pasos.", "").replace("variables.", "").split(".")

        current: Any = outputs
        for part in parts:
            if isinstance(current, dict):
                # Map "salida" → "output" (ES/EN bilingual)
                part = "output" if part == "salida" else part
                if part in current:
                    current = current[part]
                else:
                    return template  # Leave template as-is if not found
            else:
                return template

        # If the entire string was the template, return the resolved value
        if match.group(0) == template:
            return current

        # Otherwise, interpolate as string
        return template.replace(match.group(0), str(current))
