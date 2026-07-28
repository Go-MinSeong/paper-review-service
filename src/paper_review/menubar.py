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


def _stale_server_pids(port: int) -> list[int]:
    """PIDs of our own `paper-review serve` left listening on `port`.

    When the menubar is SIGKILLed (e.g. `launchctl kickstart -k`), its server
    child — spawned with start_new_session=True — is orphaned to PID 1 and keeps
    holding the port, so a fresh menubar can't bind and ends up serving stale
    code. We match by command so we never touch unrelated processes.
    """
    # Absolute paths: under launchd the inherited PATH is minimal and would not
    # find lsof (/usr/sbin) or ps (/bin), silently disabling reclaim.
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    ps = shutil.which("ps") or "/bin/ps"
    try:
        out = subprocess.run(
            [lsof, "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=4,
        ).stdout
    except Exception:
        return []
    pids: list[int] = []
    for tok in out.split():
        if not tok.strip().isdigit():
            continue
        pid = int(tok)
        try:
            cmd = subprocess.run(
                [ps, "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=4,
            ).stdout
        except Exception:
            cmd = ""
        if "paper-review serve" in cmd or "paper_review" in cmd:
            pids.append(pid)
    return pids


def _reclaim_port(port: int) -> bool:
    """Kill stale paper-review servers on `port`. True if the port ends up free."""
    for pid in _stale_server_pids(port):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            freed = False
            for _ in range(20):  # up to ~2s
                if not _port_in_use(port):
                    freed = True
                    break
                time.sleep(0.1)
            if freed:
                break
    return not _port_in_use(port)


def _icon_path() -> Path | None:
    """Menubar template icon. The frozen .app carries assets/ inside _MEIPASS,
    a source checkout has it in the repo; _assets/ is where it used to live."""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    roots += [Path(__file__).resolve().parents[2], SERVICE_ROOT]
    for root in roots:
        for rel in ("assets/menubar-icon.png", "_assets/menubar-icon.png"):
            p = root / rel
            if p.exists():
                return p
    return None


def _resolve_cli() -> str:
    """Find paper-review CLI — prefer the venv next to this module."""
    venv_bin = SERVICE_ROOT / ".venv" / "bin" / "paper-review"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("paper-review")
    if found:
        return found
    return "paper-review"


def _lan_ip() -> str | None:
    """Best-effort local network IP (for accessing the app from a phone on the
    same Wi-Fi). Returns None if it can't be determined."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the egress iface
        ip = s.getsockname()[0]
        return ip if not ip.startswith("127.") else None
    except Exception:
        return None
    finally:
        s.close()


class PaperReviewMenubarApp:
    def __init__(self, port: int = DEFAULT_PORT, auto_open: bool = False):
        if rumps is None:
            print(
                "rumps not available — menubar mode requires macOS + rumps.",
                file=sys.stderr,
            )
            sys.exit(1)

        self.port = port
        self.auto_open = auto_open
        self.proc: subprocess.Popen | None = None
        self.log_path: Path | None = None

        _LOG_DIR.mkdir(parents=True, exist_ok=True)

        icon_path = _icon_path()
        icon_kwargs = {}
        if icon_path is not None:
            icon_kwargs = {"icon": str(icon_path), "template": True}
        self.app = rumps.App(
            "paper-review",
            title=None if icon_kwargs else "◫",
            quit_button=None,
            **icon_kwargs,
        )
        # One line per thing you can actually do. The old menu repeated the
        # gallery URL as its own row (same action as Open Gallery) and showed a
        # dead LAN row that was computed once at launch — so it still displayed
        # the IP of whatever network the Mac was on when the app started.
        self.menu_status = rumps.MenuItem("Starting…")
        self.menu_status.set_callback(None)
        self.menu_open = rumps.MenuItem("Open Gallery", callback=self._on_open_gallery)
        self.menu_lan = rumps.MenuItem("Phone URL: …", callback=self._on_copy_lan)
        self.menu_restart = rumps.MenuItem("Restart Server", callback=self._on_restart)
        self.menu_toggle = rumps.MenuItem("Stop Server", callback=self._on_toggle)
        self.menu_logs = rumps.MenuItem("Open Latest Log", callback=self._on_open_log)
        self.menu_auto_open = rumps.MenuItem(
            "Auto-open on Launch", callback=self._on_toggle_auto_open
        )
        if self.auto_open:
            self.menu_auto_open.state = 1
        self.menu_quit = rumps.MenuItem("Quit paper-review", callback=self._on_quit)

        self.app.menu = [
            self.menu_status,
            None,
            self.menu_open,
            self.menu_lan,
            None,
            self.menu_restart,
            self.menu_toggle,
            None,
            self.menu_logs,
            self.menu_auto_open,
            None,
            self.menu_quit,
        ]
        self._refresh_lan()

        # Periodic status refresh
        self.timer = rumps.Timer(self._tick, 2)

    # ─── Server lifecycle ───────────────────────────────────────────────
    def _start_server(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if _port_in_use(self.port):
            # A previous instance may have been SIGKILLed (launchctl kickstart),
            # orphaning its server here. Reclaim it so we serve current code.
            if not _reclaim_port(self.port):
                self._set_status(f"Port {self.port} is busy", "yellow")
                return
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = _LOG_DIR / f"server-{ts}.log"
        cli = _resolve_cli()
        # Bind all interfaces by default so the app is reachable from a phone
        # on the same Wi-Fi (http://<lan-ip>:<port>). Override with
        # PAPER_REVIEW_HOST=127.0.0.1 for localhost-only.
        host = os.environ.get("PAPER_REVIEW_HOST", "0.0.0.0")
        cmd = [cli, "serve", "--port", str(self.port), "--host", host]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=open(self.log_path, "ab"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            self._set_status(f"CLI not found: {e}", "red")
            return
        ready = _wait_port(self.port, timeout=8)
        if ready:
            self._set_status(f"Running · localhost:{self.port}", "green")
            self.menu_toggle.title = "Stop Server"
            _wait_port(80, timeout=2)  # pretty-URL listener (best effort)
            self._refresh_url_items()
            if self.auto_open:
                self._open_gallery()
        else:
            self._set_status("Failed to start — see log", "red")

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
        self._set_status("Stopped", "gray")
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

    def _on_copy_lan(self, _sender) -> None:
        """Copy the same-Wi-Fi URL — you can't click a link into a phone, but
        you can paste it into a message to yourself."""
        url = self._lan_url()
        if not url:
            rumps.notification(
                title="paper-review",
                subtitle="",
                message="No local network address right now.",
            )
            return
        try:
            import AppKit

            pb = AppKit.NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(url, AppKit.NSPasteboardTypeString)
        except Exception:
            subprocess.run(["pbcopy"], input=url.encode(), check=False)
        rumps.notification(title="paper-review", subtitle="", message=f"Copied {url}")

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
    def _gallery_url(self) -> str:
        """Pretty URL when the port-80 listener is up, else the plain one."""
        if _port_in_use(80):
            return "http://paper-review.local"
        return f"http://127.0.0.1:{self.port}"

    def _lan_url(self) -> str | None:
        ip = _lan_ip()
        return f"http://{ip}:{self.port}" if ip else None

    def _refresh_lan(self) -> None:
        """The Mac changes networks; the menu used to keep the launch-time IP."""
        url = self._lan_url()
        self.menu_lan.title = (
            f"Phone URL: {url.removeprefix('http://')}"
            if url
            else "Phone URL: (offline)"
        )

    def _refresh_url_items(self) -> None:
        self._refresh_lan()

    def _open_gallery(self) -> None:
        if not _port_in_use(self.port):
            self._start_server()
            time.sleep(0.5)
        webbrowser.open(self._gallery_url())

    def _set_status(self, text: str, color: str) -> None:
        self.menu_status.title = text
        # If we're using a template image icon, keep it fixed; status shows in
        # the dropdown. Only fall back to a glyph title when no icon is set.
        if getattr(self.app, "icon", None):
            return
        self.app.title = "⚠" if color == "red" else "◫"

    def _tick(self, _sender) -> None:
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 15 == 0:  # ~30s — networks change, the menu shouldn't lie
            self._refresh_lan()
        # Detect external state changes (e.g. proc died, port freed)
        if self.proc and self.proc.poll() is not None:
            self.proc = None
            self._set_status("Crashed — see log", "red")
            self.menu_toggle.title = "Start Server"
        elif self.proc is None and _port_in_use(self.port):
            self._set_status(f"External server on :{self.port}", "yellow")
        elif self.proc is None and not _port_in_use(self.port):
            # idle
            pass

    # ─── Run ────────────────────────────────────────────────────────────
    def run(self) -> None:
        # Kick off the server before the run loop starts so the menubar shows
        # the live state immediately
        rumps.Timer(lambda _: (self._start_server(), self.timer.start()), 0.1).start()
        self.app.run()
