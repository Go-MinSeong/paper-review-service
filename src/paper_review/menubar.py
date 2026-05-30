"""macOS menubar app for paper-review.

Run with: paper-review menubar

The app sits in the menubar and manages the FastAPI server as a subprocess.
Click the menubar icon to open the gallery, restart, or quit.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

try:
    import rumps
except ImportError:
    rumps = None  # type: ignore

from . import DEFAULT_PORT, SERVICE_ROOT

_LOG_DIR = SERVICE_ROOT / "_logs"


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _wait_port(port: int, timeout: float = 6.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _port_in_use(port):
            return True
        time.sleep(0.15)
    return False


def _resolve_cli() -> str:
    """Find paper-review CLI — prefer the venv next to this module."""
    venv_bin = SERVICE_ROOT / ".venv" / "bin" / "paper-review"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("paper-review")
    if found:
        return found
    return "paper-review"


class PaperReviewMenubarApp:
    def __init__(self, port: int = DEFAULT_PORT, auto_open: bool = False):
        if rumps is None:
            print("rumps not available — menubar mode requires macOS + rumps.",
                  file=sys.stderr)
            sys.exit(1)

        self.port = port
        self.auto_open = auto_open
        self.proc: subprocess.Popen | None = None
        self.log_path: Path | None = None

        _LOG_DIR.mkdir(parents=True, exist_ok=True)

        icon_path = SERVICE_ROOT / "_assets" / "menubar-icon.png"
        icon_kwargs = {}
        if icon_path.exists():
            icon_kwargs = {"icon": str(icon_path), "template": True}
        self.app = rumps.App("paper-review", title=None if icon_kwargs else "◫",
                             quit_button=None, **icon_kwargs)
        self.menu_status = rumps.MenuItem("●  starting…")
        self.menu_status.set_callback(None)
        self.menu_open = rumps.MenuItem("Open Gallery",
                                        callback=self._on_open_gallery)
        self.menu_url = rumps.MenuItem(f"http://127.0.0.1:{port}",
                                       callback=self._on_open_gallery)
        self.menu_restart = rumps.MenuItem("Restart Server",
                                           callback=self._on_restart)
        self.menu_toggle = rumps.MenuItem("Stop Server",
                                          callback=self._on_toggle)
        self.menu_logs = rumps.MenuItem("Open Latest Log",
                                        callback=self._on_open_log)
        self.menu_auto_open = rumps.MenuItem("Auto-open on launch",
                                             callback=self._on_toggle_auto_open)
        if self.auto_open:
            self.menu_auto_open.state = 1
        self.menu_quit = rumps.MenuItem("Quit", callback=self._on_quit)

        self.app.menu = [
            self.menu_status,
            None,
            self.menu_open,
            self.menu_url,
            None,
            self.menu_restart,
            self.menu_toggle,
            None,
            self.menu_logs,
            self.menu_auto_open,
            None,
            self.menu_quit,
        ]

        # Periodic status refresh
        self.timer = rumps.Timer(self._tick, 2)

    # ─── Server lifecycle ───────────────────────────────────────────────
    def _start_server(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if _port_in_use(self.port):
            self._set_status("●  port in use", "yellow")
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = _LOG_DIR / f"server-{ts}.log"
        cli = _resolve_cli()
        cmd = [cli, "serve", "--port", str(self.port)]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=open(self.log_path, "ab"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            self._set_status(f"●  CLI not found: {e}", "red")
            return
        ready = _wait_port(self.port, timeout=8)
        if ready:
            self._set_status(f"●  running on :{self.port}", "green")
            self.menu_toggle.title = "Stop Server"
            if self.auto_open:
                self._open_gallery()
        else:
            self._set_status("●  failed to start (check log)", "red")

    def _stop_server(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self.proc = None
        self._set_status("●  stopped", "gray")
        self.menu_toggle.title = "Start Server"

    # ─── Menu callbacks ─────────────────────────────────────────────────
    def _on_open_gallery(self, _sender) -> None:
        self._open_gallery()

    def _on_restart(self, _sender) -> None:
        self._stop_server()
        time.sleep(0.4)
        self._start_server()

    def _on_toggle(self, sender) -> None:
        if self.proc and self.proc.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _on_open_log(self, _sender) -> None:
        if self.log_path and self.log_path.exists():
            subprocess.Popen(["open", str(self.log_path)])
        else:
            rumps.notification(
                title="paper-review",
                subtitle="",
                message="No log yet — server hasn't started.",
            )

    def _on_toggle_auto_open(self, sender) -> None:
        sender.state = 0 if sender.state else 1
        self.auto_open = bool(sender.state)

    def _on_quit(self, _sender) -> None:
        self._stop_server()
        rumps.quit_application()

    # ─── Helpers ────────────────────────────────────────────────────────
    def _open_gallery(self) -> None:
        if not _port_in_use(self.port):
            self._start_server()
            time.sleep(0.5)
        webbrowser.open(f"http://127.0.0.1:{self.port}")

    def _set_status(self, text: str, color: str) -> None:
        self.menu_status.title = text
        # If we're using a template image icon, keep it fixed; status shows in
        # the dropdown. Only fall back to a glyph title when no icon is set.
        if getattr(self.app, "icon", None):
            return
        self.app.title = "⚠" if color == "red" else "◫"

    def _tick(self, _sender) -> None:
        # Detect external state changes (e.g. proc died, port freed)
        if self.proc and self.proc.poll() is not None:
            self.proc = None
            self._set_status("●  crashed (see log)", "red")
            self.menu_toggle.title = "Start Server"
        elif self.proc is None and _port_in_use(self.port):
            self._set_status(f"●  external server on :{self.port}", "yellow")
        elif self.proc is None and not _port_in_use(self.port):
            # idle
            pass

    # ─── Run ────────────────────────────────────────────────────────────
    def run(self) -> None:
        # Kick off the server before the run loop starts so the menubar shows
        # the live state immediately
        rumps.Timer(lambda _: (self._start_server(), self.timer.start()), 0.1).start()
        self.app.run()
