"""Tags backend: GET /tags (union) + PATCH /paper/<slug>/tags."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

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
    counter: Counter[str] = Counter()
    if SERVICE_ROOT.exists():
        for d in SERVICE_ROOT.iterdir():
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            wb = d / "workbench.md"
            counter.update(_read_frontmatter_tags(wb))
    return {
        "tags": [
            {"name": t, "count": c}
            for t, c in counter.most_common()
        ],
    }


def patch_paper_tags(slug: str, body: TagsPatchBody) -> dict:
    paper_dir = SERVICE_ROOT / slug
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
