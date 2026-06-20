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
import socket
import sys
import threading
import time
from pathlib import Path

WINDOW_TITLE = "paper-review"


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

        uvicorn.run(
            "paper_review.server.app:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )

    t = threading.Thread(target=_serve, name="pr-server", daemon=True)
    t.start()
    return t


def run_app(port: int | None = None) -> None:
    _augment_path()
    # Best-effort first-run install of the named subagents into ~/.claude/agents.
    try:
        from ._paper_reader import runner

        runner.install_subagents()
    except Exception:
        pass
    port = port or _free_port()
    start_server(port)
    if not _wait_server(port):
        print("paper-review: server failed to start", file=sys.stderr)
        sys.exit(1)
    import webview

    webview.create_window(
        WINDOW_TITLE, f"http://127.0.0.1:{port}/", width=1280, height=860
    )
    webview.start()


def desktop_main() -> None:
    """Frozen .app entry: window when double-clicked, CLI when given args."""
    if len(sys.argv) > 1:
        from .cli import main

        main()
    else:
        run_app()
