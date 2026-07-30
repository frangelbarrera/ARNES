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
from collections.abc import AsyncIterator
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

    # Marker so specialists can detect already-wrapped providers and avoid
    # double-wrapping the middleware stack. Set to True by all middleware.
    _arnes_wrapped: bool = False

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
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion."""
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models for this provider."""
        raise NotImplementedError

    @abstractmethod
    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Stream a completion as an async iterator of ``LLMResponse`` chunks.

        The contract mirrors :meth:`complete` — same parameters, same
        ``LLMResponse`` shape — but the response is delivered as a sequence
        of partial chunks (typically one per generated token group) instead
        of a single fully-buffered object.

        Contract:

        - Each chunk's ``content`` is *just the new token* (not the
          accumulated content). Callers that need the full text accumulate
          themselves.
        - Intermediate chunks carry an empty ``LLMUsage`` (zeros) — token
          counts are only known once generation completes.
        - A final chunk with the full ``LLMUsage`` (tokens + cost) is
          yielded after the stream ends, when the vendor exposes usage.

        Implementations:

        * :class:`MockLLMProvider` yields the full response in a single
          chunk (deterministic, no network).
        * :class:`OllamaProvider` reads NDJSON from ``/api/chat`` with
          ``stream: true``.
        * :class:`LiteLLMProvider` iterates the ``CustomStreamWrapper``
          from ``litellm.acompletion(stream=True)``.
        """
        ...  # pragma: no cover
        yield  # type: ignore[misc]  # pragma: no cover - makes this an async generator

    def peek_cost(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> float | None:
        """Estimate the USD cost of the upcoming ``complete()`` call.

        Returns ``None`` if the provider cannot estimate the cost upfront
        (the default — real LLM costs depend on the response, which isn't
        known until the call returns). CostGuard uses this for **pre-flight
        budget checking**: when a non-None estimate is available and
        ``spent + estimate > budget``, the call is rejected *before* it
        reaches the provider, preventing any spend on a call that would
        breach the budget.

        Override in subclasses that can provide accurate estimates
        (e.g. fixed-cost mock providers, or providers with per-token
        pricing tables and a local tokenizer).
        """
        return None
