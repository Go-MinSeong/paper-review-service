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
echo "✓ built $APP"

if [[ "${1:-}" == "--apps" ]]; then
  dest="$HOME/Applications/paper-review.app"
  rm -rf "$dest"
  cp -R "$APP" "$dest"
  echo "✓ copied to $dest"
fi

echo ""
echo "Double-click paper-review.app to start. A ◫ icon appears in the menubar —"
echo "click it → Open Gallery. To keep it handy, drag the app to the Dock or"
echo "into Applications (or re-run with --apps)."
