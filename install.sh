#!/usr/bin/env bash
# Installs the widget as a login item (launchd agent) for the current user.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-$(command -v python3)}"
LABEL="com.mowuji.widget"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mo-wuji-widget.log"

if ! "$PY" -c 'import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' 2>/dev/null; then
  echo "error: $PY needs Tk 8.6+. Use the python.org installer, or: brew install python python-tk" >&2
  exit 1
fi
if ! "$PY" -c 'import PIL' 2>/dev/null; then
  echo "error: Pillow is missing. Run: $PY -m pip install -r \"$DIR/requirements.txt\"" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/widget.py</string>
    <!-- after a crash macOS would otherwise wait on a hidden "reopen windows?" alert -->
    <string>-ApplePersistenceIgnoreState</string>
    <string>YES</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. The widget starts now and at every login. Logs: $LOG"
