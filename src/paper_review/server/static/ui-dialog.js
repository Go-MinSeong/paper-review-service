/* Shared, app-styled dialogs replacing the native confirm()/prompt()/alert().
 * Exposes window.UIDialog = { confirm, prompt, alert }. All return Promises.
 * Self-contained: injects its own CSS (using the app's CSS variables, so it
 * follows light/dark automatically) and DOM on first use. */
(() => {
  if (window.UIDialog) return;

  const CSS = `
  .uidlg-backdrop {
    position: fixed; inset: 0; z-index: 9000;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0,0,0,.42); backdrop-filter: blur(3px);
    opacity: 0; transition: opacity .14s ease;
  }
  .uidlg-backdrop.show { opacity: 1; }
  .uidlg {
    width: min(440px, calc(100vw - 40px));
    background: var(--bg-elevated, #fff);
    color: var(--text-primary, #1d1d1f);
    border: 1px solid var(--border-default, #e0e0e0);
    border-radius: 16px;
    box-shadow: 0 24px 60px -12px rgba(0,0,0,.45), 0 8px 20px -8px rgba(0,0,0,.3);
    padding: 22px 22px 18px;
    transform: translateY(8px) scale(.98); opacity: 0;
    transition: transform .16s cubic-bezier(.34,1.3,.64,1), opacity .16s ease;
    font-family: var(--font-text, -apple-system, system-ui, sans-serif);
  }
  .uidlg-backdrop.show .uidlg { transform: none; opacity: 1; }
  .uidlg-title { font-size: 15px; font-weight: 700; color: var(--text-primary, #1d1d1f);
                 margin: 0 0 6px; letter-spacing: -.01em; }
  .uidlg-msg { font-size: 13px; line-height: 1.6; color: var(--text-secondary, #444);
               white-space: pre-wrap; margin: 0; }
  .uidlg-input {
    width: 100%; margin-top: 14px; box-sizing: border-box;
    font: inherit; font-size: 13.5px; padding: 9px 12px;
    border-radius: 9px; border: 1px solid var(--border-default, #ddd);
    background: var(--bg-surface, #f7f7f8); color: var(--text-primary, #1d1d1f);
    outline: none; transition: border-color .12s, box-shadow .12s;
  }
  .uidlg-input:focus { border-color: var(--accent, #0066cc);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent, #0066cc) 22%, transparent); }
  .uidlg-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
  .uidlg-btn {
    font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
    padding: 8px 16px; border-radius: 9px; border: 1px solid transparent;
    transition: background .12s, border-color .12s, color .12s, transform .08s;
  }
  .uidlg-btn:active { transform: scale(.97); }
  .uidlg-btn.cancel { background: var(--bg-surface, #f0f0f0); color: var(--text-secondary, #444);
                      border-color: var(--border-default, #ddd); }
  .uidlg-btn.cancel:hover { background: var(--bg-hover, #e8e8e8); color: var(--text-primary, #111); }
  .uidlg-btn.ok { background: var(--accent, #0066cc); color: #fff; }
  .uidlg-btn.ok:hover { background: var(--accent-hover, #0071e3); }
  .uidlg-btn.danger { background: #e5484d; color: #fff; }
  .uidlg-btn.danger:hover { background: #d63a3f; }
  `;

  function ensureStyle() {
    if (document.getElementById('uidlg-style')) return;
    const s = document.createElement('style');
    s.id = 'uidlg-style';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function open({ kind, title, message, value, placeholder, okLabel, cancelLabel, danger }) {
    ensureStyle();
    return new Promise((resolve) => {
      const backdrop = document.createElement('div');
      backdrop.className = 'uidlg-backdrop';
      const isPrompt = kind === 'prompt';
      const isAlert = kind === 'alert';
      backdrop.innerHTML = `
        <div class="uidlg" role="dialog" aria-modal="true">
          ${title ? `<h2 class="uidlg-title"></h2>` : ''}
          <p class="uidlg-msg"></p>
          ${isPrompt ? `<input class="uidlg-input" type="text">` : ''}
          <div class="uidlg-actions">
            ${isAlert ? '' : `<button class="uidlg-btn cancel"></button>`}
            <button class="uidlg-btn ${danger ? 'danger' : 'ok'}"></button>
          </div>
        </div>`;
      // Fill text via textContent (no HTML injection)
      if (title) backdrop.querySelector('.uidlg-title').textContent = title;
      backdrop.querySelector('.uidlg-msg').textContent = message || '';
      const okBtn = backdrop.querySelector('.uidlg-btn.ok, .uidlg-btn.danger');
      okBtn.textContent = okLabel || (isAlert ? '확인' : isPrompt ? '저장' : '확인');
      const cancelBtn = backdrop.querySelector('.uidlg-btn.cancel');
      if (cancelBtn) cancelBtn.textContent = cancelLabel || '취소';
      const input = backdrop.querySelector('.uidlg-input');
      if (input && value != null) input.value = value;
      if (input && placeholder) input.placeholder = placeholder;

      document.body.appendChild(backdrop);
      requestAnimationFrame(() => backdrop.classList.add('show'));

      let done = false;
      const close = (result) => {
        if (done) return; done = true;
        document.removeEventListener('keydown', onKey, true);
        backdrop.classList.remove('show');
        setTimeout(() => backdrop.remove(), 150);
        resolve(result);
      };
      const confirmResult = () =>
        isPrompt ? (input ? input.value : '') : true;
      const cancelResult = () => (isPrompt ? null : false);

      okBtn.addEventListener('click', () => close(confirmResult()));
      if (cancelBtn) cancelBtn.addEventListener('click', () => close(cancelResult()));
      backdrop.addEventListener('mousedown', (e) => {
        if (e.target === backdrop) close(cancelResult());
      });
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); close(cancelResult()); }
        else if (e.key === 'Enter' && (!isPrompt || document.activeElement === input)) {
          e.preventDefault(); close(confirmResult());
        }
      }
      document.addEventListener('keydown', onKey, true);

      setTimeout(() => (input || okBtn).focus(), 60);
      if (input) input.select();
    });
  }

  window.UIDialog = {
    confirm: (message, opts = {}) =>
      open({ kind: 'confirm', message, title: opts.title || '확인',
             okLabel: opts.okLabel, cancelLabel: opts.cancelLabel, danger: opts.danger }),
    prompt: (message, opts = {}) =>
      open({ kind: 'prompt', message, title: opts.title || '',
             value: opts.value, placeholder: opts.placeholder,
             okLabel: opts.okLabel, cancelLabel: opts.cancelLabel }),
    alert: (message, opts = {}) =>
      open({ kind: 'alert', message, title: opts.title || '알림', okLabel: opts.okLabel }),
  };
})();
