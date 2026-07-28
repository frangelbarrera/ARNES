"""
ARNES LLM provider abstraction.

Vendor-neutral. Default is Ollama (local). Supports Anthropic, OpenAI,
Google, Groq via LiteLLM.

The provider abstraction is intentionally minimal:
- take a list of messages + tool schemas
- return a response (content, tool_calls, usage)

All the heavy lifting (token optimization, verification, cost guard) is
done by middleware that wraps the provider, NOT by the provider itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None  # for tool messages
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class LLMUsage(BaseModel):
    """Token usage for a single LLM call."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    cached: bool = False  # True if served from semantic cache

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            cost_usd=self.cost_usd + other.cost_usd,
            model=other.model or self.model,
            cached=self.cached or other.cached,
        )


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: LLMUsage
    model: str = ""
    raw: dict[str, Any] | None = None  # vendor-specific raw response


class LLMProvider(ABC):
    """Abstract LLM provider. Implementations: OllamaProvider, AnthropicProvider, etc."""

    @abstractmethod
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
        """Generate a completion."""
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models for this provider."""
        raise NotImplementedError
