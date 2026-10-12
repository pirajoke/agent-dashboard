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

## «По дням»: the first screen

Mark (2026-10-11): the day-by-day list is what matters, the rest is not needed
on the first screen. command.meshly.fr opens on «По дням»
(`builder/mac-mini-dashboard/index.html`, section `section-today`): the last 14
days with work, newest first, in the same rows as «По дням» on a project page.
Each day shows its total work time and, per project, Claude's plain-language
bullets for that day; «Технические детали» (Claude/Codex time, sessions, PRs,
infrastructure commands) stay folded, and each project there opens that day on
its project page. The first three days are open. Dated deadlines from the
summaries sit above the list. The other sections (MAIN MANAGER, Agents,
Platforms, Техника) are one small link row at the top; the big navigation shows
only once you are in one of them. On a project page «По дням» comes right after
the title; numbers, the project's to-do, the chart and loose ends are folded
under «Цифры, задачи и график».

Data comes from `/api/work/daily?edition=1` (`feed` and `deadlines` in
`dashboard_builder/daily_work.py`, owner token only). The text is written by
`daily_work_summarizer.py` on the Mac mini, for today as well, rewritten while
the day goes on. Each bullet names what appeared or changed; a project with
nothing concrete is answered empty and kept in the summary's `quiet` list.
Quick looks (under 3 minutes, or sessions with no title, ask or reply, and no
PR) are not sent to Claude and not listed; a day of only those is left out.
A project still waiting for its retelling is only named in one line, never
described with invented text. `PROMPT_VERSION` in the summarizer goes up when
the instructions change, so the last two weeks are rewritten. Without the
owner token the page shows only the newest working day's totals.

Technical pages moved to the last tab, «Техника» (machines, services, ports).

## MAIN MANAGER: what waits on Mark

Mark (2026-10-12): «По дням» and MAIN MANAGER must not show the same thing.
«По дням» says what was done; MAIN MANAGER (`?tab=work`) opens on «Дела», only
what waits on Mark, per project: dated deadlines, next steps from the
project's newest summary of the last 7 days, and PRs ready to merge (drafts
are only counted), nearest deadline first (`todo` in `/api/work/daily`, owner
only). «Хвосты» lists loose ends and «Изменения» the infrastructure change
log. Project pages are reached from «Дела» and from the technical details in
«По дням».
