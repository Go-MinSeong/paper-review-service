"""FastAPI app: read-only gallery + paper detail + SSE on workbench.md changes."""

from __future__ import annotations

import asyncio
import json
from html import escape as _escape
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from .. import SERVICE_ROOT
from ..workbench import read_status
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
    RatingPatchBody,
    TagsPatchBody,
    list_all_tags,
    patch_paper_rating,
    patch_paper_tags,
)

app = FastAPI(title="paper-review")

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
    p = SERVICE_ROOT / safe
    if not p.is_dir():
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


def _list_papers() -> list[dict]:
    if not SERVICE_ROOT.exists():
        return []
    views = _load_views()
    rows: list[dict] = []
    for d in sorted(
        SERVICE_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        wb = d / "workbench.md"
        if not wb.exists():
            continue
        meta = _read_frontmatter(wb)
        text = wb.read_text()
        total, done = _section_progress(text)
        try:
            rating = max(0, min(5, int(str(meta.get("rating", "")).strip() or 0)))
        except ValueError:
            rating = 0
        # Figure count
        fig_files = list(d.glob("*_figures.json"))
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

        rows.append(
            {
                "slug": d.name,
                "status": meta.get("status", read_status(wb)),
                "content_type": meta.get("content_type", "paper"),
                "title_en": meta.get("title_en", ""),
                "title_ko": meta.get("title_ko", ""),
                "paper_url": meta.get("paper_url", ""),
                "category": meta.get("category", ""),
                "review_started": meta.get("review_started", ""),
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
            }
        )
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
    if not fig or not fig.get("data_uri"):
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
    """Delete a paper's working directory (irreversible). Cancels any running
    analyze job for it first."""
    import shutil

    d = _paper_dir(slug)  # validates existence
    # Best-effort cancel of an in-flight analyze job
    try:
        from .analyze import _jobs as _analyze_jobs

        job = _analyze_jobs.get(slug)
        if job and job.status == "running":
            job.cancel_event.set()
    except Exception:
        pass
    shutil.rmtree(d, ignore_errors=True)
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
    return PlainTextResponse(read_skill(name), media_type="text/markdown; charset=utf-8")


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


@app.get("/papers/active-jobs")
def papers_active_jobs():
    """List slugs with currently running analyze jobs (for gallery indicator)."""
    from .analyze import _jobs

    return [
        {
            "slug": j.slug,
            "current": j.current,
            "total": j.total,
            "current_heading": j.current_heading,
        }
        for j in _jobs.values()
        if j.status == "running"
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


@app.post("/paper/{slug}/generate-pipeline")
async def paper_generate_pipeline(slug: str, body: GenQBody):
    """Auto-generate the ```pipeline animation spec from the paper (on demand)."""
    from .analyze import generate_pipeline

    d = _paper_dir(slug)
    return await generate_pipeline(d, body.model)


@app.post("/paper/{slug}/publish")
def paper_publish(slug: str):
    import re as _re
    from ..publish.transform import workbench_to_draft
    from .. import VELOG_DRAFTS_DIR

    d = _paper_dir(slug)
    wb = d / "workbench.md"
    if not wb.exists():
        raise HTTPException(404, "workbench missing")
    VELOG_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = VELOG_DRAFTS_DIR / f"{slug}.md"
    workbench_to_draft(wb, dest, paper_dir=d)
    # Bump workbench status to 'exported'
    text = wb.read_text()
    new_text = _re.sub(r"^status:\s*\S+", "status: exported", text, flags=_re.MULTILINE)
    if new_text != text:
        wb.write_text(new_text)
    return {"ok": True, "draft_path": str(dest), "size": dest.stat().st_size}


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
