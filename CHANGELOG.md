# Changelog

## 2.2.14

### Fixed
- **Detail page hung on some math-heavy papers.** `marked` treated `$… internals
  (`_`, `*`) as markdown and split each math span across inline elements; KaTeX
  auto-render (`renderMathInElement`) then re-paired the loose ` across Korean
  prose into a giant bogus span whose layout froze the page. Math is now shielded
  from marked (placeholder swap) and each span is pre-rendered with
  `katex.renderToString` and spliced in — no whole-document delimiter walk. Also
  renders more math correctly (spans marked previously mangled).


## 2.2.13

### Fixed
- **Stray leading colon in the Wrap-up one-liner.** A workbench that wrote
  `**한 줄 contribution** : value` (space before colon) rendered as
  `한 줄 요약: : value`. `_extract_dash_field` now drops a leading colon from
  the extracted value.


## 2.2.12

### Fixed
- **Wrap-up (“## 정리”) dropped from published posts.** `_extract_dash_field`
  required a colon after the label (`**한 줄 contribution**:`), but a workbench that
  wrote the label on its own line with the body below (no colon) parsed empty, so
  the whole Wrap-up section was skipped at publish. The colon is now optional and
  the value may span the following lines.


## 2.2.11

### Changed
- **Reverted the math placeholder tokens.** 2.2.10 hid `$…$` behind `◆mathN◆`
  tokens in the editor, which leaked into view and read poorly. Math now shows as
  its `$…$` source again; the WYSIWYG backslash/`_`/`*` mangling is undone on save
  inside math spans instead (known ceiling: an escaped `\_` inside `\text{}`).
- **Inserted figures are centered in the editor** (`display:block; margin:auto`).

## 2.2.10

### Fixed
- **Editing no longer breaks LaTeX math.** The WYSIWYG editor mangled `$…$` /
  `$$…$$` (doubled backslashes, escaped `_`/`*`), corrupting KaTeX. Math is now
  swapped for opaque tokens before loading and restored verbatim on save —
  lossless, and correct LaTeX is never touched. (A one-off repair fixed 233
  already-mangled spans across existing review workbenches.)
- **Color no longer drops the selection.** The color picker popup collapsed the
  WYSIWYG selection, so you couldn't apply bold to the same text without
  re-selecting. The selection is now restored after a swatch is picked, allowing
  color → bold chaining.

## 2.2.9

### Fixed / Added
- **Themes now apply to the review (detail) page.** It only honored dark/light;
  the brand/original themes (stripe/figma/tesla/sunset/sage) set in the gallery
  were ignored. detail.css already had the rules — detail.js just wasn't setting
  `data-theme` for them.
- **Fullscreen toggle on the review page** (topbar button + `F` key) via the
  native Fullscreen API, to hide the browser chrome while reviewing.

## 2.2.8

### Fixed
- **Publish moved web figures around / dumped them to the end.** Two causes:
  (1) the publish renderer dropped each section's `원문 발췌` block — where the
  workbench keeps its figures — then re-inserted every figure by figures.json
  `section_heading`, ignoring the editor placement. Now figures the workbench
  already references are rendered in place (top of their section, with the real
  caption), and `_inline_web_figures` only rescues figures referenced nowhere.
  (2) The section parser ended the `섹션별 리뷰` block at *any* non-numbered H2,
  so a stray content heading (e.g. `## vLLM에서의 구현`) silently dropped every
  later section and its figures into the trailing `## 그림` dump. It now stops
  only at the known structural H2s (Q&A / Wrap-up / 메타 / 그림).

## 2.2.7

### Fixed
- **SVG figures (blog/article) couldn't be resized in the editor.** The WYSIWYG
  image rule had `max-width: 100%` but no `height: auto`, so SVG figures (which
  carry width+height attrs) collapsed to ~2px — leaving nothing to hover or
  drag. Added `height: auto` to match the read view; figures now render full
  size and the drag-resize handle attaches.

## 2.2.6

### Changed
- **Chat now uses the review skill that matches the content type.** Previously
  the chat always loaded `paper-review`; it now selects `blog-review` /
  `article-review` for web content (by `content_type` in the workbench
  frontmatter), so blogs and articles get their own rubric.

## 2.2.5

### Fixed
- **Chat "기재" requests didn't write to the workbench.** Asking the chat to
  record a question/answer/note often produced only a chat-panel reply, never an
  edit. The chat system prompt now has an explicit rule: record requests
  (기재/기록/메모/저장/추가) MUST Edit `workbench.md` (default target `## Q&A`,
  or the tied `### ` section), then confirm what was written. The plumbing was
  already in place (acceptEdits + Edit tool + SSE auto-reload on file change);
  this closes the instruction gap.

## 2.2.4

### Fixed
- **Garbled strip at the top of the list when scrolling.** The scroll container's
  top padding let cards bleed into a band above the sticky toolbar. Moved that
  spacing into the toolbar's own padding so its frosted background covers from the
  very top edge.
- **Type badge shown only on web content.** Papers had no type badge, so the grid
  looked inconsistent. Every card now shows its type (`PAPER` / `BLOG` / `ARTICLE`).

## 2.2.3

### Changed
- **Per-card "로그" button on the list.** Every gallery card now has a ▤ log
  button (next to 🏷/🗑) that opens the analyze-log modal in place — the log
  button moved off the detail topbar onto the list, where it's reachable for any
  paper without opening it. (The running pulse / "⚠ 분석 실패" chip still open it too.)
- **Illustrations dedup by character, not file.** A character isn't shown on two
  cards until every registered character has been used; variants of the same
  character (e.g. `redpanda` / `redpanda-2`) count as one. When a tag group runs
  out of unused characters, selection widens to the global pool so an unused
  character appears instead of repeating one.

## 2.2.2

### Changed
- **Analyze log reachable from the gallery (list page).** A running card's
  "분석 중" pulse and a "⚠ 분석 실패" chip (shown when a run errored or had failed
  sections) now open the full log modal in place — no need to open the detail
  page. `/papers/active-jobs` also reports finished error/failed jobs so the
  list can flag them.

## 2.2.1

### Changed (interface polish)
- Applied the *make-interfaces-feel-better* principles across the gallery,
  detail, and source views: scale-on-press (0.96) on buttons, subtle theme-aware
  1px image outlines on card illustrations / figures, `text-wrap: balance` on
  headings + `pretty` on body, font smoothing on the source pane, and
  transition-property-specific transitions (never `transition: all`).

## 2.2.0

### Added
- **Analyze log window** — a "로그" button (topbar + the progress toast) opens a
  modal with the full run log, status, and failed-section list, reachable any
  time (even after a clean run or a page reload). Backend keeps more log lines.

### Note
- If analysis "completes" but the workbench wasn't filled, it's the pre-2.1.1
  `--continue` failure — restart the menubar/server so the fix is live, then
  re-run; the log window now shows exactly what happened.

## 2.1.1

### Fixed
- **Auto-analysis silently aborting on freshly-ingested content.** Every claude
  call used `--continue`, but a just-ingested folder has no prior session, so
  the first call errored and every section failed. The first call of an analyze
  run now starts a fresh session (subsequent calls still chain with `--continue`).
- **Failures weren't visible.** The analyze toast now stays open (with the error
  log + a ✕ to close) whenever a run errors or any section fails, and re-attaches
  on page load — instead of auto-dismissing after a few seconds.

## 2.1.0

Packaged as a **standalone macOS app** (like data-manager) for one-download
accessibility — no Python/uv/clone needed.

### Added
- **Desktop .app** — `packaging/build.sh` produces `dist/paper-review-<arch>.zip`
  (PyInstaller bundle: FastAPI backend + vendored engine + UI). Double-click opens
  a native **pywebview** window over the local server. First launch copies the
  skills into `~/.claude/skills` and installs the subagents.
- `paper-review app` runs the same window in dev.

### Changed
- Vendored scripts now run via a self-re-exec dispatcher (`_run-script`) instead
  of `python <file>`, so the pipeline works inside a frozen bundle. uvicorn is
  started from the app object (import strings don't resolve when frozen). PATH is
  augmented at launch so a Finder-launched app still finds `claude`.

### Notes
- **Review/chat still require the Claude Code CLI** installed and signed in — it
  can't be bundled. ingest, browsing, and publish work without it.
- The app is ad-hoc signed: first launch needs right-click → Open.

## 2.0.0

Expands the service from papers-only to **papers, engineering/release blogs, and
general web articles**, and adds a settings surface.

### Added
- **Web content** — ingest any URL (`paper-review init <url>` or paste a link in
  the gallery). Source kind is auto-detected (arXiv · PDF · web) and web content
  is classified `blog` vs `article`. Web ingest extracts a clean markdown body,
  section index, and inline figures (incl. SVG) via `fetch_web.py`.
- **Per-type review skills** — `blog-review`, `article-review` alongside
  `paper-review`, sharing one engine (`_paper_reader/references/review-engine.md`).
- **Reading-list save for web** — save a URL with metadata only, promote to a
  full ingest later (▶ Analyze).
- **Publish by type** — `paper-publish` reshapes the workbench using a
  content-type-aware template (paper / blog / article); web drafts inline their
  figures by section.
- **Settings panel** (⚙, top-right of the gallery) — switch themes, view/edit
  installed skills, manage card illustrations (upload / soft-delete to _trash).
- **Themes** — light/dark plus brand-referenced (Stripe, Figma, Tesla — see
  `~/Documents/design/themes/`) and original (Sunset, Sage) themes, applied
  across the gallery, detail, and source viewer.
- **Illustration grouping** — cards pick a thumbnail from the group mapped to
  their tags (vision / language / generative / systems / general), spreading
  usage so similar-tag papers look consistent without repeating.
- **Source viewer** — web detail pages render the original article (figures
  placed inline by section) in place of the PDF pane.
- **Tests** — a pytest smoke suite (routes, skills, transform, settings).

### Fixed / hardened
- Figure-export path-traversal guard; HTML-escaped page titles; UTF-8 for
  skill/groups file I/O.

### Notes
- The skills directory is the source of truth, symlinked into `~/.claude/skills`
  via `install-skills.sh`. Changing server routes requires restarting the
  menubar app (templates/CSS/JS hot-reload on refresh).

## 0.1.0
- Initial release: arXiv/PDF paper ingest, section-by-section review with
  Claude, Velog draft export, FastAPI gallery + macOS menubar.
