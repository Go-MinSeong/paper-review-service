#!/usr/bin/env bash
# Build a double-clickable macOS launcher app for paper-review.
#
# Non-developers can then start the service (menubar + server + gallery) by
# double-clicking an app icon — no Terminal, no commands. The app just runs
# `paper-review menubar` (which manages the FastAPI server and opens the
# gallery on click).
#
# Usage:
#   bash install-launcher.sh            # build ./paper-review.app
#   bash install-launcher.sh --apps     # also copy it into ~/Applications
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$REPO_DIR/.venv/bin/paper-review"
APP="$REPO_DIR/paper-review.app"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "✗ macOS only (the launcher is a .app bundle)." >&2
  exit 1
fi
if [[ ! -x "$BIN" ]]; then
  echo "✗ $BIN not found. Run 'uv venv && uv pip install -e .' first." >&2
  exit 1
fi

# AppleScript: launch the menubar app detached so the .app returns immediately
# and the menubar icon stays running. Logs go to /tmp for troubleshooting.
read -r -d '' SCRIPT <<APPLESCRIPT || true
do shell script "'$BIN' menubar > /tmp/paper-review-launcher.log 2>&1 &"
APPLESCRIPT

rm -rf "$APP"
osacompile -o "$APP" -e "$SCRIPT"

# Give the launcher the real app icon — otherwise it sits in the Dock as a
# generic AppleScript applet. (The PyInstaller bundle from packaging/build.sh
# gets this from its spec; this is the source-install path.)
ICON="$REPO_DIR/assets/app_icon.icns"
if [[ ! -f "$ICON" && -f "$REPO_DIR/assets/app_icon.png" ]]; then
  set +e
  ICONSET="$REPO_DIR/assets/app_icon.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$REPO_DIR/assets/app_icon.png" \
      --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s*2)) $((s*2)) "$REPO_DIR/assets/app_icon.png" \
      --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$ICON" >/dev/null 2>&1
  rm -rf "$ICONSET"
  set -e
fi
if [[ -f "$ICON" ]]; then
  cp "$ICON" "$APP/Contents/Resources/applet.icns"
  touch "$APP"   # nudge Finder/Dock to re-read the icon
fi
echo "✓ built $APP"

if [[ "${1:-}" == "--apps" ]]; then
  dest="$HOME/Applications/paper-review.app"
  # Non-fatal: ~/Applications may be missing or not user-writable. The repo
  # app already works; the copy is just for convenience.
  if mkdir -p "$HOME/Applications" 2>/dev/null && rm -rf "$dest" 2>/dev/null \
     && cp -R "$APP" "$dest" 2>/dev/null; then
    echo "✓ copied to $dest"
  else
    echo "! couldn't copy to ~/Applications (not writable) — drag $APP there yourself."
  fi
fi

echo ""
echo "Double-click paper-review.app to start. A ◫ icon appears in the menubar —"
echo "click it → Open Gallery. To keep it handy, drag the app to the Dock or"
echo "into Applications (or re-run with --apps)."
