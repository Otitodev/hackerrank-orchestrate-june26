"""The five-step evidence-review pipeline (TRD v1.1 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from models.schemas import Requirement, UserHistory

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a prompt template by stem from ``code/prompts/``."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


@dataclass
class Refs:
    """Reference data loaded once at startup and shared across claims."""

    history: Dict[str, UserHistory]
    requirements: List[Requirement]
    allowed_families: List[str]
