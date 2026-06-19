# Technical Requirements Document

## Multi-Modal Evidence Review Agent

**HackerRank Orchestrate — June 2026**
**Author:** Otito Ogene
**Version:** 1.0
**Date:** June 19, 2026
**Status:** Draft

-----

## Table of Contents

1. [Overview](#1-overview)
1. [System Inputs](#2-system-inputs)
1. [System Output](#3-system-output)
1. [Architecture Overview](#4-architecture-overview)
1. [Pipeline Steps — Detailed Spec](#5-pipeline-steps--detailed-spec)
- 5.1 Claim Parser
- 5.2 Image Analyser
- 5.3 Evidence Checker
- 5.4 Risk Assessor
- 5.5 Decision Synthesiser
1. [Decision Logic](#6-decision-logic)
1. [Evaluation Workflow](#7-evaluation-workflow)
1. [Error Handling](#8-error-handling)
1. [Execution Strategy](#9-execution-strategy)
1. [Known Risks and Mitigations](#10-known-risks-and-mitigations)
1. [Tech Stack](#11-tech-stack)
1. [Project File Structure](#12-project-file-structure)

-----

## 1. Overview

This document specifies the technical architecture for an AI-powered damage claim verification agent. The system processes multi-modal inputs — images, claim conversations, user history, and evidence requirements — and produces a structured verdict per claim.

### Core objective

For each claim, decide whether submitted image evidence **supports**, **contradicts**, or **does not sufficiently address** the user’s stated damage claim.

### Design principles

- **Images are the primary source of truth.** No verdict should be driven by conversation text or user history alone.
- **User history raises flags, not verdicts.** A high-risk user history never overrides clear visual evidence.
- **Evidence requirements are a hard gate.** If minimum image requirements are not met, the verdict is always `insufficient_evidence`.
- **Perception and reasoning are separated.** The VLM observes images; a separate LLM synthesises the verdict. This prevents hallucination from anchoring.
- **Deterministic at the edges.** Rule-based logic handles clear cases (missing evidence, object mismatch). LLM judgment handles ambiguous ones.

-----

## 2. System Inputs

### 2.1 File inventory

|File                       |Location  |Description                                               |
|---------------------------|----------|----------------------------------------------------------|
|`sample_claims.csv`        |`dataset/`|Labeled rows for development and evaluation               |
|`claims.csv`               |`dataset/`|Unlabeled rows — agent runs on this file                  |
|`user_history.csv`         |`dataset/`|Per-user historical claim and risk data                   |
|`evidence_requirements.csv`|`dataset/`|Minimum image requirements by object type and issue family|
|Images                     |`images/` |JPEG/PNG files referenced by `image_ids` in claims        |

### 2.2 `claims.csv` schema

|Field         |Type  |Description                    |
|--------------|------|-------------------------------|
|`claim_id`    |string|Unique claim identifier        |
|`user_id`     |string|References `user_history.csv`  |
|`object_type` |enum  |`car` | `laptop` | `package`   |
|`conversation`|string|Raw support chat text          |
|`image_ids`   |string|Comma-separated image filenames|

### 2.3 `user_history.csv` schema (expected)

|Field          |Type  |Description            |
|---------------|------|-----------------------|
|`user_id`      |string|User identifier        |
|`total_claims` |int   |Lifetime claim count   |
|`recent_claims`|int   |Claims in last 90 days |
|`fraud_flags`  |int   |Prior flagged incidents|

### 2.4 `evidence_requirements.csv` schema (expected)

|Field            |Type  |Description                 |
|-----------------|------|----------------------------|
|`object_type`    |enum  |`car` | `laptop` | `package`|
|`issue_family`   |string|Normalised damage category  |
|`min_images`     |int   |Minimum image count required|
|`required_angles`|string|Expected viewpoints or parts|

### 2.5 Image format assumptions

- Accepted formats: `.jpg`, `.jpeg`, `.png`, `.webp`
- Naming convention: TBD from repo inspection — likely `{claim_id}_{index}.jpg`
- Images are loaded from disk and base64-encoded for the Anthropic Vision API
- Images exceeding 5MB are resized to a max dimension of 1568px before encoding (Anthropic limit)

-----

## 3. System Output

### 3.1 `output.csv` schema

|Field                 |Type  |Allowed values                                                                 |
|----------------------|------|-------------------------------------------------------------------------------|
|`claim_id`            |string|As provided in input                                                           |
|`decision`            |enum  |`supported` | `contradicted` | `insufficient_evidence`                         |
|`issue_type`          |string|Specific damage label (e.g. `cracked_screen`, `dented_panel`, `torn_packaging`)|
|`object_part`         |string|Relevant object part (e.g. `display`, `hood`, `outer_box`)                     |
|`supporting_image_ids`|string|Pipe-separated image IDs that drove the decision                               |
|`flags`               |string|Pipe-separated list of raised risk signals                                     |
|`severity`            |enum  |`low` | `medium` | `high`                                                      |
|`justification`       |string|1–2 sentences grounded in image evidence                                       |


> **Note:** Separator character for `supporting_image_ids` and `flags` (pipe vs comma) must be confirmed against the exact schema in `problem_statement.md`.

### 3.2 Valid flag values

|Flag           |Trigger                                                    |
|---------------|-----------------------------------------------------------|
|`history_risk` |User has elevated prior claim count or fraud flags         |
|`image_quality`|One or more images scored below quality threshold          |
|`mismatch`     |Image detected object type does not match claim object type|
|`authenticity` |VLM suspects image is stock photo or digitally altered     |

### 3.3 Severity mapping

|Decision               |Severity derivation                                                                                    |
|-----------------------|-------------------------------------------------------------------------------------------------------|
|`insufficient_evidence`|Always `low` — damage cannot be assessed                                                               |
|`contradicted`         |`medium` if minor mismatch; `high` if claim is clearly fabricated                                      |
|`supported`            |Derived from damage description: `low` (surface), `medium` (functional), `high` (structural/total loss)|

-----

## 4. Architecture Overview

```
claims.csv + images/
         │
         ▼
┌─────────────────────┐
│   1. Claim Parser   │  LLM — structured claim extraction from conversation
└──────────┬──────────┘
           │  { object_type, claimed_damage, claimed_part, issue_family }
           ▼
┌─────────────────────┐
│  2. Image Analyser  │  Claude Vision (async, one call per image)
│     [per image]     │  Two-pass: blind observation → targeted judgment
└──────────┬──────────┘
           │  [{ image_id, detected_object, visible_parts, damage_observed,
           │     quality_score, authenticity_suspicion, verdict, confidence }]
           ▼
┌─────────────────────┐
│ 3. Evidence Checker │  Rule-based — no LLM
│                     │  Lookup evidence_requirements.csv
└──────────┬──────────┘
           │  { evidence_ok: bool, reason?: string }
           ▼
┌─────────────────────┐
│  4. Risk Assessor   │  Rule-based — no LLM
│                     │  Lookup user_history.csv + image quality + mismatch check
└──────────┬──────────┘
           │  { flags: [] }
           ▼
┌──────────────────────────┐
│  5. Decision Synthesiser │  LLM — reasons over structured context (no raw images)
│                          │  Produces final output row
└──────────┬───────────────┘
           │
           ▼
       output.csv
```

-----

## 5. Pipeline Steps — Detailed Spec

### 5.1 Claim Parser

**Type:** LLM call (text only)

**Inputs:**

- `conversation` — raw support chat
- `object_type` — as given in the claims row
- `allowed_issue_families` — list loaded from `evidence_requirements.csv` at startup

**Prompt strategy:**
Extract a structured claim from the conversation. Normalise `issue_family` to one of the known values from the requirements table. Do not invent values outside the provided vocabulary.

**Output:**

```json
{
  "object_type": "laptop",
  "claimed_damage": "cracked screen after being dropped",
  "claimed_part": "display",
  "issue_family": "display_damage"
}
```

**Failure modes:**

- Conversation is vague or non-specific → `claimed_damage` = null → downstream evidence check will return `insufficient_evidence`
- Issue family cannot be mapped → log warning, set `issue_family` = `unknown`, treat as evidence gate failure

-----

### 5.2 Image Analyser

**Type:** Claude Vision API (two-pass, per image, async)

**Inputs:**

- Image file (base64-encoded)
- On pass 2 only: structured claim from Step 5.1

#### Pass 1 — Blind observation

No claim context is provided. The model describes what it sees without anchoring to what the user claimed.

**Prompt excerpt:**

> Describe what you see in this image. What object is present? What parts of the object are visible? Is there any visible damage? Rate the image quality on a scale of 1–5 where 1 is unusable (extreme blur, darkness, or cropping) and 5 is clear and detailed. Does this appear to be an authentic photograph or could it be a stock image or digitally altered?

**Pass 1 output:**

```json
{
  "detected_object": "laptop",
  "visible_parts": ["display", "keyboard", "hinge"],
  "damage_observed": ["spider fracture pattern on screen", "cracked bezel"],
  "quality_score": 4,
  "authenticity_suspicion": false
}
```

#### Pass 2 — Targeted judgment

Pass 1 output + claim context are both provided.

**Prompt excerpt:**

> The user claims: [cracked display on a laptop after impact]. Based on your observation above, does this image support the claim, contradict it, or is it inconclusive?

**Pass 2 output:**

```json
{
  "verdict": "supports",
  "confidence": "high",
  "reason": "Visible spider fracture pattern is consistent with impact damage to the display panel."
}
```

**Final image analyser output (merged):**

```json
{
  "image_id": "CLM001_1.jpg",
  "detected_object": "laptop",
  "visible_parts": ["display", "keyboard", "hinge"],
  "damage_observed": ["spider fracture pattern on screen", "cracked bezel"],
  "quality_score": 4,
  "authenticity_suspicion": false,
  "verdict": "supports",
  "confidence": "high",
  "reason": "Visible spider fracture pattern is consistent with impact damage to the display panel."
}
```

**Implementation notes:**

- All images for a single claim are processed in parallel using `asyncio.gather`
- Model: `claude-sonnet-4-6` with `temperature=0` for reproducibility
- Max tokens: 500 per pass
- If an image file is missing on disk, assign a synthetic result: `quality_score=0`, `verdict="inconclusive"`, flag `image_quality`

-----

### 5.3 Evidence Checker

**Type:** Rule-based (no LLM)

**Inputs:**

- Structured claim from Step 5.1 (`object_type`, `issue_family`)
- List of image analyser results from Step 5.2
- `evidence_requirements.csv` loaded into memory at startup

**Logic:**

```
1. Look up row in evidence_requirements where
   object_type == claim.object_type AND issue_family == claim.issue_family

2. If no matching row found:
   → evidence_ok = False, reason = "unknown_issue_family"

3. If len(images) < row.min_images:
   → evidence_ok = False, reason = "insufficient_image_count"

4. If required_angles defined and not all angles covered by visible_parts across images:
   → evidence_ok = False, reason = "missing_required_angles"

5. Otherwise:
   → evidence_ok = True
```

**Output:**

```json
{
  "evidence_ok": true
}
```

or

```json
{
  "evidence_ok": false,
  "reason": "insufficient_image_count"
}
```

**Important:** If `evidence_ok` is `False`, the pipeline short-circuits. Decision is set to `insufficient_evidence` and Steps 5.4–5.5 still run for flags, but the verdict is locked.

-----

### 5.4 Risk Assessor

**Type:** Rule-based (no LLM)

**Inputs:**

- `user_id` from the claim
- Image analyser results from Step 5.2
- `user_history.csv` loaded into memory at startup

**Flag generation rules:**

|Flag           |Rule                                                                                                     |
|---------------|---------------------------------------------------------------------------------------------------------|
|`history_risk` |`total_claims >= 5` OR `recent_claims >= 3` OR `fraud_flags >= 1` (thresholds TBD from data distribution)|
|`image_quality`|Any image has `quality_score < 3`                                                                        |
|`mismatch`     |Any image has `detected_object != claim.object_type`                                                     |
|`authenticity` |Any image has `authenticity_suspicion == true`                                                           |

**Notes:**

- If `user_id` is not in `user_history.csv`, skip `history_risk` silently — do not crash
- Multiple flags are additive
- Flags feed into the output row but **do not alter the verdict**

**Output:**

```json
{
  "flags": ["image_quality", "history_risk"]
}
```

-----

### 5.5 Decision Synthesiser

**Type:** LLM call (text only — no raw images)

**Inputs (all structured):**

- Structured claim from Step 5.1
- All image analyser results from Step 5.2
- Evidence check result from Step 5.3
- Flags from Step 5.4

**Why no raw images at this step:** The synthesiser reasons over structured observations, not pixels. This separates visual perception from logical reasoning and reduces hallucination risk.

**Prompt strategy:**

The synthesiser receives a compact JSON bundle of all context and is asked to produce the output row fields with chain-of-thought reasoning inside `<thinking>` tags before emitting the final JSON.

**Example prompt bundle:**

```
Claim: User claims a cracked laptop display after dropping the device.
Object type: laptop | Issue family: display_damage

Image evidence:
- CLM001_1.jpg: laptop detected, visible parts: [display, keyboard], damage: [spider fracture, cracked bezel], quality: 4/5, verdict: supports (high confidence)
- CLM001_2.jpg: laptop detected, visible parts: [bottom panel], damage: none observed, quality: 3/5, verdict: inconclusive

Evidence requirements met: yes (2 of 2 images provided)
Flags raised: []

Produce a verdict.
```

**Output:**

```json
{
  "decision": "supported",
  "issue_type": "cracked_screen",
  "object_part": "display",
  "supporting_image_ids": ["CLM001_1.jpg"],
  "severity": "high",
  "justification": "CLM001_1 shows a clear spider-fracture pattern across the display panel, consistent with the user's claim of impact damage. CLM001_2 provides no contradicting evidence."
}
```

**Validation:** Output is parsed into a Pydantic model before writing to CSV. On validation failure (wrong enum value, missing field), the step retries once with an explicit correction prompt. If it fails twice, the row is written with `decision = "insufficient_evidence"` and flagged for manual review.

-----

## 6. Decision Logic

The final decision follows a deterministic priority ladder:

```
Priority 1 — Evidence gate failed?
  → decision = insufficient_evidence, severity = low
  → STOP

Priority 2 — Any image shows object type mismatch?
  → decision = contradicted, flag = mismatch
  → severity = medium (minor) or high (major discrepancy)
  → STOP

Priority 3 — All image verdicts = "contradicts"?
  → decision = contradicted
  → severity from synthesiser

Priority 4 — At least one image verdict = "supports" and evidence gate passed?
  → decision = supported
  → severity from synthesiser

Priority 5 — Mixed or inconclusive signals?
  → decision = insufficient_evidence
  → severity = low
```

The LLM synthesiser handles Priority 3–5. Priorities 1 and 2 are rule-enforced before the synthesiser is called.

-----

## 7. Evaluation Workflow

Before running on `claims.csv`, evaluate against `sample_claims.csv` which has known expected outputs.

### Metrics

|Metric               |Field          |Weight                |
|---------------------|---------------|----------------------|
|Decision accuracy    |`decision`     |Primary               |
|Severity accuracy    |`severity`     |Secondary             |
|Flag recall          |`flags`        |Secondary             |
|Justification quality|`justification`|Qualitative (AI judge)|

### Eval loop

```
1. Run full pipeline on sample_claims.csv
2. Compare output.decision to expected.decision for each row
3. Compute accuracy, false positive rate (supported → actually contradicted), false negative rate
4. Identify failure patterns in prompt output
5. Adjust Step 5.1 (claim parser) or Step 5.5 (synthesiser) prompts
6. Re-run until decision accuracy is acceptable
7. Run on claims.csv — do not touch prompts again after this point
```

**Overfitting guard:** Tune prompt wording only. Never hard-code claim-specific answers. The system must generalise.

-----

## 8. Error Handling

|Error                                            |Location           |Handling                                                                                      |
|-------------------------------------------------|-------------------|----------------------------------------------------------------------------------------------|
|Image file not found on disk                     |Step 5.2           |Assign synthetic result: `quality_score=0`, `verdict="inconclusive"`, add `image_quality` flag|
|API rate limit (429)                             |Steps 5.1, 5.2, 5.5|Exponential backoff, max 3 retries                                                            |
|API call fails entirely                          |Steps 5.1, 5.2, 5.5|Log error, write row with `decision=insufficient_evidence`, flag for manual review            |
|Pydantic validation failure on synthesiser output|Step 5.5           |Retry once with correction prompt; on second failure, write fallback row                      |
|User ID not in history CSV                       |Step 5.4           |Skip `history_risk` flag silently                                                             |
|Issue family not in requirements CSV             |Step 5.3           |`evidence_ok = False`, `reason = unknown_issue_family`                                        |
|Unsupported image format                         |Step 5.2           |Log warning, treat as missing image                                                           |
|Image exceeds size limit                         |Step 5.2           |Resize to max 1568px before encoding                                                          |

All errors are written to a `run.log` file alongside `output.csv` for post-run inspection.

-----

## 9. Execution Strategy

### Startup

```python
# At startup, load all reference data into memory once
user_history = load_csv("dataset/user_history.csv")       # dict keyed by user_id
evidence_reqs = load_csv("dataset/evidence_requirements.csv")  # dict keyed by (object_type, issue_family)
allowed_issue_families = list(evidence_reqs.keys())
```

### Per-claim execution

```python
for claim in claims:
    structured_claim = claim_parser(claim.conversation, claim.object_type)

    image_results = await asyncio.gather(*[
        image_analyser(img, structured_claim) for img in claim.images
    ])

    evidence_result = evidence_checker(structured_claim, image_results)
    risk_result = risk_assessor(claim.user_id, image_results)
    final_output = decision_synthesiser(structured_claim, image_results, evidence_result, risk_result)

    write_row(output_csv, final_output)
```

### Rate limiting

- Use `asyncio.Semaphore(5)` to cap concurrent API calls at 5
- Process claims in sequential order; parallelism is within a single claim’s images only
- Add a 0.5s sleep between claim batches if running a large set

### Output writing

- Write rows incrementally as each claim completes (not all at once at the end)
- This allows partial recovery if the run is interrupted

-----

## 10. Known Risks and Mitigations

|Risk                                           |Likelihood|Impact  |Mitigation                                                             |
|-----------------------------------------------|----------|--------|-----------------------------------------------------------------------|
|VLM hallucinates damage on blurry image        |Medium    |High    |Quality gate in Step 5.3; blind pass in Step 5.2 prevents anchoring    |
|Wrong issue family mapping in parser           |Medium    |High    |Constrain LLM to known vocabulary from requirements CSV                |
|Output CSV field names mismatch expected schema|Low       |Critical|Read problem_statement.md schema verbatim before writing Pydantic model|
|Rate limit hit mid-run                         |Medium    |Medium  |Semaphore + backoff; incremental writes preserve completed rows        |
|Prompt overfitting to sample labels            |Medium    |Medium  |Tune wording only; never hard-code claim references                    |
|User ID missing from history CSV               |Low       |Low     |Silent skip; no crash                                                  |
|Stock photo submitted as evidence              |Low       |Medium  |Authenticity flag from VLM; does not change verdict alone              |
|Context bleeding between image passes          |Low       |High    |Pass 1 is strictly blind — claim context added only in Pass 2          |
|Severity calibration inconsistency             |Medium    |Low     |Explicit severity rubric in synthesiser prompt                         |

-----

## 11. Tech Stack

|Layer              |Choice                               |Rationale                                                                   |
|-------------------|-------------------------------------|----------------------------------------------------------------------------|
|Language           |Python 3.11                          |Standard for ML pipelines                                                   |
|LLM / VLM          |`claude-sonnet-4-6` via Anthropic SDK|Native vision, reliable JSON output, structured tool use                    |
|Async I/O          |`asyncio`                            |Parallel image analysis per claim                                           |
|Data handling      |`pandas`                             |CSV reading, data lookups                                                   |
|Output validation  |`pydantic` v2                        |Strict schema enforcement before CSV write                                  |
|Orchestration      |Sequential Python (no LangGraph)     |Simpler to debug; LangGraph overhead not needed for a 5-step linear pipeline|
|Logging            |Python `logging` module → `run.log`  |Required by AGENTS.md (chat transcript logging)                             |
|Image preprocessing|`Pillow`                             |Resize oversized images before base64 encoding                              |

-----

## 12. Project File Structure

```
code/
├── main.py                    # Entry point — reads claims.csv, writes output.csv
├── pipeline/
│   ├── __init__.py
│   ├── claim_parser.py        # Step 5.1 — LLM structured extraction
│   ├── image_analyser.py      # Step 5.2 — VLM two-pass per image
│   ├── evidence_checker.py    # Step 5.3 — rule-based requirements gate
│   ├── risk_assessor.py       # Step 5.4 — rule-based flag generation
│   └── decision_synthesiser.py # Step 5.5 — LLM final verdict
├── models/
│   └── schemas.py             # Pydantic models for all structured data
├── utils/
│   ├── csv_loader.py          # Load and index all reference CSVs
│   ├── image_loader.py        # File path resolution, base64 encoding, resize
│   └── logger.py              # Logging setup → run.log
├── eval/
│   └── evaluate.py            # Run against sample_claims.csv, print metrics
├── prompts/
│   ├── claim_parser.txt       # Prompt template for Step 5.1
│   ├── image_blind.txt        # Pass 1 prompt for Step 5.2
│   ├── image_targeted.txt     # Pass 2 prompt for Step 5.2
│   └── synthesiser.txt        # Prompt template for Step 5.5
├── requirements.txt
└── output.csv                 # Generated — do not commit
```

-----

*This document should be treated as the single source of truth for implementation decisions. Any deviation during build should be noted here with rationale.*