"""Google Gemini vision adapter. Default model: gemini-1.5-pro.

Uses the google-generativeai SDK with inline image data and JSON output.
"""

from __future__ import annotations

import base64
from typing import List, Tuple

from .base import ImageBlock, LLMClient, ModelConfig


class GeminiClient(LLMClient):
    def __init__(self, config: ModelConfig, concurrency: int = 5):
        super().__init__(config, concurrency=concurrency)
        import os

        import google.generativeai as genai  # lazy import

        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self._genai = genai
        self._model_name = config.model

    async def _raw_complete(
        self, system: str, text: str, images: List[ImageBlock], max_tokens: int
    ) -> Tuple[str, int, int]:
        model = self._genai.GenerativeModel(
            model_name=self._model_name, system_instruction=system
        )
        parts: list = [text]
        for b64, media in images:
            parts.append({"mime_type": media, "data": base64.b64decode(b64)})

        resp = await model.generate_content_async(
            parts,
            generation_config={
                "temperature": 0,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
            },
        )
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tok = getattr(usage, "candidates_token_count", 0) if usage else 0
        return resp.text, in_tok, out_tok
