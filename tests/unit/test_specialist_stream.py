"""Tests for ``Specialist.stream()``.

The streaming specialist mirrors ``Harness.stream()`` at the specialist
layer: it yields ``LLMResponse`` chunks as they arrive from the provider
and emits a single ``AssistantMessageEvent`` after the stream completes
so the audit trail records streaming runs the same way it records
non-streaming runs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget, CostGuard
from arnes.middleware.token_optimizer import TokenOptimizer
from arnes.middleware.verification import VerificationConfig, VerificationLayer
from arnes.specialists.planner import Planner
from arnes.thread.events import EventType
from arnes.tools.base import ToolContext


class StreamingMockProvider(LLMProvider):
    """Mock that simulates token-by-token streaming."""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=sum(len(m.content) // 4 for m in messages),
                tokens_out=len(content) // 4,
                cost_usd=0.0,
                model=model,
            ),
            model=model,
        )

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        self.call_count += 1
        content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        tokens_in = sum(len(m.content) // 4 for m in messages)

        # Yield 3 content chunks
        chunk_size = max(1, len(content) // 3)
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            if chunk:
                yield LLMResponse(
                    content=chunk,
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=0, tokens_out=0, cost_usd=0.0, model=model),
                    model=model,
                )

        # Final chunk with usage
        yield LLMResponse(
            content="",
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=len(content) // 4,
                cost_usd=0.0,
                model=model,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock"]


def _build_wrapped_provider(provider: LLMProvider) -> CostGuard:
    """Build the standard middleware stack (TokenOptimizer → Verification → CostGuard)."""
    inner: LLMProvider = TokenOptimizer(provider, enable_cache=True)
    inner = VerificationLayer(
        inner,
        VerificationConfig(structured_outputs=True, refusal_pattern=True),
    )
    return CostGuard(inner, budget=CostBudget(task_budget_usd=1.0))


class TestSpecialistStream:
    """Tests for ``Specialist.stream()``."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        """Specialist.stream() yields LLMResponse chunks."""
        provider = StreamingMockProvider()
        wrapped = _build_wrapped_provider(provider)
        specialist = Planner()
        ctx = ToolContext(thread_id=__import__("uuid").uuid4(), specialist="@planner")

        chunks = []
        async for chunk in specialist.stream({"task": "Plan a feature"}, ctx, provider=wrapped):
            chunks.append(chunk)

        # Should yield 3 content chunks + 1 final usage chunk = 4
        assert len(chunks) >= 3

        full_content = "".join(c.content for c in chunks)
        assert "steps" in full_content
        assert "@coder" in full_content

    @pytest.mark.asyncio
    async def test_stream_final_chunk_has_usage(self):
        """The final chunk should have non-zero usage."""
        provider = StreamingMockProvider()
        wrapped = _build_wrapped_provider(provider)
        specialist = Planner()
        ctx = ToolContext(thread_id=__import__("uuid").uuid4(), specialist="@planner")

        chunks = []
        async for chunk in specialist.stream({"task": "Plan"}, ctx, provider=wrapped):
            chunks.append(chunk)

        final = chunks[-1]
        assert final.usage.tokens_in > 0
        assert final.usage.tokens_out > 0

    @pytest.mark.asyncio
    async def test_stream_emits_assistant_message_event_to_sink(self):
        """After streaming, the wrapped provider's _events sink has an AssistantMessageEvent."""
        provider = StreamingMockProvider()
        wrapped = _build_wrapped_provider(provider)
        specialist = Planner()
        ctx = ToolContext(thread_id=__import__("uuid").uuid4(), specialist="@planner")

        # Consume the stream fully so the post-stream audit event is emitted.
        chunks = []
        async for chunk in specialist.stream({"task": "Plan"}, ctx, provider=wrapped):
            chunks.append(chunk)

        # The specialist._emit_assistant_message helper appends to the
        # wrapped provider's _events sink (same pattern as run()).
        events = getattr(wrapped, "_events", [])
        assert len(events) >= 1

        audit_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
        assert len(audit_events) == 1

        event = audit_events[0]
        assert event.specialist == "@planner"

        # Content matches the concatenated chunks
        full_content = "".join(c.content for c in chunks)
        assert event.data["content"] == full_content

        # Usage matches the final chunk
        final_chunk = chunks[-1]
        assert event.data["tokens_in"] == final_chunk.usage.tokens_in
        assert event.data["tokens_out"] == final_chunk.usage.tokens_out

    @pytest.mark.asyncio
    async def test_stream_wraps_unwrapped_provider(self):
        """If the provider is not already wrapped, stream() wraps it with the full stack."""
        # Pass a raw provider (no _arnes_wrapped marker) — the specialist
        # should auto-wrap it with CostGuard → Verification → TokenOptimizer.
        provider = StreamingMockProvider()
        specialist = Planner()
        ctx = ToolContext(thread_id=__import__("uuid").uuid4(), specialist="@planner")

        chunks = []
        async for chunk in specialist.stream({"task": "Plan"}, ctx, provider=provider):
            chunks.append(chunk)

        # Stream should still work — auto-wrapping is a safety net.
        assert len(chunks) > 0
        full_content = "".join(c.content for c in chunks)
        assert "steps" in full_content

    @pytest.mark.asyncio
    async def test_stream_no_tool_calls_terminates_after_one_iteration(self):
        """Streaming with a provider that returns no tool_calls terminates
        after one ReAct iteration (no tool execution).

        The streaming path participates in the ReAct loop — if the
        provider streams tool_calls, the specialist executes the tools and
        starts another streaming iteration. This mock returns a complete
        JSON response without ``tool_calls``, so the loop exits after one
        iteration. The key invariant: we got chunks, the call_count is
        exactly 1 (one stream_complete call, no follow-up calls from a
        ReAct continuation).
        """
        from arnes.tools.registry import get_default_registry

        provider = StreamingMockProvider()
        wrapped = _build_wrapped_provider(provider)
        specialist = Planner()
        ctx = ToolContext(thread_id=__import__("uuid").uuid4(), specialist="@planner")
        tool_registry = get_default_registry()

        chunks = []
        async for chunk in specialist.stream(
            {"task": "Plan"}, ctx, provider=wrapped, tool_registry=tool_registry
        ):
            chunks.append(chunk)

        # The mock provider returns a complete JSON response without
        # tool_calls, so even though the ReAct loop is wired, it
        # terminates immediately after 1 iteration.
        assert provider.call_count == 1
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_stream_executes_react_tool_loop_when_tool_calls_present(self):
        """Streaming participates in the ReAct loop.

        When the provider streams a final chunk with ``tool_calls`` populated,
        the specialist must execute the tool, append the result to messages,
        and start another streaming iteration. The final iteration's stream
        (with no tool_calls) terminates the loop.

        Streaming now participates in the ReAct tool-use loop (previously
        it bypassed tool execution).
        """
        import uuid

        from arnes.tools.registry import get_default_registry

        # Provider that streams ONE iteration with a tool_call, then a
        # SECOND iteration with a plain JSON final response.
        class ReActStreamingProvider(LLMProvider):
            """Two-iteration streaming provider for the ReAct-with-stream test."""

            def __init__(self) -> None:
                self.call_count = 0

            async def complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                **kwargs: Any,
            ) -> LLMResponse:
                self.call_count += 1
                return LLMResponse(
                    content='{"steps": []}',
                    tool_calls=[],
                    usage=LLMUsage(tokens_in=1, tokens_out=1, cost_usd=0.0, model=model),
                    model=model,
                )

            async def stream_complete(
                self,
                messages: list[LLMMessage],
                *,
                model: str = "mock",
                **kwargs: Any,
            ) -> AsyncIterator[LLMResponse]:
                self.call_count += 1
                if self.call_count == 1:
                    # Iteration 1: stream a tool_call.
                    yield LLMResponse(
                        content='{"thinking": "need to read fs"}',
                        tool_calls=[
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "fs_read",
                                    "arguments": '{"path": "README.md"}',
                                },
                            }
                        ],
                        usage=LLMUsage(
                            tokens_in=10,
                            tokens_out=5,
                            cost_usd=0.0,
                            model=model,
                        ),
                        model=model,
                    )
                else:
                    # Iteration 2: final response (no tool_calls).
                    content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
                    yield LLMResponse(
                        content=content,
                        tool_calls=[],
                        usage=LLMUsage(
                            tokens_in=sum(len(m.content) // 4 for m in messages),
                            tokens_out=len(content) // 4,
                            cost_usd=0.0,
                            model=model,
                        ),
                        model=model,
                    )

            def list_models(self) -> list[str]:
                return ["mock"]

        provider = ReActStreamingProvider()
        wrapped = _build_wrapped_provider(provider)
        specialist = Planner()
        ctx = ToolContext(thread_id=uuid.uuid4(), specialist="@planner")
        tool_registry = get_default_registry()

        chunks = []
        async for chunk in specialist.stream(
            {"task": "Plan"}, ctx, provider=wrapped, tool_registry=tool_registry
        ):
            chunks.append(chunk)

        # TWO streaming iterations: 1st returned tool_calls → execute →
        # 2nd returned final JSON.
        assert provider.call_count == 2, (
            f"Expected 2 stream_complete calls (ReAct loop), got {provider.call_count}"
        )
        # Final accumulated content includes the second iteration's JSON.
        full_content = "".join(c.content for c in chunks)
        assert "steps" in full_content

        # TWO AssistantMessageEvents emitted (one per iteration).
        from arnes.thread.events import EventType

        events = getattr(wrapped, "_events", [])
        audit_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
        assert len(audit_events) == 2, (
            f"Expected 2 AssistantMessageEvents (one per ReAct iteration), got {len(audit_events)}"
        )
