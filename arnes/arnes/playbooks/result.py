"""PlaybookRunResult — the structured return value of a playbook execution.

Extracted from ``arnes.playbooks.executor`` (SPLIT-R12) so the executor
module stays focused on the DAG walk. The result model is a plain pydantic
``BaseModel`` carrying the final ``Thread`` plus aggregate accounting
(steps executed/failed, tokens, cost, duration) and the per-step
``outputs`` map.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from arnes.thread import Thread


class PlaybookRunResult(BaseModel):
    """Result of running a playbook."""

    model_config = {"arbitrary_types_allowed": True}

    thread: Thread
    success: bool
    steps_executed: int = 0
    steps_failed: int = 0
    duration_s: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    outputs: dict[str, Any] = Field(default_factory=dict)  # step_id -> output
    error: str | None = None

    def to_markdown(self) -> str:
        """Render the run as a markdown bitácora."""
        return self.thread.to_markdown()
