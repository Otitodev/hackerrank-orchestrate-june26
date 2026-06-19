"""Step 5.3 — Evidence Checker (rule-based, no LLM).

There is no numeric ``min_images`` in the data; requirements are natural-language
guidance. So this is a soft check: ``valid_image`` = at least one technically
usable image; ``evidence_standard_met`` = a usable image actually shows the
claimed object/part well enough to inspect the claim.
"""

from __future__ import annotations

from typing import List, Optional

from models.schemas import EvidenceResult, ImageAnalysis, Requirement, StructuredClaim


def _is_usable(a: ImageAnalysis) -> bool:
    return (
        a.quality_score >= 3
        and not a.authenticity_suspicion
        and not a.text_instruction_present
    )


def _part_visible(claim: StructuredClaim, a: ImageAnalysis) -> bool:
    obj = claim.claim_object.value
    if a.detected_object and a.detected_object.lower() != obj:
        return False
    part = (claim.claimed_part or "").lower().strip()
    if not part:
        return True  # no specific part claimed; object presence is enough
    parts = " ".join(a.visible_parts).lower()
    return part in parts or any(p in part for p in a.visible_parts if p) or "body" in parts


def _standard(requirement: Optional[Requirement]) -> str:
    """The minimum-evidence standard prose for this claim, if matched."""
    if requirement and requirement.minimum_image_evidence:
        return f" Standard ({requirement.requirement_id}): {requirement.minimum_image_evidence}"
    return ""


def check_evidence(
    claim: StructuredClaim,
    analyses: List[ImageAnalysis],
    requirement: Optional[Requirement] = None,
) -> EvidenceResult:
    """Decide usability and whether the matched evidence standard is met.

    ``requirement`` is the single most relevant row of
    ``evidence_requirements.csv`` (see ``csv_loader.match_requirement``); its
    natural-language ``minimum_image_evidence`` is woven into the reason so the
    rulebook actually drives the explanation rather than being ignored.
    """
    standard = _standard(requirement)

    usable = [a for a in analyses if _is_usable(a)]
    valid_image = len(usable) > 0
    if not valid_image:
        return EvidenceResult(
            valid_image=False,
            evidence_standard_met=False,
            evidence_standard_met_reason=(
                "No usable image: all submitted images are too low quality, "
                "suspected non-original, or contain instruction text." + standard
            ),
        )

    shows = any(_part_visible(claim, a) for a in usable)
    if not shows:
        part = claim.claimed_part or "claimed part"
        return EvidenceResult(
            valid_image=True,
            evidence_standard_met=False,
            evidence_standard_met_reason=(
                f"Images are usable but none clearly show the {part} of the "
                f"{claim.claim_object.value} needed to evaluate the claim." + standard
            ),
        )

    return EvidenceResult(
        valid_image=True,
        evidence_standard_met=True,
        evidence_standard_met_reason=(
            f"At least one usable image shows the claimed {claim.claim_object.value} "
            f"part clearly enough to inspect the claimed condition." + standard
        ),
    )
