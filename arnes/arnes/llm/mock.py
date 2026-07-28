"""Mock LLM provider for testing. Deterministic, no network calls."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


class MockLLMProvider(LLMProvider):
    """Deterministic mock for tests. Returns predictable responses based
    on a hash of the input messages. Useful for snapshot tests."""

    def __init__(self, *, default_response: str = "Mock response") -> None:
        self.default_response = default_response
        self.call_count = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "mock",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,  # Accepted but ignored
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1

        # Deterministic response based on input hash
        input_hash = hashlib.sha256(
            json.dumps([m.model_dump() for m in messages], default=str, sort_keys=True).encode()
        ).hexdigest()[:8]

        content = self.default_response
        if response_format and response_format.get("type") == "json_object":
            # Return mock JSON matching common schemas
            content = json.dumps(
                {
                    "mock": True,
                    "input_hash": input_hash,
                    "response": self.default_response,
                }
            )

        # Estimate tokens (4 chars ≈ 1 token)
        tokens_in = sum(len(m.content) // 4 for m in messages)
        tokens_out = len(content) // 4

        return LLMResponse(
            content=content,
            tool_calls=[],
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,  # Mock is free
                model=model,
                cached=False,
            ),
            model=model,
        )

    def list_models(self) -> list[str]:
        return ["mock-llm"]
