# Changelog

## 2.16.0

### Added
- **Zoom for the source PDF, on its own.** WebKit draws the PDF with a native
  plugin inside an iframe, so it can't be zoomed from inside and page zoom would
  scale the whole review. The pane scales the iframe instead — trackpad pinch
  (ctrl+wheel) plus **−/+/⤾** buttons in the pane's hover actions, remembered
  per paper.

### Changed
- **Search now reaches archived papers.** With 97 of 109 papers archived,
  typing a query in the default view returned nothing and you had to know to
  switch to Archived first. Archived stays hidden while browsing, appears while
  searching, and the result count says how many came from the archive.


## 2.15.5

### Fixed
- **Pinch-to-zoom didn't work on the source PDF in the desktop app.** pywebview
  creates windows with `zoomable=False` by default and then injects a handler
  that `preventDefault`s ctrl+wheel — which is exactly what a macOS trackpad
  pinch sends. The same PDF zooms fine in a browser; the window now opts in.


## 2.15.4

### Fixed
- **The gallery flickered on every selection click.** Picking a card re-rendered
  the whole grid — 109 cards and their illustrations — just to toggle one
  checkbox. Selection now updates the affected nodes in place: zero grid
  rebuilds, zero image reloads.
- **Double-clicking the top of the window didn't maximise it.** Taking over the
  title bar area for dragging also took over its double-click; it now performs
  the system action (zoom, or minimise if that's what System Settings ›
  Desktop & Dock says).


## 2.15.3

### Fixed
- **The released app shipped character art it shouldn't have.** Six characters
  based on third-party IP were already gitignored, but the PyInstaller spec
  copied the whole `static/` tree — so every release zip carried them. The
  bundle now filters them out (list kept in sync with `.gitignore`, asserted by
  a test), and the shipped illustration groups reference only original artwork.
- Personal characters can still be grouped locally: `illustration_groups.local.json`
  (gitignored, never packaged) merges over the shipped groups.


## 2.15.2

### Fixed
- **Settings → 스킬 was empty in the desktop app.** The skills folder was
  resolved with `parents[2]`, which is the repo root from a source checkout but
  one level ABOVE `_MEIPASS` in the frozen app — so the list came up empty
  there while the browser was fine. It has been wrong since the .app existed;
  moving to the app is what surfaced it.
- **Exporting the Summary did nothing in the desktop app.** pywebview's
  `window.print()` prints the top-level web view, and the report is rendered in
  an iframe, so the button silently no-opped. In the app it now opens the
  report in the real browser (where ⌘P works), and the report pane gained a ⤓
  that saves `report.html` as a file — which works everywhere.


## 2.15.1

### Fixed
- The bulk-selection checkbox landed on the same spot as the card's **delete**
  button, and the action bar slid under the sticky header as soon as you
  scrolled — right when you were scrolling to pick more cards. The overlay
  buttons each get their own column now, and the bar floats at the bottom.

## 2.15.0

### Added
- **Bulk edits in the gallery.** Pick cards (⇧-click for a range, or select
  everything on screen) and set the status or add/remove tags in one go. Tagging
  an imported batch of 90 papers used to mean 90 menus.
- **Settings → 태그.** Rename a tag across the whole library, or clear the name
  to remove it. Free-text tags drift — `Agent` / `agent` / `agents` were three
  separate tags here — and fixing that meant editing every paper by hand.

### Security
- **The server no longer binds the LAN by default.** The menubar path bound
  `0.0.0.0` so a phone on the same Wi-Fi could open the gallery, but nothing is
  authenticated: on a shared network that also exposed `DELETE /paper/<slug>`,
  the whole library, and `POST /analyze` on your Claude quota. It's loopback
  now; `PAPER_REVIEW_HOST=0.0.0.0` opts back in. Phones use the remote slot.

### Fixed
- **Deleting a paper called rmtree** — one misclick on a card's 🗑 destroyed a
  review that took hours. Papers move to `_trash/<slug>-<timestamp>/` now, the
  way illustrations already did.
- **Saving the workbench overwrote it with no way back**, though the review is
  the entire product. Each save snapshots the previous text into `.history/`
  (last 5 kept).
- **The gallery re-read the whole library on every load.** Each row parses
  workbench.md and a `*_figures.json` that runs to several MB of base64; with
  100+ papers that ran on every page load and every focus refresh. Rows are now
  cached on (workbench mtime, figures mtime): **163ms → 8ms**.


## 2.14.0

### Fixed
- **The window couldn't be dragged.** Hiding the title bar left nothing to grab:
  WKWebView swallows the clicks, so `movableByWindowBackground` never fires. A
  native drag strip now sits on the window frame — `performWindowDragWithEvent:`
  hands the whole drag to AppKit, which also fixes dragging *between monitors*
  (pywebview's JS drag region computes coordinates itself and drifts across
  displays with different scale factors). The strip goes below the titlebar
  container, so the traffic lights keep working — a subview of the content view
  would have landed inside the web view, which is what pywebview makes the
  content view.
- **A window left open showed a stale library.** The gallery embeds its list at
  render time and the app has no address bar to reload from, so papers added
  since launch (e.g. a bulk import) simply weren't there. `GET /papers.json` +
  a refresh when the window returns to the foreground.


## 2.13.2

### Fixed
- **The menubar icon read faint and blurry.** An SF Symbol's thin strokes land
  on half pixels at 18px, and even the filled variant stayed soft next to the
  solid glyphs its neighbours use. It is now the app's own brand mark — a card
  with three text lines — drawn directly with every edge on a whole pixel.

## 2.13.1

### Fixed
- Status-item failures used to be invisible (a windowed .app sends stdout
  nowhere); they now land in `_logs/app.log`, along with where the icon was
  loaded from. That is how the icon's state got confirmed inside the bundle.
- The status item declares an autosave name and forces itself visible —
  NSStatusItem visibility persists per name, so one that got hidden once would
  have stayed hidden on every later launch.


## 2.13.0

### Added
- **The desktop app puts an icon in the menubar too.** The standalone
  `paper-review menubar` runs its own NSApplication and can't be reused, so the
  app adds an NSStatusItem to the one pywebview already drives: status line,
  Show Window, Open in Browser, Quit. Opening the app now gives you both a Dock
  icon and a menubar item.

### Changed
- **The window's title bar is gone — the UI runs to the top of the window**, the
  way the sibling apps do. pywebview's grey bar read as browser chrome bolted
  above the app. The bar is transparent with full-size content; the sidebar and
  the content head simply start their padding below the traffic lights (a strip
  across the top left a seam where its colour met the content). The window stays
  draggable by its background.


## 2.12.0

### Changed
- **Menubar icon and menu cleaned up.** The icon was a hand-drawn 171-byte
  document outline; it is now generated from the same SF Symbol family as the
  Dock icon (`assets/generate_icons.py`, black template glyph that macOS tints)
  so the two read as one app. The dropdown lost its duplicate row — the gallery
  URL was its own item running the same action as *Open Gallery* — and the
  status line dropped the "●" it always drew regardless of state, folding the
  port in instead (`Running · localhost:7300`).
- **The gallery marks the phone's paper with a card border**, not a
  permanently-lit 📱 button. A button stuck in a highlighted state read as a
  control you had left pressed.

### Fixed
- The menubar's phone URL was computed once at launch, so after moving between
  networks it advertised an address that no longer existed. It now refreshes
  (~30s) and clicking it copies the URL — you can't click a link into a phone.
- The frozen app's menubar had no icon at all: `assets/` was never bundled, so
  it fell back to a "◫" text title.


## 2.11.0

### Added
- **A proper macOS app.** paper-review now sits in the Dock next to any other
  app, with its own icon (SF Symbol on the gallery's indigo, generated by
  `assets/generate_icons.py` — the same approach as the daily-log app) instead
  of the generic PyInstaller placeholder. `LSUIElement: False` is explicit: the
  menubar item still exists, but a status item hides behind the notch or a
  Hidden Bar, so the Dock is the entry point that is always there.
- `packaging/install-app.sh` installs the built bundle into /Applications and
  registers it with Launch Services (Spotlight + Dock icon pick it up at once).
  It refuses to overwrite a running copy instead of corrupting it.
- The source-install launcher (`install-launcher.sh`) gets the same icon —
  it used to land in the Dock as a generic AppleScript applet.

### Changed
- Bundle identifier is now `io.github.go-minseong.paperreview`, matching the
  other apps, and the plist declares local-HTTP (ATS) and the Documents-folder
  purpose string for publishing into a vault.
- The bundle version is read from `__init__.py` instead of being typed into the
  spec by hand — that drift is how v2.7.1 once shipped a 2.4.6 build.


## 2.10.2

### Fixed
- **The retired Wrap-up/메타 fields finally disappear from existing papers.**
  2.6.0 removed 가장 약한 부분 / 후속으로 읽을 논문 / 마지막 세션 from the
  generator, but every workbench created before that kept the empty
  placeholders — and re-analyzing can't clear them, since analyze deliberately
  never touches Wrap-up. The gallery now strips them once per paper, *only*
  while they are empty (a field with the user's own text stays), preserving the
  file's mtime so old papers don't all jump to "edited just now".
- **Tests no longer run against the developer's own library.** SERVICE_ROOT
  defaults to the checkout, so the route tests exercised handlers over real
  papers; harmless while everything was read-only, not once a migration writes.
  The suite now runs against a throwaway root.


## 2.10.1

### Fixed
- **Summary was empty on the phone.** Push only sent `report.md`, but reports
  built before that file existed are html-only — the slot's paper was one of
  them, so mobile got an empty Summary for a paper that clearly had one. Those
  now go as html and render in an iframe, restyled for a phone (nav/hero
  dropped, container widths capped, tables scrollable).
- **Tables were broken images on mobile — in both views.** Figures extracted as
  HTML tables (most `tbl*` entries) carry `html`, not `data_uri`, and the push
  payload dropped everything without a `data_uri`. Tables are now sent and
  rendered in place. Reports referencing extracted files by relative path get
  those inlined as data URIs, and anything still unresolvable (e.g. arXiv
  bundle paths inside extracted table HTML) shows a note instead of a broken
  image icon.


## 2.10.0

### Added
- **Summary on mobile.** The remote slot now carries `report.md` alongside the
  workbench, and the phone gets the same Detail / Summary switch as the desktop.
  Summary is read-only (the report is generated by Analyze, not hand-edited), so
  a mobile save keeps the report it was pushed with. Papers without a report
  simply don't show the switch.
- **The gallery shows which paper is on the phone.** Pushing records the slot
  locally, and that card's 📱 badge stays lit — previously there was no way to
  tell from the list which paper the remote slot held.
- **Settings → 모바일.** The remote URL and token can be set from the UI instead
  of hand-writing `~/.config/paper-review/remote.json`. The token is written
  0600 and never sent back to the browser (the field means "change it"; leaving
  it blank keeps the stored one). Clearing the URL disconnects the slot.

### Fixed
- The mobile header and the new view switch were both `position: sticky; top: 0`
  and overlapped on scroll — they now share one sticky container.


## 2.9.0

### Changed
- **Analyze now builds Detail AND Summary in one run.** The structured report
  used to be a separate button, so a freshly analyzed paper showed a Summary
  built from *fewer* sections — the old report kept filling the tab. Report
  generation is now the closing phase of the analyze job, so Detail and Summary
  always describe the same review. A paper whose sections are all done but has
  no report gets one backfilled; a report failure never fails the analyze (the
  sections are already written).
- **Report generation shows progress.** It used to be a request that blocked for
  minutes with nothing but a "Generating…" button — no way to tell whether it
  was working. It now runs as a job like analyze: the request returns
  immediately and the toast shows the phase ("Building Summary"), the live tool
  log (Read / WebSearch / Write report.html), and can be cancelled. The gallery
  card shows a "Summary 생성 중" pill, and the progress survives a page reload.


## 2.8.0

### Added
- **Launch screen for the desktop app.** Double-clicking the .app used to show
  nothing for several seconds (bundle unpack + uvicorn boot). The window now
  appears immediately with the paper-review mark and reports what it is doing
  (installing skills… → starting local server… → opening library…), then swaps
  itself over to the gallery. If the server never comes up, the splash turns
  into a readable error instead of leaving a blank window. Self-contained HTML
  (no CDN), light/dark aware, and the window background matches the system
  appearance so dark-mode users get no white flash.


## 2.7.1

### Fixed (first-run experience for other people)
- **Cloning anywhere but `~/Projects/paper-review-service` broke the library.**
  `SERVICE_ROOT` was a hardcoded path, so a checkout elsewhere read/wrote
  papers in a folder that didn't exist. Source installs now resolve to their
  own checkout; the frozen .app keeps the legacy location and
  `PAPER_REVIEWS_ROOT` still overrides both.
- **`install-menubar.sh` hardcoded the author's clone path** — now derived from
  the script location like the other installers.
- **The illustration fallback list named images that aren't in the repo** (the
  IP-character files are gitignored), so a fresh clone could show broken
  thumbnails if `/illustrations` ever failed. It now lists only shipped art.
- **`__version__` was still `0.1.0`** while the product shipped 2.x.

### Added
- **`?dash=1`** deep-links straight to the dashboard (also used for the docs
  screenshots).
- **README rewritten** for newcomers: badges, hero + report/dashboard/review
  screenshots, a feature table, install paths, architecture diagram, CLI
  reference, FAQ, roadmap and contributing notes.


## 2.7.0

### Changed
- **Dashboard split into Intake and Export, both monthly.** Tabs at the top of
  the dashboard switch between the two views (choice remembered):
  - **Intake** — papers by the month they arrived: Papers / Sections /
    Avg rating KPIs, review-status funnel, monthly intake chart, rating
    distribution, top tags.
  - **Export** — papers by the month they were exported: Exported count /
    export rate / median days intake→export, recent exports list, monthly
    export chart, and rating/top tags restricted to exported papers.
  The 52-week activity heatmap is replaced by a 12-month bar chart in both.
  Dashboard labels are English, matching the rest of the UI.

### Added
- **`exported_at` in the workbench frontmatter**, stamped on every publish —
  the Export dashboard needs a stable export date (the workbench mtime moves
  on any later edit). Existing exported papers were backfilled from their
  vault draft/published file mtime; papers with no vault file are counted as
  "undated" in the chart subtitle.


## 2.6.2

### Changed
- **Model picker updated for the Claude 5 generation**: Opus 5 (new default),
  Opus 4.8, Sonnet 5, Fable 5, Haiku 4.5. Every entry is now a pinned model id
  instead of a floating alias — the old list showed "Sonnet 4.6" while the
  `sonnet` alias already served Sonnet 5, so the label lied about what ran.
  Legacy saved values migrate (opus/sonnet/haiku → the pinned ids, retired
  Opus 4.7 → default), and installs still sitting on the previous default get a
  one-time bump to Opus 5; an explicit pick after that is never overridden.
  (Tag suggestion in ingest keeps the `haiku` alias on purpose — cheapest,
  not user-facing.)


## 2.6.1

### Fixed
- **Summary↔Detail no longer jerks the top of the page.** Both views repeated
  the paper title that the topbar already shows, at very different heights —
  Detail's workbench H1 (~150px) vs the report's sticky nav + hero cover
  (~615px), a ~400px jump on every toggle. The workbench H1 is now hidden on
  screen (print/PDF keeps it) and the embedded report hides its nav + hero via
  injected screen-only CSS, so both views open on TL;DR (4px apart). The
  standalone report (새 탭) and printed PDFs keep the full cover.


## 2.6.0

### Changed
- **Sections are now ONE block: `핵심 해설`.** The old `요약` + `Claude 1차 번역`
  pair made you read the same content twice. Analysis now writes a single
  self-contained Korean explanation per section — source order preserved but
  written, not transliterated (~50-70% of a literal translation, load-bearing
  phrases bolded, numbers/symbols/comparisons kept). Applies to NEW analysis;
  already-reviewed papers keep 요약+번역 and still render/publish as before.
- **Wrap-up trimmed to `한 줄 contribution`.** `가장 약한 부분` and `후속으로
  읽을 논문` are gone (the report's 05 한계 / 06 후속 연구 cover them), as is
  메타's `마지막 세션`. /finalize now asks one question. Publish still renders
  those fields for older papers that have them.
- **Pipeline auto-generation archived.** The structured report replaced that
  need: the generate card, route and prompt are removed. Existing ```pipeline
  blocks still render, animate and export to GIF for publish.


## 2.5.0

### Added
- **Publish exports Detail and Summary separately.** The Publish button now
  opens a target menu (Detail — full review / Summary — report / Both). The
  summary draft comes from a new velog-compatible report.md that report
  generation writes alongside report.html (degraded visuals: tables/bullets,
  same-origin figure refs materialized into the vault). Both drafts land in
  the configured drafts folder — <slug>.md and <slug>-summary.md — with the
  summary tagged `summary` and titled "… (Summary)". Older reports without
  report.md get a clear 400 asking to regenerate.

### Changed
- **Report button labels are English** (Generate Report / Generating… /
  Regenerate Report / Regenerate · outdated) per the English-UI rule.


## 2.4.7

### Fixed
- **Stale report after Analyze.** Running Analyze updated the workbench but
  the Summary tab kept serving the old report. Now: (1) a successful analyze
  run automatically rebuilds an existing report in the background (logged in
  the analyze log); (2) /report returns X-Report-Stale / X-Report-Mtime, the
  Summary button shows "리포트 재생성 · 변경됨" (amber) when the review
  changed after the report was built, and the iframe URL is mtime-versioned
  so a rebuilt report reloads automatically on the next Summary visit.


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
