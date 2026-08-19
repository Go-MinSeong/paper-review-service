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


# Height of the strip reserved for the traffic lights (mirrors --titlebar-h).
TITLEBAR_H = 28.0


def _install_drag_view(ns) -> int:
    """Make the reserved top strip drag the window — natively.

    pywebview offers a JS drag region (.pywebview-drag-region), but it moves the
    window by computing screen coordinates in JavaScript, which drifts across
    displays with different scale factors — dragging between monitors fights
    you. A native view whose mouseDownCanMoveWindow is YES hands the drag to
    AppKit instead, so it behaves like any other window.
    """
    import AppKit

    cls = globals().get("_PRDragView")
    if cls is None:

        class _PRDragView(AppKit.NSView):
            # performWindowDragWithEvent: is the documented way to move a window
            # from a view (10.11+). mouseDownCanMoveWindow alone was ignored
            # here, and AppKit does the whole drag — including across displays
            # with different scale factors, which a JS drag region gets wrong.
            def mouseDown_(self, event):  # noqa: N802 (AppKit selector)
                if event.clickCount() == 2:
                    # Taking over the title bar area also took over its
                    # double-click, which zooms (or minimises, per System
                    # Settings › Desktop & Dock). Put that back.
                    self._doubleClickAction()
                    return
                self.window().performWindowDragWithEvent_(event)

            def _doubleClickAction(self):  # noqa: N802
                pref = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_(
                    "AppleActionOnDoubleClick"
                )
                win = self.window()
                if pref == "Minimize":
                    win.miniaturize_(None)
                elif pref != "None":  # "Maximize" and the unset default
                    win.zoom_(None)

            def mouseDownCanMoveWindow(self) -> bool:  # noqa: N802
                return True

        cls = globals()["_PRDragView"] = _PRDragView

    # pywebview makes the WKWebView the contentView itself, so a subview of the
    # content view lands INSIDE the web view and never sees a click. The strip
    # goes on the window frame instead — below the titlebar container, so the
    # traffic lights keep working, but above the web view.
    frame = ns.contentView().superview()
    titlebar = frame.subviews().lastObject()
    b = frame.bounds()
    view = cls.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, b.size.height - TITLEBAR_H, b.size.width, TITLEBAR_H)
    )
    view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
    frame.addSubview_positioned_relativeTo_(view, AppKit.NSWindowBelow, titlebar)
    return frame.subviews().count()


def _enable_web_features(ns) -> str:
    """Turn on the WebKit features the UI actually uses.

    WKWebView ships element fullscreen OFF, so requestFullscreen() rejects —
    which is how the pane ⛶ buttons and the topbar ⛶ silently stopped working in
    the app while still working in a browser. pywebview makes the WKWebView the
    window's contentView, so its preferences are reachable from there. The
    preference has no public setter; KVC is the supported route."""
    import AppKit  # noqa: F401  (imported for symmetry with callers)

    web = ns.contentView()
    prefs = web.configuration().preferences()
    enabled = []
    for key in ("elementFullscreenEnabled", "fullScreenEnabled"):
        try:
            prefs.setValue_forKey_(True, key)
            enabled.append(key)
        except Exception:
            pass  # the key name differs across WebKit versions; one of them lands
    return ",".join(enabled) or "none"


# Latest pending pinch, shared between the AppKit monitor and its pump thread.
_PINCH: dict = {}


def _install_pinch_zoom(window, ns) -> bool:
    """Forward trackpad pinch to the page.

    The source PDF is an <iframe> drawn by WebKit's built-in PDF plugin, and the
    plugin swallows the gesture: `wheel`/`gesturechange` listeners in the parent
    document never fire while the cursor is over it, so pinch-to-zoom did
    nothing over exactly the pane it was written for. A window-level NSEvent
    monitor sees the gesture wherever the cursor is; the page decides whether
    that point is over the PDF.

    evaluate_js blocks waiting on the main thread and the monitor runs ON the
    main thread, so calling it from the handler deadlocks. A pump thread makes
    the call and only ever sends the newest pending delta, which coalesces the
    ~60Hz gesture stream for free.
    """
    import AppKit

    st = _PINCH
    st.update(mag=0.0, x=0.0, y=0.0, wake=threading.Event())

    def _pump() -> None:
        while True:
            st["wake"].wait()
            st["wake"].clear()
            mag, x, y = st["mag"], st["x"], st["y"]
            st["mag"] = 0.0
            if not mag:
                continue
            try:
                window.evaluate_js(
                    f"window.__prPinch&&window.__prPinch({x:.1f},{y:.1f},{mag:.4f})"
                )
            except Exception:
                pass
            time.sleep(0.03)

    def _handler(event):
        view = ns.contentView()
        p = view.convertPoint_fromView_(event.locationInWindow(), None)
        st["x"] = p.x
        st["y"] = view.bounds().size.height - p.y  # AppKit counts up, CSS down
        st["mag"] += event.magnification()
        st["wake"].set()
        return event

    st["monitor"] = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        AppKit.NSEventMaskMagnify, _handler
    )
    threading.Thread(target=_pump, name="pr-pinch", daemon=True).start()
    return st["monitor"] is not None


def _install_edit_menu() -> bool:
    """Give the app an Edit menu, because without one ⌘C does nothing.

    AppKit delivers cut:/copy:/paste:/selectAll: through a menu item's key
    equivalent, and pywebview builds only the application and View menus. So
    text everywhere in the app could be selected but never copied — most
    painfully the ingest and analyze logs, which is where a copy matters most.
    The items target nil, so they travel the responder chain to the web view.
    """
    import AppKit

    main = AppKit.NSApp.mainMenu()
    if main is None:
        return False
    for i in range(main.numberOfItems()):
        if main.itemAtIndex_(i).title() == "Edit":
            return True
    menu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in (
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        (None, None, None),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ):
        if title is None:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
    item = AppKit.NSMenuItem.alloc().init()
    item.setTitle_("Edit")
    item.setSubmenu_(menu)
    main.insertItem_atIndex_(item, 1)
    return True


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

        def _log(msg: str) -> None:
            try:
                from . import SERVICE_ROOT

                d = SERVICE_ROOT / "_logs"
                d.mkdir(parents=True, exist_ok=True)
                with open(d / "app.log", "a") as fh:
                    fh.write(f"titlebar: {msg}\n")
            except Exception:
                pass

        def _apply() -> None:
            try:
                ns.setTitlebarAppearsTransparent_(True)
                ns.setTitleVisibility_(1)  # NSWindowTitleHidden
                ns.setStyleMask_(ns.styleMask() | (1 << 15))  # FullSizeContentView
                # undo the window-background colour pywebview paints on the bar
                bar = ns.contentView().superview().subviews().lastObject()
                bar.setBackgroundColor_(AppKit.NSColor.clearColor())
                # With no title bar left to grab, the window still has to be
                # draggable. Background drag alone doesn't reach through the
                # web view, so a native drag strip goes on top of it.
                ns.setMovableByWindowBackground_(True)
                n = _install_drag_view(ns)
                feats = _enable_web_features(ns)
                pinch = _install_pinch_zoom(window, ns)
                edit = _install_edit_menu()
                _log(
                    f"applied · drag view subviews={n} · web features: {feats}"
                    f" · pinch monitor: {pinch} · edit menu: {edit}"
                )
            except Exception as e:
                _log(f"failed: {e!r}")
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
        # pywebview defaults zoomable=False and then injects a handler that
        # preventDefaults ctrl+wheel — which is exactly what a trackpad pinch
        # sends. That killed pinch-to-zoom on the source PDF, a gesture the
        # same document supports fine in a browser.
        zoomable=True,
    )
    webview.start(_boot, (window, port))


def desktop_main() -> None:
    """Frozen .app entry: window when double-clicked, CLI when given args."""
    if len(sys.argv) > 1:
        from .cli import main

        main()
    else:
        run_app()
