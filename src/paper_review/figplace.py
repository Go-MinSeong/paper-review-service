"""Put a paper's own figures into the review, where the text talks about them.

Figures were extracted at ingest and then sat in a modal waiting to be inserted
by hand, one at a time, into every section. The placement they need is already
in the data: each figure records the section that references it
(`ref_in_section`), and the translated prose names the figure ("Figure 3",
"그림 3"). So this is arithmetic, not judgement — no model call, and a wrong id
is impossible because the ids come from the file.

Tables are left alone: they are extracted as HTML with no image bytes, so an
`![](…)` pointing at one renders broken. They keep the manual path, which
rasterizes them in the browser first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# A figure belongs in the explanation: the source excerpt above it is a quote,
# and the notes below are commentary. Sections come in two shapes depending on
# when they were written.
_BODY_STARTS = ("**핵심 해설**", "**Claude 1차 번역**")
# The explanation itself contains bold sub-headings ("**무엇을 하는가**"), so the
# end has to be a known marker — treating any bold line as the end put figures
# at the very top of the explanation instead of after it.
_BODY_END = re.compile(r"\n\*\*(?:Claude Reader's Notes|Reader's Notes|요약)\*\*")


def _norm(s: str) -> str:
    """Section ids carry the numbering ("2-1-overview"), ref_in_section does not."""
    return re.sub(r"^[\d\-.]+", "", (s or "").strip().lower()).strip("-")


def _load(paper_dir: Path) -> list[dict]:
    files = sorted(paper_dir.glob("*_figures.json"))
    if not files:
        return []
    try:
        data = json.loads(files[0].read_text())
    except Exception:
        return []
    items = data if isinstance(data, list) else data.get("figures", [])
    return [f for f in items if isinstance(f, dict)]


def for_section(paper_dir: Path, section_id: str) -> list[dict]:
    """The servable figures this section references, in file order."""
    want = _norm(section_id)
    if not want:
        return []
    return [
        f
        for f in _load(paper_dir)
        if f.get("data_uri") and _norm(f.get("ref_in_section", "")) == want
    ]


def _mention(label: str) -> re.Pattern | None:
    """Match how the prose names this item: Figure 3 / Fig. 3 / 그림 3 / Table 3.

    The kind has to match too — keying on the number alone put "Table 3" after
    the paragraph that discussed Figure 3.
    """
    m = re.search(r"(\d+)", label or "")
    if not m:
        return None
    n = m.group(1)
    words = (
        r"Table|표"
        if re.match(r"\s*(table|표)", label or "", re.I)
        else r"Figure|Fig\.?|그림"
    )
    return re.compile(rf"(?:{words})\s*{n}(?!\d)", re.I)


def _markdown(slug: str, fig: dict) -> str:
    """Same shape the Figure-삽입 button produces, so publish sees no difference."""
    label = (fig.get("label") or "figure").replace("[", "").replace("]", "")
    cap = (fig.get("caption_ko") or fig.get("caption_en") or "").strip()
    out = f"![{label}](/paper/{slug}/fig/{fig['id']})"
    return out + ("\n" + cap if cap else "")


def insert(text: str, heading: str, slug: str, figs: list[dict]) -> str:
    """Return `text` with `figs` placed inside the given section's explanation.

    A figure the prose names goes right after that paragraph; the rest go at the
    end of the explanation. Figures already present anywhere in the workbench are
    skipped, so re-running analyze never duplicates one.
    """
    figs = [f for f in figs if f"/fig/{f['id']})" not in text]
    if not figs:
        return text

    start = text.find(f"### {heading}")
    if start < 0:
        return text
    nxt = text.find("\n### ", start + 1)
    end = nxt if nxt >= 0 else len(text)
    block = text[start:end]

    body_at = -1
    for marker in _BODY_STARTS:
        at = block.find(marker)
        if at >= 0:
            body_at = at + len(marker)
            break
    if body_at < 0:
        return text
    tail = _BODY_END.search(block[body_at:])
    body_end = body_at + (tail.start() if tail else len(block) - body_at)
    body = block[body_at:body_end]

    paras = body.split("\n\n")
    trailing = []
    for fig in figs:
        pat = _mention(fig.get("label", ""))
        at = None
        if pat:
            at = next(
                (i for i, p in enumerate(paras) if p.strip() and pat.search(p)), None
            )
        md = _markdown(slug, fig)
        if at is None:
            trailing.append(md)
        else:
            paras.insert(at + 1, md)
    body = "\n\n".join(paras + trailing)
    return text[:start] + block[:body_at] + body + block[body_end:] + text[end:]


def place(paper_dir: Path, heading: str) -> int:
    """Insert this section's figures into workbench.md. Returns how many landed."""
    wb = paper_dir / "workbench.md"
    if not wb.exists():
        return 0
    text = wb.read_text()
    start = text.find(f"### {heading}")
    if start < 0:
        return 0
    m = re.search(r"<!-- section_id: ([^|]+)\|", text[start:])
    figs = for_section(paper_dir, m.group(1).strip()) if m else []
    if not figs:
        return 0
    out = insert(text, heading, paper_dir.name, figs)
    if out == text:
        return 0
    wb.write_text(out)
    return sum(
        1 for f in figs if f"/fig/{f['id']})" in out and f"/fig/{f['id']})" not in text
    )
