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
from typing import Any

import structlog
from pydantic import BaseModel, Field

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse

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


class VerificationLayer:
    """Middleware that verifies LLM responses to prevent hallucinations."""

    def __init__(self, provider: LLMProvider, config: VerificationConfig | None = None) -> None:
        self.provider = provider
        self.config = config or VerificationConfig()
        self._refusals_triggered = 0
        self._hedging_detected = 0
        self._validation_failures = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
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
        if self.config.structured_outputs and response_schema:
            effective_kwargs["response_format"] = {"type": "json_object"}

        # Call underlying provider
        response = await self.provider.complete(
            effective_messages,
            model=model,
            **effective_kwargs,
        )

        # Verify response
        verification = self._verify(response, response_schema)

        if not verification.passed:
            self._refusals_triggered += 1
            logger.warning(
                "verification_failed",
                reason="refusal_triggered" if verification.refusal_triggered else "validation_failed",
                errors=verification.validation_errors,
            )
            # Replace response with refusal
            response.content = self.config.refusal_message
            response.usage.cached = False  # Don't cache refusals

        return response

    # ============================================================
    # Verification logic
    # ============================================================

    def _verify(
        self,
        response: LLMResponse,
        response_schema: dict[str, Any] | None,
    ) -> VerificationResult:
        """Run all enabled verification checks on a response."""
        result = VerificationResult(passed=True, confidence=0.8)  # default

        # Check 1: hedging detection — if hedging detected, fail verification
        if self.config.detect_hedging:
            hedging = self._detect_hedging(response.content)
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
        """Detect if the response is hedging / refusing."""
        for pattern in _HEDGING_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

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
                content=m.content + "\n\n" + refusal_prompt.content if m.role == "system" else m.content,
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
