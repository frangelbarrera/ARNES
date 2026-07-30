#!/usr/bin/env python3
"""
ARNES Example: Streaming Responses

Shows how to stream a specialist's response token by token.

Usage:
    python examples/05_streaming.py

Expected output:
    Streaming @planner response...
    {"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}
    ---
    Done. Tokens: 20 in, 15 out. Cost: $0.0000
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arnes import Harness, HarnessConfig
from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


class StreamingMockProvider(LLMProvider):
    """Mock that simulates streaming by yielding tokens one at a time."""

    async def complete(self, messages, *, model="mock", **kwargs):
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
        """Yield tokens one at a time to simulate real streaming."""
        content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        tokens_in = sum(len(m.content) // 4 for m in messages)
        tokens_out = len(content) // 4

        # Yield 10-character chunks to simulate token streaming
        chunk_size = 10
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            yield LLMResponse(
                content=chunk,
                tool_calls=[],
                usage=LLMUsage(tokens_in=0, tokens_out=0, cost_usd=0.0, model=model),
                model=model,
            )

        # Final chunk with full usage
        yield LLMResponse(
            content="",
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,
                model=model,
            ),
            model=model,
        )

    def list_models(self):
        return ["mock"]


async def main():
    harness = Harness(
        config=HarnessConfig(model="mock/test", budget_usd=0.10),
        provider=StreamingMockProvider(),
    )

    print("Streaming @planner response...")
    print("---")

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    async for chunk in harness.stream("@planner", {"task": "Plan a simple feature"}):
        # Print each chunk as it arrives
        print(chunk.content, end="", flush=True)
        total_tokens_in += chunk.usage.tokens_in
        total_tokens_out += chunk.usage.tokens_out
        total_cost += chunk.usage.cost_usd

    print()
    print("---")
    print(f"Done. Tokens: {total_tokens_in} in, {total_tokens_out} out. Cost: ${total_cost:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
