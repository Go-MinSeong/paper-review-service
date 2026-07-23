# Changelog

## 2.4.6

### Fixed
- **Report pane STILL visible at the bottom of Detail (root cause).** The
  `hidden` attribute relies on the UA's `display: none`, but our author rule
  `.pane.report { display: flex }` overrides UA styles by cascade origin — so
  every `hidden` toggle on the pane silently never worked (behind all the
  "창이 여전히 열려 있다" reports). Added `[hidden] { display: none
  !important; }` so the attribute always wins; verified with computed styles
  this time.


## 2.4.5

### Changed (review-page UX)
- **No more report bars/banners.** The in-pane "구조화 리포트 —…" bar and the
  "구조화 리포트 없음 —…" banner are gone. Report generation/regeneration is a
  single topbar button shown only in Summary; open-in-tab / fullscreen are
  hover-only overlay buttons on the report pane.
- **PDF export follows the screen.** In Summary with a report, the PDF button
  prints the report; in Detail it prints the workbench (as before).
- **Per-pane fullscreen.** Hover ⛶ on the 원문 pane, the review pane, and the
  report pane fullscreens just that pane (the topbar F button still
  fullscreens the whole page).
- **Mobile push moved to the gallery.** The 📱 button now lives on each list
  card (slot swapping is a list-level action); removed from the detail topbar.


## 2.4.4

### Security
- **Pretty URL is now this-Mac-only.** 2.4.3's port-80 listener followed the
  main --host (0.0.0.0) and advertised the LAN IP over mDNS — widening LAN
  exposure. macOS only permits unprivileged low-port binds on the wildcard
  address, so the :80 socket stays wildcard but a middleware now rejects any
  non-loopback client on port 80 (403), and mDNS advertises 127.0.0.1. The
  main :7300 keeps its existing policy (LAN access for phones) unchanged.


## 2.4.3

### Added
- **Pretty URL: http://paper-review.local/** — serve now also binds port 80
  (unprivileged on macOS) and registers the mDNS name via `dns-sd -P`,
  advertising the LAN IP so phones on the same Wi-Fi can use the same
  address. Menubar menu/open use it when available; falls back to
  http://127.0.0.1:7300 when port 80 or dns-sd is unavailable.


## 2.4.2

### Fixed
- **Report view sticking to every paper.** The Summary/Detail choice was a
  single global key, so opening the report once made EVERY paper open in the
  report view (with its top bar). The view is now remembered per paper
  (default: Detail). The no-report generate banner also shrank to one line.

### Added
- **Configurable publish path (Settings → 경로).** The Obsidian/velog vault
  drafts folder is no longer hardcoded: set it in the gallery settings (stored
  in ~/.config/paper-review/settings.json; PAPER_REVIEW_DRAFTS_DIR env
  overrides; empty = legacy default). Publish routes and `export-draft` use it.


## 2.4.1

### Fixed
- **Report pane leaking into the Detail view.** Rapid Summary↔Detail toggling
  let the async report check resolve late and re-show the pane over Detail;
  showReportPane now bails unless the current view is summary. The "리포트
  생성" banner also moved from the bottom (next to chat) to ABOVE the summary.


## 2.4.0

### Added
- **Structured review report (최종 정리) in the Summary view.** A "구조화
  리포트 생성" button builds a single-file report.html from the finished
  review — 00 TL;DR → 01 개념 → 02 배경 → 03 방법론 → 04 실험 → 05 한계 →
  06 후속 연구, with hero key numbers, prior-work timeline, result bars /
  stat boxes, paper figures (same-origin), scope-discipline callouts,
  ⚠️ 논문 명시 / 🔍 리뷰 중 발견 limitation split, and WebSearch-backed
  follow-up papers. The reviewer's 내 정리/Q&A are woven in. Summary tab
  shows the report once generated (새 탭/재생성 bar); until then it keeps
  the label-filtered summary with a generate banner. Template adapted from
  the team review guide (+ dark mode).

### Changed
- **Scope discipline in analysis prompts.** Section analysis and the
  paper-review skill now separate the paper's claims from general-knowledge
  inference ("논문 밖 일반론", "논문에 명시되지 않음"), require symbol
  definitions/concrete numbers in method sections, and structure experiment
  summaries as 실험 목적 → 결과 → 해석.


## 2.3.0

### Added
- **Mobile continuation (remote slot).** A tiny Vercel app (`remote/`, monorepo
  subfolder) holds ONE paper's workbench + figures. Push from the detail page
  (📱 button) or `paper-review remote push <slug>`; edit on the phone
  (section-level ✏️ editing, KaTeX/figures rendered, frontmatter via ⚙);
  pull back from the gallery (📥 button) or `paper-review remote pull`
  (backs up workbench.md.bak first). Manual sync only; optimistic rev check
  guards concurrent edits. Config in ~/.config/paper-review/remote.json.


## 2.2.18

### Added
- **Actionable hint on Claude CLI auth expiry.** When an analyze section fails
  with an authentication/OAuth error, the log now appends: re-login with
  `claude auth login`, then re-run Analyze (no server restart needed).
- Tests for the status PATCH helpers/route (missed in 2.2.16) and the auth hint.


## 2.2.17

### Changed
- **Status menu labels are now English** (Reading / In progress / Reviewed /
  Exported / Archived) to match the badges and sidebar.


## 2.2.16

### Added
- **Manual status change from the gallery.** Click a card's status badge to open
  a menu and set the status (읽을 예정 / 리뷰 중 / 완료 / 발행 / 보관). New
  `PATCH /paper/<slug>/status` writes it to the workbench frontmatter.
- **Archived status.** The default "All" view (and its count) hide archived
  papers; a new **Archived** sidebar filter shows them.


## 2.2.15

### Fixed
- **Pipeline player, hero card, mermaid, image-resize, and section anchors gone
  (2.2.14 regression).** The 2.2.14 math-render rewrite accidentally removed the
  post-render calls (h3/h1/h2 ids, annotateBlocksByLabel, wrapHeroCard,
  renderPipelinePlayers, injectPipelineGenButton, renderMermaid,
  setupResizableImages) that run after the workbench HTML is inserted. Restored
  them; the animated pipeline (and the auto-generate button when absent) render
  again, and math still pre-renders correctly.


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
