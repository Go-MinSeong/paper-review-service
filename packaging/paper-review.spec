# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — bundles the FastAPI app + vendored engine + UI into a
macOS .app. Build via packaging/build.sh."""
import os
import re

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))  # noqa: F821
SRC = os.path.join(ROOT, "src", "paper_review")

# Version comes from ONE place. It used to be typed into this file by hand and
# drifted from __init__.py more than once (the v2.7.1 release even shipped a
# 2.4.6 build).
with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)

ICON = os.path.join(ROOT, "assets", "app_icon.icns")
if not os.path.exists(ICON):  # build.sh generates it; keep a source build working
    ICON = None

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
    icon=ICON,
)
coll = COLLECT(  # noqa: F821
    exe, a.binaries, a.datas, name="paper-review"
)
app = BUNDLE(  # noqa: F821
    coll,
    name="paper-review.app",
    icon=ICON,
    bundle_identifier="io.github.go-minseong.paperreview",
    info_plist={
        "CFBundleName": "paper-review",
        "CFBundleDisplayName": "paper-review",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # False = a real Dock app, not a menubar-only accessory. The menubar
        # entry point still exists, but a status item hides behind the notch or
        # a Hidden Bar — the Dock is the entry point that is always there.
        "LSUIElement": False,
        # The window loads the local server over plain http
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
            "NSExceptionDomains": {
                "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                "localhost": {"NSExceptionAllowsInsecureHTTPLoads": True},
            },
        },
        # publish writes drafts into the user's vault, usually under ~/Documents
        "NSDocumentsFolderUsageDescription": (
            "Obsidian/velog vault의 drafts 폴더에 리뷰를 내보냅니다."
        ),
    },
)
