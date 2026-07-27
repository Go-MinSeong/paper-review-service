#!/usr/bin/env bash
# Build the paper-review macOS .app and a distributable zip.
#
#   bash packaging/build.sh            # build for the host arch
#   PR_TARGET_ARCH=universal2 bash packaging/build.sh universal2
#
# Output: dist/paper-review-<arch>.zip  (extract → /Applications → right-click Open)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ARCH="${1:-$(uname -m)}"
PY="$ROOT/.venv/bin/python"

command -v "$PY" >/dev/null || { echo "✗ $PY not found (uv venv && uv pip install -e '.[dev]')"; exit 1; }
"$PY" -c "import PyInstaller" 2>/dev/null || { echo "✗ pyinstaller missing — uv pip install -e '.[dev]'"; exit 1; }

echo "→ app icon (.icns) …"
[ -f assets/app_icon.png ] || "$PY" assets/generate_icons.py
# always rebuild the iconset — a cached one leaves the Dock showing the old icon
rm -rf assets/app_icon.iconset && mkdir -p assets/app_icon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s assets/app_icon.png \
    --out "assets/app_icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/app_icon.png \
    --out "assets/app_icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns assets/app_icon.iconset -o assets/app_icon.icns
rm -rf assets/app_icon.iconset

echo "→ PyInstaller (arch=$ARCH) …"
rm -rf build "dist/paper-review.app"
"$PY" -m PyInstaller --noconfirm --clean packaging/paper-review.spec

echo "→ ad-hoc codesign …"
codesign --force --deep --sign - "dist/paper-review.app" || echo "  (codesign skipped/failed — ok for local use)"

echo "→ zip …"
( cd dist && rm -f "paper-review-${ARCH}.zip" && ditto -c -k --keepParent "paper-review.app" "paper-review-${ARCH}.zip" )

echo "✓ dist/paper-review-${ARCH}.zip"
echo "  Install: bash packaging/install-app.sh   (or drag paper-review.app to /Applications)"
echo "  First launch: right-click → Open (ad-hoc signed)."
echo "  Review/chat still need the Claude Code CLI installed & signed in."
