
(() => {
  const slug = document.body.dataset.slug;

  // Record this view (for the gallery's last-activity time) — fire-and-forget
  fetch(`/paper/${slug}/viewed`, { method: "POST" }).catch(() => {});

  // ───────────────────────────────────────────────────────── State
  let prevSectionContent = new Map();   // heading → text content, used for diff
  let figures = [];
  let currentFigIdx = 0;
  let firstRender = true;

  // ───────────────────────────────────────────────────────── Markdown
  marked.use({ gfm: true, breaks: false });

  function stripFrontmatter(md) {
    return md.replace(/^---\n[\s\S]*?\n---\n/, "");
  }

  function statusFromBody(body) {
    // Italic marker may be _( … )_ or *( … )* depending on the markdown editor
    if (/[*_]?\(미진행/.test(body)) return "not_started";
    // A section is "done" once it has analyzed content (요약 or 번역),
    // regardless of whether a user answer block exists.
    if (/\*\*\s*(요약|Claude 1차 번역|원문 발췌)/.test(body)) return "done";
    return "not_started";
  }

  // Parse workbench markdown to extract sections list with status
  function extractSections(md) {
    const stripped = stripFrontmatter(md);
    // Bound the 섹션별 리뷰 block explicitly between its own H2 and the next
    // known H2 (Q&A / Wrap-up). A bare \n## terminator breaks when a section's
    // translated body happens to contain a line starting with "## ".
    const startM = stripped.match(/##\s+섹션별 리뷰\s*\n/);
    if (!startM) return [];
    const start = startM.index + startM[0].length;
    const tailM = stripped.slice(start).match(/\n##\s+(?:Q ?& ?A|Wrap-up|메타|정리)\b/);
    const end = tailM ? start + tailM.index : stripped.length;
    const body = stripped.slice(start, end);
    const chunks = body.split(/(?=\n### )/);
    const sections = [];
    for (const chunk of chunks) {
      if (!chunk.trim().startsWith("### ")) continue;
      const headM = chunk.match(/^###\s+(.+?)\s*$/m);
      if (!headM) continue;
      // Un-escape markdown escapes (WYSIWYG writes "1\." to avoid an ordered
      // list) so the nav shows "1." not "1\.".
      const heading = headM[1].replace(/\\([\\`*_{}\[\]()#+\-.!~>|])/g, "$1");
      sections.push({
        heading,
        status: statusFromBody(chunk),
        slug: slugify(heading),
      });
    }
    return sections;
  }

  function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9가-힣]+/g, "-").replace(/^-+|-+$/g, "");
  }

  const LABEL_ALIAS = {
    "원문 발췌": "orig",
    "요약": "summary",
    "Claude 1차 번역": "translation",
    "Claude Reader's Notes": "notes",
    "A (내 정리)": "user",
    "내 정리": "user",
    "내 메모": "user",
  };

  function annotateBlocksByLabel(container) {
    let currentAlias = null;
    for (const child of Array.from(container.children)) {
      if (child.tagName === "H3" || child.tagName === "H2") {
        currentAlias = null;
        continue;
      }
      // Detect label paragraph: <p><strong>label</strong>...</p>
      const strong = child.querySelector?.(":scope > strong, :scope > p > strong");
      if (strong) {
        const labelKey = Object.keys(LABEL_ALIAS).find(k => strong.textContent.startsWith(k));
        if (labelKey) {
          currentAlias = LABEL_ALIAS[labelKey];
          child.classList.add("wb-label", `wb-label-${currentAlias}`);
          continue;
        }
      }
      // Also handle <strong> as first child of a paragraph
      const firstStrong = child.tagName === "P" && child.firstElementChild?.tagName === "STRONG"
        ? child.firstElementChild : null;
      if (firstStrong) {
        const labelKey = Object.keys(LABEL_ALIAS).find(k => firstStrong.textContent.startsWith(k));
        if (labelKey) {
          currentAlias = LABEL_ALIAS[labelKey];
          child.classList.add("wb-label", `wb-label-${currentAlias}`);
          continue;
        }
      }
      if (currentAlias) {
        child.classList.add(`wb-block-${currentAlias}`);
      }
    }
  }

  // ──────────────── Authorship edit-diff ────────────────
  // Highlight the words the user changed vs Claude's per-section baseline.
  function _tokenize(s) { return s.match(/\s+|[^\s]+/g) || []; }
  function _markable(t) {
    // Never mark tokens that carry inline HTML (e.g. a color <span> the user
    // added). Wrapping `<span style="color: #e64980">` in <mark> shreds the tag
    // nesting and bleeds the blue highlight across un-edited text.
    return /[\p{L}\p{N}]/u.test(t)
        && !/^[|>#*_`~\-=]+$/.test(t)
        && !/[<>"]/.test(t);
  }
  function _lcsFlags(a, b) {           // → boolean[] over b: true if unchanged (in LCS)
    const n = a.length, m = b.length;
    const flags = new Array(m).fill(false);
    if (!n || !m) return flags;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { flags[j] = true; i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
      else j++;
    }
    return flags;
  }
  // Collapse escaping/whitespace differences the WYSIWYG editor introduces on
  // save (e.g. "정식화한다\." vs "정식화한다.", "$\\in$" vs "$\in$") so they
  // don't read as edits. Compare on normalized tokens, render the originals.
  function _normTok(t) { return t.replace(/\\([!-/:-@\[-`{-~])/g, "$1"); }
  function wordDiffMark(baseText, curText) {
    const baseWords = _tokenize(baseText).filter(t => /\S/.test(t)).map(_normTok);
    const cur = _tokenize(curText);
    const flags = _lcsFlags(baseWords, cur.filter(t => /\S/.test(t)).map(_normTok));
    let wi = 0, open = false, out = "";
    const close = () => { if (open) { out += "</mark>"; open = false; } };
    for (const tok of cur) {
      if (/\S/.test(tok)) {
        const unchanged = flags[wi++];
        if (unchanged || !_markable(tok)) { close(); out += tok; }
        else { if (!open) { out += '<mark class="wb-edit">'; open = true; } out += tok; }
      } else { if (tok.includes("\n")) close(); out += tok; }   // don't span blocks
    }
    close();
    return out;
  }
  function injectEditMarks(body, baseline) {
    if (!baseline || !Object.keys(baseline).length) return body;
    return body.split(/(?=^###\s)/m).map(chunk => {
      const hm = chunk.match(/^###\s+(.+?)\s*$/m);
      if (!hm) return chunk;
      const base = baseline[hm[1].trim()];
      if (!base) return chunk;
      const baseBody = base.replace(/^###\s+.*(?:\r?\n|$)/, "");
      const nl = chunk.indexOf("\n");
      if (nl < 0) return chunk;
      const body2 = chunk.slice(nl + 1);
      // The chunk runs to the next ### — but a following ## (Q&A / Wrap-up / 메타)
      // can get lumped in. Only diff up to that H2; leave the rest untouched.
      const h2 = body2.search(/^##\s/m);
      const head = chunk.slice(0, nl + 1);
      if (h2 >= 0)
        return head + wordDiffMark(baseBody, body2.slice(0, h2)) + body2.slice(h2);
      return head + wordDiffMark(baseBody, body2);
    }).join("");
  }

  // Elevate the TL;DR into a "한눈에" hero card pinned at the top.
  function wrapHeroCard(wb) {
    const h2 = [...wb.children].find(
      el => el.tagName === "H2" && /^TL;?DR/i.test(el.textContent.trim()));
    if (!h2 || h2.parentElement.classList.contains("wb-hero")) return;
    const card = document.createElement("div");
    card.className = "wb-hero";
    wb.insertBefore(card, h2);
    let node = h2;
    while (node) {
      const next = node.nextElementSibling;
      card.appendChild(node);
      if (next && next.tagName === "H2") break;
      node = next;
    }
  }

  // Render ```mermaid fences into SVG pipeline diagrams.
  let _mermaidReady = false;
  function _initMermaid() {
    if (_mermaidReady || typeof mermaid === "undefined") return;
    const dark = document.body.dataset.theme === "dark" ||
      (!document.body.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    mermaid.initialize({
      startOnLoad: false, theme: dark ? "dark" : "default",
      securityLevel: "strict", fontFamily: "inherit",
    });
    _mermaidReady = true;
  }
  async function renderMermaid(wb) {
    const blocks = [...wb.querySelectorAll("code.language-mermaid")];
    if (!blocks.length || typeof mermaid === "undefined") return;
    _initMermaid();
    let i = 0;
    for (const code of blocks) {
      const pre = code.closest("pre") || code;
      const spec = code.textContent;
      const box = document.createElement("div");
      box.className = "wb-mermaid";
      try {
        const { svg } = await mermaid.render("mmd-" + slug.replace(/\W/g, "") + "-" + (i++), spec);
        box.innerHTML = svg;
      } catch (e) {
        box.classList.add("err");
        box.textContent = "다이어그램 렌더 실패: " + (e && e.message ? e.message : e);
      }
      pre.replaceWith(box);
    }
  }

  // ───────────────────────────────────────────────────────── Render
  async function loadWorkbench() {
    const res = await fetch(`/paper/${slug}/workbench.md`);
    const md = await res.text();
    const stripped = stripFrontmatter(md);
    let baseline = {};
    try { baseline = await (await fetch(`/paper/${slug}/baseline.json`)).json(); } catch (_) {}

    const html = marked.parse(injectEditMarks(stripped, baseline));
    const wb = document.getElementById("wb");
    wb.innerHTML = html;

    // Add ids to h3 for nav jumps; h1/h2 too so bookmarks can anchor to them
    wb.querySelectorAll("h3").forEach(h => {
      h.id = "sec-" + slugify(h.textContent);
    });
    wb.querySelectorAll("h1, h2").forEach(h => {
      if (!h.id) h.id = "h-" + slugify(h.textContent);
    });

    // Mark workbench blocks by label so view toggle (summary/detail) can hide
    annotateBlocksByLabel(wb);
    wrapHeroCard(wb);
    renderMermaid(wb);

    // KaTeX
    if (window.renderMathInElement) {
      renderMathInElement(wb, {
        delimiters: [
          {left: "$$", right: "$$", display: true},
          {left: "$", right: "$", display: false},
        ],
        throwOnError: false,
      });
    }

    // Diff: detect changed section content
    const newContent = new Map();
    let currentH3 = null;
    let buffer = [];
    const flush = () => {
      if (currentH3) {
        const text = buffer.map(n => n.textContent || "").join(" ");
        newContent.set(currentH3.textContent, text);
        if (!firstRender && prevSectionContent.get(currentH3.textContent) !== text) {
          // Mark all buffer elements as just-added
          for (const node of buffer) {
            if (node.classList) node.classList.add("just-added");
          }
        }
      }
    };
    for (const child of Array.from(wb.children)) {
      if (child.tagName === "H3") {
        flush();
        currentH3 = child;
        buffer = [];
      } else if (currentH3) {
        buffer.push(child);
      }
    }
    flush();
    prevSectionContent = newContent;

    if (!firstRender) {
      // Trigger fade
      requestAnimationFrame(() => {
        wb.querySelectorAll(".just-added").forEach(el => el.classList.add("fade"));
        setTimeout(() => {
          wb.querySelectorAll(".just-added").forEach(el => el.classList.remove("just-added", "fade"));
        }, 3500);
      });
    }
    firstRender = false;

    const secs = extractSections(md);
    renderNav(secs);
    injectGenQuestionsBtn(wb);
    injectSectionAnalyzeButtons(wb, secs);
  }

  // Inject "이 섹션 분석" buttons on every not-yet-done section heading
  function injectSectionAnalyzeButtons(wb, secs) {
    // Hide the "_(미진행 …)_" placeholder paragraphs — the button replaces them.
    wb.querySelectorAll("p, em").forEach(el => {
      const t = el.textContent.trim();
      if (/^[*_]?\(미진행/.test(t) && t.length < 80) {
        const p = el.closest("p") || el;
        p.style.display = "none";
      }
    });
    const byId = new Map(secs.map(s => [s.slug, s]));
    wb.querySelectorAll("h3").forEach(h => {
      const id = (h.id || "").replace(/^sec-/, "");
      const sec = byId.get(id);
      if (!sec || sec.status !== "not_started") return;
      if (h.querySelector(".gen-sec-btn")) return;
      const btn = document.createElement("button");
      btn.className = "gen-q-btn gen-sec-btn";
      btn.textContent = "이 섹션 분석";
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (analyzePolling) { UIDialog.alert("이미 분석이 진행 중입니다."); return; }
        analyzeSection(sec.heading, btn);
      });
      h.appendChild(btn);
    });
  }

  async function analyzeSection(heading, btn) {
    if (btn) { btn.textContent = "분석 중…"; btn.disabled = true; }
    try {
      const r = await fetch(`/paper/${slug}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelPicker.value, only_sections: [heading] }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      pollAnalyze();  // reuse the existing progress toast + polling
    } catch (e) {
      UIDialog.alert("섹션 분석 실패: " + (e.message || e));
      if (btn) { btn.textContent = "이 섹션 분석"; btn.disabled = false; }
    }
  }

  // Inject a "질문 생성" button into the ## Q&A heading
  let genQBusy = false;
  function injectGenQuestionsBtn(wb) {
    const qaH = [...wb.querySelectorAll("h2")].find(h =>
      h.textContent.trim().replace(/\\s+/g, "").startsWith("Q&A") ||
      h.textContent.trim().startsWith("Q & A"));
    if (!qaH || qaH.querySelector(".gen-q-btn")) return;
    const btn = document.createElement("button");
    btn.className = "gen-q-btn";
    btn.textContent = genQBusy ? "생성 중…" : "질문 생성";
    btn.disabled = genQBusy;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      if (genQBusy) return;
      genQBusy = true;
      btn.textContent = "생성 중…";
      btn.disabled = true;
      try {
        const r = await fetch(`/paper/${slug}/generate-questions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelPicker.value }),
        });
        const data = await r.json();
        if (!r.ok || !data.ok) throw new Error(data.error || ("HTTP " + r.status));
        // workbench updates via SSE; reload to be safe
        firstRender = true; prevSectionContent = new Map();
        await loadWorkbench();
      } catch (err) {
        UIDialog.alert("질문 생성 실패: " + (err.message || err));
      } finally {
        genQBusy = false;
      }
    });
    qaH.appendChild(btn);
  }

  // ───────────────────────────────────────────────────────── Nav
  function renderNav(sections) {
    const list = document.getElementById("nav-list");
    if (!sections.length) {
      list.innerHTML = '<li style="padding: 12px 14px; color: var(--text-muted); font-size: 12px;">No sections detected.</li>';
      return;
    }
    list.innerHTML = sections.map(s => {
      const dotCls = s.status === "done" ? "s-done" :
                     s.status === "in_progress" ? "s-in_progress" : "";
      const { num, title, depth } = parseHeading(s.heading);
      return `
        <li class="nav-item" data-target="sec-${s.slug}" data-depth="${depth}">
          <span class="nav-dot ${dotCls}" aria-label="${s.status}"></span>
          <span class="nav-label">${num ? `<span class="nav-num">${escapeHtml(num)}</span>` : ''}${escapeHtml(title)}</span>
        </li>`;
    }).join("");
    list.querySelectorAll(".nav-item").forEach(li => {
      li.addEventListener("click", () => {
        const id = li.dataset.target;
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        closeNavOnMobile();
      });
    });
  }

  function parseHeading(s) {
    // "3.2.1 Scaled Dot-Product Attention" → { num: "3.2.1", title: "Scaled…", depth: 2 }
    const m = s.match(/^([IVXLCDM]+|\d+(?:\.\d+)*)(?:\.?)\s+(.+)$/);
    if (!m) return { num: "", title: s, depth: 0 };
    const num = m[1];
    const title = m[2];
    const depth = (num.match(/\./g) || []).length;
    return { num, title, depth };
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" })[c]);
  }

  // Highlight active section on scroll
  const wbEl = document.getElementById("wb");
  let scrollTimer = null;
  wbEl.addEventListener("scroll", () => {
    if (scrollTimer) cancelAnimationFrame(scrollTimer);
    scrollTimer = requestAnimationFrame(updateActiveNav);
  });
  function updateActiveNav() {
    const h3s = Array.from(wbEl.querySelectorAll("h3"));
    if (!h3s.length) return;
    const wbRect = wbEl.getBoundingClientRect();
    const threshold = wbRect.top + 80;
    let active = null;
    for (const h of h3s) {
      const r = h.getBoundingClientRect();
      if (r.top <= threshold) active = h;
    }
    document.querySelectorAll(".nav-item").forEach(li => {
      const targetId = li.dataset.target;
      li.classList.toggle("active", active && active.id === targetId);
    });
  }

  // ───────────────────────────────────────────────────────── View toggle (summary/detail)
  const viewToggle = document.getElementById("view-toggle");
  const savedView = localStorage.getItem("pr-view") || "detail";
  setView(savedView);
  viewToggle.querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => setView(b.dataset.view));
  });
  function setView(mode) {
    document.getElementById("wb").dataset.view = mode;
    viewToggle.querySelectorAll("button").forEach(b => {
      b.classList.toggle("active", b.dataset.view === mode);
    });
    localStorage.setItem("pr-view", mode);
  }

  // ───────────────────────────────────────────────────────── Nav toggle
  const navEl = document.getElementById("nav");
  const layoutEl = document.getElementById("layout");
  // Restore nav state from localStorage (desktop)
  if (localStorage.getItem("pr-nav-closed") === "1") {
    layoutEl.dataset.nav = "closed";
  }
  function toggleNav() {
    const wide = window.innerWidth > 1280;
    if (wide) {
      // Desktop: collapse the grid column
      if (layoutEl.dataset.nav === "closed") {
        delete layoutEl.dataset.nav;
        localStorage.removeItem("pr-nav-closed");
      } else {
        layoutEl.dataset.nav = "closed";
        localStorage.setItem("pr-nav-closed", "1");
      }
    } else {
      // Narrow: drawer overlay
      if (navEl.dataset.open) delete navEl.dataset.open;
      else navEl.dataset.open = "1";
    }
  }
  document.getElementById("nav-collapse").addEventListener("click", toggleNav);
  document.getElementById("nav-reopen").addEventListener("click", toggleNav);
  function closeNavOnMobile() {
    if (window.innerWidth <= 1280) delete navEl.dataset.open;
  }

  // ─────────────────────────────────────────────── Resizable PDF | workbench split
  const gutter = document.getElementById("gutter");
  const SPLIT_KEY = "pr-split";
  const DEFAULT_SPLIT = "42%";
  const savedSplit = localStorage.getItem(SPLIT_KEY);
  if (savedSplit) layoutEl.style.setProperty("--split", savedSplit);
  if (gutter) {
    const pdfPane = document.querySelector(".pane.pdf");
    let dragging = false;
    const onMove = (e) => {
      if (!dragging) return;
      const lr = layoutEl.getBoundingClientRect();
      const navW = pdfPane.getBoundingClientRect().left - lr.left; // 0 when nav closed
      let pct = ((e.clientX - lr.left - navW) / lr.width) * 100;
      pct = Math.max(18, Math.min(78, pct));
      layoutEl.style.setProperty("--split", pct.toFixed(1) + "%");
    };
    const stop = () => {
      if (!dragging) return;
      dragging = false;
      layoutEl.classList.remove("dragging");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", stop);
      const v = layoutEl.style.getPropertyValue("--split").trim();
      if (v) localStorage.setItem(SPLIT_KEY, v);
    };
    gutter.addEventListener("mousedown", (e) => {
      e.preventDefault();
      dragging = true;
      layoutEl.classList.add("dragging");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", stop);
    });
    // double-click resets to the default split
    gutter.addEventListener("dblclick", () => {
      layoutEl.style.setProperty("--split", DEFAULT_SPLIT);
      localStorage.setItem(SPLIT_KEY, DEFAULT_SPLIT);
    });
  }

  // ─────────────────────────────────────── Pane visibility (원본 PDF / 정리본)
  const paneToggle = document.getElementById("pane-toggle");
  function setPanes(mode) {           // 'both' | 'pdf' | 'wb'
    layoutEl.dataset.panes = mode;
    if (paneToggle) {
      paneToggle.querySelector('[data-pane="pdf"]').classList.toggle('active', mode === 'both' || mode === 'pdf');
      paneToggle.querySelector('[data-pane="wb"]').classList.toggle('active', mode === 'both' || mode === 'wb');
    }
    localStorage.setItem("pr-panes", mode);
  }
  setPanes(localStorage.getItem("pr-panes") || "both");
  if (paneToggle) paneToggle.querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => {
      const cur = layoutEl.dataset.panes || "both";
      let pdfOn = cur === "both" || cur === "pdf";
      let wbOn = cur === "both" || cur === "wb";
      if (b.dataset.pane === "pdf") pdfOn = !pdfOn; else wbOn = !wbOn;
      if (!pdfOn && !wbOn) return;    // keep at least one pane visible
      setPanes(pdfOn && wbOn ? "both" : pdfOn ? "pdf" : "wb");
    }));

  // ─────────────────────────────────────────────── Star rating
  const ratingEl = document.getElementById("rating");
  let curRating = parseInt(document.body.dataset.rating || "0", 10) || 0;
  function paintStars(value) {
    ratingEl.querySelectorAll(".star").forEach((s, i) => s.classList.toggle("on", i < value));
  }
  if (ratingEl) {
    for (let i = 1; i <= 5; i++) {
      const s = document.createElement("span");
      s.className = "star"; s.textContent = "★"; s.dataset.v = String(i);
      ratingEl.appendChild(s);
    }
    paintStars(curRating);
    ratingEl.addEventListener("mousemove", (e) => {
      const s = e.target.closest(".star"); if (s) paintStars(+s.dataset.v);
    });
    ratingEl.addEventListener("mouseleave", () => paintStars(curRating));
    ratingEl.addEventListener("click", async (e) => {
      const s = e.target.closest(".star"); if (!s) return;
      let v = +s.dataset.v;
      if (v === curRating) v = 0;            // click the current rating to clear
      curRating = v;
      paintStars(v);
      try {
        await fetch(`/paper/${slug}/rating`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rating: v }),
        });
      } catch (_) { /* non-fatal */ }
    });
  }

  // ───────────────────────────────────────────────────────── Model picker
  const modelPicker = document.getElementById("model-picker");
  // Migrate legacy values to the new explicit IDs
  const MODEL_MIGRATE = { "opus": "claude-opus-4-8" };
  let savedModel = localStorage.getItem("pr-model") || "claude-opus-4-8";
  savedModel = MODEL_MIGRATE[savedModel] || savedModel;
  // Fall back to first option if the saved value is no longer offered
  const known = Array.from(modelPicker.options).map(o => o.value);
  if (!known.includes(savedModel)) savedModel = modelPicker.options[0].value;
  modelPicker.value = savedModel;
  localStorage.setItem("pr-model", savedModel);
  modelPicker.addEventListener("change", () => {
    localStorage.setItem("pr-model", modelPicker.value);
  });

  // ───────────────────────────────────────────────────────── Figures
  async function loadFigures() {
    const res = await fetch(`/paper/${slug}/figures.json`);
    const data = await res.json();
    figures = Array.isArray(data) ? data : (data.figures || []);
    const cnt = document.getElementById("figs-count");
    cnt.textContent = figures.length ? figures.length : "—";
    if (!figures.length) document.getElementById("btn-figures").disabled = true;
  }

  function openFigures() {
    if (!figures.length) return;
    const grid = document.getElementById("figs-grid");
    if (!grid.dataset.rendered) {
      grid.innerHTML = figures.map((f, i) => {
        const kind = f.kind || (f.data_uri ? 'image' : (f.html ? 'table' : 'unknown'));
        let preview;
        if (f.data_uri) {
          preview = `<img src="${f.data_uri}" alt="${escapeHtml(f.label || '')}">`;
        } else if (f.html) {
          preview = `<div class="fig-html-preview">${f.html}</div>`;
        } else {
          preview = `<div class="fig-html-preview" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted)">no preview</div>`;
        }
        const badgeText = f.label || ((kind === 'table' ? 'Table ' : 'Figure ') + (i + 1));
        const badge = `<span class="fig-kind-badge ${kind === 'table' ? 'is-table' : 'is-figure'}">${escapeHtml(badgeText)}</span>`;
        return `
        <div class="fig-card" data-idx="${i}">
          ${preview}${badge}
          <div class="meta">
            <div class="cap">${escapeHtml(f.caption_ko || f.caption_en || "")}</div>
          </div>
        </div>`;
      }).join("");
      grid.querySelectorAll(".fig-card").forEach(c =>
        c.addEventListener("click", () => {
          if (editing && tuiEditor) insertFigureIntoEditor(+c.dataset.idx);
          else openLightbox(+c.dataset.idx);
        })
      );
      grid.dataset.rendered = "1";
    }
    document.getElementById("modal-figs").setAttribute("open", "");
  }
  function closeFigures() {
    document.getElementById("modal-figs").removeAttribute("open");
  }
  document.getElementById("btn-figures").addEventListener("click", openFigures);
  document.querySelectorAll("#modal-figs [data-close]").forEach(el =>
    el.addEventListener("click", closeFigures)
  );

  // ───────────────────────────────────────────────────────── Lightbox
  const lb = document.getElementById("lightbox");
  function openLightbox(idx) {
    currentFigIdx = idx;
    renderLightbox();
    lb.setAttribute("open", "");
  }
  function closeLightbox() { lb.removeAttribute("open"); }
  function renderLightbox() {
    const f = figures[currentFigIdx];
    if (!f) return;
    const imgWrap = document.getElementById("lb-imgwrap");
    const htmlWrap = document.getElementById("lb-html");
    if (f.data_uri) {
      imgWrap.style.display = '';
      htmlWrap.style.display = 'none';
      document.getElementById("lb-img").src = f.data_uri;
      document.getElementById("lb-img").alt = f.label || "";
    } else if (f.html) {
      imgWrap.style.display = 'none';
      htmlWrap.style.display = '';
      htmlWrap.innerHTML = f.html;
    } else {
      imgWrap.style.display = 'none';
      htmlWrap.style.display = '';
      htmlWrap.innerHTML = '<p style="color:var(--text-muted);text-align:center">no preview available</p>';
    }
    document.getElementById("lb-pos").textContent =
      `${f.label || f.id || ''} · ${currentFigIdx + 1} / ${figures.length}`;
    const cap = document.getElementById("lb-cap");
    cap.innerHTML = (f.caption_ko ? `<div class="ko">${escapeHtml(f.caption_ko)}</div>` : "") +
                    (f.caption_en ? `<div>${escapeHtml(f.caption_en)}</div>` : "");
  }
  document.getElementById("lb-close").addEventListener("click", closeLightbox);
  document.getElementById("lb-prev").addEventListener("click", () => {
    currentFigIdx = (currentFigIdx - 1 + figures.length) % figures.length;
    renderLightbox();
  });
  document.getElementById("lb-next").addEventListener("click", () => {
    currentFigIdx = (currentFigIdx + 1) % figures.length;
    renderLightbox();
  });

  // ───────────────────────────────────────────────────────── Keyboard
  document.addEventListener("keydown", e => {
    // Don't hijack single-key shortcuts (g/s/c/ …) while the user is typing
    // in a field, the WYSIWYG editor (contenteditable), or any edit mode.
    const t = e.target;
    if (t.isContentEditable || t.tagName === "INPUT" || t.tagName === "TEXTAREA"
        || t.tagName === "SELECT" || (typeof editing !== "undefined" && editing)) return;
    if (e.key === "Escape") {
      if (lb.hasAttribute("open")) return closeLightbox();
      if (document.getElementById("modal-figs").hasAttribute("open")) return closeFigures();
    }
    if (lb.hasAttribute("open")) {
      if (e.key === "ArrowLeft")  { document.getElementById("lb-prev").click(); }
      if (e.key === "ArrowRight") { document.getElementById("lb-next").click(); }
      return;
    }
    if (e.key === "g" || e.key === "G") openFigures();
    if (e.key === "s" || e.key === "S") toggleNav();
    if (e.key === "c" || e.key === "C") chatHead.click();
    if (e.key === "/" && !chatBusy) {
      e.preventDefault();
      chatInput.focus();
      chatInput.value = "/";
      chatInput.dispatchEvent(new Event('input'));
    }
  });

  // ───────────────────────────────────────────────────────── WYSIWYG edit
  const btnEdit = document.getElementById('btn-edit');
  const wbPane = document.getElementById('wb');
  let editing = false;
  let tuiEditor = null;
  let savedFrontmatter = "";   // preserved verbatim across an edit
  let suppressSSEReload = false;

  btnEdit.addEventListener('click', toggleEdit);

  function isDarkNow() {
    const t = document.body.dataset.theme;
    if (t === 'dark') return true;
    if (t === 'light') return false;
    return matchMedia('(prefers-color-scheme: dark)').matches;
  }

  async function toggleEdit() {
    if (editing) return cancelEdit();
    const res = await fetch(`/paper/${slug}/workbench.md`);
    const md = await res.text();
    // Split frontmatter (preserved) from the editable body
    const fm = md.match(/^(---\n[\s\S]*?\n---\n)([\s\S]*)$/);
    savedFrontmatter = fm ? fm[1] : "";
    const body = fm ? fm[2] : md;
    suppressSSEReload = true;

    wbPane.classList.add('editing');
    wbPane.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'edit-wrap';
    wrap.innerHTML = `
      <div class="edit-toolbar">
        <strong>편집 (WYSIWYG)</strong>
        <span class="hint">우측 상단에서 마크다운/문서 모드 전환 · Cmd/Ctrl+S 저장 · Esc 취소</span>
        <button class="btn-secondary" id="edit-figure" style="padding:6px 12px;font-size:12px">Figure 삽입</button>
        <button class="btn-secondary" id="edit-cancel" style="padding:6px 12px;font-size:12px">취소</button>
        <button class="btn-primary" id="edit-save" style="padding:6px 14px;font-size:12px">저장</button>
      </div>
      <div class="tui-host" id="tui-host"></div>
    `;
    wbPane.appendChild(wrap);
    editing = true;
    btnEdit.textContent = 'Editing';
    btnEdit.style.background = 'var(--accent)';
    btnEdit.style.color = 'white';

    // Text-color picker (color-syntax plugin) — loaded from CDN in detail.html.
    // Guard so the editor still opens if the plugin script failed to load.
    const colorPlugin = (window.toastui && toastui.Editor && toastui.Editor.plugin
      && toastui.Editor.plugin.colorSyntax) || null;
    const editorOpts = {
      el: document.getElementById('tui-host'),
      initialValue: body,
      initialEditType: 'wysiwyg',
      previewStyle: 'tab',
      height: '100%',
      usageStatistics: false,
      theme: isDarkNow() ? 'dark' : 'default',
      autofocus: true,
      toolbarItems: [
        ['heading', 'bold', 'italic', 'strike'],
        ['hr', 'quote'],
        ['ul', 'ol', 'task'],
        ['table', 'link'],
        ['code', 'codeblock'],
      ],
    };
    if (colorPlugin) {
      // Korean-blog-friendly palette + a custom hex box. The plugin appends a
      // color button to the toolbar and emits inline <span style="color:…">.
      editorOpts.plugins = [[colorPlugin, {
        preset: ['#212529', '#868e96', '#fa5252', '#e64980', '#be4bdb',
                 '#7950f2', '#4c6ef5', '#228be6', '#15aabf', '#12b886',
                 '#40c057', '#82c91e', '#fab005', '#fd7e14'],
        useCustomInputBox: true,
      }]];
    }
    tuiEditor = new toastui.Editor(editorOpts);

    document.getElementById('edit-cancel').onclick = cancelEdit;
    document.getElementById('edit-save').onclick = saveEdit;
    document.getElementById('edit-figure').onclick = () => openFigures();
  }

  // Convert an HTML <table> (from figures.json) into a GFM markdown table.
  function htmlTableToMarkdown(html) {
    const tbl = new DOMParser().parseFromString(html, "text/html").querySelector("table");
    if (!tbl) return null;
    const rows = [...tbl.querySelectorAll("tr")].map(tr =>
      [...tr.querySelectorAll("th,td")].map(c =>
        c.textContent.replace(/\s+/g, " ").trim().replace(/\|/g, "\\|")));
    const data = rows.filter(r => r.length);
    if (!data.length) return null;
    const cols = Math.max(...data.map(r => r.length));
    const fill = r => { const x = r.slice(); while (x.length < cols) x.push(""); return x; };
    const ln = cells => "| " + cells.join(" | ") + " |";
    const out = [ln(fill(data[0])), ln(Array(cols).fill("---"))];
    data.slice(1).forEach(r => out.push(ln(fill(r))));
    return out.join("\n");
  }

  // Rasterize an HTML <table> to a PNG data URL via html2canvas. Math in cells
  // is KaTeX-rendered first. Tables are published as images (GFM tables break
  // on Velog: merged cells, math, multi-row headers, WYSIWYG re-serialization).
  async function renderTableToDataURL(html) {
    if (typeof html2canvas === "undefined") throw new Error("html2canvas 미로드");
    const wrap = document.createElement("div");
    wrap.className = "tbl-raster";
    wrap.innerHTML = html;
    document.body.appendChild(wrap);
    try {
      if (window.renderMathInElement) {
        try {
          renderMathInElement(wrap, {
            delimiters: [
              { left: "$$", right: "$$", display: true },
              { left: "$", right: "$", display: false },
            ],
            throwOnError: false,
          });
        } catch {}
      }
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const target = wrap.querySelector("table") || wrap;
      const canvas = await html2canvas(target, {
        backgroundColor: "#ffffff", scale: 2, logging: false, useCORS: true,
      });
      return canvas.toDataURL("image/png");
    } finally {
      wrap.remove();
    }
  }

  async function insertFigureIntoEditor(idx) {
    const f = figures[idx];
    if (!f || !tuiEditor) return;
    const cap = (f.caption_ko || f.caption_en || "").trim();
    if (f.data_uri) {
      // Image → addImage at the cursor + caption below
      const url = `/paper/${slug}/fig/${f.id}`;
      const alt = (f.label || "figure").replace(/[\[\]]/g, "");
      tuiEditor.exec("addImage", { imageUrl: url, altText: alt });
      if (cap) tuiEditor.insertText("\n" + cap + "\n");
    } else if (f.html) {
      // Table → rasterize to a PNG (GFM tables break on Velog). Render
      // offscreen, persist as this figure's data_uri, insert as an image.
      const card = document.querySelector(`#figs-grid .fig-card[data-idx="${idx}"]`);
      if (card) card.classList.add("rasterizing");
      let dataUrl;
      try {
        dataUrl = await renderTableToDataURL(f.html);
        const r = await fetch(`/paper/${slug}/fig/${f.id}/image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data_uri: dataUrl }),
        });
        if (!r.ok) throw new Error("HTTP " + r.status);
      } catch (e) {
        if (card) card.classList.remove("rasterizing");
        UIDialog.alert("표를 이미지로 변환 실패: " + (e.message || e));
        return;
      }
      f.data_uri = dataUrl;
      f.kind = "image";
      if (card) card.classList.remove("rasterizing");
      const url = `/paper/${slug}/fig/${f.id}`;
      const alt = (f.label || "table").replace(/[\[\]]/g, "");
      tuiEditor.exec("addImage", { imageUrl: url, altText: alt });
      if (cap) tuiEditor.insertText("\n" + cap + "\n");
    } else {
      UIDialog.alert("삽입할 수 없는 항목입니다."); return;
    }
    closeFigures();
  }

  async function saveEdit() {
    if (!editing || !tuiEditor) return;
    const newBody = tuiEditor.getMarkdown();
    const fullText = savedFrontmatter + newBody;
    try {
      const res = await fetch(`/paper/${slug}/workbench.md`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: fullText }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      exitEdit();
    } catch (e) {
      UIDialog.alert('저장 실패: ' + (e.message || e));
    }
  }

  function cancelEdit() { if (editing) exitEdit(); }

  function exitEdit() {
    if (tuiEditor) { try { tuiEditor.destroy(); } catch {} tuiEditor = null; }
    editing = false;
    suppressSSEReload = false;
    btnEdit.textContent = 'Edit';
    btnEdit.style.background = '';
    btnEdit.style.color = '';
    wbPane.classList.remove('editing');
    wbPane.innerHTML = '';
    firstRender = true; // suppress diff highlight on the post-edit reload
    prevSectionContent = new Map();
    loadWorkbench();
  }

  // Global Cmd/Ctrl+S + Esc while editing
  document.addEventListener('keydown', (e) => {
    if (!editing) return;
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
      e.preventDefault(); saveEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault(); cancelEdit();
    }
  });

  function showSaveWarn(msg, onOverride) {
    let warn = document.querySelector('.save-warn');
    if (!warn) {
      warn = document.createElement('div');
      warn.className = 'save-warn';
      document.body.appendChild(warn);
    }
    warn.innerHTML = '';
    const text = document.createElement('span');
    text.textContent = msg;
    warn.appendChild(text);
    const btn = document.createElement('button');
    btn.textContent = '덮어쓰기';
    btn.style.cssText = 'margin-left:12px;background:white;color:#ef4444;border:0;padding:4px 10px;border-radius:6px;cursor:pointer;font-weight:600;font-size:12px';
    btn.onclick = () => { warn.removeAttribute('open'); onOverride(); };
    warn.appendChild(btn);
    warn.setAttribute('open', '');
    setTimeout(() => warn.removeAttribute('open'), 10000);
  }

  // ───────────────────────────────────────────────────────── Analyze
  const btnAnalyze = document.getElementById('btn-analyze');
  let analyzePolling = false;

  btnAnalyze.addEventListener('click', async () => {
    if (analyzePolling) {
      // Cancel
      if (!await UIDialog.confirm('진행 중인 분석을 취소할까요?',
        { title: '분석 취소', danger: true, okLabel: '분석 중단', cancelLabel: '계속' })) return;
      await fetch(`/paper/${slug}/analyze/cancel`, { method: 'POST' });
      return;
    }
    // If this paper is still on the reading list, first promote (ingest body)
    const status = document.body.dataset.status;
    if (status === 'to_read') {
      if (!await UIDialog.confirm(
        '이 paper는 reading list에만 저장된 상태입니다.\n본문 추출 + figures 다운로드를 진행할까요? (~5-15분, paper에 따라 다름)',
        { title: '본문 추출', okLabel: '진행' })) return;
      try {
        const r = await fetch(`/paper/${slug}/promote`, { method: 'POST' });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.detail || 'HTTP ' + r.status);
        }
        const out = await r.json();
        UIDialog.alert('본문 추출이 시작되었습니다 (~5-15분). 완료 후 페이지가 자동 새로고침됩니다.');
        // Poll the ingest job
        pollPromoteJob(out.job_id);
      } catch (e) {
        UIDialog.alert('✗ ' + (e.message || e));
      }
      return;
    }
    // Fetch dynamic cost estimate
    let preview = null;
    try {
      preview = await (await fetch(`/paper/${slug}/analyze/preview`)).json();
    } catch {}
    let msg = '자동 분석을 시작합니다.';
    if (preview && preview.pending_sections >= 0) {
      const min = Math.max(1, Math.round(preview.estimated_seconds / 60));
      const cost = preview.estimated_cost_usd;
      const pre = preview.needs_prelude ? ' (TL;DR+contribution+사전지식 자동 생성 포함)' : '';
      msg = `${preview.pending_sections}개 섹션 분석${pre}\n예상 시간: ~${min}분 · 예상 비용: ~$${cost.toFixed(2)}\n진행할까요?`;
    }
    if (!await UIDialog.confirm(msg, { title: '자동 분석', okLabel: '시작' })) return;
    try {
      const r = await fetch(`/paper/${slug}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelPicker.value }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      pollAnalyze();
    } catch (e) {
      UIDialog.alert('✗ ' + (e.message || e));
    }
  });

  async function pollPromoteJob(jobId) {
    while (true) {
      await new Promise(r => setTimeout(r, 2000));
      let job;
      try {
        job = await (await fetch(`/papers/jobs/${jobId}`)).json();
      } catch { continue; }
      if (job.status === 'done' && job.slug) {
        location.reload();
        return;
      }
      if (job.status === 'error') {
        UIDialog.alert('✗ 본문 추출 실패: ' + (job.error || 'unknown'));
        return;
      }
    }
  }

  async function pollAnalyze() {
    if (analyzePolling) return;
    analyzePolling = true;
    while (analyzePolling) {
      try {
        const r = await fetch(`/paper/${slug}/analyze/status`);
        const s = await r.json();
        updateAnalyzeButton(s);
        if (s.status === 'done' || s.status === 'error' || s.status === 'cancelled' || s.status === 'idle') {
          analyzePolling = false;
          break;
        }
      } catch {}
      await new Promise(r => setTimeout(r, 1500));
    }
  }

  const aToast = document.getElementById('a-toast');
  const aLabel = document.getElementById('a-toast-label');
  const aFrac = document.getElementById('a-toast-frac');
  const aSub = document.getElementById('a-toast-sub');
  const aLog = document.getElementById('a-toast-log');
  const aPreview = document.getElementById('a-toast-preview');
  document.getElementById('a-toast-cancel').addEventListener('click', async () => {
    if (await UIDialog.confirm('분석을 취소할까요?',
      { title: '분석 취소', danger: true, okLabel: '분석 중단', cancelLabel: '계속' })) {
      await fetch(`/paper/${slug}/analyze/cancel`, { method: 'POST' });
    }
  });

  function updateAnalyzeButton(s) {
    if (s.status === 'running') {
      btnAnalyze.textContent = `${s.current}/${s.total}`;
      btnAnalyze.style.background = 'var(--status-in_progress)';
      btnAnalyze.style.color = 'white';
      btnAnalyze.title = `분석 중: ${s.current_heading} (클릭하여 취소)`;
      renderAnalyzeToast(s);
      aToast.setAttribute('open', '');
    } else {
      btnAnalyze.textContent = 'Analyze';
      btnAnalyze.style.background = '';
      btnAnalyze.style.color = '';
      btnAnalyze.title = '미완료 섹션 자동 분석';
      if (s.status === 'done' || s.status === 'cancelled' || s.status === 'error') {
        // Show final state briefly then hide
        renderAnalyzeToast(s);
        setTimeout(() => aToast.removeAttribute('open'), s.status === 'error' ? 8000 : 3500);
      } else {
        aToast.removeAttribute('open');
      }
      if (s.status === 'error') {
        // Keep error visible
        aLabel.textContent = '✗ Failed';
      }
    }
  }

  function renderAnalyzeToast(s) {
    const failed = (s.failed_sections || []).length;
    aLabel.textContent = s.status === 'running' ? 'Analyzing'
                       : s.status === 'done' ? (failed ? `⚠ Done (${failed} failed)` : '✓ Done')
                       : s.status === 'cancelled' ? '⏹ Cancelled'
                       : s.status === 'error' ? '✗ Error'
                       : '—';
    aFrac.textContent = `${s.current}/${s.total}`;
    aSub.textContent = s.current_heading || '';
    aLog.innerHTML = '';
    (s.log_tail || []).slice(-12).forEach(line => {
      const el = document.createElement('span');
      el.className = 'l';
      if (line.includes('✓')) el.classList.add('done');
      else if (line.includes('✗') || line.includes('⚠')) el.classList.add('err');
      else if (line.startsWith('━━')) el.classList.add('sect');
      el.textContent = line;
      aLog.appendChild(el);
    });
    aLog.scrollTop = aLog.scrollHeight;
    if (s.last_text_preview) {
      aPreview.style.display = '';
      aPreview.textContent = s.last_text_preview;
    } else {
      aPreview.style.display = 'none';
    }
    // Retry block: visible when not running and failed_sections non-empty
    let retry = document.getElementById('a-toast-retry');
    if (!retry) {
      retry = document.createElement('div');
      retry.id = 'a-toast-retry';
      retry.className = 'a-toast-retry';
      aToast.appendChild(retry);
    }
    if (s.status !== 'running' && failed) {
      retry.innerHTML = `
        <div class="r-list">${failed}개 실패: ${s.failed_sections.slice(0, 3).map(f =>
          `<span class="r-pill">${escapeHtml(f)}</span>`).join('')}${failed > 3 ? ` +${failed-3}` : ''}</div>
        <button class="r-btn" id="a-retry-btn">실패한 섹션 재시도</button>
      `;
      retry.style.display = '';
      document.getElementById('a-retry-btn').onclick = async () => {
        retry.style.display = 'none';
        await fetch(`/paper/${slug}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: modelPicker.value, only_sections: s.failed_sections }),
        });
        if (!analyzePolling) pollAnalyze();
      };
    } else {
      retry.style.display = 'none';
    }
  }

  // Check on load — if a job is running already, resume polling
  fetch(`/paper/${slug}/analyze/status`).then(r => r.json()).then(s => {
    if (s.status === 'running') {
      updateAnalyzeButton(s);
      pollAnalyze();
    }
  }).catch(() => {});

  // ───────────────────────────────────────────────────────── Publish
  document.getElementById('btn-publish').addEventListener('click', async () => {
    if (!await UIDialog.confirm('~/Documents/velog-vault/drafts/<slug>.md 로 내보냅니다.', { title: 'Velog draft export', okLabel: 'Export' })) return;
    try {
      const res = await fetch(`/paper/${slug}/publish`, { method: 'POST' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const kb = (data.size / 1024).toFixed(1);
      UIDialog.alert(`✓ Velog draft 생성됨\n\n경로: ${data.draft_path}\n크기: ${kb} KB\n\n터미널에서: velog publish drafts/${slug}.md`);
    } catch (e) {
      UIDialog.alert('✗ ' + (e.message || e));
    }
  });

  // ───────────────────────────────────────────────────────── Chat
  const chatEl = document.getElementById('chat');
  const chatBody = document.getElementById('chat-body');
  const chatEmpty = document.getElementById('chat-empty');
  const chatInput = document.getElementById('chat-input');
  const chatSend = document.getElementById('chat-send');
  const chatMeta = document.getElementById('chat-meta');
  const chatCost = document.getElementById('chat-cost');
  const chatHead = document.getElementById('chat-head');
  let chatBusy = false;
  let pendingClaudeMsg = null;
  let pendingStatusEl = null;
  let toolEls = new Map();

  function toggleChat() {
    if (chatEl.dataset.collapsed) {
      delete chatEl.dataset.collapsed;
      setTimeout(() => chatInput.focus(), 100);
    } else {
      chatEl.dataset.collapsed = "1";
    }
  }
  chatHead.addEventListener('click', toggleChat);
  document.getElementById('btn-chat').addEventListener('click', toggleChat);

  // ───────────────────────────────────────────────────────── PDF export
  // Print the review content to PDF (browser "Save as PDF"). Force the full
  // (detail) view and collapse the nav so the print stylesheet captures the
  // entire workbench; restore the prior view afterwards.
  const btnPdf = document.getElementById('btn-pdf');
  if (btnPdf) btnPdf.addEventListener('click', () => {
    if (editing) { UIDialog.alert('편집 중에는 PDF로 내보낼 수 없습니다. 저장 후 다시 시도하세요.'); return; }
    const prevView = document.getElementById('wb').dataset.view;
    if (prevView !== 'detail') setView('detail');
    const restore = () => { if (prevView && prevView !== 'detail') setView(prevView); window.removeEventListener('afterprint', restore); };
    window.addEventListener('afterprint', restore);
    // let the view switch + KaTeX/layout settle, then open the print dialog
    setTimeout(() => window.print(), 200);
  });

  // ─────────────────────────────────────────────── Bookmark (resume position)
  const BM_KEY = "pr-bm-" + slug;
  function _wbPane() { return document.querySelector(".pane.wb"); }
  let _bmToastT;
  function bmToast(msg) {
    let t = document.getElementById("bm-toast");
    if (!t) { t = document.createElement("div"); t.id = "bm-toast"; t.className = "bm-toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("show");
    clearTimeout(_bmToastT); _bmToastT = setTimeout(() => t.classList.remove("show"), 1400);
  }
  function refreshBookmarkBtn() {
    const b = document.getElementById("btn-bookmark");
    if (b) b.classList.toggle("has-bm", !!localStorage.getItem(BM_KEY));
  }
  // "Reading line" = top edge of the workbench viewport (below the sticky bar).
  function _readY() {
    const wb = _wbPane();
    return (wb ? wb.getBoundingClientRect().top : 49) + 6;
  }
  function setBookmark() {
    const wb = _wbPane(); if (!wb) return;
    const refY = _readY();
    let anchor = null;
    for (const h of wb.querySelectorAll("h1[id],h2[id],h3[id]")) {
      if (h.getBoundingClientRect().top <= refY) anchor = h; else break;
    }
    // Anchor to the nearest heading above the fold + how far past it we are
    // (works whether the pane or the page is the actual scroller).
    const data = anchor
      ? { id: anchor.id, off: Math.round(refY - anchor.getBoundingClientRect().top) }
      : { top: true };
    localStorage.setItem(BM_KEY, JSON.stringify(data));
    refreshBookmarkBtn();
    bmToast("책갈피를 저장했어요");
  }
  function _nudge(px) {
    if (!px) return;
    const wb = _wbPane();
    const el = (wb && wb.scrollTop > 0) ? wb : (document.scrollingElement || wb);
    if (el) el.scrollBy({ top: px, behavior: "smooth" });
  }
  function gotoBookmark() {
    const raw = localStorage.getItem(BM_KEY);
    if (!raw) { setBookmark(); return; }       // nothing yet → set here
    let d; try { d = JSON.parse(raw); } catch { return; }
    if (d.top || !d.id) {
      const wb = _wbPane();
      (wb || document.scrollingElement)?.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const el = document.getElementById(d.id);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      if (d.off) setTimeout(() => _nudge(d.off), 380);   // refine within the section
    }
    bmToast("책갈피로 이동");
  }
  const btnBookmark = document.getElementById("btn-bookmark");
  if (btnBookmark) {
    refreshBookmarkBtn();
    btnBookmark.addEventListener("click", (e) => {
      if (e.shiftKey) { localStorage.removeItem(BM_KEY); refreshBookmarkBtn(); bmToast("책갈피 삭제"); }
      else if (e.altKey) setBookmark();
      else gotoBookmark();
    });
  }

  document.querySelectorAll('.slash-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      if (chatBusy) return;
      const prompt = btn.dataset.prompt;
      sendChat(prompt);
    });
  });

  chatInput.addEventListener('input', () => {
    chatInput.style.height = '36px';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
  });

  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const v = chatInput.value.trim();
      if (v && !chatBusy) {
        sendChat(v);
        chatInput.value = '';
        chatInput.style.height = '36px';
      }
    }
  });

  chatSend.addEventListener('click', () => {
    const v = chatInput.value.trim();
    if (v && !chatBusy) {
      sendChat(v);
      chatInput.value = '';
      chatInput.style.height = '36px';
    }
  });

  function addMsg(role, text = '') {
    if (chatEmpty.parentNode) chatEmpty.remove();
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = text;
    wrap.appendChild(bubble);
    chatBody.appendChild(wrap);
    scrollChatBottom();
    return bubble;
  }
  function addStatus(text) {
    const el = document.createElement('div');
    el.className = 'chat-status';
    el.innerHTML = `<span class="dot"></span><span>${escapeHtml(text)}</span>`;
    chatBody.appendChild(el);
    scrollChatBottom();
    return el;
  }
  function addTool(id, name) {
    const el = document.createElement('div');
    el.className = 'msg-tool';
    el.innerHTML = `<span class="dot"></span><span>tool: <strong>${escapeHtml(name)}</strong></span>`;
    chatBody.appendChild(el);
    toolEls.set(id, el);
    scrollChatBottom();
  }
  function finishTool(id) {
    const el = toolEls.get(id);
    if (el) el.classList.add('done');
  }
  function scrollChatBottom() {
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  async function sendChat(prompt) {
    chatBusy = true;
    chatSend.disabled = true;
    document.querySelectorAll('.slash-chip').forEach(b => b.disabled = true);
    addMsg('user', prompt);
    pendingStatusEl = addStatus('requesting…');
    chatMeta.textContent = '…';
    chatCost.textContent = '';
    pendingClaudeMsg = null;
    toolEls.clear();

    try {
      const res = await fetch(`/paper/${slug}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, model: modelPicker.value }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      await parseSSE(res.body);
    } catch (e) {
      if (pendingStatusEl) { pendingStatusEl.remove(); pendingStatusEl = null; }
      addMsg('claude', '✗ ' + (e.message || String(e)));
    } finally {
      chatBusy = false;
      chatSend.disabled = false;
      document.querySelectorAll('.slash-chip').forEach(b => b.disabled = false);
      chatMeta.textContent = '·';
    }
  }

  async function parseSSE(stream) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\n\n/);
      buffer = events.pop() || '';
      for (const raw of events) {
        const line = raw.trim();
        if (!line.startsWith('data:')) continue;
        const json = line.slice(5).trim();
        if (!json) continue;
        try { handleEvent(JSON.parse(json)); } catch {}
      }
    }
  }

  function handleEvent(ev) {
    if (ev.type === 'user') return;
    if (ev.type === 'system') {
      if (ev.subtype === 'status' && pendingStatusEl) {
        pendingStatusEl.querySelector('span:last-child').textContent = ev.status || '…';
      }
      if (ev.subtype === 'init') {
        chatMeta.textContent = ev.model || 'connected';
      }
      if (ev.subtype === 'summary' && ev.status_detail) {
        chatMeta.textContent = ev.status_detail.slice(0, 60);
      }
      return;
    }
    if (ev.type === 'tool_start') {
      if (pendingStatusEl) { pendingStatusEl.remove(); pendingStatusEl = null; }
      addTool(ev.id, ev.name);
      return;
    }
    if (ev.type === 'delta') {
      if (pendingStatusEl) { pendingStatusEl.remove(); pendingStatusEl = null; }
      if (!pendingClaudeMsg) pendingClaudeMsg = addMsg('claude', '');
      pendingClaudeMsg.textContent += ev.text;
      scrollChatBottom();
      return;
    }
    if (ev.type === 'message_stop') {
      pendingClaudeMsg = null; // next delta starts a new bubble
      return;
    }
    if (ev.type === 'result') {
      if (pendingStatusEl) { pendingStatusEl.remove(); pendingStatusEl = null; }
      toolEls.forEach((el) => el.classList.add('done'));
      const cost = ev.total_cost_usd ? `$${ev.total_cost_usd.toFixed(4)}` : '';
      const dur = ev.duration_ms ? `${(ev.duration_ms/1000).toFixed(1)}s` : '';
      chatCost.textContent = [dur, cost].filter(Boolean).join(' · ');
      // Fallback only — show result text if no delta-driven bubble was produced
      const haveAnyClaudeMsg = !!document.querySelector('.msg.claude .msg-bubble');
      if (ev.is_error && ev.result) addMsg('claude', '⚠ ' + ev.result);
      else if (!haveAnyClaudeMsg && ev.result) addMsg('claude', ev.result);
      return;
    }
    if (ev.type === 'error') {
      if (pendingStatusEl) { pendingStatusEl.remove(); pendingStatusEl = null; }
      addMsg('claude', '✗ ' + (ev.message || ev.stderr || 'error'));
    }
  }

  // ───────────────────────────────────────────────────────── SSE
  function connectSSE() {
    const es = new EventSource(`/paper/${slug}/events`);
    es.addEventListener("change", e => {
      const data = JSON.parse(e.data);
      if (data.file === "workbench.md" && !suppressSSEReload) loadWorkbench();
    });
    es.addEventListener("error", () => {
      es.close();
      setTimeout(connectSSE, 3000);
    });
  }

  // ───────────────────────────────────────────────────────── Theme (apply only)
  // Theme is toggled from the gallery; here we just honor the saved choice.
  (function applySavedTheme() {
    const t = localStorage.getItem('pr-theme') || 'auto';
    if (t === 'dark' || t === 'light') document.body.dataset.theme = t;
    else delete document.body.dataset.theme;
  })();

  // ───────────────────────────────────────────────────────── Init
  loadWorkbench();
  loadFigures();
  connectSSE();
})();
