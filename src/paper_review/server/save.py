"""POST /papers/save — add a paper to the reading list (metadata only).

Doesn't extract body, doesn't fetch figures. Just enough metadata so the user
can see it in the gallery, tag it, and decide later whether to fully analyze.
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from pydantic import BaseModel

from .. import SERVICE_ROOT


ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class ArxivMeta:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str  # ISO date


class SaveBody(BaseModel):
    source: str  # arXiv URL or ID
    tags: list[str] = []
    category: str | None = None


def _extract_arxiv_id(source: str) -> str:
    s = source.strip()
    # https://arxiv.org/abs/2410.24164 or .pdf or with version
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", s)
    if m:
        return m.group(1)
    # raw id like "2410.24164" or "2410.24164v2"
    m = re.match(r"^(\d{4}\.\d{4,5})(?:v\d+)?$", s)
    if m:
        return m.group(1)
    raise HTTPException(400, f"can't parse arXiv id from {source!r}")


def _fetch_arxiv_meta(arxiv_id: str) -> ArxivMeta:
    url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "paper-review/0.1"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                xml = r.read().decode("utf-8", "replace")
            break
        except Exception as e:
            last_err = e
            import time as _t
            _t.sleep(1.5 * (attempt + 1))
    else:
        raise HTTPException(502, f"arxiv fetch failed after 3 tries: {last_err}")
    root = ET.fromstring(xml)
    entry = root.find(f"{ATOM_NS}entry")
    if entry is None:
        raise HTTPException(404, f"arxiv id {arxiv_id!r} not found")
    title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
    title = re.sub(r"\s+", " ", title)
    abstract = (entry.findtext(f"{ATOM_NS}summary") or "").strip()
    abstract = re.sub(r"\s+", " ", abstract)
    published = (entry.findtext(f"{ATOM_NS}published") or "")[:10]
    authors = [
        (a.findtext(f"{ATOM_NS}name") or "").strip()
        for a in entry.findall(f"{ATOM_NS}author")
    ]
    authors = [a for a in authors if a]
    return ArxivMeta(
        arxiv_id=arxiv_id, title=title, authors=authors,
        abstract=abstract, published=published,
    )


def _make_slug(arxiv_id: str) -> str:
    return arxiv_id  # arxiv id is unique + URL-safe


def _render_to_read_workbench(meta: ArxivMeta, *, category: str, tags: list[str]) -> str:
    slug = _make_slug(meta.arxiv_id)
    title_en = meta.title.replace('"', '\\"')
    paper_url = f"https://arxiv.org/abs/{meta.arxiv_id}"
    today = date.today().isoformat()
    tags_str = ", ".join(tags) if tags else ""
    authors_short = ", ".join(meta.authors[:3])
    if len(meta.authors) > 3:
        authors_short += " 외"

    parts: list[str] = [
        "---",
        f"slug: {slug}",
        f'title_en: "{title_en}"',
        'title_ko: ""',
        f"paper_url: {paper_url}",
        f'category: "{category}"',
        f"tags: [{tags_str}]",
        f"review_started: {today}",
        "status: to_read",
        "---",
        "",
        f"# {meta.title} — Reading list",
        "",
        "## 논문 정보",
        "",
        f"- **저자**: {authors_short}" if authors_short else "",
        f"- **발표**: {meta.published}" if meta.published else "",
        f"- **링크**: {paper_url}",
        f"- **분류**: {category or '_(미정)_'}",
        "",
        "## Abstract",
        "",
        meta.abstract or "_(abstract 없음)_",
        "",
        "---",
        "",
        "_이 paper는 reading list에만 저장된 상태입니다. detail 페이지에서 **▶ Analyze** 버튼을 누르면 본문·figures 추출과 분석이 시작됩니다._",
        "",
    ]
    return "\n".join(p for p in parts if p is not None)


async def save_paper(body: SaveBody) -> dict:
    arxiv_id = _extract_arxiv_id(body.source)
    meta = await asyncio.get_event_loop().run_in_executor(None, _fetch_arxiv_meta, arxiv_id)
    slug = _make_slug(arxiv_id)
    paper_dir = SERVICE_ROOT / slug
    if paper_dir.exists() and (paper_dir / "workbench.md").exists():
        # Already exists — just bump tags if requested
        if body.tags:
            from .tags import _set_tags_in_text  # forward import
            wb = paper_dir / "workbench.md"
            wb.write_text(_set_tags_in_text(wb.read_text(), body.tags))
        return {"slug": slug, "already_existed": True}
    paper_dir.mkdir(parents=True, exist_ok=True)
    wb_text = _render_to_read_workbench(
        meta, category=body.category or "", tags=body.tags,
    )
    (paper_dir / "workbench.md").write_text(wb_text)
    return {"slug": slug, "already_existed": False}
