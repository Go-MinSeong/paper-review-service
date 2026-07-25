"""Launch screen for the desktop app (macOS .app / `paper-review app`).

Self-contained HTML — no CDN, no asset files — because it must render instantly
on a cold start, before the local server exists. `boot_steps` names the phases
the window reports while starting up; `fail_js` swaps the spinner for an error.
"""

from __future__ import annotations

SPLASH_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<style>
  :root {
    --bg: #ffffff; --fg: #1d1d1f; --muted: #7a7a7a; --accent: #0066cc;
    --border: #e6e6e8;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0c0d0e; --fg: #f7f8f8; --muted: #8a8f98; --accent: #6f7bff;
            --border: #23252a; }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 22px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Pretendard Variable", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased; user-select: none; cursor: default;
  }
  .mark { color: var(--accent); animation: rise .5s cubic-bezier(.2,.8,.2,1) both; }
  .brand {
    font-size: 21px; font-weight: 650; letter-spacing: -.4px;
    animation: rise .5s cubic-bezier(.2,.8,.2,1) .06s both;
  }
  .tag {
    font-size: 12.5px; color: var(--muted); margin-top: -14px;
    animation: rise .5s cubic-bezier(.2,.8,.2,1) .12s both;
  }
  .track {
    width: 210px; height: 3px; border-radius: 999px; overflow: hidden;
    background: var(--border); animation: rise .5s cubic-bezier(.2,.8,.2,1) .18s both;
  }
  .track i {
    display: block; height: 100%; width: 40%; border-radius: 999px;
    background: var(--accent); animation: slide 1.15s ease-in-out infinite;
  }
  .status {
    font-size: 12px; color: var(--muted); min-height: 16px;
    font-variant-numeric: tabular-nums;
  }
  .err { color: #d1453b; font-size: 12.5px; max-width: 360px; text-align: center;
         line-height: 1.6; white-space: pre-line; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  @keyframes slide {
    0% { transform: translateX(-105%); } 50% { transform: translateX(115%); }
    100% { transform: translateX(-105%); }
  }
  body.failed .track { display: none; }
</style></head>
<body>
  <span class="mark" aria-hidden="true">
    <svg viewBox="0 0 24 24" width="54" height="54">
      <rect x="3" y="2.5" width="18" height="19" rx="5.5" fill="currentColor" opacity=".14"/>
      <rect x="3.75" y="3.25" width="16.5" height="17.5" rx="4.75" fill="none"
            stroke="currentColor" stroke-width="1.3" opacity=".55"/>
      <path d="M7.75 8.5h8.5M7.75 12h8.5M7.75 15.5h5" stroke="currentColor"
            stroke-width="1.7" stroke-linecap="round" fill="none"/>
    </svg>
  </span>
  <div class="brand">paper-review</div>
  <div class="tag">Read papers with Claude</div>
  <div class="track"><i></i></div>
  <div class="status" id="s">starting…</div>
<script>
  window.prStatus = (t) => { document.getElementById('s').textContent = t; };
  window.prFail = (msg) => {
    document.body.classList.add('failed');
    const s = document.getElementById('s');
    s.className = 'err';
    s.textContent = msg;
  };
</script>
</body></html>
"""

# Phases reported on the splash while the app boots.
STEP_SKILLS = "installing skills…"
STEP_SERVER = "starting local server…"
STEP_READY = "opening library…"


def status_js(text: str) -> str:
    """JS that updates the splash status line (safe for quotes/newlines)."""
    import json

    return f"window.prStatus && window.prStatus({json.dumps(text)})"


def fail_js(message: str) -> str:
    """JS that turns the splash into an error state."""
    import json

    return f"window.prFail && window.prFail({json.dumps(message)})"
