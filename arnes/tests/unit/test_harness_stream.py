"""Tests for Harness.stream() method."""

from __future__ import annotations

import pytest

from arnes import Harness, HarnessConfig
from arnes.llm.base import LLMProvider, LLMResponse, LLMUsage


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
