"""Step 5.4 — Risk Assessor (rule-based, no LLM).

Reads the precomputed ``history_flags`` from user_history directly and maps
image-analysis signals to the controlled ``risk_flags`` vocabulary. Flags never
change the verdict.
"""

from __future__ import annotations

from typing import Dict, List

from models.schemas import ImageAnalysis, RiskFlag, RiskResult, StructuredClaim, UserHistory


def assess_risk(
    claim: StructuredClaim,
    user_id: str,
    analyses: List[ImageAnalysis],
    history: Dict[str, UserHistory],
) -> RiskResult:
    flags: set[RiskFlag] = set()

    # History-derived flags come straight from the dataset.
    record = history.get(user_id)
    if record:
        for token in record.flag_list:
            try:
                flags.add(RiskFlag(token))
            except ValueError:
                pass  # unknown token; skip silently

    obj = claim.claim_object.value
    for a in analyses:
        if 0 < a.quality_score < 3:
            flags.add(RiskFlag.blurry_image)
        if a.authenticity_suspicion:
            flags.add(RiskFlag.possible_manipulation)
        if a.text_instruction_present:
            flags.add(RiskFlag.text_instruction_present)
        if a.detected_object and a.detected_object.lower() != obj:
            flags.add(RiskFlag.wrong_object)
        if a.verdict == "contradicts":
            flags.add(RiskFlag.claim_mismatch)

    # Damage-not-visible only when no usable image showed any damage at all.
    usable = [a for a in analyses if a.quality_score >= 3]
    if usable and not any(a.damage_observed for a in usable):
        flags.add(RiskFlag.damage_not_visible)

    # Order deterministically by vocabulary order for stable output.
    ordered = [f for f in RiskFlag if f in flags and f != RiskFlag.none]
    return RiskResult(risk_flags=ordered)
