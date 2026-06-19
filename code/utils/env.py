"""Minimal, dependency-free ``.env`` loader.

The pipeline reads secrets from environment variables only (per AGENTS.md §6.2).
For local runs we also support a ``code/.env`` file so keys never have to be
exported by hand. This avoids a hard dependency on ``python-dotenv``.

Lines are ``KEY=VALUE`` (optionally ``export KEY=VALUE``); blank lines and
``#`` comments are ignored; surrounding single/double quotes are stripped. By
default, values in the file take precedence over any pre-existing environment
variable (so a stale shell value can't silently shadow the file the user just
edited). Never logs values.
"""

from __future__ import annotations

import os
from pathlib import Path

# code/utils/env.py -> code/.env
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path | str = DEFAULT_ENV_PATH, override: bool = True) -> list[str]:
    """Load ``KEY=VALUE`` pairs from ``path`` into ``os.environ``.

    Returns the list of key *names* that were set (for non-sensitive logging).
    Silently does nothing if the file is absent.
    """
    p = Path(path)
    if not p.is_file():
        return []

    loaded: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
