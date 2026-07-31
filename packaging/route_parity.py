#!/usr/bin/env python3
"""Compare what the bundled app serves against what the source serves.

The .app reads templates, static files, skills and assets from inside the
bundle; a source checkout reads them from the tree. Anything the packaging spec
forgets is invisible until someone opens that screen in the app — Settings →
스킬 shipped empty for weeks because `parents[2]` means something different
inside _MEIPASS, and every check had been done in a browser against the source.

    python packaging/route_parity.py http://127.0.0.1:8801 http://127.0.0.1:8802

Exits non-zero on the first difference, so CI can gate a release on it.
"""

from __future__ import annotations

import json
import sys

import httpx

# Routes whose responses come from bundled files. Paper-scoped routes are
# covered by the fixture paper both servers are pointed at.
ROUTES = [
    "/",
    "/skills",
    "/illustrations",
    "/illustration-groups",
    "/tags",
    "/settings",
    "/papers.json",
    "/papers/active-jobs",
    "/static/gallery.js",
    "/static/detail.js",
    "/static/gallery.css",
    "/static/detail.css",
    "/static/ui-dialog.js",
    "/paper/fixture",
    "/paper/fixture/workbench.md",
    "/paper/fixture/analyze/status",
]

# The gallery HTML embeds the port and asset mtimes, so byte equality is the
# wrong test there; compare the shape instead.
SIZE_TOLERANT = {"/", "/paper/fixture"}

# A dev machine can hold illustrations that are deliberately not shipped (the
# third-party character art is gitignored and excluded from the bundle), so the
# lists are allowed to differ — but the bundle's must be non-empty and a subset.
# Empty is the signature of packaging having forgotten the directory.
SUBSET_OK = {"/illustrations", "/illustration-groups"}


def _get(client: httpx.Client, base: str, route: str):
    r = client.get(base + route, timeout=30)
    return r.status_code, r.content


def main() -> int:
    app_base, src_base = sys.argv[1], sys.argv[2]
    problems: list[str] = []
    with httpx.Client() as c:
        for route in ROUTES:
            a_code, a_body = _get(c, app_base, route)
            s_code, s_body = _get(c, src_base, route)

            if a_code != s_code:
                problems.append(f"{route}: app {a_code} vs source {s_code}")
                continue
            if route in SIZE_TOLERANT:
                # a page that renders at all is enough; its bytes carry the port
                if not a_body.strip():
                    problems.append(f"{route}: app served an empty page")
                continue
            if route in SUBSET_OK:
                a_json, s_json = json.loads(a_body), json.loads(s_body)
                a_items = a_json if isinstance(a_json, list) else a_json.get("groups", {})
                s_items = s_json if isinstance(s_json, list) else s_json.get("groups", {})
                if not a_items:
                    problems.append(f"{route}: the bundle serves nothing")
                elif set(a_items) - set(s_items):
                    problems.append(
                        f"{route}: bundle has entries the source doesn't: "
                        f"{sorted(set(a_items) - set(s_items))[:3]}"
                    )
                else:
                    print(f"  ok   {route} ({len(a_items)} in bundle ⊆ {len(s_items)})")
                continue
            if a_body == s_body:
                print(f"  ok   {route}")
                continue

            # JSON that differs: an empty list from the bundle is the classic
            # "the packaging spec forgot this directory" signature.
            try:
                a_json, s_json = json.loads(a_body), json.loads(s_body)
            except ValueError:
                problems.append(
                    f"{route}: bodies differ ({len(a_body)}B app / {len(s_body)}B source)"
                )
                continue
            if isinstance(a_json, list) and isinstance(s_json, list):
                if len(a_json) != len(s_json):
                    problems.append(
                        f"{route}: app has {len(a_json)} items, source has {len(s_json)}"
                    )
                    continue
            elif a_json != s_json:
                problems.append(f"{route}: JSON differs")
                continue
            print(f"  ok   {route} (equivalent)")

    if problems:
        print("\nthe bundle does not match the source:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"\n{len(ROUTES)} routes match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
