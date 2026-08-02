"""Stress test for ARNES Playbook template resolution.

STRESS-4 — verifies that the standalone ``_resolve_template`` in
``arnes.playbooks.template`` and the end-to-end playbook runtime handle
pathological / adversarial template inputs gracefully.

The 7 stress cases exercised here:

1. **20+ template refs in one string** — ``{{ variables.a }} ... {{ variables.t }}``
2. **Deep nesting** — ``{{ steps.s1.output.steps.s2.output.steps.s3.output }}``
3. **Mixed variables + steps** — ``{{ variables.pr }} + {{ steps.review.output.verdict }}``
4. **Template in parallel sub-step** — ``{{ steps.parallel.lint.output }}`` (was a P0 bug)
5. **Template not found** — ``{{ steps.nonexistent.output }}`` returns the literal string
6. **Empty template** — ``{{ }}`` must not crash
7. **Template with special chars** — ``{{ variables.path_with_underscores }}``

Both unit-level (``_resolve_template`` direct calls) and end-to-end
(full playbook execution) paths are exercised.

The unit-level tests call the standalone ``_resolve_template`` from
``arnes.playbooks.template`` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.playbooks.template import _resolve_template

# ============================================================
# A deterministic mock provider whose responses carry structured
# payloads so that template resolution can be verified end-to-end.
# ============================================================


class StructuredMockProvider(LLMProvider):
    """Returns JSON payloads that downstream templates can dereference."""

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

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
        self.call_count += 1

        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""
        user_msg = next((m for m in messages if m.role == "user"), None)
        user_content = user_msg.content if user_msg else ""

        self.calls.append({"system": sys_content, "user": user_content})

        # Return fixed valid JSON for each specialist. The user_content
        # (which contains the resolved templates) is captured in self.calls
        # so the tests can verify template resolution after-the-fact.
        #
        # NOTE: check @planner BEFORE @reviewer — the planner's system prompt
        # mentions @reviewer (and other specialists) by name, so a naive
        # "@reviewer in sys_content" check would misfire on the planner.
        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = (
                '{"files": [{"path": "out.py", "language": "python", "content": "pass"}], '
                '"summary": "ok", "assumptions": [], "warnings": []}'
            )
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "LGTM"}'
        elif "@tester" in sys_content:
            content = (
                '{"test_files": [{"path": "test.py", "content": "pass"}], '
                '"test_results": {"passed": 1, "failed": 0, "skipped": 0, "failures": []}, '
                '"summary": "ok"}'
            )
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


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def executor() -> PlaybookExecutor:
    provider = StructuredMockProvider()
    return PlaybookExecutor(
        provider=provider,
        cost_budget=CostBudget(task_budget_usd=10.0),
    )


@pytest.fixture
def bare_executor() -> PlaybookExecutor:
    """Executor with a no-op provider — used only for direct _resolve_template tests.

    The ``_resolve_template`` standalone function lives in
    ``arnes.playbooks.template``; the fixture is kept for symmetry with
    the e2e fixture, but the unit tests below call ``_resolve_template``
    as a free function rather than via ``executor._resolve_template``.
    """
    return PlaybookExecutor(provider=StructuredMockProvider())


# ============================================================
# Unit-level tests — call _resolve_template directly.
# ============================================================


class TestResolveTemplateDirect:
    """Drive the standalone ``_resolve_template`` directly with crafted outputs."""

    def test_case1_many_template_refs_one_string(self, bare_executor: PlaybookExecutor) -> None:
        """20+ template refs in one string all resolve correctly."""
        # a..t = 20 letters
        keys = [chr(ord("a") + i) for i in range(20)]
        outputs: dict[str, Any] = {k: k.upper() for k in keys}
        template = " ".join(f"{{{{ variables.{k} }}}}" for k in keys)
        expected = " ".join(k.upper() for k in keys)

        result = _resolve_template(template, outputs)

        assert result == expected, f"20-template resolution failed: {result!r}"
        # Sanity: every letter appears
        for k in keys:
            assert k.upper() in result

    def test_case1b_30_template_refs_one_string(self, bare_executor: PlaybookExecutor) -> None:
        """Push past 20 to verify scaling — 30 refs in one string."""
        keys = [chr(ord("a") + i) for i in range(26)] + [f"v{i}" for i in range(4)]
        outputs = {k: f"<{k}>" for k in keys}
        template = " ".join(f"{{{{ variables.{k} }}}}" for k in keys)
        expected = " ".join(f"<{k}>" for k in keys)

        result = _resolve_template(template, outputs)
        assert result == expected

    def test_case2_deep_nesting(self, bare_executor: PlaybookExecutor) -> None:
        """``{{ steps.s1.output.steps.s2.output.steps.s3.output }}`` resolves through
        a deeply nested output structure (where intermediate dicts literally
        contain the key ``steps``)."""
        outputs = {
            "s1": {
                "output": {
                    "steps": {
                        "s2": {
                            "output": {
                                "steps": {
                                    "s3": {
                                        "output": "deep_value",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        template = "{{ steps.s1.output.steps.s2.output.steps.s3.output }}"

        result = _resolve_template(template, outputs)

        assert result == "deep_value", f"Deep nesting failed: {result!r}"

    def test_case3_mixed_variables_and_steps(self, bare_executor: PlaybookExecutor) -> None:
        """``{{ variables.pr }} + {{ steps.review.output.verdict }}`` mixes the
        two template namespaces in one string."""
        outputs = {
            "pr": 1234,
            "review": {"output": {"verdict": "approve"}},
        }
        template = "{{ variables.pr }} + {{ steps.review.output.verdict }}"

        result = _resolve_template(template, outputs)

        assert result == "1234 + approve", f"Mixed resolution failed: {result!r}"

    def test_case4_parallel_substep_template(self, bare_executor: PlaybookExecutor) -> None:
        """``{{ steps.parallel.lint.output }}`` — parallel substep template resolution.

        After parallel execution, ``outputs['parallel']`` is a map of
        sub-step-id → ``{'output': ..., 'success': ...}``.  This template must
        resolve all the way down to the sub-step's output value.
        """
        outputs = {
            "parallel": {
                "lint": {"output": "lint_passed", "success": True},
                "test": {"output": "tests_passed", "success": True},
            },
        }

        # Top-level (whole string is one template) — preserves type
        result = _resolve_template("{{ steps.parallel.lint.output }}", outputs)
        assert result == "lint_passed", f"Parallel template failed: {result!r}"

        # Embedded inside a larger string — exercises str() coercion path
        result_embedded = _resolve_template(
            "lint: {{ steps.parallel.lint.output }} | test: {{ steps.parallel.test.output }}",
            outputs,
        )
        assert result_embedded == "lint: lint_passed | test: tests_passed", (
            f"Embedded parallel template failed: {result_embedded!r}"
        )

        # Success flag is also reachable
        result_success = _resolve_template("{{ steps.parallel.lint.success }}", outputs)
        assert result_success is True, f"Parallel success flag failed: {result_success!r}"

    def test_case5_template_not_found_returns_literal(
        self, bare_executor: PlaybookExecutor
    ) -> None:
        """``{{ steps.nonexistent.output }}`` returns the literal template string,
        NOT an empty string, NOT None, NOT a crash."""
        outputs: dict[str, Any] = {}
        template = "{{ steps.nonexistent.output }}"

        result = _resolve_template(template, outputs)

        assert result == "{{ steps.nonexistent.output }}", (
            f"Missing template should return literal, got: {result!r}"
        )

    def test_case5b_partial_path_not_found_returns_literal(
        self, bare_executor: PlaybookExecutor
    ) -> None:
        """A path that exists for the first segment but not deep down also
        returns the literal template."""
        outputs = {"s1": {"output": "ok"}}  # no nested 'steps.s2'
        template = "{{ steps.s1.output.steps.s2.output }}"

        result = _resolve_template(template, outputs)

        assert result == "{{ steps.s1.output.steps.s2.output }}", (
            f"Partial-path miss should return literal, got: {result!r}"
        )

    def test_case6_empty_template_does_not_crash(self, bare_executor: PlaybookExecutor) -> None:
        """``{{ }}`` (empty template body) must not crash and must round-trip
        to the original literal string."""
        outputs: dict[str, Any] = {"a": 1}

        # Whole string is one empty template
        result = _resolve_template("{{ }}", outputs)
        assert result == "{{ }}", f"Empty template should round-trip, got: {result!r}"

        # Empty template embedded among valid ones
        result_embedded = _resolve_template("before {{ }} after {{ variables.a }}", outputs)
        # The valid template still resolves; the empty one stays literal.
        assert "{{ }}" in result_embedded, (
            f"Empty template should remain literal in mix, got: {result_embedded!r}"
        )
        assert "1" in result_embedded, "Valid template should still resolve alongside empty"

    def test_case6b_no_space_empty_template(self, bare_executor: PlaybookExecutor) -> None:
        """``{{}}`` (no whitespace at all) must also be safe."""
        outputs: dict[str, Any] = {}
        result = _resolve_template("{{}}", outputs)
        # The regex requires [^}]+ between the braces, so {{}} is NOT matched
        # and should be returned verbatim.
        assert result == "{{}}", f"{{{{}}}} should round-trip, got: {result!r}"

    def test_case7_special_chars_underscores(self, bare_executor: PlaybookExecutor) -> None:
        """``{{ variables.path_with_underscores }}`` resolves correctly —
        underscore-rich identifiers must survive the prefix-stripping logic."""
        outputs = {"path_with_underscores": "/usr/local/bin/arnes"}
        template = "{{ variables.path_with_underscores }}"

        result = _resolve_template(template, outputs)

        assert result == "/usr/local/bin/arnes", f"Underscore variable failed: {result!r}"

    def test_case7b_special_chars_dashes_and_dots_in_value(
        self, bare_executor: PlaybookExecutor
    ) -> None:
        """Variable values containing special chars (dots, dashes) are passed
        through verbatim — only the variable NAME is parsed, not the value."""
        outputs = {"commit_sha": "abc-1234.deadbeef"}
        result = _resolve_template("{{ variables.commit_sha }}", outputs)
        assert result == "abc-1234.deadbeef"

    def test_case8_variables_strict_key_lookup(self, bare_executor: PlaybookExecutor) -> None:
        """``variables.X.output`` (where X has no 'output' key) must return the
        literal template — the virtual 'output' accessor only applies to
        ``steps.*`` refs, not ``variables.*`` refs. Variables are
        user-defined; a missing key is a real error."""
        outputs = {"config": {"foo": "bar"}}  # no 'output' key
        result = _resolve_template("{{ variables.config.output }}", outputs)
        assert result == "{{ variables.config.output }}", (
            f"variables.* should use strict lookup, got: {result!r}"
        )

        # But a variable that DOES have an 'output' key should dereference it
        outputs2 = {"config": {"output": "wrapped"}}
        result2 = _resolve_template("{{ variables.config.output }}", outputs2)
        assert result2 == "wrapped", (
            f"variables.* with real 'output' key should dereference, got: {result2!r}"
        )

    def test_case9_steps_output_virtual_accessor_skips_missing(
        self, bare_executor: PlaybookExecutor
    ) -> None:
        """``steps.X.output`` where X's output is stored raw (no 'output' key)
        must resolve to the raw output itself (virtual accessor)."""
        # Simulate how the executor stores a regular step's output:
        # outputs[step_id] = raw_output_dict  (NOT wrapped in {"output": ...})
        outputs = {"review": {"verdict": "approve", "issues": []}}
        # Top-level: returns the raw output dict (preserves type)
        result = _resolve_template("{{ steps.review.output }}", outputs)
        assert result == {"verdict": "approve", "issues": []}, (
            f"Virtual accessor (whole-string) failed: {result!r}"
        )
        # Deep access: skips 'output', then dereferences 'verdict'
        result_deep = _resolve_template("{{ steps.review.output.verdict }}", outputs)
        assert result_deep == "approve", f"Virtual accessor (deep) failed: {result_deep!r}"


# ============================================================
# End-to-end tests — full playbook execution with templates.
# ============================================================


class TestTemplateResolutionEndToEnd:
    """Run actual playbooks through the executor and verify templates resolved
    correctly by inspecting what the LLM was invoked with."""

    @pytest.mark.asyncio
    async def test_e2e_many_template_refs(self, executor: PlaybookExecutor) -> None:
        """A playbook whose step input references 20+ variables end-to-end."""
        # Build 20 variables a..t
        var_lines = "\n".join(f"  {chr(ord('a') + i)}: val_{chr(ord('a') + i)}" for i in range(20))
        ref_str = " ".join(f"{{{{ variables.{chr(ord('a') + i)} }}}}" for i in range(20))

        yaml_str = f"""
name: many_refs
objective: Stress-test 20 template refs
variables:
{var_lines}
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Refs: {ref_str}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Run failed: {result.error}"

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        # The planner call should have received the fully resolved task string
        planner_call = next(c for c in provider.calls if "@planner" in c["system"])
        expected_refs = " ".join(f"val_{chr(ord('a') + i)}" for i in range(20))
        assert f"Refs: {expected_refs}" in planner_call["user"], (
            f"Expected resolved refs in user msg, got: {planner_call['user']!r}"
        )

    @pytest.mark.asyncio
    async def test_e2e_parallel_substep_template(self, executor: PlaybookExecutor) -> None:
        """End-to-end: a parallel branch produces outputs that a subsequent
        step references via ``{{ steps.parallel.<sub>.output }}``."""
        yaml_str = """
name: parallel_template
objective: Verify parallel sub-step template resolution end-to-end
steps:
  - id: parallel
    parallel:
      - id: lint
        specialist: "@reviewer"
        input: {code: "sample"}
      - id: test
        specialist: "@tester"
        input: {code: "sample"}
  - id: summarize
    specialist: "@planner"
    input:
      task: "lint={{ steps.parallel.lint.output }} test={{ steps.parallel.test.output }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Run failed: {result.error}"
        assert result.steps_executed == 2

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        planner_call = next(c for c in provider.calls if "@planner" in c["system"])
        # The lint and test sub-step outputs are JSON strings; we just need to
        # confirm they were interpolated (not left as literal templates).
        assert "{{ steps.parallel.lint.output }}" not in planner_call["user"], (
            f"Parallel lint template was NOT resolved! Got: {planner_call['user']!r}"
        )
        assert "{{ steps.parallel.test.output }}" not in planner_call["user"], (
            f"Parallel test template was NOT resolved! Got: {planner_call['user']!r}"
        )
        # The actual JSON outputs should be present
        assert "verdict" in planner_call["user"]
        assert "test_results" in planner_call["user"]

    @pytest.mark.asyncio
    async def test_e2e_template_not_found_keeps_literal(self, executor: PlaybookExecutor) -> None:
        """A reference to a non-existent step output survives as a literal
        string in the LLM input — no crash, no abort."""
        yaml_str = """
name: missing_template
objective: Test missing template behavior
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Missing: {{ steps.nonexistent.output }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Run should NOT fail on missing template: {result.error}"

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        planner_call = provider.calls[0]
        assert "{{ steps.nonexistent.output }}" in planner_call["user"], (
            f"Missing template should be preserved as literal, got: {planner_call['user']!r}"
        )

    @pytest.mark.asyncio
    async def test_e2e_empty_template_does_not_crash(self, executor: PlaybookExecutor) -> None:
        """An empty ``{{ }}`` template must not crash the run."""
        yaml_str = """
name: empty_template
objective: Test empty template behavior
variables:
  real: "value"
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "before {{ }} after {{ variables.real }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Empty template crashed the run: {result.error}"

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        planner_call = provider.calls[0]
        # The valid template resolves; the empty one stays literal.
        assert "value" in planner_call["user"], (
            f"Valid template should resolve alongside empty, got: {planner_call['user']!r}"
        )

    @pytest.mark.asyncio
    async def test_e2e_special_chars_underscores(self, executor: PlaybookExecutor) -> None:
        """``{{ variables.path_with_underscores }}`` resolves end-to-end."""
        yaml_str = """
name: underscore_var
objective: Test underscore variable
variables:
  path_with_underscores: "/usr/local/bin"
steps:
  - id: s1
    specialist: "@planner"
    input:
      task: "Path is {{ variables.path_with_underscores }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Run failed: {result.error}"

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        planner_call = provider.calls[0]
        assert "Path is /usr/local/bin" in planner_call["user"], (
            f"Underscore variable did not resolve, got: {planner_call['user']!r}"
        )

    @pytest.mark.asyncio
    async def test_e2e_mixed_variables_and_steps(self, executor: PlaybookExecutor) -> None:
        """End-to-end: a step input mixes ``variables.X`` and ``steps.Y.output``."""
        yaml_str = """
name: mixed_templates
objective: Test mixed variable + step templates
variables:
  pr: 1234
steps:
  - id: review
    specialist: "@reviewer"
    input: {code: "sample"}
  - id: summarize
    specialist: "@planner"
    input:
      task: "PR {{ variables.pr }} verdict={{ steps.review.output.verdict }}"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        result = await executor.run(playbook)

        assert result.success is True, f"Run failed: {result.error}"
        assert result.steps_executed == 2

        provider = executor.provider
        assert isinstance(provider, StructuredMockProvider)
        planner_call = next(c for c in provider.calls if "@planner" in c["system"])
        assert "PR 1234 verdict=approve" in planner_call["user"], (
            f"Mixed templates did not resolve, got: {planner_call['user']!r}"
        )
