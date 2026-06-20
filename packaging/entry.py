"""PyInstaller entry point for the packaged .app.

No args → native window; any args → CLI (so the frozen binary can re-exec
itself for serve / init / _run-script). See paper_review.app.desktop_main.
"""

from paper_review.app import desktop_main

if __name__ == "__main__":
    desktop_main()
