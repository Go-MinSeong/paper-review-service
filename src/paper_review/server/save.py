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

from fastapi import HTTPException, UploadFile
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


def _download_arxiv_pdf(arxiv_id: str, dest: Path) -> bool:
    """Best-effort download of the arXiv PDF to dest. Returns True on success."""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "paper-review/0.1"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if data[:4] != b"%PDF":
                raise ValueError("not a PDF response")
            dest.write_bytes(data)
            return True
        except Exception:
            import time as _t
            _t.sleep(1.5 * (attempt + 1))
    return False


def _slug_from_filename(name: str) -> str:
    base = Path(name).stem
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
    return (slug or "paper")[:48]


def _looks_like_title(t: str) -> bool:
    if not t or len(t) < 5 or len(t) > 300:
        return False
    low = t.lower().strip()
    if low.endswith((".pdf", ".docx", ".doc", ".tex", ".dvi")):
        return False
    if "microsoft word" in low or low.startswith("untitled"):
        return False
    if "\n" in t or "\r" in t:
        return False
    return True


def _title_from_first_page(text: str) -> str | None:
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    if not lines:
        return None
    title = lines[0]
    # Skip a leading "arXiv:..." stamp
    if title.lower().startswith("arxiv:") and len(lines) > 1:
        title = lines[1]
    # Very short first line → likely a wrapped title; join with the next line
    if len(title) < 15 and len(lines) > 1:
        title = (title + " " + lines[1]).strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title[:300] if len(title) >= 5 else None


def _extract_pdf_meta(pdf_path: Path) -> tuple[str | None, list[str]]:
    """Best-effort (title, authors) from a PDF's metadata, else first page."""
    title: str | None = None
    authors: list[str] = []
    try:
        from pypdf import PdfReader
        m = PdfReader(str(pdf_path)).metadata
        if m:
            t = (m.title or "").strip()
            if _looks_like_title(t):
                title = re.sub(r"\s+", " ", t)
            a = (m.author or "").strip()
            if a:
                authors = [x.strip() for x in re.split(r"[;,]", a) if x.strip()]
    except Exception:
        pass
    if not title:
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(str(pdf_path))
            text = doc[0].get_textpage().get_text_range()
            title = _title_from_first_page(text)
        except Exception:
            pass
    return title, authors


def _unique_slug(slug: str) -> str:
    if not (SERVICE_ROOT / slug).exists():
        return slug
    i = 2
    while (SERVICE_ROOT / f"{slug}-{i}").exists():
        i += 1
    return f"{slug}-{i}"


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


def _render_pdf_to_read_workbench(
    *, title: str, category: str, tags: list[str], filename: str,
    authors: list[str] | None = None,
) -> str:
    today = date.today().isoformat()
    tags_str = ", ".join(tags) if tags else ""
    title_en = title.replace('"', '\\"')
    authors = authors or []
    authors_short = ", ".join(authors[:3]) + (" 외" if len(authors) > 3 else "")
    parts = [
        "---",
        f"slug: {_slug_from_filename(filename)}",
        f'title_en: "{title_en}"',
        'title_ko: ""',
        "paper_url: ",
        f'category: "{category}"',
        f"tags: [{tags_str}]",
        f"review_started: {today}",
        "status: to_read",
        f'source_pdf: "{filename}"',
        "---",
        "",
        f"# {title}",
        "",
        "## 논문 정보",
        "",
        f"- **저자**: {authors_short}" if authors_short else "",
        f"- **원본 파일**: {filename}",
        "- **링크**: _(로컬 PDF 업로드)_",
        f"- **분류**: {category or '_(미정)_'}",
        "",
        "---",
        "",
        "_이 paper는 로컬 PDF로 reading list에 저장되었습니다. 좌측 PDF는 바로 확인 가능하며, "
        "detail 페이지에서 **▶ Analyze** 를 누르면 본문·figures 추출과 분석이 시작됩니다._",
        "",
    ]
    return "\n".join(p for p in parts if p is not None)


async def save_paper(body: SaveBody) -> dict:
    arxiv_id = _extract_arxiv_id(body.source)
    meta = await asyncio.get_event_loop().run_in_executor(None, _fetch_arxiv_meta, arxiv_id)
    slug = _make_slug(arxiv_id)
    paper_dir = SERVICE_ROOT / slug
    if paper_dir.exists() and (paper_dir / "workbench.md").exists():
        # Already exists — just bump tags if requested, and backfill PDF if missing
        if body.tags:
            from .tags import _set_tags_in_text  # forward import
            wb = paper_dir / "workbench.md"
            wb.write_text(_set_tags_in_text(wb.read_text(), body.tags))
        pdf_dest = paper_dir / "original.pdf"
        pdf_ok = pdf_dest.exists()
        if not pdf_ok:
            pdf_ok = await asyncio.get_event_loop().run_in_executor(
                None, _download_arxiv_pdf, arxiv_id, pdf_dest
            )
        return {"slug": slug, "already_existed": True, "pdf_ok": pdf_ok}
    paper_dir.mkdir(parents=True, exist_ok=True)
    wb_text = _render_to_read_workbench(
        meta, category=body.category or "", tags=body.tags,
    )
    (paper_dir / "workbench.md").write_text(wb_text)
    # Archive the actual PDF so it's viewable in the reading list
    pdf_ok = await asyncio.get_event_loop().run_in_executor(
        None, _download_arxiv_pdf, arxiv_id, paper_dir / "original.pdf"
    )
    return {"slug": slug, "already_existed": False, "pdf_ok": pdf_ok}


async def save_pdf_paper(
    file: UploadFile, tags: list[str], category: str | None
) -> dict:
    """Save an uploaded PDF to the reading list (no ingest). Archives the file."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "must be a .pdf")
    filename = Path(file.filename).name
    slug = _unique_slug(_slug_from_filename(filename))
    paper_dir = SERVICE_ROOT / slug
    paper_dir.mkdir(parents=True, exist_ok=True)

    data = await file.read()
    if data[:4] != b"%PDF":
        raise HTTPException(400, "not a valid PDF")
    pdf_dest = paper_dir / "original.pdf"
    pdf_dest.write_bytes(data)

    # Pull the real title + authors from the PDF; fall back to the filename.
    extracted_title, authors = _extract_pdf_meta(pdf_dest)
    fallback = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    title = extracted_title or fallback or filename
    wb_text = _render_pdf_to_read_workbench(
        title=title, category=category or "", tags=tags, filename=filename,
        authors=authors,
    )
    # Override the slug line to the unique slug (render uses filename-derived)
    wb_text = re.sub(r"^slug: .*$", f"slug: {slug}", wb_text, count=1, flags=re.MULTILINE)
    (paper_dir / "workbench.md").write_text(wb_text)
    return {"slug": slug, "already_existed": False, "pdf_ok": True}
