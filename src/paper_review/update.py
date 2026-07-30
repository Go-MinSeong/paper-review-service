"""Is a newer release out?

The app has no way to tell you a new version exists — you'd have to remember to
look at GitHub. This asks the releases API and the UI shows a quiet chip; it
never downloads or installs anything.

Deliberately tolerant: no network, rate limits, a repo without releases, or a
version string we can't parse all mean "no update", never an error the user has
to deal with.
"""

from __future__ import annotations

import re
import time

REPO = "Go-MinSeong/paper-review-service"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_CACHE_TTL = 6 * 3600  # the answer changes at most a few times a week
_cache: dict = {"at": 0.0, "value": None}


def _parse(v: str) -> tuple[int, ...] | None:
    """'v2.16.1' → (2, 16, 1). None when it isn't a plain release version, so a
    dev build like '2.17.0.dev1' never claims to be newer or older."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def check(force: bool = False) -> dict:
    """{current, latest, url, newer}. Cached; safe to call on every page load."""
    from . import __version__

    now = time.time()
    if not force and _cache["value"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["value"]

    out = {"current": __version__, "latest": None, "url": None, "newer": False}
    try:
        import httpx

        r = httpx.get(
            API,
            timeout=6,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"paper-review/{__version__}",
            },
        )
        if r.status_code == 200:
            data = r.json()
            tag = data.get("tag_name") or ""
            out["latest"] = tag.lstrip("v") or None
            out["url"] = data.get("html_url")
            here, there = _parse(__version__), _parse(tag)
            out["newer"] = bool(here and there and there > here)
    except Exception:
        pass  # offline / rate-limited / malformed — just don't nag

    _cache.update(at=now, value=out)
    return out
