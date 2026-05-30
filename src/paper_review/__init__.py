"""paper-review — local collaborative paper review service."""

from pathlib import Path

__version__ = "0.1.0"

SERVICE_ROOT = Path.home() / ".paper-reviews"
VELOG_DRAFTS_DIR = Path.home() / "Documents" / "velog-vault" / "drafts"
DEFAULT_PORT = 7300
