"""Pydantic schemas + controlled vocabularies for the multi-modal evidence
review agent.

Everything here is reconciled against the *actual* dataset and
``problem_statement.md`` (see trd.md v1.1). The output contract is strict:
14 columns in a fixed order, the first four echoed verbatim from the input,
semicolon-separated lists, and the literal string ``none`` for empty lists.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies (problem_statement.md "Allowed values")
# ---------------------------------------------------------------------------


class ClaimObject(str, Enum):
    car = "car"
    laptop = "laptop"
    package = "package"


class ClaimStatus(str, Enum):
    supported = "supported"
    contradicted = "contradicted"
    not_enough_information = "not_enough_information"


class IssueType(str, Enum):
    dent = "dent"
    scratch = "scratch"
    crack = "crack"
    glass_shatter = "glass_shatter"
    broken_part = "broken_part"
    missing_part = "missing_part"
    torn_packaging = "torn_packaging"
    crushed_packaging = "crushed_packaging"
    water_damage = "water_damage"
    stain = "stain"
    none = "none"
    unknown = "unknown"


class Severity(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class RiskFlag(str, Enum):
    none = "none"
    blurry_image = "blurry_image"
    cropped_or_obstructed = "cropped_or_obstructed"
    low_light_or_glare = "low_light_or_glare"
    wrong_angle = "wrong_angle"
    wrong_object = "wrong_object"
    wrong_object_part = "wrong_object_part"
    damage_not_visible = "damage_not_visible"
    claim_mismatch = "claim_mismatch"
    possible_manipulation = "possible_manipulation"
    non_original_image = "non_original_image"
    text_instruction_present = "text_instruction_present"
    user_history_risk = "user_history_risk"
    manual_review_required = "manual_review_required"


# object_part is constrained *per object type*. "unknown" is valid everywhere.
OBJECT_PARTS: dict[ClaimObject, set[str]] = {
    ClaimObject.car: {
        "front_bumper", "rear_bumper", "door", "hood", "windshield",
        "side_mirror", "headlight", "taillight", "fender", "quarter_panel",
        "body", "unknown",
    },
    ClaimObject.laptop: {
        "screen", "keyboard", "trackpad", "hinge", "lid", "corner", "port",
        "base", "body", "unknown",
    },
    ClaimObject.package: {
        "box", "package_corner", "package_side", "seal", "label", "contents",
        "item", "unknown",
    },
}

# Exact output column order required by problem_statement.md.
OUTPUT_COLUMNS: List[str] = [
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]

NONE_SENTINEL = "none"
LIST_SEP = ";"


def _join_list(values: List[str]) -> str:
    """Serialize a list field to the on-disk convention (``;`` join / ``none``)."""
    cleaned = [v for v in values if v and v != NONE_SENTINEL]
    return LIST_SEP.join(cleaned) if cleaned else NONE_SENTINEL


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# Input + reference data models
# ---------------------------------------------------------------------------


class ClaimInput(BaseModel):
    """One row of ``claims.csv`` (input only; no ``claim_id`` exists)."""

    user_id: str
    image_paths: str          # raw semicolon-separated field, echoed verbatim
    user_claim: str
    claim_object: ClaimObject

    @property
    def image_path_list(self) -> List[str]:
        return [p.strip() for p in self.image_paths.split(LIST_SEP) if p.strip()]


class UserHistory(BaseModel):
    """One row of ``user_history.csv``."""

    user_id: str
    past_claim_count: int = 0
    accept_claim: int = 0
    manual_review_claim: int = 0
    rejected_claim: int = 0
    last_90_days_claim_count: int = 0
    history_flags: str = NONE_SENTINEL   # precomputed; may contain risk tokens
    history_summary: str = ""

    @property
    def flag_list(self) -> List[str]:
        """Risk flags already supplied by the dataset (read, don't recompute)."""
        return [f.strip() for f in self.history_flags.split(LIST_SEP)
                if f.strip() and f.strip() != NONE_SENTINEL]


class Requirement(BaseModel):
    """One row of ``evidence_requirements.csv`` (natural-language guidance)."""

    requirement_id: str
    claim_object: str                 # car | laptop | package | all
    applies_to: str                   # fuzzy issue family text
    minimum_image_evidence: str       # prose, NOT a count


# ---------------------------------------------------------------------------
# Intermediate pipeline structures
# ---------------------------------------------------------------------------


class StructuredClaim(BaseModel):
    """Output of Step 5.1 (Claim Parser)."""

    claim_object: ClaimObject
    claimed_damage: Optional[str] = None
    claimed_part: Optional[str] = None
    issue_family: str = "unknown"


class ImageAnalysis(BaseModel):
    """Merged two-pass result for a single image (Step 5.2)."""

    image_id: str
    detected_object: Optional[str] = None
    visible_parts: List[str] = []
    damage_observed: List[str] = []
    quality_score: int = 0            # 0 = missing/unusable, 1-5 otherwise
    # Perceptual risk signals (map to the controlled risk_flags vocabulary).
    low_light_or_glare: bool = False
    wrong_angle: bool = False
    cropped_or_obstructed: bool = False
    authenticity_suspicion: bool = False   # digitally edited -> possible_manipulation
    non_original_suspicion: bool = False    # stock/reused/AI -> non_original_image
    wrong_part_suspicion: bool = False      # claimed part not the one shown
    text_instruction_present: bool = False
    verdict: str = "inconclusive"     # supports | contradicts | inconclusive
    confidence: str = "low"
    reason: str = ""


class EvidenceResult(BaseModel):
    """Output of Step 5.3 (Evidence Checker)."""

    valid_image: bool = False
    evidence_standard_met: bool = False
    evidence_standard_met_reason: str = ""


class RiskResult(BaseModel):
    """Output of Step 5.4 (Risk Assessor)."""

    risk_flags: List[RiskFlag] = []


class SynthesiserOutput(BaseModel):
    """Verdict fields produced by the LLM in Step 5.5 (strict enums)."""

    model_config = ConfigDict(use_enum_values=False)

    claim_status: ClaimStatus
    issue_type: IssueType
    object_part: str
    supporting_image_ids: List[str] = []
    severity: Severity
    claim_status_justification: str


# ---------------------------------------------------------------------------
# Final output row — the contract that gets written to output.csv
# ---------------------------------------------------------------------------


class OutputRow(BaseModel):
    """A single validated row of ``output.csv`` (14 columns, fixed order)."""

    # 1-4: echoed input
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: ClaimObject
    # 5-6: evidence gate
    evidence_standard_met: bool
    evidence_standard_met_reason: str
    # 7: risk
    risk_flags: List[RiskFlag] = []
    # 8-9: classification
    issue_type: IssueType
    object_part: str
    # 10-11: verdict
    claim_status: ClaimStatus
    claim_status_justification: str
    # 12: support
    supporting_image_ids: List[str] = []
    # 13-14: usability + severity
    valid_image: bool
    severity: Severity

    @field_validator("object_part")
    @classmethod
    def _strip_object_part(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check_object_part(self) -> "OutputRow":
        allowed = OBJECT_PARTS[self.claim_object]
        if self.object_part not in allowed:
            raise ValueError(
                f"object_part={self.object_part!r} not valid for "
                f"claim_object={self.claim_object.value!r}; allowed: {sorted(allowed)}"
            )
        return self

    def to_csv_dict(self) -> dict[str, str]:
        """Render to the exact string form written to ``output.csv``."""
        return {
            "user_id": self.user_id,
            "image_paths": self.image_paths,
            "user_claim": self.user_claim,
            "claim_object": self.claim_object.value,
            "evidence_standard_met": _bool_str(self.evidence_standard_met),
            "evidence_standard_met_reason": self.evidence_standard_met_reason,
            "risk_flags": _join_list([f.value for f in self.risk_flags]),
            "issue_type": self.issue_type.value,
            "object_part": self.object_part,
            "claim_status": self.claim_status.value,
            "claim_status_justification": self.claim_status_justification,
            "supporting_image_ids": _join_list(self.supporting_image_ids),
            "valid_image": _bool_str(self.valid_image),
            "severity": self.severity.value,
        }
