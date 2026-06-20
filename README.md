# paper-review

A local-first service for **collaborative review** — ingest a paper, blog, or web article, read and review it section-by-section together with Claude, then publish a polished blog draft. Runs entirely on your machine with a browser UI and a macOS menubar app.

> Built on top of the `paper-reader` translation engine. Connects to a Velog/Obsidian vault only at the publish step.

> **v2.0** — the workflow now covers **papers, engineering/release blogs, and
> general web articles** (paste any link; type is auto-detected), with a settings
> panel (themes, skill editor, illustrations) and tag-based card illustrations.
> See [Beyond papers](#beyond-papers) and the [CHANGELOG](./CHANGELOG.md). The
> academic-paper workflow remains the core.

## Screenshots

**Gallery** — reading list + dashboard (weekly-activity heatmap, KPIs, status funnel), color-coded hierarchical tags, star ratings, grid/list views.

![Gallery](docs/assets/gallery.png)

**Review page** — the original PDF and the review workbench side by side (resizable splitter, each pane toggleable), section navigator, WYSIWYG editing, live updates over SSE.

![Review page](docs/assets/review.png)

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

### Desktop app (macOS, recommended)

A standalone `.app` — no Python/clone needed.

- **Prebuilt**: grab `paper-review-<arch>.zip` from [Releases](https://github.com/Go-MinSeong/paper-review-service/releases),
  unzip, drag **paper-review.app** to `/Applications`, first launch right-click → **Open**.
- **Build it yourself**: `uv venv && uv pip install -e '.[dev]'` then
  `bash packaging/build.sh` → `dist/paper-review-<arch>.zip`.

Double-clicking opens a native window with the gallery; first launch installs
the skills into `~/.claude/skills`. **Review/chat need the
[Claude Code](https://claude.com/claude-code) CLI installed & signed in** (it
isn't bundled); ingest, browsing, and publish work without it.

### From source (macOS, no commands)

1. Download this repo: green **Code** button → **Download ZIP** → unzip.
2. Double-click **`setup.command`** inside the folder. It installs everything
   and builds the launcher app. (First time, Gatekeeper may block it —
   right-click `setup.command` → **Open** → **Open**.)
3. Double-click **`paper-review.app`** to start.

`setup.command` installs [`uv`](https://github.com/astral-sh/uv) if missing,
sets up the environment, links the skills, and builds the launcher.
You still need the [Claude Code](https://claude.com/claude-code) CLI installed
and signed in for the review/chat step — `setup.command` tells you if it's missing.

### Manual (developers)

Requires Python ≥ 3.10 and [`uv`](https://github.com/astral-sh/uv). macOS for the menubar app.

```bash
git clone https://github.com/Go-MinSeong/paper-review-service.git ~/Projects/paper-review-service
cd ~/Projects/paper-review-service
uv venv && uv pip install -e .
bash install-skills.sh        # symlink skills into ~/.claude/skills/
bash install-launcher.sh      # optional: build the double-click launcher app
```

Also requires the [Claude Code](https://claude.com/claude-code) CLI on your PATH (used for analysis and chat).

## Usage

### No-terminal launch (macOS, recommended for non-developers)

After the one-time install above, build a double-clickable launcher once:

```bash
bash install-launcher.sh --apps     # creates paper-review.app (and copies to ~/Applications)
```

Then **just double-click `paper-review.app`** — no Terminal, no commands. A ◫
icon appears in the menubar; click it → **Open Gallery**. From the gallery you
add content by pasting a link (paper / blog / web), review it in the chat dock,
and publish — all in the browser. Drag the app to the Dock to keep it handy.

### Commands (for development)

```bash
# Menubar app — ◫ icon, click → Open Gallery
paper-review menubar

# Or run the server directly
paper-review serve            # http://localhost:7300

# CLI
paper-review init <arxiv-id|pdf>     # full ingest
paper-review list                    # list papers + status
paper-review export-draft <slug>     # workbench → Velog draft
```

Everything else (registering papers, analyzing, tagging, reviewing, publishing) happens in the browser UI.

## Beyond papers

The ingest → review → publish pipeline is content-type aware, so the same flow
handles web content alongside papers:

| Type | Examples | Review skill |
|---|---|---|
| `paper` | arXiv / PDF | `paper-review` |
| `blog` | vLLM / PyTorch / company engineering & release posts | `blog-review` |
| `article` | news, op-eds, product / tech reviews, general web pages | `article-review` |

```bash
paper-review init https://some-blog.example/post   # auto-detects blog vs article
```

The source kind is detected automatically (arXiv ID/URL · PDF · web URL); web
content is classified as `blog` or `article` and reviewed with a matching
rubric (claims & tradeoffs for blogs, critical reading for articles). Web pages
can also be saved to the reading list (metadata only) and promoted later, and
their published drafts inline the article figures by section.

### Settings & illustrations

The gallery's ⚙ panel (top-right) switches **themes** (light/dark + Stripe,
Figma, Tesla, Sunset, Sage), views/edits the installed **skills**, and manages
the card **illustrations** (upload / soft-delete). Cards pick a thumbnail from
the illustration group mapped to their tags, so similar-tag items look
consistent (config in `server/illustration_groups.json`).

## Voice samples

`paper-publish` matches your writing tone using markdown samples in
`src/paper_review/publish/voice_samples/`. These are **git-ignored** (personal
writing) — drop 5–7 of your own paper-review markdown files there to enable tone
matching. Without them, publish still works (structural pass only).

## Architecture

Per-paper runtime state lives in `~/Projects/paper-review-service/<slug>/` (git-ignored):
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

Claude Code skills live in [`skills/`](./skills/). The core paper trio:

| Skill | Role |
|---|---|
| `paper-ingest` | arXiv/PDF (or web URL) → workbench skeleton + figures + viewer |
| `paper-review` | section-by-section interactive review (`/next-section`, `/explain`, `/finalize`) |
| `paper-publish` | workbench → Velog draft (kimjy99 structure + your voice) |

Plus two review skills for web content — `blog-review` and `article-review` —
which share the same engine as `paper-review` (see [Beyond papers](#beyond-papers)).

`bash install-skills.sh` symlinks them into `~/.claude/skills/` so the repo stays
the source of truth (edits are live). Pass `--copy` to copy instead of symlink.
Restart your Claude Code session after installing.
