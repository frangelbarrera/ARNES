"""VCR cassette tests for the ``@coder`` and ``@reviewer`` specialists (R15).

R15 closes part of the R13→R14 ``only 1 vcrpy cassette`` gap by shipping
two additional hand-authored cassettes alongside the existing
``test_planner_basic.yaml``:

- ``cassettes/test_coder_basic.yaml`` — a recorded OpenAI response
  carrying a ``CoderOutput`` payload (one file, ``action: create``).
- ``cassettes/test_reviewer_basic.yaml`` — a recorded OpenAI response
  carrying a ``ReviewerOutput`` payload (``verdict: approve``, empty
  issues list).

These tests verify:

1. :class:`LiteLLMProvider` can complete against each cassette and return
   a correctly-mapped :class:`LLMResponse` (content + usage + raw).
2. The recorded payloads validate against :class:`CoderOutput` and
   :class:`ReviewerOutput` when invoked end-to-end through the
   specialist :meth:`run` (proving the cassette isn't silently
   short-circuited by a mock at the LLM layer).
3. Cost calculation uses the local pricing table (``62 in + 48 out``
   tokens for ``openai/gpt-4o`` ⇒ ``$0.000655`` for ``@coder``; ``58 in
   + 36 out`` ⇒ ``$0.000505`` for ``@reviewer``).
4. Cassette sanity (file exists, valid YAML, 200 OK, OpenAI endpoint,
   no real API key) — same checks as the planner cassette.

See ``test_litellm_cassette.py`` for the original planner cassette test
suite and the regeneration instructions (same pattern; just point
``_CASSETTE_PATH`` at the new file).
"""

from __future__ import annotations

from pathlib import Path

import litellm
import pytest
import vcr

from arnes.llm.base import LLMMessage
from arnes.llm.litellm_provider import _PRICING_USD_PER_1M_TOKENS, LiteLLMProvider

litellm.logging = False

_CASSETTES_DIR: Path = Path(__file__).parent / "cassettes"
_CODER_CASSETTE: Path = _CASSETTES_DIR / "test_coder_basic.yaml"
_REVIEWER_CASSETTE: Path = _CASSETTES_DIR / "test_reviewer_basic.yaml"

_VCR = vcr.VCR(
    record_mode="none",
    filter_headers=["authorization"],
    match_on=["method", "uri"],
)


@pytest.fixture
def _openai_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Placeholder OPENAI_API_KEY — never sent (vcrpy intercepts)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-cassette-replay-placeholder")
    return "sk-cassette-replay-placeholder"


@pytest.fixture(autouse=True)
def _silence_litellm_logging_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable litellm's background LoggingWorker for the test.

    Same reasoning as ``test_litellm_cassette.py`` — the worker leaks at
    session teardown and trips ``filterwarnings = ["error"]``. Patching
    ``_client_async_logging_helper`` to a no-op prevents the spawn.
    """
    from litellm import utils as litellm_utils

    async def _noop_async_logging_helper(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        litellm_utils,
        "_client_async_logging_helper",
        _noop_async_logging_helper,
    )


# ============================================================
# @coder cassette
# ============================================================


class TestCoderCassette:
    """Replay the ``@coder`` cassette through :class:`LiteLLMProvider`."""

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_coder_complete_returns_recorded_content(self, _openai_api_key: str) -> None:
        """``LiteLLMProvider.complete()`` against the @coder cassette must
        return a payload that validates against :class:`CoderOutput`
        (``files`` list with at least one entry, ``summary`` string,
        ``assumptions`` + ``warnings`` lists)."""
        assert _CODER_CASSETTE.exists(), f"Cassette missing: {_CODER_CASSETTE}"
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @coder, a senior software engineer."),
            LLMMessage(role="user", content="Write a hello-world function."),
        ]
        with _VCR.use_cassette(str(_CODER_CASSETTE)):
            response = await provider.complete(messages, model="openai/gpt-4o")
        assert '"files"' in response.content
        assert '"summary"' in response.content
        assert response.model == "openai/gpt-4o"
        assert response.tool_calls == []

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_coder_complete_extracts_usage_and_cost(self, _openai_api_key: str) -> None:
        """Usage (``prompt_tokens=62``, ``completion_tokens=48``) must land
        in :class:`LLMUsage`, and cost must be calculated from the local
        pricing table (not a server-side cost field)."""
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @coder."),
            LLMMessage(role="user", content="Write a hello-world function."),
        ]
        with _VCR.use_cassette(str(_CODER_CASSETTE)):
            response = await provider.complete(messages, model="openai/gpt-4o")
        assert response.usage.tokens_in == 62
        assert response.usage.tokens_out == 48
        pricing = _PRICING_USD_PER_1M_TOKENS["openai/gpt-4o"]
        expected = (62 * pricing["input"] + 48 * pricing["output"]) / 1_000_000
        assert response.usage.cost_usd == pytest.approx(expected, rel=1e-9)
        # (62 * 2.50 + 48 * 10.00) / 1_000_000 = (155 + 480) / 1_000_000 = 0.000635
        assert response.usage.cost_usd == pytest.approx(0.000635, rel=1e-9)

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_coder_specialist_validates_against_coder_output(
        self, _openai_api_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: invoke ``@coder`` through the registry + middleware
        stack and verify the recorded response validates against
        :class:`CoderOutput` (files list, ``action: create`` enum)."""
        from arnes.middleware import (
            CostBudget,
            CostGuard,
            TokenOptimizer,
            VerificationConfig,
            VerificationLayer,
        )
        from arnes.specialists.base import get_default_specialist_registry
        from arnes.specialists.coder import Coder
        from arnes.thread import Thread
        from arnes.tools.base import ToolContext

        # Route @coder through LiteLLM+OpenAI so the cassette intercepts.
        monkeypatch.setattr(Coder.config, "default_model", "openai/gpt-4o")

        raw_provider = LiteLLMProvider(api_key=_openai_api_key)
        inner: object = TokenOptimizer(raw_provider, enable_cache=False, enable_routing=False)
        inner = VerificationLayer(
            inner,
            VerificationConfig(structured_outputs=True, refusal_pattern=True),
        )
        wrapped_provider = CostGuard(inner, budget=CostBudget(task_budget_usd=0.50))

        registry = get_default_specialist_registry()
        specialist = registry.get("@coder")
        assert specialist is not None, "@coder not in default registry"

        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist="@coder",
            metadata={"interactive": False},
        )

        with _VCR.use_cassette(str(_CODER_CASSETTE)):
            result = await specialist.run(
                {"spec": "Write a hello-world function."},
                ctx,
                provider=wrapped_provider,
            )

        assert result["success"] is True, f"Specialist failed: {result.get('error')}"
        assert result["specialist"] == "@coder"
        output = result["output"]
        assert "files" in output
        assert isinstance(output["files"], list)
        assert len(output["files"]) == 1
        assert output["files"][0]["path"] == "hello.py"
        assert output["files"][0]["action"] == "create"
        assert output["summary"]
        assert output["assumptions"] == ["Python 3.11+ syntax is acceptable"]
        assert output["warnings"] == []


# ============================================================
# @reviewer cassette
# ============================================================


class TestReviewerCassette:
    """Replay the ``@reviewer`` cassette through :class:`LiteLLMProvider`."""

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_reviewer_complete_returns_recorded_content(self, _openai_api_key: str) -> None:
        """``LiteLLMProvider.complete()`` against the @reviewer cassette must
        return a payload that validates against :class:`ReviewerOutput`
        (``verdict`` enum, ``issues`` list, ``summary`` string)."""
        assert _REVIEWER_CASSETTE.exists(), f"Cassette missing: {_REVIEWER_CASSETTE}"
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @reviewer, a senior code reviewer."),
            LLMMessage(role="user", content="Review this code."),
        ]
        with _VCR.use_cassette(str(_REVIEWER_CASSETTE)):
            response = await provider.complete(messages, model="openai/gpt-4o")
        assert '"verdict"' in response.content
        assert '"approve"' in response.content
        assert response.model == "openai/gpt-4o"
        assert response.tool_calls == []

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_reviewer_complete_extracts_usage_and_cost(self, _openai_api_key: str) -> None:
        """Usage (``prompt_tokens=58``, ``completion_tokens=36``) must land
        in :class:`LLMUsage`, and cost must be calculated from the local
        pricing table."""
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @reviewer."),
            LLMMessage(role="user", content="Review this code."),
        ]
        with _VCR.use_cassette(str(_REVIEWER_CASSETTE)):
            response = await provider.complete(messages, model="openai/gpt-4o")
        assert response.usage.tokens_in == 58
        assert response.usage.tokens_out == 36
        pricing = _PRICING_USD_PER_1M_TOKENS["openai/gpt-4o"]
        expected = (58 * pricing["input"] + 36 * pricing["output"]) / 1_000_000
        assert response.usage.cost_usd == pytest.approx(expected, rel=1e-9)
        # (58 * 2.50 + 36 * 10.00) / 1_000_000 = (145 + 360) / 1_000_000 = 0.000505
        assert response.usage.cost_usd == pytest.approx(0.000505, rel=1e-9)

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_reviewer_specialist_validates_against_reviewer_output(
        self, _openai_api_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: invoke ``@reviewer`` through the registry + middleware
        stack and verify the recorded response validates against
        :class:`ReviewerOutput` (``verdict: approve`` enum, ``issues`` list,
        ``summary`` string)."""
        from arnes.middleware import (
            CostBudget,
            CostGuard,
            TokenOptimizer,
            VerificationConfig,
            VerificationLayer,
        )
        from arnes.specialists.base import get_default_specialist_registry
        from arnes.specialists.reviewer import Reviewer
        from arnes.thread import Thread
        from arnes.tools.base import ToolContext

        monkeypatch.setattr(Reviewer.config, "default_model", "openai/gpt-4o")

        raw_provider = LiteLLMProvider(api_key=_openai_api_key)
        inner: object = TokenOptimizer(raw_provider, enable_cache=False, enable_routing=False)
        inner = VerificationLayer(
            inner,
            VerificationConfig(structured_outputs=True, refusal_pattern=True),
        )
        wrapped_provider = CostGuard(inner, budget=CostBudget(task_budget_usd=0.50))

        registry = get_default_specialist_registry()
        specialist = registry.get("@reviewer")
        assert specialist is not None, "@reviewer not in default registry"

        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist="@reviewer",
            metadata={"interactive": False},
        )

        with _VCR.use_cassette(str(_REVIEWER_CASSETTE)):
            result = await specialist.run(
                {"code": "def hello(): return 'hello, world'"},
                ctx,
                provider=wrapped_provider,
            )

        assert result["success"] is True, f"Specialist failed: {result.get('error')}"
        assert result["specialist"] == "@reviewer"
        output = result["output"]
        assert output["verdict"] == "approve"
        assert output["issues"] == []
        assert output["summary"]


# ============================================================
# Cassette sanity (no network)
# ============================================================


class TestSpecialistCassetteSanity:
    """Static checks on the two new cassette files."""

    @pytest.mark.parametrize(
        ("cassette", "expected_id"),
        [
            (_CODER_CASSETTE, "chatcmpl-bench-r15-coder"),
            (_REVIEWER_CASSETTE, "chatcmpl-bench-r15-reviewer"),
        ],
    )
    def test_cassette_file_exists(self, cassette: Path, expected_id: str) -> None:
        assert cassette.exists(), f"Cassette missing: {cassette}"

    @pytest.mark.parametrize("cassette", [_CODER_CASSETTE, _REVIEWER_CASSETTE])
    def test_cassette_is_valid_yaml(self, cassette: Path) -> None:
        import yaml

        data = yaml.safe_load(cassette.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["version"] == 1
        assert isinstance(data["interactions"], list)
        assert len(data["interactions"]) >= 1

    @pytest.mark.parametrize("cassette", [_CODER_CASSETTE, _REVIEWER_CASSETTE])
    def test_cassette_response_is_200(self, cassette: Path) -> None:
        import yaml

        data = yaml.safe_load(cassette.read_text(encoding="utf-8"))
        for interaction in data["interactions"]:
            status = interaction["response"]["status"]
            assert status["code"] == 200, f"Cassette {cassette.name} has non-200 status: {status}"

    @pytest.mark.parametrize("cassette", [_CODER_CASSETTE, _REVIEWER_CASSETTE])
    def test_cassette_targets_openai_endpoint(self, cassette: Path) -> None:
        import yaml

        data = yaml.safe_load(cassette.read_text(encoding="utf-8"))
        for interaction in data["interactions"]:
            uri = interaction["request"]["uri"]
            assert "api.openai.com/v1/chat/completions" in uri, (
                f"Cassette {cassette.name} records a call to {uri}, not the OpenAI chat endpoint."
            )

    @pytest.mark.parametrize("cassette", [_CODER_CASSETTE, _REVIEWER_CASSETTE])
    def test_cassette_has_no_real_api_key(self, cassette: Path) -> None:
        """Defense-in-depth: scan for anything that looks like a real OpenAI key."""
        import re

        content = cassette.read_text(encoding="utf-8")
        real_key_pattern = re.compile(r"sk-[A-Za-z0-9]{40,}")
        matches = real_key_pattern.findall(content)
        real_matches = [m for m in matches if m != "sk-cassette-replay-placeholder"[:43]]
        assert not real_matches, (
            f"Cassette {cassette.name} appears to contain a real API key: {real_matches}."
        )
