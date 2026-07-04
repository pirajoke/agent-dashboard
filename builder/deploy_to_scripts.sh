#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$REPO_DIR/builder"
SCRIPTS_DIR="${DASHBOARD_SCRIPTS_DIR:-$HOME/scripts}"
PUBLIC_ASSETS_DIR="${DASHBOARD_PUBLIC_ASSETS_DIR:-$HOME/dashboard-assets}"

mkdir -p "$SCRIPTS_DIR/dashboard_builder" "$SCRIPTS_DIR/dashboard-assets" "$PUBLIC_ASSETS_DIR"

cp "$SRC_DIR/build-agent-dashboard.py" "$SCRIPTS_DIR/build-agent-dashboard.py"
cp "$SRC_DIR/dashboard-rebuild.sh" "$SCRIPTS_DIR/dashboard-rebuild.sh"
cp "$SRC_DIR/dashboard_builder/"*.py "$SCRIPTS_DIR/dashboard_builder/"
cp "$SRC_DIR/dashboard-assets/style.css" "$SCRIPTS_DIR/dashboard-assets/style.css"
cp "$SRC_DIR/dashboard-assets/script.js" "$SCRIPTS_DIR/dashboard-assets/script.js"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$SCRIPTS_DIR/dashboard-assets/ai-town-32x32folk.png"
cp "$SRC_DIR/dashboard-assets/ai-town-32x32folk.png" "$PUBLIC_ASSETS_DIR/ai-town-32x32folk.png"

chmod +x "$SCRIPTS_DIR/dashboard-rebuild.sh"

cd "$SCRIPTS_DIR"
python3 -m py_compile build-agent-dashboard.py dashboard_builder/*.py
python3 build-agent-dashboard.py

echo "Dashboard builder deployed to $SCRIPTS_DIR"
