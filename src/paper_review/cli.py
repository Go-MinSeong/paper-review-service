"""paper-review CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

from . import DEFAULT_PORT, SERVICE_ROOT, VELOG_DRAFTS_DIR
from ._paper_reader import runner
from .workbench import read_status, render_initial


@click.group()
@click.version_option()
def main() -> None:
    """Local paper review service — ingest, review with Claude, publish to Velog."""


_ARXIV_RE = re.compile(
    r"(?:arxiv\.org|^\d{4}\.\d{4,5}(?:v\d+)?$|^[a-z\-]+/\d{7}$)", re.I
)


def _source_kind(source: str) -> str:
    """Classify an init SOURCE → 'pdf' | 'arxiv' | 'web'."""
    if source.lower().endswith(".pdf"):
        return "pdf"
    if _ARXIV_RE.search(source):
        return "arxiv"
    if source.lower().startswith(("http://", "https://")):
        return "web"
    return "arxiv"  # bare token → assume arxiv id (legacy behavior)


@main.command()
@click.argument("source")
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    help="Override service root for this item (default: ~/Projects/paper-review-service/<slug>/).",
)
@click.option("--no-figures", is_flag=True, help="Skip figure/image extraction.")
@click.option(
    "--content-type",
    type=click.Choice(["blog", "article", "auto"]),
    default="auto",
    help="Web content type (web sources only; default auto-detect).",
)
@click.option(
    "--no-install-agents",
    is_flag=True,
    help="Skip installing paper-translator / github-investigator subagents.",
)
@click.option(
    "--force", "-f", is_flag=True, help="Overwrite existing folder without prompt."
)
def init(
    source: str,
    out_dir: Path | None,
    no_figures: bool,
    content_type: str,
    no_install_agents: bool,
    force: bool,
) -> None:
    """Ingest content. SOURCE = arxiv ID/URL, local PDF path, or web page URL."""
    kind = _source_kind(source)
    is_pdf = kind == "pdf"
    if is_pdf and not Path(source).exists():
        raise click.ClickException(f"PDF not found: {source}")

    SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
    staging = SERVICE_ROOT / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    if kind == "web":
        click.secho("→ fetch_web.py …", fg="cyan")
        paper = runner.init_web(
            source, staging, content_type=content_type, no_images=no_figures
        )
    else:
        click.secho("→ init_paper.py …", fg="cyan")
        paper = runner.init_paper(source, staging, is_pdf=is_pdf)
    slug = paper["metadata"].get("slug") or runner._find_slug(staging)

    final_dir = out_dir or (SERVICE_ROOT / slug)
    if final_dir.exists():
        if not force and not click.confirm(
            f"{final_dir} already exists. Overwrite?", default=False
        ):
            shutil.rmtree(staging)
            raise click.Abort()
        shutil.rmtree(final_dir)
    final_dir.mkdir(parents=True)

    for f in staging.iterdir():
        shutil.move(str(f), final_dir / f.name)
    shutil.rmtree(staging)

    if is_pdf:
        shutil.copy(source, final_dir / "original.pdf")

    paper_json = final_dir / f"{slug}_paper.json"

    arxiv_id = paper["metadata"].get("arxiv_id")
    if not no_figures and arxiv_id:
        click.secho("→ fetch_figures.py …", fg="cyan")
        figs_path = runner.fetch_figures(arxiv_id, final_dir, slug)
        if figs_path:
            click.secho(f"   figures.json: {figs_path.name}", dim=True)
        else:
            click.secho(
                "   (no figures extracted — paper may be non-arXiv or ar5iv missing)",
                fg="yellow",
            )

    click.secho("→ writing workbench.md skeleton …", fg="cyan")
    (final_dir / "workbench.md").write_text(render_initial(final_dir, slug))

    click.secho("→ build_html.py (viewer) …", fg="cyan")
    try:
        runner.build_viewer(
            paper_json,
            final_dir / "viewer.html",
            skip_validate=True,
        )
    except RuntimeError as e:
        click.secho(f"   viewer build failed (will retry later): {e}", fg="yellow")

    if not no_install_agents:
        installed = runner.install_subagents()
        if installed:
            click.secho(f"→ installed subagents: {', '.join(installed)}", fg="cyan")

    click.secho(f"\n✓ ready at: {final_dir}", fg="green")
    click.echo(f"  workbench: {final_dir / 'workbench.md'}")
    click.echo(f"  viewer:    {final_dir / 'viewer.html'}")
    click.echo()
    click.echo("Next:")
    click.echo(f"  paper-review session {slug}     # cd + claude")
    click.echo(f"  paper-review serve              # localhost:{DEFAULT_PORT}")


@main.command(name="list")
def list_cmd() -> None:
    """List all papers under the service root with their status."""
    if not SERVICE_ROOT.exists():
        click.echo("(no papers yet)")
        return
    rows = []
    for d in sorted(SERVICE_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        wb = d / "workbench.md"
        if not wb.exists():
            continue
        rows.append((d.name, read_status(wb)))
    if not rows:
        click.echo("(no papers yet)")
        return
    width = max(len(s) for s, _ in rows)
    for slug, status in rows:
        click.echo(f"  {slug.ljust(width)}  {status}")


@main.command()
@click.argument("slug")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation.")
def rm(slug: str, yes: bool) -> None:
    """Delete a paper's working directory."""
    target = SERVICE_ROOT / slug
    if not target.exists():
        raise click.ClickException(f"Not found: {target}")
    if not yes and not click.confirm(f"Delete {target}?", default=False):
        raise click.Abort()
    shutil.rmtree(target)
    click.secho(f"✓ removed {target}", fg="green")


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=DEFAULT_PORT, type=int)
def serve(host: str, port: int) -> None:
    """Start the local FastAPI server (read-only gallery + paper detail)."""
    try:
        import uvicorn
    except ImportError:
        raise click.ClickException("uvicorn not installed. Run: uv pip install -e .")
    from .server.app import app as fastapi_app

    click.secho(f"→ paper-review serve on http://{host}:{port}", fg="cyan")
    uvicorn.run(fastapi_app, host=host, port=port, reload=False)


@main.command()
@click.option("--port", default=DEFAULT_PORT, type=int)
@click.option(
    "--auto-open/--no-auto-open",
    default=False,
    help="Open the gallery in browser when the server starts.",
)
def menubar(port: int, auto_open: bool) -> None:
    """Run the macOS menubar app (server + click-to-open gallery)."""
    if sys.platform != "darwin":
        raise click.ClickException("menubar mode is macOS-only.")
    from .menubar import PaperReviewMenubarApp

    PaperReviewMenubarApp(port=port, auto_open=auto_open).run()


@main.command()
def app() -> None:
    """Launch the desktop app (native window over the local server)."""
    from .app import run_app

    run_app()


@main.command()
@click.argument("slug")
def session(slug: str) -> None:
    """cd into the paper's folder and launch claude."""
    target = SERVICE_ROOT / slug
    if not target.exists():
        raise click.ClickException(f"Not found: {target}")
    click.secho(f"→ starting claude in {target}", fg="cyan")
    try:
        subprocess.run(["claude"], cwd=str(target), check=False)
    except FileNotFoundError:
        raise click.ClickException("`claude` CLI not found on PATH.")


@main.command(name="export-draft")
@click.argument("slug")
@click.option(
    "--drafts-dir",
    type=click.Path(path_type=Path),
    default=VELOG_DRAFTS_DIR,
    help="Where to write the Velog draft.",
)
def export_draft(slug: str, drafts_dir: Path) -> None:
    """Transform workbench.md → Velog draft markdown in drafts/."""
    from .publish.transform import workbench_to_draft

    src = SERVICE_ROOT / slug / "workbench.md"
    if not src.exists():
        raise click.ClickException(f"workbench.md not found: {src}")
    drafts_dir.mkdir(parents=True, exist_ok=True)
    dest = drafts_dir / f"{slug}.md"
    workbench_to_draft(src, dest, paper_dir=SERVICE_ROOT / slug)
    click.secho(f"✓ wrote {dest}", fg="green")


@main.command(
    name="_run-script",
    hidden=True,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("script")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _run_script(script: str, args: tuple[str, ...]) -> None:
    """Internal: run a vendored _paper_reader script in-process so the pipeline
    works in a frozen .app (where `python <file>` isn't available). Invoked by
    runner._run via self-re-exec."""
    import importlib.util

    from ._paper_reader import SCRIPTS_DIR

    # Put the scripts dir on sys.path so sibling imports (e.g. fetch_web's
    # `from fetch_figures import ...`) resolve, then load the target by file
    # path — robust whether running from source or a frozen bundle.
    sys.path.insert(0, str(SCRIPTS_DIR))
    name = Path(script).stem
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    saved = sys.argv
    sys.argv = [script, *args]
    try:
        mod.main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    main()
