"""paper-review — local collaborative paper review service."""

import os
import sys
from pathlib import Path

__version__ = "2.9.0"

# Service root: code + per-paper review data (data dirs are gitignored).
# Source installs resolve to THIS checkout, so cloning anywhere works; the
# frozen .app keeps the legacy location (its bundle is read-only, and existing
# installs already keep their library there). PAPER_REVIEWS_ROOT overrides both.
_LEGACY_ROOT = "~/Projects/paper-review-service"


def _resolve_service_root() -> Path:
    env = os.environ.get("PAPER_REVIEWS_ROOT")
    if env:
        return Path(env).expanduser()
    if not getattr(sys, "frozen", False):
        repo = Path(__file__).resolve().parents[2]  # src/paper_review/ → repo
        if (repo / "pyproject.toml").exists():
            return repo
    return Path(_LEGACY_ROOT).expanduser()


SERVICE_ROOT = _resolve_service_root()
# Publish output dir — configurable per user (Settings UI / settings.json /
# PAPER_REVIEW_DRAFTS_DIR env). Import get_drafts_dir() for the live value;
# this constant is only the legacy default.
VELOG_DRAFTS_DIR = Path.home() / "Documents" / "velog-vault" / "drafts"
DEFAULT_PORT = 7300
