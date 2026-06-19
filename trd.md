# Technical Requirements Document

## Multi-Modal Evidence Review Agent

**HackerRank Orchestrate — June 2026**
**Author:** Otito Ogene
**Version:** 1.1
**Date:** June 19, 2026
**Status:** Draft — reconciled against actual repo schema

> **v1.1 changelog (schema reconciliation).** v1.0 was written from assumed
> schemas. After inspecting the real `dataset/` files and `problem_statement.md`,
> the following were corrected: input/output column names, separators (semicolon,
> not pipe/comma), the decision enum (`not_enough_information`, not
> `insufficient_evidence`), the full `risk_flags` / `issue_type` / `object_part`
> controlled vocabularies, the `user_history.csv` and `evidence_requirements.csv`
> schemas (the latter has **no** numeric `min_images` — requirements are
> natural-language guidance), image naming (`case_NNN/img_N.jpg`, no `claim_id`),
> the 5-value severity set, the split between `valid_image` and
> `evidence_standard_met`, and the entry-point/folder contract.

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
|`sample_claims.csv`        |`dataset/`|Labeled rows for development and evaluation (20 rows)     |
|`claims.csv`               |`dataset/`|Unlabeled rows — agent runs on this file (44 rows)        |
|`user_history.csv`         |`dataset/`|Per-user historical claim and risk data (47 users)        |
|`evidence_requirements.csv`|`dataset/`|Natural-language minimum-evidence guidance (11 rules)     |
|Images                     |`dataset/images/{sample,test}/case_NNN/`|JPEG files referenced by `image_paths` in claims|

### 2.2 `claims.csv` schema (actual)

There is **no `claim_id` column.** Rows are identified by position and by
echoing the four input columns into the output.

|Field         |Type  |Description                                                  |
|--------------|------|-------------------------------------------------------------|
|`user_id`     |string|References `user_history.csv`                                |
|`image_paths` |string|**Semicolon**-separated relative paths, e.g. `images/test/case_001/img_1.jpg;images/test/case_001/img_2.jpg`|
|`user_claim`  |string|Raw support chat transcript                                  |
|`claim_object`|enum  |`car` \| `laptop` \| `package`                               |

The **image ID** is the filename without extension (e.g. `img_1`). Image IDs
are not globally unique — every `case_NNN` folder has its own `img_1` — so index
images per-claim, never in a global map.

### 2.3 `user_history.csv` schema (actual)

|Field                     |Type  |Description / observed range                 |
|--------------------------|------|---------------------------------------------|
|`user_id`                 |string|User identifier                              |
|`past_claim_count`        |int   |Lifetime claim count (0–14)                  |
|`accept_claim`            |int   |Historically accepted claims (0–4)           |
|`manual_review_claim`     |int   |Historically manually-reviewed claims (0–4)  |
|`rejected_claim`          |int   |Historically rejected claims (0–7)           |
|`last_90_days_claim_count`|int   |Recent claim count (0–9)                     |
|`history_flags`           |string|**Precomputed** semicolon-separated flags: `none`, `user_history_risk`, `manual_review_required` (or a combination)|
|`history_summary`         |string|Free-text risk summary                       |

> **Key:** `history_flags` already encodes the history-derived risk. The Risk
> Assessor should **read `history_flags` directly** rather than invent count
> thresholds. (`fraud_flags` from v1.0 does not exist.)

### 2.4 `evidence_requirements.csv` schema (actual)

|Field                  |Type  |Description                                            |
|-----------------------|------|-------------------------------------------------------|
|`requirement_id`       |string|Rule identifier, e.g. `REQ_CAR_BODY_PANEL`             |
|`claim_object`         |enum  |`car` \| `laptop` \| `package` \| **`all`**            |
|`applies_to`           |string|Fuzzy issue family, e.g. `"dent or scratch"`, `"crack, broken, or missing part"`|
|`minimum_image_evidence`|string|**Natural-language** sentence describing what must be visible|

> **Critical:** there is **no integer `min_images` and no `required_angles`
> field.** `minimum_image_evidence` is prose guidance, several rules apply to
> `all`, and multiple rules can apply to one claim. The evidence check therefore
> cannot be an arithmetic count gate (see §5.3); it is a soft, guidance-driven
> assessment.

### 2.5 Image format assumptions

- Format on disk: `.jpg` (loader still accepts `.jpeg`, `.png`, `.webp`).
- Layout: `dataset/images/{sample,test}/case_NNN/img_N.jpg`. Ignore `.DS_Store`.
- `image_id` = filename stem (`img_1`). Paths in `image_paths` are repo-relative.
- Images are loaded from disk and base64-encoded for the Anthropic Vision API.
- Images exceeding 5MB are resized to a max dimension of 1568px before encoding (Anthropic limit).

-----

## 3. System Output

### 3.1 `output.csv` schema

**14 columns, in this exact order.** The first four **echo the input row verbatim.**

|#|Field                       |Type  |Allowed values / format                                                  |
|-|----------------------------|------|-------------------------------------------------------------------------|
|1|`user_id`                   |string|Echoed from input                                                        |
|2|`image_paths`               |string|Echoed from input (semicolon-separated)                                  |
|3|`user_claim`                |string|Echoed from input                                                        |
|4|`claim_object`              |enum  |Echoed from input: `car` \| `laptop` \| `package`                        |
|5|`evidence_standard_met`     |bool  |`true` if the image set is sufficient to evaluate the claim, else `false`|
|6|`evidence_standard_met_reason`|string|Short reason for the evidence decision                                 |
|7|`risk_flags`                |string|**Semicolon**-separated risk flags, or `none` (see §3.2)                 |
|8|`issue_type`                |enum  |Controlled vocab (see §3.2)                                              |
|9|`object_part`               |enum  |Controlled vocab, per object type (see §3.2)                            |
|10|`claim_status`             |enum  |`supported` \| `contradicted` \| `not_enough_information`                |
|11|`claim_status_justification`|string|1–2 sentences grounded in image evidence; mention image IDs when helpful|
|12|`supporting_image_ids`     |string|**Semicolon**-separated image IDs (e.g. `img_1;img_2`), or `none`        |
|13|`valid_image`              |bool  |`true` if the image set is usable for automated review, else `false`     |
|14|`severity`                 |enum  |`none` \| `low` \| `medium` \| `high` \| `unknown`                       |

> **Separators are confirmed:** semicolon for `risk_flags` and
> `supporting_image_ids`; empty lists are the literal string `none`.
> `claim_status` is `not_enough_information` (**not** `insufficient_evidence`).

### 3.2 Controlled vocabularies

**`claim_status`:** `supported`, `contradicted`, `not_enough_information`

**`issue_type`:** `dent`, `scratch`, `crack`, `glass_shatter`, `broken_part`,
`missing_part`, `torn_packaging`, `crushed_packaging`, `water_damage`, `stain`,
`none`, `unknown`. Use `none` when the part is visible and undamaged; `unknown`
when it cannot be determined.

**`object_part`** (depends on `claim_object`):
- car: `front_bumper`, `rear_bumper`, `door`, `hood`, `windshield`, `side_mirror`, `headlight`, `taillight`, `fender`, `quarter_panel`, `body`, `unknown`
- laptop: `screen`, `keyboard`, `trackpad`, `hinge`, `lid`, `corner`, `port`, `base`, `body`, `unknown`
- package: `box`, `package_corner`, `package_side`, `seal`, `label`, `contents`, `item`, `unknown`

**`risk_flags`** (semicolon-separated, or `none`):
`none`, `blurry_image`, `cropped_or_obstructed`, `low_light_or_glare`,
`wrong_angle`, `wrong_object`, `wrong_object_part`, `damage_not_visible`,
`claim_mismatch`, `possible_manipulation`, `non_original_image`,
`text_instruction_present`, `user_history_risk`, `manual_review_required`

Rough sourcing of flags:

|Flag family                                              |Source                                                          |
|---------------------------------------------------------|----------------------------------------------------------------|
|`blurry_image`, `low_light_or_glare`, `cropped_or_obstructed`, `wrong_angle`|Image Analyser quality/framing observation       |
|`wrong_object`, `wrong_object_part`, `claim_mismatch`, `damage_not_visible`|Image vs claim comparison                         |
|`possible_manipulation`, `non_original_image`            |VLM authenticity suspicion (stock / edited)                     |
|`text_instruction_present`                               |VLM detects embedded text trying to instruct the model (image prompt-injection)|
|`user_history_risk`, `manual_review_required`            |Read directly from `user_history.history_flags`                 |

### 3.3 Severity mapping (5-value set)

|`claim_status`           |Severity derivation                                                                    |
|-------------------------|---------------------------------------------------------------------------------------|
|`not_enough_information` |`unknown` (cannot be assessed) or `none` when no damage is the finding                 |
|`contradicted`           |`none`/`low` for minor mismatch; up to `high` when the claim is clearly unsupported     |
|`supported`              |From damage extent: `low` (surface), `medium` (functional), `high` (structural/total loss)|

> Calibrate against `sample_claims.csv`: observed severity distribution is
> `medium`×11, `low`×3, `unknown`×3, `none`×2, `high`×1. Do not force gated rows
> to `low` (v1.0 was wrong here).

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

- Structured claim from Step 5.1 (`claim_object`, `issue_family`)
- List of image analyser results from Step 5.2
- `evidence_requirements.csv` loaded into memory at startup

**Logic (soft, guidance-driven — there is no numeric `min_images`):**

```
1. Select applicable requirement rows:
   rows where claim_object in (claim.claim_object, "all"),
   optionally narrowed by fuzzy-matching the claim's issue family
   against `applies_to`. Multiple rows may apply; collect all.

2. valid_image  = at least one image is usable for automated review
                  (quality_score >= 3 AND not authenticity-suspect AND
                   no text-instruction injection).

3. evidence_standard_met = valid_image AND at least one image clearly
   shows the claimed object and the claimed part well enough to inspect
   the claimed condition (per the selected requirements' prose).

4. evidence_standard_met_reason = short human reason, e.g.
   "rear bumper visible and dent inspectable" /
   "claimed part not visible in any submitted image" /
   "all images too blurry to assess".
```

`valid_image` (technical usability) and `evidence_standard_met` (claim-specific
coverage) are **distinct** output fields — do not collapse them.

**Output:**

```json
{
  "valid_image": true,
  "evidence_standard_met": true,
  "evidence_standard_met_reason": "The claimed rear bumper is clearly visible and the dent can be inspected."
}
```

**Important:** If `evidence_standard_met` is `false`, the claim cannot be
adjudicated from evidence — `claim_status` is locked to
`not_enough_information`. Steps 5.4–5.5 still run for flags and justification.

-----

### 5.4 Risk Assessor

**Type:** Rule-based (no LLM)

**Inputs:**

- `user_id` from the claim
- Image analyser results from Step 5.2
- `user_history.csv` loaded into memory at startup

**Flag generation rules** (output values must come from the §3.2 vocabulary):

|Source flag(s)                                                            |Rule                                                                 |
|--------------------------------------------------------------------------|---------------------------------------------------------------------|
|`user_history_risk`, `manual_review_required`                             |**Read directly** from `user_history.history_flags` for this `user_id` and pass through|
|`blurry_image`, `low_light_or_glare`, `cropped_or_obstructed`, `wrong_angle`|Any image flagged with the corresponding quality/framing defect    |
|`wrong_object`, `wrong_object_part`                                       |Detected object / part does not match the claim                       |
|`claim_mismatch`, `damage_not_visible`                                    |Claimed damage absent or inconsistent across all images               |
|`possible_manipulation`, `non_original_image`                             |Image Analyser authenticity suspicion                                 |
|`text_instruction_present`                                                |Image Analyser detected embedded instruction text                     |

**Notes:**

- If `user_id` is not in `user_history.csv`, skip the history flags silently — do not crash.
- Multiple flags are additive; join with `;`. If none, emit the literal `none`.
- Flags feed the output row but **do not alter `claim_status`**.

**Output:**

```json
{
  "risk_flags": ["blurry_image", "user_history_risk"]
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
- img_1: laptop detected, visible parts: [screen, keyboard], damage: [spider fracture, cracked bezel], quality: 4/5, verdict: supports (high confidence)
- img_2: laptop detected, visible parts: [base], damage: none observed, quality: 3/5, verdict: inconclusive

Evidence standard met: yes (screen clearly inspectable in img_1)
Flags raised: none

Produce a verdict using only the allowed vocabularies.
```

**Output (synthesiser-owned fields only; the loader echoes the 4 input columns
and the rule layer supplies `evidence_standard_met*`/`valid_image`):**

```json
{
  "claim_status": "supported",
  "issue_type": "crack",
  "object_part": "screen",
  "supporting_image_ids": ["img_1"],
  "severity": "high",
  "claim_status_justification": "img_1 shows a clear spider-fracture across the screen, consistent with the claimed impact damage; img_2 shows no contradicting evidence."
}
```

**Validation:** Output is parsed into a Pydantic model (strict enums) before
writing to CSV. On validation failure (bad enum, missing field), retry once with
an explicit correction prompt. If it fails twice, write a fallback row with
`claim_status = "not_enough_information"` and add `manual_review_required` to
`risk_flags`.

-----

## 6. Decision Logic

The final decision follows a deterministic priority ladder:

```
Priority 1 — evidence_standard_met == false (or valid_image == false)?
  → claim_status = not_enough_information, severity = unknown
  → STOP (synthesiser not called for the verdict)

Priority 2 — Any image shows wrong_object / wrong_object_part vs the claim?
  → claim_status = contradicted, flag = wrong_object / wrong_object_part / claim_mismatch
  → severity = low (minor) … high (clearly unsupported)
  → STOP

Priority 3 — All image verdicts = "contradicts"?
  → claim_status = contradicted
  → severity from synthesiser

Priority 4 — At least one image verdict = "supports" and evidence standard met?
  → claim_status = supported
  → severity from synthesiser

Priority 5 — Mixed or inconclusive signals?
  → claim_status = not_enough_information
  → severity = unknown
```

The LLM synthesiser handles Priority 3–5. Priorities 1 and 2 are rule-enforced
before the synthesiser is called. Note `not_enough_information` takes severity
`unknown`/`none`, never a forced `low`.

-----

## 7. Evaluation Workflow

Before running on `claims.csv`, evaluate against `sample_claims.csv` which has known expected outputs.

### Metrics

|Metric               |Field                       |Weight                |
|---------------------|----------------------------|----------------------|
|Decision accuracy    |`claim_status`              |Primary               |
|Evidence-gate accuracy|`evidence_standard_met`, `valid_image`|Secondary    |
|Severity accuracy    |`severity`                  |Secondary             |
|Flag recall/precision|`risk_flags`                |Secondary             |
|Justification quality|`claim_status_justification`|Qualitative (AI judge)|

### Required deliverables (per README + problem_statement)

1. Metrics on `dataset/sample_claims.csv`.
2. **At least two strategies / prompts / model configurations compared** (e.g.
   single-pass vs two-pass image analysis, or Sonnet-only vs Sonnet+Opus on hard
   rows). Record both in the report.
3. The final strategy chosen for `output.csv`.
4. `evaluation/evaluation_report.md` with an **operational analysis**: approximate
   model-call count, input/output token usage, images processed, estimated cost
   (state pricing assumptions), runtime/latency, and TPM/RPM + batching/throttling/
   caching/retry strategy.

### Eval loop

```
1. Run full pipeline on sample_claims.csv
2. Compare output.claim_status to expected.claim_status per row
3. Compute accuracy, FP rate (supported → actually contradicted), FN rate
4. Identify failure patterns; adjust Step 5.1 / 5.5 prompts (wording only)
5. Re-run until decision accuracy is acceptable
6. Lock prompts, run on claims.csv
```

**Overfitting guard:** Tune prompt wording only. Never hard-code claim-specific
answers. The system must generalise.

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
user_history = load_user_history("dataset/user_history.csv")     # dict keyed by user_id
evidence_reqs = load_requirements("dataset/evidence_requirements.csv")  # list of rules
# Requirements are grouped by claim_object (incl. "all"); matching to a claim is
# fuzzy on `applies_to`, so we keep the rows and select applicable ones per claim
# rather than building a single (object, family) lookup key.
```

### Per-claim execution

```python
for claim in claims:                      # claim has user_id, image_paths, user_claim, claim_object
    structured_claim = claim_parser(claim.user_claim, claim.claim_object)

    image_results = await asyncio.gather(*[
        image_analyser(img, structured_claim) for img in claim.images   # img.image_id == filename stem
    ])

    evidence_result = evidence_checker(structured_claim, image_results, evidence_reqs)
    risk_result = risk_assessor(claim.user_id, image_results, user_history)
    verdict = decision_synthesiser(structured_claim, image_results, evidence_result, risk_result)

    # Output row echoes the 4 input columns, then merges rule + synthesiser fields
    write_row(output_csv, build_output_row(claim, evidence_result, risk_result, verdict))
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

> **Entry-point contract (AGENTS.md §6.1):** the evaluator looks for
> `code/main.py` and `code/evaluation/main.py`, and the submitted `code.zip`
> must contain an `evaluation/` folder. Use `evaluation/` (not `eval/`).

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
├── evaluation/
│   ├── main.py                # Evaluation entry point (run on sample_claims.csv)
│   └── evaluation_report.md   # Metrics + strategy comparison + operational analysis
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