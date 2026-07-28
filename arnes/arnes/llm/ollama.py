"""Ollama provider — local-first, default."""

from __future__ import annotations

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

        content = data.get("message", {}).get("content", "")
        eval_count = data.get("eval_count", 0)
        prompt_eval_count = data.get("prompt_eval_count", 0)

        return LLMResponse(
            content=content,
            tool_calls=[],  # Ollama tool use is evolving — fall back to text parsing
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
