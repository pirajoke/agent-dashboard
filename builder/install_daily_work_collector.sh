#!/usr/bin/env bash
# Install the Daily Work and Infra change collectors as launchd agents on this Mac.
#
#   Mac mini (serves Command Center, also collects GitHub and writes the
#   plain-language day summaries with the Claude Code CLI signed in there):
#     builder/install_daily_work_collector.sh --machine mac-mini --github --summaries
#   Any other Mac (sends its session days to the Mac mini over ssh):
#     builder/install_daily_work_collector.sh --machine macbook-pro --push-to maxxs-mac-mini
#
# Daily Work runs every 2 hours, the Infra change log every 10 minutes, both
# at load. Both are tokenless. With --summaries, the day summarizer runs every
# 3 hours and calls Claude only for finished days whose activity changed.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${DAILY_WORK_INSTALL_DIR:-$HOME/scripts}"

# Only --machine and --push-to apply to the infra collector; --github is Daily Work only;
# --summaries is for this script.
INFRA_ARGS=()
COLLECTOR_ARGS=()
SUMMARIES=0
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    --summaries) SUMMARIES=1 ;;
    --machine|--push-to)
      INFRA_ARGS+=("${args[$i]}" "${args[$((i + 1))]}")
      COLLECTOR_ARGS+=("${args[$i]}" "${args[$((i + 1))]}")
      i=$((i + 1)) ;;
    *) COLLECTOR_ARGS+=("${args[$i]}") ;;
  esac
done

mkdir -p "$INSTALL_DIR" "$HOME/.agent-bridge/daily-work" "$HOME/.agent-bridge/infra-changes"
chmod 700 "$HOME/.agent-bridge/daily-work" "$HOME/.agent-bridge/infra-changes"
SCRIPTS=(daily_work_collector.py infra_change_collector.py)
if [[ "$SUMMARIES" == "1" ]]; then
  SCRIPTS+=(daily_work_summarizer.py)
  # The summarizer groups days by product with the dashboard's own code.
  mkdir -p "$INSTALL_DIR/dashboard_builder"
  if [[ "$SRC_DIR/dashboard_builder" != "$INSTALL_DIR/dashboard_builder" ]]; then
    cp "$SRC_DIR/dashboard_builder/"*.py "$INSTALL_DIR/dashboard_builder/"
  fi
fi
for script in "${SCRIPTS[@]}"; do
  if [[ "$SRC_DIR/$script" != "$INSTALL_DIR/$script" ]]; then
    cp "$SRC_DIR/$script" "$INSTALL_DIR/$script"
  fi
  python3 -m py_compile "$INSTALL_DIR/$script"
done

install_agent() {
  local label="$1" script="$2" interval="$3"
  shift 3
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  local log_dir="$HOME/Library/Logs/$label"
  mkdir -p "$log_dir"
  python3 - "$plist.tmp" "$label" "$INSTALL_DIR/$script" "$log_dir" "$interval" "$@" <<'PY'
import plistlib, sys
target, label, script, log_dir, interval, *extra = sys.argv[1:]
plist = {
    "Label": label,
    "ProgramArguments": ["/usr/bin/python3", script, *extra],
    "StartInterval": int(interval),
    "RunAtLoad": True,
    "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    "StandardOutPath": f"{log_dir}/stdout.log",
    "StandardErrorPath": f"{log_dir}/stderr.log",
}
with open(target, "wb") as handle:
    plistlib.dump(plist, handle)
PY
  plutil -lint "$plist.tmp" >/dev/null
  mv "$plist.tmp" "$plist"
  launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "Installed $label: $plist"
}

install_agent com.pirajoke.daily-work-collector daily_work_collector.py 7200 ${COLLECTOR_ARGS[@]+"${COLLECTOR_ARGS[@]}"}
install_agent com.pirajoke.infra-change-collector infra_change_collector.py 600 ${INFRA_ARGS[@]+"${INFRA_ARGS[@]}"}
if [[ "$SUMMARIES" == "1" ]]; then
  install_agent com.pirajoke.daily-work-summarizer daily_work_summarizer.py 10800
fi
