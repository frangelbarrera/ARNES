"""
ARNES Harness — high-level wrapper for simple use cases.

Hello world:
    from arnes import Harness
    harness = Harness(model="ollama/llama3.2")
    result = await harness.run("@planner", {"task": "Plan a blog post about ARNES"})
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from arnes.llm.factory import get_provider
from arnes.middleware import BudgetExceeded, build_middleware_stack
from arnes.specialists.base import (
    SpecialistRegistry,
    _drain_event_to_sink,
    get_default_specialist_registry,
)
from arnes.thread import Thread
from arnes.thread.events import AssistantMessageEvent
from arnes.tools.base import ToolContext, ToolRegistry
from arnes.tools.registry import get_default_registry

logger = structlog.get_logger(__name__)


class HarnessConfig(BaseModel):
    """Configuration for a Harness."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "ollama/llama3.2"
    budget_usd: float = 0.50
    enable_cache: bool = True
    enable_verification: bool = True
    interactive: bool = False


class Harness:
    """High-level harness — wraps provider + middleware + specialist registry.

    The Harness wraps the provider ONCE with the full middleware stack
    (CostGuard → VerificationLayer → TokenOptimizer → provider). The wrapped
    provider is passed to the specialist, which does NOT re-wrap.

    For simple use cases:
        harness = Harness()
        result = await harness.run("@planner", {"task": "..."})

    For complex workflows, use PlaybookExecutor directly.
    """

    def __init__(
        self,
        config: HarnessConfig | None = None,
        *,
        provider: LLMProvider | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.provider = provider or get_provider(self.config.model)
        self.specialist_registry = specialist_registry or get_default_specialist_registry()
        self.tool_registry = tool_registry or get_default_registry()

    async def run(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a specialist with input data. Returns the result dict."""
        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            available = self.specialist_registry.list_names()
            return {
                "success": False,
                "error": f"Specialist '{specialist}' not found. Available: {available}",
            }

        # Wrap provider with middleware ONCE (order matters: cost outermost).
        # The specialist's structured-output contract gates whether the
        # VerificationLayer is added — see ``build_middleware_stack``.
        wrapped_provider = build_middleware_stack(
            self.provider,
            enable_cache=self.config.enable_cache,
            enable_verification=self.config.enable_verification,
            budget_usd=self.config.budget_usd,
            output_schema=specialist_obj.config.output_schema,
            pydantic_model=specialist_obj.config.pydantic_model,
        )

        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist=specialist,
            metadata={"interactive": self.config.interactive},
        )

        try:
            result = await specialist_obj.run(
                input_data,
                ctx,
                provider=wrapped_provider,
                tool_registry=self.tool_registry,
            )
            return result
        except BudgetExceeded as e:
            # Budget exceeded is a known, expected exception — return structured result
            logger.warning("harness_budget_exceeded", specialist=specialist, error=str(e))
            return {
                "success": False,
                "error": f"Budget exceeded: {e}",
                "specialist": specialist,
                "budget_exceeded": True,
            }
        except Exception as e:
            # Unexpected exceptions — log with full traceback for debugging
            logger.exception("harness_run_failed", specialist=specialist, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "specialist": specialist,
                "error_type": type(e).__name__,
            }

    async def stream(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ) -> AsyncIterator[LLMResponse]:
        """Stream a specialist's response token by token.

        Yields ``LLMResponse`` chunks as they arrive from the provider.
        The final chunk contains the full usage stats.

        Audit trail (FIX-R9-DATA): after the stream completes, a single
        :class:`AssistantMessageEvent` carrying the full accumulated
        content + final usage is appended to the wrapped provider's
        ``_events`` sink. Streaming therefore no longer bypasses the
        bitácora — the audit log records streaming runs the same way
        it records non-streaming runs.

        Streaming produces ONE ``AssistantMessageEvent`` per call (not
        per-chunk events). Per-chunk events would balloon the audit log
        without adding forensic value: chunks are a transport
        optimisation, not a semantic unit. The single event captures
        the complete assistant turn (content + tokens + cost) exactly
        as :meth:`run` does.

        Usage::

            async for chunk in harness.stream("@coder", {"spec": "..."}):
                print(chunk.content, end="", flush=True)

        To get both the chunks AND a ``Thread`` with the audit trail,
        use :meth:`stream_with_audit` instead.
        """

        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            return

        # Build messages (same as specialist.run but without tool-use loop)
        user_content = json.dumps(input_data, indent=2, default=str)
        messages = [
            LLMMessage(role="system", content=specialist_obj.config.system_prompt),
            LLMMessage(
                role="user",
                content=f"Input:\n```json\n{user_content}\n```\n\nReturn JSON matching the schema.",
            ),
        ]

        model = specialist_obj.config.default_model or "ollama/llama3.2"

        # Wrap provider with middleware (same stack as run()).
        wrapped_provider = build_middleware_stack(
            self.provider,
            enable_cache=self.config.enable_cache,
            enable_verification=self.config.enable_verification,
            budget_usd=self.config.budget_usd,
            output_schema=specialist_obj.config.output_schema,
            pydantic_model=specialist_obj.config.pydantic_model,
        )

        # Track the thread_id / step_id for the AssistantMessageEvent.
        # The Harness does not maintain a long-lived Thread (each run()
        # call creates a fresh one), but we still need stable ids so the
        # event can be appended to the sink and later drained by a
        # caller that consumes ``wrapped_provider._events``.
        thread = Thread.create()
        ctx = ToolContext(
            thread_id=thread.id,
            specialist=specialist,
            metadata={"interactive": self.config.interactive},
        )

        # Accumulate content + usage so we can emit a single
        # AssistantMessageEvent after the stream ends. Per-chunk usage is
        # zero on intermediate chunks (see LLMProvider.stream_complete
        # contract); the final chunk carries the full usage.
        accumulated_content: list[str] = []
        total_usage = LLMUsage()

        # Stream from the provider
        async for chunk in wrapped_provider.stream_complete(
            messages,
            model=model,
            temperature=specialist_obj.config.temperature,
            max_tokens=specialist_obj.config.max_tokens,
            response_format={"type": "json_object"}
            if specialist_obj.config.output_schema
            else None,
            response_schema=specialist_obj.config.output_schema,
        ):
            if chunk.content:
                accumulated_content.append(chunk.content)
            # The last non-zero usage wins (providers send the full count
            # on the final chunk, not a running delta).
            if chunk.usage.tokens_in > 0 or chunk.usage.tokens_out > 0 or chunk.usage.cost_usd > 0:
                total_usage = chunk.usage
            yield chunk

        # Emit a single AssistantMessageEvent to the wrapped provider's
        # shared ``_events`` sink (same pattern as the middleware event
        # sink drained by the PlaybookExecutor). The event carries the
        # full accumulated content + final usage so the audit trail
        # records the streaming run as a complete assistant turn.
        self._emit_stream_audit_event(
            wrapped_provider,
            ctx,
            "".join(accumulated_content),
            total_usage,
            model,
        )

    def stream_with_audit(
        self,
        specialist: str,
        input_data: dict[str, Any],
    ) -> tuple[AsyncIterator[LLMResponse], Thread]:
        """Stream a specialist's response AND return a Thread with the audit trail.

        Returns a ``(chunks, thread)`` tuple:

        - ``chunks`` is an :class:`AsyncIterator[LLMResponse]` — consume
          it with ``async for`` to get the token-by-token stream.
        - ``thread`` is a :class:`Thread` that starts empty and is
          mutated in place as the stream is consumed. After the stream
          completes, the thread contains a single
          :class:`AssistantMessageEvent` with the full accumulated
          content + final usage.

        The thread is the same append-only event log used everywhere
        else in ARNES, so ``thread.to_markdown()`` produces a valid
        bitácora entry for the streaming run.

        Usage::

            chunks, thread = harness.stream_with_audit("@planner", {"task": "..."})
            async for chunk in chunks:
                print(chunk.content, end="", flush=True)
            # After iteration, thread has the AssistantMessageEvent.
            print(thread.to_markdown())

        Note: the thread is mutated as a side-effect of consuming the
        chunks iterator. If you don't iterate, no event is appended.
        """
        thread = Thread.create()
        chunks = self._stream_into_thread(specialist, input_data, thread)
        return chunks, thread

    async def _stream_into_thread(
        self,
        specialist: str,
        input_data: dict[str, Any],
        thread: Thread,
    ) -> AsyncIterator[LLMResponse]:
        """Stream a specialist's response, emitting the audit event into ``thread``.

        Internal helper for :meth:`stream_with_audit`. Mirrors
        :meth:`stream` but emits the ``AssistantMessageEvent`` directly
        into the provided ``thread`` (instead of the wrapped provider's
        ``_events`` sink), so the caller can inspect the thread after
        the stream completes.
        """
        if not specialist.startswith("@"):
            specialist = "@" + specialist

        specialist_obj = self.specialist_registry.get(specialist)
        if not specialist_obj:
            return

        user_content = json.dumps(input_data, indent=2, default=str)
        messages = [
            LLMMessage(role="system", content=specialist_obj.config.system_prompt),
            LLMMessage(
                role="user",
                content=f"Input:\n```json\n{user_content}\n```\n\nReturn JSON matching the schema.",
            ),
        ]

        model = specialist_obj.config.default_model or "ollama/llama3.2"

        wrapped_provider = build_middleware_stack(
            self.provider,
            enable_cache=self.config.enable_cache,
            enable_verification=self.config.enable_verification,
            budget_usd=self.config.budget_usd,
            output_schema=specialist_obj.config.output_schema,
            pydantic_model=specialist_obj.config.pydantic_model,
        )

        accumulated_content: list[str] = []
        total_usage = LLMUsage()

        async for chunk in wrapped_provider.stream_complete(
            messages,
            model=model,
            temperature=specialist_obj.config.temperature,
            max_tokens=specialist_obj.config.max_tokens,
            response_format={"type": "json_object"}
            if specialist_obj.config.output_schema
            else None,
            response_schema=specialist_obj.config.output_schema,
        ):
            if chunk.content:
                accumulated_content.append(chunk.content)
            if chunk.usage.tokens_in > 0 or chunk.usage.tokens_out > 0 or chunk.usage.cost_usd > 0:
                total_usage = chunk.usage
            yield chunk

        # Append the AssistantMessageEvent directly to the provided thread.
        # ``Thread.append`` validates that event.thread_id == thread.id,
        # so we must construct the event with the thread's id (not a nil
        # placeholder).
        event = AssistantMessageEvent(
            thread_id=thread.id,
            specialist=specialist,
            data={
                "content": "".join(accumulated_content),
                "model": total_usage.model or model,
                "tokens_in": total_usage.tokens_in,
                "tokens_out": total_usage.tokens_out,
                "cost_usd": total_usage.cost_usd,
                "cached": total_usage.cached,
                "streamed": True,
            },
        )
        thread.append(event)

    def _emit_stream_audit_event(
        self,
        wrapped_provider: LLMProvider,
        ctx: ToolContext,
        content: str,
        usage: LLMUsage,
        model: str,
    ) -> None:
        """Emit an ``AssistantMessageEvent`` for a streaming run to the ``_events`` sink.

        Same sink pattern as :meth:`arnes.specialists.base.Specialist._emit_assistant_message`:
        the event is appended to the wrapped provider's shared ``_events``
        list (set up by ``CostGuard``), so callers that drain the sink
        (e.g. ``PlaybookExecutor._drain_middleware_events``) pick it up
        automatically.

        Delegates to the shared module-level :func:`_drain_event_to_sink`
        helper so the "get list / type-guard / append" defensive pattern is
        not duplicated between :class:`Harness` and :class:`Specialist`.

        If ``wrapped_provider`` has no ``_events`` attribute (e.g. a raw
        third-party provider), the emission is a no-op — the stream
        itself still works, just without an audit trail.
        """
        event = AssistantMessageEvent(
            thread_id=ctx.thread_id,
            step_id=ctx.step_id,
            specialist=ctx.specialist,
            data={
                "content": content,
                "model": usage.model or model,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "cost_usd": usage.cost_usd,
                "cached": usage.cached,
                "streamed": True,
            },
        )
        _drain_event_to_sink(wrapped_provider, event)
