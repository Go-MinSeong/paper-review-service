
(() => {
  // ─── Render gallery from JSON
  let papers = JSON.parse(document.getElementById('papers-data').textContent);
  const grid = document.getElementById('grid');
  let activeFilter = 'all';
  let searchQuery = '';
  let activeTags = new Set();
  let collapsedTags = new Set();
  let sortBy = localStorage.getItem('pr-sort') || 'created';   // 등록순 default
  // ?capture — freeze live updates (polling/SSE) so the page reaches network
  // idle for clean screenshots.
  const CAPTURE = new URLSearchParams(location.search).has('capture');

  // Status the user can set from the badge (order = menu order). `archived` is
  // hidden from the default "all" view.
  const STATUSES = [
    { k: 'to_read', label: 'Reading' },
    { k: 'in_progress', label: 'In progress' },
    { k: 'review_done', label: 'Reviewed' },
    { k: 'exported', label: 'Exported' },
    { k: 'archived', label: 'Archived' },
  ];
  const STATUS_LABEL = Object.fromEntries(STATUSES.map(s => [s.k, s.label]));
  function statusCounts() {
    // `all` excludes archived so it matches what the default view shows.
    const c = { all: 0, to_read: 0, in_progress: 0, review_done: 0, exported: 0, archived: 0 };
    for (const p of papers) {
      if (c.hasOwnProperty(p.status)) c[p.status]++;
      if (p.status !== 'archived') c.all++;
    }
    return c;
  }
  function papersWithTagPrefix(prefix) {
    return papers.filter(p => (p.tags || []).some(t => t === prefix || t.startsWith(prefix + '/'))).length;
  }
  function buildTagTree() {
    // Collect all tags, build nested tree from slash-delimited paths
    const allTags = new Set();
    for (const p of papers) for (const t of (p.tags || [])) allTags.add(t);
    const root = new Map();
    for (const full of allTags) {
      const parts = full.split('/');
      let node = root;
      let path = '';
      for (const part of parts) {
        path = path ? path + '/' + part : part;
        if (!node.has(part)) node.set(part, { path, children: new Map() });
        node = node.get(part).children;
      }
    }
    return root;
  }
  function renderTagTree() {
    const container = document.getElementById('nav-tags');
    const group = document.getElementById('nav-tags-group');
    const tree = buildTagTree();
    if (!tree.size) { group.style.display = 'none'; return; }
    group.style.display = '';
    const rows = [];
    const walk = (node, depth) => {
      // Sort: by paper count desc, then name
      const entries = [...node.entries()].sort((a, b) =>
        papersWithTagPrefix(b[1].path) - papersWithTagPrefix(a[1].path) ||
        a[0].localeCompare(b[0]));
      for (const [name, info] of entries) {
        const hasChildren = info.children.size > 0;
        const isCollapsed = collapsedTags.has(info.path);
        const cnt = papersWithTagPrefix(info.path);
        const active = activeTags.has(info.path) ? ' active' : '';
        rows.push(`
          <div class="tag-node">
            <button class="nav-item tag-item${active}" data-tag="${escapeHtml(info.path)}" data-depth="${depth}" style="--tagc:${tagColor(info.path)}">
              <span class="tag-twisty ${hasChildren ? (isCollapsed ? 'collapsed' : '') : 'leaf'}" data-twisty="${escapeHtml(info.path)}">▾</span>
              <span class="tag-dot"></span>
              <span class="nav-name">${escapeHtml(name)}</span>
              <span class="nav-n">${cnt}</span>
            </button>
          </div>`);
        if (hasChildren && !isCollapsed) walk(info.children, depth + 1);
      }
    };
    walk(tree, 0);
    container.innerHTML = rows.join('');
    container.querySelectorAll('.nav-item').forEach(b => {
      b.addEventListener('click', (e) => {
        if (e.target.closest('.tag-twisty') && !e.target.closest('.tag-twisty').classList.contains('leaf')) return;
        const t = b.dataset.tag;
        // Single-select: clicking a tag selects only it; clicking it again clears.
        if (activeTags.has(t)) {
          activeTags.clear();
        } else {
          activeTags.clear();
          activeTags.add(t);
        }
        renderTagTree();
        renderCards();
        updateClearTags();
      });
    });
    container.querySelectorAll('.tag-twisty').forEach(tw => {
      if (tw.classList.contains('leaf')) return;
      tw.addEventListener('click', (e) => {
        e.stopPropagation();
        const p = tw.dataset.twisty;
        if (collapsedTags.has(p)) collapsedTags.delete(p);
        else collapsedTags.add(p);
        renderTagTree();
      });
    });
  }
  function updateClearTags() {
    const el = document.getElementById('clear-tags');
    el.style.display = activeTags.size ? '' : 'none';
  }
  function updateCounts() {
    const c = statusCounts();
    for (const [k, v] of Object.entries(c)) {
      const el = document.querySelector(`.side-nav [data-count="${k}"]`);
      if (el) el.textContent = v;
    }
  }
  function hashHue(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 10;
    return h;
  }
  // Full filenames (with extension). Refreshed from /illustrations at load so
  // added/removed illustrations show up on cards. The hardcoded list is the
  // fallback if the fetch fails.
  let CHARACTERS = [
    "badger.jpg", "corgi.jpg", "dolphin.jpg", "fennec.jpg", "penguin.jpg", "redpanda.jpg",
  ];
  function hashStr(s) {
    // djb2 — better spread than a per-step modulo (slugs are mostly digits)
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }
  function hashChar(s) { return hashStr(s) % CHARACTERS.length; }

  // Illustration grouping: papers with similar tags draw from the same group,
  // so the gallery looks thematically consistent. Loaded from /illustration-groups.
  let ILLUST_GROUPS = {};   // { groupName: [file, ...] }
  let TAG_GROUPS = {};      // { tag(lowercase): groupName }
  function groupForTags(tags) {
    for (const t of (tags || [])) {
      // try the full tag and each "/"-separated segment (e.g. CV/segmentation)
      for (const cand of [t, ...String(t).split('/')]) {
        const g = TAG_GROUPS[cand.trim().toLowerCase()];
        if (g && ILLUST_GROUPS[g] && ILLUST_GROUPS[g].length) return g;
      }
    }
    return null;
  }
  // Character (base name) of an illustration file: "redpanda-2.jpg" → "redpanda".
  // Different variants of the same character count as the *same* character so we
  // never show two red pandas while another character is still unused.
  function illustBase(f) {
    return (f || '').replace(/\.[^.]+$/, '').replace(/-\d+$/, '');
  }
  // Usage counters (reset each renderCards). Dedup is enforced at the character
  // level: a character isn't reused until every character in the pool has been
  // used; variant rotation (file level) only breaks ties within a character.
  let _charUsage = {}, _fileUsage = {};
  // Pick a card illustration: prefer the tag-mapped group, else the global pool.
  // Choose the least-used character first, then its least-used variant, with a
  // deterministic hash tie-break, and count both.
  function pickIllust(p) {
    const g = groupForTags(p.tags);
    let pool = g ? ILLUST_GROUPS[g] : CHARACTERS;
    if (!pool || !pool.length) pool = CHARACTERS;
    // No-repeat rule wins over grouping: if every character in the tag group is
    // already used this render, widen to the global pool so an as-yet-unused
    // character is shown instead of repeating one from the (small) group.
    if (pool !== CHARACTERS && !pool.some(f => !_charUsage[illustBase(f)])) {
      pool = CHARACTERS;
    }
    const key = (p.title_en || p.title_ko || p.slug) + p.slug;
    let best = pool[0], bestC = Infinity, bestF = Infinity, bestH = Infinity;
    for (const f of pool) {
      const cu = _charUsage[illustBase(f)] || 0;
      const fu = _fileUsage[f] || 0;
      const h = hashStr(key + '|' + f);
      if (cu < bestC
          || (cu === bestC && fu < bestF)
          || (cu === bestC && fu === bestF && h < bestH)) {
        best = f; bestC = cu; bestF = fu; bestH = h;
      }
    }
    _charUsage[illustBase(best)] = (_charUsage[illustBase(best)] || 0) + 1;
    _fileUsage[best] = (_fileUsage[best] || 0) + 1;
    return best;
  }
  function initials(s) {
    const tokens = s.replace(/[:\-]/g, ' ').split(/\s+/).filter(Boolean);
    if (!tokens.length) return '?';
    return (tokens[0][0] || '?').toUpperCase()
      + (tokens.length > 1 ? (tokens[1][0] || '').toUpperCase() : '');
  }
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  }
  function starsHTML(rating, slug) {
    const r = rating || 0;
    const stars = [1,2,3,4,5].map(i =>
      `<span class="star${i <= r ? ' on' : ''}" data-v="${i}">★</span>`).join('');
    return `<span class="card-rating" data-slug="${escapeHtml(slug)}" data-rating="${r}" title="별점">${stars}</span>`;
  }
  // Deterministic per-tag color. Hue is derived from the top-level segment
  // so a family ("CV", "CV/segmentation", "CV/detection") shares one hue.
  function tagHue(name) {
    const s = (name || '').split('/')[0];
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 37 + s.charCodeAt(i)) >>> 0;
    return h % 360;
  }
  function tagColor(name) { return `hsl(${tagHue(name)} 58% 52%)`; }
  function relTime(sec) {
    if (!sec) return '';
    const diff = Date.now() / 1000 - sec;
    if (diff < 90) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 86400 * 7) return Math.floor(diff / 86400) + 'd ago';
    if (diff < 86400 * 30) return Math.floor(diff / 86400 / 7) + 'w ago';
    if (diff < 86400 * 365) return Math.floor(diff / 86400 / 30) + 'mo ago';
    return Math.floor(diff / 86400 / 365) + 'y ago';
  }
  function renderCards() {
    _charUsage = {}; _fileUsage = {};  // reset usage so spreading is recomputed per render
    const filtered = papers.filter(p => {
      // Default view ("all") hides archived; a specific filter matches exactly.
      if (activeFilter === 'all') { if (p.status === 'archived') return false; }
      else if (p.status !== activeFilter) return false;
      if (activeTags.size) {
        const tags = p.tags || [];
        // Each selected tag (or any of its descendants) must be present
        for (const sel of activeTags) {
          if (!tags.some(t => t === sel || t.startsWith(sel + '/'))) return false;
        }
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const hay = `${p.title_en} ${p.title_ko} ${p.category} ${p.slug} ${(p.tags||[]).join(' ')}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // Sort: 등록순(created) / 편집순(edited) / 별점순(rating). All newest/highest first.
    const cmp = {
      created: (a, b) => (b.created_at || 0) - (a.created_at || 0),
      edited: (a, b) => (b.updated_at || 0) - (a.updated_at || 0),
      published: (a, b) => (b.published_ym || 0) - (a.published_ym || 0) || (b.created_at || 0) - (a.created_at || 0),
      rating: (a, b) => (b.rating || 0) - (a.rating || 0) || (b.updated_at || 0) - (a.updated_at || 0),
    }[sortBy] || ((a, b) => (b.created_at || 0) - (a.created_at || 0));
    filtered.sort(cmp);
    const rc = document.getElementById('result-count');
    if (rc) rc.textContent = `${filtered.length} / ${papers.length}`;

    if (!papers.length) {
      grid.innerHTML = `
        <div class="empty" style="grid-column: 1 / -1">
          <div class="ico">📄</div>
          <div class="t1">아직 paper가 없습니다</div>
          <div class="t2">arXiv URL 또는 로컬 PDF로 시작해보세요</div>
          <button class="btn-new" onclick="document.getElementById('btn-new').click()"><span class="plus">+</span> 새 paper 추가</button>
        </div>`;
      return;
    }
    if (!filtered.length) {
      grid.innerHTML = `
        <div class="empty" style="grid-column: 1 / -1">
          <div class="ico">⌕</div>
          <div class="t1">검색 결과 없음</div>
          <div class="t2">필터 또는 검색어를 바꿔보세요</div>
        </div>`;
      return;
    }
    grid.innerHTML = filtered.map(p => {
      const title = p.title_ko || p.title_en || p.slug;
      const subTitle = (p.title_ko && p.title_en) ? p.title_en : '';
      const charName = pickIllust(p);
      const ci = hashStr(charName) % 14;  // thumb background tint (char-bg-0..13)
      const total = Math.max(p.sections_total || 0, 1);
      const done = p.sections_done || 0;
      const isActive = activeJobs.has(p.slug);
      const activeMeta = activeJobs.get(p.slug);
      // While a background analysis runs, the progress bar tracks the live job
      // (current/total); otherwise it shows the workbench done count.
      const running = isActive && activeMeta && activeMeta.status === 'running';
      // Report phase has no per-section fraction (and a report-only job has
      // total 0), so it gets its own pill instead of a stuck 100% bar.
      const reportPhase = running && activeMeta.phase === 'report';
      const live = running && !reportPhase && activeMeta.total > 0;
      const failedJob = isActive && activeMeta && !running &&
        (activeMeta.status === 'error' || (activeMeta.failed || 0) > 0);
      const dispDone = live ? activeMeta.current : done;
      const dispTotal = live ? activeMeta.total : total;
      const pct = Math.round((dispDone / Math.max(dispTotal, 1)) * 100);
      const segs = Math.min(dispTotal, 14);
      const doneSegs = Math.round((dispDone / Math.max(dispTotal, 1)) * segs);
      const bars = Array.from({length: segs}, (_, i) =>
        `<span class="seg${i < doneSegs ? ' done' : ''}"></span>`).join('');
      const tags = p.tags || [];
      const tagsHTML = tags.length
        ? `<div class="card-tags">${tags.slice(0, 3).map(t => `<span class="t" style="--tagc:${tagColor(t)}">${escapeHtml(t)}</span>`).join('')}${tags.length > 3 ? `<span class="t more">+${tags.length - 3}</span>` : ''}</div>`
        : '';
      const isToRead = p.status === 'to_read';
      return `
        <a class="card${running ? ' analyzing' : ''}${p.on_remote ? ' on-remote' : ''}" href="/paper/${p.slug}" data-slug="${p.slug}" ${p.on_remote ? 'title="모바일 슬롯에 올라가 있는 페이퍼"' : ''}>
          <div class="card-thumb char-bg-${ci}">
            <img class="card-illust" src="/static/characters/${charName}" alt="" loading="${CAPTURE ? 'eager' : 'lazy'}">
            <button class="badge s-${p.status}" data-status="${escapeHtml(p.slug)}" title="상태 변경">${p.status === 'to_read' ? 'reading' : p.status}</button>
            <span class="type-badge t-${escapeHtml(p.content_type || 'paper')}">${escapeHtml(p.content_type || 'paper')}</span>
            <button class="card-log" data-log="${escapeHtml(p.slug)}" title="분석 로그">▤</button>
            <button class="card-remote" data-remote="${escapeHtml(p.slug)}" title="${p.on_remote ? '지금 모바일 슬롯에 있는 페이퍼 — 다시 보내면 최신 내용으로 갱신' : '모바일로 보내기 (원격 슬롯 교체)'}">📱</button>
            <button class="card-tagedit" data-tagedit="${escapeHtml(p.slug)}" title="태그 편집">🏷</button>
            <button class="card-del" data-del="${escapeHtml(p.slug)}" title="삭제">🗑</button>
            ${live ? `<span class="pulse" data-log="${escapeHtml(p.slug)}" title="분석 로그 보기">분석 중 ${activeMeta.current}/${activeMeta.total} · ${pct}%</span>` : ''}
          ${reportPhase ? `<span class="pulse" data-log="${escapeHtml(p.slug)}" title="분석 로그 보기">Summary 생성 중</span>` : ''}
            ${starsHTML(p.rating, p.slug)}
          </div>
          <div class="card-body">
            <div class="card-title">${escapeHtml(title)}</div>
            ${subTitle ? `<div class="card-sub">${escapeHtml(subTitle)}</div>` : ''}
            ${dispTotal > 0 ? `<div class="progress${live ? ' analyzing' : ''}">${bars}</div>` : ''}
            <div class="card-foot">
              ${isToRead ? '<span class="frac">reading list</span>'
                : live ? `<span class="frac analyzing">⟳ 분석 ${dispDone}/${dispTotal} · ${pct}%</span>`
                : `<span class="frac">${done}/${total} sections</span>`}
              ${failedJob ? `<span class="sep">·</span><span class="frac err" data-log="${escapeHtml(p.slug)}" title="분석 로그 보기">⚠ 분석 실패${activeMeta.failed ? ` (${activeMeta.failed})` : ''}</span>` : ''}
              ${p.category ? `<span class="sep">·</span><span class="cat">${escapeHtml(p.category)}</span>` : ''}
              ${p.figures_count > 0 ? `<span class="sep">·</span><span>${p.figures_count} figs</span>` : ''}
              ${(p.updated_at || p.last_viewed) ? `<span class="sep">·</span><span class="act">${(p.last_viewed || 0) > (p.updated_at || 0) ? 'viewed' : 'edited'} ${relTime(Math.max(p.last_viewed || 0, p.updated_at || 0))}</span>` : ''}
            </div>
            ${tagsHTML}
          </div>
        </a>`;
    }).join('');
  }
  // ── Reusable chip-based tag input ──────────────────────────────────────
  // Renders tags as removable colored chips + an inline field; suggests
  // existing tags (click or autocomplete) to keep the vocabulary consistent.
  function makeTagInput(mountEl, initial) {
    const seen = new Set();
    const tags = [];
    (initial || []).forEach(t => {
      t = (t || '').trim();
      if (t && !seen.has(t)) { seen.add(t); tags.push(t); }
    });
    const allTags = [...new Set(papers.flatMap(p => p.tags || []))]
      .filter(Boolean).sort((a, b) => a.localeCompare(b));

    mountEl.classList.add('taginput-wrap');
    mountEl.innerHTML =
      '<div class="taginput"><input class="taginput-field" type="text" autocomplete="off" placeholder="태그 입력 후 Enter…"></div>' +
      '<div class="tagsugg"></div>';
    const box = mountEl.querySelector('.taginput');
    const field = mountEl.querySelector('.taginput-field');
    const sugg = mountEl.querySelector('.tagsugg');

    const add = (name) => {
      name = (name || '').trim().replace(/^#/, '');
      field.value = '';
      if (name && !seen.has(name)) { seen.add(name); tags.push(name); renderChips(); }
      renderSugg(); field.focus();
    };
    const remove = (name) => {
      const i = tags.indexOf(name);
      if (i >= 0) { tags.splice(i, 1); seen.delete(name); renderChips(); renderSugg(); }
    };
    function renderChips() {
      box.querySelectorAll('.tag-chip').forEach(n => n.remove());
      tags.forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.style.setProperty('--tagc', tagColor(t));
        chip.innerHTML = `<span class="tc-name">${escapeHtml(t)}</span><button type="button" class="tc-x" title="삭제">×</button>`;
        chip.querySelector('.tc-x').addEventListener('click', () => remove(t));
        box.insertBefore(chip, field);
      });
    }
    function renderSugg() {
      const q = field.value.trim().toLowerCase();
      let list = allTags.filter(t => !seen.has(t));
      if (q) list = list.filter(t => t.toLowerCase().includes(q));
      list = list.slice(0, 12);
      sugg.innerHTML = list.length
        ? '<span class="tagsugg-label">기존 태그</span>' + list.map(t =>
            `<button type="button" class="tagsugg-item" style="--tagc:${tagColor(t)}" data-t="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join('')
        : '';
      sugg.querySelectorAll('.tagsugg-item').forEach(b => b.addEventListener('click', () => add(b.dataset.t)));
    }
    field.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(field.value); }
      else if (e.key === 'Backspace' && !field.value && tags.length) { remove(tags[tags.length - 1]); }
    });
    field.addEventListener('input', renderSugg);
    box.addEventListener('mousedown', e => { if (e.target === box) { e.preventDefault(); field.focus(); } });
    renderChips(); renderSugg();
    return { getTags: () => [...tags], focus: () => field.focus() };
  }

  // ── Tag edit modal (chip-based) ────────────────────────────────────────
  const tagsModal = document.getElementById('modal-tags');
  const editTagsMount = document.getElementById('edit-tags-mount');
  let tagEditState = null; // { slug, paper, input }
  function openTagEditor(slug) {
    const paper = papers.find(p => p.slug === slug);
    if (!paper) return;
    const titleEl = document.getElementById('modal-tags-title');
    if (titleEl) titleEl.textContent = `태그 편집 — ${paper.title_ko || paper.title_en || slug}`.slice(0, 60);
    const input = makeTagInput(editTagsMount, paper.tags || []);
    tagEditState = { slug, paper, input };
    tagsModal.setAttribute('open', '');
    setTimeout(() => input.focus(), 80);
  }
  function closeTagEditor() { tagsModal.removeAttribute('open'); tagEditState = null; }
  tagsModal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeTagEditor));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && tagsModal.hasAttribute('open')) closeTagEditor();
  });
  document.getElementById('btn-tags-save').addEventListener('click', async () => {
    if (!tagEditState) return;
    const { slug, paper, input } = tagEditState;
    const tags = input.getTags();
    try {
      const r = await fetch(`/paper/${encodeURIComponent(slug)}/tags`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      paper.tags = tags;
      closeTagEditor();
      renderTagTree(); renderCards(); updateClearTags();
    } catch (err) {
      UIDialog.alert('태그 저장 실패: ' + (err.message || err), { title: '오류' });
    }
  });
  // Tag edit launcher (event-delegated on the grid)
  grid.addEventListener('click', (e) => {
    const tbtn = e.target.closest('.card-tagedit');
    if (!tbtn) return;
    e.preventDefault();
    e.stopPropagation();
    openTagEditor(tbtn.dataset.tagedit);
  });
  // Mobile push — replace the remote slot with this paper (moved here from the
  // detail topbar: slot swapping is a list-level action).
  grid.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-remote]');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    const slug = b.dataset.remote;
    const ok = await UIDialog.confirm(
      '이 페이퍼로 원격(모바일) 슬롯을 교체할까요?\n기존 슬롯 내용은 사라집니다.',
      { okLabel: '보내기', cancelLabel: '취소' });
    if (!ok) return;
    b.disabled = true;
    try {
      const r = await fetch(`/paper/${encodeURIComponent(slug)}/remote-push`, { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
      papers.forEach(x => x.on_remote = x.slug === slug);   // the slot moved
      renderCards();
      UIDialog.alert(
        `원격 슬롯에 푸시됨 (rev ${j.rev}).` +
        (j.has_report ? '\nSummary 리포트도 함께 전송됨.' : '\n(Summary 리포트 없음 — Analyze 후 다시 보내면 포함됩니다)') +
        `\n모바일에서 열기: ${j.url}`, { title: '📱 완료' });
    } catch (err) {
      UIDialog.alert('푸시 실패: ' + (err.message || err), { title: '오류' });
    } finally { b.disabled = false; }
  });

  // Analyze-log launcher — open the run log straight from the list (the
  // "분석 중" pulse or a "⚠ 분석 실패" chip), without leaving the gallery.
  grid.addEventListener('click', (e) => {
    const el = e.target.closest('[data-log]');
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    openAnalyzeLog(el.dataset.log);
  });
  // ── Status menu (click a card's status badge to change it) ──────────────
  let _statusMenu = null;
  function closeStatusMenu() { if (_statusMenu) { _statusMenu.remove(); _statusMenu = null; } }
  function openStatusMenu(anchor, slug) {
    closeStatusMenu();
    const paper = papers.find(p => p.slug === slug);
    const cur = paper ? paper.status : '';
    const menu = document.createElement('div');
    menu.className = 'status-menu';
    menu.innerHTML = STATUSES.map(s =>
      `<button class="status-opt s-${s.k}${s.k === cur ? ' cur' : ''}" data-set="${s.k}">${s.label}</button>`
    ).join('');
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.top = Math.round(r.bottom + 4) + 'px';
    menu.style.left = Math.round(Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
    _statusMenu = menu;
    menu.addEventListener('click', async (e) => {
      const opt = e.target.closest('[data-set]');
      if (!opt) return;
      const status = opt.dataset.set;
      closeStatusMenu();
      if (!paper || status === cur) return;
      paper.status = status;
      renderCards(); updateCounts();
      const dEl = document.getElementById('dashboard');
      if (dEl && !dEl.hidden && typeof renderDashboard === 'function') renderDashboard();
      try {
        const res = await fetch(`/paper/${encodeURIComponent(slug)}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
      } catch (err) {
        UIDialog.alert('상태 변경 실패: ' + (err.message || err), { title: '오류' });
      }
    });
  }
  document.addEventListener('click', (e) => {
    if (_statusMenu && !_statusMenu.contains(e.target) && !e.target.closest('[data-status]')) closeStatusMenu();
  }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeStatusMenu(); });

  // Status badge — click to open a menu and set the status manually.
  grid.addEventListener('click', (e) => {
    const b = e.target.closest('[data-status]');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    openStatusMenu(b, b.dataset.status);
  });
  // Star rating (event-delegated) — click a star to set, click the current to clear
  grid.addEventListener('click', async (e) => {
    const star = e.target.closest('.card-rating .star');
    if (!star) return;
    e.preventDefault();
    e.stopPropagation();
    const wrap = star.closest('.card-rating');
    const slug = wrap.dataset.slug;
    let v = +star.dataset.v;
    if (v === (+wrap.dataset.rating || 0)) v = 0;
    wrap.dataset.rating = v;
    wrap.querySelectorAll('.star').forEach((s, i) => s.classList.toggle('on', i < v));
    const paper = papers.find(p => p.slug === slug);
    if (paper) paper.rating = v;
    const dEl = document.getElementById('dashboard');
    if (dEl && !dEl.hidden && typeof renderDashboard === 'function') renderDashboard();
    try {
      await fetch(`/paper/${encodeURIComponent(slug)}/rating`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: v }),
      });
    } catch (_) { /* non-fatal */ }
  });

  // Delete (event-delegated so it survives re-renders)
  grid.addEventListener('click', async (e) => {
    const btn = e.target.closest('.card-del');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const slug = btn.dataset.del;
    const ok = await UIDialog.confirm(
      `"${slug}" 를 삭제할까요?\n원본 PDF · 워크벤치 · 분석 결과가 모두 사라집니다 (되돌릴 수 없음).`,
      { title: 'paper 삭제', danger: true, okLabel: '삭제' });
    if (!ok) return;
    btn.textContent = '…';
    try {
      const r = await fetch(`/paper/${encodeURIComponent(slug)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const idx = papers.findIndex(p => p.slug === slug);
      if (idx >= 0) papers.splice(idx, 1);
      updateCounts();
      renderTagTree();
      renderCards();
      updateClearTags();
    } catch (err) {
      UIDialog.alert('삭제 실패: ' + (err.message || err), { title: '오류' });
      btn.textContent = '🗑';
    }
  });

  document.querySelectorAll('.side-nav .nav-item[data-filter]').forEach(b => {
    b.addEventListener('click', () => {
      document.querySelectorAll('.side-nav .nav-item[data-filter]').forEach(o =>
        o.classList.toggle('active', o === b));
      activeFilter = b.dataset.filter;
      renderCards();
    });
  });
  document.getElementById('clear-tags').addEventListener('click', () => {
    activeTags.clear();
    renderTagTree();
    renderCards();
    updateClearTags();
  });
  const searchEl = document.getElementById('search');
  searchEl.addEventListener('input', () => {
    searchQuery = searchEl.value;
    renderCards();
  });
  // Sort selector (등록순 / 편집순 / 별점순)
  const sortEl = document.getElementById('sort-select');
  if (sortEl) {
    sortEl.value = sortBy;
    sortEl.addEventListener('change', () => {
      sortBy = sortEl.value;
      localStorage.setItem('pr-sort', sortBy);
      renderCards();
    });
  }
  // Sidebar toggle (narrow)
  const sidebarEl = document.getElementById('sidebar');
  document.getElementById('sidebar-toggle').addEventListener('click', () => {
    if (sidebarEl.dataset.open) delete sidebarEl.dataset.open;
    else sidebarEl.dataset.open = '1';
  });
  // ─── Active jobs polling (gallery indicator)
  let activeJobs = new Map(); // slug → {current, total, current_heading}
  async function pollActiveJobs() {
    try {
      const r = await fetch('/papers/active-jobs');
      const list = await r.json();
      const next = new Map(list.map(j => [j.slug, j]));
      // A job that disappeared just finished — bake its progress into the
      // static done count so the bar lands on the final value (no full reload).
      let finalized = false;
      for (const [slug, prev] of activeJobs) {
        if (!next.has(slug)) {
          const p = papers.find(x => x.slug === slug);
          if (p && prev.total) { p.sections_done = Math.max(p.sections_done || 0, prev.current); finalized = true; }
        }
      }
      // Only re-render if set changed
      const same = next.size === activeJobs.size &&
        [...next.keys()].every(k => activeJobs.has(k) &&
          activeJobs.get(k).current === next.get(k).current &&
          activeJobs.get(k).phase === next.get(k).phase);
      activeJobs = next;
      if (!same || finalized) renderCards();
    } catch {}
  }
  pollActiveJobs();
  if (!CAPTURE) setInterval(pollActiveJobs, 3000);

  // ─── Analyze log modal (reachable from the list — pulse / failure chip)
  const aLogModal = document.getElementById('modal-alog');
  async function openAnalyzeLog(slug) {
    const body = document.getElementById('alog-body');
    const statusEl = document.getElementById('alog-status');
    const failedEl = document.getElementById('alog-failed');
    const titleEl = document.getElementById('alog-title');
    const p = papers.find(x => x.slug === slug);
    titleEl.textContent = '분석 로그 — ' + ((p && (p.title_ko || p.title_en)) || slug);
    body.textContent = '불러오는 중…';
    failedEl.textContent = '';
    statusEl.textContent = '';
    aLogModal.setAttribute('open', '');
    try {
      const s = await (await fetch(`/paper/${encodeURIComponent(slug)}/analyze/status`)).json();
      statusEl.textContent = `${s.status} · ${s.current || 0}/${s.total || 0}`;
      const failed = s.failed_sections || [];
      failedEl.textContent = failed.length
        ? `실패 섹션 (${failed.length}): ${failed.join(', ')}` : '';
      const lines = s.log_tail || [];
      body.textContent = lines.length
        ? lines.join('\n')
        : (s.status === 'idle' ? '아직 분석을 실행한 적이 없습니다.' : '로그 없음');
      if (s.error) body.textContent += `\n\n✗ ${s.error}`;
      body.scrollTop = body.scrollHeight;
    } catch (e) { body.textContent = '상태를 불러오지 못했습니다: ' + e; }
  }
  aLogModal.querySelectorAll('[data-close]').forEach(el =>
    el.addEventListener('click', () => aLogModal.removeAttribute('open')));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && aLogModal.hasAttribute('open')) aLogModal.removeAttribute('open');
  });

  // ─── Theme toggle
  // Dark-ish themes (for the toggle glyph + auto handling).
  const DARK_THEMES = new Set(['dark', 'tesla', 'sunset']);
  function applyTheme(t) {
    if (t && t !== 'auto') document.body.dataset.theme = t;
    else delete document.body.dataset.theme;
    const tb = document.getElementById('theme-toggle');
    const isDark = DARK_THEMES.has(t) || (t === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
    if (tb) tb.textContent = isDark ? '☾' : '☼';
    document.querySelectorAll('#theme-grid .theme-card').forEach(c =>
      c.classList.toggle('active', c.dataset.theme === (t || 'auto')));
  }
  const savedTheme = localStorage.getItem('pr-theme') || 'auto';
  applyTheme(savedTheme);
  // Pull mobile edits from the remote slot back into the local workbench.
  document.getElementById('remote-pull-btn').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const r = await fetch('/remote-pull', { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
      if (j.changed) {
        await UIDialog.alert(`${j.slug} 워크벤치를 원격(rev ${j.rev}) 내용으로 갱신했습니다.\n이전 내용은 workbench.md.bak에 백업.`, { title: '📥 동기화 완료' });
        location.reload();
      } else {
        UIDialog.alert(`${j.slug} — 이미 최신입니다 (rev ${j.rev}).`, { title: '📥' });
      }
    } catch (err) {
      UIDialog.alert('가져오기 실패: ' + (err.message || err), { title: '오류' });
    } finally { btn.disabled = false; }
  });
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const cur = localStorage.getItem('pr-theme') || 'auto';
    const next = cur === 'auto' ? 'dark' : cur === 'dark' ? 'light' : 'auto';
    localStorage.setItem('pr-theme', next);
    applyTheme(next);
  });

  updateCounts();
  renderTagTree();
  renderCards();
  updateClearTags();

  // The list is embedded at render time, so a window left open (the desktop app
  // has no address bar to reload from) kept showing the library as it was at
  // launch — papers added since simply weren't there. Re-read it when the
  // window comes back to the foreground.
  let refreshing = false;
  async function refreshPapers() {
    if (refreshing || CAPTURE) return;
    refreshing = true;
    try {
      const r = await fetch('/papers.json', { cache: 'no-store' });
      if (!r.ok) return;
      const next = await r.json();
      if (JSON.stringify(next) === JSON.stringify(papers)) return;
      papers = next;
      updateCounts();
      renderTagTree();
      renderCards();
    } catch (e) { /* offline / server restarting — keep what we have */ }
    finally { refreshing = false; }
  }
  window.addEventListener('focus', refreshPapers);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshPapers();
  });

  // ─── Dashboard (client-side aggregates over `papers`) ────────────
  const dashEl = document.getElementById('dashboard');
  const dashToggle = document.getElementById('dash-toggle');
  function dashBars(rows, max, cls) {
    return rows.map(([label, n]) =>
      `<div class="dash-bar-row"><span class="lbl" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`
      + `<span class="bar"><i class="${cls || ''}" style="width:${Math.max(4, Math.round(n / max * 100))}%"></i></span>`
      + `<span class="val">${n}</span></div>`).join('');
  }
  // ── Dashboard (two views, both monthly) ──────────────────────────────
  // Intake  = when papers arrived (folder creation, else review_started)
  // Export  = when papers were exported (frontmatter exported_at)
  let dashTab = localStorage.getItem('pr-dash-tab') || 'intake';
  const MONTHS = 12;

  function monthKey(ms) {
    const d = new Date(ms);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }
  function lastMonthKeys(n) {
    const now = new Date(), out = [];
    for (let i = n - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }
    return out;
  }
  function intakeMs(p) {
    if (p.created_at) return p.created_at * 1000;
    if (/^\d{4}-\d{2}-\d{2}/.test(p.review_started || '')) return new Date(p.review_started + 'T00:00:00').getTime();
    return 0;
  }
  function exportMs(p) {
    return /^\d{4}-\d{2}-\d{2}/.test(p.exported_at || '')
      ? new Date(p.exported_at + 'T00:00:00').getTime() : 0;
  }
  function monthChart(map, cls) {
    const keys = lastMonthKeys(MONTHS);
    const max = Math.max(1, ...keys.map(k => map[k] || 0));
    const cols = keys.map(k => {
      const n = map[k] || 0;
      const h = n ? Math.max(6, Math.round(n / max * 76)) : 2;
      const mm = +k.split('-')[1];
      return `<span class="mcol" title="${k} · ${n}">`
        + `<span class="m-val">${n || ''}</span>`
        + `<i class="${n ? (cls || '') : 'zero'}" style="height:${h}px"></i>`
        + `<span class="m-lbl">${mm}</span></span>`;
    }).join('');
    return `<div class="mchart">${cols}</div>`;
  }
  function monthRangeLabel() {
    const keys = lastMonthKeys(MONTHS);
    const f = k => k.replace('-', '.');
    return `${f(keys[0])} – ${f(keys[keys.length - 1])}`;
  }
  function ratingRows(list) {
    const dist = [5, 4, 3, 2, 1].map(r => [r + '★', list.filter(p => p.rating === r).length]);
    return { dist, max: Math.max(1, ...dist.map(d => d[1])), rated: list.filter(p => (p.rating || 0) > 0) };
  }
  function topTagRows(list, n = 6) {
    const c = {};
    list.forEach(p => (p.tags || []).forEach(t => { c[t] = (c[t] || 0) + 1; }));
    const rows = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, n);
    return { rows, max: Math.max(1, ...rows.map(r => r[1])) };
  }

  function dashIntakeHtml() {
    const N = papers.length;
    const STAT = [
      { k: 'to_read', label: 'Reading', cls: 'to_read' },
      { k: 'in_progress', label: 'In progress', cls: 'in_progress' },
      { k: 'review_done', label: 'Reviewed', cls: 'review_done' },
      { k: 'exported', label: 'Exported', cls: 'exported' },
      { k: 'archived', label: 'Archived', cls: 'archived' },
    ].map(s => ({ ...s, n: papers.filter(p => p.status === s.k).length }));
    let secDone = 0, secTotal = 0;
    papers.forEach(p => { secDone += p.sections_done || 0; secTotal += p.sections_total || 0; });
    const secPct = secTotal ? Math.round(secDone / secTotal * 100) : 0;
    const { dist, max: maxRD, rated } = ratingRows(papers);
    const avg = rated.length ? (rated.reduce((a, p) => a + p.rating, 0) / rated.length) : 0;
    const { rows: tagRows, max: maxTag } = topTagRows(papers);

    const map = {}; let undated = 0;
    papers.forEach(p => { const ms = intakeMs(p); if (ms) map[monthKey(ms)] = (map[monthKey(ms)] || 0) + 1; else undated++; });
    const inWindow = lastMonthKeys(MONTHS).reduce((a, k) => a + (map[k] || 0), 0);

    return `
      <div class="dash-row dash-row1">
        <div class="kpi"><div class="kpi-num">${N}</div><div class="kpi-lbl">Papers</div></div>
        <div class="kpi"><div class="kpi-num">${secPct}<span class="u">%</span></div><div class="kpi-lbl">Sections · ${secDone}/${secTotal}</div></div>
        <div class="kpi"><div class="kpi-num">${avg ? avg.toFixed(1) : '–'}${avg ? '<span class="u gold">★</span>' : ''}</div><div class="kpi-lbl">Avg rating · ${rated.length}</div></div>
        <div class="dash-card c-status">
          <div class="dash-title">Review status</div>
          <div class="dash-funnel">
            ${STAT.filter(s => s.n).map(s => `<span class="seg s-${s.cls}" style="flex:${s.n}" title="${s.label} ${s.n}"></span>`).join('') || '<span class="seg" style="flex:1;background:var(--border-default)"></span>'}
          </div>
          <div class="dash-legend">
            ${STAT.map(s => `<span><i class="dot s-${s.cls}"></i>${s.label} <b>${s.n}</b></span>`).join('')}
          </div>
        </div>
      </div>
      <div class="dash-row dash-row2">
        <div class="dash-card c-month">
          <div class="dash-title">Monthly intake <span class="dash-sub">${monthRangeLabel()} · ${inWindow} papers${undated ? ` · ${undated} undated` : ''}</span></div>
          ${monthChart(map)}
        </div>
        <div class="dash-card c-rating">
          <div class="dash-title">Rating distribution</div>
          ${rated.length ? dashBars(dist, maxRD, 'gold') : '<div class="dash-empty">No ratings yet</div>'}
        </div>
        <div class="dash-card c-tags">
          <div class="dash-title">Top tags</div>
          ${tagRows.length ? dashBars(tagRows, maxTag) : '<div class="dash-empty">No tags</div>'}
        </div>
      </div>`;
  }

  function dashExportHtml() {
    const exported = papers.filter(p => p.status === 'exported' || exportMs(p));
    const dated = exported.filter(p => exportMs(p));
    const rate = papers.length ? Math.round(exported.length / papers.length * 100) : 0;
    // median days intake → export (only papers where both dates are known)
    const spans = dated.map(p => {
      const a = intakeMs(p), b = exportMs(p);
      return a && b && b >= a ? Math.round((b - a) / 86400000) : null;
    }).filter(v => v !== null).sort((x, y) => x - y);
    const median = spans.length
      ? (spans.length % 2 ? spans[(spans.length - 1) / 2]
        : Math.round((spans[spans.length / 2 - 1] + spans[spans.length / 2]) / 2))
      : null;

    const map = {};
    dated.forEach(p => { const k = monthKey(exportMs(p)); map[k] = (map[k] || 0) + 1; });
    const inWindow = lastMonthKeys(MONTHS).reduce((a, k) => a + (map[k] || 0), 0);
    const undated = exported.length - dated.length;

    const { dist, max: maxRD, rated } = ratingRows(exported);
    const { rows: tagRows, max: maxTag } = topTagRows(exported);
    const recent = dated.slice().sort((a, b) => exportMs(b) - exportMs(a)).slice(0, 5);

    return `
      <div class="dash-row dash-row1">
        <div class="kpi"><div class="kpi-num">${exported.length}</div><div class="kpi-lbl">Exported</div></div>
        <div class="kpi"><div class="kpi-num">${rate}<span class="u">%</span></div><div class="kpi-lbl">of ${papers.length} papers</div></div>
        <div class="kpi"><div class="kpi-num">${median === null ? '–' : median}${median === null ? '' : '<span class="u">d</span>'}</div><div class="kpi-lbl">Median intake→export</div></div>
        <div class="dash-card c-status">
          <div class="dash-title">Recent exports</div>
          ${recent.length ? `<div class="dash-recent">${recent.map(p =>
            `<span><b>${p.exported_at}</b> ${escapeHtml((p.title_ko || p.title_en || p.slug).slice(0, 46))}</span>`).join('')}</div>`
            : '<div class="dash-empty">No exports yet</div>'}
        </div>
      </div>
      <div class="dash-row dash-row2">
        <div class="dash-card c-month">
          <div class="dash-title">Monthly exports <span class="dash-sub">${monthRangeLabel()} · ${inWindow} exports${undated ? ` · ${undated} undated` : ''}</span></div>
          ${monthChart(map, 'exp')}
        </div>
        <div class="dash-card c-rating">
          <div class="dash-title">Rating · exported</div>
          ${rated.length ? dashBars(dist, maxRD, 'gold') : '<div class="dash-empty">No ratings yet</div>'}
        </div>
        <div class="dash-card c-tags">
          <div class="dash-title">Top tags · exported</div>
          ${tagRows.length ? dashBars(tagRows, maxTag) : '<div class="dash-empty">No tags</div>'}
        </div>
      </div>`;
  }

  function renderDashboard() {
    if (!dashEl) return;
    const tab = (t, label) =>
      `<button data-dtab="${t}" class="${dashTab === t ? 'active' : ''}">${label}</button>`;
    dashEl.innerHTML = `
      <div class="dash-bar">
        <div class="dash-tabs">${tab('intake', 'Intake')}${tab('export', 'Export')}</div>
        <span class="dash-spacer"></span>
        <button class="dash-close" id="dash-close" title="Close (Esc)">✕ Close</button>
      </div>
      ${dashTab === 'export' ? dashExportHtml() : dashIntakeHtml()}`;
  }
  if (dashEl) {
    dashEl.addEventListener('click', (e) => {
      const t = e.target.closest('[data-dtab]');
      if (!t) return;
      dashTab = t.dataset.dtab;
      localStorage.setItem('pr-dash-tab', dashTab);
      renderDashboard();
    });
  }

  if (dashToggle && dashEl) {
    const setDash = (open) => {
      dashEl.hidden = !open;
      dashToggle.classList.toggle('active', open);
      localStorage.setItem('pr-dash-open', open ? '1' : '0');
      if (open) renderDashboard();
    };
    dashToggle.addEventListener('click', () => setDash(dashEl.hidden));
    dashEl.addEventListener('click', (e) => { if (e.target.closest('#dash-close')) setDash(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !dashEl.hidden) setDash(false); });
    const dashParam = new URLSearchParams(location.search).get('dash');
    if (dashParam === '1' || (dashParam === null && localStorage.getItem('pr-dash-open') === '1')) setDash(true);
  }

  // ─── Grid / List view toggle ─────────────────────────────────────
  const viewSwitch = document.getElementById('view-switch');
  function setGridView(mode) {
    grid.dataset.view = mode;
    if (viewSwitch) viewSwitch.querySelectorAll('button').forEach(b =>
      b.classList.toggle('active', b.dataset.view === mode));
    localStorage.setItem('pr-grid-view', mode);
  }
  setGridView(localStorage.getItem('pr-grid-view') || 'grid');
  if (viewSwitch) viewSwitch.querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => setGridView(b.dataset.view)));

  // ─── New paper modal (unchanged) ─────────────────────────────────
  const modal = document.getElementById('modal-new');
  const btnNew = document.getElementById('btn-new');
  const btnSubmit = document.getElementById('btn-submit');
  const arxivInput = document.getElementById('arxiv-input');
  const pdfInput = document.getElementById('pdf-input');
  const drop = document.getElementById('drop');
  const dropLabel = document.getElementById('drop-label');
  const progBox = document.getElementById('prog-box');
  const tabs = document.querySelectorAll('.modal-tab');
  let activeTab = 'arxiv';
  let busy = false;

  let newTagInput = null;
  btnNew.addEventListener('click', () => {
    newTagInput = makeTagInput(document.getElementById('new-tags-mount'), []);  // fresh, empty
    modal.setAttribute('open', '');
    setTimeout(() => arxivInput.focus(), 100);
  });
  modal.querySelectorAll('[data-close]').forEach(el => {
    el.addEventListener('click', () => { if (!busy) closeModal(); });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modal.hasAttribute('open') && !busy) closeModal();
  });

  tabs.forEach(t => {
    t.addEventListener('click', () => {
      tabs.forEach(o => o.classList.toggle('active', o === t));
      activeTab = t.dataset.tab;
      document.getElementById('tab-arxiv').style.display = activeTab === 'arxiv' ? '' : 'none';
      document.getElementById('tab-pdf').style.display = activeTab === 'pdf' ? '' : 'none';
    });
  });

  drop.addEventListener('click', () => pdfInput.click());
  ['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.add('hover');
  }));
  ['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.remove('hover');
  }));
  drop.addEventListener('drop', e => {
    const f = e.dataTransfer?.files?.[0];
    if (f) { pdfInput.files = e.dataTransfer.files; updateDropLabel(); }
  });
  pdfInput.addEventListener('change', updateDropLabel);
  function updateDropLabel() {
    const f = pdfInput.files?.[0];
    if (f) {
      dropLabel.textContent = `${f.name} (${(f.size/1024/1024).toFixed(1)}MB)`;
      drop.classList.add('has-file');
    } else {
      dropLabel.textContent = 'PDF 파일을 끌어다 놓거나 클릭해서 선택';
      drop.classList.remove('has-file');
    }
  }

  btnSubmit.addEventListener('click', submit);
  arxivInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') submit();
  });

  async function submit() {
    if (busy) return;
    const mode = document.querySelector('input[name=mode]:checked')?.value || 'analyze';
    const tags = newTagInput ? newTagInput.getTags() : [];

    if (mode === 'save') {
      busy = true;
      btnSubmit.disabled = true;
      btnSubmit.textContent = '저장 중…';
      try {
        let out;
        if (activeTab === 'arxiv') {
          const v = arxivInput.value.trim();
          if (!v) { busy = false; btnSubmit.disabled = false; btnSubmit.textContent = '저장'; return; }
          btnSubmit.textContent = '저장 + PDF 다운로드…';
          const r = await fetch('/papers/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: v, tags })
          });
          if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || 'HTTP ' + r.status);
          }
          out = await r.json();
          if (out.pdf_ok === false) {
            showProgress('⚠ 메타는 저장됐지만 PDF 다운로드 실패 (나중에 Analyze 시 재시도)', true);
          }
        } else {
          const f = pdfInput.files?.[0];
          if (!f) { busy = false; btnSubmit.disabled = false; btnSubmit.textContent = '저장'; return; }
          btnSubmit.textContent = 'PDF 업로드…';
          const fd = new FormData();
          fd.append('file', f);
          fd.append('tags', tags.join(','));
          const r = await fetch('/papers/save-pdf', { method: 'POST', body: fd });
          if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || 'HTTP ' + r.status);
          }
          out = await r.json();
        }
        progBox.style.display = 'block';
        showProgress('✓ 저장 완료. 페이지로 이동…');
        setTimeout(() => { location.href = '/paper/' + out.slug; }, 700);
      } catch (e) {
        progBox.style.display = 'block';
        showProgress('✗ ' + (e.message || e), true);
        busy = false;
        btnSubmit.disabled = false;
        btnSubmit.textContent = '저장';
      }
      return;
    }

    // mode === 'analyze' — full ingest
    let job;
    if (activeTab === 'arxiv') {
      const v = arxivInput.value.trim();
      if (!v) return;
      busy = true;
      btnSubmit.disabled = true;
      btnSubmit.textContent = '시작…';
      try {
        const r = await fetch('/papers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: v })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        job = await r.json();
      } catch (e) {
        progBox.style.display = 'block';
        showProgress('✗ ' + (e.message || e), true);
        busy = false;
        btnSubmit.disabled = false;
        btnSubmit.textContent = '등록';
        return;
      }
    } else {
      const f = pdfInput.files?.[0];
      if (!f) return;
      busy = true;
      btnSubmit.disabled = true;
      btnSubmit.textContent = '업로드…';
      try {
        const fd = new FormData();
        fd.append('file', f);
        const r = await fetch('/papers/upload', { method: 'POST', body: fd });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        job = await r.json();
      } catch (e) {
        progBox.style.display = 'block';
        showProgress('✗ ' + (e.message || e), true);
        busy = false;
        btnSubmit.disabled = false;
        btnSubmit.textContent = '등록';
        return;
      }
    }
    progBox.style.display = 'block';
    progBox.innerHTML = '';
    showProgress('ingest 시작…');
    btnSubmit.textContent = '진행 중…';
    pollJob(job.job_id, tags);
  }

  function showProgress(text, err = false) {
    const row = document.createElement('div');
    row.className = 'row' + (err ? ' err' : '');
    row.textContent = text;
    progBox.appendChild(row);
    progBox.scrollTop = progBox.scrollHeight;
  }

  async function pollJob(jobId, pendingTags = []) {
    let lastLogLen = 0;
    while (true) {
      await new Promise(r => setTimeout(r, 800));
      let job;
      try {
        const r = await fetch(`/papers/jobs/${jobId}`);
        job = await r.json();
      } catch (e) {
        showProgress('✗ poll failed', true);
        break;
      }
      const newLines = job.log_tail.slice(lastLogLen);
      newLines.forEach(line => showProgress(line));
      lastLogLen = job.log_tail.length;

      if (job.status === 'done' && job.slug) {
        if (pendingTags.length) {
          try {
            await fetch(`/paper/${job.slug}/tags`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tags: pendingTags }),
            });
          } catch {}
        }
        showProgress('✓ 완료. 페이지로 이동합니다…');
        setTimeout(() => { location.href = '/paper/' + job.slug; }, 800);
        break;
      }
      if (job.status === 'error') {
        showProgress('✗ ' + (job.error || 'unknown error'), true);
        busy = false;
        btnSubmit.disabled = false;
        btnSubmit.textContent = '재시도';
        break;
      }
    }
  }

  function closeModal() {
    modal.removeAttribute('open');
    setTimeout(() => {
      progBox.style.display = 'none';
      progBox.innerHTML = '';
      arxivInput.value = '';
      pdfInput.value = '';
      updateDropLabel();
      btnSubmit.disabled = false;
      btnSubmit.textContent = '등록';
      busy = false;
    }, 200);
  }

  // ─── Settings modal ───────────────────────────────────────────
  (function initSettings() {
    const sModal = document.getElementById('modal-settings');
    const sBtn = document.getElementById('settings-btn');
    if (!sModal || !sBtn) return;

    sBtn.addEventListener('click', () => { sModal.setAttribute('open', ''); renderThemes(); });
    sModal.querySelectorAll('[data-close]').forEach(el =>
      el.addEventListener('click', () => sModal.removeAttribute('open')));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && sModal.hasAttribute('open')) sModal.removeAttribute('open');
    });

    const stabs = sModal.querySelectorAll('.settings-tab');
    stabs.forEach(t => t.addEventListener('click', () => {
      stabs.forEach(o => o.classList.toggle('active', o === t));
      const id = t.dataset.stab;
      document.getElementById('spane-themes').hidden = id !== 'themes';
      document.getElementById('spane-skills').hidden = id !== 'skills';
      document.getElementById('spane-illust').hidden = id !== 'illust';
      document.getElementById('spane-paths').hidden = id !== 'paths';
      document.getElementById('spane-mobile').hidden = id !== 'mobile';
      if (id === 'skills') loadSkills();
      if (id === 'illust') loadIllust();
      if (id === 'paths') loadPaths();
      if (id === 'mobile') loadMobile();
    }));

    // — Paths (publish output → user's own Obsidian/velog vault) —
    async function loadPaths() {
      try {
        const s = await (await fetch('/settings')).json();
        document.getElementById('paths-drafts').value = s.drafts_dir || '';
        document.getElementById('paths-hint').textContent =
          `현재 적용 경로: ${s.effective_drafts_dir}` +
          (s.drafts_dir ? '' : ` (기본값)`);
      } catch (e) {
        document.getElementById('paths-hint').textContent = '설정을 불러오지 못했습니다: ' + e;
      }
    }
    document.getElementById('paths-save').addEventListener('click', async () => {
      try {
        const r = await fetch('/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ drafts_dir: document.getElementById('paths-drafts').value }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
        document.getElementById('paths-hint').textContent =
          `저장됨 — 적용 경로: ${j.effective_drafts_dir}`;
      } catch (e) {
        UIDialog.alert('저장 실패: ' + (e.message || e), { title: '오류' });
      }
    });

    // — Mobile remote slot (URL + token; the token never comes back to the UI) —
    // The gallery's HTML/JS are read from disk per request but the routes live in
    // the running process: after an update, a server that hasn't been restarted
    // serves THIS pane over endpoints that don't know its fields yet. The
    // missing field is the tell — say so instead of failing with a raw 422.
    const STALE_SERVER = '서버가 예전 버전으로 실행 중입니다 — 메뉴바에서 Restart 후 다시 시도하세요.';
    async function loadMobile() {
      const hint = document.getElementById('rm-hint');
      const save = document.getElementById('rm-save');
      try {
        const st = await (await fetch('/settings')).json();
        const supported = 'remote_token_set' in st;
        save.disabled = !supported;
        document.getElementById('rm-url').value = st.remote_url || '';
        document.getElementById('rm-token').value = '';
        hint.textContent = !supported ? STALE_SERVER
          : st.remote_from_env
          ? '환경변수(PAPER_REVIEW_REMOTE_URL/TOKEN)가 설정되어 있어 그것이 우선합니다.'
          : st.remote_token_set ? '토큰이 저장되어 있습니다 — 비워두면 그대로 유지됩니다.'
          : '아직 토큰이 없습니다 — URL과 함께 입력하세요.';
      } catch (e) { hint.textContent = '설정을 불러오지 못했습니다: ' + e; }
    }
    document.getElementById('rm-save').addEventListener('click', async () => {
      const url = document.getElementById('rm-url').value.trim();
      const tokenEl = document.getElementById('rm-token');
      const body = { remote_url: url };
      if (tokenEl.value.trim()) body.remote_token = tokenEl.value.trim();
      if (!url && !await UIDialog.confirm('원격 슬롯 연결을 해제할까요? (저장된 토큰도 삭제됩니다)',
        { okLabel: '해제', cancelLabel: '취소', danger: true })) return;
      try {
        const r = await fetch('/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const j = await r.json().catch(() => ({}));
        // 422 = the running server's route doesn't accept these fields yet
        if (r.status === 422) throw new Error(STALE_SERVER);
        if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
        tokenEl.value = '';
        document.getElementById('rm-hint').textContent =
          url ? '저장됨 — 카드의 📱 버튼으로 페이퍼를 보낼 수 있습니다.' : '연결이 해제되었습니다.';
      } catch (e) {
        UIDialog.alert('저장 실패: ' + (e.message || e), { title: '오류' });
      }
    });

    // — Themes —
    const THEMES = [
      { id: 'auto', name: '시스템', sub: 'OS 설정', sw: ['#ffffff', '#0066cc', '#010102'] },
      { id: 'light', name: 'Light', sub: 'Apple', sw: ['#ffffff', '#f5f5f7', '#0066cc'] },
      { id: 'dark', name: 'Dark', sub: 'Linear', sw: ['#010102', '#141516', '#5e6ad2'] },
      { id: 'stripe', name: 'Stripe', sub: 'getdesign.md', sw: ['#ffffff', '#f6f8fb', '#635bff'] },
      { id: 'figma', name: 'Figma', sub: 'getdesign.md', sw: ['#ffffff', '#f8f8f8', '#18a0fb'] },
      { id: 'tesla', name: 'Tesla', sub: 'getdesign.md', sw: ['#000000', '#171717', '#e82127'] },
      { id: 'sunset', name: 'Sunset', sub: 'original', sw: ['#1a1412', '#2b211d', '#ff7a59'] },
      { id: 'sage', name: 'Sage', sub: 'original', sw: ['#f6f8f4', '#eef2ea', '#2f7d4f'] },
    ];
    function renderThemes() {
      const grid = document.getElementById('theme-grid');
      const cur = localStorage.getItem('pr-theme') || 'auto';
      grid.innerHTML = THEMES.map(t => `
        <div class="theme-card${t.id === cur ? ' active' : ''}" data-theme="${t.id}">
          <div class="theme-swatch">${t.sw.map(c => `<span style="background:${c}"></span>`).join('')}</div>
          <div class="theme-name">${t.name}</div>
          <div class="theme-sub">${t.sub}</div>
        </div>`).join('');
      grid.querySelectorAll('.theme-card').forEach(c => c.addEventListener('click', () => {
        const id = c.dataset.theme;
        localStorage.setItem('pr-theme', id);
        applyTheme(id);
      }));
    }

    // — Skills —
    async function loadSkills() {
      const list = document.getElementById('skills-list');
      list.innerHTML = '<li>불러오는 중…</li>';
      let skills;
      try { skills = await fetch('/skills').then(r => r.json()); }
      catch (e) { list.innerHTML = '<li>로드 실패</li>'; return; }
      list.innerHTML = skills.map(s =>
        `<li data-skill="${escapeHtml(s.name)}"><span class="sk-name">${escapeHtml(s.name)}</span>` +
        `<span class="sk-desc">${escapeHtml(s.description || '')}</span></li>`).join('');
      list.querySelectorAll('li[data-skill]').forEach(li =>
        li.addEventListener('click', () => openSkill(li.dataset.skill, list)));
    }
    async function openSkill(name, list) {
      list.querySelectorAll('li').forEach(o => o.classList.toggle('active', o.dataset.skill === name));
      const body = document.getElementById('skill-editor-body');
      const ta = document.getElementById('skill-text');
      document.getElementById('skill-editor-empty').hidden = true;
      body.hidden = false;
      document.getElementById('skill-editor-name').textContent = name;
      ta.value = '불러오는 중…';
      ta.value = await fetch(`/skills/${encodeURIComponent(name)}`).then(r => r.text());
      const save = document.getElementById('skill-save');
      save.onclick = async () => {
        save.textContent = '저장 중…'; save.disabled = true;
        try {
          const r = await fetch(`/skills/${encodeURIComponent(name)}`, {
            method: 'PUT', headers: { 'Content-Type': 'text/plain' }, body: ta.value,
          });
          if (!r.ok) throw new Error('HTTP ' + r.status);
          save.textContent = '저장됨 ✓';
        } catch (e) { save.textContent = '실패'; }
        setTimeout(() => { save.textContent = '저장'; save.disabled = false; }, 1300);
      };
    }

    // — Illustrations —
    async function loadIllust() {
      const grid = document.getElementById('illust-grid');
      grid.innerHTML = '불러오는 중…';
      let items;
      try { items = await fetch('/illustrations').then(r => r.json()); }
      catch (e) { grid.innerHTML = '로드 실패'; return; }
      grid.innerHTML = items.map(f => `
        <div class="illust-item">
          <button class="illust-del" data-del="${encodeURIComponent(f)}" title="_trash로 이동">×</button>
          <img src="/static/characters/${encodeURIComponent(f)}" alt="" loading="lazy">
          <div class="illust-name">${escapeHtml(f)}</div>
        </div>`).join('') || '<div class="hint">일러스트가 없습니다.</div>';
      grid.querySelectorAll('.illust-del').forEach(b => b.addEventListener('click', async () => {
        const f = decodeURIComponent(b.dataset.del);
        if (!confirm(`${f} 을(를) _trash로 이동할까요? (복구 가능)`)) return;
        const r = await fetch(`/illustrations/${encodeURIComponent(f)}`, { method: 'DELETE' });
        if (r.ok) { await refreshCharacters(); loadIllust(); } else alert('삭제 실패');
      }));
      const fileInput = document.getElementById('illust-file');
      const upBtn = document.getElementById('illust-upload-btn');
      upBtn.onclick = () => fileInput.click();
      fileInput.onchange = async () => {
        const files = [...fileInput.files];
        if (!files.length) return;
        const nameInput = document.getElementById('illust-name');
        const baseName = (nameInput && nameInput.value.trim()) || '';
        upBtn.textContent = '업로드 중…';
        for (const f of files) {
          const fd = new FormData();
          fd.append('file', f);
          if (baseName) fd.append('name', baseName);
          await fetch('/illustrations', { method: 'POST', body: fd });
        }
        fileInput.value = '';
        if (nameInput) nameInput.value = '';
        upBtn.textContent = '+ 이미지 추가';
        await refreshCharacters(); loadIllust();
      };
    }
  })();

  // Refresh the card-illustration pool + groups from the server, re-render cards.
  async function refreshCharacters() {
    try {
      const items = await fetch('/illustrations').then(r => r.json());
      if (Array.isArray(items) && items.length) CHARACTERS = items;
    } catch (e) { /* keep fallback list */ }
    try {
      const g = await fetch('/illustration-groups').then(r => r.json());
      ILLUST_GROUPS = g.groups || {};
      TAG_GROUPS = g.tag_groups || {};
    } catch (e) { /* no grouping → global hash fallback */ }
    renderCards();
  }
  refreshCharacters();
})();
