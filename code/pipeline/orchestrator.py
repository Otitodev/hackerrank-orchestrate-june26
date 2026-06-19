"""Per-claim orchestration: run the five steps, apply the §6 decision ladder,
and assemble a validated 14-column :class:`OutputRow`.
"""

from __future__ import annotations

import asyncio

from models.schemas import (
    ClaimInput,
    ClaimStatus,
    IssueType,
    OBJECT_PARTS,
    OutputRow,
    RiskFlag,
    Severity,
)
from utils.csv_loader import match_requirement
from utils.image_loader import resolve_image_paths
from utils.llm import LLMClient

from . import Refs
from .claim_parser import parse_claim
from .decision_synthesiser import synthesise
from .evidence_checker import check_evidence
from .image_analyser import analyse_image
from .risk_assessor import assess_risk


def _safe_part(claim_object, part: str | None) -> str:
    if part and part in OBJECT_PARTS[claim_object]:
        return part
    return "unknown"


async def process_claim(
    claim: ClaimInput, refs: Refs, client: LLMClient, mode: str = "single"
) -> OutputRow:
    structured = await parse_claim(claim, client, refs.allowed_families)

    # Single best-match evidence rule for this claim; drives both the evidence
    # reason and the synthesiser context (the rulebook is no longer ignored).
    requirement = match_requirement(
        refs.requirements,
        claim.claim_object.value,
        structured.issue_family,
        structured.claimed_damage or "",
    )

    images = resolve_image_paths(claim.image_paths)
    analyses = await asyncio.gather(
        *[analyse_image(img, structured, client, mode) for img in images]
    )

    evidence = check_evidence(structured, list(analyses), requirement)
    risk = assess_risk(structured, claim.user_id, list(analyses), refs.history)

    # ---- Decision ladder (TRD §6) -------------------------------------
    # Priority 1: the evidence standard is the gate to a verdict. Calibrated on
    # the labeled sample: evidence_standard_met=false always maps to
    # not_enough_information. valid_image alone does NOT force NEI (a usable but
    # not-fully-standard image set can still yield a confident contradiction).
    if not evidence.evidence_standard_met:
        return _row(
            claim,
            evidence,
            risk,
            issue_type=IssueType.unknown,
            object_part=_safe_part(claim.claim_object, structured.claimed_part),
            claim_status=ClaimStatus.not_enough_information,
            justification=evidence.evidence_standard_met_reason,
            supporting_image_ids=[],
            severity=Severity.unknown,
        )

    # Priorities 2-5: handled by the synthesiser over structured context.
    synth = await synthesise(
        structured, list(analyses), evidence, risk, client, requirement
    )
    if synth is None:
        flags = list(risk.risk_flags)
        if RiskFlag.manual_review_required not in flags:
            flags.append(RiskFlag.manual_review_required)
        risk.risk_flags = flags
        return _row(
            claim,
            evidence,
            risk,
            issue_type=IssueType.unknown,
            object_part=_safe_part(claim.claim_object, structured.claimed_part),
            claim_status=ClaimStatus.not_enough_information,
            justification="Automated verdict could not be validated; flagged for manual review.",
            supporting_image_ids=[],
            severity=Severity.unknown,
        )

    return _row(
        claim,
        evidence,
        risk,
        issue_type=synth.issue_type,
        object_part=_safe_part(claim.claim_object, synth.object_part),
        claim_status=synth.claim_status,
        justification=synth.claim_status_justification,
        supporting_image_ids=synth.supporting_image_ids,
        severity=synth.severity,
    )


def _row(
    claim: ClaimInput,
    evidence,
    risk,
    *,
    issue_type: IssueType,
    object_part: str,
    claim_status: ClaimStatus,
    justification: str,
    supporting_image_ids,
    severity: Severity,
) -> OutputRow:
    return OutputRow(
        user_id=claim.user_id,
        image_paths=claim.image_paths,
        user_claim=claim.user_claim,
        claim_object=claim.claim_object,
        evidence_standard_met=evidence.evidence_standard_met,
        evidence_standard_met_reason=evidence.evidence_standard_met_reason,
        risk_flags=list(risk.risk_flags),
        issue_type=issue_type,
        object_part=object_part,
        claim_status=claim_status,
        claim_status_justification=justification,
        supporting_image_ids=list(supporting_image_ids),
        valid_image=evidence.valid_image,
        severity=severity,
    )
