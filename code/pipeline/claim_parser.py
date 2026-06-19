"""Step 5.1 — Claim Parser. Text LLM that extracts a structured claim."""

from __future__ import annotations

from typing import List

from models.schemas import ClaimInput, StructuredClaim
from utils.llm import LLMClient

from . import load_prompt


async def parse_claim(
    claim: ClaimInput, client: LLMClient, allowed_families: List[str]
) -> StructuredClaim:
    system = load_prompt("claim_parser")
    text = (
        f"object_type: {claim.claim_object.value}\n"
        f"allowed_issue_families: {', '.join(allowed_families)}\n\n"
        f"conversation:\n{claim.user_claim}"
    )
    data = await client.complete_json(system, text, purpose="parse", max_tokens=300)
    return StructuredClaim(
        claim_object=claim.claim_object,
        claimed_damage=data.get("claimed_damage") or None,
        claimed_part=data.get("claimed_part") or None,
        issue_family=(data.get("issue_family") or "unknown"),
    )
