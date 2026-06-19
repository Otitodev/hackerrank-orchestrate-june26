"""Provider-agnostic LLM client interface.

The pipeline depends only on :class:`LLMClient` and never imports a vendor SDK
directly. Concrete adapters (Anthropic / OpenAI / Gemini / mock) live in sibling
modules and import their SDK lazily, so a missing SDK never breaks the others.

Images are passed in a vendor-neutral form: a list of ``(base64_data,
media_type)`` tuples produced by ``utils.image_loader.encode_image``. Each
adapter translates that into its provider's wire format.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

ImageBlock = Tuple[str, str]  # (base64_data, media_type)


@dataclass
class ModelConfig:
    """Provider + model identity and pricing (for the operational report)."""

    provider: str
    model: str
    max_tokens: int = 700
    # USD per 1M tokens; 0 for the mock.
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0


@dataclass
class Usage:
    """Running token/call totals, used by the evaluation report."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    images: int = 0

    def add(self, in_tok: int, out_tok: int, images: int = 0) -> None:
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.calls += 1
        self.images += images

    def cost(self, config: ModelConfig) -> float:
        return (
            self.input_tokens / 1_000_000 * config.input_cost_per_mtok
            + self.output_tokens / 1_000_000 * config.output_cost_per_mtok
        )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Best-effort extraction of the first JSON object from a model reply."""
    if not text:
        raise ValueError("empty model response")
    candidate = text.strip()
    fence = _FENCE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(candidate[start : end + 1])
    raise ValueError(f"no JSON object found in response: {candidate[:200]!r}")


# Models that reject sampling parameters (temperature/top_p/top_k).
_NO_SAMPLING = ("opus-4-6", "opus-4-7", "opus-4-8", "fable", "mythos")


def supports_sampling(model: str) -> bool:
    m = model.lower()
    return not any(tag in m for tag in _NO_SAMPLING)


class LLMClient(ABC):
    """Abstract vision-capable JSON client.

    Subclasses implement :meth:`_raw_complete`; the base handles concurrency
    capping, retries with exponential backoff, JSON extraction, and usage
    accounting. ``purpose`` is a hint used only by the mock client.
    """

    def __init__(self, config: ModelConfig, concurrency: int = 5, max_retries: int = 3):
        self.config = config
        self.usage = Usage()
        self._sem = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries

    async def complete_json(
        self,
        system: str,
        text: str,
        images: Optional[List[ImageBlock]] = None,
        max_tokens: Optional[int] = None,
        purpose: Optional[str] = None,
    ) -> dict:
        images = images or []
        max_tokens = max_tokens or self.config.max_tokens
        delay = 1.0
        last_exc: Optional[Exception] = None
        async with self._sem:
            for attempt in range(self._max_retries):
                try:
                    raw, in_tok, out_tok = await self._raw_complete(
                        system, text, images, max_tokens
                    )
                    self.usage.add(in_tok, out_tok, images=len(images))
                    return extract_json(raw)
                except Exception as exc:  # noqa: BLE001 - retry any transient failure
                    last_exc = exc
                    if attempt == self._max_retries - 1:
                        break
                    await asyncio.sleep(delay + random.uniform(0, 0.5))
                    delay *= 2
        raise RuntimeError(f"{self.config.provider} call failed after retries: {last_exc}")

    @abstractmethod
    async def _raw_complete(
        self, system: str, text: str, images: List[ImageBlock], max_tokens: int
    ) -> Tuple[str, int, int]:
        """Return ``(response_text, input_tokens, output_tokens)``."""
        raise NotImplementedError
