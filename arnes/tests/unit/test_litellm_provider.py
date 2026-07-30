"""Tests for arnes.llm.litellm_provider.LiteLLMProvider.complete().

Covers:
1. ``complete()`` returns a correct ``LLMResponse`` from a litellm response.
2. ``complete()`` extracts ``tool_calls`` into the OpenAI shape ARNES uses.
3. ``complete()`` calculates ``cost_usd`` from the pricing table + usage.
4. ``complete()`` passes ``tools`` through to ``litellm.acompletion``.
5. ``complete()`` passes ``response_format`` through to ``litellm.acompletion``.
6. ``complete()`` tolerates a missing ``usage`` block (some vendors do this
   when the call is served from cache or short-circuited server-side).

The actual ``litellm.acompletion`` is patched via ``monkeypatch.setattr`` —
we never touch the network. We construct real ``ModelResponse`` objects
from ``litellm.types.utils`` so the attribute accesses (``choices[0]``,
``message.content``, ``message.tool_calls``, ``usage.prompt_tokens``) match
the surface ``LiteLLMProvider.complete()`` actually depends on.

Bonus (kept here for locality):
7. ``stream_complete()`` raises ``NotImplementedError("Streaming coming in v0.2")``
   when iterated, and the message matches the README's v0.2 commitment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from litellm.types.utils import (
    ChatCompletionMessageToolCall,
    Choices,
    Function,
    Message,
    ModelResponse,
    Usage,
)

from arnes.llm.base import LLMMessage
from arnes.llm.litellm_provider import (
    _PRICING_USD_PER_1M_TOKENS,
    LiteLLMProvider,
    _estimate_cost,
)

# ============================================================
# Helpers — build real litellm ModelResponse objects so the
# attribute accesses in LiteLLMProvider.complete() match the
# actual surface it depends on at runtime.
# ============================================================


def _make_response(
    *,
    content: str | None = "Hello!",
    tool_calls: list[ChatCompletionMessageToolCall] | None = None,
    usage: Usage | None = None,
    model: str = "openai/gpt-4o",
) -> ModelResponse:
    """Construct a minimal but real ``litellm.ModelResponse``."""
    message = Message(role="assistant", content=content, tool_calls=tool_calls)
    return ModelResponse(
        id="test-resp-1",
        choices=[Choices(message=message, finish_reason="stop", index=0)],
        model=model,
        usage=usage,
    )


def _patch_acompletion(monkeypatch, response: ModelResponse) -> AsyncMock:
    """Replace ``litellm.acompletion`` with an ``AsyncMock`` returning *response*.

    Returns the mock so the test can assert on ``call_args``.
    """
    import litellm

    mock = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", mock)
    return mock


# ============================================================
# 1. complete() returns a correct LLMResponse
# ============================================================


class TestLiteLLMCompleteBasics:
    @pytest.mark.asyncio
    async def test_complete_returns_content_model_and_usage(self, monkeypatch):
        """``complete()`` must map the litellm response onto ``LLMResponse``
        without dropping or mutating the standard fields.
        """
        usage = Usage(prompt_tokens=12, completion_tokens=8, total_tokens=20)
        litellm_resp = _make_response(
            content="Hello!",
            usage=usage,
            model="openai/gpt-4o",
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert response.content == "Hello!"
        assert response.model == "openai/gpt-4o"
        assert response.usage.tokens_in == 12
        assert response.usage.tokens_out == 8
        assert response.usage.model == "openai/gpt-4o"
        assert response.usage.cached is False
        assert response.tool_calls == []
        # raw is the model_dump of the litellm response — preserves vendor
        # specifics for debugging / observability without leaking them into
        # the typed LLMResponse fields.
        assert response.raw is not None
        assert response.raw["model"] == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_complete_forwards_model_and_messages_to_litellm(self, monkeypatch):
        """``complete()`` must pass ``model`` and ``messages`` (serialized)
        to ``litellm.acompletion`` — these are the irreducible call args.
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=1, completion_tokens=1))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        messages = [
            LLMMessage(role="system", content="be brief"),
            LLMMessage(role="user", content="ping"),
        ]
        await provider.complete(messages, model="openai/gpt-4o")

        assert mock.called
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o"
        # Messages are passed as plain dicts (model_dump), not LLMMessage
        # objects — litellm doesn't know about our pydantic wrapper.
        assert call_kwargs["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "ping"},
        ]

    @pytest.mark.asyncio
    async def test_complete_forwards_temperature_default(self, monkeypatch):
        """The default ``temperature=0.0`` reaches litellm (deterministic by
        default, matching ARNES's reproducibility ethos).
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=1, completion_tokens=1))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert mock.call_args.kwargs["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_complete_forwards_max_tokens_when_set(self, monkeypatch):
        """``max_tokens`` must reach litellm only when explicitly set —
        silently defaulting to a small value would truncate long responses.
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=1, completion_tokens=1))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()

        # When max_tokens is None (default), it must NOT be added to call_kwargs
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )
        assert "max_tokens" not in mock.call_args.kwargs

        # When max_tokens is explicitly set, it must reach litellm
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
            max_tokens=512,
        )
        assert mock.call_args.kwargs["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_complete_merges_init_kwargs_and_call_kwargs(self, monkeypatch):
        """Construction-time kwargs (e.g. ``api_key``) must reach litellm,
        and per-call kwargs must take precedence — this is the precedence
        contract documented in the LiteLLMProvider docstring.
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=1, completion_tokens=1))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider(api_key="sk-init", base_url="https://init.example")
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
            api_key="sk-override",
            top_p=0.9,
        )

        call_kwargs = mock.call_args.kwargs
        # Per-call kwarg wins over init kwarg
        assert call_kwargs["api_key"] == "sk-override"
        # Init kwarg is preserved when not overridden
        assert call_kwargs["base_url"] == "https://init.example"
        # Per-call extra kwargs (top_p) are forwarded
        assert call_kwargs["top_p"] == 0.9


# ============================================================
# 2. complete() extracts tool_calls correctly
# ============================================================


class TestLiteLLMCompleteToolCalls:
    @pytest.mark.asyncio
    async def test_complete_extracts_tool_calls_in_openai_shape(self, monkeypatch):
        """``complete()`` must convert litellm ``ChatCompletionMessageToolCall``
        objects into the OpenAI dict shape that ``Specialist._execute_tool_call``
        expects: ``{"id", "type": "function", "function": {"name", "arguments"}}``.
        """
        tc = ChatCompletionMessageToolCall(
            id="call_abc123",
            type="function",
            function=Function(name="get_weather", arguments='{"city": "SF"}'),
        )
        litellm_resp = _make_response(
            content="",
            tool_calls=[tc],
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="weather?")],
            model="openai/gpt-4o",
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )

        assert len(response.tool_calls) == 1
        extracted = response.tool_calls[0]
        assert extracted["id"] == "call_abc123"
        assert extracted["type"] == "function"
        assert extracted["function"]["name"] == "get_weather"
        # arguments is passed through as the JSON string litellm gave us —
        # the specialist's _execute_tool_call does json.loads() on it.
        assert extracted["function"]["arguments"] == '{"city": "SF"}'

    @pytest.mark.asyncio
    async def test_complete_extracts_multiple_tool_calls_in_order(self, monkeypatch):
        """When the model returns multiple tool_calls in one response, the
        extraction preserves order — the ReAct loop relies on this for
        parallel tool execution semantics.
        """
        tcs = [
            ChatCompletionMessageToolCall(
                id="call_1",
                type="function",
                function=Function(name="fs_read", arguments='{"path": "a.py"}'),
            ),
            ChatCompletionMessageToolCall(
                id="call_2",
                type="function",
                function=Function(name="fs_read", arguments='{"path": "b.py"}'),
            ),
            ChatCompletionMessageToolCall(
                id="call_3",
                type="function",
                function=Function(name="shell", arguments='{"cmd": "ls"}'),
            ),
        ]
        litellm_resp = _make_response(
            content="",
            tool_calls=tcs,
            usage=Usage(prompt_tokens=20, completion_tokens=10),
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="multi")],
            model="openai/gpt-4o",
        )

        assert len(response.tool_calls) == 3
        assert [tc["id"] for tc in response.tool_calls] == ["call_1", "call_2", "call_3"]
        assert [tc["function"]["name"] for tc in response.tool_calls] == [
            "fs_read",
            "fs_read",
            "shell",
        ]

    @pytest.mark.asyncio
    async def test_complete_no_tool_calls_returns_empty_list(self, monkeypatch):
        """When the litellm response has ``tool_calls=None``, the extracted
        list must be ``[]`` (not None) — specialists iterate over this
        without a None-check.
        """
        litellm_resp = _make_response(
            content="just text, no tool calls",
            tool_calls=None,
            usage=Usage(prompt_tokens=5, completion_tokens=3),
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert response.tool_calls == []
        assert response.content == "just text, no tool calls"


# ============================================================
# 3. complete() calculates cost correctly
# ============================================================


class TestLiteLLMCompleteCostCalc:
    @pytest.mark.asyncio
    async def test_complete_calculates_cost_for_known_model(self, monkeypatch):
        """``cost_usd`` must be ``tokens_in * input_price + tokens_out *
        output_price`` (per 1M tokens), looked up in the pricing table.
        """
        usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        litellm_resp = _make_response(content="ok", usage=usage, model="openai/gpt-4o")
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        pricing = _PRICING_USD_PER_1M_TOKENS["openai/gpt-4o"]
        expected_cost = (1000 * pricing["input"] + 500 * pricing["output"]) / 1_000_000
        assert response.usage.cost_usd == pytest.approx(expected_cost, rel=1e-9)

    @pytest.mark.asyncio
    async def test_complete_calculates_cost_for_anthropic_model(self, monkeypatch):
        """Sanity-check the cost calc against a different pricing entry —
        guards against a hard-coded price slipping in.
        """
        usage = Usage(prompt_tokens=2000, completion_tokens=1000, total_tokens=3000)
        litellm_resp = _make_response(
            content="ok", usage=usage, model="anthropic/claude-sonnet-4-20250514"
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="anthropic/claude-sonnet-4-20250514",
        )

        pricing = _PRICING_USD_PER_1M_TOKENS["anthropic/claude-sonnet-4-20250514"]
        expected_cost = (2000 * pricing["input"] + 1000 * pricing["output"]) / 1_000_000
        # Claude Sonnet 4: $3/1M in, $15/1M out
        # = (2000*3 + 1000*15) / 1_000_000 = (6000 + 15000) / 1_000_000 = 0.021
        assert response.usage.cost_usd == pytest.approx(expected_cost, rel=1e-9)
        assert response.usage.cost_usd == pytest.approx(0.021, rel=1e-9)

    @pytest.mark.asyncio
    async def test_complete_uses_fallback_pricing_for_unknown_model(self, monkeypatch):
        """Models not in the pricing table fall back to $1/1M tokens (the
        documented conservative default) — must not raise.
        """
        usage = Usage(prompt_tokens=5000, completion_tokens=2000, total_tokens=7000)
        litellm_resp = _make_response(content="ok", usage=usage, model="vendor/unknown-model")
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="vendor/unknown-model",
        )

        expected = (5000 + 2000) * 1.0 / 1_000_000
        assert response.usage.cost_usd == pytest.approx(expected, rel=1e-9)
        # And the standalone _estimate_cost helper agrees with the in-call calc
        assert _estimate_cost("vendor/unknown-model", 5000, 2000) == pytest.approx(
            expected, rel=1e-9
        )


# ============================================================
# 4. complete() passes tools to litellm
# ============================================================


class TestLiteLLMCompleteToolsForwarding:
    @pytest.mark.asyncio
    async def test_complete_passes_tools_to_litellm(self, monkeypatch):
        """The ``tools`` kwarg must reach litellm unmodified — dropping it
        would silently disable tool-calling for any specialist that
        relies on the ReAct loop.
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=10, completion_tokens=5))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "fs_read",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]
        await provider.complete(
            [LLMMessage(role="user", content="read foo.py")],
            model="openai/gpt-4o",
            tools=tools,
        )

        assert mock.call_args.kwargs["tools"] == tools

    @pytest.mark.asyncio
    async def test_complete_omits_tools_kwarg_when_none(self, monkeypatch):
        """When ``tools`` is None (the default), the ``tools`` key must NOT
        appear in the call kwargs — some vendors reject an empty tools list,
        so we must distinguish "no tools" from "tools=[]".
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=10, completion_tokens=5))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert "tools" not in mock.call_args.kwargs


# ============================================================
# 5. complete() passes response_format to litellm
# ============================================================


class TestLiteLLMCompleteResponseFormat:
    @pytest.mark.asyncio
    async def test_complete_passes_response_format_for_json_object(self, monkeypatch):
        """When ``response_format={"type": "json_object"}`` is set, it must
        be forwarded to litellm — this is how the VerificationLayer forces
        structured outputs on vendors that support JSON mode.
        """
        litellm_resp = _make_response(
            content='{"result": "ok"}',
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        await provider.complete(
            [LLMMessage(role="user", content="give me json")],
            model="openai/gpt-4o",
            response_format={"type": "json_object"},
        )

        assert mock.call_args.kwargs["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_complete_omits_response_format_when_none(self, monkeypatch):
        """When ``response_format`` is None, it must NOT be added to the
        call kwargs — defaulting to JSON mode would break free-text
        responses (the planner/coder/reviewer all return free text JSON,
        but the user-facing chat specialists return prose).
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=10, completion_tokens=5))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert "response_format" not in mock.call_args.kwargs

    @pytest.mark.asyncio
    async def test_complete_ignores_non_json_object_response_format(self, monkeypatch):
        """Only ``{"type": "json_object"}`` triggers the response_format
        forwarding — other shapes (e.g. ``{"type": "text"}``) must NOT be
        passed, because not all vendors support them and ARNES's contract
        is "json_object mode or nothing".
        """
        litellm_resp = _make_response(usage=Usage(prompt_tokens=10, completion_tokens=5))
        mock = _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
            response_format={"type": "text"},
        )

        assert "response_format" not in mock.call_args.kwargs


# ============================================================
# 6. complete() handles missing usage in response
# ============================================================


class TestLiteLLMCompleteMissingUsage:
    @pytest.mark.asyncio
    async def test_complete_handles_missing_usage(self, monkeypatch):
        """Some litellm code paths (cached responses, certain vendor
        short-circuits) return ``usage=None``. ``complete()`` must not
        raise — it must fall back to 0 tokens and $0 cost.
        """
        litellm_resp = _make_response(
            content="ok",
            usage=None,
            model="openai/gpt-4o",
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert response.content == "ok"
        assert response.usage.tokens_in == 0
        assert response.usage.tokens_out == 0
        assert response.usage.cost_usd == 0.0
        # Model still recorded for observability, even when usage is missing.
        assert response.usage.model == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_complete_handles_none_content(self, monkeypatch):
        """When litellm returns ``content=None`` (typical for a pure
        tool-call response with no preamble), ``complete()`` must coerce
        to empty string — downstream code does ``response.content.lower()``
        and similar without a None-check.
        """
        litellm_resp = _make_response(
            content=None,
            usage=Usage(prompt_tokens=5, completion_tokens=3),
        )
        _patch_acompletion(monkeypatch, litellm_resp)

        provider = LiteLLMProvider()
        response = await provider.complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )

        assert response.content == ""


# ============================================================
# Bonus: stream_complete stub
# ============================================================


class TestLiteLLMStreamStub:
    @pytest.mark.asyncio
    async def test_stream_complete_raises_not_implemented_when_iterated(self):
        """``stream_complete()`` returns an async iterator (so the call
        site doesn't crash on a TypeError), but iterating it raises
        ``NotImplementedError("Streaming coming in v0.2")`` immediately —
        matching the README's v0.2 commitment.
        """
        provider = LiteLLMProvider()
        stream = provider.stream_complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
        )
        # The generator hasn't started executing yet — calling .stream_complete()
        # alone must NOT raise (otherwise middleware that inspects the stream
        # shape before consuming it would break).
        assert stream is not None

        with pytest.raises(NotImplementedError, match=r"Streaming coming in v0\.2"):
            async for _chunk in stream:
                # If we ever get here, the stub didn't raise.
                pytest.fail("stream_complete stub yielded a chunk instead of raising")

    @pytest.mark.asyncio
    async def test_stream_complete_signature_accepts_standard_kwargs(self):
        """Smoke-test that the stub accepts the same kwargs as ``complete()``
        — callers should be able to swap ``complete`` for ``stream_complete``
        without changing the call site (forward-compatibility for v0.2).
        """
        provider = LiteLLMProvider()
        # Just construct the async iterator; we won't iterate it (that raises).
        stream = provider.stream_complete(
            [LLMMessage(role="user", content="hi")],
            model="openai/gpt-4o",
            tools=[{"type": "function", "function": {"name": "noop"}}],
            temperature=0.5,
            max_tokens=100,
            response_format={"type": "json_object"},
            response_schema={"type": "object"},
            top_p=0.9,
        )
        # Close the generator without iterating (avoids the NotImplementedError).
        await stream.aclose()
