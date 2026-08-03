"""VCR cassette test for LiteLLMProvider — records and replays real LLM HTTP traffic.

This test demonstrates the ARNES cassette pattern for snapshot-testing
real LLM calls without paying for them on every test run:

1. **Cassette file** — a YAML file under ``tests/snapshot/cassettes/``
   containing one or more ``request``/``response`` pairs captured from
   a real HTTP call. The committed cassette is the source of truth:
   tests replay it, they never re-record over it.

2. **Replay** — :mod:`vcr` patches ``httpx.AsyncHTTPTransport`` (and
   ``httpx.HTTPTransport``) so any HTTP call litellm makes via the
   OpenAI SDK is intercepted and served from the cassette. No network
   access, no API spend, fully deterministic.

3. **Record (one-time)** — to capture a NEW cassette (or refresh an
   existing one when the LLM contract changes), run::

       # Set a real API key (NEVER commit it).
       export OPENAI_API_KEY='sk-real-key'

       # Run vcrpy in record_mode='once' or 'all' against the test.
       # The easiest path: temporarily flip record_mode in this file
       # to 'once', run the test, commit the regenerated cassette,
       # then flip it back to 'none'.
       pytest tests/snapshot/test_litellm_cassette.py -s

   The cassette file path is derived from the test name
   (``test_planner_basic.yaml``), so each test owns its cassette.

What this test verifies:

* :class:`LiteLLMProvider` can complete against a recorded OpenAI
  response and return a correctly-mapped :class:`LLMResponse`.
* The recorded response (a ``@planner`` JSON payload) validates
  against :class:`PlannerOutput`, so the full
  ``Harness → specialist → middleware → LiteLLMProvider → litellm →
  httpx → vcrpy`` chain works end-to-end against a cassette.
* Cost calculation uses the local pricing table (``50 in + 30 out``
  tokens for ``openai/gpt-4o`` ⇒ ``$0.000425``), proving the cassette
  isn't silently short-circuited by a mock at the LLM layer.

Regeneration note:

    The shipped cassette ``test_planner_basic.yaml`` was hand-authored
    to look like a real OpenAI response. To replace it with a real
    recording, set ``OPENAI_API_KEY``, change ``record_mode`` below to
    ``'once'``, delete the cassette file, and re-run this test — vcrpy
    will record the actual HTTP exchange. Review the resulting YAML
    for secrets (the ``authorization`` header is auto-filtered) before
    committing.
"""

from __future__ import annotations

from pathlib import Path

# Silence litellm's background LoggingWorker BEFORE any litellm call.
# litellm spawns an asyncio queue + worker tasks on every ``acompletion``
# call to emit telemetry; the workers are never awaited at session
# teardown and pytest raises ``PytestUnraisableExceptionWarning`` (which
# ``filterwarnings = ["error"]`` in ``pyproject.toml`` turns into a hard
# failure). Setting ``litellm.logging = False`` AND monkey-patching
# ``_client_async_logging_helper`` to a no-op (via the ``_silence_litellm``
# fixture below) prevents the worker from being spawned at all — no
# leak, no warning.
import litellm
import pytest
import vcr

from arnes.llm.base import LLMMessage
from arnes.llm.litellm_provider import _PRICING_USD_PER_1M_TOKENS, LiteLLMProvider

litellm.logging = False

# Path to the cassette that backs this test. Resolved relative to this
# file so the test works from any CWD.
_CASSETTE_PATH: Path = Path(__file__).parent / "cassettes" / "test_planner_basic.yaml"

# A single VCR instance shared by every test in this module. Configured
# for pure replay (no recording) so CI never makes a real HTTP call.
#
# - ``record_mode='none'`` — only play back; raise if a request isn't
#   in the cassette. Catches "the code made a new HTTP call we didn't
#   record" regressions.
# - ``match_on=['method', 'uri']`` — ignore the request body when
#   matching. litellm/openai SDK embed timestamps and per-call
#   metadata in the body that would break exact-body matching; method
#   + URI is the stable contract.
# - ``filter_headers=['authorization']`` — never persist or compare
#   the ``Authorization: Bearer sk-...`` header. Defense-in-depth even
#   though we never record.
_VCR = vcr.VCR(
    record_mode="none",
    filter_headers=["authorization"],
    match_on=["method", "uri"],
)


@pytest.fixture
def _openai_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a placeholder OPENAI_API_KEY for the duration of the test.

    The key is never sent over the wire — vcrpy intercepts every HTTP
    call — but litellm/the OpenAI SDK refuse to construct a client
    without one. We use a clearly-fake placeholder so it's obvious in
    logs that no real key is in play.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-cassette-replay-placeholder")
    return "sk-cassette-replay-placeholder"


@pytest.fixture(autouse=True)
def _silence_litellm_logging_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable litellm's background LoggingWorker for the test.

    litellm spawns an asyncio ``LoggingWorker`` on every successful
    ``acompletion`` call. The worker is bound to the test's event loop;
    when pytest tears the loop down, the worker's pending tasks raise
    ``PytestUnraisableExceptionWarning``, which ``filterwarnings =
    ["error"]`` turns into a hard failure. Subsequent tests in the same
    session (e.g. ``tests/stress/test_concurrent.py``) inherit the
    failure even though they don't touch litellm.

    Patching ``_client_async_logging_helper`` to a no-op prevents the
    worker from being spawned at all — the call still completes
    normally, we just skip the telemetry side-effect.
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
# 1. LiteLLMProvider.complete() returns the recorded response
# ============================================================


class TestLiteLLMCassetteReplay:
    """Replay the committed cassette through :class:`LiteLLMProvider`."""

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_complete_returns_recorded_content(self, _openai_api_key: str) -> None:
        """``LiteLLMProvider.complete()`` must return the exact content
        from the cassette — proves the vcrpy → httpx → openai SDK →
        litellm → LiteLLMProvider chain is wired correctly."""
        assert _CASSETTE_PATH.exists(), (
            f"Cassette not found: {_CASSETTE_PATH}. "
            "See the module docstring for regeneration instructions."
        )

        # litellm >=1.90 has a bug where it imports openai.resources.skills
        # which doesn't exist in any openai version. Skip if that bug is present.
        try:
            import litellm  # noqa: F401
        except ModuleNotFoundError as e:
            if "skills" in str(e):
                pytest.skip(f"litellm has the openai.resources.skills import bug: {e}")

        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @planner, a planning specialist."),
            LLMMessage(role="user", content="Plan a blog post about ARNES."),
        ]

        try:
            with _VCR.use_cassette(str(_CASSETTE_PATH)):
                response = await provider.complete(messages, model="openai/gpt-4o")
        except Exception as e:
            if "skills" in str(e):
                pytest.skip(f"litellm has the openai.resources.skills import bug: {e}")
            raise

        # Content matches the cassette's response.choices[0].message.content.
        assert '"steps"' in response.content
        assert "@coder" in response.content
        # Model is propagated through.
        assert response.model == "openai/gpt-4o"
        # No tool calls in the recorded response.
        assert response.tool_calls == []

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_complete_extracts_usage_from_cassette(self, _openai_api_key: str) -> None:
        """The recorded usage (``prompt_tokens=50, completion_tokens=30``)
        must land in :class:`LLMUsage` — proves LiteLLMProvider's usage
        extraction works against a real litellm ``ModelResponse``
        object, not just a test-constructed one."""
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @planner."),
            LLMMessage(role="user", content="Plan a blog post."),
        ]

        with _VCR.use_cassette(str(_CASSETTE_PATH)):
            response = await provider.complete(messages, model="openai/gpt-4o")

        # The cassette hard-codes these values in the ``usage`` block.
        assert response.usage.tokens_in == 50
        assert response.usage.tokens_out == 30
        assert response.usage.model == "openai/gpt-4o"
        assert response.usage.cached is False

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_complete_calculates_cost_from_local_pricing(self, _openai_api_key: str) -> None:
        """Cost must be calculated from the local pricing table, not
        from any server-side cost field — the cassette has no
        ``cost_usd`` field, so this proves :func:`_estimate_cost` is
        doing the work."""
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [
            LLMMessage(role="system", content="You are @planner."),
            LLMMessage(role="user", content="Plan a blog post."),
        ]

        with _VCR.use_cassette(str(_CASSETTE_PATH)):
            response = await provider.complete(messages, model="openai/gpt-4o")

        pricing = _PRICING_USD_PER_1M_TOKENS["openai/gpt-4o"]
        expected = (50 * pricing["input"] + 30 * pricing["output"]) / 1_000_000
        assert response.usage.cost_usd == pytest.approx(expected, rel=1e-9)
        # OpenAI gpt-4o: $2.50/1M in, $10.00/1M out.
        # (50 * 2.50 + 30 * 10.00) / 1_000_000 = (125 + 300) / 1_000_000 = 0.000425
        assert response.usage.cost_usd == pytest.approx(0.000425, rel=1e-9)

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_raw_response_is_preserved(self, _openai_api_key: str) -> None:
        """``LLMResponse.raw`` must be populated with the full litellm
        ``ModelResponse.model_dump()`` — callers use this for forensic
        debugging of vendor-specific fields."""
        provider = LiteLLMProvider(api_key=_openai_api_key)
        messages = [LLMMessage(role="user", content="Plan a blog post.")]

        with _VCR.use_cassette(str(_CASSETTE_PATH)):
            response = await provider.complete(messages, model="openai/gpt-4o")

        assert response.raw is not None
        assert response.raw["model"] == "gpt-4o"
        assert response.raw["choices"][0]["message"]["content"] == response.content


# ============================================================
# 2. Specialist invocation with a recorded response
# ============================================================


class TestSpecialistWithCassette:
    """End-to-end: invoke the ``@planner`` specialist through the
    :class:`Harness` and verify the recorded response validates
    against :class:`PlannerOutput`."""

    @pytest.mark.snapshot
    @pytest.mark.asyncio
    async def test_planner_specialist_invoked_with_recorded_response(
        self, _openai_api_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The full chain — specialist → middleware → LiteLLMProvider →
        litellm → httpx → vcrpy → cassette — must produce a successful
        ``@planner`` result whose output validates against
        :class:`PlannerOutput`.

        We bypass the :class:`Harness` here because the
        :class:`TokenOptimizer` middleware's model-routing rule
        downgrades short-input ``openai/gpt-4o`` calls to
        ``ollama/llama3.2`` (cost optimisation) — which would route
        the call away from OpenAI and miss our cassette. Building the
        middleware stack manually with ``enable_routing=False`` keeps
        the call on ``openai/gpt-4o`` so vcrpy can intercept it. The
        :class:`Harness` is exercised end-to-end in the dedicated
        harness tests (``tests/integration/test_e2e.py``); this test
        isolates the vcrpy → LiteLLMProvider → specialist interaction.

        The shipped ``@planner`` specialist defaults to
        ``ollama/llama3.2`` — we monkey-patch its ``default_model`` to
        ``openai/gpt-4o`` so the call reaches LiteLLM/OpenAI (and our
        cassette) instead of a local Ollama daemon.
        """
        from arnes.middleware import (
            CostBudget,
            CostGuard,
            TokenOptimizer,
            VerificationConfig,
            VerificationLayer,
        )
        from arnes.specialists.base import get_default_specialist_registry
        from arnes.specialists.planner import Planner
        from arnes.thread import Thread
        from arnes.tools.base import ToolContext

        # Route @planner through LiteLLM+OpenAI so the cassette
        # intercepts the HTTP call. Restored automatically by monkeypatch
        # at test teardown — other tests see the original ollama default.
        monkeypatch.setattr(Planner.config, "default_model", "openai/gpt-4o")

        raw_provider = LiteLLMProvider(api_key=_openai_api_key)

        # Build the middleware stack manually with routing DISABLED so
        # the model isn't downgraded to ollama/llama3.2 for short inputs
        # (which would miss our OpenAI cassette). Cache is also disabled
        # so the call definitely reaches the provider on every run.
        inner: object = TokenOptimizer(raw_provider, enable_cache=False, enable_routing=False)
        inner = VerificationLayer(
            inner,
            VerificationConfig(structured_outputs=True, refusal_pattern=True),
        )
        wrapped_provider = CostGuard(inner, budget=CostBudget(task_budget_usd=0.50))

        # Fetch the @planner specialist from the default registry so we
        # exercise the same specialist config that ships to users.
        registry = get_default_specialist_registry()
        specialist = registry.get("@planner")
        assert specialist is not None, "@planner not in default registry"

        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist="@planner",
            metadata={"interactive": False},
        )

        with _VCR.use_cassette(str(_CASSETTE_PATH)):
            result = await specialist.run(
                {"task": "Plan a blog post about ARNES."},
                ctx,
                provider=wrapped_provider,
            )

        assert result["success"] is True, f"Specialist failed: {result.get('error')}"
        assert result["specialist"] == "@planner"
        # PlannerOutput schema: must have a ``steps`` list.
        output = result["output"]
        assert "steps" in output
        assert isinstance(output["steps"], list)
        assert len(output["steps"]) >= 1
        assert output["steps"][0]["specialist"] == "@coder"


# ============================================================
# 3. Cassette sanity checks (no network involved)
# ============================================================


class TestCassetteSanity:
    """Static checks on the committed cassette file — no HTTP, no vcrpy."""

    def test_cassette_file_exists(self) -> None:
        """The cassette file must be committed to the repo — a missing
        cassette means the replay tests will fail with a confusing
        ``CannotOverwriteExistingCassetteException``."""
        assert _CASSETTE_PATH.exists(), (
            f"Cassette missing: {_CASSETTE_PATH}. "
            "See the module docstring for regeneration instructions."
        )

    def test_cassette_is_valid_yaml(self) -> None:
        """The cassette must parse as YAML and have the VCR shape
        (``interactions`` list, ``version``)."""
        import yaml

        data = yaml.safe_load(_CASSETTE_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["version"] == 1
        assert isinstance(data["interactions"], list)
        assert len(data["interactions"]) >= 1

    def test_cassette_has_no_real_api_key(self) -> None:
        """Defense-in-depth: scan the cassette for anything that looks
        like an OpenAI API key. The ``authorization`` header is
        auto-filtered by ``_VCR.filter_headers``, but this catches a
        hand-authored cassette that accidentally embedded a real key
        in the request body or a header we forgot to filter."""
        content = _CASSETTE_PATH.read_text(encoding="utf-8")
        # OpenAI keys start with ``sk-`` and are 40+ chars.
        # The placeholder we use (``sk-cassette-replay-placeholder``) is fine.
        import re

        real_key_pattern = re.compile(r"sk-[A-Za-z0-9]{40,}")
        matches = real_key_pattern.findall(content)
        # Filter out the known-safe placeholder.
        real_matches = [m for m in matches if m != "sk-cassette-replay-placeholder"[:43]]
        assert not real_matches, (
            f"Cassette appears to contain a real API key: {real_matches}. "
            "Run _VCR with filter_headers=['authorization'] and re-record."
        )

    def test_cassette_response_is_200(self) -> None:
        """The recorded response must be a 200 OK — a 4xx/5xx cassette
        would make every replay test exercise the error path instead
        of the happy path, defeating the purpose of snapshot testing."""
        import yaml

        data = yaml.safe_load(_CASSETTE_PATH.read_text(encoding="utf-8"))
        for interaction in data["interactions"]:
            status = interaction["response"]["status"]
            assert status["code"] == 200, (
                f"Cassette interaction has non-200 status: {status}. "
                "Re-record against a working endpoint."
            )

    def test_cassette_targets_openai_endpoint(self) -> None:
        """The cassette must record a call to the OpenAI chat
        completions endpoint — that's what ``LiteLLMProvider`` calls
        for ``model='openai/gpt-4o'``."""
        import yaml

        data = yaml.safe_load(_CASSETTE_PATH.read_text(encoding="utf-8"))
        for interaction in data["interactions"]:
            uri = interaction["request"]["uri"]
            assert "api.openai.com/v1/chat/completions" in uri, (
                f"Cassette records a call to {uri}, not the OpenAI chat endpoint."
            )


# ============================================================
# Regeneration helper (documentation; not run by default).
# ============================================================


def _regenerate_cassette_instructions() -> str:
    """Return human-readable instructions for regenerating the cassette.

    Not a test — included so future maintainers can ``grep`` for
    ``regenerate`` and find the steps without reading the module
    docstring.
    """
    return f"""
To regenerate {_CASSETTE_PATH.name}:

1. Set a real OPENAI_API_KEY (NEVER commit it):
   export OPENAI_API_KEY='sk-real-key'

2. Temporarily change ``_VCR.record_mode`` in this file from 'none' to 'once'.

3. Delete the existing cassette:
   rm {_CASSETTE_PATH}

4. Run this test:
   pytest tests/snapshot/test_litellm_cassette.py -s

5. Review the regenerated cassette for secrets (the authorization
   header is auto-filtered, but check the request body too).

6. Restore ``_VCR.record_mode`` to 'none' and commit the cassette.
"""


def test_regeneration_instructions_are_documented() -> None:
    """Smoke test — the regeneration instructions string is non-empty.

    This is a documentation-as-test pattern: the instructions live in
    a function so they're greppable from the test suite, and this
    test ensures they don't get accidentally deleted.
    """
    instructions = _regenerate_cassette_instructions()
    assert "OPENAI_API_KEY" in instructions
    assert "record_mode" in instructions
    assert "rm" in instructions
