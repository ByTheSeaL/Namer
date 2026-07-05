"""Tiny JSON preferences store (last model, recently chosen models)."""

import json

from .paths import config_dir

PREFS_FILE = config_dir() / "prefs.json"
MAX_RECENT = 5


def load() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save(prefs: dict) -> None:
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(json.dumps(prefs, indent=2))
