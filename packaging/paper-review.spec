# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — bundles the FastAPI app + vendored engine + UI into a
macOS .app. Build via packaging/build.sh."""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))  # noqa: F821
SRC = os.path.join(ROOT, "src", "paper_review")

# Data files (kept on disk in the bundle). The vendored scripts must be present
# as .py so cli._run-script can load them by path.
datas = [
    (os.path.join(SRC, "_paper_reader", "scripts"), "paper_review/_paper_reader/scripts"),
    (os.path.join(SRC, "_paper_reader", "assets"), "paper_review/_paper_reader/assets"),
    (os.path.join(SRC, "_paper_reader", "references"), "paper_review/_paper_reader/references"),
    (os.path.join(SRC, "server", "templates"), "paper_review/server/templates"),
    (os.path.join(SRC, "server", "static"), "paper_review/server/static"),
    (os.path.join(SRC, "server", "illustration_groups.json"), "paper_review/server"),
    (os.path.join(ROOT, "skills"), "skills"),
]
_vs = os.path.join(SRC, "publish", "voice_samples")
if os.path.isdir(_vs):
    datas += [(_vs, "paper_review/publish/voice_samples")]

# The vendored scripts are bundled as DATA (.py on disk, loaded by path), so
# PyInstaller never analyzes their imports — every 3rd-party module they use
# must be collected explicitly here.
hiddenimports = []
binaries = []
for pkg in (
    "trafilatura", "lxml", "pypdfium2", "bs4", "webview", "rumps", "PIL",
    "pypdf", "httpx", "httpcore", "h11", "certifi", "charset_normalizer",
    "courlan", "justext", "htmldate", "dateparser",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
for pkg in ("uvicorn", "fastapi", "pydantic", "anyio", "multipart"):
    hiddenimports += collect_submodules(pkg)

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="paper-review",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=os.environ.get("PR_TARGET_ARCH"),
)
coll = COLLECT(  # noqa: F821
    exe, a.binaries, a.datas, name="paper-review"
)
app = BUNDLE(  # noqa: F821
    coll,
    name="paper-review.app",
    bundle_identifier="com.paper-review.app",
    info_plist={
        "CFBundleName": "paper-review",
        "CFBundleDisplayName": "paper-review",
        "CFBundleShortVersionString": "2.2.2",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
