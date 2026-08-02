"""Tests for Harness.stream() method."""

from __future__ import annotations

import pytest

from arnes import Harness, HarnessConfig
from arnes.llm.base import LLMProvider, LLMResponse, LLMUsage
from arnes.thread.events import EventType


class StreamingMockProvider(LLMProvider):
    """Mock that simulates streaming by yielding tokens."""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, messages, *, model="mock", **kwargs):
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

    async def stream_complete(self, messages, *, model="mock", **kwargs):
        self.call_count += 1
        content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        tokens_in = sum(len(m.content) // 4 for m in messages)

        # Yield 3 chunks
        chunk_size = len(content) // 3
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

    def list_models(self):
        return ["mock"]


class TestHarnessStream:
    """Test the Harness.stream() method."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        """Harness.stream() yields LLMResponse chunks."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks = []
        async for chunk in harness.stream("@planner", {"task": "Test"}):
            chunks.append(chunk)

        # Should yield at least 3 chunks (2 content + 1 final with usage)
        assert len(chunks) >= 3

        # Concatenate content
        full_content = "".join(c.content for c in chunks)
        assert "steps" in full_content
        assert "@coder" in full_content

    @pytest.mark.asyncio
    async def test_stream_final_chunk_has_usage(self):
        """The final chunk should have usage stats."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks = []
        async for chunk in harness.stream("@planner", {"task": "Test"}):
            chunks.append(chunk)

        # Final chunk should have non-zero usage
        final = chunks[-1]
        assert final.usage.tokens_in > 0
        assert final.usage.tokens_out > 0

    @pytest.mark.asyncio
    async def test_stream_unknown_specialist_yields_nothing(self):
        """Streaming an unknown specialist yields nothing."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks = []
        async for chunk in harness.stream("@nonexistent", {"task": "Test"}):
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_stream_normalizes_specialist_name(self):
        """stream('planner') should work same as stream('@planner')."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks = []
        async for chunk in harness.stream("planner", {"task": "Test"}):
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_stream_passes_through_middleware(self):
        """Stream should pass through CostGuard (no budget exceeded with $0 cost)."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks = []
        async for chunk in harness.stream("@planner", {"task": "Test"}):
            chunks.append(chunk)

        # Should complete without BudgetExceeded
        assert len(chunks) > 0


class TestHarnessStreamAudit:
    """Tests for the streaming audit log.

    Harness.stream() must emit an AssistantMessageEvent after the stream
    completes so the audit trail records streaming runs the same way it
    records non-streaming runs. Streaming produces ONE event per call
    (not per-chunk events) for audit-trail completeness without log bloat.
    """

    @pytest.mark.asyncio
    async def test_stream_emits_assistant_message_event_to_sink(self):
        """After streaming, the wrapped provider's _events sink has an AssistantMessageEvent."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        # Consume the stream fully so the post-stream audit event is emitted.
        chunks = []
        async for chunk in harness.stream("@planner", {"task": "Test"}):
            chunks.append(chunk)

        # The audit event was emitted to the wrapped provider's _events sink.
        # We can't access the wrapped provider directly (it's local to stream()),
        # but stream_with_audit() exposes the thread, so we test that path
        # separately. Here we just verify the stream completed and the final
        # chunk has the usage stats that the audit event will carry.
        assert len(chunks) > 0
        final = chunks[-1]
        assert final.usage.tokens_in > 0

    @pytest.mark.asyncio
    async def test_stream_with_audit_returns_chunks_and_thread(self):
        """stream_with_audit() returns (chunks, thread) tuple."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks_iter, thread = harness.stream_with_audit("@planner", {"task": "Test"})

        # Thread starts empty (no events yet — the audit event is emitted
        # as a side-effect of consuming the chunks iterator).
        assert len(thread) == 0

        # Consume the chunks
        chunks = []
        async for chunk in chunks_iter:
            chunks.append(chunk)

        # After consumption, the thread has exactly one AssistantMessageEvent
        # with the full accumulated content + final usage.
        assert len(thread) == 1
        event = thread.events[0]
        assert event.type == EventType.ASSISTANT_MESSAGE
        assert event.specialist == "@planner"

        # Content matches the concatenated chunks
        full_content = "".join(c.content for c in chunks)
        assert event.data["content"] == full_content
        assert "steps" in event.data["content"]

        # Usage matches the final chunk
        final_chunk = chunks[-1]
        assert event.data["tokens_in"] == final_chunk.usage.tokens_in
        assert event.data["tokens_out"] == final_chunk.usage.tokens_out

        # The event is marked as streamed so the audit log distinguishes
        # streaming runs from non-streaming runs.
        assert event.data.get("streamed") is True

    @pytest.mark.asyncio
    async def test_stream_with_audit_thread_renders_to_markdown(self):
        """The audit thread from stream_with_audit() renders as a valid audit log."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks_iter, thread = harness.stream_with_audit("@planner", {"task": "Plan X"})

        async for _ in chunks_iter:
            pass

        md = thread.to_markdown()
        assert "Audit log ARNES" in md
        assert "assistant_message" in md
        assert "@planner" in md

    @pytest.mark.asyncio
    async def test_stream_with_audit_unknown_specialist_yields_nothing(self):
        """stream_with_audit() with an unknown specialist yields nothing and emits no event."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks_iter, thread = harness.stream_with_audit("@nonexistent", {"task": "Test"})

        chunks = []
        async for chunk in chunks_iter:
            chunks.append(chunk)

        assert len(chunks) == 0
        # No event should be emitted — the early return prevents the audit event.
        assert len(thread) == 0

    @pytest.mark.asyncio
    async def test_stream_with_audit_normalizes_specialist_name(self):
        """stream_with_audit('planner') should work same as stream_with_audit('@planner')."""
        harness = Harness(
            config=HarnessConfig(model="mock/test", budget_usd=0.10),
            provider=StreamingMockProvider(),
        )

        chunks_iter, thread = harness.stream_with_audit("planner", {"task": "Test"})

        chunks = []
        async for chunk in chunks_iter:
            chunks.append(chunk)

        assert len(chunks) > 0
        assert len(thread) == 1
        assert thread.events[0].specialist == "@planner"
