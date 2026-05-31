
(() => {
  // ─── Render gallery from JSON
  const papers = JSON.parse(document.getElementById('papers-data').textContent);
  const grid = document.getElementById('grid');
  let activeFilter = 'all';
  let searchQuery = '';
  let activeTags = new Set();
  let collapsedTags = new Set();

  function statusCounts() {
    const c = { all: papers.length, to_read: 0, in_progress: 0, review_done: 0, exported: 0 };
    for (const p of papers) {
      if (c.hasOwnProperty(p.status)) c[p.status]++;
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
            <button class="nav-item${active}" data-tag="${escapeHtml(info.path)}" data-depth="${depth}">
              <span class="tag-twisty ${hasChildren ? (isCollapsed ? 'collapsed' : '') : 'leaf'}" data-twisty="${escapeHtml(info.path)}">▾</span>
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
  const CHARACTERS = ["fennec", "penguin", "dolphin", "badger", "redpanda", "corgi", "calcifer"];
  function hashChar(s) {
    // djb2 — better spread than a per-step modulo (slugs are mostly digits)
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return Math.abs(h) % CHARACTERS.length;
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
  function renderCards() {
    const filtered = papers.filter(p => {
      if (activeFilter !== 'all' && p.status !== activeFilter) return false;
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
      const ci = hashChar((p.title_en || p.title_ko || p.slug) + p.slug);
      const charName = CHARACTERS[ci];
      const total = Math.max(p.sections_total || 0, 1);
      const done = p.sections_done || 0;
      const segs = Math.min(total, 14);
      const doneSegs = Math.round((done / total) * segs);
      const bars = Array.from({length: segs}, (_, i) =>
        `<span class="seg${i < doneSegs ? ' done' : ''}"></span>`).join('');
      const isActive = activeJobs.has(p.slug);
      const activeMeta = activeJobs.get(p.slug);
      const tags = p.tags || [];
      const tagsHTML = tags.length
        ? `<div class="card-tags">${tags.slice(0, 3).map(t => `<span class="t">${escapeHtml(t)}</span>`).join('')}${tags.length > 3 ? `<span class="t more">+${tags.length - 3}</span>` : ''}</div>`
        : '';
      const isToRead = p.status === 'to_read';
      return `
        <a class="card" href="/paper/${p.slug}" data-slug="${p.slug}">
          <div class="card-thumb char-bg-${ci}">
            <img class="card-illust" src="/static/characters/${charName}.png" alt="" loading="lazy">
            <span class="badge s-${p.status}">${p.status === 'to_read' ? 'reading' : p.status}</span>
            <button class="card-tagedit" data-tagedit="${escapeHtml(p.slug)}" title="태그 편집">🏷</button>
            <button class="card-del" data-del="${escapeHtml(p.slug)}" title="삭제">🗑</button>
            ${isActive ? `<span class="pulse">분석 중 ${activeMeta.current}/${activeMeta.total}</span>` : ''}
          </div>
          <div class="card-body">
            <div class="card-title">${escapeHtml(title)}</div>
            ${subTitle ? `<div class="card-sub">${escapeHtml(subTitle)}</div>` : ''}
            ${total > 0 ? `<div class="progress">${bars}</div>` : ''}
            <div class="card-foot">
              ${isToRead ? '<span class="frac">reading list</span>' : `<span class="frac">${done}/${total} sections</span>`}
              ${p.category ? `<span class="sep">·</span><span class="cat">${escapeHtml(p.category)}</span>` : ''}
              ${p.figures_count > 0 ? `<span class="sep">·</span><span>${p.figures_count} figs</span>` : ''}
            </div>
            ${tagsHTML}
          </div>
        </a>`;
    }).join('');
  }
  // Tag edit (event-delegated)
  grid.addEventListener('click', async (e) => {
    const tbtn = e.target.closest('.card-tagedit');
    if (!tbtn) return;
    e.preventDefault();
    e.stopPropagation();
    const slug = tbtn.dataset.tagedit;
    const paper = papers.find(p => p.slug === slug);
    const cur = (paper?.tags || []).join(', ');
    const next = prompt('태그 (쉼표 구분, 계층은 "CV/segmentation" 처럼):', cur);
    if (next === null) return;
    const tags = next.split(',').map(t => t.trim()).filter(Boolean);
    try {
      const r = await fetch(`/paper/${encodeURIComponent(slug)}/tags`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      if (paper) paper.tags = tags;
      renderTagTree();
      renderCards();
      updateClearTags();
    } catch (err) {
      alert('태그 저장 실패: ' + (err.message || err));
    }
  });

  // Delete (event-delegated so it survives re-renders)
  grid.addEventListener('click', async (e) => {
    const btn = e.target.closest('.card-del');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const slug = btn.dataset.del;
    if (!confirm(`"${slug}" 를 삭제할까요?\n원본 PDF·워크벤치·분석 결과가 모두 사라집니다 (되돌릴 수 없음).`)) return;
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
      alert('삭제 실패: ' + (err.message || err));
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
      // Only re-render if set changed
      const same = next.size === activeJobs.size &&
        [...next.keys()].every(k => activeJobs.has(k) &&
          activeJobs.get(k).current === next.get(k).current);
      activeJobs = next;
      if (!same) renderCards();
    } catch {}
  }
  pollActiveJobs();
  setInterval(pollActiveJobs, 3000);

  // ─── Theme toggle
  function applyTheme(t) {
    if (t === 'dark' || t === 'light') document.body.dataset.theme = t;
    else delete document.body.dataset.theme;
    const tb = document.getElementById('theme-toggle');
    const isDark = t === 'dark' || (t === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
    if (tb) tb.textContent = isDark ? '☾' : '☼';
  }
  const savedTheme = localStorage.getItem('pr-theme') || 'auto';
  applyTheme(savedTheme);
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

  btnNew.addEventListener('click', () => {
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
    const tagsInput = document.getElementById('new-tags');
    const tags = (tagsInput?.value || '').split(',').map(t => t.trim()).filter(Boolean);

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
})();
