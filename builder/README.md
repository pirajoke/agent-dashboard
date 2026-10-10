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

## «Сегодня»: the first screen

command.meshly.fr opens on «Сегодня»: short news per project for the owner
(`builder/mac-mini-dashboard/index.html`, section `section-today`). Per product
that had work: a one-line lead and news items tagged «Вы» (what Mark asked,
decided or merged) or «Агенты» (what Claude and Codex got done), plus dated
deadlines. Every news item opens that day on the project's page in MAIN MANAGER
with the technical details unfolded. Every project has its own to-do («Задачи
проекта», in the card and on the project page): PRs waiting for Mark, next steps
from the day summaries and open GitHub issues of the project's repos. Products
without work that day are listed under «Остальные проекты». It opens on the
newest day with work and can step back through earlier days.

Data comes from `/api/work/daily?edition=1` (`paper` in
`dashboard_builder/daily_work.py`, owner token only). The text is written by
`daily_work_summarizer.py` on the Mac mini (summaries schema 2: `details` per
product), for today as well, rewritten while the day goes on. Without a summary
the page shows what the sessions were about, never invented text. Without the
owner token it shows only the day's totals.

Technical pages moved to the last tab, «Техника» (machines, services, ports);
MAIN MANAGER keeps the charts, loose ends and the infrastructure change log.
