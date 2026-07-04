#!/bin/bash
# Auto-rebuild agent dashboard HTML + deploy to GitHub Pages
# Runs via launchd every 5 minutes

set -euo pipefail

SCRIPTS="$HOME/scripts"
HTML_OUT="$HOME/agent-dashboard.html"
REPO_DIR="$HOME/agent-dashboard"
LOG="$SCRIPTS/dashboard-rebuild.log"

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >> "$LOG"; }

# 1. Auto-sync real usage from Claude/Codex local data.
#    The sync is incremental now, and the dashboard build happens later in this script.
cd "$SCRIPTS"
python3 usage_auto_sync.py --no-rebuild --quiet >> "$LOG" 2>&1 || log "WARN: usage sync failed"

# 1b. Auto-switch mode by quota/availability policy
python3 auto_mode_switch.py >> "$LOG" 2>&1 || log "WARN: auto-switch failed"

# 2. Rebuild HTML
python3 build-agent-dashboard.py >> "$LOG" 2>&1 || { log "ERROR: build failed"; exit 1; }

# 2b. Check for mode-request.json from GitHub Pages dashboard
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git pull --ff-only origin main >> "$LOG" 2>&1 || log "WARN: git pull failed"
    MODE_REQ="$REPO_DIR/mode-request.json"
    if [ -f "$MODE_REQ" ]; then
        NEW_MODE=$(python3 -c "import json; print(json.load(open('$MODE_REQ'))['mode'])" 2>/dev/null)
        if [ -n "$NEW_MODE" ]; then
            ORCH="$HOME/.agent-bridge/orchestrator.json"
            if [ -f "$ORCH" ]; then
                python3 -c "
import json, sys
from datetime import datetime, timezone
orch = json.load(open('$ORCH'))
orch['mode'] = '$NEW_MODE'
orch['changed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
orch['changed_reason'] = 'dashboard-github'
json.dump(orch, open('$ORCH','w'), indent=2)
print(f'Mode set to $NEW_MODE')
" >> "$LOG" 2>&1
                log "MODE: Applied $NEW_MODE from GitHub Pages dashboard"
            fi
            rm -f "$MODE_REQ"
            git add -A && git commit -m "applied mode: $NEW_MODE" --no-gpg-sign 2>/dev/null || true
            git push origin main >> "$LOG" 2>&1 || true
        fi
    fi

    # Check for model-request.json (Per-agent model switcher)
    MODEL_REQ="$REPO_DIR/model-request.json"
    if [ -f "$MODEL_REQ" ]; then
        ORCH="$HOME/.agent-bridge/orchestrator.json"
        if [ -f "$ORCH" ]; then
            python3 -c "
import json
req = json.load(open('$MODEL_REQ'))
orch = json.load(open('$ORCH'))
agent = req.get('agent', '')
model = req.get('model', '')
if agent and model:
    if 'agent_models' not in orch:
        orch['agent_models'] = {}
    orch['agent_models'][agent] = model
    json.dump(orch, open('$ORCH','w'), indent=2)
    print(f'{agent} model set to {model}')
" >> "$LOG" 2>&1
            log "MODEL: Applied from dashboard"
        fi
        rm -f "$MODEL_REQ"
        git add -A && git commit -m "applied model change" --no-gpg-sign 2>/dev/null || true
        git push origin main >> "$LOG" 2>&1 || true
    fi

    # Check for pause-request.json (ON/OFF toggle)
    PAUSE_REQ="$REPO_DIR/pause-request.json"
    if [ -f "$PAUSE_REQ" ]; then
        ORCH="$HOME/.agent-bridge/orchestrator.json"
        if [ -f "$ORCH" ]; then
            python3 -c "
import json
req = json.load(open('$PAUSE_REQ'))
orch = json.load(open('$ORCH'))
orch['paused'] = req.get('paused', False)
from datetime import datetime, timezone
orch['changed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
orch['changed_reason'] = 'dashboard-toggle'
json.dump(orch, open('$ORCH','w'), indent=2)
print(f'Orchestrator paused={req.get(\"paused\", False)}')
" >> "$LOG" 2>&1
        fi
        rm -f "$PAUSE_REQ"
        git add -A && git commit -m "applied pause toggle" --no-gpg-sign 2>/dev/null || true
        git push origin main >> "$LOG" 2>&1 || true
    fi

    # Check for run-request.json (Launch Agents button)
    RUN_REQ="$REPO_DIR/run-request.json"
    if [ -f "$RUN_REQ" ]; then
        log "RUN: Launch agents triggered from dashboard"
        rm -f "$RUN_REQ"
        git add -A && git commit -m "consumed run-request" --no-gpg-sign 2>/dev/null || true
        git push origin main >> "$LOG" 2>&1 || true

        # Determine which executor to run based on current mode
        ORCH="$HOME/.agent-bridge/orchestrator.json"
        CUR_MODE=$(python3 -c "import json; print(json.load(open('$ORCH')).get('mode','claude-codex'))" 2>/dev/null)

        case "$CUR_MODE" in
            claude-claude)
                log "RUN: Launching Claude executor"
                nohup python3 "$SCRIPTS/claude-autonomous-executor.py" >> "$SCRIPTS/claude-executor.log" 2>&1 &
                ;;
            claude-codex|codex-codex)
                log "RUN: Launching light Linear worker"
                nohup python3 "$SCRIPTS/light-linear-worker.py" >> "$SCRIPTS/light-linear-worker.log" 2>&1 &
                ;;
        esac
        log "RUN: Executor launched in background (mode=$CUR_MODE)"
    fi
fi

# 3. Copy to GitHub Pages repo and push
if [ -d "$REPO_DIR/.git" ]; then
    PUBLISH_WT="$(mktemp -d /tmp/agent-dashboard-publish.XXXXXX)"
    cleanup_publish_wt() {
        git -C "$REPO_DIR" worktree remove --force "$PUBLISH_WT" >> "$LOG" 2>&1 || rm -rf "$PUBLISH_WT"
    }
    trap cleanup_publish_wt EXIT

    cd "$REPO_DIR"
    git fetch origin main >> "$LOG" 2>&1 || log "WARN: git fetch failed"
    git worktree add --detach "$PUBLISH_WT" FETCH_HEAD >> "$LOG" 2>&1 || { log "ERROR: publish worktree failed"; exit 1; }
    cp "$HTML_OUT" "$PUBLISH_WT/index.html"
    mkdir -p "$PUBLISH_WT/dashboard-assets"
    cp "$HOME/dashboard-assets/ai-town-32x32folk.png" "$PUBLISH_WT/dashboard-assets/ai-town-32x32folk.png" 2>/dev/null || log "WARN: AI Town sprite asset missing"
    cd "$PUBLISH_WT"

    # Only commit+push if there are actual changes
    if git diff --quiet index.html dashboard-assets 2>/dev/null; then
        log "No changes, skipping push"
    else
        git add index.html dashboard-assets
        git commit -m "auto-update dashboard $(date -u '+%Y-%m-%d %H:%M UTC')" --no-gpg-sign 2>/dev/null || true
        if git push origin HEAD:main >> "$LOG" 2>&1; then
            log "Pushed update to GitHub Pages"
        else
            log "WARN: push failed"
        fi
    fi
else
    log "WARN: $REPO_DIR not found, skipping deploy"
fi
