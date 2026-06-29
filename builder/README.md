# Agent Dashboard Builder Source

This directory is the git-managed source of truth for the Mac Mini dashboard builder.

Runtime location on Mac Mini:

- scripts: `/Users/pirajoke/scripts`
- generated HTML: `/Users/pirajoke/agent-dashboard.html`
- published GitHub Pages checkout: `/Users/pirajoke/agent-dashboard`

Normal source update flow:

```bash
cd /Users/pirajoke/agent-dashboard
builder/deploy_to_scripts.sh
git add builder CLAUDE.md index.html
git commit -m "..."
git push origin main
```

What `deploy_to_scripts.sh` does:

1. Copies `builder/build-agent-dashboard.py` to `~/scripts/`.
2. Copies `builder/dashboard_builder/*.py` to `~/scripts/dashboard_builder/`.
3. Copies `builder/dashboard-assets/` to `~/scripts/dashboard-assets/`.
4. Copies `builder/dashboard-rebuild.sh` to `~/scripts/`.
5. Runs Python compile checks.
6. Runs `python3 build-agent-dashboard.py`.

Publishing still happens through:

```bash
/Users/pirajoke/scripts/dashboard-rebuild.sh
```

Current JARVIS card source:

- `builder/dashboard_builder/jarvis_pipeline.py`
- `builder/dashboard_builder/now.py`
- `builder/dashboard-assets/style.css`
