# Evaluation Report — Multi-Modal Evidence Review

This report covers the evaluation methodology, a two-strategy comparison, and the
operational analysis (model calls, tokens, cost, latency, rate-limit handling)
required by `problem_statement.md`.

> Reproduce: `python code/evaluation/main.py --compare` (real metrics, needs a
> provider key) or `python code/evaluation/main.py --mock --compare` (offline
> wiring + cost/call comparison). Results are written to `metrics.json`.

## 1. Methodology

The system is scored on the labeled `dataset/sample_claims.csv` (20 rows) before
running on `dataset/claims.csv` (44 rows). Predictions are compared field-by-field
to the expected labels:

| Metric | Field | Weight |
|---|---|---|
| Decision accuracy | `claim_status` | **primary** |
| Evidence-gate accuracy | `evidence_standard_met`, `valid_image` | secondary |
| Severity accuracy | `severity` | secondary |
| Risk-flag precision / recall | `risk_flags` (set overlap) | secondary |
| Justification quality | `claim_status_justification` | qualitative (AI judge) |

The harness also prints a `claim_status` confusion matrix to expose failure
patterns (e.g. `contradicted → supported` false positives), which guide prompt
tuning of Step 5.1 (parser) and Step 5.5 (synthesiser). Per the overfitting
guard, only prompt wording is tuned — never claim-specific answers.

## 1a. Measured results (real run)

Measured on `dataset/sample_claims.csv` (n=20), provider `anthropic`, model
`claude-sonnet-4-6`, single strategy, `temperature=0`:

| Metric | Score |
|---|---|
| `claim_status` accuracy | 0.50 |
| `evidence_standard_met` accuracy | 0.65 |
| `valid_image` accuracy | 0.90 |
| `severity` accuracy | 0.25 |
| risk-flag precision / recall | 0.42 / 0.86 |
| sample-set cost | $0.33 (63 calls, 29 images) |

Confusion (`claim_status`): the dominant error is over-routing to
`not_enough_information` — `supported→not_enough_information` (4) and
`contradicted→not_enough_information` (3) — i.e. the evidence gate
(`evidence_standard_met`) is too strict, which also caps `claim_status` accuracy.
Risk-flag **recall is strong (0.86)** after wiring the full perceptual-flag set
and the `manual_review_required` escalation rule; **precision (0.42) is the next
lever** — the VLM over-asserts `non_original_image` / `claim_mismatch` on these
stock-like dataset images, which then over-triggers manual review. Both are
prompt-tuning / threshold opportunities, not structural gaps.

Full test run (`dataset/claims.csv`, n=44): **153 model calls, 82 images,
$0.84** measured.

## 2. Two-strategy comparison

The required comparison is **single structured call per image** (primary) vs
**two-pass blind→targeted** per image. Both share every other component; only
Step 5.2 changes (`--mode single` vs `--mode two_pass`).

| Strategy | Image calls (test set) | Total calls | Rationale |
|---|---|---|---|
| **single** (chosen) | 82 | **170** | One call yields observation + verdict. Halves VLM cost; the model still observes before judging within one structured response. |
| two_pass | 164 | 252 | Blind observation then targeted judgment. Strictly separates perception from anchoring, but doubles image-call cost for marginal benefit on this dataset. |

Measured on the sample set (offline mock, wiring + call counts): single = **69
calls**, two_pass = **98 calls** for the same 29 images — the +29 calls are the
extra blind/targeted split. Accuracy is identical under the mock (it is a
structural stub); run with a real provider to compare true accuracy.

**Final strategy for `output.csv`: `single`.** It meets the design goal of
minimizing repeated calls (the problem explicitly rewards this) while preserving
the perception-before-judgment ordering inside one response. `two_pass` remains
available for ablation.

A third axis is available for free via the provider-agnostic client: the same
prompts run on `claude-sonnet-4-6`, `gpt-4o`, or `gemini-1.5-pro` by changing one
env var, enabling cross-provider cost/quality comparison without code changes.

## 3. Operational analysis

### 3.1 Model calls

Per claim (single strategy): **1 parser + N image + 1 synthesiser**, where N is
the number of submitted images. Evidence and risk steps are rule-based (0 calls).

| Dataset | Claims | Images | Calls (single) | Calls (two_pass) |
|---|---|---|---|---|
| sample | 20 | 29 | 69 | 98 |
| **test (`claims.csv`)** | 44 | 82 | **170** | 252 |

Test image distribution: 13 claims × 1 img, 24 × 2 img, 7 × 3 img = 82 images.

> **Measured:** the real test run made **153 calls** (not the 170 upper bound):
> the synthesiser is skipped on rows where the evidence gate fails (NEI), so
> calls = 44 parser + 82 image + 27 synthesiser. Sample run = 63 calls.

### 3.2 Token & cost estimate (test set, single strategy)

Rough per-call estimates (Anthropic vision, ~1568px images):

| Call type | Count | ~input tok | ~output tok |
|---|---|---|---|
| Claim parser | 44 | ~350 | ~120 |
| Image analyser | 82 | ~1,900 (incl. ~1,600 image) | ~200 |
| Synthesiser | 44 | ~550 | ~200 |
| **Total** | **170** | **~195K** | **~30K** |

**Pricing assumptions** (USD per 1M tokens):

| Provider | Model | Input | Output | Source |
|---|---|---|---|---|
| Anthropic | `claude-sonnet-4-6` | $3.00 | $15.00 | authoritative |
| OpenAI | `gpt-4o` | $2.50 | $10.00 | documented assumption |
| Google | `gemini-1.5-pro` | $1.25 | $5.00 | documented assumption |

Estimated cost on `claude-sonnet-4-6` (single): `0.195M × $3 + 0.030M × $15 ≈`
**$1.04** for the full 44-row test set (~$0.47 for the 20-row sample).
Two-pass adds ~80 image calls → roughly **$1.6–1.8**. Image tokens dominate, so
provider/model choice and image down-sizing are the main cost levers. (Image
token accounting differs per provider; treat cross-provider figures as estimates.)

### 3.3 Latency / runtime

Within a claim, all images are analysed concurrently (`asyncio.gather`); claims
run sequentially with incremental writes. With a concurrency cap of 5 and
~1–3 s/call, the test set completes in roughly **3–6 minutes** on the single
strategy (two_pass ~1.5×). The exact figure depends on provider latency and
rate-limit tier.

### 3.4 TPM/RPM, batching, throttling, caching, retries

- **Concurrency cap:** a shared `asyncio.Semaphore(5)` bounds in-flight calls
  (configurable via `--concurrency`), keeping well under typical RPM limits.
- **Retries:** every call retries up to 3× with exponential backoff + jitter on
  any transient failure (covers 429/5xx).
- **Throttling:** claims are processed sequentially; only intra-claim image calls
  fan out — naturally smoothing request bursts.
- **Caching / repeated calls:** the two LLM steps are text-only and the image
  step is one call per image (no re-analysis), minimizing repeated work. The
  evidence and risk layers are pure rules (0 tokens). Identical image bytes could
  be content-hash cached to skip re-encoding/re-analysis across runs — a
  straightforward extension.
- **Incremental writes:** rows are flushed to `output.csv` as each claim
  completes, so an interrupted run preserves completed predictions.
- **Determinism:** `temperature=0` (where the model supports it) for reproducible
  extraction and verdicts.

## 4. Notes & limitations

- Mock-mode metrics validate wiring only; true accuracy requires a provider key.
- Severity and image-derived risk flags (blur, wrong-object, manipulation) depend
  on real VLM perception and are not exercised by the offline mock.
- History-derived flags (`user_history_risk`, `manual_review_required`) are read
  directly from `user_history.history_flags`, so they score correctly even offline.
