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
        "모바일 원격 슬롯이 설정되지 않았습니다 — 설정 → 모바일에서 "
        "URL과 토큰을 입력하세요."
    )


def read_config() -> dict:
    """Stored config for the Settings UI ({} when unset). Never returns the
    token itself — only whether one is set."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except ValueError:
            cfg = {}
    env_url = os.environ.get("PAPER_REVIEW_REMOTE_URL")
    env_token = os.environ.get("PAPER_REVIEW_REMOTE_TOKEN")
    return {
        "url": env_url or cfg.get("url", ""),
        "token_set": bool(env_token or cfg.get("token")),
        "from_env": bool(env_url and env_token),
    }


def save_config(url: str, token: str | None) -> None:
    """Write the slot config. `token=None` keeps the stored one (so the UI can
    save a URL change without ever handling the secret); an empty url clears
    the whole config."""
    cur = {}
    if CONFIG_PATH.exists():
        try:
            cur = json.loads(CONFIG_PATH.read_text())
        except ValueError:
            cur = {}
    url = url.strip()
    token = cur.get("token", "") if token is None else token.strip()
    if not url:
        CONFIG_PATH.unlink(missing_ok=True)
        return
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL은 https://<app>.vercel.app 형식이어야 합니다")
    if not token:
        raise ValueError("토큰을 입력하세요")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"url": url.rstrip("/"), "token": token}))
    CONFIG_PATH.chmod(0o600)  # it holds a shared secret


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
    # Only what the mobile page needs to resolve a /fig/<id> reference. Tables
    # are extracted as HTML rather than an image — dropping them (as this used
    # to) left broken images on the phone for every table the review cites.
    out = []
    for f in items:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if f.get("data_uri"):
            out.append({"id": f["id"], "data_uri": f["data_uri"]})
        elif f.get("html"):
            out.append({"id": f["id"], "html": f["html"]})
    return out


def _inline_local_images(html: str, paper_dir: Path) -> str:
    """Reports may reference extracted files by relative path (extracted/…png)
    instead of a /fig/<id> route. Those paths only exist on this machine, so
    inline them as data URIs before the html goes to the phone."""
    import base64
    import mimetypes
    import re

    def repl(m: "re.Match[str]") -> str:
        rel = m.group(2)
        f = (paper_dir / rel).resolve()
        try:
            f.relative_to(paper_dir.resolve())  # stay inside the paper folder
            data = f.read_bytes()
        except (ValueError, OSError):
            return m.group(0)
        mime = mimetypes.guess_type(f.name)[0] or "image/png"
        return f'{m.group(1)}"data:{mime};base64,{base64.b64encode(data).decode()}"'

    return re.sub(r'(src=)"(?!https?:|data:|/)([^"]+)"', repl, html)


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
    # The Summary rides along read-only: the phone should show the same two
    # views as the desktop. report.md renders natively, but reports built before
    # it existed are html-only — send those as-is rather than showing an empty
    # Summary for a paper that clearly has one.
    report_md = service_root / slug / "report.md"
    report_html = service_root / slug / "report.html"
    payload = {
        "force": True,
        "slug": slug,
        "title": _title_of(md),
        "md": md,
        "report_md": report_md.read_text() if report_md.exists() else "",
        "report_html": (
            _inline_local_images(report_html.read_text(), service_root / slug)
            if report_html.exists() and not report_md.exists()
            else ""
        ),
        "figures": _load_figures(service_root / slug),
    }
    c = client or httpx.Client(timeout=60)
    try:
        r = c.put(_api(cfg), headers=_headers(cfg), json=payload)
        r.raise_for_status()
        out = r.json()
        out["url"] = cfg["url"]
        out["has_report"] = bool(payload["report_md"] or payload["report_html"])
    finally:
        if client is None:
            c.close()
    _write_slot_state(service_root, {"slug": slug, "rev": out.get("rev")})
    return out


SLOT_STATE = ".remote-slot.json"


def _write_slot_state(service_root: Path, state: dict) -> None:
    """Remember which paper the slot holds, so the gallery can mark it without
    a network round-trip. Best-effort — losing it only costs the badge."""
    import time

    state = {**state, "pushed_at": int(time.time())}
    try:
        (service_root / SLOT_STATE).write_text(json.dumps(state))
    except OSError:
        pass


def slot_state(service_root: Path) -> dict:
    """Which paper is currently on the phone ({} if none / never pushed)."""
    try:
        s = json.loads((service_root / SLOT_STATE).read_text())
        return s if isinstance(s, dict) and s.get("slug") else {}
    except (OSError, ValueError):
        return {}


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
