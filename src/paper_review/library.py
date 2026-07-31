"""Where papers live on disk.

Papers used to sit directly in the service root, so a library of a hundred
turned the project folder into a wall of slugs mixed in with the source tree.
They now live under `papers/<status>/<slug>/` and move as their status changes,
so the filesystem shows the same shape the gallery does.

Everything resolves through here: `paper_dir()` finds a paper wherever it is
(including the old flat layout, so nothing breaks before a migration runs), and
`move_to_status()` is the only thing that relocates one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PAPERS_DIRNAME = "papers"
# Folder names ARE the status values — no mapping table to drift out of sync.
STATUSES = ("to_read", "in_progress", "review_done", "exported", "archived")
DEFAULT_STATUS = "to_read"


def _root() -> Path:
    """Resolved on each call, not bound at import: the service root moves under
    tests and PAPER_REVIEWS_ROOT, and a stale binding would silently point the
    whole library at the wrong place."""
    import paper_review

    return paper_review.SERVICE_ROOT


def papers_root(root: Path | None = None) -> Path:
    return (root or _root()) / PAPERS_DIRNAME


def status_dir(status: str, root: Path | None = None) -> Path:
    """Folder for a status. Unknown values fall back to the default rather than
    creating junk directories from a typo or a future status."""
    s = status if status in STATUSES else DEFAULT_STATUS
    return papers_root(root) / s


def _is_paper(d: Path) -> bool:
    return d.is_dir() and (d / "workbench.md").exists()


def iter_papers(root: Path | None = None):
    """Every paper folder, new layout first, then any left in the flat one."""
    seen: set[str] = set()
    pr = papers_root(root)
    if pr.is_dir():
        for status in sorted(pr.iterdir()):
            if not status.is_dir() or status.name.startswith((".", "_")):
                continue
            for d in sorted(status.iterdir()):
                if _is_paper(d) and d.name not in seen:
                    seen.add(d.name)
                    yield d
    base = root or _root()
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.name in (PAPERS_DIRNAME,) or d.name.startswith((".", "_")):
                continue
            if _is_paper(d) and d.name not in seen:
                seen.add(d.name)
                yield d


def paper_dir(slug: str, root: Path | None = None) -> Path | None:
    """Locate a paper by slug, wherever it currently sits."""
    base = root or _root()
    for status in STATUSES:
        p = papers_root(root) / status / slug
        if p.is_dir():
            return p
    flat = base / slug  # pre-migration layout
    if flat.is_dir():
        return flat
    # a status folder we don't know about (hand-made, or from a newer version)
    pr = papers_root(root)
    if pr.is_dir():
        for status in pr.iterdir():
            p = status / slug
            if status.is_dir() and p.is_dir():
                return p
    return None


def new_paper_dir(
    slug: str, status: str = DEFAULT_STATUS, root: Path | None = None
) -> Path:
    """Path for a paper being created (does not create it)."""
    return status_dir(status, root) / slug


def move_to_status(slug: str, status: str, root: Path | None = None) -> Path | None:
    """Move a paper into its status folder. Returns the new path, or None if the
    paper is gone. A move is skipped (not failed) when the destination exists —
    losing a review to a rename is worse than a folder in the wrong place."""
    src = paper_dir(slug, root)
    if src is None:
        return None
    dest = status_dir(status, root) / slug
    if src == dest:
        return src
    if dest.exists():
        return src
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError:  # different filesystem
        shutil.move(str(src), str(dest))
    return dest


def migrate(root: Path | None = None, is_busy=None) -> dict:
    """Move flat-layout papers into papers/<status>/.

    `is_busy(slug)` lets the caller keep a paper that a job is currently running
    in — moving it out from under a `claude` process whose cwd it is would break
    that run. Those get picked up by the next migration or status change.
    """
    base = root or _root()
    moved, skipped = [], []
    if not base.is_dir():
        return {"moved": moved, "skipped": skipped}
    from .workbench import read_status

    for d in sorted(base.iterdir()):
        if d.name == PAPERS_DIRNAME or d.name.startswith((".", "_")):
            continue
        if not _is_paper(d):
            continue
        if is_busy and is_busy(d.name):
            skipped.append(d.name)
            continue
        wb = d / "workbench.md"
        status = read_status(wb) or DEFAULT_STATUS
        dest = status_dir(status, root) / d.name
        if dest.exists():
            skipped.append(d.name)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            d.rename(dest)
            moved.append((d.name, status))
        except OSError:
            skipped.append(d.name)
    return {"moved": moved, "skipped": skipped}
