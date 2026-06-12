"""paper-review — local collaborative paper review service."""

import os
from pathlib import Path

__version__ = "0.1.0"

# Service root: code + per-paper review data (data dirs are gitignored).
# Override with PAPER_REVIEWS_ROOT for non-standard locations.
SERVICE_ROOT = Path(
    os.environ.get("PAPER_REVIEWS_ROOT", "~/Projects/paper-review-service")
).expanduser()
VELOG_DRAFTS_DIR = Path.home() / "Documents" / "velog-vault" / "drafts"
DEFAULT_PORT = 7300
