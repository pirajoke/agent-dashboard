#!/usr/bin/env bash
# Shared lifecycle for an already linted LaunchAgent candidate.
install_launchd_agent() {
  local candidate="$1" destination="$2" label="$3"
  local domain="gui/$(id -u)" service attempts=0
  service="$domain/$label"

  if launchctl print "$service" >/dev/null 2>&1; then
    if cmp -s "$candidate" "$destination"; then
      rm "$candidate"
      return 0
    fi

    if ! launchctl bootout "$service"; then
      # Another installer may have finished unloading it in the meantime.
      if launchctl print "$service" >/dev/null 2>&1; then
        echo "Failed to unload LaunchAgent $label" >&2
        return 1
      fi
    fi
    # bootout can return before launchd has removed the service. Bootstrapping
    # during that interval fails with "Operation already in progress".
    while launchctl print "$service" >/dev/null 2>&1; do
      if (( attempts >= 50 )); then
        echo "Timed out waiting for LaunchAgent $label to unload" >&2
        return 1
      fi
      sleep 0.2
      attempts=$((attempts + 1))
    done
  fi

  mv "$candidate" "$destination"
  if ! launchctl bootstrap "$domain" "$destination"; then
    echo "Failed to bootstrap LaunchAgent $label" >&2
    return 1
  fi
}
