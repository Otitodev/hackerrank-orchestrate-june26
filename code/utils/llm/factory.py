"""Factory that selects a vision-LLM provider by config or auto-detection.

Selection order: explicit arg -> ``LLM_PROVIDER`` env -> first provider whose
API key is present -> ``mock``. ``LLM_MODEL`` overrides the per-provider default.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMClient, ModelConfig

# Per-provider default model + pricing (USD per 1M tokens).
# Anthropic pricing is authoritative (claude-api skill); OpenAI/Gemini are
# documented assumptions for the cost report — see evaluation_report.md.
_DEFAULTS = {
    "anthropic": ModelConfig("anthropic", "claude-sonnet-4-6", 700, 3.00, 15.00),
    "openai": ModelConfig("openai", "gpt-4o", 700, 2.50, 10.00),
    "gemini": ModelConfig("gemini", "gemini-1.5-pro", 700, 1.25, 5.00),
    "mock": ModelConfig("mock", "mock", 700, 0.0, 0.0),
}

_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


def _autodetect() -> str:
    for provider, env in _KEY_ENV.items():
        if os.getenv(env):
            return provider
    return "mock"


def make_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    concurrency: int = 5,
) -> LLMClient:
    provider = (provider or os.getenv("LLM_PROVIDER") or _autodetect()).lower()
    if provider not in _DEFAULTS:
        raise ValueError(
            f"unknown provider {provider!r}; choose anthropic|openai|gemini|mock"
        )

    config = ModelConfig(**vars(_DEFAULTS[provider]))
    if model or os.getenv("LLM_MODEL"):
        config.model = model or os.getenv("LLM_MODEL")

    if provider == "mock":
        from .mock_client import MockClient

        return MockClient(config, concurrency=concurrency)
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(config, concurrency=concurrency)
    if provider == "openai":
        from .openai_client import OpenAIClient

        return OpenAIClient(config, concurrency=concurrency)
    if provider == "gemini":
        from .gemini_client import GeminiClient

        return GeminiClient(config, concurrency=concurrency)
    raise AssertionError("unreachable")
