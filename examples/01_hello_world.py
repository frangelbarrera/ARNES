#!/usr/bin/env python3
"""
ARNES Example: Hello World

The simplest possible ARNES usage — invoke a single specialist.

Usage:
    python examples/01_hello_world.py

Expected output:
    Specialist: @planner
    Success: True
    Output: {"steps": [...]}
"""

import asyncio
import sys
from pathlib import Path

# Add parent dir to path so we can import arnes
sys.path.insert(0, str(Path(__file__).parent.parent))

from arnes import Harness, HarnessConfig
from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


class DemoMockProvider(LLMProvider):
    """Simple mock that returns valid JSON for @planner."""

    async def complete(self, messages, *, model="mock", **kwargs):
        return LLMResponse(
            content='{"steps": [{"id": "s1", "specialist": "@coder", "input": {"task": "Implement the feature"}}]}',
            tool_calls=[],
            usage=LLMUsage(tokens_in=50, tokens_out=20, cost_usd=0.0, model=model),
            model=model,
        )

    def list_models(self):
        return ["mock"]


async def main():
    # Create a Harness with mock provider (no API key needed)
    harness = Harness(
        config=HarnessConfig(model="mock/test", budget_usd=0.10),
        provider=DemoMockProvider(),
    )

    # Invoke @planner
    result = await harness.run("@planner", {
        "task": "Plan a simple feature: add a hello endpoint to a Flask app"
    })

    print(f"Specialist: {result['specialist']}")
    print(f"Success: {result['success']}")

    if result["success"]:
        print(f"Output: {result['output']}")
    else:
        print(f"Error: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
