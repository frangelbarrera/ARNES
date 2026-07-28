"""LiteLLM-based provider for paid vendors (Anthropic, OpenAI, Google, Groq, etc.)."""

from __future__ import annotations

import os
from typing import Any

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


# Cost per 1M tokens (USD) — kept up to date as of 2026-01. Used for cost guard.
# Source: official pricing pages. Update when vendors change pricing.
_PRICING_USD_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "anthropic/claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "openai/gpt-4o": {"input": 2.50, "output": 10.00},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai/o1": {"input": 15.00, "output": 60.00},
    "openai/o1-mini": {"input": 3.00, "output": 12.00},
    "google/gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "groq/llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate cost in USD for a single LLM call."""
    pricing = _PRICING_USD_PER_1M_TOKENS.get(model)
    if not pricing:
        # Fallback: assume $1/1M tokens (conservative)
        return (tokens_in + tokens_out) * 1.0 / 1_000_000
    return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000


class LiteLLMProvider(LLMProvider):
    """Universal provider for paid vendors via LiteLLM.

    Reads API keys from environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.).
    NEVER stores or logs the keys.
    """

    def __init__(self) -> None:
        # Validate that LiteLLM is available
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "LiteLLM is required for paid providers. Install with: pip install litellm"
            ) from e

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        import litellm

        # LiteLLM uses "provider/model" format directly
        litellm_messages = [m.model_dump(exclude_none=True) for m in messages]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": litellm_messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        if response_format and response_format.get("type") == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        # LiteLLM async call
        response = await litellm.acompletion(**kwargs)

        # Extract standard fields
        content = response.choices[0].message.content or ""
        tool_calls = []
        if hasattr(response.choices[0].message, "tool_calls") and response.choices[0].message.tool_calls:
            for tc in response.choices[0].message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )

        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        cost = _estimate_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                model=model,
                cached=False,
            ),
            model=model,
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    def list_models(self) -> list[str]:
        return list(_PRICING_USD_PER_1M_TOKENS.keys())
