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
import shutil
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
    Event,
    EventType,
    RunCompletedEvent,
    RunFailedEvent,
    StepCompletedEvent,
    StepFailedEvent,
    StepStartedEvent,
)
from arnes.tools.base import ToolContext, ToolRegistry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)

# Default Docker image used by the ShellTool sandbox. The image is expected
# to be present locally (built via `docker build -t arnes-sandbox:latest .`
# from the project's Dockerfile.sandbox). The ShellTool falls back to a
# clear error message if the daemon or image is missing at execution time.
DEFAULT_SANDBOX_CONTAINER = "arnes-sandbox:latest"


def _is_docker_available() -> bool:
    """Return True if the ``docker`` CLI is on PATH.

    Used by the executor to decide whether to wire the Docker sandbox into
    the default ``ToolContext``. This is a presence check only — it does NOT
    verify the daemon is running or that ``arnes-sandbox:latest`` exists.
    The ``ShellTool`` surfaces a clear error if either is missing at
    execution time (``FileNotFoundError`` on ``docker run``).

    We deliberately avoid probing the daemon (``docker info`` / ``docker
    version``) here because:

    1. It spawns a subprocess on every ``PlaybookExecutor`` construction,
       which is wasteful for tests and high-throughput runs.
    2. The daemon may be temporarily down even if the CLI is installed —
       failing fast at construction time would prevent the user from
       running non-shell playbooks that don't need Docker at all.
    3. The ``ShellTool._execute_in_sandbox`` already handles the
       ``FileNotFoundError`` case (docker binary missing) and returns a
       actionable error message.
    """
    return shutil.which("docker") is not None


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
        sandbox_enabled: bool | None = None,
        sandbox_container: str | None = None,
    ) -> None:
        self.provider = provider or get_provider()
        self.specialist_registry = specialist_registry or get_default_specialist_registry()
        self.tool_registry = tool_registry or get_default_registry()
        self.cost_budget = cost_budget or CostBudget()
        self.interactive = interactive

        # Sandbox wiring (Issue 1 / FIX-R3-SEC).
        #
        # Default behaviour:
        #   - If ``sandbox_enabled`` is explicitly passed, honour it (caller
        #     knows best — e.g. tests, Harness, MCP server).
        #   - Otherwise, auto-detect: enable the Docker sandbox when the
        #     ``docker`` CLI is on PATH, fall back to non-sandboxed mode
        #     when it isn't.
        #
        # In non-sandboxed mode the ShellTool requires ``ARNES_DEV_MODE=1``
        # as a double-gate before it will execute commands locally. We log
        # a warning so operators know shell calls will be gated rather than
        # sandboxed.
        if sandbox_enabled is not None:
            self._sandbox_enabled = sandbox_enabled
            self._sandbox_container = sandbox_container or (
                DEFAULT_SANDBOX_CONTAINER if sandbox_enabled else None
            )
        elif _is_docker_available():
            self._sandbox_enabled = True
            self._sandbox_container = sandbox_container or DEFAULT_SANDBOX_CONTAINER
            logger.info(
                "sandbox_docker_detected",
                container=self._sandbox_container,
                mode="docker-tier1",
            )
        else:
            self._sandbox_enabled = False
            self._sandbox_container = None
            logger.warning(
                "sandbox_docker_unavailable",
                fallback="ARNES_DEV_MODE=1 required for local shell execution",
                hint="Install Docker or build arnes-sandbox:latest to enable the sandbox",
            )

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

        # Build tool context — sandbox state is detected once at executor
        # construction time (see __init__) and propagated to every
        # specialist invocation so the ShellTool can pick the right
        # execution path (Docker sandbox vs. gated local execution).
        ctx = ToolContext(
            thread_id=thread_holder[0].id,
            step_id=step.id,
            specialist=step.specialist,
            working_dir=".",
            sandbox_enabled=self._sandbox_enabled,
            sandbox_container=self._sandbox_container,
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
        """Execute parallel sub-steps concurrently with ``asyncio.gather``.

        Each sub-step gets its OWN thread_holder (a copy of the parent thread
        at this point) so appends are isolated — no race on the shared
        ``thread_holder[0]`` reference. After all sub-steps complete, their
        event deltas are merged back into the parent thread_holder in
        timestamp order. This preserves the audit-log pattern while
        enabling true parallelism (the previous implementation ran sub-steps
        sequentially in a for-loop, which was correct but not concurrent).

        ``Thread.append`` mutates in place (O(1) per append, replacing the
        old O(N²) ``[*self.events, event]`` rebuild). Because the sub-step
        coroutines mutate their own Thread objects, we MUST give each one
        an isolated copy (with its own ``events`` list reference) — sharing
        the parent reference would let every sub-step clobber the others'
        appends. The copy is shallow on the list (a new list of the same
        Event references); Events themselves are frozen pydantic models so
        sharing the references is safe.

        The shared ``cost_guard._events`` sink is drained by each sub-step's
        own ``_execute_step`` call; because ``_drain_middleware_events`` is
        synchronous, drains run atomically in the single-threaded asyncio
        loop. An event emitted by sub-step B's specialist may end up drained
        into sub-step A's thread_holder, but each event carries its own
        ``step_id`` (set by ``_emit_assistant_message`` from the
        ``ToolContext``) so the merged audit log is still correctly
        attributed — the delta is just a container for the merge, not an
        authoritative attribution.

        Emits ``PARALLEL_BRANCH_STARTED`` before ``asyncio.gather`` and
        ``PARALLEL_BRANCH_COMPLETED`` after the merge so the audit log
        marks the parallel block boundaries (previously these event types
        were defined but never instantiated).
        """
        if not step.parallel:
            return {"success": False, "error": "No parallel steps defined"}

        # Snapshot the parent thread so each sub-step's delta is exactly
        # the events it appends beyond this point. The parent thread already
        # has the outer StepStartedEvent(parallel) appended by _execute_step.
        parent_snapshot = thread_holder[0]
        parent_event_count = len(parent_snapshot.events)

        # Emit PARALLEL_BRANCH_STARTED so the audit log records the
        # parallel-block boundary. ``step_id`` is the outer parallel step's
        # id; sub-step ids live inside the ``sub_steps`` payload.
        thread_holder[0] = thread_holder[0].append(
            Event(
                type=EventType.PARALLEL_BRANCH_STARTED,
                thread_id=parent_snapshot.id,
                step_id=step.id,
                data={
                    "step_id": step.id,
                    "sub_step_ids": [s.id for s in step.parallel],
                    "sub_step_count": len(step.parallel),
                },
            )
        )
        # Re-snapshot so the STARTED event is part of every sub-step's
        # parent_event_count baseline (it belongs to the parent, not to
        # any individual sub-step's delta).
        parent_snapshot = thread_holder[0]
        parent_event_count = len(parent_snapshot.events)

        # Each sub-step gets its OWN Thread copy with a fresh events list.
        # ``Thread.append`` mutates in place, so without this copy every
        # sub-step would share the same parent.events list and clobber
        # each other. The new list contains the same Event references
        # (Events are frozen, so sharing is safe).
        sub_holders: list[list[Thread]] = [
            [Thread(id=parent_snapshot.id, events=list(parent_snapshot.events))]
            for _ in step.parallel
        ]

        # Run all sub-steps concurrently. return_exceptions=True so a single
        # failure doesn't cancel the others — every sub-step runs to
        # completion (or to its own failure) and we merge everything.
        coros = [
            self._execute_step(
                sub_step,
                sub_holders[i],
                outputs,
                cost_guard,
                playbook,
            )
            for i, sub_step in enumerate(step.parallel)
        ]
        raw_results = await asyncio.gather(*coros, return_exceptions=True)

        # Merge sub-step deltas back into the parent thread_holder in
        # timestamp order. Each delta is the events the sub-step appended
        # beyond the shared snapshot (StepStarted, AssistantMessage(s),
        # StepCompleted/Failed for the sub-step, plus any middleware events
        # it drained from the shared cost_guard sink).
        merged_events: list[Event] = []
        for holder in sub_holders:
            merged_events.extend(holder[0].events[parent_event_count:])
        # Stable sort by timestamp preserves intra-sub-step order for events
        # with identical timestamps (the natural audit order within a single
        # sub-step's lifecycle: Started → AssistantMessage → Completed).
        merged_events.sort(key=lambda e: e.timestamp)

        thread_holder[0] = thread_holder[0].extend(merged_events)

        # Emit PARALLEL_BRANCH_COMPLETED with the per-sub-step outcome so
        # the audit log marks the parallel-block end and records which
        # branches succeeded / failed.
        sub_step_outcomes: list[dict[str, Any]] = []
        all_success = True
        first_error: str | None = None
        outputs_map: dict[str, dict[str, Any]] = {}

        for sub_step, raw in zip(step.parallel, raw_results, strict=True):
            if isinstance(raw, BaseException):
                # A sub-step coroutine raised (shouldn't happen — _execute_step
                # catches exceptions — but defend against executor bugs).
                outputs_map[sub_step.id] = {
                    "output": None,
                    "success": False,
                    "error": str(raw),
                }
                sub_step_outcomes.append(
                    {"sub_step_id": sub_step.id, "success": False, "error": str(raw)}
                )
                all_success = False
                if first_error is None:
                    first_error = str(raw)
            else:
                outputs_map[sub_step.id] = {
                    "output": raw.get("output"),
                    "success": raw.get("success", False),
                    "error": raw.get("error"),
                }
                sub_step_outcomes.append(
                    {
                        "sub_step_id": sub_step.id,
                        "success": raw.get("success", False),
                        "error": raw.get("error"),
                    }
                )
                if not raw.get("success", False):
                    all_success = False
                    if first_error is None:
                        first_error = raw.get("error")

        thread_holder[0] = thread_holder[0].append(
            Event(
                type=EventType.PARALLEL_BRANCH_COMPLETED,
                thread_id=thread_holder[0].id,
                step_id=step.id,
                data={
                    "step_id": step.id,
                    "all_success": all_success,
                    "sub_step_outcomes": sub_step_outcomes,
                    "merged_event_count": len(merged_events),
                },
            )
        )

        result: dict[str, Any] = {
            "success": all_success,
            "output": outputs_map,
        }
        if first_error is not None:
            result["error"] = first_error
        return result

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
