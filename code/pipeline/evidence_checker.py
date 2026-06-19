"""Step 5.3 — Evidence Checker (rule-based, no LLM).

There is no numeric ``min_images`` in the data; requirements are natural-language
guidance. So this is a soft check: ``valid_image`` = at least one technically
usable image; ``evidence_standard_met`` = a usable image actually shows the
claimed object/part well enough to inspect the claim.
"""

from __future__ import annotations

from typing import List

from models.schemas import EvidenceResult, ImageAnalysis, Requirement, StructuredClaim
from utils.csv_loader import select_requirements


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


def check_evidence(
    claim: StructuredClaim,
    analyses: List[ImageAnalysis],
    requirements: List[Requirement],
) -> EvidenceResult:
    # Applicable requirements (object-specific + "all"); kept for traceability.
    _ = select_requirements(requirements, claim.claim_object.value)

    usable = [a for a in analyses if _is_usable(a)]
    valid_image = len(usable) > 0
    if not valid_image:
        return EvidenceResult(
            valid_image=False,
            evidence_standard_met=False,
            evidence_standard_met_reason="No usable image: all submitted images are too low quality, suspected non-original, or contain instruction text.",
        )

    shows = any(_part_visible(claim, a) for a in usable)
    if not shows:
        part = claim.claimed_part or "claimed part"
        return EvidenceResult(
            valid_image=True,
            evidence_standard_met=False,
            evidence_standard_met_reason=f"Images are usable but none clearly show the {part} of the {claim.claim_object.value} needed to evaluate the claim.",
        )

    return EvidenceResult(
        valid_image=True,
        evidence_standard_met=True,
        evidence_standard_met_reason=f"At least one usable image shows the claimed {claim.claim_object.value} part clearly enough to inspect the claimed condition.",
    )
