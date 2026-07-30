"""
ARNES Token Optimizer — middleware that reduces token usage on every LLM call.

Combines 4 techniques (v0.1 implements routing + cache; compaction + few-shot
pruning land in v0.2/v0.3):

1. Model routing — simple tasks → cheap model, complex tasks → capable model.
2. Semantic cache — if we've seen this input before, return cached response.
3. Context compaction — summarize prior context before sending (v0.2).
4. Few-shot pruning — if N examples given and model gets it in 2, drop the rest (v0.3).

Target: 40-65% token reduction without touching playbook logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from pydantic import BaseModel

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse
from arnes.thread.events import Event, EventType

logger = structlog.get_logger(__name__)


# Routing rules: if input < N tokens and no tools → use cheap model
_ROUTING_RULES = [
    # (max_input_tokens, has_tools, fallback_model)
    (500, False, "ollama/llama3.2"),  # tiny input, no tools → local
    (2000, False, "anthropic/claude-3-5-haiku-20241022"),  # short, no tools → Haiku
    # Otherwise keep the user-specified model
]


class CacheEntry(BaseModel):
    """One entry in the semantic cache."""

    input_hash: str
    response: LLMResponse
    created_at: float
    hit_count: int = 0


class TokenOptimizer(LLMProvider):
    """Middleware that wraps an LLMProvider and optimizes token usage.

    Usage:
        provider = get_provider("anthropic/claude-sonnet-4-20250514")
        optimizer = TokenOptimizer(provider)
        response = await optimizer.complete(messages, model="anthropic/claude-sonnet-4-20250514")
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        enable_cache: bool = True,
        enable_routing: bool = True,
        cache_ttl_s: int = 3600,
        cache_max_entries: int = 1000,
    ) -> None:
        self.provider = provider
        self.enable_cache = enable_cache
        self.enable_routing = enable_routing
        self.cache_ttl_s = cache_ttl_s
        self.cache_max_entries = cache_max_entries
        self._cache: dict[str, CacheEntry] = {}
        # Lock serializes cache dict mutations and hit/miss counter
        # increments. Without it, two concurrent ``complete()`` calls for
        # the same uncached key could both miss, both call the provider,
        # and both write — a benign race today (idempotent response) but a
        # maintainability hazard and a source of flaky stats. The provider
        # call itself runs OUTSIDE the lock so slow LLM calls don't
        # serialize concurrent requests for different keys.
        self._cache_lock = asyncio.Lock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._routing_decisions = 0
        self._tokens_saved = 0
        # Event sink shared with the outer CostGuard (if any). The executor
        # drains this list after each step and appends the events to the
        # Thread. See CostGuard._propagate_event_sink().
        self._events: list[Event] = []
        # Marker so specialists can detect already-wrapped providers
        self._arnes_wrapped = True

    def _emit(self, event: Event) -> None:
        """Append an event to the shared sink (drained by the executor)."""
        self._events.append(event)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Optimized completion. Routes to cheaper model when safe, checks cache first."""
        # Step 1: route to cheaper model if input is simple
        effective_model = model
        if self.enable_routing and tools is None:
            effective_model = self._route_model(messages, model)

        # Step 2: check cache (under lock — cache_hits/cache_misses increments
        # and the ``hit_count`` mutation on the shared CacheEntry must be
        # serialized to avoid lost updates under concurrent complete() calls).
        cache_key = self._cache_key(messages, effective_model, tools, response_schema, kwargs)
        if self.enable_cache:
            async with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached and self._is_fresh(cached):
                    self._cache_hits += 1
                    cached.hit_count += 1
                    # Mark as cached in usage
                    cached.response.usage.cached = True
                    self._tokens_saved += (
                        cached.response.usage.tokens_in + cached.response.usage.tokens_out
                    )
                    logger.info(
                        "cache_hit",
                        cache_key=cache_key[:8],
                        tokens_saved=(
                            cached.response.usage.tokens_in + cached.response.usage.tokens_out
                        ),
                    )
                    self._emit_cache_hit(cached, effective_model)
                    return cached.response
                self._cache_misses += 1

        # Step 3: call underlying provider (NOT under the lock — provider
        # calls may be slow and would serialize all concurrent complete()
        # calls for different keys, defeating the point of the lock).
        response = await self.provider.complete(
            messages,
            model=effective_model,
            tools=tools,
            response_schema=response_schema,
            **kwargs,
        )

        # Step 4: store in cache (under lock — _cache.__setitem__ and the
        # del _cache[key] inside _evict_if_needed must be serialized).
        if self.enable_cache and response.content:
            async with self._cache_lock:
                self._cache[cache_key] = CacheEntry(
                    input_hash=cache_key,
                    response=response,
                    created_at=time.time(),
                )
                self._evict_if_needed()

        return response

    # ============================================================
    # Routing
    # ============================================================

    def _emit_cache_hit(self, cached: CacheEntry, effective_model: str) -> None:
        """Emit a CACHE_HIT event for observability.

        The TokenOptimizer does not have direct access to the Thread (it only
        sees LLMMessage lists). The event is appended to the shared
        ``self._events`` sink with a nil thread_id placeholder; the
        PlaybookExecutor patches the real thread_id and step_id when it
        drains the sink after each step.
        """
        from arnes.middleware.cost_guard import NIL_THREAD_ID

        # Build a generic Event of type CACHE_HIT. We use the base Event
        # class because there is no dedicated CacheHitEvent subclass — the
        # typed payload lives in ``data`` and consumers dispatch on
        # ``event.type``.
        event = Event(
            type=EventType.CACHE_HIT,
            thread_id=NIL_THREAD_ID,
            data={
                "model": effective_model,
                "tokens_in": cached.response.usage.tokens_in,
                "tokens_out": cached.response.usage.tokens_out,
                "tokens_saved": cached.response.usage.tokens_in + cached.response.usage.tokens_out,
                "hit_count": cached.hit_count,
            },
        )
        self._emit(event)

    def _emit_model_routed(
        self,
        *,
        from_model: str,
        to_model: str,
        reason: str,
        input_tokens_est: int,
    ) -> None:
        """Emit a MODEL_ROUTED event for observability.

        Fired whenever the routing logic actually downgrades the requested
        model to a cheaper one (no event when the requested model is kept
        as-is). The event is appended to the shared ``self._events`` sink
        with a nil thread_id placeholder; the PlaybookExecutor patches the
        real thread_id and step_id when it drains the sink.
        """
        from arnes.middleware.cost_guard import NIL_THREAD_ID

        event = Event(
            type=EventType.MODEL_ROUTED,
            thread_id=NIL_THREAD_ID,
            data={
                "from_model": from_model,
                "to_model": to_model,
                "reason": reason,
                "input_tokens_est": input_tokens_est,
            },
        )
        self._emit(event)

    def _route_model(self, messages: list[LLMMessage], requested_model: str) -> str:
        """Pick a cheaper model if the task is simple."""
        input_tokens_est = sum(len(m.content) // 4 for m in messages)
        for max_tokens, has_tools, fallback in _ROUTING_RULES:
            if input_tokens_est <= max_tokens:
                # Only route if requested model is more expensive than fallback
                if self._is_more_expensive(requested_model, fallback):
                    self._routing_decisions += 1
                    logger.info(
                        "model_routed",
                        from_model=requested_model,
                        to_model=fallback,
                        reason=f"input<{max_tokens} tokens, no tools",
                    )
                    self._emit_model_routed(
                        from_model=requested_model,
                        to_model=fallback,
                        reason=f"input<{max_tokens} tokens, no tools",
                        input_tokens_est=input_tokens_est,
                    )
                    return fallback
                break
        return requested_model

    def _is_more_expensive(self, model_a: str, model_b: str) -> bool:
        """Heuristic: is model_a more expensive than model_b?"""
        # Very rough tier ranking
        tiers = {
            "ollama": 0,  # free
            "groq": 1,
            "haiku": 1,
            "mini": 1,
            "flash": 1,
            "sonnet": 2,
            "gpt-4o": 2,
            "opus": 3,
            "o1": 3,
            "pro": 3,
        }
        a_tier = max((t for k, t in tiers.items() if k in model_a.lower()), default=2)
        b_tier = max((t for k, t in tiers.items() if k in model_b.lower()), default=2)
        return a_tier > b_tier

    # ============================================================
    # Cache
    # ============================================================

    def _cache_key(
        self,
        messages: list[LLMMessage],
        model: str,
        tools: list[dict[str, Any]] | None,
        response_schema: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> str:
        """Stable hash of inputs for cache key.

        Includes ``response_schema`` so two calls with the same messages but
        different requested output schemas cannot return each other's cached
        responses (cache-poisoning defense).
        """
        payload = json.dumps(
            {
                "messages": [m.model_dump() for m in messages],
                "model": model,
                "tools": tools,
                "response_schema": response_schema,
                "kwargs": {k: v for k, v in kwargs.items() if k != "temperature"},
            },
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _is_fresh(self, entry: CacheEntry) -> bool:
        return (time.time() - entry.created_at) < self.cache_ttl_s

    def _evict_if_needed(self) -> None:
        """LRU eviction when cache is full.

        Must be called while holding ``self._cache_lock`` — mutates
        ``self._cache`` via ``del``.
        """
        if len(self._cache) <= self.cache_max_entries:
            return
        # Sort by created_at and remove oldest 10%
        sorted_entries = sorted(self._cache.items(), key=lambda x: x[1].created_at)
        evict_count = max(1, len(self._cache) // 10)
        for key, _ in sorted_entries[:evict_count]:
            del self._cache[key]

    # ============================================================
    # Stats
    # ============================================================

    def stats(self) -> dict[str, Any]:
        """Return optimization stats for observability.

        Best-effort snapshot — this is a sync method and cannot acquire the
        async ``_cache_lock``, so the returned values may reflect an
        in-flight ``complete()`` call. Acceptable for observability (called
        rarely, e.g. at end of run); not for fine-grained concurrency
        control.
        """
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": (
                self._cache_hits / (self._cache_hits + self._cache_misses)
                if (self._cache_hits + self._cache_misses) > 0
                else 0.0
            ),
            "cache_size": len(self._cache),
            "routing_decisions": self._routing_decisions,
            "tokens_saved": self._tokens_saved,
            "estimated_savings_usd": self._tokens_saved * 0.000003,  # rough $3/1M tokens
        }

    def reset_stats(self) -> None:
        """Reset stats counters. Best-effort — see :meth:`stats`."""
        self._cache_hits = 0
        self._cache_misses = 0
        self._routing_decisions = 0
        self._tokens_saved = 0

    def list_models(self) -> list[str]:
        """Delegate to the wrapped provider (middleware is transparent)."""
        return self.provider.list_models()

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
        """Delegate streaming to the wrapped provider (passthrough).

        v0.1 behavior: thin passthrough — no cache lookup, no cache
        population, no routing decision emission. The streaming path
        bypasses the semantic cache entirely because:

        1. Caching a stream requires reassembling the full response before
           computing the cache key, which defeats the latency benefit of
           streaming.
        2. Routing decisions on streaming calls would emit a
           ``MODEL_ROUTED`` event mid-stream, interleaving with token
           chunks — the AG-UI transport (v0.2) will handle this cleanly,
           but ad-hoc emission today would confuse consumers expecting a
           pure token stream.

        Full streaming-aware cache (key on the reassembled final response,
        serve cached streams as a single ``LLMResponse`` chunk) and
        streaming-aware routing (emit ``MODEL_ROUTED`` before the first
        token chunk) land in v0.2.
        """
        async for chunk in self.provider.stream_complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_schema=response_schema,
            **kwargs,
        ):
            yield chunk

    def peek_cost(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> float | None:
        """Delegate pre-flight cost estimation to the wrapped provider."""
        peek = getattr(self.provider, "peek_cost", None)
        if not callable(peek):
            return None
        estimate = peek(
            model=model,
            messages=messages,
            tools=tools,
            response_schema=response_schema,
            **kwargs,
        )
        if estimate is None:
            return None
        return float(estimate)
