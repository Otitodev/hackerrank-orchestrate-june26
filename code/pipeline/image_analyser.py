"""Step 5.2 — Image Analyser.

Primary strategy ``single``: one structured VLM call per image returning the
merged observation + verdict. ``two_pass`` (blind -> targeted) is kept only for
the evaluation comparison. Missing/unreadable images get a synthetic result.
"""

from __future__ import annotations

from models.schemas import ImageAnalysis, StructuredClaim
from utils.image_loader import ResolvedImage, encode_image
from utils.llm import LLMClient

from . import load_prompt

_VERDICTS = {"supports", "contradicts", "inconclusive"}


def _synthetic_missing(image_id: str, reason: str) -> ImageAnalysis:
    return ImageAnalysis(
        image_id=image_id, quality_score=0, verdict="inconclusive", reason=reason
    )


def _to_analysis(image_id: str, data: dict) -> ImageAnalysis:
    try:
        quality = int(data.get("quality_score", 0))
    except (TypeError, ValueError):
        quality = 0
    quality = max(0, min(5, quality))
    verdict = str(data.get("verdict", "inconclusive")).lower()
    if verdict not in _VERDICTS:
        verdict = "inconclusive"
    return ImageAnalysis(
        image_id=image_id,
        detected_object=(data.get("detected_object") or None),
        visible_parts=list(data.get("visible_parts") or []),
        damage_observed=list(data.get("damage_observed") or []),
        quality_score=quality,
        low_light_or_glare=bool(data.get("low_light_or_glare", False)),
        wrong_angle=bool(data.get("wrong_angle", False)),
        cropped_or_obstructed=bool(data.get("cropped_or_obstructed", False)),
        authenticity_suspicion=bool(data.get("authenticity_suspicion", False)),
        non_original_suspicion=bool(data.get("non_original_suspicion", False)),
        wrong_part_suspicion=bool(data.get("wrong_part_suspicion", False)),
        text_instruction_present=bool(data.get("text_instruction_present", False)),
        verdict=verdict,
        confidence=str(data.get("confidence", "low")),
        reason=str(data.get("reason", "")),
    )


def _claim_line(claim: StructuredClaim) -> str:
    return (
        f"The user claims: {claim.claimed_damage or 'unspecified damage'} "
        f"(object: {claim.claim_object.value}, part: {claim.claimed_part or 'unspecified'})."
    )


async def analyse_image(
    image: ResolvedImage,
    claim: StructuredClaim,
    client: LLMClient,
    mode: str = "single",
) -> ImageAnalysis:
    if not image.exists:
        return _synthetic_missing(image.image_id, "image file not found on disk")
    enc = encode_image(image.abs_path)
    if enc is None:
        return _synthetic_missing(image.image_id, "image could not be read")
    b64, media = enc

    if mode == "two_pass":
        return await _two_pass(image.image_id, claim, client, b64, media)

    system = load_prompt("image_single")
    text = _claim_line(claim) + "\nAnalyse this image and return the required JSON."
    data = await client.complete_json(
        system, text, images=[(b64, media)], purpose="image", max_tokens=600
    )
    return _to_analysis(image.image_id, data)


async def _two_pass(image_id, claim, client, b64, media) -> ImageAnalysis:
    """Comparison strategy: blind observation, then targeted judgment."""
    blind = await client.complete_json(
        load_prompt("image_blind"),
        "Describe this image and return the required JSON.",
        images=[(b64, media)],
        purpose="image",
        max_tokens=500,
    )
    targeted = await client.complete_json(
        load_prompt("image_targeted"),
        _claim_line(claim)
        + f"\nObservation: {blind}\nReturn the verdict JSON.",
        purpose="image",
        max_tokens=300,
    )
    merged = {**blind, **targeted}
    return _to_analysis(image_id, merged)
