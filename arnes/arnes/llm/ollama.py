"""Ollama provider — local-first, default."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from arnes.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


class OllamaProvider(LLMProvider):
    """Local Ollama provider. Requires `ollama serve` running on localhost:11434.

    Cost: $0 (local inference). Default for ARNES quickstart.
    """

    def __init__(self, host: str = "http://localhost:11434", timeout: float = 120.0) -> None:
        self.host = host
        self.timeout = timeout

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str = "llama3.2",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        response_schema: dict[str, Any] | None = None,  # Accepted but ignored
        **kwargs: Any,
    ) -> LLMResponse:
        import httpx

        # Strip vendor prefix if present
        if "/" in model:
            model = model.split("/", 1)[1]

        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"
        # Pass tools through — Ollama supports tool calling since v0.3.0.
        # Silently dropping the parameter here would mean any specialist that
        # relies on the ReAct loop never sees a tool_call back from the model.
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.host}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.host}. "
                "Install with: curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2"
            ) from e

        message = data.get("message", {}) or {}
        content = message.get("content", "") or ""
        eval_count = data.get("eval_count", 0)
        prompt_eval_count = data.get("prompt_eval_count", 0)

        # Parse tool_calls from the Ollama response (v0.3.0+). Older versions
        # or non-tool-aware models won't return this field — fall back to an
        # empty list rather than hardcoding [] so callers can distinguish
        # "model returned no tool calls" from "provider didn't look".
        tool_calls: list[dict[str, Any]] = []
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            for tc in raw_tool_calls:
                if not isinstance(tc, dict):
                    continue
                function = tc.get("function") or {}
                # Ollama returns {"function": {"name": ..., "arguments": {...}}}.
                # Normalize to the OpenAI shape used everywhere else in ARNES:
                # {"id": ..., "type": "function", "function": {"name": ..., "arguments": "<json-str>"}}
                name = function.get("name")
                if not name:
                    continue
                args = function.get("arguments", {})
                # OpenAI ships arguments as a JSON string; mirror that so the
                # downstream specialist `_execute_tool_call` can json.loads it.
                if isinstance(args, (dict, list)):
                    args = json.dumps(args)
                elif args is None:
                    args = "{}"
                tool_calls.append(
                    {
                        "id": tc.get("id") or f"call_{name}",
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    }
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=LLMUsage(
                tokens_in=prompt_eval_count,
                tokens_out=eval_count,
                cost_usd=0.0,  # Local = free
                model=f"ollama/{model}",
                cached=False,
            ),
            model=f"ollama/{model}",
            raw=data,
        )

    def list_models(self) -> list[str]:
        try:
            import httpx

            resp = httpx.get(f"{self.host}/api/tags", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            return [f"ollama/{m['name']}" for m in data.get("models", [])]
        except Exception:
            return ["ollama/llama3.2", "ollama/llama3.1", "ollama/qwen2.5", "ollama/mistral"]

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
        """Streaming coming in v0.2.

        Ollama supports streaming via ``/api/chat`` with ``"stream": true``,
        but the ARNES streaming middleware (AG-UI compatible, with token-
        by-token emission, structured-output validation on the final chunk,
        and CostGuard accounting across partial ``usage`` deltas) lands in
        v0.2. Until then, calling this method and iterating the result
        raises immediately so callers fail fast instead of silently
        receiving a buffered response masquerading as a stream.
        """
        raise NotImplementedError("Streaming coming in v0.2")
        yield  # type: ignore[unreachable]  # pragma: no cover - makes this an async generator
