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
        response_schema: dict[str, Any] | None = None,  # Accepted but ignored
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Stream a completion as an async iterator of ``LLMResponse`` chunks.

        Uses Ollama's ``/api/chat`` endpoint with ``"stream": true``. The
        response is NDJSON: one JSON object per line, each shaped like
        ``{"message": {"content": "token"}, "done": false}``. The final
        chunk has ``"done": true`` and carries the full usage stats
        (``prompt_eval_count``, ``eval_count``).

        Contract:

        - Each non-final chunk yields an ``LLMResponse`` whose ``content``
          is *just the new token* (not the accumulated content). Callers
          that need the full text accumulate themselves.
        - Intermediate chunks carry an empty ``LLMUsage`` (zeros) — token
          counts are only known once generation completes.
        - The final chunk (yielded after the ``done: true`` line) carries
          the full ``LLMUsage`` with ``tokens_in`` / ``tokens_out``.
        - Connection errors are wrapped in a ``RuntimeError`` with install
          instructions, matching :meth:`complete`.
        """
        import httpx

        # Strip vendor prefix if present (mirrors complete())
        effective_model = model.split("/", 1)[1] if "/" in model else model

        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"
        if tools:
            payload["tools"] = tools

        full_model = f"ollama/{effective_model}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.host}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    final_usage_yielded = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            # Skip malformed lines rather than aborting the
                            # stream mid-generation — a single bad line from
                            # the model should not discard the tokens already
                            # received.
                            continue
                        if not isinstance(chunk, dict):
                            continue

                        message = chunk.get("message") or {}
                        content = message.get("content") or ""
                        done = bool(chunk.get("done", False))

                        if done:
                            # Final chunk: Ollama only sends prompt_eval_count
                            # / eval_count on the done=true line. If this
                            # chunk also carries a trailing content token
                            # (rare but possible), yield it before the usage-
                            # only final chunk so no tokens are lost.
                            if content:
                                yield LLMResponse(
                                    content=content,
                                    tool_calls=[],
                                    usage=LLMUsage(
                                        tokens_in=0,
                                        tokens_out=0,
                                        cost_usd=0.0,
                                        model=full_model,
                                        cached=False,
                                    ),
                                    model=full_model,
                                )
                            final_usage_yielded = True
                            yield LLMResponse(
                                content="",
                                tool_calls=[],
                                usage=LLMUsage(
                                    tokens_in=chunk.get("prompt_eval_count", 0),
                                    tokens_out=chunk.get("eval_count", 0),
                                    cost_usd=0.0,  # Local = free
                                    model=full_model,
                                    cached=False,
                                ),
                                model=full_model,
                                raw=chunk,
                            )
                            return

                        # Regular token chunk
                        yield LLMResponse(
                            content=content,
                            tool_calls=[],
                            usage=LLMUsage(
                                tokens_in=0,
                                tokens_out=0,
                                cost_usd=0.0,
                                model=full_model,
                                cached=False,
                            ),
                            model=full_model,
                        )

                    # Stream ended without a ``done: true`` line (network
                    # interruption, server crash). Yield a sentinel final
                    # chunk with zeroed usage so callers that block on the
                    # final chunk to read usage don't hang — they'll see
                    # zeros and can detect the anomaly.
                    if not final_usage_yielded:
                        yield LLMResponse(
                            content="",
                            tool_calls=[],
                            usage=LLMUsage(
                                tokens_in=0,
                                tokens_out=0,
                                cost_usd=0.0,
                                model=full_model,
                                cached=False,
                            ),
                            model=full_model,
                        )
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.host}. "
                "Install with: curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2"
            ) from e
