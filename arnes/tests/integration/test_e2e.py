"""Integration tests for the full ARNES stack."""
from __future__ import annotations

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry
from arnes.tools.registry import get_default_registry


class SchemaValidMockProvider(LLMProvider):
    """Mock provider that returns schema-valid JSON for each specialist."""

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

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=sum(len(m.content) // 4 for m in messages),
                tokens_out=len(content) // 4,
                cost_usd=0.0,
                model=model,
                cached=False,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock"]


class TestEndToEnd:
    """End-to-end integration tests with mock LLM."""

    @pytest.mark.asyncio
    async def test_full_playbook_run_with_mock(self):
        """Run a complete playbook with mock LLM and verify all components work."""
        provider = SchemaValidMockProvider()
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

        yaml_str = """
nombre: e2e_test
objetivo: End-to-end test
budget_usd: 0.50
pasos:
  - id: plan
    especialista: "@planner"
    input:
      task: "Plan a feature"
  - id: code
    especialista: "@coder"
    input:
      spec: "Implement the feature"
      context: "{{ pasos.plan.salida }}"
  - id: review
    especialista: "@reviewer"
    input:
      codigo: "{{ pasos.code.salida }}"
      enfoque: "Review for correctness"
  - id: test
    especialista: "@tester"
    input:
      codigo: "{{ pasos.code.salida }}"
      enfoque: "Write tests"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        # Verify success
        assert result.success is True, f"Failed: {result.error}"
        assert result.steps_executed == 4
        assert result.steps_failed == 0

        # Verify outputs were tracked
        assert "plan" in result.outputs
        assert "code" in result.outputs
        assert "review" in result.outputs
        assert "test" in result.outputs

        # Verify thread has all events
        # 4 step_started + 4 step_completed + 1 run_completed = 9
        assert len(result.thread) == 9

        # Verify bitácora is generated
        bitacora = result.to_markdown()
        assert "plan" in bitacora
        assert "code" in bitacora
        assert "review" in bitacora
        assert "test" in bitacora

    @pytest.mark.asyncio
    async def test_specialist_registry_has_all_5_specialists(self):
        registry = get_default_specialist_registry()
        specialists = registry.list()
        assert "@planner" in specialists
        assert "@coder" in specialists
        assert "@reviewer" in specialists
        assert "@tester" in specialists
        assert "@debugger" in specialists
        assert len(specialists) == 5

    @pytest.mark.asyncio
    async def test_tool_registry_has_all_5_tools(self):
        registry = get_default_registry()
        assert "shell" in registry
        assert "http" in registry
        assert "fs_read" in registry
        assert "fs_write" in registry
        assert "human_approval" in registry

    @pytest.mark.asyncio
    async def test_real_playbook_files_compile_and_run(self):
        """Test that the example playbooks in manuales/ compile and run."""
        from pathlib import Path

        manuales_dir = Path(__file__).parent.parent.parent / "manuales"
        if not manuales_dir.exists():
            pytest.skip(f"manuales/ dir not found at {manuales_dir}")

        provider = SchemaValidMockProvider()
        executor = PlaybookExecutor(
            provider=provider,
            cost_budget=CostBudget(task_budget_usd=1.0),
        )

        yaml_files = list(manuales_dir.glob("*.yaml"))
        assert len(yaml_files) >= 3, "Expected at least 3 example playbooks"

        for yaml_file in yaml_files:
            playbook = PlaybookCompiler.from_file(yaml_file)
            result = await executor.run(playbook)
            # All playbooks should complete successfully with mock LLM
            assert result.success is True, f"Playbook {yaml_file.name} failed: {result.error}"

    @pytest.mark.asyncio
    async def test_token_optimizer_stats_trackable(self):
        """Verify that TokenOptimizer tracks cache hits/misses."""
        from arnes.llm.base import LLMMessage
        from arnes.middleware.token_optimizer import TokenOptimizer

        provider = SchemaValidMockProvider()
        optimizer = TokenOptimizer(provider, enable_cache=True)

        msg = [LLMMessage(role="user", content="test")]

        # First call: miss
        await optimizer.complete(msg, model="mock")
        # Second call: hit
        await optimizer.complete(msg, model="mock")

        stats = optimizer.stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_cost_guard_stats_trackable(self):
        """Verify that CostGuard tracks spend."""
        from arnes.llm.base import LLMMessage
        from arnes.middleware.cost_guard import CostBudget, CostGuard

        provider = SchemaValidMockProvider()
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=1.0))

        await guard.complete([LLMMessage(role="user", content="hi")], model="mock")

        stats = guard.stats()
        assert stats["calls_made"] == 1
        assert stats["spent_usd"] == 0.0  # Mock is free
        assert stats["paused"] is False
        assert stats["aborted"] is False

    @pytest.mark.asyncio
    async def test_harness_high_level_api(self):
        """FIX-9: Harness class (renamed from Agent) works."""
        from arnes import Harness, HarnessConfig

        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=SchemaValidMockProvider(),
        )
        result = await harness.run("@planner", {"task": "Test"})

        assert result["success"] is True, f"Failed: {result.get('error')}"
        assert result["specialist"] == "@planner"

    @pytest.mark.asyncio
    async def test_cli_init_creates_valid_playbook(self, tmp_path, monkeypatch):
        """FIX-1: arnes init template must produce valid YAML."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ARNES_DEV_MODE", "1")

        from click.testing import CliRunner
        from arnes.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--manual", "test_playbook"])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        yaml_file = tmp_path / "manuales" / "test_playbook.md.yaml"
        assert yaml_file.exists()

        # The generated YAML must compile
        playbook = PlaybookCompiler.from_file(yaml_file)
        assert playbook.metadata.nombre == "test_playbook"

    @pytest.mark.asyncio
    async def test_tool_use_loop_in_specialist(self):
        """FIX-3: Specialist.run() supports tool-use loop (ReAct)."""
        from arnes.specialists.base import get_default_specialist_registry
        from arnes.tools.registry import get_default_registry
        from arnes.tools.base import ToolContext
        from arnes.thread import Thread

        # Mock provider that returns a tool call on first iteration,
        # then a final response on second
        class ToolUseMockProvider(LLMProvider):
            def __init__(self):
                self.call_count = 0

            async def complete(self, messages, *, model="mock", tools=None, response_schema=None, **kwargs):
                self.call_count += 1
                if self.call_count == 1 and tools:
                    return LLMResponse(
                        content="",
                        tool_calls=[{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "fs_read",
                                "arguments": '{"path": "test.txt"}',
                            },
                        }],
                        usage=LLMUsage(tokens_in=10, tokens_out=5, cost_usd=0.0, model=model),
                        model=model,
                    )
                # Final response — must be valid for @coder schema
                return LLMResponse(
                    content='{"files": [{"path": "out.py", "language": "python", "content": "pass"}], "summary": "ok", "assumptions": [], "warnings": []}',
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=20, tokens_out=10, cost_usd=0.0, model=model),
                    model=model,
                )

            def list_models(self):
                return ["mock"]

        # Setup: create a test file
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("hello world")

            registry = get_default_specialist_registry()
            # @coder declares tools=["fs_read", "fs_write", "shell"]
            specialist = registry.get("@coder")
            tool_registry = get_default_registry()

            thread = Thread.create()
            ctx = ToolContext(
                thread_id=thread.id,
                working_dir=tmpdir,
                metadata={"interactive": False},
            )

            provider = ToolUseMockProvider()
            result = await specialist.run(
                {"spec": "Read test.txt and write code"},
                ctx,
                provider=provider,
                tool_registry=tool_registry,
            )

            assert result["success"] is True, f"Failed: {result.get('error')}"
            assert provider.call_count == 2  # First (tool call) + second (final)
            assert len(result.get("tool_results", [])) == 1
            assert result["tool_results"][0]["tool"] == "fs_read"
            assert result["tool_results"][0]["success"] is True
