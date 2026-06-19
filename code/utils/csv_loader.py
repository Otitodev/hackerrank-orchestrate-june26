"""Load and index the reference CSVs, and write ``output.csv``.

Uses the stdlib ``csv`` module (no pandas dependency) for deterministic,
quote-everything output that matches the dataset's formatting. All reference
data is loaded once at startup.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List

from models.schemas import (
    OUTPUT_COLUMNS,
    ClaimInput,
    OutputRow,
    Requirement,
    UserHistory,
)

# Repo layout: this file is code/utils/csv_loader.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"


def _read_dicts(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_claims(path: Path | str = DATASET_DIR / "claims.csv") -> List[ClaimInput]:
    """Load input-only rows from ``claims.csv``."""
    return [ClaimInput(**row) for row in _read_dicts(Path(path))]


def load_sample_claims(
    path: Path | str = DATASET_DIR / "sample_claims.csv",
) -> List[dict]:
    """Load labeled sample rows as raw dicts.

    Returned dicts contain both the input columns and the expected-output
    columns, so the evaluation harness can compare predictions to ground truth.
    """
    return _read_dicts(Path(path))


def sample_claim_inputs(path: Path | str = DATASET_DIR / "sample_claims.csv") -> List[ClaimInput]:
    """The four input columns of the sample set, as :class:`ClaimInput`."""
    rows = load_sample_claims(path)
    return [
        ClaimInput(
            user_id=r["user_id"],
            image_paths=r["image_paths"],
            user_claim=r["user_claim"],
            claim_object=r["claim_object"],
        )
        for r in rows
    ]


def load_user_history(
    path: Path | str = DATASET_DIR / "user_history.csv",
) -> Dict[str, UserHistory]:
    """Index ``user_history.csv`` by ``user_id``."""
    index: Dict[str, UserHistory] = {}
    for row in _read_dicts(Path(path)):
        record = UserHistory(**row)
        index[record.user_id] = record
    return index


def load_requirements(
    path: Path | str = DATASET_DIR / "evidence_requirements.csv",
) -> List[Requirement]:
    """Load all requirement rules (kept as a list; matching is fuzzy/per-claim)."""
    return [Requirement(**row) for row in _read_dicts(Path(path))]


def select_requirements(
    requirements: Iterable[Requirement], claim_object: str
) -> List[Requirement]:
    """Requirements applicable to a claim: object-specific rows plus ``all`` rows.

    There is no numeric ``min_images``; ``applies_to`` is fuzzy text, so callers
    refine further (e.g. against the parsed issue family) when needed.
    """
    return [
        r for r in requirements
        if r.claim_object in (claim_object, "all")
    ]


def write_output(rows: Iterable[OutputRow], path: Path | str) -> int:
    """Write validated rows to ``output.csv`` (all fields quoted). Returns count."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=OUTPUT_COLUMNS, quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_dict())
            count += 1
    return count
