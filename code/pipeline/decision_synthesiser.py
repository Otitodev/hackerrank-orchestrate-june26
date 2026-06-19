"""Step 5.5 — Decision Synthesiser. Text LLM over structured context (no pixels).

Produces the verdict fields, validated by Pydantic with one correction retry.
Returns ``None`` on repeated failure so the orchestrator can write a safe
fallback row.
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import ValidationError

from models.schemas import (
    EvidenceResult,
    ImageAnalysis,
    OBJECT_PARTS,
    Requirement,
    RiskResult,
    StructuredClaim,
    SynthesiserOutput,
)
from utils.llm import LLMClient

from . import load_prompt


def _bundle(
    claim: StructuredClaim,
    analyses: List[ImageAnalysis],
    evidence: EvidenceResult,
    risk: RiskResult,
    requirement: Optional[Requirement],
) -> str:
    lines = [
        f"Claim object: {claim.claim_object.value}",
        f"Claimed damage: {claim.claimed_damage or 'unspecified'}",
        f"Claimed part: {claim.claimed_part or 'unspecified'}",
        f"Issue family: {claim.issue_family}",
        f"Allowed object_part values: {sorted(OBJECT_PARTS[claim.claim_object])}",
    ]
    if requirement and requirement.minimum_image_evidence:
        lines.append(f"Minimum evidence standard: {requirement.minimum_image_evidence}")
    lines += [
        "",
        "Image evidence:",
    ]
    for a in analyses:
        lines.append(
            f"- {a.image_id}: detected={a.detected_object}, parts={a.visible_parts}, "
            f"damage={a.damage_observed}, quality={a.quality_score}/5, "
            f"verdict={a.verdict} ({a.confidence})"
        )
    lines += [
        "",
        f"Evidence standard met: {evidence.evidence_standard_met} ({evidence.evidence_standard_met_reason})",
        f"Risk flags: {[f.value for f in risk.risk_flags] or 'none'}",
        "",
        "Produce the verdict JSON using only the allowed vocabularies.",
    ]
    return "\n".join(lines)


def _coerce(data: dict, claim: StructuredClaim, valid_ids: set[str]) -> dict:
    """Sanitize model output toward the strict schema before validation."""
    out = dict(data)
    part = str(out.get("object_part", "unknown")).strip()
    if part not in OBJECT_PARTS[claim.claim_object]:
        part = "unknown"
    out["object_part"] = part
    ids = out.get("supporting_image_ids") or []
    if isinstance(ids, str):
        ids = [ids]
    out["supporting_image_ids"] = [i for i in ids if i in valid_ids]
    return out


async def synthesise(
    claim: StructuredClaim,
    analyses: List[ImageAnalysis],
    evidence: EvidenceResult,
    risk: RiskResult,
    client: LLMClient,
    requirement: Optional[Requirement] = None,
) -> Optional[SynthesiserOutput]:
    system = load_prompt("synthesiser")
    bundle = _bundle(claim, analyses, evidence, risk, requirement)
    valid_ids = {a.image_id for a in analyses}

    for attempt in range(2):
        data = await client.complete_json(
            system, bundle, purpose="synthesis", max_tokens=500
        )
        try:
            return SynthesiserOutput(**_coerce(data, claim, valid_ids))
        except (ValidationError, TypeError) as exc:
            if attempt == 0:
                bundle += (
                    f"\n\nYour previous response failed validation ({exc}). "
                    "Return corrected JSON using only the allowed enum values."
                )
            else:
                return None
    return None
