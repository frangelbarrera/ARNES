"""
ARNES LLM provider factory.

Resolves a model string like "ollama/llama3.2" or "anthropic/claude-sonnet-4-20250514"
to the correct provider. Defaults to ollama for local-first ethos.
"""

from __future__ import annotations

import os
from typing import Any

from arnes.llm.base import LLMProvider
from arnes.llm.mock import MockLLMProvider


# Default model if user doesn't specify (vendor-neutral, local-first)
DEFAULT_MODEL = "ollama/llama3.2"


def get_provider(model: str = DEFAULT_MODEL, **kwargs: Any) -> LLMProvider:
    """Return the right LLMProvider for a model string.

    Format: "vendor/model-name"
    Examples:
        "ollama/llama3.2"       → OllamaProvider (local, default)
        "anthropic/claude-..."  → AnthropicProvider
        "openai/gpt-4o"         → OpenAIProvider
        "mock/anything"         → MockLLMProvider (for tests)
    """
    vendor = model.split("/")[0].lower() if "/" in model else "ollama"

    # Allow override via env for tests / dev
    if os.getenv("ARNES_MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return MockLLMProvider()

    if vendor == "mock":
        return MockLLMProvider(**kwargs)

    if vendor == "ollama":
        from arnes.llm.ollama import OllamaProvider

        return OllamaProvider(**kwargs)

    if vendor in ("anthropic", "openai", "google", "groq", "mistral", "cohere", "azure"):
        # Use LiteLLM as the universal adapter for paid providers
        from arnes.llm.litellm_provider import LiteLLMProvider

        return LiteLLMProvider(**kwargs)

    raise ValueError(f"Unknown LLM vendor: {vendor}. Use 'ollama/...', 'anthropic/...', 'openai/...', 'mock/...'")
