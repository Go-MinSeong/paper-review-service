#!/usr/bin/env bash
# Install a macOS LaunchAgent so the paper-review menubar app starts at login
# and stays alive. Edits the user's ~/Library/LaunchAgents.
#
# Usage:
#   bash install-menubar.sh            # install + load
#   bash install-menubar.sh --uninstall
#
set -euo pipefail

LABEL="com.paper-review.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV_BIN="$HOME/.paper-reviews/.venv/bin/paper-review"
LOG_DIR="$HOME/.paper-reviews/_logs"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ uninstalled $LABEL"
  exit 0
fi

if [[ ! -x "$VENV_BIN" ]]; then
  echo "ERROR: $VENV_BIN not found. Run 'uv pip install -e .' first." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

# Resolve the directory holding the `claude` CLI so the agent's PATH can find it
CLAUDE_DIR=""
if command -v claude >/dev/null 2>&1; then
  CLAUDE_DIR="$(dirname "$(command -v claude)")"
fi
AGENT_PATH="$HOME/.local/bin:$(dirname "$VENV_BIN"):/usr/local/bin:/usr/bin:/bin"
[[ -n "$CLAUDE_DIR" ]] && AGENT_PATH="$CLAUDE_DIR:$AGENT_PATH"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_BIN</string>
        <string>menubar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$AGENT_PATH</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/menubar.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/menubar.err.log</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
PLISTEOF

# Reload
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✓ installed $LABEL"
echo "  plist: $PLIST"
echo "  The menubar app will start now and at every login."
echo "  Quit from the menubar to stop; it won't auto-restart after a clean quit."
echo "  Uninstall: bash install-menubar.sh --uninstall"
