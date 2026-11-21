#!/usr/bin/env bash
# Put this commit's MacBook Pro code in place and keep it current by itself.
#
# Mark 2026-11-21 («Моя цель это твоя автономность», option «Б + Г»): merged
# code reaches the MacBook Pro like it reaches the Mac mini. Run it once by hand
# from a checkout of this repository:
#
#   git clone https://github.com/pirajoke/agent-dashboard ~/agent-dashboard 2>/dev/null
#   cd ~/agent-dashboard && git pull --ff-only && builder/deploy_macbook.sh
#
# It installs the launchd agent com.pirajoke.macbook-auto-update. Every 5 minutes
# it runs builder/auto_deploy.py, which checks main and, when builder/ changed
# and CI is green, runs this script again from that commit
# (with MACBOOK_INSTALL_AUTO_UPDATE=0). It then checks the Health API on :8880
# and redeploys the previous commit if the check fails. The result shows on
# GitHub as the commit status macbook-pro/deploy.
#
# What it puts in place:
#   - the collectors (Daily Work, infra changes, sessions, care) through
#     install_daily_work_collector.sh, as for any Mac that sends to the Mac mini;
#   - the Health API script builder/macbook/macbook-pro-health.py, if this
#     commit has it, restarting com.pirajoke.macbook-pro-health only when it
#     changed. The pre-git copy is kept as macbook-pro-health.py.pre-git and is
#     restored by a rollback to a commit without the script.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SRC_DIR/.." && pwd)"
source "$SRC_DIR/launchd/install_agent.sh"
SCRIPTS_DIR="${MACBOOK_SCRIPTS_DIR:-$HOME/scripts}"
STATE_DIR="${MACBOOK_STATE_DIR:-$HOME/.agent-bridge/macbook-auto-update}"
HEALTH_LABEL="com.pirajoke.macbook-pro-health"
HEALTH_TARGET="$SCRIPTS_DIR/macbook-pro-health.py"
HEALTH_SOURCE="$SRC_DIR/macbook/macbook-pro-health.py"
mkdir -p "$SCRIPTS_DIR" "$STATE_DIR"

# 1. Collectors, the same set any Mac that sends to the Mac mini runs.
"$SRC_DIR/install_daily_work_collector.sh" --machine macbook-pro --push-to "${MACBOOK_PUSH_TO:-maxxs-mac-mini}"

# 2. Health API script: replace it only when this commit changes it.
restart_health=0
if [[ -f "$HEALTH_SOURCE" ]]; then
  python3 -m py_compile "$HEALTH_SOURCE"
  if [[ -f "$HEALTH_TARGET" && ! -f "$HEALTH_TARGET.pre-git" ]]; then
    cp -p "$HEALTH_TARGET" "$HEALTH_TARGET.pre-git"
  fi
  if ! cmp -s "$HEALTH_SOURCE" "$HEALTH_TARGET"; then
    cp "$HEALTH_SOURCE" "$HEALTH_TARGET.tmp" && mv "$HEALTH_TARGET.tmp" "$HEALTH_TARGET"
    restart_health=1
  fi
elif [[ -f "$HEALTH_TARGET.pre-git" ]] && ! cmp -s "$HEALTH_TARGET.pre-git" "$HEALTH_TARGET"; then
  # Rolled back to a commit from before the script was in git.
  cp -p "$HEALTH_TARGET.pre-git" "$HEALTH_TARGET"
  restart_health=1
fi
if [[ "$restart_health" == "1" ]] && launchctl print "gui/$(id -u)/$HEALTH_LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$HEALTH_LABEL"
fi

# 3. The updater itself, and the commit it now counts as deployed.
cp "$SRC_DIR/auto_deploy.py" "$SCRIPTS_DIR/auto_deploy.py"
python3 -m py_compile "$SCRIPTS_DIR/auto_deploy.py"
DEPLOYED_SHA="${AUTO_DEPLOY_DEPLOYED_SHA:-$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)}"
if [[ -n "$DEPLOYED_SHA" ]]; then
  AUTO_DEPLOY_STATE_DIR="$STATE_DIR" python3 "$SCRIPTS_DIR/auto_deploy.py" --record "$DEPLOYED_SHA"
fi

UPDATE_LABEL="com.pirajoke.macbook-auto-update"
UPDATE_PLIST="$HOME/Library/LaunchAgents/$UPDATE_LABEL.plist"
if [[ "${MACBOOK_INSTALL_AUTO_UPDATE:-${DASHBOARD_INSTALL_AUTO_DEPLOY:-1}}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$UPDATE_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" -e "s|__REPO_DIR__|$REPO_DIR|g" \
    -e "s|__STATE_DIR__|$STATE_DIR|g" "$SRC_DIR/launchd/$UPDATE_LABEL.plist.template" > "$UPDATE_PLIST.tmp"
  plutil -lint "$UPDATE_PLIST.tmp" >/dev/null
  install_launchd_agent "$UPDATE_PLIST.tmp" "$UPDATE_PLIST" "$UPDATE_LABEL"
fi

echo "MacBook Pro code deployed from ${DEPLOYED_SHA:-this checkout}"
