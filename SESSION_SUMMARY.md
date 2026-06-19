# Session Summary — Multi-Modal Evidence Review

Working log of the build for the HackerRank Orchestrate challenge, branch
`claude/trd-review-schema-check-foxm86` (PR #1). Captures the TRD review,
decisions made, what was built, and how to run it.

---

## 1. Starting point

The repo shipped a starter (`AGENTS.md`, `problem_statement.md`, `dataset/`,
empty `code/main.py` + `code/evaluation/main.py`) plus a full **Technical
Requirements Document** (`trd.md`, v1.0) written from *assumed* schemas. The
task: review the TRD against the real files, then build the system.

---

## 2. TRD review — findings (v1.0 was written from assumptions)

The architecture and reasoning design were sound; the concrete contract details
were largely wrong. Reconciled against the actual `dataset/` + `problem_statement.md`:

### 🔴 Critical (would fail evaluation)
1. **Input columns wrong.** No `claim_id` exists. Real `claims.csv`:
   `user_id, image_paths, user_claim, claim_object`.
2. **Output is 14 columns, fixed order, first 4 echo the input.** TRD listed 8
   and missed `evidence_standard_met`, `evidence_standard_met_reason`, `valid_image`.
3. **Decision enum** is `not_enough_information`, not `insufficient_evidence`.
4. **Separators are semicolons**, not pipes; empty lists are the literal `none`.
5. **`risk_flags` vocabulary** — none of the TRD's 4 flags were valid; the real
   controlled set has 14 tokens (incl. `text_instruction_present` for image
   prompt-injection, which the TRD missed).
6. **`evidence_requirements.csv` has no `min_images`** — it's natural-language
   guidance, so the TRD's arithmetic evidence gate was impossible as designed.
7. **`user_history.csv`** ships a precomputed `history_flags` column
   (`user_history_risk` / `manual_review_required`) — read it directly rather
   than inventing count thresholds. No `fraud_flags` exists.

### 🟠 Significant
8. **Image naming guessed wrong.** Real layout `images/{sample,test}/case_NNN/img_N.jpg`;
   image ID = filename stem (`img_1`), unique only within a claim.
9. **Severity** is a 5-value set (`none/low/medium/high/unknown`); gated rows are
   `unknown`/`none`, not forced `low`.
10. **`valid_image` vs `evidence_standard_met`** are distinct fields the TRD conflated.
11. Missing required deliverables: a **two-strategy comparison** and an
    `evaluation/evaluation_report.md` **operational analysis**.
12. Entry-point/folder contract: must be `code/evaluation/main.py` (not `eval/`).

### Dataset facts
- 44 test claims (82 images), 20 sample claims (29 images), 47 users, 11 rules.
- Test image distribution: 13×1-img, 24×2-img, 7×3-img.

These were all corrected in **`trd.md` v1.1** (with a changelog).

---

## 3. Decisions made during the session

| Decision | Choice | Rationale |
|---|---|---|
| Image analysis | **single structured call per image** (primary) | Halves VLM cost vs two-pass; problem rewards minimizing repeated calls. Two-pass kept for the eval comparison only. |
| LLM layer | **provider-agnostic factory** | User requirement: support vision models from multiple vendors. Anthropic / OpenAI / Gemini + offline mock behind one interface. |
| Default model | `claude-sonnet-4-6` ($3/$15 per 1M, native vision) | Cost-effective for ~170 calls/run. `claude-opus-4-8` available via `LLM_MODEL`. **(open question — see §6)** |
| Offline testability | **mock client** | No API key in the build env; mock makes the whole pipeline + eval runnable and deterministic for tests. |
| Evidence check | soft, guidance-driven (no arithmetic gate) | `evidence_requirements` has no numeric `min_images`. |
| Risk flags | read `history_flags` directly + map image signals | Dataset already encodes history risk. |

---

## 4. What was built

### Contract layer (`code/models/`, `code/utils/`)
- `models/schemas.py` — Pydantic enums + `OutputRow` with per-object
  `object_part` validation and exact CSV serialization (`;`-join, `none`
  sentinel, lowercase bools).
- `utils/csv_loader.py` — indexed reference-data loaders + quote-all writer.
- `utils/image_loader.py` — path resolution, `image_id` stem, base64 + resize.
- `utils/logger.py` — `run.log` setup.

### Provider-agnostic LLM layer (`code/utils/llm/`)
- `base.py` — abstract `LLMClient` (async `complete_json` over vendor-neutral
  `(base64, media_type)` image blocks), shared `asyncio.Semaphore`, retry +
  exponential backoff, JSON extraction, token/cost accounting.
- Adapters (lazy SDK imports): `anthropic_client`, `openai_client`,
  `gemini_client`, `mock_client`.
- `factory.py` — `make_client()` selects provider via `LLM_PROVIDER`/`LLM_MODEL`,
  else auto-detects from whichever API key is present, else mock.

### Pipeline (`code/pipeline/`)
- `claim_parser` (5.1) → `image_analyser` (5.2, single + two_pass) →
  `evidence_checker` (5.3, rules) → `risk_assessor` (5.4, rules) →
  `decision_synthesiser` (5.5, pydantic-validated + retry + fallback) →
  `orchestrator` applying the §6 decision ladder into a validated `OutputRow`.
- `prompts/*.txt` — provider-neutral templates embedding the controlled vocab.

### Runner, eval, docs
- `main.py` — CLI (`--provider/--model/--mock/--mode/--limit`), incremental
  crash-safe writes, `run.log`.
- `evaluation/main.py` — scores `sample_claims.csv` (claim_status accuracy +
  severity/evidence/valid-image + risk-flag P/R + confusion matrix), runs the
  single-vs-two_pass comparison.
- `evaluation/evaluation_report.md` — operational analysis (call counts, token/
  cost estimates with per-provider pricing assumptions, latency, TPM/RPM).
- `README.md`, `tests/test_pipeline_mock.py`, `requirements.txt`, `.gitignore`.

---

## 5. Verification (offline, no API key)

- All pipeline modules import cleanly.
- Full test set (mock): **44 rows / 170 calls / 82 images** — matches the report.
- Two-pass path works; `pytest` → 2 passed.
- `OutputRow` round-trips to CSV matching `sample_claims.csv` formatting exactly;
  invalid `object_part`/object combos are rejected.

Operational numbers (single strategy, test set): 170 calls (44 parser + 82 image
+ 44 synth); est. ~$1.04 on `claude-sonnet-4-6`. Two-pass ≈ 252 calls.

---

## 6. How to produce the real submission

The build env has no API key, so the system was validated against the mock.
To generate real predictions:

```bash
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY / GOOGLE_API_KEY
pip install -r code/requirements.txt
python code/evaluation/main.py --compare   # real metrics + report numbers
python code/main.py                         # real output.csv (44 rows)
```

Swap providers with one env var, e.g. `LLM_PROVIDER=openai`.

---

## 7. Open question

- **Default model:** currently `claude-sonnet-4-6` (cost-efficient for this
  high-volume VLM workload). Repo guidance leans toward defaulting to the most
  capable model (`claude-opus-4-8`). One-line change in
  `code/utils/llm/factory.py` if we want Opus as the default (optionally
  escalating only hard rows).

---

## 8. Commits on this branch (PR #1)

1. **Reconcile TRD to actual schema (v1.1) and scaffold contract layer** —
   `trd.md` v1.1 + `models/schemas.py`, `utils/csv_loader.py`,
   `utils/image_loader.py`.
2. **Implement 5-step pipeline with provider-agnostic vision-LLM factory** —
   LLM layer, pipeline, runner, eval harness, report, prompts, tests, docs.
