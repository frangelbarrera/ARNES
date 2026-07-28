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

import hashlib
import json
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

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


class TokenOptimizer:
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
        self._cache_hits = 0
        self._cache_misses = 0
        self._routing_decisions = 0
        self._tokens_saved = 0

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

        # Step 2: check cache
        cache_key = self._cache_key(messages, effective_model, tools, kwargs)
        if self.enable_cache:
            cached = self._cache.get(cache_key)
            if cached and self._is_fresh(cached):
                self._cache_hits += 1
                cached.hit_count += 1
                # Mark as cached in usage
                cached.response.usage.cached = True
                self._tokens_saved += cached.response.usage.tokens_in + cached.response.usage.tokens_out
                logger.info(
                    "cache_hit",
                    cache_key=cache_key[:8],
                    tokens_saved=cached.response.usage.tokens_in + cached.response.usage.tokens_out,
                )
                return cached.response
            self._cache_misses += 1

        # Step 3: call underlying provider
        response = await self.provider.complete(
            messages,
            model=effective_model,
            tools=tools,
            response_schema=response_schema,
            **kwargs,
        )

        # Step 4: store in cache
        if self.enable_cache and response.content:
            self._cache[cache_key] = CacheEntry(
                input_hash=cache_key,
                response=response,
                created_at=__import__("time").time(),
            )
            self._evict_if_needed()

        return response

    # ============================================================
    # Routing
    # ============================================================

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
        kwargs: dict[str, Any],
    ) -> str:
        """Stable hash of inputs for cache key."""
        payload = json.dumps(
            {
                "messages": [m.model_dump() for m in messages],
                "model": model,
                "tools": tools,
                "kwargs": {k: v for k, v in kwargs.items() if k != "temperature"},
            },
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _is_fresh(self, entry: CacheEntry) -> bool:
        import time

        return (time.time() - entry.created_at) < self.cache_ttl_s

    def _evict_if_needed(self) -> None:
        """LRU eviction when cache is full."""
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
        """Return optimization stats for observability."""
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
        self._cache_hits = 0
        self._cache_misses = 0
        self._routing_decisions = 0
        self._tokens_saved = 0
