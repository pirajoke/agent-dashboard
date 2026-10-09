#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$REPO_DIR/builder"
SCRIPTS_DIR="${DASHBOARD_SCRIPTS_DIR:-$HOME/scripts}"
PUBLIC_ASSETS_DIR="${DASHBOARD_PUBLIC_ASSETS_DIR:-$HOME/dashboard-assets}"
MAC_MINI_DASHBOARD_DIR="${MAC_MINI_DASHBOARD_DIR:-$HOME/mac-mini-dashboard}"
LOCAL_BIN_DIR="${DASHBOARD_LOCAL_BIN_DIR:-$HOME/.local/bin}"
SERVER_LABEL="${DASHBOARD_SERVER_LABEL:-com.pirajoke.dashboard-server-m4}"

mkdir -p "$SCRIPTS_DIR/dashboard_builder" "$SCRIPTS_DIR/dashboard-assets" "$PUBLIC_ASSETS_DIR" "$MAC_MINI_DASHBOARD_DIR" "$LOCAL_BIN_DIR"

cp "$SRC_DIR/build-agent-dashboard.py" "$SCRIPTS_DIR/build-agent-dashboard.py"
cp "$SRC_DIR/dashboard-rebuild.sh" "$SCRIPTS_DIR/dashboard-rebuild.sh"
cp "$SRC_DIR/dashboard-server-m4.py" "$SCRIPTS_DIR/dashboard-server-m4.py"
cp "$SRC_DIR/jarvis-agent-pipeline" "$SCRIPTS_DIR/jarvis-agent-pipeline"
cp "$SRC_DIR/jarvis-pixel-agent-event" "$SCRIPTS_DIR/jarvis-pixel-agent-event"
cp "$SRC_DIR/main_manager_status_publisher.py" "$SCRIPTS_DIR/main_manager_status_publisher.py"
cp "$SRC_DIR/daily_work_collector.py" "$SCRIPTS_DIR/daily_work_collector.py"
cp "$SRC_DIR/infra_change_collector.py" "$SCRIPTS_DIR/infra_change_collector.py"
cp "$SRC_DIR/daily_work_summarizer.py" "$SCRIPTS_DIR/daily_work_summarizer.py"
cp "$SRC_DIR/mm-command-center-auth" "$LOCAL_BIN_DIR/mm-command-center-auth"
cp "$SRC_DIR/dashboard_builder/"*.py "$SCRIPTS_DIR/dashboard_builder/"
cp "$SRC_DIR/dashboard-assets/style.css" "$SCRIPTS_DIR/dashboard-assets/style.css"
cp "$SRC_DIR/dashboard-assets/script.js" "$SCRIPTS_DIR/dashboard-assets/script.js"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$SCRIPTS_DIR/dashboard-assets/ai-town-32x32folk.png"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$PUBLIC_ASSETS_DIR/ai-town-32x32folk.png"
cp "$SRC_DIR/dashboard-assets/pixel-verse-campus-bg.webp" "$PUBLIC_ASSETS_DIR/pixel-verse-campus-bg.webp"
cp "$SRC_DIR/dashboard-assets/three.module.min.js" "$PUBLIC_ASSETS_DIR/three.module.min.js"

if [[ -f "$SRC_DIR/mac-mini-dashboard/index.html" ]]; then
  cp "$SRC_DIR/mac-mini-dashboard/index.html" "$MAC_MINI_DASHBOARD_DIR/index.html"
fi

chmod +x "$SCRIPTS_DIR/dashboard-rebuild.sh"
chmod +x "$SCRIPTS_DIR/jarvis-agent-pipeline"
chmod +x "$SCRIPTS_DIR/jarvis-pixel-agent-event"
chmod +x "$LOCAL_BIN_DIR/mm-command-center-auth"

cd "$SCRIPTS_DIR"
python3 -m py_compile build-agent-dashboard.py dashboard-server-m4.py main_manager_status_publisher.py daily_work_collector.py infra_change_collector.py daily_work_summarizer.py dashboard_builder/*.py
python3 build-agent-dashboard.py

if [[ "${DASHBOARD_RESTART_SERVER:-1}" == "1" ]] && launchctl print "gui/$(id -u)/$SERVER_LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$SERVER_LABEL"
fi

PUBLISHER_LABEL="com.pirajoke.main-manager-status-publisher"
PUBLISHER_PLIST="$HOME/Library/LaunchAgents/$PUBLISHER_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_STATUS_PUBLISHER:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/main-manager-status-publisher"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$PUBLISHER_LABEL.plist.template" > "$PUBLISHER_PLIST.tmp"
  plutil -lint "$PUBLISHER_PLIST.tmp" >/dev/null
  mv "$PUBLISHER_PLIST.tmp" "$PUBLISHER_PLIST"
  launchctl bootout "gui/$(id -u)/$PUBLISHER_LABEL" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PUBLISHER_PLIST"
fi

if [[ "${DASHBOARD_INSTALL_DAILY_WORK:-1}" == "1" ]]; then
  DAILY_WORK_INSTALL_DIR="$SCRIPTS_DIR" "$SRC_DIR/install_daily_work_collector.sh" --machine mac-mini --github --summaries
fi

echo "Dashboard builder deployed to $SCRIPTS_DIR"
