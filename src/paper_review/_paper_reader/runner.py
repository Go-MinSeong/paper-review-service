"""Thin Python wrappers around the vendored paper-reader-v8 scripts.

Each function shells out to the corresponding script with explicit --out-dir,
so the original /tmp/papers default is never used.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import SCRIPTS_DIR, VIEWER_TEMPLATE


def _self_cmd() -> list[str]:
    """Command prefix that re-invokes this app/CLI's hidden `_run-script`
    dispatcher. In a PyInstaller bundle sys.executable is the app binary (which
    dispatches via cli.main); in dev it's python, so go through the module."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "_run-script"]
    return [sys.executable, "-m", "paper_review.cli", "_run-script"]


def _run(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Re-exec ourselves to run the vendored script in-process, so the pipeline
    # works whether running from source or a frozen .app (no `python <file>`).
    env = {**os.environ, "PR_RUN_SCRIPT": json.dumps(_self_cmd())}
    cmd = [*_self_cmd(), script, *args]
    res = subprocess.run(cmd, check=False, text=True, capture_output=True, env=env)
    if check and res.returncode:
        # check=True used to raise CalledProcessError here, which reaches the
        # user as a traceback ending in "returned non-zero exit status 1" — the
        # script's own message (why it failed, what to do instead) was captured
        # and thrown away. Callers format res.stderr; give them the chance.
        raise RuntimeError((res.stderr or res.stdout or "").strip() or f"{script} 실패")
    return res


def init_paper(
    source: str,
    out_dir: Path,
    *,
    is_pdf: bool = False,
) -> dict:
    """Run init_paper.py. Returns parsed paper.json after init."""
    args = ["--out-dir", str(out_dir)]
    args += ["--pdf", source] if is_pdf else [source]
    res = _run("init_paper.py", *args)
    if res.returncode != 0:
        raise RuntimeError(f"init_paper failed:\n{res.stderr}")
    slug = _find_slug(out_dir)
    paper_path = out_dir / f"{slug}_paper.json"
    return json.loads(paper_path.read_text())


def init_web(
    url: str,
    out_dir: Path,
    *,
    content_type: str = "auto",
    no_images: bool = False,
) -> dict:
    """Run fetch_web.py (web page → same source/sections/paper/figures layout).
    Returns parsed paper.json after init."""
    args = [url, "--out-dir", str(out_dir), "--content-type", content_type]
    if no_images:
        args.append("--no-images")
    res = _run("fetch_web.py", *args)
    if res.returncode != 0:
        raise RuntimeError(f"fetch_web failed:\n{res.stderr}")
    slug = _find_slug(out_dir)
    paper_path = out_dir / f"{slug}_paper.json"
    return json.loads(paper_path.read_text())


def fetch_figures(
    arxiv_id: str,
    out_dir: Path,
    slug: str,
    *,
    max_width: int = 800,
    jpeg_quality: int = 80,
) -> Path | None:
    """Run fetch_figures.py. Returns path to figures.json if produced."""
    args = [
        arxiv_id,
        "--out-dir",
        str(out_dir),
        "--max-width",
        str(max_width),
        "--jpeg-quality",
        str(jpeg_quality),
        "--source-text",
        str(out_dir / f"{slug}_source.txt"),
        "--sections-index",
        str(out_dir / f"{slug}_sections.txt"),
    ]
    res = _run("fetch_figures.py", *args, check=False)
    figs_path = out_dir / f"{slug}_figures.json"
    return figs_path if figs_path.exists() else None


def add_section(
    paper_json: Path,
    *,
    kind: str | None = None,
    data: Path | None = None,
    batch: Path | None = None,
) -> None:
    """Run add_section.py. Either (kind+data) or batch must be provided."""
    args = ["--paper", str(paper_json)]
    if batch:
        args += ["--batch", str(batch)]
    elif kind and data:
        args += ["--kind", kind, "--data", str(data)]
    else:
        raise ValueError("add_section requires either batch= or (kind=, data=)")
    res = _run("add_section.py", *args)
    if res.returncode != 0:
        raise RuntimeError(f"add_section failed:\n{res.stderr}")


def build_viewer(
    paper_json: Path, out_html: Path, *, skip_validate: bool = False
) -> None:
    """Run build_html.py to produce viewer.html."""
    args = [
        "--data",
        str(paper_json),
        "--template",
        str(VIEWER_TEMPLATE),
        "--out",
        str(out_html),
    ]
    if skip_validate:
        args.append("--skip-validate")
    res = _run("build_html.py", *args, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"build_html failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        )


def install_subagents() -> list[str]:
    """Copy paper-translator + github-investigator into ~/.claude/agents/."""
    from . import AGENTS_DIR

    dest = Path.home() / ".claude" / "agents"
    dest.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for md in AGENTS_DIR.glob("*.md"):
        target = dest / md.name
        target.write_text(md.read_text())
        installed.append(md.stem)
    return installed


def _find_slug(out_dir: Path) -> str:
    """Infer slug from a freshly-init'd output dir by looking for *_paper.json."""
    candidates = list(out_dir.glob("*_paper.json"))
    if not candidates:
        raise RuntimeError(f"No *_paper.json in {out_dir} after init")
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple *_paper.json in {out_dir}; ambiguous slug: {candidates}"
        )
    return candidates[0].name.removesuffix("_paper.json")
