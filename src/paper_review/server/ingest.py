"""POST /papers — async ingest jobs.

Spawns `paper-review init <source>` in a background asyncio task. The endpoint
returns a job_id immediately; the client polls GET /papers/jobs/<job_id> until
status == "done", then redirects to /paper/<slug>.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel

from .. import SERVICE_ROOT


Status = Literal["starting", "running", "done", "error"]


@dataclass
class IngestJob:
    job_id: str
    source: str
    is_pdf: bool
    status: Status = "starting"
    slug: Optional[str] = None
    log: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    preserve_fields: dict = field(default_factory=dict)  # tags / category to restore
    cleanup_dir: Optional[str] = None  # old reading-list folder to remove on success


_jobs: dict[str, IngestJob] = {}
_TMP_UPLOADS = SERVICE_ROOT / "_uploads"


class StartIngestBody(BaseModel):
    source: str  # arxiv id, arxiv URL, or "(pdf upload)"


async def start_arxiv_job(body: StartIngestBody) -> dict:
    if not body.source.strip():
        raise HTTPException(400, "empty source")
    job = IngestJob(job_id=uuid.uuid4().hex[:12], source=body.source.strip(), is_pdf=False)
    _jobs[job.job_id] = job
    asyncio.create_task(_run_ingest(job))
    return {"job_id": job.job_id}


async def start_pdf_job(file: UploadFile) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "must be a .pdf")
    _TMP_UPLOADS.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = _TMP_UPLOADS / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    job = IngestJob(job_id=uuid.uuid4().hex[:12], source=str(dest), is_pdf=True)
    _jobs[job.job_id] = job
    asyncio.create_task(_run_ingest(job))
    return {"job_id": job.job_id}


async def start_local_pdf_job(pdf_path: str, cleanup_dir: str | None = None) -> dict:
    """Ingest a PDF that already lives on disk (e.g. promoting a saved PDF)."""
    job = IngestJob(job_id=uuid.uuid4().hex[:12], source=pdf_path, is_pdf=True)
    job.cleanup_dir = cleanup_dir
    _jobs[job.job_id] = job
    asyncio.create_task(_run_ingest(job))
    return {"job_id": job.job_id}


def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return _serialize(job)


async def _run_ingest(job: IngestJob) -> None:
    job.status = "running"
    job.log.append(f"$ paper-review init {job.source}")

    venv_bin = SERVICE_ROOT / ".venv" / "bin" / "paper-review"
    paper_review_bin = str(venv_bin) if venv_bin.exists() else "paper-review"

    cmd = [paper_review_bin, "init", "--force", job.source]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            limit=16 * 1024 * 1024,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                job.log.append(text)
                _maybe_extract_slug(job, text)
        await proc.wait()
        if proc.returncode != 0:
            job.status = "error"
            job.error = f"exit {proc.returncode}"
        else:
            if not job.slug:
                _detect_slug_post_hoc(job)
            job.status = "done"
            _restore_preserved_fields(job)
            await _auto_tag(job)
            # Remove the old reading-list folder if this promote produced a new slug
            if job.cleanup_dir:
                old = Path(job.cleanup_dir)
                if old.exists() and job.slug and old.name != job.slug:
                    shutil.rmtree(old, ignore_errors=True)
    except Exception as e:
        job.status = "error"
        job.error = str(e)
    finally:
        job.finished_at = time.time()
        # Clean up temp PDF (CLI already copied it as original.pdf inside the
        # paper folder)
        if job.is_pdf:
            try:
                Path(job.source).unlink(missing_ok=True)
            except Exception:
                pass


def _maybe_extract_slug(job: IngestJob, line: str) -> None:
    # CLI prints "✓ ready at: /Users/.../paper-reviews/<slug>"
    if "ready at:" in line:
        path = line.split("ready at:", 1)[1].strip()
        try:
            job.slug = Path(path).name
        except Exception:
            pass


def _restore_preserved_fields(job: IngestJob) -> None:
    """Restore tags / category in the new workbench.md after a promote ingest."""
    if not job.slug or not job.preserve_fields:
        return
    wb = SERVICE_ROOT / job.slug / "workbench.md"
    if not wb.exists():
        return
    text = wb.read_text()
    if "tags" in job.preserve_fields:
        from .tags import _set_tags_in_text
        text = _set_tags_in_text(text, job.preserve_fields["tags"])
    if job.preserve_fields.get("category"):
        cat = job.preserve_fields["category"]
        if re.search(r"^category:.*$", text, flags=re.MULTILINE):
            text = re.sub(r"^category:.*$", f'category: "{cat}"', text,
                          count=1, flags=re.MULTILINE)
    wb.write_text(text)


async def _auto_tag(job: IngestJob) -> None:
    """Best-effort auto-tagging at registration: derive 3-6 topical tags from
    the paper's title + abstract via a fast headless `claude -p` call. Skips
    silently if the workbench already has tags (manual or restored) or on any
    failure — auto-tagging must never break ingest."""
    if not job.slug:
        return
    paper_dir = SERVICE_ROOT / job.slug
    wb = paper_dir / "workbench.md"
    if not wb.exists():
        return
    try:
        import json as _json
        from .tags import _read_frontmatter_tags, _set_tags_in_text

        if _read_frontmatter_tags(wb):
            return  # already tagged — respect it

        title = abstract = ""
        pj = next(iter(paper_dir.glob("*_paper.json")), None)
        if pj:
            data = _json.loads(pj.read_text())
            meta = data.get("metadata", {}) if isinstance(data, dict) else {}
            title = meta.get("title", "") or meta.get("title_en", "")
            abstract = meta.get("abstract_en", "") or meta.get("abstract", "")
        if not (title or abstract):
            return

        prompt = (
            "Tag this academic paper for a personal reading library.\n"
            f"Title: {title}\n"
            f"Abstract: {abstract[:1500]}\n\n"
            "Output 3-6 short topical tags (model families, techniques, domains, "
            "task types) as ONE comma-separated line — no explanation, no prose. "
            "Good examples: VLM, diffusion, RAG, object-detection, RLHF, benchmark."
        )
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt, "--model", "haiku", "--max-turns", "1",
            limit=16 * 1024 * 1024,
            cwd=str(paper_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        text = out.decode("utf-8", "replace").strip()
        if not text:
            return
        line = [ln for ln in text.splitlines() if ln.strip()][-1]
        tags: list[str] = []
        seen: set[str] = set()
        for raw in line.split(","):
            t = raw.strip().strip('"').strip("'").lstrip("#").rstrip(".").strip()
            if not t or len(t) > 24:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            tags.append(t)
            if len(tags) >= 6:
                break
        if tags:
            wb.write_text(_set_tags_in_text(wb.read_text(), tags))
            job.log.append(f"✓ auto-tags: {', '.join(tags)}")
    except Exception as e:  # never fail ingest over tagging
        job.log.append(f"auto-tag skipped: {e}")


def _detect_slug_post_hoc(job: IngestJob) -> None:
    """Fallback: scan ~/.paper-reviews/* for folders modified after job start."""
    if not SERVICE_ROOT.exists():
        return
    candidates = []
    for d in SERVICE_ROOT.iterdir():
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        wb = d / "workbench.md"
        if not wb.exists():
            continue
        if wb.stat().st_mtime >= job.started_at - 1:
            candidates.append((wb.stat().st_mtime, d.name))
    if candidates:
        candidates.sort(reverse=True)
        job.slug = candidates[0][1]


def _serialize(job: IngestJob) -> dict:
    return {
        "job_id": job.job_id,
        "source": job.source,
        "is_pdf": job.is_pdf,
        "status": job.status,
        "slug": job.slug,
        "log_tail": job.log[-30:],
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
    }
