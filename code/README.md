# Multi-Modal Evidence Review — Solution

Verifies damage claims (car / laptop / package) from submitted images, a claim
conversation, user history, and minimum-evidence guidance. For each row in
`dataset/claims.csv` it produces one row in `output.csv` with the exact 14-column
schema from `problem_statement.md`.

See `../trd.md` (v1.1) for the full design rationale.

## Architecture (5-step pipeline)

```
claims.csv + images
   │
   ├─ 5.1 Claim Parser        (LLM, text)      → structured claim
   ├─ 5.2 Image Analyser      (VLM, per image) → observation + verdict   [async]
   ├─ 5.3 Evidence Checker    (rules)          → valid_image / evidence_standard_met
   ├─ 5.4 Risk Assessor       (rules)          → risk_flags
   └─ 5.5 Decision Synthesiser(LLM, text)      → claim_status / issue_type / …
                                                → output.csv (14 cols)
```

Image analysis uses **one structured call per image** (primary strategy);
two-pass blind→targeted is available via `--mode two_pass` for the eval
comparison. The decision ladder (TRD §6) enforces the evidence gate and
object/part mismatch as rules before the synthesiser runs.

## Provider-agnostic LLM layer

The pipeline depends only on the abstract `LLMClient` (`utils/llm/`). Swappable
adapters: **anthropic** (default `claude-sonnet-4-6`), **openai** (`gpt-4o`),
**gemini** (`gemini-1.5-pro`), and a deterministic **mock** for offline runs.
Vendor SDKs are imported lazily, so you only install the one(s) you use.

Provider is chosen by `--provider`/`LLM_PROVIDER`, else auto-detected from
whichever API key is set, else falls back to `mock`. Override the model with
`--model`/`LLM_MODEL`.

## Install

```bash
pip install -r code/requirements.txt          # core + anthropic
# optional: pip install openai google-generativeai
```

## Run

```bash
# Offline wiring check (no API key) — produces a structurally valid output.csv
python code/main.py --mock --input dataset/sample_claims.csv --output /tmp/out.csv

# Real run on the test set (set ONE key; provider auto-detected)
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY / GOOGLE_API_KEY
python code/main.py                 # dataset/claims.csv -> output.csv

# Pick a provider/model explicitly
LLM_PROVIDER=openai LLM_MODEL=gpt-4o python code/main.py
```

Secrets are read from environment variables only. Rows are written
incrementally to `output.csv` (crash-safe); a runtime `run.log` is written
alongside.

## Evaluate

```bash
python code/evaluation/main.py --mock --compare     # offline wiring + strategy compare
python code/evaluation/main.py                       # real metrics (needs a key)
```

Scores predictions against the labeled `dataset/sample_claims.csv`
(claim_status accuracy primary; plus severity, evidence/valid-image, and
risk-flag precision/recall), prints a confusion matrix, and writes
`evaluation/metrics.json`. `--compare` runs both `single` and `two_pass`.
See `evaluation/evaluation_report.md` for the operational analysis.

## Test

```bash
python -m pytest code/tests/ -q        # full pipeline on the mock, offline
```

## Layout

```
code/
├── main.py                  # runner: claims.csv -> output.csv
├── models/schemas.py        # Pydantic enums + OutputRow (14-col contract)
├── pipeline/                # the 5 steps + orchestrator (decision ladder)
├── prompts/                 # provider-neutral prompt templates
├── utils/
│   ├── csv_loader.py        # indexed reference data + quote-all writer
│   ├── image_loader.py      # path resolution, base64 + resize
│   ├── logger.py            # run.log setup
│   └── llm/                 # provider-agnostic factory + adapters + mock
├── evaluation/main.py       # scoring harness + strategy comparison
├── evaluation/evaluation_report.md
└── tests/test_pipeline_mock.py
```
