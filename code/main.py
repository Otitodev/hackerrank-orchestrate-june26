"""Entry point: run the evidence-review pipeline over claims.csv -> output.csv.

Usage:
    python code/main.py [--input PATH] [--output PATH] [--mock]
                        [--provider anthropic|openai|gemini|mock] [--model ID]
                        [--mode single|two_pass] [--limit N]

With no provider/key, it falls back to the deterministic mock so the wiring runs
offline. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY / GOOGLE_API_KEY) for a real run.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from utils.env import load_env_file  # noqa: E402

load_env_file()  # pick up code/.env before provider auto-detection

from models.schemas import OUTPUT_COLUMNS, IssueType  # noqa: E402
from pipeline import Refs  # noqa: E402
from pipeline.orchestrator import process_claim  # noqa: E402
from utils.csv_loader import (  # noqa: E402
    DATASET_DIR,
    load_claims,
    load_requirements,
    load_user_history,
)
from utils.llm import make_client  # noqa: E402
from utils.logger import setup_logger  # noqa: E402


def build_refs() -> Refs:
    requirements = load_requirements()
    history = load_user_history()
    families = sorted(
        {i.value for i in IssueType} | {r.applies_to for r in requirements}
    )
    return Refs(history=history, requirements=requirements, allowed_families=families)


async def run(args) -> int:
    log = setup_logger(args.log)
    provider = "mock" if args.mock else args.provider
    client = make_client(provider=provider, model=args.model, concurrency=args.concurrency)
    log.info("provider=%s model=%s mode=%s", client.config.provider, client.config.model, args.mode)

    claims = load_claims(args.input)
    if args.limit:
        claims = claims[: args.limit]
    refs = build_refs()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for i, claim in enumerate(claims, 1):
            try:
                row = await process_claim(claim, refs, client, mode=args.mode)
                writer.writerow(row.to_csv_dict())
                fh.flush()  # incremental write for crash recovery
                written += 1
            except Exception as exc:  # noqa: BLE001
                log.error("claim %d (user=%s) failed: %s", i, claim.user_id, exc)
            if i % 10 == 0:
                log.info("processed %d/%d claims", i, len(claims))

    u = client.usage
    log.info(
        "done: %d rows -> %s | calls=%d in_tok=%d out_tok=%d images=%d est_cost=$%.4f",
        written, out_path, u.calls, u.input_tokens, u.output_tokens, u.images, u.cost(client.config),
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Multi-modal evidence review")
    p.add_argument("--input", default=str(DATASET_DIR / "claims.csv"))
    p.add_argument("--output", default=str(CODE_DIR.parent / "output.csv"))
    p.add_argument("--provider", default=None, help="anthropic|openai|gemini|mock")
    p.add_argument("--model", default=None, help="override model id")
    p.add_argument("--mock", action="store_true", help="force the offline mock client")
    p.add_argument("--mode", default="single", choices=["single", "two_pass"])
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--log", default=str(CODE_DIR.parent / "run.log"))
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
