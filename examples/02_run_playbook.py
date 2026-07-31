#!/usr/bin/env python3
"""
ARNES Example: Execute a Playbook

Compile and execute a YAML playbook programmatically.

Usage:
    python examples/02_run_playbook.py

Expected output:
    Playbook: hello-world
    Success: True
    Steps executed: 2
    Bitácora saved to: bitacora-hello-world-<timestamp>.md
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.middleware.cost_guard import CostBudget
from arnes.playbooks.compiler import PlaybookCompiler
from arnes.playbooks.executor import PlaybookExecutor


class DemoMockProvider(LLMProvider):
    """Mock that returns schema-valid JSON for each specialist."""

    async def complete(self, messages, *, model="mock", **kwargs):
        sys_msg = next((m for m in messages if m.role == "system"), None)
        sys_content = sys_msg.content if sys_msg else ""

        if "@planner" in sys_content:
            content = '{"steps": [{"id": "s1", "specialist": "@coder", "input": {}}]}'
        elif "@coder" in sys_content:
            content = '{"files": [{"path": "app.py", "language": "python", "content": "from flask import Flask\\napp = Flask(__name__)\\n@app.route(\\"/\\")\\ndef hello():\\n    return \\"Hello!\\""}], "summary": "Flask app with hello endpoint", "assumptions": [], "warnings": []}'
        elif "@reviewer" in sys_content:
            content = '{"verdict": "approve", "issues": [], "summary": "Clean code"}'
        else:
            content = '{"result": "ok"}'

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

    def list_models(self):
        return ["mock"]


async def main():
    # Path to the example playbook
    playbook_path = Path(__file__).parent.parent / "manuals" / "hello-world.yaml"

    # Compile
    playbook = PlaybookCompiler.from_file(playbook_path)
    print(f"Playbook: {playbook.metadata.name}")
    print(f"Objective: {playbook.metadata.objective}")
    print(f"Steps: {len(playbook.steps)}")
    print()

    # Execute
    executor = PlaybookExecutor(
        provider=DemoMockProvider(),
        cost_budget=CostBudget(task_budget_usd=1.0),
    )

    result = await executor.run(playbook)

    print(f"Success: {result.success}")
    print(f"Steps executed: {result.steps_executed}")
    print(f"Steps failed: {result.steps_failed}")
    print(f"Duration: {result.duration_s:.3f}s")
    print(f"Tokens in/out: {result.total_tokens_in}/{result.total_tokens_out}")
    print(f"Cost: ${result.total_cost_usd:.4f}")

    # Save bitácora
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bitacora_path = f"bitacora-{playbook.metadata.name}-{ts}.md"
    Path(bitacora_path).write_text(result.to_markdown(), encoding="utf-8")
    print(f"\nBitácora saved to: {bitacora_path}")


if __name__ == "__main__":
    asyncio.run(main())
