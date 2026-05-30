#!/usr/bin/env bash
# Symlink the paper-review Claude Code skills into ~/.claude/skills/.
# The repo's skills/ directory is the source of truth — edits there are live.
#
# Usage:
#   bash install-skills.sh           # symlink (default)
#   bash install-skills.sh --copy    # copy instead of symlink
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$REPO_DIR/skills"
DEST_DIR="$HOME/.claude/skills"
MODE="symlink"
[[ "${1:-}" == "--copy" ]] && MODE="copy"

mkdir -p "$DEST_DIR"

for skill_path in "$SRC_DIR"/*/; do
  name="$(basename "$skill_path")"
  target="$DEST_DIR/$name"

  # Remove any existing install (dir or symlink)
  if [[ -e "$target" || -L "$target" ]]; then
    rm -rf "$target"
  fi

  if [[ "$MODE" == "symlink" ]]; then
    ln -s "$skill_path%/" "$target"
    # ln above keeps trailing slash on some shells; normalize:
    rm -f "$target"
    ln -s "${skill_path%/}" "$target"
    echo "✓ linked  $name -> ${skill_path%/}"
  else
    cp -R "${skill_path%/}" "$target"
    echo "✓ copied  $name"
  fi
done

echo ""
echo "Done. Restart your Claude Code session for the skills to be picked up."
