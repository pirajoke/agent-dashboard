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

## Services come back after a reboot

On 2026-10-12 the Mac mini lost power, and after the login launchd left many LaunchAgents
unloaded. `launchd_watchdog.py` (launchd `com.pirajoke.launchd-watchdog`, at login and every
5 minutes, installed by `deploy_to_scripts.sh`) remembers every `com.pirajoke.*` and
`homebrew.mxcl.*` job it has seen loaded and loads back the ones launchd does not have.
It never loads a job it has not seen running, so services that are off stay off.

To stop a service for good, use `launchctl disable gui/$(id -u)/<label>`; the watchdog then
forgets it. A plain `launchctl bootout` is undone within 5 minutes. If auto-deploy rolls back to a
release without the watchdog, its next run removes its own LaunchAgent. State and log:
`~/.agent-bridge/launchd-watchdog/`.

Before the login nothing runs: with FileVault on, the Mac mini waits for the password after a
power loss. If macOS blocks a job under System Settings → General → Login Items & Extensions →
«Allow in the background», the watchdog is blocked too, so that switch must stay on.

## Owner sign-in through Cloudflare Access

On command.meshly.fr the owner no longer needs the owner key in each browser
once a Cloudflare Access application guards the host (Zero Trust → Access
controls → Applications, login by a one-time code to Mark's Gmail or Google
sign-in, policy allowing only his address). Cloudflare then signs every request
it lets through (`Cf-Access-Jwt-Assertion`), and the server
(`dashboard_builder/cloudflare_access.py`) treats a valid token for this
application as the owner: everything is shown, no key, no QR. Whoever the
Access policy lets in is the owner, so keep that policy to Mark alone.

Nothing to configure: the team domain and the application's audience tag come
from Cloudflare's own login redirect for command.meshly.fr, the signing keys
from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, and RS256 is
checked with the standard library. If that redirect can't be read,
`~/.agent-bridge/cloudflare_access.json` (`{"team": "<team>.cloudflareaccess.com",
"aud": "<AUD tag>"}`) names them instead. Writes also need the page itself as
`Origin`. Without Access the owner key works exactly as before.

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
only), then «Хвосты», the loose ends, in the same list (2026-10-13: one list
of what waits on Mark, as he chose). «Изменения» is the infrastructure change
log. Project pages are reached from «Дела» and from the technical details in
«По дням».

## ChatGPT work

Mark builds many projects in ChatGPT (2026-10-12). Two sources reach the day
summaries, both through `daily_work_collector.py` on the MacBook:

- The ChatGPT desktop app works in `~/Documents/ChatGPT/<project>`; those
  sessions are named «ChatGPT · <project>», and chats outside a project (folders
  named by an id or `new-chat`) are grouped as «ChatGPT · без проекта».
- Chats on chatgpt.com and the phone keep no local logs. The data export
  (Settings → Data controls → Export data) is read from `~/ChatGPT-export`
  (or `~/Downloads`, which macOS may keep closed to a launchd job), once per new
  export, into `sessions/chatgpt/<day>.json` and pushed to the Mac mini. Each
  chat is one session: its title is the topic, a few redacted asks and the last
  reply feed the summarizer. ChatGPT projects are named from the export when it
  lists them, else from `chatgpt_projects.json` in the daily-work folder
  (`{"g-p-…": "SHOPIFY"}`), else «ChatGPT · проект <id>». `--no-chatgpt-export`
  switches the import off.

In session tables these show as «ChatGPT»; their time counts with Codex.


## Optional owner project navigation

`GET /api/platform-resources` projects `navigation.command_center` from the existing
Portfolio Registry v2 at `JARVIS_VAULT_ROOT/35-Systems/PORTFOLIO-REGISTRY.json`.
Every request requires the existing strict owner authority (verified Google Access
session or owner token), regardless of Host. Anonymous requests return only an
`owner_required` state without reading the registry. Responses are `no-store`;
raw registry downloads and filesystem aliases remain blocked even for owners.

The optional block has `verified_at` and `platforms`, keyed by existing runtime
card IDs. Each card contains up to eight `resources` (`kind`, `label`, `url`,
`scope`) and an optional short `note`. Kinds are `documents`, `notes`, `code`,
`tasks`; scopes are `current`, `archive`, `upstream`, `reference`. Only HTTPS
GitHub and Google Drive links without credentials, ports, query strings or
fragments are allowed. Invalid entries are isolated; an absent or unreadable
block produces an honest unavailable/not-configured state. Input is bounded to
1 MiB, labels to 120 characters, notes to 400 and URLs to 2048.

Real private links belong in the private registry, never this repository or the
static snapshot. Installing code does not populate the registry. The installed
cards load links on opening the Platforms tab and recheck while it is visible;
failed or superseded checks cannot restore old private links. Per-source daily
collection state is independent of response generation time and is displayed in
Europe/Paris; public source names remain anonymized.

## Private context library

`?tab=context` opens the owner-only transcript and recent project-update view.
The source of truth remains the existing Obsidian vault. This feature neither
changes importers nor writes to source notes or the document Inbox. Source badges
mean records were observed, not that PLAUD, Krisp or Granola is connected.

Run the stdlib collector with explicit private paths (never commit those values):

```sh
python3 builder/context_library_collect.py --vault "$VAULT" --output "$EXPORT_ROOT" --state-dir "$CONTEXT_STATE" --dry-run
python3 builder/context_library_collect.py --vault "$VAULT" --output "$EXPORT_ROOT" --state-dir "$CONTEXT_STATE"
```

The output and private state directories must already exist. State must be outside
Drive and the web document root. Keep the output directory private. The API reads
`~/.agent-bridge/context-library/catalog.json` by default;
`COMMAND_CENTER_CONTEXT_CATALOG` can point to another private catalog. It applies
the existing strict owner check on every request, including loopback. Responses
are no-store. Static GET and HEAD requests cannot access the catalog state directory,
including configured overrides, manifests, aliases and implicit directory indexes.
Public/static HTML contains no notes, private paths or source links.

The collector reads only Markdown from `10-Transcripts`, the three service intake
folders under `00-Inbox`, and the newest 200 update logs. Transcripts are capped
at 2000 and 2 MiB per note. Source dates and file modification times stay separate.
It never invokes a model or the network. A missing vault or previously available source root preserves the last good
catalog; the API marks snapshots older than one hour stale. Read failures are
reported as partial, not healthy completeness. Use one operator-managed Mini job
at a 15-minute interval after verifying its background filesystem permission.
This command does not install or enable a scheduler.

Exports use readable date, title, source and short-ID filenames with a private hash manifest. Existing filenames remain stable after title or date edits. They update managed
files in place, never prune missing notes, and refuse unknown or edited files and
symlinks. A durable private intent lets a retry complete a crash between file publication and manifest commit; it accepts only the exact expected old or generated bytes. Owner edits after interruption remain untouched. Resolve a conflict by comparing the preserved destination manually;
never remove the manifest or force an overwrite. The CSV and recent-update text
are managed too. Do not edit exports; change the original note in Obsidian.
A changed source date does not move an existing export to a second year folder.
No importer state or service authentication is inferred from existing notes.

Validation: `PYTHONPATH=builder python3 -m unittest builder.tests.test_context_library -v`.
Fixtures must be synthetic. Local live collection, private Drive sharing, scheduler
configuration and deployment are separate operator stages.

Manual Krisp/Granola exports can be ingested with `context_library_run.py --config /private/config.json` (or `--dry-run`). The private JSON specifies `vault`, `output`, `state_dir`, and `intake`; all directories must already exist. Only `intake/krisp` and `intake/granola` UTF-8 TXT/MD are read, and canonical notes go to the corresponding `00-Inbox` service folder. Existing source IDs and import hashes prevent repeated notes. Conflicting content is preserved for review. Source exports are never removed. State and locks stay outside data roots. Run only one scheduled writer. This is automatic processing of manually exported files, not an authenticated cloud integration with either service.
