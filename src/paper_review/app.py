"""Desktop-app entry point.

Runs the FastAPI server in a background thread and shows it in a native
pywebview window — this is what the packaged .app launches. Also reachable in
dev via `paper-review app`.

The frozen .app binary uses `desktop_main`: no args → open the window; any args
→ delegate to the CLI (so `runner._self_cmd` / ingest can re-exec the same
binary for `serve` / `init` / `_run-script`).
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

WINDOW_TITLE = "paper-review"


def _bundle_dir() -> Path:
    """Root holding bundled data (skills/, etc.) — _MEIPASS when frozen, else repo."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _install_skills() -> None:
    """First-run: copy bundled skills into ~/.claude/skills (skip existing, so a
    dev symlink or the user's edits are never clobbered)."""
    src = _bundle_dir() / "skills"
    if not src.is_dir():
        return
    dest = Path.home() / ".claude" / "skills"
    dest.mkdir(parents=True, exist_ok=True)
    for d in src.iterdir():
        if d.is_dir() and (d / "SKILL.md").is_file() and not (dest / d.name).exists():
            try:
                shutil.copytree(d, dest / d.name)
            except Exception:
                pass


def _augment_path() -> None:
    """A .app launched from Finder gets a minimal PATH that usually omits where
    `claude` lives. Prepend the common install dirs so the headless `claude -p`
    calls (review/chat/analyze) resolve."""
    extra = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".claude" / "local"),
        str(Path.home() / ".npm-global" / "bin"),
    ]
    cur = os.environ.get("PATH", "")
    have = set(cur.split(":"))
    add = [p for p in extra if p and p not in have]
    if add:
        os.environ["PATH"] = ":".join(add + ([cur] if cur else []))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_server(port: int, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_server(port: int) -> threading.Thread:
    """Start uvicorn(app) on 127.0.0.1:port in a daemon thread."""

    def _serve() -> None:
        import uvicorn

        # Pass the app object (not an import string) — the string form can't be
        # re-imported inside a frozen bundle.
        from .server.app import app as fastapi_app

        uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning")

    t = threading.Thread(target=_serve, name="pr-server", daemon=True)
    t.start()
    return t


def _appearance_bg() -> str:
    """Window background before the splash paints — matching the system
    appearance avoids a white flash for dark-mode users."""
    if sys.platform == "darwin":
        try:
            import subprocess

            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if "dark" in out.stdout.strip().lower():
                return "#0C0D0E"  # keep in sync with splash.py --bg (dark)
        except Exception:
            pass
    return "#FFFFFF"


def _unify_titlebar(window) -> None:
    """Let the page run under the title bar, like the sibling apps do.

    pywebview paints its own grey title bar, which reads as a browser chrome bar
    stuck above the UI. Making it transparent + full-size-content puts the app's
    own header at the very top; the traffic lights stay where macOS wants them
    (the pages offset their top strip for the app — see `body.in-app`).
    """
    try:
        import AppKit

        ns = getattr(window, "native", None)
        if ns is None:
            return

        def _apply() -> None:
            try:
                ns.setTitlebarAppearsTransparent_(True)
                ns.setTitleVisibility_(1)  # NSWindowTitleHidden
                ns.setStyleMask_(ns.styleMask() | (1 << 15))  # FullSizeContentView
                # undo the window-background colour pywebview paints on the bar
                bar = ns.contentView().superview().subviews().lastObject()
                bar.setBackgroundColor_(AppKit.NSColor.clearColor())
                # With no title bar left to grab, the window still has to be
                # draggable — background drag covers the empty header areas.
                ns.setMovableByWindowBackground_(True)
            except Exception:
                pass
            ns.displayIfNeeded()

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_apply)
    except Exception:
        pass


def _boot(window, port: int) -> None:
    """Runs after the splash is on screen: prepare, start the server, then swap
    the window over to the gallery. Failures stay visible on the splash instead
    of leaving a blank window behind."""
    from . import splash

    def say(text: str) -> None:
        try:
            window.evaluate_js(splash.status_js(text))
        except Exception:
            pass

    try:
        say(splash.STEP_SKILLS)
        _install_skills()
        # Best-effort first-run install of the named subagents into ~/.claude/agents.
        try:
            from ._paper_reader import runner

            runner.install_subagents()
        except Exception:
            pass

        say(splash.STEP_SERVER)
        start_server(port)
        if not _wait_server(port):
            window.evaluate_js(
                splash.fail_js(
                    "로컬 서버를 시작하지 못했습니다.\n"
                    "메뉴바 앱이 같은 포트를 쓰고 있는지 확인하거나, 앱을 다시 실행해 주세요."
                )
            )
            return
        say(splash.STEP_READY)
        window.load_url(f"http://127.0.0.1:{port}/")
        # Menubar presence too — the Dock icon disappears behind other windows,
        # and the status item is how you get back without hunting for it.
        try:
            from . import statusitem

            statusitem.install(port, window)
        except Exception:
            pass
        _unify_titlebar(window)
    except Exception as e:  # never leave the splash spinning forever
        try:
            window.evaluate_js(splash.fail_js(f"시작 중 오류가 발생했습니다.\n{e}"))
        except Exception:
            print(f"paper-review: startup failed: {e}", file=sys.stderr)


def run_app(port: int | None = None) -> None:
    _augment_path()
    port = port or _free_port()

    import webview

    from . import splash

    # Show the launch screen FIRST — on a cold start (bundle unpack + uvicorn
    # boot) the window used to sit blank for several seconds.
    window = webview.create_window(
        WINDOW_TITLE,
        html=splash.SPLASH_HTML,
        width=1280,
        height=860,
        background_color=_appearance_bg(),
    )
    webview.start(_boot, (window, port))


def desktop_main() -> None:
    """Frozen .app entry: window when double-clicked, CLI when given args."""
    if len(sys.argv) > 1:
        from .cli import main

        main()
    else:
        run_app()
