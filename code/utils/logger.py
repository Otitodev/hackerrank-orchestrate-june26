"""Logging setup. Writes to ``run.log`` alongside the output, plus the console.

Note: this is the *runtime* log for the claim-verification system, not the
AGENTS.md chat-transcript log.
"""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logger(log_path: Path | str = "run.log", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("evidence_review")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(Path(log_path), encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    logger.propagate = False
    return logger
