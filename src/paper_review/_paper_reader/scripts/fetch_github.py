#!/usr/bin/env python3
"""
GitHub repo 정보 + 파일 트리 + README.

Usage:
    python fetch_github.py <github-url> [--max-depth 3] [--max-items 300]

Output: stdout JSON with:
    repo, url, description, language, stars, default_branch, tree_text, readme
"""

import re
import json
import argparse
import base64
import urllib.request

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "paper-reader/0.1",
}


def parse_repo(url: str):
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/?#\s]+)", url)
    if not m:
        raise ValueError(f"Not a GitHub URL: {url}")
    owner, repo = m.group(1), m.group(2)
    repo = re.sub(r"\.git$", "", repo)
    return owner, repo


def gh_get(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def render_tree(items, max_depth: int = 3, max_items: int = 300):
    """Render a flat list of git tree items into an indented text tree."""
    paths = sorted(item["path"] for item in items if "path" in item)
    types = {item["path"]: item.get("type", "blob") for item in items if "path" in item}

    # Filter by depth
    filtered = [p for p in paths if p.count("/") + 1 <= max_depth]
    if len(filtered) > max_items:
        filtered = filtered[:max_items]

    lines = []
    seen = set()
    for p in filtered:
        parts = p.split("/")
        # Add ancestor directories
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            if ancestor not in seen:
                seen.add(ancestor)
                indent = "  " * (i - 1)
                lines.append(f"{indent}{parts[i-1]}/")
        if p in seen:
            continue
        seen.add(p)
        indent = "  " * (len(parts) - 1)
        suffix = "/" if types.get(p) == "tree" else ""
        lines.append(f"{indent}{parts[-1]}{suffix}")
    return "\n".join(lines)


def fetch_readme(owner: str, repo: str) -> str:
    try:
        d = gh_get(f"https://api.github.com/repos/{owner}/{repo}/readme")
        return base64.b64decode(d["content"]).decode("utf-8", errors="replace")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-depth", type=int, default=3)
    ap.add_argument("--max-items", type=int, default=300)
    args = ap.parse_args()

    owner, repo = parse_repo(args.url)
    info = gh_get(f"https://api.github.com/repos/{owner}/{repo}")
    branch = info.get("default_branch", "main")
    tree = gh_get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    )
    readme = fetch_readme(owner, repo)

    out = {
        "repo": f"{owner}/{repo}",
        "url": f"https://github.com/{owner}/{repo}",
        "description": info.get("description") or "",
        "language": info.get("language") or "",
        "stars": info.get("stargazers_count", 0),
        "default_branch": branch,
        "tree_text": render_tree(
            tree.get("tree", []),
            max_depth=args.max_depth,
            max_items=args.max_items,
        ),
        "readme": readme[:10000],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
