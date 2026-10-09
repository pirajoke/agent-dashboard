#!/usr/bin/env bash
# Install the Daily Work and Infra change collectors as launchd agents on this Mac.
#
#   Mac mini (serves Command Center, also collects GitHub):
#     builder/install_daily_work_collector.sh --machine mac-mini --github
#   Any other Mac (sends its session days to the Mac mini over ssh):
#     builder/install_daily_work_collector.sh --machine macbook-pro --push-to maxxs-mac-mini
#
# Daily Work runs every 2 hours, the Infra change log every 10 minutes, both
# at load. Tokenless: no model calls.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${DAILY_WORK_INSTALL_DIR:-$HOME/scripts}"

# Only --machine and --push-to apply to the infra collector; --github is Daily Work only.
INFRA_ARGS=()
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    --machine|--push-to) INFRA_ARGS+=("${args[$i]}" "${args[$((i + 1))]}"); i=$((i + 1)) ;;
  esac
done

mkdir -p "$INSTALL_DIR" "$HOME/.agent-bridge/daily-work" "$HOME/.agent-bridge/infra-changes"
chmod 700 "$HOME/.agent-bridge/daily-work" "$HOME/.agent-bridge/infra-changes"
for script in daily_work_collector.py infra_change_collector.py; do
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

install_agent com.pirajoke.daily-work-collector daily_work_collector.py 7200 "$@"
install_agent com.pirajoke.infra-change-collector infra_change_collector.py 600 ${INFRA_ARGS[@]+"${INFRA_ARGS[@]}"}
