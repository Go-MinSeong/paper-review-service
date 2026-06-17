"""Settings endpoints: skills (view/edit) and illustrations (list/add/delete).

Both operate on the repo's source-of-truth directories:
  - skills/<name>/SKILL.md      (symlinked into ~/.claude/skills)
  - server/static/characters/   (card thumbnail pool)

All paths are whitelisted to those directories — no traversal, no escapes.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

_SERVER_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SERVER_DIR.parents[2]  # server → paper_review → src → repo
SKILLS_DIR = _REPO_ROOT / "skills"
CHARS_DIR = _SERVER_DIR / "static" / "characters"
TRASH_DIR = CHARS_DIR / "_trash"

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# ── Skills ────────────────────────────────────────────────────────────────
def _skill_dir(name: str) -> Path:
    """Resolve a skill name to its directory, guarding against traversal."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
        raise HTTPException(400, "bad skill name")
    d = SKILLS_DIR / name
    if not (d.is_dir() and (d / "SKILL.md").is_file()):
        raise HTTPException(404, f"unknown skill {name!r}")
    return d


def _parse_frontmatter(md: str) -> dict:
    if not md.startswith("---"):
        return {}
    end = md.find("\n---", 3)
    if end < 0:
        return {}
    out: dict = {}
    for line in md[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"')
    return out


def list_skills() -> list[dict]:
    if not SKILLS_DIR.is_dir():
        return []
    rows = []
    for d in sorted(SKILLS_DIR.iterdir()):
        sk = d / "SKILL.md"
        if not sk.is_file():
            continue
        fm = _parse_frontmatter(sk.read_text())
        rows.append({"name": d.name, "description": fm.get("description", "")})
    return rows


def read_skill(name: str) -> str:
    return (_skill_dir(name) / "SKILL.md").read_text()


def write_skill(name: str, content: str) -> None:
    if not content.strip():
        raise HTTPException(400, "empty content")
    (_skill_dir(name) / "SKILL.md").write_text(content)


# ── Illustrations ───────────────────────────────────────────────────────────
def _safe_char_name(name: str) -> str:
    """A characters/ filename, no path parts, image extension only."""
    base = Path(name or "").name
    if base != name or base.startswith("."):
        raise HTTPException(400, "bad filename")
    if Path(base).suffix.lower() not in _IMG_EXTS:
        raise HTTPException(400, "not an image")
    return base


def list_illustrations() -> list[str]:
    if not CHARS_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in CHARS_DIR.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _IMG_EXTS
    )


async def save_illustration(file: UploadFile) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMG_EXTS:
        raise HTTPException(400, "only image files (jpg/png/gif/webp)")
    stem = (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(file.filename or "img").stem).strip("-")
        or "img"
    )
    CHARS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CHARS_DIR / f"{stem}{ext}"
    n = 2
    while dest.exists():
        dest = CHARS_DIR / f"{stem}-{n}{ext}"
        n += 1
    dest.write_bytes(await file.read())
    return dest.name


def trash_illustration(name: str) -> None:
    safe = _safe_char_name(name)
    src = CHARS_DIR / safe
    if not src.is_file():
        raise HTTPException(404, "not found")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = TRASH_DIR / safe
    n = 2
    while dest.exists():
        dest = TRASH_DIR / f"{Path(safe).stem}-{n}{Path(safe).suffix}"
        n += 1
    shutil.move(str(src), str(dest))
