"""Tests for the actor-critic review loop (iterative refinement)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.playbooks.schema import PlaybookStep, ReviewLoop
from arnes.thread.events import EventType

# ============================================================
# Test fixtures: a mock provider that returns configurable verdicts
# ============================================================


class _ScriptedCriticProvider(LLMProvider):
    """Mock provider that returns scripted JSON for the @reviewer critic.

    The ``verdicts`` list is consumed in order: the first critic call
    returns verdicts[0], the second verdicts[1], etc. Actor calls (any
    system prompt that does NOT contain "@reviewer") return a fixed
    actor response and do NOT consume a verdict slot.
    """

    def __init__(self, verdicts: list[str], feedback: list[str] | None = None) -> None:
        self.verdicts = list(verdicts)
        self.feedback = feedback or ["Looks good."] * len(verdicts)
        self._critic_call_idx = 0

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
        **kwargs: Any,
    ) -> LLMResponse:
        sys_content = next((m.content for m in messages if m.role == "system"), "")

        # If the system prompt identifies the reviewer specialist, act as the critic.
        # We check the start of the prompt (not a substring search) because the
        # @planner prompt also mentions @reviewer in its list of available specialists.
        if sys_content.lstrip().startswith("You are @reviewer"):
            idx = min(self._critic_call_idx, len(self.verdicts) - 1)
            verdict = self.verdicts[idx]
            feedback = self.feedback[idx] if idx < len(self.feedback) else self.feedback[-1]
            content = f'{{"verdict": "{verdict}", "issues": [], "summary": "{feedback}"}}'
            self._critic_call_idx += 1
        else:
            # Act as the actor: return a simple JSON the specialist can parse.
            # Include enough fields to satisfy the planner schema if needed.
            content = '{"steps": [], "result": "actor output", "summary": "done"}'

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=len(sys_content) // 4,
                tokens_out=len(content) // 4,
                cost_usd=0.0,
                model=model,
                cached=False,
            ),
            model=model,
        )

    async def stream_complete(self, messages: list[LLMMessage], **kwargs: Any) -> Any:
        response = await self.complete(messages, **kwargs)
        yield response

    def list_models(self) -> list[str]:
        return ["mock"]


def _make_executor(provider: LLMProvider, *, loops: bool = False) -> PlaybookExecutor:
    return PlaybookExecutor(
        provider=provider,
        cost_budget=CostBudget(task_budget_usd=1.0),
        enable_review_loops=loops,
    )


# ============================================================
# ReviewLoop schema
# ============================================================


class TestReviewLoopSchema:
    def test_defaults(self) -> None:
        r = ReviewLoop()
        assert r.enabled is True
        assert r.critic == "@reviewer"
        assert r.max_iterations == 3
        assert r.pass_threshold == 0.8
        assert r.interactive is False

    def test_max_iterations_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ReviewLoop(max_iterations=0)
        with pytest.raises(ValidationError):
            ReviewLoop(max_iterations=11)

    def test_pass_threshold_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ReviewLoop(pass_threshold=1.5)
        with pytest.raises(ValidationError):
            ReviewLoop(pass_threshold=-0.1)

    def test_step_can_have_review(self) -> None:
        step = PlaybookStep(id="s1", specialist="@planner", review=ReviewLoop())
        assert step.review is not None
        assert step.review.critic == "@reviewer"


# ============================================================
# _effective_review_config
# ============================================================


class TestEffectiveReviewConfig:
    def test_no_review_when_flag_off_and_no_step_review(self) -> None:
        executor = _make_executor(_ScriptedCriticProvider(["approve"]), loops=False)
        step = PlaybookStep(id="s1", specialist="@planner")
        assert executor._effective_review_config(step) is None

    def test_default_loop_when_flag_on(self) -> None:
        executor = _make_executor(_ScriptedCriticProvider(["approve"]), loops=True)
        step = PlaybookStep(id="s1", specialist="@planner")
        cfg = executor._effective_review_config(step)
        assert cfg is not None
        assert cfg.critic == "@reviewer"
        assert cfg.max_iterations == 3

    def test_step_review_overrides_flag(self) -> None:
        executor = _make_executor(_ScriptedCriticProvider(["approve"]), loops=False)
        custom = ReviewLoop(critic="@security-auditor", max_iterations=5)
        step = PlaybookStep(id="s1", specialist="@planner", review=custom)
        cfg = executor._effective_review_config(step)
        assert cfg is not None
        assert cfg.critic == "@security-auditor"
        assert cfg.max_iterations == 5

    def test_step_review_disabled_overrides_flag(self) -> None:
        """If step.review.enabled is False, no loop runs even with flag on."""
        executor = _make_executor(_ScriptedCriticProvider(["approve"]), loops=True)
        step = PlaybookStep(
            id="s1",
            specialist="@planner",
            review=ReviewLoop(enabled=False),
        )
        assert executor._effective_review_config(step) is None

    def test_no_loop_for_tool_steps(self) -> None:
        """Review loops only apply to specialist steps, not tool steps."""
        executor = _make_executor(_ScriptedCriticProvider(["approve"]), loops=True)
        step = PlaybookStep(id="s1", tool="shell")
        assert executor._effective_review_config(step) is None


# ============================================================
# Verdict / score extraction
# ============================================================


class TestVerdictExtraction:
    def test_extract_verdict_approve(self) -> None:
        assert PlaybookExecutor._extract_verdict({"verdict": "approve"}) == "approve"

    def test_extract_verdict_request_changes(self) -> None:
        assert (
            PlaybookExecutor._extract_verdict({"verdict": "request_changes"}) == "request_changes"
        )

    def test_extract_verdict_missing(self) -> None:
        assert PlaybookExecutor._extract_verdict({}) == "unknown"

    def test_extract_score_normalized_from_10_scale(self) -> None:
        # A score of 9 on a 0-10 scale normalises to 0.9.
        assert PlaybookExecutor._extract_score({"score": 9}) == pytest.approx(0.9)

    def test_extract_score_already_0_1(self) -> None:
        assert PlaybookExecutor._extract_score({"score": 0.85}) == pytest.approx(0.85)

    def test_extract_score_missing(self) -> None:
        assert PlaybookExecutor._extract_score({}) is None

    def test_extract_feedback_from_summary(self) -> None:
        assert PlaybookExecutor._extract_feedback({"summary": "Good work"}) == "Good work"

    def test_extract_feedback_from_issues_list(self) -> None:
        feedback = PlaybookExecutor._extract_feedback({"issues": ["bug1", "bug2"]})
        assert "bug1" in feedback and "bug2" in feedback

    def test_extract_feedback_default(self) -> None:
        assert "No feedback" in PlaybookExecutor._extract_feedback({})


# ============================================================
# End-to-end review loop via executor.run()
# ============================================================


class TestReviewLoopExecution:
    @pytest.mark.asyncio
    async def test_loop_approves_on_first_iteration(self) -> None:
        """Critic approves immediately → 1 iteration, REVIEW_COMPLETED approved."""
        provider = _ScriptedCriticProvider(["approve"])
        executor = _make_executor(provider, loops=True)

        yaml_str = """
name: test_approve_first
objective: Test review loop approves on first iteration
budget_usd: 1.0
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan something simple"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success
        # One REVIEW_ITERATION event (the approve) + one REVIEW_COMPLETED.
        review_iters = [e for e in result.thread if e.type == EventType.REVIEW_ITERATION]
        review_done = [e for e in result.thread if e.type == EventType.REVIEW_COMPLETED]
        assert len(review_iters) == 1
        assert len(review_done) == 1
        assert review_done[0].data["approved"] is True
        assert review_done[0].data["iterations"] == 1

    @pytest.mark.asyncio
    async def test_loop_iterates_then_approves(self) -> None:
        """Critic rejects first, approves second → 2 iterations."""
        provider = _ScriptedCriticProvider(
            ["request_changes", "approve"],
            feedback=["Fix the bug", "Now it's good"],
        )
        executor = _make_executor(provider, loops=True)

        yaml_str = """
name: test_iterate_then_approve
objective: Test review loop iterates then approves
budget_usd: 1.0
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan something"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success
        review_iters = [e for e in result.thread if e.type == EventType.REVIEW_ITERATION]
        review_done = [e for e in result.thread if e.type == EventType.REVIEW_COMPLETED]
        assert len(review_iters) == 2
        assert review_iters[0].data["approved"] is False
        assert review_iters[1].data["approved"] is True
        assert review_done[0].data["approved"] is True
        assert review_done[0].data["iterations"] == 2

    @pytest.mark.asyncio
    async def test_loop_exhausts_max_iterations(self) -> None:
        """Critic never approves → loop stops at max_iterations."""
        provider = _ScriptedCriticProvider(
            ["request_changes", "request_changes", "request_changes"],
            feedback=["Still bad", "Worse", "Hopeless"],
        )
        executor = _make_executor(provider, loops=True)

        yaml_str = """
name: test_exhaust
objective: Test review loop exhausts without approval
budget_usd: 1.0
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan something"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success  # The step still succeeded; the loop just didn't approve.
        review_iters = [e for e in result.thread if e.type == EventType.REVIEW_ITERATION]
        review_done = [e for e in result.thread if e.type == EventType.REVIEW_COMPLETED]
        assert len(review_iters) == 3
        assert all(not e.data["approved"] for e in review_iters)
        assert review_done[0].data["approved"] is False
        assert review_done[0].data["iterations"] == 3

    @pytest.mark.asyncio
    async def test_no_loop_when_flag_off(self) -> None:
        """Without --loops, no review events are emitted."""
        provider = _ScriptedCriticProvider(["approve"])
        executor = _make_executor(provider, loops=False)

        yaml_str = """
name: test_no_loop
objective: Test no review loop when flag is off
budget_usd: 1.0
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan something"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success
        review_iters = [e for e in result.thread if e.type == EventType.REVIEW_ITERATION]
        review_done = [e for e in result.thread if e.type == EventType.REVIEW_COMPLETED]
        assert len(review_iters) == 0
        assert len(review_done) == 0

    @pytest.mark.asyncio
    async def test_step_level_review_overrides_global_flag(self) -> None:
        """A step with its own review config runs the loop even without --loops."""
        provider = _ScriptedCriticProvider(["approve"])
        executor = _make_executor(provider, loops=False)

        yaml_str = """
name: test_step_review
objective: Test step-level review config
budget_usd: 1.0
steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan something"
    review:
      enabled: true
      critic: "@reviewer"
      max_iterations: 2
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success
        review_done = [e for e in result.thread if e.type == EventType.REVIEW_COMPLETED]
        assert len(review_done) == 1
        assert review_done[0].data["approved"] is True
