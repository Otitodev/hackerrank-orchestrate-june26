"""Pydantic models and controlled vocabularies for the evidence-review pipeline.

The single source of truth for the output contract lives in ``schemas.py``.
See ``trd.md`` (v1.1) and ``problem_statement.md`` for the schema rationale.
"""

from .schemas import (  # noqa: F401
    OUTPUT_COLUMNS,
    OBJECT_PARTS,
    ClaimInput,
    ClaimObject,
    ClaimStatus,
    EvidenceResult,
    ImageAnalysis,
    IssueType,
    OutputRow,
    RiskFlag,
    RiskResult,
    Severity,
    StructuredClaim,
    SynthesiserOutput,
    UserHistory,
)
