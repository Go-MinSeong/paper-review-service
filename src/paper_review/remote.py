"""Manual sync with the Vercel remote slot (mobile continuation).

One slot: `push(slug)` replaces it with a paper's workbench (+ figures);
`pull()` writes the slot's markdown back to the local workbench.md (after a
.bak backup). Config lives OUTSIDE the repo — never commit the token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

CONFIG_PATH = Path.home() / ".config" / "paper-review" / "remote.json"


def load_config() -> dict:
    url = os.environ.get("PAPER_REVIEW_REMOTE_URL")
    token = os.environ.get("PAPER_REVIEW_REMOTE_TOKEN")
    if url and token:
        return {"url": url, "token": token}
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        if cfg.get("url") and cfg.get("token"):
            return cfg
    raise RuntimeError(
        f"remote not configured — write {CONFIG_PATH} as "
        '{"url": "https://<app>.vercel.app", "token": "<REMOTE_TOKEN>"}'
    )


def _api(cfg: dict) -> str:
    return cfg["url"].rstrip("/") + "/api/doc"


def _headers(cfg: dict) -> dict:
    return {"x-token": cfg["token"], "Content-Type": "application/json"}


def _load_figures(paper_dir: Path) -> list[dict]:
    files = sorted(paper_dir.glob("*_figures.json"))
    if not files:
        return []
    try:
        data = json.loads(files[0].read_text())
    except Exception:
        return []
    items = data if isinstance(data, list) else data.get("figures", [])
    # only what the mobile page needs: id → data_uri
    return [
        {"id": f["id"], "data_uri": f["data_uri"]}
        for f in items
        if isinstance(f, dict) and f.get("id") and f.get("data_uri")
    ]


def _title_of(md: str) -> str:
    import re

    m = re.search(r'^title_ko:\s*"?(.*?)"?\s*$', md, re.MULTILINE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r'^title_en:\s*"?(.*?)"?\s*$', md, re.MULTILINE)
    return m.group(1).strip() if m else ""


def push(slug: str, service_root: Path, client: httpx.Client | None = None) -> dict:
    """Replace the remote slot with this paper's workbench."""
    cfg = load_config()
    wb = service_root / slug / "workbench.md"
    if not wb.exists():
        raise FileNotFoundError(f"workbench not found: {wb}")
    md = wb.read_text()
    payload = {
        "force": True,
        "slug": slug,
        "title": _title_of(md),
        "md": md,
        "figures": _load_figures(service_root / slug),
    }
    c = client or httpx.Client(timeout=60)
    try:
        r = c.put(_api(cfg), headers=_headers(cfg), json=payload)
        r.raise_for_status()
        out = r.json()
        out["url"] = cfg["url"]
        return out
    finally:
        if client is None:
            c.close()


def pull(service_root: Path, client: httpx.Client | None = None) -> dict:
    """Write the remote slot's markdown back to the local workbench.md."""
    cfg = load_config()
    c = client or httpx.Client(timeout=60)
    try:
        r = c.get(_api(cfg), headers={"x-token": cfg["token"]})
        r.raise_for_status()
        doc = r.json()
    finally:
        if client is None:
            c.close()
    if doc.get("empty") or not doc.get("md"):
        raise RuntimeError("remote slot is empty — push first")
    slug = doc.get("slug", "")
    wb = service_root / slug / "workbench.md"
    if not wb.exists():
        raise FileNotFoundError(f"local paper for slot not found: {wb}")
    local = wb.read_text()
    if local == doc["md"]:
        return {"slug": slug, "rev": doc.get("rev"), "changed": False}
    wb.with_suffix(".md.bak").write_text(local)  # safety net before overwrite
    wb.write_text(doc["md"])
    return {"slug": slug, "rev": doc.get("rev"), "changed": True}
