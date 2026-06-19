"""Deterministic offline mock client.

Returns schema-valid JSON via lightweight keyword heuristics so the full
pipeline and the evaluation harness run end-to-end without any API key. It does
NOT attempt to be accurate — it only guarantees structurally valid responses,
which is enough to exercise wiring and tests.
"""

from __future__ import annotations

from typing import List, Optional

from .base import ImageBlock, LLMClient, ModelConfig

# keyword -> (issue_type, generic part hint)
_ISSUE_KEYWORDS = {
    "dent": "dent",
    "scratch": "scratch",
    "crack": "crack",
    "shatter": "glass_shatter",
    "broken": "broken_part",
    "missing": "missing_part",
    "torn": "torn_packaging",
    "crush": "crushed_packaging",
    "water": "water_damage",
    "stain": "stain",
}

_PART_KEYWORDS = {
    "bumper": "front_bumper",
    "rear bumper": "rear_bumper",
    "front bumper": "front_bumper",
    "door": "door",
    "hood": "hood",
    "windshield": "windshield",
    "mirror": "side_mirror",
    "headlight": "headlight",
    "taillight": "taillight",
    "screen": "screen",
    "display": "screen",
    "keyboard": "keyboard",
    "trackpad": "trackpad",
    "hinge": "hinge",
    "lid": "lid",
    "corner": "corner",
    "box": "box",
    "seal": "seal",
    "label": "label",
    "contents": "contents",
}


def _first_keyword(text: str, table: dict) -> Optional[str]:
    low = text.lower()
    for key, value in table.items():
        if key in low:
            return value
    return None


class MockClient(LLMClient):
    """Heuristic stand-in. Overrides ``complete_json`` directly (no network)."""

    def __init__(self, config: ModelConfig | None = None, concurrency: int = 5):
        super().__init__(config or ModelConfig("mock", "mock"), concurrency=concurrency)

    async def _raw_complete(self, system, text, images, max_tokens):  # pragma: no cover
        # Unused: complete_json is overridden. Kept to satisfy the ABC.
        return "{}", 0, 0

    async def complete_json(
        self,
        system: str,
        text: str,
        images: Optional[List[ImageBlock]] = None,
        max_tokens: Optional[int] = None,
        purpose: Optional[str] = None,
    ) -> dict:
        self.usage.add(120, 60, images=len(images or []))
        issue = _first_keyword(text, _ISSUE_KEYWORDS)
        part = _first_keyword(text, _PART_KEYWORDS)

        if purpose == "parse":
            return {
                "claimed_damage": text.strip()[:120] or None,
                "claimed_part": part,
                "issue_family": issue or "unknown",
            }

        if purpose == "image":
            return {
                "detected_object": _detect_object(text),
                "visible_parts": [part] if part else [],
                "damage_observed": [issue] if issue else [],
                "quality_score": 4,
                "low_light_or_glare": False,
                "wrong_angle": False,
                "cropped_or_obstructed": False,
                "authenticity_suspicion": False,
                "non_original_suspicion": False,
                "wrong_part_suspicion": False,
                "text_instruction_present": False,
                "verdict": "supports" if issue else "inconclusive",
                "confidence": "medium",
                "reason": "mock: heuristic analysis",
            }

        # purpose == "synthesis"
        return {
            "claim_status": "supported" if issue else "not_enough_information",
            "issue_type": issue or "unknown",
            "object_part": part or "unknown",
            "supporting_image_ids": ["img_1"] if issue else [],
            "severity": "medium" if issue else "unknown",
            "claim_status_justification": "mock: heuristic verdict from claim text.",
        }


def _detect_object(text: str) -> str:
    low = text.lower()
    for obj in ("car", "laptop", "package"):
        if obj in low:
            return obj
    return "unknown"
