#!/usr/bin/env bash
set -euo pipefail
LABEL="com.mowuji.widget"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Uninstalled."
