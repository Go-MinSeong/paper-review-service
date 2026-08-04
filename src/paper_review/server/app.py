"""FastAPI app: read-only gallery + paper detail + SSE on workbench.md changes."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from html import escape as _escape
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from .. import SERVICE_ROOT
from ..workbench import read_status, strip_legacy_wrapup_fields
from pydantic import BaseModel

from .analyze import (
    AnalyzeBody,
    cancel as cancel_analysis,
    get_status as get_analysis_status,
    start_analysis,
)
from .chat import ChatBody, chat_route
from .ingest import StartIngestBody, get_job, start_arxiv_job, start_pdf_job
from .save import SaveBody, save_paper, save_pdf_paper
from .tags import (
    BulkBody,
    RatingPatchBody,
    StatusPatchBody,
    TagRenameBody,
    TagsPatchBody,
    bulk_edit,
    list_all_tags,
    rename_tag,
    patch_paper_rating,
    patch_paper_status,
    patch_paper_tags,
)


def _migrate_layout() -> None:
    """Sort any flat-layout papers into papers/<status>/ once, at startup.

    Same-filesystem renames, so it is fast and reversible. A paper an analyze
    job is currently running in stays put — that folder is the cwd of a live
    `claude` process."""
    from ..library import migrate

    def busy(slug: str) -> bool:
        from .analyze import _jobs

        job = _jobs.get(slug)
        return bool(job and job.status == "running")

    try:
        out = migrate(is_busy=busy)
    except Exception as e:  # never keep the server from starting
        print(f"paper-review: layout migration skipped ({e})")
        return
    if out["moved"]:
        print(f"paper-review: moved {len(out['moved'])} papers into papers/<status>/")
    if out["skipped"]:
        print(f"paper-review: left {len(out['skipped'])} in place (busy or clashing)")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _migrate_layout()
    yield


app = FastAPI(title="paper-review", lifespan=_lifespan)


@app.middleware("http")
async def _port80_loopback_only(request, call_next):
    """The pretty-URL listener (:80) must not widen network exposure: macOS
    only lets unprivileged binds use the wildcard address, so we reject any
    non-loopback client that arrives via port 80. The main port keeps its
    configured policy (e.g. LAN access for phones on :7300)."""
    server = request.scope.get("server") or ("", 0)
    client = request.client.host if request.client else ""
    # "testclient" = starlette TestClient (in-process, not a network peer)
    if server[1] == 80 and client not in ("127.0.0.1", "::1", "testclient", ""):
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("local access only", status_code=403)
    return await call_next(request)


_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _render_template(name: str, **subs: str) -> str:
    """Read templates/<name>.html, cache-bust /static/* by mtime, substitute __KEY__."""
    text = (_TEMPLATES_DIR / f"{name}.html").read_text()
    # Auto cache-bust own static assets
    for asset in _STATIC_DIR.iterdir():
        if asset.is_file():
            v = int(asset.stat().st_mtime)
            text = text.replace(f"/static/{asset.name}", f"/static/{asset.name}?v={v}")
    for key, val in subs.items():
        text = text.replace(f"__{key}__", val)
    return text


def _paper_dir(slug: str) -> Path:
    safe = slug.strip()
    if not safe or "/" in safe or safe.startswith("."):
        raise HTTPException(400, "bad slug")
    from ..library import paper_dir

    p = paper_dir(safe)
    if p is None:
        raise HTTPException(404, f"unknown slug {safe!r}")
    return p


# Central view-timestamp store (slug → unix seconds). Kept out of the paper
# folders so opening a paper doesn't bump its dir mtime / gallery order.
_VIEWS_FILE = SERVICE_ROOT / ".views.json"


def _load_views() -> dict:
    try:
        return json.loads(_VIEWS_FILE.read_text())
    except Exception:
        return {}


def _mark_viewed(slug: str) -> None:
    import time

    views = _load_views()
    views[slug] = int(time.time())
    try:
        _VIEWS_FILE.write_text(json.dumps(views))
    except Exception:
        pass


def _published_ym(slug: str, paper_dir: Path) -> int:
    """Approx publication date as a sortable int YYYYMM (e.g. 202406).
    arXiv IDs encode YYMM (2406.09246 → 2024-06); fall back to paper.json year."""
    import re as _re

    m = _re.match(r"^(\d{2})(\d{2})\.\d{4,5}", slug)
    if m:
        mm = int(m.group(2))
        return (2000 + int(m.group(1))) * 100 + (mm if 1 <= mm <= 12 else 1)
    pj = list(paper_dir.glob("*_paper.json"))
    if pj:
        try:
            yr = json.loads(pj[0].read_text()).get("metadata", {}).get("year")
            if yr:
                return int(yr) * 100
        except Exception:
            pass
    return 0


# Per-paper row cache: {slug: (workbench_mtime, figures_mtime, row)}. Building a
# row means reading and parsing workbench.md AND a *_figures.json that can be
# several MB of base64 — at 100+ papers that ran on every gallery load and every
# focus refresh. Keyed on both mtimes, so an edit anywhere still shows up.
_ROW_CACHE: dict = {}


def _list_papers() -> list[dict]:
    if not SERVICE_ROOT.exists():
        return []
    views = _load_views()
    from ..remote import slot_state

    on_phone = slot_state(SERVICE_ROOT).get("slug", "")
    from ..library import iter_papers

    rows: list[dict] = []
    for d in sorted(iter_papers(), key=lambda p: p.stat().st_mtime, reverse=True):
        wb = d / "workbench.md"
        fig_files = list(d.glob("*_figures.json"))
        fig_mtime = fig_files[0].stat().st_mtime if fig_files else 0.0
        wb_mtime = wb.stat().st_mtime
        cached = _ROW_CACHE.get(d.name)
        if cached and cached[0] == wb_mtime and cached[1] == fig_mtime:
            row = dict(cached[2])
            # these two live outside the paper folder, so they aren't covered
            # by the mtimes the cache keys on
            row["last_viewed"] = int(views.get(d.name, 0))
            row["on_remote"] = d.name == on_phone
            rows.append(row)
            continue
        meta = _read_frontmatter(wb)
        text = wb.read_text()
        # One-time cleanup of the Wrap-up/메타 fields retired in 2.6.0. Analyze
        # deliberately never touches Wrap-up, so papers created before that kept
        # the empty placeholders forever; the gallery already reads every
        # workbench, so this is where they get dropped (only while empty).
        migrated = strip_legacy_wrapup_fields(text)
        if migrated != text:
            try:
                st = wb.stat()
                wb.write_text(migrated)
                # keep the original mtime: this is housekeeping, not an edit —
                # otherwise every old paper jumps to "edited just now" at once
                os.utime(wb, (st.st_atime, st.st_mtime))
                text = migrated
            except OSError:
                pass
        total, done = _section_progress(text)
        try:
            rating = max(0, min(5, int(str(meta.get("rating", "")).strip() or 0)))
        except ValueError:
            rating = 0
        fig_count = 0
        if fig_files:
            try:
                data = json.loads(fig_files[0].read_text())
                fig_count = (
                    len(data)
                    if isinstance(data, list)
                    else len(data.get("figures", []))
                )
            except Exception:
                pass
        from .tags import _parse_tags_value

        row = {
            "slug": d.name,
            "status": meta.get("status", read_status(wb)),
            "content_type": meta.get("content_type", "paper"),
            "title_en": meta.get("title_en", ""),
            "title_ko": meta.get("title_ko", ""),
            "paper_url": meta.get("paper_url", ""),
            "category": meta.get("category", ""),
            "review_started": meta.get("review_started", ""),
            "exported_at": meta.get("exported_at", ""),
            "sections_total": total,
            "sections_done": done,
            "figures_count": fig_count,
            "tags": _parse_tags_value(meta.get("tags", "")),
            "rating": rating,
            "updated_at": int(wb.stat().st_mtime),
            "created_at": int(
                getattr(d.stat(), "st_birthtime", 0) or d.stat().st_ctime
            ),
            "published_ym": _published_ym(d.name, d),
            "last_viewed": int(views.get(d.name, 0)),
            "on_remote": d.name == on_phone,
        }
        _ROW_CACHE[d.name] = (wb.stat().st_mtime, fig_mtime, row)
        rows.append(row)
    # drop entries for papers that are gone (deleted / moved to _trash)
    if len(_ROW_CACHE) > len(rows):
        live = {r["slug"] for r in rows}
        for gone in [k for k in _ROW_CACHE if k not in live]:
            _ROW_CACHE.pop(gone, None)
    return rows


def _sections_block(workbench_md: str) -> "str | None":
    """The body between '## 섹션별 리뷰' and the next known H2 (Q&A/Wrap-up/메타/
    정리). Bounding by an explicit H2 avoids breaking when a section's translated
    body contains a line starting with '## '."""
    import re

    start_m = re.search(r"##\s+섹션별 리뷰\s*\n", workbench_md)
    if not start_m:
        return None
    start = start_m.end()
    tail = re.search(r"\n##\s+(?:Q ?& ?A|Wrap-up|메타|정리)\b", workbench_md[start:])
    end = start + tail.start() if tail else len(workbench_md)
    return workbench_md[start:end]


def _section_progress(workbench_md: str) -> tuple[int, int]:
    import re

    body = _sections_block(workbench_md)
    if body is None:
        return 0, 0
    chunks = re.split(r"(?=\n### )", body)
    total = 0
    done = 0
    for chunk in chunks:
        if not chunk.lstrip().startswith("### "):
            continue
        total += 1
        if "(미진행" not in chunk:
            done += 1
    return total, done


def _read_frontmatter(workbench_md: Path) -> dict:
    text = workbench_md.read_text()
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    out: dict = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


@app.get("/", response_class=HTMLResponse)
def gallery() -> HTMLResponse:
    rows = _list_papers()
    payload = json.dumps(rows, ensure_ascii=False)
    html = _render_template("gallery", PAPERS_JSON=payload, COUNT=str(len(rows)))
    return HTMLResponse(html)


@app.get("/paper/{slug}", response_class=HTMLResponse)
def paper_detail(slug: str) -> HTMLResponse:
    d = _paper_dir(slug)
    meta = _read_frontmatter(d / "workbench.md")
    title = meta.get("title_ko") or meta.get("title_en") or slug
    content_type = meta.get("content_type", "paper")
    has_pdf = (d / "original.pdf").exists() or any(d.glob("*.pdf"))
    pdf_name = (
        "original.pdf"
        if (d / "original.pdf").exists()
        else next((f.name for f in d.glob("*.pdf")), "")
    )
    has_viewer = (d / "viewer.html").exists()
    # Left pane source: PDF for papers, rendered original text for web content.
    source_src = f"/paper/{slug}/pdf" if has_pdf else f"/paper/{slug}/source"
    html = _render_template(
        "detail",
        SLUG=slug,
        TITLE=_escape(title),
        STATUS=meta.get("status", "?"),
        RATING=str(meta.get("rating") or "0"),
        CONTENT_TYPE=content_type,
        SOURCE_SRC=source_src,
        PDF_NAME=pdf_name,
        HAS_PDF="true" if has_pdf else "false",
        HAS_VIEWER="true" if has_viewer else "false",
    )
    return HTMLResponse(html)


@app.get("/paper/{slug}/workbench.md", response_class=PlainTextResponse)
def workbench_raw(slug: str) -> PlainTextResponse:
    wb = _paper_dir(slug) / "workbench.md"
    if not wb.exists():
        raise HTTPException(404)
    return PlainTextResponse(wb.read_text(), media_type="text/markdown; charset=utf-8")


class WorkbenchPut(BaseModel):
    text: str
    expected_mtime: float | None = None  # for optimistic concurrency


_HISTORY_KEEP = 5


def _keep_history(wb: Path) -> None:
    """Snapshot workbench.md before overwriting it.

    The review IS the product and every save replaced it in place — a bad
    paste or a stale editor tab could wipe an afternoon with no way back.
    Keeps the last few versions per paper; best-effort, never blocks a save."""
    try:
        hist = wb.parent / ".history"
        hist.mkdir(exist_ok=True)
        stamp = int(wb.stat().st_mtime)
        snap = hist / f"workbench-{stamp}.md"
        if not snap.exists():
            snap.write_bytes(wb.read_bytes())
        old = sorted(hist.glob("workbench-*.md"))[:-_HISTORY_KEEP]
        for f in old:
            f.unlink(missing_ok=True)
    except OSError:
        pass


@app.put("/paper/{slug}/workbench.md")
def workbench_put(slug: str, body: WorkbenchPut):
    wb = _paper_dir(slug) / "workbench.md"
    if not wb.exists():
        raise HTTPException(404)
    if body.expected_mtime is not None:
        current = wb.stat().st_mtime
        # 1s tolerance for filesystem precision
        if abs(current - body.expected_mtime) > 1.0:
            raise HTTPException(
                409,
                detail={
                    "error": "modified",
                    "current_mtime": current,
                    "expected_mtime": body.expected_mtime,
                },
            )
    _keep_history(wb)
    wb.write_text(body.text)
    return {"ok": True, "mtime": wb.stat().st_mtime, "size": len(body.text)}


@app.get("/paper/{slug}/pdf")
def paper_pdf(slug: str) -> FileResponse:
    d = _paper_dir(slug)
    pdf = d / "original.pdf"
    if not pdf.exists():
        candidates = list(d.glob("*.pdf"))
        if not candidates:
            raise HTTPException(404, "no pdf")
        pdf = candidates[0]
    return FileResponse(pdf, media_type="application/pdf")


@app.get("/paper/{slug}/viewer.html", response_class=HTMLResponse)
def paper_viewer(slug: str) -> HTMLResponse:
    v = _paper_dir(slug) / "viewer.html"
    if not v.exists():
        raise HTTPException(404)
    return HTMLResponse(v.read_text())


@app.get("/paper/{slug}/source.md", response_class=PlainTextResponse)
def paper_source_md(slug: str) -> PlainTextResponse:
    """Raw original body (markdown for web content / plain text for papers)."""
    d = _paper_dir(slug)
    src = next(iter(d.glob("*_source.txt")), None)
    if not src or not src.exists():
        raise HTTPException(404, "no source")
    return PlainTextResponse(src.read_text(), media_type="text/markdown; charset=utf-8")


@app.get("/paper/{slug}/source", response_class=HTMLResponse)
def paper_source(slug: str) -> HTMLResponse:
    """Rendered original body — the left-pane 'PDF replacement' for web content."""
    d = _paper_dir(slug)
    if not next(iter(d.glob("*_source.txt")), None):
        raise HTTPException(404, "no source")
    meta = _read_frontmatter(d / "workbench.md")
    title = meta.get("title_ko") or meta.get("title_en") or slug
    html = _render_template("source", SLUG=slug, TITLE=_escape(title))
    return HTMLResponse(html)


@app.get("/paper/{slug}/figures/{name}")
def paper_figure(slug: str, name: str) -> FileResponse:
    if "/" in name or name.startswith("."):
        raise HTTPException(400)
    p = _paper_dir(slug) / "figures" / name
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/paper/{slug}/fig/{fig_id}")
def paper_fig_by_id(slug: str, fig_id: str):
    """Serve a single figure by id, decoding its base64 data_uri to bytes.
    Lets the workbench reference figures by a short path instead of inlining
    ~120KB of base64 per image."""
    import base64
    import re as _re
    from fastapi.responses import Response

    d = _paper_dir(slug)
    figs = list(d.glob("*_figures.json"))
    if not figs:
        raise HTTPException(404)
    data = json.loads(figs[0].read_text())
    items = data if isinstance(data, list) else data.get("figures", [])
    fig = next((f for f in items if f.get("id") == fig_id), None)
    if not fig:
        raise HTTPException(404)
    if not fig.get("data_uri"):
        # Tables are extracted as HTML, not pixels. Serving the markup beats a
        # 404: the link works when followed, and the mobile page and the
        # publish pipeline can pick the table up from here.
        if fig.get("html"):
            return HTMLResponse(
                "<!doctype html><meta charset='utf-8'>"
                "<style>body{font:14px/1.6 -apple-system,sans-serif;margin:16px}"
                "table{border-collapse:collapse}td,th{border:1px solid #ccc;"
                "padding:.35rem .55rem}</style>" + fig["html"]
            )
        raise HTTPException(404)
    m = _re.match(r"data:(image/[\w.+-]+);base64,(.*)", fig["data_uri"], _re.DOTALL)
    if not m:
        raise HTTPException(415, "figure is not a base64 image")
    return Response(base64.b64decode(m.group(2)), media_type=m.group(1))


@app.post("/paper/{slug}/fig/{fig_id}/image")
async def set_fig_image(slug: str, fig_id: str, request: Request):
    """Attach a rasterized PNG (data URI) to a figure entry. The review UI
    renders tables to images (html2canvas) so they survive the WYSIWYG → Velog
    pipeline intact; this stores the result as the figure's data_uri so the
    /fig/{id} route serves it and publish materializes it like any figure.
    Body: {"data_uri": "data:image/png;base64,..."}."""
    d = _paper_dir(slug)
    figs = list(d.glob("*_figures.json"))
    if not figs:
        raise HTTPException(404, "no figures.json")
    body = await request.json()
    data_uri = (body or {}).get("data_uri", "")
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        raise HTTPException(400, "data_uri must be a data:image/* URI")
    path = figs[0]
    data = json.loads(path.read_text())
    items = data if isinstance(data, list) else data.get("figures", [])
    fig = next((f for f in items if f.get("id") == fig_id), None)
    if fig is None:
        raise HTTPException(404, "fig id not found")
    fig["data_uri"] = data_uri
    fig["kind"] = "image"  # rasterized — no longer an HTML table
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True, "url": f"/paper/{slug}/fig/{fig_id}"}


@app.post("/paper/{slug}/pipeline-image")
async def set_pipeline_image(slug: str, request: Request):
    """Store an exported pipeline GIF (data URI) as figure `pipe<n>` so publish
    materializes it like any figure. Body: {"index": 1, "data_uri": "data:image/gif;base64,..."}.
    Creates the figures.json sidecar / entry if needed (pipelines aren't ar5iv figures).
    """
    body = await request.json()
    data_uri = (body or {}).get("data_uri", "")
    try:
        index = int((body or {}).get("index", 1))
    except (TypeError, ValueError):
        index = 1
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        raise HTTPException(400, "data_uri must be a data:image/* URI")
    d = _paper_dir(slug)
    figs = list(d.glob("*_figures.json"))
    path = figs[0] if figs else (d / f"{slug}_figures.json")
    data = json.loads(path.read_text()) if path.exists() else []
    items = data if isinstance(data, list) else data.get("figures", [])
    fig_id = f"pipe{max(1, index)}"
    fig = next((f for f in items if f.get("id") == fig_id), None)
    if fig is None:
        fig = {
            "id": fig_id,
            "label": f"Pipeline {index}",
            "kind": "image",
            "source": "pipeline",
        }
        items.append(fig)
    fig["data_uri"] = data_uri
    fig["kind"] = "image"
    if isinstance(data, list):
        data = items
    else:
        data["figures"] = items
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True, "url": f"/paper/{slug}/fig/{fig_id}", "id": fig_id}


@app.get("/paper/{slug}/figures.json")
def paper_figures_json(slug: str) -> JSONResponse:
    """Serve the raw figures.json (list of {id, label, caption_en, caption_ko,
    data_uri, ref_in_section, kind, source})."""
    d = _paper_dir(slug)
    figs = list(d.glob("*_figures.json"))
    if not figs:
        return JSONResponse([])
    return JSONResponse(json.loads(figs[0].read_text()))


@app.get("/paper/{slug}/meta")
def paper_meta(slug: str) -> JSONResponse:
    d = _paper_dir(slug)
    meta = _read_frontmatter(d / "workbench.md")
    figs_files = list(d.glob("*_figures.json"))
    figs_count = 0
    if figs_files:
        data = json.loads(figs_files[0].read_text())
        figs_count = (
            len(data) if isinstance(data, list) else len(data.get("figures", []))
        )
    return JSONResponse(
        {
            "slug": slug,
            "frontmatter": meta,
            "figures_count": figs_count,
        }
    )


app.post("/paper/{slug}/chat")(chat_route(_paper_dir))


@app.post("/papers")
async def papers_create_arxiv(body: StartIngestBody):
    return await start_arxiv_job(body)


@app.post("/papers/upload")
async def papers_create_pdf(file: UploadFile):
    return await start_pdf_job(file)


@app.post("/papers/save")
async def papers_save(body: SaveBody):
    """Add an arXiv paper to the reading list + archive its PDF (no body extraction)."""
    return await save_paper(body)


@app.post("/papers/save-pdf")
async def papers_save_pdf(
    file: UploadFile,
    tags: str = Form(""),
    category: str = Form(""),
):
    """Save an uploaded PDF to the reading list (archive file, no ingest)."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return await save_pdf_paper(file, tag_list, category or None)


@app.delete("/paper/{slug}")
def paper_delete(slug: str):
    """Move a paper's working directory to _trash/ (recoverable). Cancels any
    running analyze job for it first.

    This used to rmtree — one misclick on a card's 🗑 destroyed a review that
    took hours. Illustrations already went to a trash folder; papers, the thing
    the whole tool exists to produce, did not."""
    d = _paper_dir(slug)  # validates existence
    # Best-effort cancel of an in-flight analyze job
    try:
        from .analyze import _jobs as _analyze_jobs

        job = _analyze_jobs.get(slug)
        if job and job.status == "running":
            job.cancel_event.set()
    except Exception:
        pass
    import time

    trash = SERVICE_ROOT / "_trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        d.rename(dest)
    except OSError:  # cross-device or name clash — fall back to a copy+remove
        import shutil

        shutil.move(str(d), str(dest))
    return {"ok": True, "slug": slug}


@app.post("/paper/{slug}/promote")
async def papers_promote(slug: str):
    """Promote a to_read paper to full ingest (body + figures + sections).
    Preserves user-added tags / category."""
    from .ingest import _jobs as _ingest_jobs

    d = _paper_dir(slug)
    wb = d / "workbench.md"
    if not wb.exists():
        raise HTTPException(404)
    fm = _read_frontmatter(wb)
    if fm.get("status") not in ("to_read", "unknown", "", None):
        raise HTTPException(400, "paper is already ingested (status != to_read)")
    # Snapshot preserve fields
    from .tags import _parse_tags_value

    preserve = {}
    if fm.get("tags"):
        preserve["tags"] = _parse_tags_value(fm["tags"])
    if fm.get("category"):
        preserve["category"] = fm["category"]

    # PDF-backed reading list paper → ingest from the archived original.pdf
    is_pdf_paper = bool(fm.get("source_pdf")) or (
        (d / "original.pdf").exists() and not (fm.get("paper_url") or "").strip()
    )
    if is_pdf_paper:
        pdf = d / "original.pdf"
        if not pdf.exists():
            raise HTTPException(400, "no original.pdf to analyze")
        import shutil
        import uuid as _uuid
        from .ingest import start_local_pdf_job, _TMP_UPLOADS

        _TMP_UPLOADS.mkdir(parents=True, exist_ok=True)
        tmp = _TMP_UPLOADS / f"{_uuid.uuid4().hex[:8]}_{slug}.pdf"
        shutil.copy(pdf, tmp)
        job_resp = await start_local_pdf_job(str(tmp), cleanup_dir=str(d))
        job = _ingest_jobs[job_resp["job_id"]]
        job.preserve_fields = preserve
        return job_resp

    # Web-backed (blog/article) → re-ingest from the URL; `init` auto-detects web
    # and produces the same slug, so it overwrites this reading-list folder.
    paper_url = (fm.get("paper_url") or "").strip()
    is_web = fm.get("content_type") in ("blog", "article") or (
        paper_url.startswith("http") and "arxiv.org" not in paper_url
    )
    if is_web:
        if not paper_url:
            raise HTTPException(400, "no source_url to analyze")
        job_resp = await start_arxiv_job(StartIngestBody(source=paper_url))
        job = _ingest_jobs[job_resp["job_id"]]
        job.preserve_fields = preserve
        return job_resp

    # arXiv-backed → re-ingest by id (stable slug)
    arxiv_id = fm.get("slug") or slug
    job_resp = await start_arxiv_job(StartIngestBody(source=arxiv_id))
    job = _ingest_jobs[job_resp["job_id"]]
    job.preserve_fields = preserve
    return job_resp


@app.get("/skills")
def skills_list():
    from .settings import list_skills

    return list_skills()


@app.get("/skills/{name}", response_class=PlainTextResponse)
def skill_get(name: str) -> PlainTextResponse:
    from .settings import read_skill

    return PlainTextResponse(
        read_skill(name), media_type="text/markdown; charset=utf-8"
    )


@app.put("/skills/{name}")
async def skill_put(name: str, request: Request):
    from .settings import write_skill

    write_skill(name, (await request.body()).decode("utf-8"))
    return {"ok": True}


@app.get("/illustrations")
def illustrations_list():
    from .settings import list_illustrations

    return list_illustrations()


@app.get("/illustration-groups")
def illustration_groups_route():
    from .settings import illustration_groups

    return illustration_groups()


@app.post("/illustrations")
async def illustrations_add(file: UploadFile, name: str = Form("")):
    from .settings import save_illustration

    return {"name": await save_illustration(file, name)}


@app.delete("/illustrations/{name}")
def illustrations_delete(name: str):
    from .settings import trash_illustration

    trash_illustration(name)
    return {"ok": True}


@app.get("/tags")
def get_tags():
    return list_all_tags()


@app.patch("/paper/{slug}/tags")
def patch_tags(slug: str, body: TagsPatchBody):
    _paper_dir(slug)  # validate
    return patch_paper_tags(slug, body)


@app.patch("/paper/{slug}/rating")
def patch_rating(slug: str, body: RatingPatchBody):
    _paper_dir(slug)  # validate
    return patch_paper_rating(slug, body)


@app.patch("/paper/{slug}/status")
def patch_status(slug: str, body: StatusPatchBody):
    _paper_dir(slug)  # validate
    return patch_paper_status(slug, body)


class SettingsBody(BaseModel):
    # Every field is optional: each Settings pane saves only what it owns.
    drafts_dir: str | None = None
    remote_url: str | None = None
    remote_token: str | None = None  # None = keep the stored one


@app.get("/settings")
def get_settings():
    """User settings + effective paths (for the gallery settings panel).
    The remote token is never sent back — only whether one is stored."""
    from ..config import DEFAULT_DRAFTS_DIR, get_drafts_dir, load_settings
    from ..remote import read_config

    rc = read_config()
    return {
        "drafts_dir": load_settings().get("drafts_dir", ""),
        "effective_drafts_dir": str(get_drafts_dir()),
        "default_drafts_dir": str(DEFAULT_DRAFTS_DIR),
        "remote_url": rc["url"],
        "remote_token_set": rc["token_set"],
        "remote_from_env": rc["from_env"],
    }


@app.put("/settings")
def put_settings(body: SettingsBody):
    """Save the panes' settings. Publish dir: empty = default. Mobile slot:
    empty URL clears the config, and an omitted token keeps the stored one."""
    from ..config import get_drafts_dir, load_settings, save_settings
    from ..remote import save_config

    if body.drafts_dir is not None:
        s = load_settings()
        val = body.drafts_dir.strip()
        if val:
            p = Path(val).expanduser()
            if not p.is_absolute():
                raise HTTPException(
                    400, "절대 경로를 입력하세요 (예: ~/Documents/my-vault/drafts)"
                )
            s["drafts_dir"] = str(p)
        else:
            s.pop("drafts_dir", None)
        save_settings(s)

    if body.remote_url is not None:
        try:
            save_config(body.remote_url, body.remote_token)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return {"ok": True, "effective_drafts_dir": str(get_drafts_dir())}


@app.post("/paper/{slug}/remote-push")
def remote_push(slug: str):
    """Replace the Vercel remote slot with this paper (mobile continuation)."""
    _paper_dir(slug)  # validate
    from ..remote import push

    try:
        return push(slug, SERVICE_ROOT)
    except Exception as e:  # config missing / network — surface as a clean 400
        raise HTTPException(400, str(e))


@app.post("/remote-pull")
def remote_pull():
    """Write the remote slot's workbench back to the local paper."""
    from ..remote import pull

    try:
        return pull(SERVICE_ROOT)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/paper/{slug}/baseline.json")
def paper_baseline(slug: str) -> JSONResponse:
    """Claude-authored section snapshots (heading → markdown), used by the UI
    to word-diff and highlight the user's own edits. Empty if not yet built."""
    p = _paper_dir(slug) / ".baseline.json"
    if not p.exists():
        return JSONResponse({})
    try:
        return JSONResponse(json.loads(p.read_text()))
    except Exception:
        return JSONResponse({})


@app.post("/paper/{slug}/viewed")
def mark_viewed(slug: str):
    """Record that the paper was opened (for the gallery's last-activity time)."""
    _paper_dir(slug)  # validate
    _mark_viewed(slug)
    return {"ok": True}


@app.get("/papers/jobs/{job_id}")
def papers_job(job_id: str):
    return get_job(job_id)


@app.post("/papers/bulk")
def papers_bulk(body: BulkBody):
    """Set status / add / remove tags on many papers in one call."""
    return bulk_edit(body)


@app.post("/tags/rename")
def tags_rename(body: TagRenameBody):
    """Rename a tag library-wide; an empty target removes it."""
    return rename_tag(body)


@app.get("/update")
def update_check(force: int = 0):
    """Is a newer release out? Cached, never blocking, never installs anything."""
    from ..update import check

    return check(force=bool(force))


@app.get("/papers.json")
def papers_json():
    """The gallery embeds its list at render time, so a window left open shows a
    stale library. This lets it re-read the list without a reload — there is no
    address bar in the desktop app."""
    return _list_papers()


@app.get("/papers/active-jobs")
def papers_active_jobs():
    """Analyze jobs the gallery should surface: running ones (progress bar) plus
    finished ones that errored or had failed sections (a failure flag + log)."""
    from .analyze import _jobs

    return [
        {
            "slug": j.slug,
            "status": j.status,
            "phase": j.phase,
            "current": j.current,
            "total": j.total,
            "current_heading": j.current_heading,
            "failed": len(j.failed_sections),
            "error": j.error,
        }
        for j in _jobs.values()
        if j.status == "running" or j.status == "error" or j.failed_sections
    ]


@app.post("/paper/{slug}/analyze")
async def paper_analyze(slug: str, body: AnalyzeBody):
    d = _paper_dir(slug)
    return await start_analysis(slug, d, body)


@app.get("/paper/{slug}/analyze/status")
def paper_analyze_status(slug: str):
    _paper_dir(slug)  # validate
    return get_analysis_status(slug)


@app.get("/paper/{slug}/analyze/preview")
def paper_analyze_preview(slug: str):
    """Estimate pending sections + cost/time before triggering analyze."""
    from .analyze import _parse_unfinished_sections, _needs_prelude

    d = _paper_dir(slug)
    wb = d / "workbench.md"
    if not wb.exists():
        raise HTTPException(404)
    text = wb.read_text()
    pending = _parse_unfinished_sections(d, text)
    needs_prelude = _needs_prelude(text)
    # Rough estimates per Sonnet 4.6 with cache hits: ~60s/section, ~$0.07/section
    # Prelude is heavier (more context, more output): ~90s, ~$0.15
    est_secs = (90 if needs_prelude else 0) + 60 * len(pending)
    est_cost = (0.15 if needs_prelude else 0) + 0.07 * len(pending)
    return {
        "pending_sections": len(pending),
        "needs_prelude": needs_prelude,
        "estimated_seconds": est_secs,
        "estimated_cost_usd": round(est_cost, 2),
    }


@app.post("/paper/{slug}/analyze/cancel")
def paper_analyze_cancel(slug: str):
    _paper_dir(slug)
    return cancel_analysis(slug)


class GenQBody(BaseModel):
    model: str | None = None


@app.post("/paper/{slug}/generate-questions")
async def paper_generate_questions(slug: str, body: GenQBody):
    """Generate probing Q&A questions for the analyzed sections (on demand)."""
    from .analyze import generate_questions

    d = _paper_dir(slug)
    return await generate_questions(d, body.model)


@app.post("/paper/{slug}/generate-report")
async def paper_generate_report(slug: str, body: GenQBody):
    """Start building the structured review report (최종 정리). Returns as soon as
    the job starts — follow it via /analyze/status (phase == "report")."""
    from .analyze import start_report

    d = _paper_dir(slug)
    return await start_report(slug, d, body.model)


def _inline_table_figs(html: str, d: Path) -> str:
    """Replace <img src=".../fig/tblN"> with the table itself.

    Tables are extracted as HTML, not pixels, so /fig/<tbl-id> has no image to
    serve and the report rendered a broken image where the table belonged. The
    prompt no longer offers table ids as images, but reports built before that
    still carry the tags — repairing on the way out fixes them without a
    regenerate."""
    import re as _re

    if "/fig/tbl" not in html:
        return html
    figs = list(d.glob("*_figures.json"))
    if not figs:
        return html
    data = json.loads(figs[0].read_text())
    items = data if isinstance(data, list) else data.get("figures", [])
    by_id = {f.get("id"): f for f in items if isinstance(f, dict)}

    def _swap(m):
        fig = by_id.get(m.group(1)) or {}
        return (
            f'<div class="paper-fig">{fig["html"]}</div>'
            if fig.get("html")
            else m.group(0)
        )

    return _re.sub(r"<img[^>]*?/fig/(tbl[\w-]+)[^>]*?>", _swap, html)


# Shown only when the report is opened as the top-level page for printing.
# WKWebView prints the top-level web view and nothing else, so the desktop app
# navigates here instead of trying (and silently failing) to print the iframe.
_PRINT_BAR = """
<style>
 #pr-printbar{position:fixed;top:0;left:0;right:0;z-index:99999;display:flex;
   gap:.5rem;align-items:center;padding:.5rem .75rem;font:13px/1.4 -apple-system,
   BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;background:#111;color:#fff}
 #pr-printbar a,#pr-printbar button{font:inherit;color:#fff;background:#333;
   border:0;border-radius:6px;padding:.35rem .7rem;text-decoration:none;cursor:pointer}
 #pr-printbar .sp{flex:1}
 body{padding-top:44px}
 @media print{#pr-printbar{display:none}body{padding-top:0}}
</style>
<div id="pr-printbar">
  <a href="__BACK__">← 리뷰로 돌아가기</a>
  <span class="sp"></span>
  <button onclick="window.print()">PDF로 저장 (⌘P)</button>
</div>
<script>
  // The print dialog is what turns this into a PDF; open it once the layout
  // and images have settled, and leave the button for a second pass.
  addEventListener('load', () => setTimeout(() => window.print(), 500));
</script>
"""


@app.get("/paper/{slug}/report")
def paper_report(
    slug: str, download: int = 0, print_view: int = Query(0, alias="print")
):
    """Serve the generated report.html (shown in the Summary view).

    X-Report-Stale: 1 when the workbench changed after the report was built,
    so the UI can flag/re-load it. X-Report-Mtime versions the iframe URL."""
    d = _paper_dir(slug)
    p = d / "report.html"
    if not p.exists():
        raise HTTPException(404, "report not generated yet")
    mtime = int(p.stat().st_mtime)
    wb = d / "workbench.md"
    stale = wb.exists() and wb.stat().st_mtime > p.stat().st_mtime
    headers = {
        "X-Report-Mtime": str(mtime),
        "X-Report-Stale": "1" if stale else "0",
    }
    if download:
        # The desktop app can't print the report: pywebview's window.print()
        # prints the top-level web view, and the report lives in an iframe, so
        # the export button did nothing there. A real file always works.
        headers["Content-Disposition"] = f'attachment; filename="{slug}-report.html"'
    raw = p.read_text()
    text = _inline_table_figs(raw, d)
    if print_view:
        bar = _PRINT_BAR.replace("__BACK__", f"/paper/{slug}")
        text = (
            text.replace("</body>", bar + "</body>", 1)
            if "</body>" in text
            else text + bar
        )
    if text != raw:
        return HTMLResponse(text, headers=headers)
    return FileResponse(p, media_type="text/html", headers=headers)


class PublishBody(BaseModel):
    # "detail" = full review draft (<slug>.md), "summary" = structured-report
    # summary draft (<slug>-summary.md, tagged `summary`). Both go to drafts/.
    targets: list[str] = ["detail"]


@app.post("/paper/{slug}/publish")
def paper_publish(slug: str, body: PublishBody | None = None):
    import re as _re
    from ..config import get_drafts_dir
    from ..publish.transform import report_to_summary_draft, workbench_to_draft

    targets = (body.targets if body else None) or ["detail"]
    if not set(targets) <= {"detail", "summary"}:
        raise HTTPException(400, f"invalid targets: {targets}")
    d = _paper_dir(slug)
    wb = d / "workbench.md"
    if not wb.exists():
        raise HTTPException(404, "workbench missing")
    drafts_dir = get_drafts_dir()
    drafts_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    stamp_export_date = True
    if "summary" in targets:
        sdest = drafts_dir / f"{slug}-summary.md"
        try:
            report_to_summary_draft(wb, sdest, paper_dir=d)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e))
        results["summary"] = str(sdest)
    if "detail" in targets:
        dest = drafts_dir / f"{slug}.md"
        workbench_to_draft(wb, dest, paper_dir=d)
        results["detail"] = str(dest)
        # Bump workbench status to 'exported' (detail is the primary artifact)
        text = wb.read_text()
        new_text = _re.sub(
            r"^status:\s*\S+", "status: exported", text, flags=_re.MULTILINE
        )
        if new_text != text:
            wb.write_text(new_text)
    if stamp_export_date and results:
        _stamp_exported_at(wb)
    return {"ok": True, "results": results}


def _stamp_exported_at(wb: Path) -> None:
    """Record/refresh `exported_at` in the frontmatter — the Export dashboard
    groups by this date (the workbench mtime keeps changing on edits)."""
    import re as _re
    from datetime import date

    today = date.today().isoformat()
    text = wb.read_text()
    line = f"exported_at: {today}"
    if _re.search(r"^exported_at:.*$", text, flags=_re.MULTILINE):
        new = _re.sub(r"^exported_at:.*$", line, text, count=1, flags=_re.MULTILINE)
    elif _re.search(r"^status:.*$", text, flags=_re.MULTILINE):
        new = _re.sub(
            r"^(status:.*)$", rf"\1\n{line}", text, count=1, flags=_re.MULTILINE
        )
    else:
        new = _re.sub(r"^---\n", f"---\n{line}\n", text, count=1)
    if new != text:
        wb.write_text(new)


@app.get("/paper/{slug}/events")
async def paper_events(slug: str, request: Request) -> StreamingResponse:
    d = _paper_dir(slug)
    targets = [d / "workbench.md", d / "viewer.html"]

    async def gen():
        last = {p.name: p.stat().st_mtime if p.exists() else 0 for p in targets}
        yield f"event: hello\ndata: {json.dumps(last)}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(0.8)
                for p in targets:
                    if not p.exists():
                        continue
                    m = p.stat().st_mtime
                    if m != last.get(p.name):
                        last[p.name] = m
                        yield f"event: change\ndata: {json.dumps({'file': p.name, 'mtime': m})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
