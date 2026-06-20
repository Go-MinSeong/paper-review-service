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

echo "→ PyInstaller (arch=$ARCH) …"
rm -rf build "dist/paper-review.app"
"$PY" -m PyInstaller --noconfirm --clean packaging/paper-review.spec

echo "→ ad-hoc codesign …"
codesign --force --deep --sign - "dist/paper-review.app" || echo "  (codesign skipped/failed — ok for local use)"

echo "→ zip …"
( cd dist && rm -f "paper-review-${ARCH}.zip" && ditto -c -k --keepParent "paper-review.app" "paper-review-${ARCH}.zip" )

echo "✓ dist/paper-review-${ARCH}.zip"
echo "  Install: unzip → drag paper-review.app to /Applications → first launch: right-click → Open."
echo "  Review/chat still need the Claude Code CLI installed & signed in."
