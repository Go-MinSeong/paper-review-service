"""Tags backend: GET /tags (union) + PATCH /paper/<slug>/tags."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from .. import SERVICE_ROOT


class TagsPatchBody(BaseModel):
    tags: list[str]


def _parse_tags_value(value: str) -> list[str]:
    """Parse frontmatter `tags:` value. Supports `[a, b, c]` and `a, b, c` forms."""
    s = value.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [
        t.strip().strip('"').strip("'")
        for t in s.split(",")
        if t.strip().strip('"').strip("'")
    ]


def _read_frontmatter_tags(workbench_md: Path) -> list[str]:
    if not workbench_md.exists():
        return []
    text = workbench_md.read_text()
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---\n", 4)
    if end < 0:
        return []
    for line in text[4:end].splitlines():
        if line.startswith("tags:"):
            return _parse_tags_value(line.split(":", 1)[1])
    return []


def _set_tags_in_text(text: str, tags: list[str]) -> str:
    """Update or insert `tags:` line in frontmatter."""
    new_line = f"tags: [{', '.join(tags)}]"
    if re.search(r"^tags:.*$", text, flags=re.MULTILINE):
        return re.sub(r"^tags:.*$", new_line, text, count=1, flags=re.MULTILINE)
    # Insert after first frontmatter delimiter
    return re.sub(r"^---\n", f"---\n{new_line}\n", text, count=1)


def list_all_tags() -> dict:
    """Return {tag: count} across all papers. Sorted by count desc."""
    from ..library import iter_papers

    counter: Counter[str] = Counter()
    for d in iter_papers():
        counter.update(_read_frontmatter_tags(d / "workbench.md"))
    return {
        "tags": [{"name": t, "count": c} for t, c in counter.most_common()],
    }


def patch_paper_tags(slug: str, body: TagsPatchBody) -> dict:
    from ..library import paper_dir as _find

    paper_dir = _find(slug) or (SERVICE_ROOT / slug)
    wb = paper_dir / "workbench.md"
    if not wb.exists():
        from fastapi import HTTPException

        raise HTTPException(404, f"workbench not found for {slug}")
    text = wb.read_text()
    # Normalize tags: strip whitespace, dedupe (preserve order), filter empty
    seen = set()
    cleaned: list[str] = []
    for t in body.tags:
        s = t.strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    new_text = _set_tags_in_text(text, cleaned)
    wb.write_text(new_text)
    return {"ok": True, "tags": cleaned}


# ── Rating (1-5 stars; 0 clears) ─────────────────────────────────────────
class RatingPatchBody(BaseModel):
    rating: int


def _set_rating_in_text(text: str, rating: int) -> str:
    """Update / insert / remove the frontmatter `rating:` line."""
    if rating <= 0:
        return re.sub(r"^rating:.*\n?", "", text, count=1, flags=re.MULTILINE)
    new_line = f"rating: {rating}"
    if re.search(r"^rating:.*$", text, flags=re.MULTILINE):
        return re.sub(r"^rating:.*$", new_line, text, count=1, flags=re.MULTILINE)
    return re.sub(r"^---\n", f"---\n{new_line}\n", text, count=1)


def patch_paper_rating(slug: str, body: RatingPatchBody) -> dict:
    from ..library import paper_dir as _find

    _d = _find(slug)
    wb = (_d / "workbench.md") if _d else (SERVICE_ROOT / slug / "workbench.md")
    if not wb.exists():
        from fastapi import HTTPException

        raise HTTPException(404, f"workbench not found for {slug}")
    r = max(0, min(5, int(body.rating)))
    wb.write_text(_set_rating_in_text(wb.read_text(), r))
    return {"ok": True, "rating": r}


# ── Status (manual override from the gallery badge) ──────────────────────
STATUSES = ("to_read", "in_progress", "review_done", "exported", "archived")


class StatusPatchBody(BaseModel):
    status: str


def _set_status_in_text(text: str, status: str) -> str:
    """Update / insert the frontmatter `status:` line."""
    new_line = f"status: {status}"
    if re.search(r"^status:.*$", text, flags=re.MULTILINE):
        return re.sub(r"^status:.*$", new_line, text, count=1, flags=re.MULTILINE)
    return re.sub(r"^---\n", f"---\n{new_line}\n", text, count=1)


def _relocate(slug: str, status: str) -> None:
    """Keep the folder in the status directory the frontmatter now claims.

    Skipped while an analyze job is running in that folder: it is the cwd of a
    live `claude` process, and pulling it away mid-run breaks the run. The next
    status change or startup migration picks it up."""
    try:
        from .analyze import _jobs
        from ..library import move_to_status

        job = _jobs.get(slug)
        if job and job.status == "running":
            return
        move_to_status(slug, status)
    except Exception:
        pass  # a paper in the wrong folder still works; losing the edit doesn't


def patch_paper_status(slug: str, body: StatusPatchBody) -> dict:
    from fastapi import HTTPException

    if body.status not in STATUSES:
        raise HTTPException(400, f"invalid status: {body.status}")
    from ..library import paper_dir as _find

    _d = _find(slug)
    wb = (_d / "workbench.md") if _d else (SERVICE_ROOT / slug / "workbench.md")
    if not wb.exists():
        raise HTTPException(404, f"workbench not found for {slug}")
    wb.write_text(_set_status_in_text(wb.read_text(), body.status))
    _relocate(slug, body.status)
    return {"ok": True, "status": body.status}


class BulkBody(BaseModel):
    """A bulk edit over selected papers. Every field is optional so one call can
    do just what the user asked for."""

    slugs: list[str]
    status: str | None = None
    add_tags: list[str] = []
    remove_tags: list[str] = []


def bulk_edit(body: BulkBody) -> dict:
    """Apply status/tag changes to many papers at once.

    Doing this a card at a time doesn't scale — tagging an imported batch of 90
    meant 90 menus. Skips slugs that don't exist rather than failing the lot."""
    changed, missing = [], []
    for slug in body.slugs:
        from ..library import paper_dir as _find

        _d = _find(slug)
        wb = (_d / "workbench.md") if _d else (SERVICE_ROOT / slug / "workbench.md")
        if not wb.exists():
            missing.append(slug)
            continue
        text = wb.read_text()
        if body.status:
            text = _set_status_in_text(text, body.status)
        if body.add_tags or body.remove_tags:
            cur = _parse_tags_value(_frontmatter_field(text, "tags"))
            drop = {t.lower() for t in body.remove_tags}
            tags = [t for t in cur if t.lower() not in drop]
            for t in body.add_tags:
                if t and t.lower() not in {x.lower() for x in tags}:
                    tags.append(t)
            text = _set_tags_in_text(text, tags)
        wb.write_text(text)
        if body.status:
            _relocate(slug, body.status)
        changed.append(slug)
    return {"ok": True, "changed": changed, "missing": missing}


class TagRenameBody(BaseModel):
    old: str
    new: str = ""  # empty = remove the tag everywhere


def rename_tag(body: TagRenameBody) -> dict:
    """Rename (or delete) a tag across the whole library.

    Free-text tags drift — Agent/agents, LLM/LLM inference — and there was no
    way to merge them short of editing every paper."""
    old = body.old.strip()
    new = body.new.strip()
    if not old:
        raise HTTPException(400, "old tag required")
    touched = 0
    from ..library import iter_papers

    for d in iter_papers():
        wb = d / "workbench.md"
        text = wb.read_text()
        cur = _parse_tags_value(_frontmatter_field(text, "tags"))
        if old.lower() not in {t.lower() for t in cur}:
            continue
        out: list[str] = []
        for t in cur:
            t2 = new if t.lower() == old.lower() else t
            if t2 and t2.lower() not in {x.lower() for x in out}:
                out.append(t2)
        wb.write_text(_set_tags_in_text(text, out))
        touched += 1
    return {"ok": True, "renamed": old, "to": new, "papers": touched}


def _frontmatter_field(text: str, key: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end < 0:
        return ""
    for line in text[4:end].splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""
