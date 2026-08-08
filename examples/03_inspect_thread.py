#!/usr/bin/env python3
"""
ARNES Example: Inspect the Thread (Event Log)

Shows how to use the Thread API to inspect the event log of a run.

Usage:
    python examples/03_inspect_thread.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arnes.llm.base import LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor
from arnes.thread import EventType


class DemoMockProvider(LLMProvider):
    async def complete(self, messages, *, model="mock", **kwargs):
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = '{"files": [], "summary": "ok", "assumptions": [], "warnings": []}'
        else:
            content = '{"result": "ok"}'

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(tokens_in=10, tokens_out=5, cost_usd=0.0, model=model),
            model=model,
        )

    async def stream_complete(self, messages, *, model="mock", **kwargs):
        response = await self.complete(messages, model=model, **kwargs)
        yield response

    def list_models(self):
        return ["mock"]


async def main():
    playbook_path = Path(__file__).parent.parent / "manuals" / "hello-world.yaml"
    playbook = PlaybookCompiler.from_file(playbook_path)

    executor = PlaybookExecutor(
        provider=DemoMockProvider(),
        cost_budget=CostBudget(task_budget_usd=1.0),
    )

    result = await executor.run(playbook)

    # Inspect the thread
    thread = result.thread
    print(f"Thread ID: {thread.id}")
    print(f"Total events: {len(thread)}")
    print()

    # List all events by type
    print("Event timeline:")
    for event in thread:
        step_info = f" [step={event.step_id}]" if event.step_id else ""
        spec_info = f" [specialist={event.specialist}]" if event.specialist else ""
        print(f"  {event.timestamp.strftime('%H:%M:%S.%f')[:-3]} {event.type.value}{step_info}{spec_info}")

    print()

    # Filter by event type
    step_starts = thread.filter_by_type(EventType.STEP_STARTED)
    step_completes = thread.filter_by_type(EventType.STEP_COMPLETED)
    run_completed = thread.filter_by_type(EventType.RUN_COMPLETED)

    print(f"Step started events: {len(step_starts)}")
    print(f"Step completed events: {len(step_completes)}")
    print(f"Run completed events: {len(run_completed)}")

    # Reduce to current state
    state = thread.reduce()
    print("\nReduced state:")
    print(f"  Status: {state['status']}")
    print(f"  Steps: {list(state['steps'].keys())}")
    print(f"  Total tokens in: {state['total_tokens_in']}")
    print(f"  Total tokens out: {state['total_tokens_out']}")


if __name__ == "__main__":
    asyncio.run(main())
