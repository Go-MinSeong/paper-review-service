"""Settings endpoints: skills (view/edit) and illustrations (list/add/delete).

Both operate on the repo's source-of-truth directories:
  - skills/<name>/SKILL.md      (symlinked into ~/.claude/skills)
  - server/static/characters/   (card thumbnail pool)

All paths are whitelisted to those directories — no traversal, no escapes.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

_SERVER_DIR = Path(__file__).resolve().parent


def _skills_root() -> Path:
    """Where the bundled skills live.

    In a source checkout that's <repo>/skills (server → paper_review → src →
    repo). The frozen .app lays them out as _MEIPASS/skills, and parents[2]
    lands one level ABOVE _MEIPASS there — so Settings → 스킬 came up empty in
    the app while working fine in the browser."""
    import sys

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = meipass / "skills"
        if bundled.is_dir():
            return bundled
    return _SERVER_DIR.parents[2] / "skills"


SKILLS_DIR = _skills_root()
CHARS_DIR = _SERVER_DIR / "static" / "characters"
TRASH_DIR = CHARS_DIR / "_trash"
GROUPS_FILE = _SERVER_DIR / "illustration_groups.json"

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
        fm = _parse_frontmatter(sk.read_text(encoding="utf-8"))
        rows.append({"name": d.name, "description": fm.get("description", "")})
    return rows


def read_skill(name: str) -> str:
    return (_skill_dir(name) / "SKILL.md").read_text(encoding="utf-8")


def write_skill(name: str, content: str) -> None:
    if not content.strip():
        raise HTTPException(400, "empty content")
    (_skill_dir(name) / "SKILL.md").write_text(content, encoding="utf-8")


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


def _base_name(filename: str) -> str:
    """corgi-2.jpg / corgi.jpg → 'corgi' (strip extension and a -N variant suffix)."""
    stem = Path(filename).stem
    return re.sub(r"-\d+$", "", stem)


def illustration_groups() -> dict:
    """Groups + tag→group map. Group config lists character BASE NAMES; expand
    each to every existing file whose base name matches (base.jpg + base-N.jpg),
    so new variants join automatically. Returns
    {"groups": {name: [files]}, "tag_groups": {tag: group}}."""
    try:
        data = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"groups": {}, "tag_groups": {}}
    files_by_base: dict[str, list[str]] = {}
    for f in list_illustrations():
        files_by_base.setdefault(_base_name(f), []).append(f)
    groups: dict[str, list[str]] = {}
    for g, bases in (data.get("groups") or {}).items():
        files = [f for b in bases for f in files_by_base.get(b, [])]
        if files:
            groups[g] = sorted(files)
    tag_groups = {
        str(k).lower(): v
        for k, v in (data.get("tag_groups") or {}).items()
        if v in groups
    }
    return {"groups": groups, "tag_groups": tag_groups}


async def save_illustration(file: UploadFile, name: str = "") -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMG_EXTS:
        raise HTTPException(400, "only image files (jpg/png/gif/webp)")
    # Prefer a user-supplied base name (e.g. "corgi"); else the uploaded filename.
    raw = name.strip() or Path(file.filename or "img").stem
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-") or "img"
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
