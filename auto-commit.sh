#!/usr/bin/env bash
# Auto-commit & push paper-review changes. Intended to run from a Claude Code
# Stop hook — fires after each turn, no-ops when nothing changed.
#
# Safe to run anytime: exits 0 quickly if there's nothing to commit.
set -uo pipefail

REPO="$HOME/Projects/paper-review-service"
cd "$REPO" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Nothing changed → done
[[ -z "$(git status --porcelain)" ]] && exit 0

git add -A 2>/dev/null || exit 0

ts="$(date '+%Y-%m-%d %H:%M')"
# Short list of changed files for the message body
files="$(git diff --cached --name-only | sed 's|^|  |' | head -8)"
n="$(git diff --cached --name-only | wc -l | tr -d ' ')"

git commit -q -m "auto: ${ts} (${n} file(s))

${files}" 2>/dev/null || exit 0

# Push in the background; ignore failures (e.g. offline). Don't block the turn.
( git push -q origin main >/dev/null 2>&1 & ) 2>/dev/null || true
exit 0
