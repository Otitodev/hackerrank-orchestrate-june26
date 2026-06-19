"""Anthropic (Claude) vision adapter. Default model: claude-sonnet-4-6."""

from __future__ import annotations

from typing import List, Tuple

from .base import ImageBlock, LLMClient, ModelConfig, supports_sampling


class AnthropicClient(LLMClient):
    def __init__(self, config: ModelConfig, concurrency: int = 5):
        super().__init__(config, concurrency=concurrency)
        from anthropic import AsyncAnthropic  # lazy import

        self._client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env

    async def _raw_complete(
        self, system: str, text: str, images: List[ImageBlock], max_tokens: int
    ) -> Tuple[str, int, int]:
        content: list = []
        for b64, media in images:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media, "data": b64},
                }
            )
        content.append({"type": "text", "text": text})

        kwargs = dict(
            model=self.config.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        if supports_sampling(self.config.model):
            kwargs["temperature"] = 0  # deterministic extraction

        resp = await self._client.messages.create(**kwargs)
        out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return out, resp.usage.input_tokens, resp.usage.output_tokens
