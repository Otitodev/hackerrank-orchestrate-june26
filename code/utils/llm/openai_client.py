"""OpenAI vision adapter. Default model: gpt-4o.

Uses Chat Completions with data-URI image blocks and JSON response format.
"""

from __future__ import annotations

from typing import List, Tuple

from .base import ImageBlock, LLMClient, ModelConfig


class OpenAIClient(LLMClient):
    def __init__(self, config: ModelConfig, concurrency: int = 5):
        super().__init__(config, concurrency=concurrency)
        from openai import AsyncOpenAI  # lazy import

        self._client = AsyncOpenAI()  # reads OPENAI_API_KEY from env

    async def _raw_complete(
        self, system: str, text: str, images: List[ImageBlock], max_tokens: int
    ) -> Tuple[str, int, int]:
        content: list = [{"type": "text", "text": text}]
        for b64, media in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media};base64,{b64}"},
                }
            )
        resp = await self._client.chat.completions.create(
            model=self.config.model,
            max_tokens=max_tokens,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
        out = resp.choices[0].message.content or ""
        usage = resp.usage
        return out, usage.prompt_tokens, usage.completion_tokens
