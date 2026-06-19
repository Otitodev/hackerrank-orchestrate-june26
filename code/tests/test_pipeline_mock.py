"""End-to-end wiring test using the offline mock client (no API key needed)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

from models.schemas import IssueType, OUTPUT_COLUMNS, OutputRow  # noqa: E402
from pipeline import Refs  # noqa: E402
from pipeline.orchestrator import process_claim  # noqa: E402
from utils.csv_loader import (  # noqa: E402
    load_requirements,
    load_user_history,
    sample_claim_inputs,
)
from utils.llm import make_client  # noqa: E402


def _refs() -> Refs:
    reqs = load_requirements()
    fams = sorted({i.value for i in IssueType} | {r.applies_to for r in reqs})
    return Refs(load_user_history(), reqs, fams)


def test_pipeline_runs_on_full_sample_offline():
    client = make_client(provider="mock")
    refs = _refs()
    inputs = sample_claim_inputs()
    assert len(inputs) == 20

    async def _run():
        return [await process_claim(c, refs, client, mode="single") for c in inputs]

    rows = asyncio.run(_run())
    assert len(rows) == 20
    for row in rows:
        assert isinstance(row, OutputRow)
        d = row.to_csv_dict()
        assert list(d.keys()) == OUTPUT_COLUMNS  # exact 14-col contract
        assert d["claim_status"] in {"supported", "contradicted", "not_enough_information"}
        assert d["valid_image"] in {"true", "false"}
        assert d["severity"] in {"none", "low", "medium", "high", "unknown"}


def test_make_client_defaults_to_mock_without_keys(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(env, raising=False)
    client = make_client()
    assert client.config.provider == "mock"


if __name__ == "__main__":
    test_pipeline_runs_on_full_sample_offline()
    print("OK: pipeline ran on all 20 sample rows with valid 14-column output")
