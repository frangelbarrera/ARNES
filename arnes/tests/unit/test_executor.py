"""Tests for arnes.playbooks.executor (end-to-end with mock LLM)."""
from __future__ import annotations

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor


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
            # Generic valid JSON
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

    def list_models(self) -> list[str]:
        return ["mock"]


class TestPlaybookExecutor:
    @pytest.fixture
    def mock_provider(self):
        return SchemaValidMockProvider()

    @pytest.fixture
    def executor(self, mock_provider):
        return PlaybookExecutor(
            provider=mock_provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

    @pytest.mark.asyncio
    async def test_simple_playbook_execution(self, executor):
        yaml_str = """
nombre: simple_test
objetivo: Test
budget_usd: 1.0
pasos:
  - id: s1
    especialista: "@planner"
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
nombre: multi_step
objetivo: Test multi-step
pasos:
  - id: plan
    especialista: "@planner"
    input: {task: "Plan"}
  - id: code
    especialista: "@coder"
    input: {spec: "Code", context: "{{ pasos.plan.salida }}"}
  - id: review
    especialista: "@reviewer"
    input: {codigo: "{{ pasos.code.salida }}"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"
        assert result.steps_executed == 3

    @pytest.mark.asyncio
    async def test_parallel_branch_execution(self, executor):
        yaml_str = """
nombre: parallel_test
objetivo: Test parallel
pasos:
  - id: parallel
    paralelo:
      - id: sub1
        especialista: "@planner"
        input: {task: "Subtask 1"}
      - id: sub2
        especialista: "@coder"
        input: {spec: "Subtask 2"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"
        # The parallel step itself counts as 1 step in steps_executed
        assert result.steps_executed == 1

    @pytest.mark.asyncio
    async def test_template_resolution(self, executor):
        yaml_str = """
nombre: template_test
objetivo: Test template resolution
variables:
  pr_number: 9999
pasos:
  - id: s1
    especialista: "@planner"
    input:
      task: "Plan for PR {{ variables.pr_number }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Failed: {result.error}"

    @pytest.mark.asyncio
    async def test_multi_template_resolution(self, executor):
        """FIX-8: Multiple {{ }} in the same string must all resolve."""
        yaml_str = """
nombre: multi_template
objetivo: Test multi-template
variables:
  a: "alpha"
  b: "beta"
pasos:
  - id: s1
    especialista: "@planner"
    input:
      task: "Mix {{ variables.a }} and {{ variables.b }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_bitacora_generated(self, executor):
        yaml_str = """
nombre: bitacora_test
objetivo: Test bitácora
pasos:
  - id: s1
    especialista: "@planner"
    input: {task: "Test"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        bitacora = result.to_markdown()
        assert "Bitácora ARNES" in bitacora
        assert "step_started" in bitacora
        assert "step_completed" in bitacora
        assert "run_completed" in bitacora
        assert "s1" in bitacora

    @pytest.mark.asyncio
    async def test_budget_exceeded_aborts_run(self, mock_provider):
        """Budget enforcement: tiny budget should abort before second step."""
        from arnes.middleware.cost_guard import BudgetExceeded, CostBudget, CostGuard
        from arnes.llm.base import LLMMessage

        # Use a provider that charges fake cost to trigger budget exceeded
        class CostlyMockProvider(LLMProvider):
            async def complete(self, messages, *, model="mock", response_schema=None, **kwargs):
                return LLMResponse(
                    content='{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}',
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=10, tokens_out=5, cost_usd=0.001, model=model),
                    model=model,
                )
            def list_models(self):
                return ["mock"]

        executor = PlaybookExecutor(
            provider=CostlyMockProvider(),
            cost_budget=CostBudget(task_budget_usd=0.0005),  # Tiny budget
        )
        yaml_str = """
nombre: budget_test
objetivo: Test budget enforcement
budget_usd: 0.0005
pasos:
  - id: s1
    especialista: "@planner"
    input: {task: "x"}
  - id: s2
    especialista: "@planner"
    input: {task: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        # First call costs $0.001 > budget $0.0005, so should fail on s2 (pre-check)
        assert result.success is False
        assert result.error is not None
        assert "Budget" in result.error or "budget" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_specialist_fails_gracefully(self, executor):
        yaml_str = """
nombre: unknown_specialist
objetivo: Test
pasos:
  - id: s1
    especialista: "@nonexistent"
    input: {task: "x"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is False
        assert "not registered" in result.error.lower()

    @pytest.mark.asyncio
    async def test_thread_persists_all_events(self, executor):
        yaml_str = """
nombre: events_test
objetivo: Test event persistence
pasos:
  - id: s1
    especialista: "@planner"
    input: {task: "x"}
  - id: s2
    especialista: "@coder"
    input: {spec: "y"}
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        # Thread should have: step_started, step_completed, step_started, step_completed, run_completed = 5
        assert len(result.thread) == 5

    @pytest.mark.asyncio
    async def test_initial_input_overrides_variables(self, executor):
        yaml_str = """
nombre: input_test
objetivo: Test initial input
variables:
  default_value: "default"
pasos:
  - id: s1
    especialista: "@planner"
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
    async def test_conditional_branch_terminar(self, executor):
        """Test si_no_se_cumple with accion=terminar."""
        yaml_str = """
nombre: conditional_test
objetivo: Test conditional
pasos:
  - id: s1
    especialista: "@planner"
    input: {task: "x"}
    si_no_se_cumple:
      accion: terminar
      terminar: rechazado
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)
        # Should succeed (s1 succeeds, conditional not triggered)
        assert result.success is True
