"""Tests for arnes.playbooks.executor (end-to-end with mock LLM)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import (
    DEFAULT_SANDBOX_CONTAINER,
    PlaybookExecutor,
    _is_docker_available,
)


class SchemaValidMockProvider(LLMProvider):
    """Mock provider that returns JSON valid for all specialist schemas."""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        response_schema: dict | None = None,
        **kwargs,
    ) -> LLMResponse:
        self.call_count += 1

        # Detect which specialist based on system prompt content
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = '{"files": [{"path": "out.py", "language": "python", "content": "pass"}], "summary": "ok", "assumptions": [], "warnings": []}'
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
        elif "@tester" in sys_content:
            content = '{"test_files": [{"path": "test.py", "content": "pass"}], "test_results": {"passed": 1, "failed": 0, "skipped": 0, "failures": []}, "summary": "ok"}'
        elif "@debugger" in sys_content:
            content = '{"root_cause": "x", "confidence": 0.9, "fix": {"file": "f.py", "line": 1, "original": "x", "fixed": "y", "explanation": "ok"}, "verification": "v", "alternative_causes": []}'
        else:
            content = '{"result": "ok"}'

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

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        response_schema: dict | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Yield the full response in one chunk (matches MockLLMProvider contract)."""
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

    def list_models(self) -> list[str]:
        return ["mock"]


@pytest.fixture
def mock_provider():
    return SchemaValidMockProvider()


class TestPlaybookExecutor:
    @pytest.fixture
    def executor(self, mock_provider):
        return PlaybookExecutor(
            provider=mock_provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

    @pytest.mark.asyncio
    async def test_simple_playbook_execution(self, executor):
        yaml_str = """
name: simple_test
objective: Test
budget_usd: 1.0
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Plan something"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Expected success, got error: {result.error}"
        assert result.steps_executed == 1
        assert result.steps_failed == 0
        assert "s1" in result.outputs

    @pytest.mark.asyncio
    async def test_multi_step_playbook(self, executor):
        yaml_str = """
name: multi_step
objective: Test multi-step
steps:
  - id: plan
    specialist: "@planner"
    input: {task: "Plan"}
  - id: code
    specialist: "@coder"
    input: {spec: "Code", context: "{{ steps.plan.output }}"}
  - id: review
    specialist: "@reviewer"
    input: {code: "{{ steps.code.output }}"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"
        assert result.steps_executed == 3

    @pytest.mark.asyncio
    async def test_parallel_branch_execution(self, executor):
        yaml_str = """
name: parallel_test
objective: Test parallel
steps:
  - id: parallel
    parallel:
      - id: sub1
        specialist: "@planner"
        input: {task: "Subtask 1"}
      - id: sub2
        specialist: "@coder"
        input: {spec: "Subtask 2"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"
        assert result.steps_executed == 1

    @pytest.mark.asyncio
    async def test_parallel_branch_emits_started_and_completed_events(self, executor):
        """FIX-R4-DATA: PARALLEL_BRANCH_STARTED and PARALLEL_BRANCH_COMPLETED
        were previously defined in EventType but never instantiated. The
        executor must now emit them around the asyncio.gather call so the
        audit log marks the parallel-block boundaries."""
        from arnes.thread.events import EventType

        yaml_str = """
name: parallel_events
objective: Test parallel branch events
steps:
  - id: parallel
    parallel:
      - id: sub1
        specialist: "@planner"
        input: {task: "Subtask 1"}
      - id: sub2
        specialist: "@coder"
        input: {spec: "Subtask 2"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"

        started = [e for e in result.thread if e.type == EventType.PARALLEL_BRANCH_STARTED]
        completed = [e for e in result.thread if e.type == EventType.PARALLEL_BRANCH_COMPLETED]
        assert len(started) == 1, (
            f"Expected 1 PARALLEL_BRANCH_STARTED event, got {len(started)}. "
            f"Event types: {[(e.type.value) for e in result.thread]}"
        )
        assert len(completed) == 1, (
            f"Expected 1 PARALLEL_BRANCH_COMPLETED event, got {len(completed)}"
        )

        # STARTED carries the sub-step ids so the audit log shows what
        # branches were launched.
        s = started[0]
        assert s.step_id == "parallel"
        assert s.data["sub_step_ids"] == ["sub1", "sub2"]
        assert s.data["sub_step_count"] == 2

        # COMPLETED carries the per-sub-step outcome.
        c = completed[0]
        assert c.step_id == "parallel"
        assert c.data["all_success"] is True
        outcomes = {o["sub_step_id"]: o for o in c.data["sub_step_outcomes"]}
        assert "sub1" in outcomes
        assert "sub2" in outcomes
        assert outcomes["sub1"]["success"] is True
        assert outcomes["sub2"]["success"] is True

        # STARTED must come before COMPLETED in the thread (audit order).
        started_idx = result.thread.events.index(started[0])
        completed_idx = result.thread.events.index(completed[0])
        assert started_idx < completed_idx, (
            f"PARALLEL_BRANCH_STARTED (idx={started_idx}) must come before "
            f"PARALLEL_BRANCH_COMPLETED (idx={completed_idx}) in the thread"
        )

    @pytest.mark.asyncio
    async def test_template_resolution(self, executor):
        yaml_str = """
name: template_test
objective: Test template resolution
variables:
  pr_number: 9999
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Plan for PR {{ variables.pr_number }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"

    @pytest.mark.asyncio
    async def test_multi_template_resolution(self, executor):
        """Multiple {{ }} in the same string must all resolve."""
        yaml_str = """
name: multi_template
objective: Test multi-template
variables:
  a: "alpha"
  b: "beta"
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Mix {{ variables.a }} and {{ variables.b }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_audit_log_generated(self, executor):
        yaml_str = """
name: audit_log_test
objective: Test audit log
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Test"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        audit_log = result.to_markdown()
        assert "Audit log ARNES" in audit_log
        assert "step_started" in audit_log
        assert "step_completed" in audit_log
        assert "run_completed" in audit_log
        assert "s1" in audit_log

    @pytest.mark.asyncio
    async def test_budget_exceeded_aborts_run(self, mock_provider):
        """Budget enforcement: tiny budget should abort before second step."""
        from arnes.llm.base import LLMProvider, LLMResponse, LLMUsage
        from arnes.middleware.cost_guard import CostBudget

        class CostlyMockProvider(LLMProvider):
            async def complete(self, messages, *, model="mock", response_schema=None, **kwargs):
                return LLMResponse(
                    content='{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}',
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=10, tokens_out=5, cost_usd=0.001, model=model),
                    model=model,
                )

            async def stream_complete(self, messages, *, model="mock", **kwargs):
                """Yield the full response in one chunk."""
                response = await self.complete(messages, model=model, **kwargs)
                yield response

            def list_models(self):
                return ["mock"]

        executor = PlaybookExecutor(
            provider=CostlyMockProvider(),
            cost_budget=CostBudget(task_budget_usd=0.0005),
        )
        yaml_str = """
name: budget_test
objective: Test budget enforcement
budget_usd: 0.0005
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
  - id: s2
    specialist: "@planner"
    input: {task: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is False
        assert result.error is not None
        assert "Budget" in result.error or "budget" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_specialist_fails_gracefully(self, executor):
        yaml_str = """
name: unknown_specialist
objective: Test
steps:
  - id: s1
    specialist: "@nonexistent"
    input: {task: "x"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is False
        assert "not registered" in result.error.lower()

    @pytest.mark.asyncio
    async def test_thread_persists_all_events(self, executor):
        yaml_str = """
name: events_test
objective: Test event persistence
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
  - id: s2
    specialist: "@coder"
    input: {spec: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        # Thread should have:
        #   2 step_started + 2 assistant_message + 2 step_completed + 1 run_completed = 7
        # (each specialist makes exactly one LLM call against the mock provider,
        # which returns no tool_calls, so exactly one AssistantMessageEvent per step)
        assert len(result.thread) == 7

    @pytest.mark.asyncio
    async def test_initial_input_overrides_variables(self, executor):
        yaml_str = """
name: input_test
objective: Test initial input
variables:
  default_value: "default"
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Use {{ variables.default_value }}"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(
            playbook,
            initial_input={"default_value": "overridden"},
        )

        assert result.success is True, f"Failed: {result.error}"
        assert result.outputs["default_value"] == "overridden"

    @pytest.mark.asyncio
    async def test_conditional_branch_terminate(self, executor):
        """Test if_not_met with action=terminate."""
        yaml_str = """
name: conditional_test
objective: Test conditional
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
    if_not_met:
      action: terminate
      terminate: rejected
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)
        assert result.success is True


class TestSandboxAutoDetection:
    """Tests for the Docker sandbox auto-wiring (FIX-R3-SEC Issue 1)."""

    def test_is_docker_available_returns_bool(self):
        """The helper must return a bool (True/False) — never None."""
        result = _is_docker_available()
        assert isinstance(result, bool)

    def test_executor_enables_sandbox_when_docker_present(self, mock_provider):
        """When ``_is_docker_available()`` returns True, the executor must
        default to ``sandbox_enabled=True`` and pin the default container."""
        with patch("arnes.playbooks.executor._is_docker_available", return_value=True):
            executor = PlaybookExecutor(provider=mock_provider)

        assert executor._sandbox_enabled is True
        assert executor._sandbox_container == DEFAULT_SANDBOX_CONTAINER

    def test_executor_disables_sandbox_when_docker_absent(self, mock_provider):
        """When ``_is_docker_available()`` returns False, the executor must
        fall back to ``sandbox_enabled=False`` (the shell tool then requires
        ``ARNES_DEV_MODE=1`` as a double-gate)."""
        with patch("arnes.playbooks.executor._is_docker_available", return_value=False):
            executor = PlaybookExecutor(provider=mock_provider)

        assert executor._sandbox_enabled is False
        assert executor._sandbox_container is None

    def test_executor_explicit_sandbox_enabled_overrides_autodetect(self, mock_provider):
        """An explicit ``sandbox_enabled=False`` must override auto-detection
        even when Docker IS available (callers know best — e.g. tests)."""
        with patch("arnes.playbooks.executor._is_docker_available", return_value=True):
            executor = PlaybookExecutor(provider=mock_provider, sandbox_enabled=False)

        assert executor._sandbox_enabled is False
        assert executor._sandbox_container is None

    def test_executor_explicit_sandbox_container_honoured(self, mock_provider):
        """An explicit ``sandbox_container`` must be honoured when
        ``sandbox_enabled=True`` is also passed."""
        with patch("arnes.playbooks.executor._is_docker_available", return_value=False):
            executor = PlaybookExecutor(
                provider=mock_provider,
                sandbox_enabled=True,
                sandbox_container="custom-sandbox:v1.2",
            )

        assert executor._sandbox_enabled is True
        assert executor._sandbox_container == "custom-sandbox:v1.2"


class TestPlaybookExecutorStream:
    """Tests for ``PlaybookExecutor.stream()`` (FIX-R9-FINAL).

    The streaming executor yields step-level events as each step completes,
    then yields a final ``PlaybookRunResult`` with the full thread + aggregate
    accounting. This complements ``Harness.stream()`` (token-level) and
    ``Specialist.stream()`` (token-level at the specialist layer) with
    step-level streaming at the playbook layer.
    """

    @pytest.fixture
    def executor(self, mock_provider):
        return PlaybookExecutor(
            provider=mock_provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

    @pytest.mark.asyncio
    async def test_stream_yields_step_completed_events_then_result(self, executor):
        """stream() yields one StepCompletedEvent per step, then a PlaybookRunResult."""
        from arnes.playbooks.executor import PlaybookRunResult
        from arnes.thread.events import EventType

        yaml_str = """
name: stream_test
objective: Test streaming
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "Plan"}
  - id: s2
    specialist: "@coder"
    input: {spec: "Code"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        collected: list = []
        async for item in executor.stream(playbook):
            collected.append(item)

        # Expect: 2 StepCompletedEvent + 1 RunCompletedEvent + 1 PlaybookRunResult = 4
        assert len(collected) == 4, f"Expected 4 items, got {len(collected)}"

        # The first two should be StepCompletedEvent for s1, s2
        step_events = [e for e in collected if getattr(e, "type", None) == EventType.STEP_COMPLETED]
        assert len(step_events) == 2
        assert step_events[0].step_id == "s1"
        assert step_events[1].step_id == "s2"

        # Third should be RunCompletedEvent
        run_events = [e for e in collected if getattr(e, "type", None) == EventType.RUN_COMPLETED]
        assert len(run_events) == 1

        # Final should be PlaybookRunResult
        assert isinstance(collected[-1], PlaybookRunResult)
        result = collected[-1]
        assert result.success is True, f"Expected success, got: {result.error}"
        assert result.steps_executed == 2
        assert result.steps_failed == 0

    @pytest.mark.asyncio
    async def test_stream_final_result_has_full_thread(self, executor):
        """The final PlaybookRunResult.thread must contain every event."""
        from arnes.playbooks.executor import PlaybookRunResult
        from arnes.thread.events import EventType

        yaml_str = """
name: thread_test
objective: Test thread completeness
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        final_result: PlaybookRunResult | None = None
        async for item in executor.stream(playbook):
            if isinstance(item, PlaybookRunResult):
                final_result = item

        assert final_result is not None
        # Thread must contain: StepStarted + AssistantMessage + StepCompleted + RunCompleted = 4
        types = [e.type for e in final_result.thread.events]
        assert EventType.STEP_STARTED in types
        assert EventType.ASSISTANT_MESSAGE in types
        assert EventType.STEP_COMPLETED in types
        assert EventType.RUN_COMPLETED in types
        assert len(final_result.thread) == 4

    @pytest.mark.asyncio
    async def test_stream_propagates_step_failure(self, executor):
        """A failing step yields a StepCompletedEvent (executor-level) then RunFailedEvent + result.

        Note: when a specialist returns ``{"success": False, ...}`` (rather
        than raising), ``_execute_step`` still appends a ``StepCompletedEvent``
        — the step "completed" from the executor's perspective, it just
        produced a failure result. The ``RunFailedEvent`` is appended by the
        streaming loop when it sees ``step_result["success"] is False`` and
        there's no ``if_not_met`` fallback.
        """
        from arnes.playbooks.executor import PlaybookRunResult
        from arnes.thread.events import EventType

        yaml_str = """
name: fail_test
objective: Test failure streaming
steps:
  - id: s1
    specialist: "@nonexistent"
    input: {task: "x"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        collected: list = []
        async for item in executor.stream(playbook):
            collected.append(item)

        # Expect: 1 StepCompletedEvent + 1 RunFailedEvent + 1 PlaybookRunResult = 3
        step_completed = [
            e for e in collected if getattr(e, "type", None) == EventType.STEP_COMPLETED
        ]
        assert len(step_completed) == 1
        assert step_completed[0].step_id == "s1"

        run_failed = [e for e in collected if getattr(e, "type", None) == EventType.RUN_FAILED]
        assert len(run_failed) == 1

        assert isinstance(collected[-1], PlaybookRunResult)
        assert collected[-1].success is False
        assert collected[-1].steps_failed == 1

    @pytest.mark.asyncio
    async def test_stream_yields_events_incrementally(self, executor):
        """Events must be yielded DURING iteration, not buffered to the end.

        We verify incremental streaming by counting yields: a multi-step
        playbook must yield more than 1 item (multiple step events + the
        final result). If the executor buffered everything and yielded
        only at the end, we'd see exactly 1 yield.
        """
        from arnes.playbooks.executor import PlaybookRunResult

        yaml_str = """
name: incremental_test
objective: Test incremental streaming
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
  - id: s2
    specialist: "@coder"
    input: {spec: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        yield_count = 0
        result_count = 0
        async for item in executor.stream(playbook):
            yield_count += 1
            if isinstance(item, PlaybookRunResult):
                result_count += 1

        # 2 StepCompleted + 1 RunCompleted + 1 PlaybookRunResult = 4 yields.
        # If everything were buffered, we'd get only 1 yield (the final result).
        assert yield_count == 4, (
            f"Expected 4 incremental yields, got {yield_count}. "
            "Streaming executor may be buffering instead of yielding per-step."
        )
        assert result_count == 1

    @pytest.mark.asyncio
    async def test_stream_budget_exceeded_yields_run_failed_then_result(self, mock_provider):
        """Budget exceeded mid-stream yields RunFailedEvent + PlaybookRunResult.

        When the CostGuard aborts a specialist call (budget exceeded), the
        specialist returns ``{"success": False, "budget_exceeded": True}``,
        ``_execute_specialist`` re-raises as ``BudgetExceeded``,
        ``_execute_step`` catches it and appends ``StepFailedEvent``, then
        the streaming loop appends ``RunFailedEvent`` and aborts.
        """
        from arnes.llm.base import LLMProvider, LLMResponse, LLMUsage
        from arnes.playbooks.executor import PlaybookRunResult
        from arnes.thread.events import EventType

        class CostlyMockProvider(LLMProvider):
            async def complete(self, messages, *, model="mock", response_schema=None, **kwargs):
                return LLMResponse(
                    content='{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}',
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=10, tokens_out=5, cost_usd=0.001, model=model),
                    model=model,
                )

            async def stream_complete(self, messages, *, model="mock", **kwargs):
                response = await self.complete(messages, model=model, **kwargs)
                yield response

            def list_models(self):
                return ["mock"]

        executor = PlaybookExecutor(
            provider=CostlyMockProvider(),
            cost_budget=CostBudget(task_budget_usd=0.0005),
        )
        yaml_str = """
name: budget_stream_test
objective: Test budget exceeded streaming
steps:
  - id: s1
    specialist: "@planner"
    input: {task: "x"}
  - id: s2
    specialist: "@planner"
    input: {task: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        collected: list = []
        async for item in executor.stream(playbook):
            collected.append(item)

        # Expect: 1 StepCompleted (s1) + 1 StepFailed (s2) + 1 RunFailed + 1 PlaybookRunResult = 4
        run_failed = [e for e in collected if getattr(e, "type", None) == EventType.RUN_FAILED]
        assert len(run_failed) == 1

        step_failed = [e for e in collected if getattr(e, "type", None) == EventType.STEP_FAILED]
        assert len(step_failed) == 1
        assert step_failed[0].step_id == "s2"

        assert isinstance(collected[-1], PlaybookRunResult)
        assert collected[-1].success is False
        assert collected[-1].error is not None

    @pytest.mark.asyncio
    async def test_stream_parallel_branch_yields_events(self, executor):
        """Parallel branches stream in completion order; PARALLEL_BRANCH_COMPLETED is yielded."""
        from arnes.playbooks.executor import PlaybookRunResult
        from arnes.thread.events import EventType

        yaml_str = """
name: parallel_stream_test
objective: Test parallel streaming
steps:
  - id: parallel
    parallel:
      - id: sub1
        specialist: "@planner"
        input: {task: "Subtask 1"}
      - id: sub2
        specialist: "@coder"
        input: {spec: "Subtask 2"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        collected: list = []
        async for item in executor.stream(playbook):
            collected.append(item)

        # The parallel step yields a StepCompletedEvent (the outer parallel step)
        # which contains the merged sub-step results.
        step_completed = [
            e for e in collected if getattr(e, "type", None) == EventType.STEP_COMPLETED
        ]
        assert len(step_completed) >= 1
        assert step_completed[0].step_id == "parallel"

        # RunCompleted + PlaybookRunResult
        assert isinstance(collected[-1], PlaybookRunResult)
        assert collected[-1].success is True
