"""User-level settings (~/.config/paper-review/settings.json).

Keeps machine-specific paths (e.g. the user's Obsidian/velog vault) out of the
code so other people can point the tool at their own vault from the Settings UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_PATH = Path.home() / ".config" / "paper-review" / "settings.json"
DEFAULT_DRAFTS_DIR = Path.home() / "Documents" / "velog-vault" / "drafts"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2))


def get_drafts_dir() -> Path:
    """Publish output dir: env override → settings.json → legacy default."""
    env = os.environ.get("PAPER_REVIEW_DRAFTS_DIR")
    if env:
        return Path(env).expanduser()
    s = load_settings().get("drafts_dir")
    if s:
        return Path(s).expanduser()
    return DEFAULT_DRAFTS_DIR
