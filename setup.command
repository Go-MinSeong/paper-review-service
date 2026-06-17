#!/usr/bin/env bash
# One-double-click setup for paper-review (macOS).
#
# For non-developers: download this repo (GitHub → Code → Download ZIP), unzip,
# then double-click this file in Finder. It installs everything and builds the
# launcher app. (Gatekeeper may block the first double-click — right-click the
# file → Open → Open.)
#
# Equivalent to running, in order:
#   uv venv && uv pip install -e .
#   bash install-skills.sh
#   bash install-launcher.sh --apps
#
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$1"; }

finish() {  # keep the Terminal window readable after a double-click
  echo ""
  read -r -p "Press Enter to close…" _ || true
}
trap finish EXIT

if [[ "$(uname)" != "Darwin" ]]; then
  warn "This setup targets macOS. On Linux, run the three commands above manually."
  exit 1
fi

# 1) uv (Python package manager) ------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"   # uv installs here
fi
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (astral.sh) — the Python package manager"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { warn "uv install failed. See https://github.com/astral-sh/uv"; exit 1; }
ok "uv: $(uv --version)"

# 2) venv + package -------------------------------------------------------------
say "Creating .venv and installing paper-review"
[[ -d .venv ]] || uv venv
uv pip install -e .
ok "package installed"

# 3) Claude Code skills ---------------------------------------------------------
say "Linking Claude Code skills"
bash install-skills.sh
ok "skills linked"

# 4) Double-click launcher app --------------------------------------------------
say "Building the launcher app"
bash install-launcher.sh --apps
ok "launcher app ready (see the line above for its location)"

# 5) Claude Code CLI check (needed for review/chat) -----------------------------
say "Checking for the Claude Code CLI"
if command -v claude >/dev/null 2>&1; then
  ok "claude: $(claude --version 2>/dev/null | head -1)"
else
  warn "The 'claude' CLI was not found on PATH."
  warn "Reviewing/chatting needs it — install & sign in: https://claude.com/claude-code"
fi

echo ""
ok "Setup complete."
echo "Next: double-click paper-review.app (in this folder or ~/Applications)."
echo "A ◫ icon appears in the menubar → Open Gallery → paste a link to review."
