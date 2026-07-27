#!/usr/bin/env bash
# Install the built app into /Applications so it lives in the Dock / Spotlight
# like any other app.
#
#   bash packaging/install-app.sh          # build if needed, then install
#   bash packaging/install-app.sh --open   # …and launch it
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
APP="dist/paper-review.app"
DEST="/Applications/paper-review.app"

[ -d "$APP" ] || { echo "→ no build yet — running packaging/build.sh"; bash packaging/build.sh; }

if [ -d "$DEST" ]; then
  # A running copy can't be replaced cleanly; ask the user to quit it first.
  if pgrep -f "$DEST/Contents/MacOS/paper-review" >/dev/null; then
    echo "✗ paper-review is running — quit it (Dock → right-click → Quit) and re-run."
    exit 1
  fi
  echo "→ replacing existing $DEST"
  rm -rf "$DEST"
fi

ditto "$APP" "$DEST"
# Let Launch Services notice the new bundle right away (Spotlight/Dock icon).
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST" 2>/dev/null || true

echo "✓ installed: $DEST"
echo "  Launch it once (right-click → Open on the very first run), then"
echo "  right-click its Dock icon → Options → Keep in Dock to pin it."
[ "${1:-}" = "--open" ] && open "$DEST"
