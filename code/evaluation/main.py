"""Evaluation harness: run the pipeline on the labeled sample set and score it.

Compares predictions to expected labels on sample_claims.csv (primary metric:
claim_status accuracy) and can compare two strategies (single vs two_pass).
Writes metrics.json next to this file.

Usage:
    python code/evaluation/main.py [--mock] [--provider P] [--model ID]
                                   [--compare] [--mode single|two_pass]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

from models.schemas import LIST_SEP, NONE_SENTINEL  # noqa: E402
from pipeline.orchestrator import process_claim  # noqa: E402
from utils.csv_loader import (  # noqa: E402
    DATASET_DIR,
    load_sample_claims,
    sample_claim_inputs,
)
from utils.llm import make_client  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
SAMPLE = DATASET_DIR / "sample_claims.csv"


def _flag_set(value: str) -> set[str]:
    if not value or value == NONE_SENTINEL:
        return set()
    return {v for v in value.split(LIST_SEP) if v and v != NONE_SENTINEL}


async def evaluate(client, mode: str) -> dict:
    expected_rows = load_sample_claims(SAMPLE)
    inputs = sample_claim_inputs(SAMPLE)
    refs = _build_refs()

    n = len(inputs)
    correct = Counter()
    flag_tp = flag_fp = flag_fn = 0
    confusion = Counter()

    for claim, exp in zip(inputs, expected_rows):
        pred = await process_claim(claim, refs, client, mode=mode)
        d = pred.to_csv_dict()

        if d["claim_status"] == exp["claim_status"]:
            correct["claim_status"] += 1
        confusion[(exp["claim_status"], d["claim_status"])] += 1
        for field in ("severity", "evidence_standard_met", "valid_image"):
            if d[field] == exp[field]:
                correct[field] += 1

        pf, ef = _flag_set(d["risk_flags"]), _flag_set(exp["risk_flags"])
        flag_tp += len(pf & ef)
        flag_fp += len(pf - ef)
        flag_fn += len(ef - pf)

    precision = flag_tp / (flag_tp + flag_fp) if (flag_tp + flag_fp) else 0.0
    recall = flag_tp / (flag_tp + flag_fn) if (flag_tp + flag_fn) else 0.0
    u = client.usage
    return {
        "mode": mode,
        "provider": client.config.provider,
        "model": client.config.model,
        "n": n,
        "claim_status_accuracy": round(correct["claim_status"] / n, 3),
        "severity_accuracy": round(correct["severity"] / n, 3),
        "evidence_standard_met_accuracy": round(correct["evidence_standard_met"] / n, 3),
        "valid_image_accuracy": round(correct["valid_image"] / n, 3),
        "risk_flag_precision": round(precision, 3),
        "risk_flag_recall": round(recall, 3),
        "confusion_claim_status": {f"{k[0]}->{k[1]}": v for k, v in sorted(confusion.items())},
        "model_calls": u.calls,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "images": u.images,
        "est_cost_usd": round(u.cost(client.config), 4),
    }


def _build_refs():
    from pipeline import Refs
    from models.schemas import IssueType
    from utils.csv_loader import load_requirements, load_user_history

    requirements = load_requirements()
    families = sorted({i.value for i in IssueType} | {r.applies_to for r in requirements})
    return Refs(load_user_history(), requirements, families)


def _print(metrics: dict) -> None:
    print(f"\n=== {metrics['mode']} | {metrics['provider']}:{metrics['model']} (n={metrics['n']}) ===")
    print(f"  claim_status accuracy : {metrics['claim_status_accuracy']}")
    print(f"  severity accuracy     : {metrics['severity_accuracy']}")
    print(f"  evidence_std accuracy : {metrics['evidence_standard_met_accuracy']}")
    print(f"  valid_image accuracy  : {metrics['valid_image_accuracy']}")
    print(f"  risk_flag P / R       : {metrics['risk_flag_precision']} / {metrics['risk_flag_recall']}")
    print(f"  model calls / images  : {metrics['model_calls']} / {metrics['images']}")
    print(f"  est cost (USD)        : ${metrics['est_cost_usd']}")
    print(f"  confusion             : {metrics['confusion_claim_status']}")


async def run(args) -> int:
    provider = "mock" if args.mock else args.provider
    results = []
    modes = ["single", "two_pass"] if args.compare else [args.mode]
    for mode in modes:
        client = make_client(provider=provider, model=args.model)
        m = await evaluate(client, mode)
        _print(m)
        results.append(m)

    (EVAL_DIR / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {EVAL_DIR / 'metrics.json'}")
    if args.mock:
        print("NOTE: mock metrics validate wiring only; run with a real provider for true accuracy.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate the evidence-review pipeline")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--mode", default="single", choices=["single", "two_pass"])
    p.add_argument("--compare", action="store_true", help="run both single and two_pass")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
