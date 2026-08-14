"""Remove sections that were never worth reviewing from existing workbenches.

The section index used to promote chapter titles with no body, table rows and
prompt-template list items to real sections; ingest no longer does (see
init_paper.write_sections_index), but papers taken in before that keep the
blocks. This recomputes the index from the source and drops the blocks that no
longer correspond to a section.

Answers live under "## Q&A", not inside a section block, so only generated
explanation is ever removed — and the workbench is snapshotted first.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_SCRIPT = Path(__file__).parent / "_paper_reader" / "scripts" / "init_paper.py"


def _index_rules():
    spec = importlib.util.spec_from_file_location("init_paper", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm(heading: str) -> str:
    """Workbench headings are markdown-escaped ("3\\. Method") — compare bare."""
    return re.sub(r"\s+", " ", heading.replace("\\", "")).strip().lower()


def live_headings(paper_dir: Path) -> set[str] | None:
    """Headings the current rules would keep, or None when there is no source."""
    src = list(paper_dir.glob("*source*.txt"))
    if not src:
        return None
    ip = _index_rules()
    text = src[0].read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    hits, total = ip.find_section_boundaries(text)
    hits, total = ip.cut_at_references(hits, lines, total)
    kept = ip.drop_bodyless(ip.drop_repeats(hits), lines, total)
    return {_norm(label) for _, label in kept}


def plan(paper_dir: Path) -> list[tuple[str, str, int]]:
    """[(heading, reason, written), ...] for blocks that no longer earn a section.

    `written` is how much explanation the block carries — removing one of those
    throws away real text (recoverable from .history), so the caller can show
    what the user is about to lose instead of deleting it quietly.
    """
    wb = paper_dir / "workbench.md"
    if not wb.exists():
        return []
    keep = live_headings(paper_dir)
    out = []
    for block in _blocks(wb.read_text()):
        heading = block.split("\n", 1)[0][4:].strip()
        body = block[4 + len(heading) :].strip()
        written = len(re.sub(r"<!--.*?-->", "", body, flags=re.S).strip())
        if not body:
            out.append((heading, "빈 제목", 0))
        elif keep is not None and _norm(heading) not in keep:
            out.append((heading, "섹션 아님", written))
    return out


def _blocks(text: str) -> list[str]:
    """The '### ' blocks inside '## 섹션별 리뷰'."""
    m = re.search(r"^## 섹션별 리뷰\s*$", text, re.M)
    if not m:
        return []
    rest = text[m.end() :]
    tail = re.search(r"\n## (?!섹션별)", rest)
    region = rest[: tail.start()] if tail else rest
    return [
        b for b in re.split(r"(?=^### )", region, flags=re.M) if b.startswith("### ")
    ]


def apply(paper_dir: Path) -> int:
    """Drop the planned blocks. Returns how many went. Snapshots first."""
    doomed = {h for h, _, _ in plan(paper_dir)}
    if not doomed:
        return 0
    wb = paper_dir / "workbench.md"
    text = wb.read_text()
    from .server.app import _keep_history

    _keep_history(wb)
    for block in _blocks(text):
        if block.split("\n", 1)[0][4:].strip() in doomed:
            text = text.replace(block, "", 1)
    wb.write_text(re.sub(r"\n{4,}", "\n\n\n", text))
    return len(doomed)
