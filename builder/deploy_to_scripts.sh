#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$REPO_DIR/builder"
source "$SRC_DIR/launchd/install_agent.sh"
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
cp "$SRC_DIR/auto_deploy.py" "$SCRIPTS_DIR/auto_deploy.py"
cp "$SRC_DIR/launchd_watchdog.py" "$SCRIPTS_DIR/launchd_watchdog.py"
cp "$SRC_DIR/owner_project_card.py" "$SCRIPTS_DIR/owner_project_card.py"
cp "$SRC_DIR/weekly_digest.py" "$SCRIPTS_DIR/weekly_digest.py"
cp "$SRC_DIR/daily_digest.py" "$SCRIPTS_DIR/daily_digest.py"
cp "$SRC_DIR/agent_task_runner.py" "$SCRIPTS_DIR/agent_task_runner.py"
cp "$SRC_DIR/context_retell.py" "$SCRIPTS_DIR/context_retell.py"
cp "$SRC_DIR/job_mail_watcher.py" "$SCRIPTS_DIR/job_mail_watcher.py"
cp "$SRC_DIR/mm-command-center-auth" "$LOCAL_BIN_DIR/mm-command-center-auth"
cp "$SRC_DIR/dashboard_builder/"*.py "$SCRIPTS_DIR/dashboard_builder/"
cp "$SRC_DIR/dashboard-assets/style.css" "$SCRIPTS_DIR/dashboard-assets/style.css"
cp "$SRC_DIR/dashboard-assets/script.js" "$SCRIPTS_DIR/dashboard-assets/script.js"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$SCRIPTS_DIR/dashboard-assets/ai-town-32x32folk.png"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$PUBLIC_ASSETS_DIR/ai-town-32x32folk.png"
cp "$SRC_DIR/dashboard-assets/pixel-verse-campus-bg.webp" "$PUBLIC_ASSETS_DIR/pixel-verse-campus-bg.webp"
cp "$SRC_DIR/dashboard-assets/three.module.min.js" "$PUBLIC_ASSETS_DIR/three.module.min.js"
for asset in manifest.json icon-192.png icon-512.png apple-touch-icon.png favicon-32.png; do
  cp "$SRC_DIR/dashboard-assets/$asset" "$PUBLIC_ASSETS_DIR/$asset"
done

if [[ -f "$SRC_DIR/mac-mini-dashboard/index.html" ]]; then
  cp "$SRC_DIR/mac-mini-dashboard/index.html" "$MAC_MINI_DASHBOARD_DIR/index.html"
fi

chmod +x "$SCRIPTS_DIR/dashboard-rebuild.sh"
chmod +x "$SCRIPTS_DIR/jarvis-agent-pipeline"
chmod +x "$SCRIPTS_DIR/jarvis-pixel-agent-event"
chmod +x "$LOCAL_BIN_DIR/mm-command-center-auth"

cd "$SCRIPTS_DIR"
python3 -m py_compile build-agent-dashboard.py dashboard-server-m4.py main_manager_status_publisher.py daily_work_collector.py infra_change_collector.py daily_work_summarizer.py auto_deploy.py launchd_watchdog.py dashboard_builder/*.py
python3 -m py_compile weekly_digest.py daily_digest.py
python3 -m py_compile agent_task_runner.py
python3 -m py_compile context_retell.py
python3 -m py_compile job_mail_watcher.py
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
  install_launchd_agent "$PUBLISHER_PLIST.tmp" "$PUBLISHER_PLIST" "$PUBLISHER_LABEL"
fi

if [[ "${DASHBOARD_INSTALL_DAILY_WORK:-1}" == "1" ]]; then
  DAILY_WORK_INSTALL_DIR="$SCRIPTS_DIR" "$SRC_DIR/install_daily_work_collector.sh" --machine mac-mini --github --summaries
fi

# Monday digest of last week's work in Telegram (Mark 2026-10-22). Sends only once Mark has saved
# ~/.agent-bridge/telegram_digest.json; until then it writes the text to ~/.agent-bridge/weekly-digest/.
DIGEST_LABEL="com.pirajoke.weekly-digest"
DIGEST_PLIST="$HOME/Library/LaunchAgents/$DIGEST_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_WEEKLY_DIGEST:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$DIGEST_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$DIGEST_LABEL.plist.template" > "$DIGEST_PLIST.tmp"
  plutil -lint "$DIGEST_PLIST.tmp" >/dev/null
  install_launchd_agent "$DIGEST_PLIST.tmp" "$DIGEST_PLIST" "$DIGEST_LABEL"
fi

# Evening summary of the day in Telegram, every day at 21:30 so it arrives by 22:00 (Mark 2026-10-23).
# Same Telegram settings as the Monday digest; without them it only writes ~/.agent-bridge/daily-digest/.
DAILY_DIGEST_LABEL="com.pirajoke.daily-digest"
DAILY_DIGEST_PLIST="$HOME/Library/LaunchAgents/$DAILY_DIGEST_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_DAILY_DIGEST:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$DAILY_DIGEST_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$DAILY_DIGEST_LABEL.plist.template" > "$DAILY_DIGEST_PLIST.tmp"
  plutil -lint "$DAILY_DIGEST_PLIST.tmp" >/dev/null
  install_launchd_agent "$DAILY_DIGEST_PLIST.tmp" "$DAILY_DIGEST_PLIST" "$DAILY_DIGEST_LABEL"
fi

# Agents take things off Mark's «Ждёт тебя» list (Mark 2026-10-23: «включай исполнителя агентов на
# Mac mini»). Every 5 minutes, one item at a time, a draft PR or a report at most; see agent_task_runner.py.
RUNNER_LABEL="com.pirajoke.agent-task-runner"
RUNNER_PLIST="$HOME/Library/LaunchAgents/$RUNNER_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_AGENT_TASK_RUNNER:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$RUNNER_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$RUNNER_LABEL.plist.template" > "$RUNNER_PLIST.tmp"
  plutil -lint "$RUNNER_PLIST.tmp" >/dev/null
  install_launchd_agent "$RUNNER_PLIST.tmp" "$RUNNER_PLIST" "$RUNNER_LABEL"
fi

# Контекст in plain Russian (Mark 2026-10-25: English agent updates were «невозможно читать»).
# Every 10 minutes new updates get a short Russian retelling; see context_retell.py.
RETELL_LABEL="com.pirajoke.context-retell"
RETELL_PLIST="$HOME/Library/LaunchAgents/$RETELL_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_CONTEXT_RETELL:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$RETELL_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$RETELL_LABEL.plist.template" > "$RETELL_PLIST.tmp"
  plutil -lint "$RETELL_PLIST.tmp" >/dev/null
  install_launchd_agent "$RETELL_PLIST.tmp" "$RETELL_PLIST" "$RETELL_LABEL"
fi

# Employer replies in Mark's job mailbox (Mark 2026-10-24: «не пропускать положительные ответы»).
# Every 10 minutes; does nothing until Mark presses «Подключить почту» (Gmail read-only).
JOB_MAIL_LABEL="com.pirajoke.job-mail-watcher"
JOB_MAIL_PLIST="$HOME/Library/LaunchAgents/$JOB_MAIL_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_JOB_MAIL:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$JOB_MAIL_LABEL"
  mkdir -p -m 700 "$HOME/.agent-bridge/job-mail"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$JOB_MAIL_LABEL.plist.template" > "$JOB_MAIL_PLIST.tmp"
  plutil -lint "$JOB_MAIL_PLIST.tmp" >/dev/null
  install_launchd_agent "$JOB_MAIL_PLIST.tmp" "$JOB_MAIL_PLIST" "$JOB_MAIL_LABEL"
fi

# Record what is deployed now, before the agent starts (RunAtLoad), so the auto-deploy agent compares main against it.
DEPLOYED_SHA="${AUTO_DEPLOY_DEPLOYED_SHA:-$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)}"
if [[ -n "$DEPLOYED_SHA" ]]; then
  python3 "$SRC_DIR/auto_deploy.py" --record "$DEPLOYED_SHA"
fi

# After a power loss launchd may not load every service at login (2026-10-12). The watchdog loads
# back the services it has seen running; see launchd_watchdog.py. Installed after the deployed commit
# is recorded: the watchdog removes itself when that commit does not ship it (a rollback).
WATCHDOG_LABEL="com.pirajoke.launchd-watchdog"
WATCHDOG_PLIST="$HOME/Library/LaunchAgents/$WATCHDOG_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_LAUNCHD_WATCHDOG:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$WATCHDOG_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$WATCHDOG_LABEL.plist.template" > "$WATCHDOG_PLIST.tmp"
  plutil -lint "$WATCHDOG_PLIST.tmp" >/dev/null
  install_launchd_agent "$WATCHDOG_PLIST.tmp" "$WATCHDOG_PLIST" "$WATCHDOG_LABEL"
fi

# Merged code reaches the site by itself: the auto-deploy agent watches main.
# It runs this script with DASHBOARD_INSTALL_AUTO_DEPLOY=0 so it never reloads itself mid-run.
AUTO_DEPLOY_LABEL="com.pirajoke.dashboard-auto-deploy"
AUTO_DEPLOY_PLIST="$HOME/Library/LaunchAgents/$AUTO_DEPLOY_LABEL.plist"
if [[ "${DASHBOARD_INSTALL_AUTO_DEPLOY:-1}" == "1" ]]; then
  mkdir -p "$HOME/Library/Logs/$AUTO_DEPLOY_LABEL"
  sed -e "s|__SCRIPTS_DIR__|$SCRIPTS_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$SRC_DIR/launchd/$AUTO_DEPLOY_LABEL.plist.template" > "$AUTO_DEPLOY_PLIST.tmp"
  plutil -lint "$AUTO_DEPLOY_PLIST.tmp" >/dev/null
  install_launchd_agent "$AUTO_DEPLOY_PLIST.tmp" "$AUTO_DEPLOY_PLIST" "$AUTO_DEPLOY_LABEL"
fi

echo "Dashboard builder deployed to $SCRIPTS_DIR"
