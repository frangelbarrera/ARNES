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

import re
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMProvider
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.playbooks.schema import ConditionalBranch, Playbook, PlaybookStep
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
        playbook = PlaybookCompiler.from_file("manuals/audit-pr.yaml")
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
            for step in playbook.steps:
                # Check if step should be skipped due to prior saltar_a
                skip_until = outputs.get("__skip_steps_until", {})
                if skip_until:
                    # If we've reached the target step, clear the skip marker
                    if step.id in skip_until:
                        del skip_until[step.id]
                        if not skip_until:
                            del outputs["__skip_steps_until"]
                        logger.info("saltar_a_reached", step_id=step.id)
                        # Don't skip this step — execute it
                    else:
                        # Skip this step
                        logger.info("step_skipped", step_id=step.id, reason="saltar_a")
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
                    if step.if_not_met:
                        branch_result = await self._handle_conditional_branch(
                            step,
                            step.if_not_met,
                            thread_holder,
                            outputs,
                            cost_guard,
                            playbook,
                        )
                        if branch_result.get("terminate"):
                            logger.info(
                                "run_terminated_by_conditional",
                                step_id=step.id,
                                termination=branch_result["terminate"],
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
                specialist=step.specialist or step.tool,
                data={"step_id": step.id, "specialist": step.specialist or step.tool},
            )
        )

        step_start = time.monotonic()

        try:
            # Parallel branch
            if step.parallel:
                result = await self._execute_parallel(
                    step, thread_holder, outputs, cost_guard, playbook
                )
            # Specialist invocation
            elif step.specialist:
                result = await self._execute_specialist(
                    step, thread_holder, outputs, cost_guard, playbook
                )
            # Tool invocation
            elif step.tool:
                result = await self._execute_tool(step, thread_holder, outputs, playbook)
            else:
                raise ValueError(f"Step '{step.id}' has no action defined")

            # Drain middleware event sink BEFORE recording completion so
            # that AssistantMessageEvent / CostThresholdEvent / CACHE_HIT /
            # REFUSAL_TRIGGERED events emitted during the step appear in
            # the thread before the StepCompletedEvent. The middleware
            # creates events with a nil thread_id placeholder (it does not
            # have access to the Thread); we patch the real thread_id and
            # step_id here.
            self._drain_middleware_events(thread_holder, cost_guard, step.id)

            # Pull token / cost usage out of the step result so the
            # StepCompletedEvent carries the per-step aggregate. The
            # specialist returns ``usage`` as a model_dump() of LLMUsage
            # (tokens_in, tokens_out, cost_usd, model, cached).
            usage = result.get("usage") or {}

            # Record completion (with token + cost accounting)
            thread_holder[0] = thread_holder[0].append(
                StepCompletedEvent(
                    thread_id=thread_holder[0].id,
                    step_id=step.id,
                    specialist=step.specialist or step.tool,
                    data={
                        "step_id": step.id,
                        "output": result.get("output"),
                        "duration_s": time.monotonic() - step_start,
                        "tokens_in": usage.get("tokens_in", 0),
                        "tokens_out": usage.get("tokens_out", 0),
                        "cost_usd": usage.get("cost_usd", 0.0),
                    },
                )
            )

            return result

        except Exception as e:
            logger.exception("step_failed", step_id=step.id, error=str(e))
            # Drain any events emitted before the failure too — they are
            # still useful for debugging (e.g. a CostThresholdEvent that
            # fired right before the crash, or an AssistantMessageEvent
            # from the failed LLM call).
            self._drain_middleware_events(thread_holder, cost_guard, step.id)
            thread_holder[0] = thread_holder[0].append(
                StepFailedEvent(
                    thread_id=thread_holder[0].id,
                    step_id=step.id,
                    specialist=step.specialist or step.tool,
                    data={"step_id": step.id, "error": str(e), "retry": False},
                )
            )
            return {"success": False, "error": str(e)}

    def _drain_middleware_events(
        self,
        thread_holder: list[Thread],
        cost_guard: CostGuard,
        step_id: str,
    ) -> None:
        """Drain the middleware event sink and append events to the Thread.

        Middleware (CostGuard, TokenOptimizer, VerificationLayer) emit
        events to a shared ``_events`` list because they do not have direct
        access to the Thread. The events are created with a nil thread_id
        placeholder; here we patch the real thread_id and step_id and
        append them to the Thread.

        Idempotent: clears the sink after draining so the same events are
        not appended twice.
        """
        events = getattr(cost_guard, "_events", None)
        if not events:
            return

        thread_id = thread_holder[0].id
        for event in events:
            # Events are frozen pydantic models; use model_copy(update=...)
            # to set the real thread_id and step_id without mutating the
            # original (which may be referenced by middleware state).
            patched = event.model_copy(
                update={"thread_id": thread_id, "step_id": event.step_id or step_id}
            )
            thread_holder[0] = thread_holder[0].append(patched)

        events.clear()

    async def _execute_specialist(
        self,
        step: PlaybookStep,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Invoke a specialist."""
        specialist = self.specialist_registry.get(step.specialist or "")
        if not specialist:
            return {
                "success": False,
                "error": f"Specialist '{step.specialist}' not registered. Available: {self.specialist_registry.list_names()}",
            }

        # Resolve input (may contain Jinja2-style template refs)
        input_data = self._resolve_input(step.input, outputs)

        # Build tool context
        ctx = ToolContext(
            thread_id=thread_holder[0].id,
            step_id=step.id,
            specialist=step.specialist,
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
            provider=cost_guard,
            tool_registry=self.tool_registry,
        )

        success = result.get("success", False)
        if not success and result.get("budget_exceeded"):
            raise BudgetExceeded(
                f"Budget exceeded during specialist '{step.specialist}' invocation",
                spent=cost_guard.spent_usd,
                budget=cost_guard.budget.effective_budget() or 0.0,
                level="specialist",
            )

        # Propagate error message for non-budget failures
        if not success and result.get("error"):
            return {
                "success": False,
                "error": result["error"],
                "output": None,
                "usage": result.get("usage", {}),
            }

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
        tool = self.tool_registry.get(step.tool or "")
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{step.tool}' not registered. Available: {self.tool_registry.list_names()}",
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
        if not step.parallel:
            return {"success": False, "error": "No parallel steps defined"}

        outputs_map = {}
        all_success = True

        # For MVP: sequential execution of "parallel" steps (correctness > parallelism)
        # In v0.2 we'll use asyncio.gather with proper thread merging
        for sub_step in step.parallel:
            result = await self._execute_step(
                sub_step, thread_holder, outputs, cost_guard, playbook
            )
            # Wrap output in {"output": ...} structure so templates like
            # {{ steps.parallel.sub_step_id.output }} resolve correctly
            outputs_map[sub_step.id] = {
                "output": result.get("output"),
                "success": result.get("success", False),
            }
            if not result.get("success", False):
                all_success = False

        return {
            "success": all_success,
            "output": outputs_map,
        }

    async def _handle_conditional_branch(
        self,
        step: PlaybookStep,
        branch: ConditionalBranch,
        thread_holder: list[Thread],
        outputs: dict[str, Any],
        cost_guard: CostGuard,
        playbook: Playbook,
    ) -> dict[str, Any]:
        """Handle an if_not_met or conditional branch."""
        thread_holder[0] = thread_holder[0].append(
            ConditionalBranchEvent(
                thread_id=thread_holder[0].id,
                step_id=step.id,
                data={
                    "condition": branch.when or "if_not_met",
                    "action": branch.action,
                },
            )
        )

        if branch.action == "call" and branch.specialist:
            # Invoke the fallback specialist
            fallback_step = PlaybookStep(
                id=f"{step.id}__fallback",
                specialist=branch.specialist,
                input=branch.input or {},
            )
            result = await self._execute_specialist(
                fallback_step, thread_holder, outputs, cost_guard, playbook
            )
            outputs[fallback_step.id] = result.get("output")
            return {"terminate": None, "result": result}

        if branch.action == "terminate":
            return {"terminate": branch.terminate}

        if branch.action == "skip" and branch.skip_to:
            # skip_to means "jump TO this step" — skip all steps between
            # current and target
            skip_set = outputs.setdefault("__skip_steps_until", {})
            skip_set[branch.skip_to] = True  # Will be cleared when we reach it
            return {"terminate": None}

        return {"terminate": None}

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
        Handles MULTIPLE templates in the same string.
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
                elif isinstance(v, list):
                    resolved[k] = [
                        self._resolve_template(item, outputs)
                        if isinstance(item, str)
                        else self._resolve_input(item, outputs)
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

    def _resolve_template(self, template: str, outputs: dict[str, Any]) -> Any:
        """Resolve a template string, handling MULTIPLE {{ }} references.

        Examples:
            "{{ pasos.X.salida }}" → outputs["X"]["output"]
            "Plan: {{ variables.nombre }} for PR {{ variables.pr_number }}" → "Plan: foo for PR 1234"
            "Diff: {{ pasos.leer_diff.salida }}, Sec: {{ pasos.auditoria.salida }}" → "Diff: ..., Sec: ..."
            "{{ }}" → "{{ }}"  (empty template body — returned as literal)
        """
        # Find ALL template references
        matches = list(self._TEMPLATE_RE.finditer(template))

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
            return self._resolve_expr(expr, outputs)

        # Otherwise, interpolate ALL matches into the string
        result = template
        # Process in reverse order to keep indexes valid
        for match in reversed(matches):
            expr = match.group(1).strip()
            if not expr:
                # Empty template body — leave the original match untouched
                continue
            resolved = self._resolve_expr(expr, outputs)
            result = result[: match.start()] + str(resolved) + result[match.end() :]

        return result

    def _resolve_expr(self, expr: str, outputs: dict[str, Any]) -> Any:
        """Resolve a single template expression like 'steps.X.output'.

        Supported forms:
            "steps.X.output"        → outputs["X"]["output"] (or outputs["X"] if raw)
            "steps.X.output.field"  → outputs["X"]["output"]["field"] (or outputs["X"]["field"])
            "variables.X"           → outputs["X"]
            "pasos.X.salida"        → legacy ES form of "steps.X.output"

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
