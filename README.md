# paper-review

A local-first service for **collaborative paper review** — ingest a paper, read and review it section-by-section together with Claude, then publish a polished blog draft. Runs entirely on your machine with a browser UI and a macOS menubar app.

> Built on top of the `paper-reader` translation engine. Connects to a Velog/Obsidian vault only at the publish step.

## What it does

```
arXiv/PDF ──► ingest ──► review (with Claude) ──► publish ──► Velog draft
              (5 min)     (~2 h interactive)        (1 click)
```

- **Reading list / archive** — save papers (arXiv metadata only) and organize them with **hierarchical tags** (`CV/segmentation`, `NLP/transformer`). Promote to full analysis when you're ready.
- **Auto-analysis** — section-by-section Korean translation + summary + Reader's Notes + probing questions, driven by headless Claude Code. Resumable, cancellable, with partial-failure retry.
- **Collaborative review** — a chat dock wired to `claude -p` runs inside each paper's folder; the workbench markdown is the single source of truth and updates live (SSE).
- **Publish** — reshapes the workbench into a kimjy99-style draft (your voice + Claude's translation), drops it into `~/Documents/velog-vault/drafts/`.
- **UI** — gallery with a left depth-sidebar (status + tag tree), live PDF + workbench panes, figure gallery (images & tables), summary/detail toggle, model picker, dark/light themes (Linear-dark / Apple-light design tokens).
- **macOS menubar app** — one click to start the server and open the gallery.

## Install

Requires Python ≥ 3.10 and [`uv`](https://github.com/astral-sh/uv). macOS for the menubar app.

```bash
git clone https://github.com/Go-MinSeong/paper-review-service.git ~/.paper-reviews
cd ~/.paper-reviews
uv venv && uv pip install -e .
bash install-skills.sh        # symlink the 3 skills into ~/.claude/skills/
```

Also requires the [Claude Code](https://claude.com/claude-code) CLI on your PATH (used for analysis and chat).

## Usage

```bash
# Menubar app (recommended) — ◫ icon, click → Open Gallery
paper-review menubar

# Or run the server directly
paper-review serve            # http://localhost:7300

# CLI
paper-review init <arxiv-id|pdf>     # full ingest
paper-review list                    # list papers + status
paper-review export-draft <slug>     # workbench → Velog draft
```

Everything else (registering papers, analyzing, tagging, reviewing, publishing) happens in the browser UI.

## Voice samples

`paper-publish` matches your writing tone using markdown samples in
`src/paper_review/publish/voice_samples/`. These are **git-ignored** (personal
writing) — drop 5–7 of your own paper-review markdown files there to enable tone
matching. Without them, publish still works (structural pass only).

## Architecture

Per-paper runtime state lives in `~/.paper-reviews/<slug>/` (git-ignored):
`workbench.md` (source of truth), `paper.json`, `source.txt`, `viewer.html`, figures, original PDF.

The package (`src/paper_review/`):

| Module | Role |
|---|---|
| `cli.py` | `init / list / rm / serve / session / export-draft / menubar` |
| `server/app.py` | FastAPI routes, gallery/detail templates |
| `server/{ingest,analyze,chat,save,tags}.py` | background jobs + endpoints |
| `server/{templates,static}/` | gallery + detail UI (HTML/CSS/JS) |
| `publish/{parser,transform}.py` | workbench → draft |
| `_paper_reader/` | vendored translation engine (init, figures, build_html) |
| `menubar.py` | macOS menubar app (rumps) |

See [`DESIGN.md`](./DESIGN.md) for the full design rationale and locked decisions.

## Skills

Three Claude Code skills live in [`skills/`](./skills/):

| Skill | Role |
|---|---|
| `paper-ingest` | arXiv/PDF → workbench skeleton + figures + viewer |
| `paper-review` | section-by-section interactive review (`/next-section`, `/explain`, `/finalize`) |
| `paper-publish` | workbench → Velog draft (kimjy99 structure + your voice) |

`bash install-skills.sh` symlinks them into `~/.claude/skills/` so the repo stays
the source of truth (edits are live). Pass `--copy` to copy instead of symlink.
Restart your Claude Code session after installing.
