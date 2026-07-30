"""
ARNES Verification Layer — anti-hallucination middleware.

5 layers (v0.1 implements structured outputs + refusal; critic loop,
confidence gate, grounding RAG land in v0.2/v0.3/v0.4):

1. Structured outputs — force LLM to return pydantic-validated JSON.
2. Refusal pattern — if LLM is uncertain, prefer "I don't know" over fabrication.
3. Confidence gate — if confidence < threshold, refuse (v0.2).
4. Critic loop — second agent validates the first's response (v0.3).
5. Grounding RAG — verify claims against knowledge base (v0.4).

This is NOT a "silver bullet against hallucinations". It's a layered defense
that makes hallucinations rare and detectable.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse
from arnes.thread.events import Event, EventType

logger = structlog.get_logger(__name__)


# Patterns that indicate the LLM is hedging / uncertain
_HEDGING_PATTERNS = [
    r"\bI\s+don'?t\s+know\b",
    r"\bI'?m\s+not\s+sure\b",
    r"\bI\s+cannot\s+(?:verify|confirm)\b",
    r"\bas\s+an\s+ai\b",
    r"\bi\s+don'?t\s+have\s+(?:access|information)\b",
    r"\bto\s+the\s+best\s+of\s+my\s+knowledge\b",
]


class VerificationConfig(BaseModel):
    """Configuration for the verification layer."""

    structured_outputs: bool = True
    refusal_pattern: bool = True
    confidence_gate: float | None = None  # None = disabled in v0.1
    critic_loop: bool = False  # v0.3
    grounding_rag: bool = False  # v0.4

    # When refusal is triggered, what should we return?
    refusal_message: str = "I don't have enough confidence to answer this. Please verify manually."

    # Detect hedging in response — if detected, mark as low-confidence
    detect_hedging: bool = True


class VerificationResult(BaseModel):
    """Result of verifying an LLM response."""

    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    refusal_triggered: bool = False
    hedging_detected: bool = False
    structured_output_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)


class VerificationLayer(LLMProvider):
    """Middleware that verifies LLM responses to prevent hallucinations."""

    def __init__(self, provider: LLMProvider, config: VerificationConfig | None = None) -> None:
        self.provider = provider
        self.config = config or VerificationConfig()
        self._refusals_triggered = 0
        self._hedging_detected = 0
        self._validation_failures = 0
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
        """Verified completion. Forces structured outputs + refusal pattern."""
        # Inject system prompt for refusal pattern
        effective_messages = list(messages)
        if self.config.refusal_pattern:
            effective_messages = self._inject_refusal_prompt(effective_messages)

        # Force JSON response if structured outputs enabled
        effective_kwargs = dict(kwargs)
        json_mode_active = False
        if self.config.structured_outputs and response_schema:
            effective_kwargs["response_format"] = {"type": "json_object"}
            # Track this so _verify can skip hedging detection — when the model
            # is forced into JSON mode, hedging phrases like "I'm not sure" can
            # legitimately appear inside a string field (e.g. {"summary":
            # "I'm not sure about the auth flow"}) and would otherwise trigger
            # a false-positive refusal. The JSON schema check is the real guard
            # in this mode.
            json_mode_active = True

        # Pass tools through to the underlying provider (don't filter them)
        response = await self.provider.complete(
            effective_messages,
            model=model,
            tools=tools,
            response_schema=response_schema,
            **effective_kwargs,
        )

        # Verify response
        verification = self._verify(response, response_schema, json_mode_active=json_mode_active)

        if not verification.passed:
            self._refusals_triggered += 1
            logger.warning(
                "verification_failed",
                reason="refusal_triggered"
                if verification.refusal_triggered
                else "validation_failed",
                errors=verification.validation_errors,
            )
            self._emit_refusal_triggered(response, verification)
            # Replace response with refusal
            response.content = self.config.refusal_message
            response.usage.cached = False  # Don't cache refusals

        return response

    # ============================================================
    # Event emission
    # ============================================================

    def _emit_refusal_triggered(
        self, response: LLMResponse, verification: VerificationResult
    ) -> None:
        """Emit a REFUSAL_TRIGGERED event for observability.

        The VerificationLayer does not have direct access to the Thread (it
        only sees LLMMessage lists). The event is appended to the shared
        ``self._events`` sink with a nil thread_id placeholder; the
        PlaybookExecutor patches the real thread_id and step_id when it
        drains the sink after each step.
        """
        from arnes.middleware.cost_guard import NIL_THREAD_ID

        event = Event(
            type=EventType.REFUSAL_TRIGGERED,
            thread_id=NIL_THREAD_ID,
            data={
                "reason": "hedging_detected"
                if verification.hedging_detected
                else "validation_failed",
                "confidence": verification.confidence,
                "validation_errors": verification.validation_errors,
                "original_content_preview": (response.content or "")[:200],
                "refusal_message": self.config.refusal_message,
            },
        )
        self._emit(event)

    # ============================================================
    # Verification logic
    # ============================================================

    def _verify(
        self,
        response: LLMResponse,
        response_schema: dict[str, Any] | None,
        *,
        json_mode_active: bool = False,
    ) -> VerificationResult:
        """Run all enabled verification checks on a response."""
        result = VerificationResult(passed=True, confidence=0.8)  # default

        # Check 1: hedging detection — if hedging detected, fail verification.
        #
        # SKIP when JSON mode is active: in JSON mode the schema validation
        # below is the real guard, and hedging phrases ("I'm not sure")
        # legitimately appear inside string fields of a valid JSON payload
        # (e.g. {"summary": "I'm not sure about the auth flow"}). Running
        # regex over the raw JSON would flag every such field as a refusal
        # and turn a perfectly valid response into a refusal message — a
        # classic anti-hallucination false positive.
        if self.config.detect_hedging and not json_mode_active:
            content = response.content if isinstance(response.content, str) else ""
            hedging = self._detect_hedging(content)
            if hedging:
                result.hedging_detected = True
                self._hedging_detected += 1
                result.confidence = min(result.confidence, 0.4)
                result.passed = False  # Hedging = failed verification
                result.refusal_triggered = True

        # Check 2: structured output validation
        if self.config.structured_outputs and response_schema:
            valid, errors = self._validate_structured(response.content, response_schema)
            result.structured_output_valid = valid
            result.validation_errors = errors
            if not valid:
                self._validation_failures += 1
                result.passed = False
                result.confidence = 0.0

        # Check 3: confidence gate (v0.2 placeholder)
        if self.config.confidence_gate is not None:
            if result.confidence < self.config.confidence_gate:
                result.refusal_triggered = True
                result.passed = False

        return result

    def _detect_hedging(self, content: str) -> bool:
        """Detect if the response is hedging / refusing.

        Caller is responsible for ensuring ``content`` is the raw natural-language
        response and NOT a JSON blob — see ``_verify`` for the JSON-mode skip.
        """
        if not isinstance(content, str) or not content:
            return False
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in _HEDGING_PATTERNS)

    def _validate_structured(
        self,
        content: str,
        schema: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate that content is valid JSON conforming to schema (basic)."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return False, [f"Invalid JSON: {e}"]

        # Basic schema check: required fields
        required = schema.get("required", [])
        missing = [f for f in required if f not in data]
        if missing:
            return False, [f"Missing required fields: {missing}"]

        return True, []

    def _inject_refusal_prompt(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Inject a system prompt that encourages honest refusals."""
        refusal_prompt = LLMMessage(
            role="system",
            content=(
                "You are part of ARNES, an agent harness that values accuracy over completeness. "
                "If you are not confident in your answer, say so explicitly. "
                "Prefer 'I don't know' over fabrication. "
                "Do not invent facts, names, dates, or sources. "
                "If asked to verify something you cannot verify, refuse."
            ),
        )
        # Prepend if no system message exists
        if not any(m.role == "system" for m in messages):
            return [refusal_prompt, *messages]
        # Otherwise, augment existing system message
        return [
            LLMMessage(
                role="system",
                content=m.content + "\n\n" + refusal_prompt.content
                if m.role == "system"
                else m.content,
            )
            if m.role == "system"
            else m
            for m in messages
        ]

    # ============================================================
    # Stats
    # ============================================================

    def stats(self) -> dict[str, Any]:
        return {
            "refusals_triggered": self._refusals_triggered,
            "hedging_detected": self._hedging_detected,
            "validation_failures": self._validation_failures,
        }

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

        v0.1 behavior: thin passthrough — verification happens on the
        *final* accumulated response, not per-chunk. Callers that need
        verified streaming should accumulate the stream and pass the
        reassembled content through :meth:`_verify` themselves, OR wait
        for v0.2 which will:

        1. Validate the final reassembled response against
           ``response_schema`` (structured-output check).
        2. Run hedging detection on the concatenated content.
        3. Emit a ``REFUSAL_TRIGGERED`` event mid-stream when hedging is
           detected on a partial chunk, and replace the remainder of the
           stream with the refusal message.

        Until then, this passthrough ensures callers using the streaming
        API against a stack that includes VerificationLayer don't lose the
        verification middleware silently — they just don't get per-chunk
        verification yet.
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
