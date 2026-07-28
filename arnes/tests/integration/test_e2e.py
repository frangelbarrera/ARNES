"""Integration tests for the full ARNES stack."""
from __future__ import annotations

import pytest

from arnes.llm.mock import MockLLMProvider
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.specialists.base import get_default_specialist_registry
from arnes.tools.registry import get_default_registry


class TestEndToEnd:
    """End-to-end integration tests with mock LLM."""

    @pytest.mark.asyncio
    async def test_full_playbook_run_with_mock(self):
        """Run a complete playbook with mock LLM and verify all components work."""
        provider = MockLLMProvider(default_response='{"result": "test"}')
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
        assert result.success is True
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
        import os
        from pathlib import Path

        manuales_dir = Path(__file__).parent.parent.parent / "manuales"
        if not manuales_dir.exists():
            pytest.skip(f"manuales/ dir not found at {manuales_dir}")

        provider = MockLLMProvider(default_response='{"result": "ok"}')
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

        provider = MockLLMProvider(default_response="cached")
        optimizer = TokenOptimizer(provider, enable_cache=True)

        msg = [LLMMessage(role="user", content="test")]

        # First call: miss
        await optimizer.complete(msg, model="mock/test")
        # Second call: hit
        await optimizer.complete(msg, model="mock/test")

        stats = optimizer.stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_cost_guard_stats_trackable(self):
        """Verify that CostGuard tracks spend."""
        from arnes.llm.base import LLMMessage
        from arnes.middleware.cost_guard import CostBudget, CostGuard

        provider = MockLLMProvider()
        guard = CostGuard(provider, budget=CostBudget(task_budget_usd=1.0))

        await guard.complete([LLMMessage(role="user", content="hi")], model="mock/test")

        stats = guard.stats()
        assert stats["calls_made"] == 1
        assert stats["spent_usd"] == 0.0  # Mock is free
        assert stats["paused"] is False
        assert stats["aborted"] is False
