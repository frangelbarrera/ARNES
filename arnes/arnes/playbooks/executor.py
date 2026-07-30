"""
ARNES Playbook Executor — runs a compiled Playbook as a DAG.

The executor:
1. Walks the playbook steps in order.
2. For each step, invokes the specialist or tool.
3. Applies conditional branches (if/elif/else).
4. Runs parallel branches concurrently.
5. Retry execution: v0.2 (schemas defined).
6. HITL execution: v0.2 (schemas defined).
7. Tracks budget via CostGuard.
8. Appends events to the Thread.
9. Returns a PlaybookRunResult with full trace.

The executor is async and supports both fire-and-forget and streaming modes.

Helpers (split out for the >500-line rule, SPLIT-R12):

- ``arnes.playbooks.result``: ``PlaybookRunResult`` model.
- ``arnes.playbooks.sandbox``: ``DEFAULT_SANDBOX_CONTAINER`` + ``_is_docker_available``.
- ``arnes.playbooks.events``: ``_drain_middleware_events`` + ``_filter_internal_keys``.
- ``arnes.playbooks.template``: ``_TEMPLATE_RE`` + ``_resolve_input`` / ``_resolve_template`` /
  ``_resolve_expr``.

These names are re-exported by this module for backwards compatibility, so
``from arnes.playbooks.executor import PlaybookRunResult`` (and the other
historical spellings) continue to work.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

from arnes.llm.base import LLMProvider
from arnes.llm.factory import get_provider
from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
from arnes.playbooks.events import _drain_middleware_events, _filter_internal_keys
from arnes.playbooks.result import PlaybookRunResult
from arnes.playbooks.sandbox import DEFAULT_SANDBOX_CONTAINER, _is_docker_available
from arnes.playbooks.schema import ConditionalBranch, Playbook, PlaybookStep
from arnes.playbooks.template import _TEMPLATE_RE, _resolve_expr, _resolve_input, _resolve_template
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

# Public re-exports for backwards compatibility (SPLIT-R12). The canonical
# homes for these symbols are the dedicated modules above; the names are
# intentionally re-bound here so existing `from arnes.playbooks.executor
# import X` imports and `unittest.mock.patch("arnes.playbooks.executor.X")`
# patches keep working.
__all__ = [
    "DEFAULT_SANDBOX_CONTAINER",
    "_TEMPLATE_RE",
    "PlaybookExecutor",
    "PlaybookRunResult",
    "_drain_middleware_events",
    "_filter_internal_keys",
    "_is_docker_available",
    "_resolve_expr",
    "_resolve_input",
    "_resolve_template",
]


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
                outputs=_filter_internal_keys(outputs),
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
                outputs=_filter_internal_keys(outputs),
                error=str(e),
            )

    async def stream(  # noqa: PLR0915 - mirrors run() body; splitting hurts readability
        self,
        playbook: Playbook,
        *,
        initial_input: dict[str, Any] | None = None,
    ) -> AsyncIterator[Event | PlaybookRunResult]:
        """Stream playbook execution, yielding events as each step completes.

        Yields (in order):

        - For each step that runs: the ``StepCompletedEvent`` (or
          ``StepFailedEvent``) emitted when that step finishes. The
          event is the *last* event appended to the thread by
          :meth:`_execute_step` — intermediate events
          (``StepStartedEvent``, ``AssistantMessageEvent``,
          ``CostThresholdEvent``, …) stay in the thread and are visible
          in the final ``PlaybookRunResult.thread``.
        - ``RunCompletedEvent`` or ``RunFailedEvent`` at the end of the run
          (also appended to the thread).
        - Final yield: a :class:`PlaybookRunResult` with the full thread
          and aggregate accounting (steps_executed, tokens, cost).

        Best-effort streaming contract:

        - Steps are still executed sequentially in definition order
          (the ``run()`` semantics are preserved). What streaming gives
          you is the ability to surface each step's completion event
          to the caller *immediately* — without waiting for the whole
          playbook to finish.
        - Parallel branches stream in **completion order**, not
          definition order: when a parallel step finishes, the
          ``PARALLEL_BRANCH_COMPLETED`` event is yielded, but the
          per-sub-step ``StepCompletedEvent`` events were appended
          inside ``asyncio.gather`` and arrive in the merged-event
          timestamp order (see :meth:`_execute_parallel`).
        - The final ``PlaybookRunResult`` is always the last yield,
          even on failure / budget-exceeded.

        Per-token streaming of LLM responses within a step is available
        via :meth:`arnes.specialists.base.Specialist.stream`; this
        executor-level stream yields step-level events, not token-level
        events. The two can be composed: a UI that wants both
        token-by-token rendering AND a final bitácora can consume
        ``Specialist.stream()`` for the rendering and rely on the
        ``AssistantMessageEvent`` emitted into the thread (by both
        ``Specialist.run()`` and ``Specialist.stream()``) for the
        audit trail.

        Usage::

            executor = PlaybookExecutor(provider=p)
            async for event in executor.stream(playbook):
                if isinstance(event, PlaybookRunResult):
                    print(event.to_markdown())
                else:
                    print(f"event: {event.type.value}")
        """
        thread_holder: list[Thread] = [Thread.create()]
        start_time = time.monotonic()
        outputs: dict[str, Any] = dict(playbook.variables)
        if initial_input:
            outputs.update(initial_input)

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
                # Mirror run()'s skip-until logic verbatim.
                skip_until = outputs.get("__skip_steps_until", {})
                if skip_until:
                    if step.id in skip_until:
                        del skip_until[step.id]
                        if not skip_until:
                            del outputs["__skip_steps_until"]
                        logger.info("saltar_a_reached", step_id=step.id)
                    else:
                        logger.info("step_skipped", step_id=step.id, reason="saltar_a")
                        continue

                step_result = await self._execute_step(
                    step,
                    thread_holder,
                    outputs,
                    cost_guard,
                    playbook,
                )

                # Yield the last event appended by _execute_step. This is
                # the StepCompletedEvent or StepFailedEvent — exactly the
                # transition a streaming consumer cares about. (Earlier
                # events like StepStartedEvent remain in the thread for
                # the final PlaybookRunResult.)
                last_event = thread_holder[0].last()
                if last_event is not None:
                    yield last_event

                if step_result["success"]:
                    steps_executed += 1
                    outputs[step.id] = step_result.get("output")
                    usage = step_result.get("usage", {})
                    total_tokens_in += usage.get("tokens_in", 0)
                    total_tokens_out += usage.get("tokens_out", 0)
                    total_cost_usd += usage.get("cost_usd", 0.0)
                else:
                    steps_failed += 1
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
                        run_failed = RunFailedEvent(
                            thread_id=thread_holder[0].id,
                            step_id=step.id,
                            data={
                                "error": step_result.get("error", "Unknown error"),
                                "recoverable": False,
                            },
                        )
                        thread_holder[0] = thread_holder[0].append(run_failed)
                        aborted = True
                        abort_error = step_result.get("error")
                        # Yield the RunFailedEvent so streaming consumers
                        # see the abort transition immediately (mirrors
                        # the success path which yields RunCompletedEvent).
                        yield run_failed
                        break

            if not aborted:
                run_completed = RunCompletedEvent(
                    thread_id=thread_holder[0].id,
                    data={
                        "steps_executed": steps_executed,
                        "duration_s": time.monotonic() - start_time,
                        "total_tokens": total_tokens_in + total_tokens_out,
                        "total_cost_usd": total_cost_usd,
                    },
                )
                thread_holder[0] = thread_holder[0].append(run_completed)
                yield run_completed

            yield self._build_run_result(
                thread_holder[0],
                success=not aborted,
                steps_executed=steps_executed,
                steps_failed=steps_failed,
                start_time=start_time,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_cost_usd=total_cost_usd,
                outputs=outputs,
                error=abort_error,
            )
        except BudgetExceeded as e:
            logger.error("budget_exceeded", error=str(e), spent=e.spent, budget=e.budget)
            run_failed = RunFailedEvent(
                thread_id=thread_holder[0].id,
                data={
                    "error": f"Budget exceeded: {e}",
                    "spent_usd": e.spent,
                    "budget_usd": e.budget,
                    "level": e.level,
                },
            )
            thread_holder[0] = thread_holder[0].append(run_failed)
            yield run_failed
            yield self._build_run_result(
                thread_holder[0],
                success=False,
                steps_executed=steps_executed,
                steps_failed=steps_failed,
                start_time=start_time,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_cost_usd=total_cost_usd,
                outputs=outputs,
                error=str(e),
            )

    @staticmethod
    def _build_run_result(
        thread: Thread,
        *,
        success: bool,
        steps_executed: int,
        steps_failed: int,
        start_time: float,
        total_tokens_in: int,
        total_tokens_out: int,
        total_cost_usd: float,
        outputs: dict[str, Any],
        error: str | None,
    ) -> PlaybookRunResult:
        """Construct a :class:`PlaybookRunResult` from accumulated run state.

        Shared by :meth:`run` and :meth:`stream` to avoid duplicating the
        10-field construction (and to keep both methods under the ruff
        PLR0915 statement-count limit).
        """
        return PlaybookRunResult(
            thread=thread,
            success=success,
            steps_executed=steps_executed,
            steps_failed=steps_failed,
            duration_s=time.monotonic() - start_time,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_cost_usd=total_cost_usd,
            outputs=_filter_internal_keys(outputs),
            error=error,
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

        Thin delegating wrapper around
        :func:`arnes.playbooks.events._drain_middleware_events` (kept on the
        class so existing call sites that use ``self._drain_middleware_events``
        continue to work after SPLIT-R12).

        Middleware (CostGuard, TokenOptimizer, VerificationLayer) emit
        events to a shared ``_events`` list because they do not have direct
        access to the Thread. The events are created with a nil thread_id
        placeholder; here we patch the real thread_id and step_id and
        append them to the Thread.

        Idempotent: clears the sink after draining so the same events are
        not appended twice.
        """
        _drain_middleware_events(thread_holder, cost_guard, step_id)

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
    # Template resolution (delegates to arnes.playbooks.template)
    # ============================================================

    # Backwards-compat attribute: stress tests and downstream code may
    # reference ``PlaybookExecutor._TEMPLATE_RE`` directly. The canonical
    # home is now ``arnes.playbooks.template._TEMPLATE_RE``.
    _TEMPLATE_RE = _TEMPLATE_RE

    def _resolve_input(
        self,
        input_value: dict[str, Any] | str | None,
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve Jinja2-style template references in input.

        Thin delegating wrapper around
        :func:`arnes.playbooks.template._resolve_input` (kept on the class
        so existing ``self._resolve_input(...)`` call sites and stress
        tests that drive ``executor._resolve_template`` directly continue
        to work after SPLIT-R12).

        Example: "{{ pasos.leer_diff.salida }}" -> outputs["leer_diff"]["output"]
        Handles MULTIPLE templates in the same string.
        """
        return _resolve_input(input_value, outputs)

    def _resolve_template(self, template: str, outputs: dict[str, Any]) -> Any:
        """Resolve a template string, handling MULTIPLE {{ }} references.

        Thin delegating wrapper around
        :func:`arnes.playbooks.template._resolve_template`.

        Examples:
            "{{ pasos.X.salida }}" -> outputs["X"]["output"]
            "Plan: {{ variables.nombre }} for PR {{ variables.pr_number }}" -> "Plan: foo for PR 1234"
            "Diff: {{ pasos.leer_diff.salida }}, Sec: {{ pasos.auditoria.salida }}" -> "Diff: ..., Sec: ..."
            "{{ }}" -> "{{ }}"  (empty template body — returned as literal)
        """
        return _resolve_template(template, outputs)

    def _resolve_expr(self, expr: str, outputs: dict[str, Any]) -> Any:
        """Resolve a single template expression like 'steps.X.output'.

        Thin delegating wrapper around
        :func:`arnes.playbooks.template._resolve_expr`.

        Supported forms:
            "steps.X.output"        -> outputs["X"]["output"] (or outputs["X"] if raw)
            "steps.X.output.field"  -> outputs["X"]["output"]["field"] (or outputs["X"]["field"])
            "variables.X"           -> outputs["X"]
            "pasos.X.salida"        -> legacy ES form of "steps.X.output"

        See the standalone function's docstring for the full semantics
        (leading-prefix-only stripping, virtual ``output`` accessor for
        step refs, etc.).
        """
        return _resolve_expr(expr, outputs)
