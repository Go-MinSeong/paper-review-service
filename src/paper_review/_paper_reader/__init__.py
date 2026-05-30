"""Vendored paper-reader-v8 (https://...)

Original scripts live under scripts/. We invoke them as subprocesses with
explicit --out-dir args, so the hardcoded /mnt/user-data/outputs and /tmp/papers
paths from the original are bypassed.
"""

from pathlib import Path

PAPER_READER_ROOT = Path(__file__).parent
SCRIPTS_DIR = PAPER_READER_ROOT / "scripts"
ASSETS_DIR = PAPER_READER_ROOT / "assets"
REFERENCES_DIR = PAPER_READER_ROOT / "references"
AGENTS_DIR = PAPER_READER_ROOT / "assets" / "agents"
VIEWER_TEMPLATE = ASSETS_DIR / "viewer-template.html"
