#!/usr/bin/env bash
# Install the Daily Work collector as a launchd agent on this Mac.
#
#   Mac mini (serves Command Center, also collects GitHub):
#     builder/install_daily_work_collector.sh --machine mac-mini --github
#   Any other Mac (sends its session days to the Mac mini over ssh):
#     builder/install_daily_work_collector.sh --machine macbook-pro --push-to maxxs-mac-mini
#
# Runs every 2 hours and at load. Tokenless: no model calls.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${DAILY_WORK_INSTALL_DIR:-$HOME/scripts}"
LABEL="com.pirajoke.daily-work-collector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/daily-work-collector"

mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$HOME/.agent-bridge/daily-work"
chmod 700 "$HOME/.agent-bridge/daily-work"
if [[ "$SRC_DIR/daily_work_collector.py" != "$INSTALL_DIR/daily_work_collector.py" ]]; then
  cp "$SRC_DIR/daily_work_collector.py" "$INSTALL_DIR/daily_work_collector.py"
fi
python3 -m py_compile "$INSTALL_DIR/daily_work_collector.py"

python3 - "$PLIST.tmp" "$LABEL" "$INSTALL_DIR/daily_work_collector.py" "$LOG_DIR" "$@" <<'PY'
import plistlib, sys
target, label, script, log_dir, *extra = sys.argv[1:]
plist = {
    "Label": label,
    "ProgramArguments": ["/usr/bin/python3", script, *extra],
    "StartInterval": 7200,
    "RunAtLoad": True,
    "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    "StandardOutPath": f"{log_dir}/stdout.log",
    "StandardErrorPath": f"{log_dir}/stderr.log",
}
with open(target, "wb") as handle:
    plistlib.dump(plist, handle)
PY
plutil -lint "$PLIST.tmp" >/dev/null
mv "$PLIST.tmp" "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Daily Work collector installed: $PLIST"
