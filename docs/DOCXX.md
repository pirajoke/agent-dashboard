# DOCXX document monitor

The Documents tab (`?tab=documents`) projects the existing Mac mini intake worker.
It does not run intake, rename files, call a model, or introduce another sync path.

## Data and privacy

`GET /api/docxx` uses the existing strict owner authorization gate, including on
loopback. Anonymous requests return only `owner_required`, before private files
are accessed. Responses use `Cache-Control: no-store`. The state directory is
also blocked from the generic static file handler for GET, HEAD and aliases.

The source is `~/Library/Application Support/DOCXX-intake/`: `status.json`,
`runner.lock`, `journal.json`, `drive-ingress-journal.json` and `config.json`.
An optional private `dashboard-links.json` supplies `guide`, `review`, `catalog`
and `status` links. Keep real IDs and this configuration out of the public repo.
Only validated HTTPS Google Drive/Docs links are exposed to the owner.

The projection exposes bounded operation metadata, never document text, complete
machine paths, tokens or raw error strings. JSON reads reject symbolic links,
nonregular files and files over 4 MiB. At most 100 operation records are returned.

## Honest status

- The held worker lock indicates an active pass. The worker does not publish
  per-document live stages, so the diagram does not invent those stages.
- The last completed pass is distinct from the current observation time.
- A snapshot over 15 minutes old, missing time or future time is stale.
- Unknown queue/catalog counts display a dash, not zero.
- Pending cloud verification is not completion. Historical records are labeled
  and do not guarantee the document's present location.
- Source failures show a warning. Loss of owner access clears visible private data.

The panel polls every five seconds while visible, stops when hidden and ignores
obsolete responses. Unchanged operation rows retain focus and expanded details.
The animation runs only for a fresh snapshot with a confirmed active worker lock;
reduced-motion preferences disable it. Intake itself retains its five-minute
schedule and existing file-watch triggers.

## Gmail entry point

The third input explains importing mail attachments through the connected chat.
This is distinct from background mail monitoring, which is not enabled by adding
the UI or connecting the chat. The page makes no Gmail requests and has no mail
write, send, archive or delete actions. Related pages may be combined only after
their contents establish that they belong to the same document.

The private intake worker may publish `gmail-status.json` next to `status.json`:

```json
{
  "schema_version": 1,
  "producer": "docxx-gmail-intake",
  "state": "ready",
  "monitoring_enabled": true,
  "checked_at": "2026-10-23T12:00:00Z",
  "pending": 0
}
```

This is a contract example, not evidence of activation. A fresh timestamp, exact
schema/producer and boolean `monitoring_enabled: true` are required before `ready`
or `processing` can show automatic monitoring. The accepted source states are
`manual`, `paused`, `ready`, `processing` and `error`. For an enabled worker's
operational states, an older-than-15-minute, invalid or future timestamp becomes
`stale`. Missing status keeps manual import
available without claiming a monitor; malformed or linked files are unavailable.
Gmail counts and freshness are separate from the file intake queue.

The API returns only Gmail `state`, `automatic`, normalized `checked_at`, nullable
`pending`, and a generic `error`. Optional `error_code` accepts `access_unavailable`,
`rate_limited` and `import_failed`; other errors receive a generic explanation.
Accounts, subjects, sender data, attachment names, credentials and raw errors are
never projected. This file uses the same bounded, symlink-rejecting, owner-only
read path as the rest of the monitor. No status file is written by the dashboard.

## Validation and release

Run the builder unittest suite, compileall, live-feed JSON validation and
`git diff --check`. `builder/tests/preview_command_center.py` supplies synthetic
ready, processing (`waiting` fixture), attention, stale, empty, anonymous and
unavailable states. Never present synthetic data as live evidence.

Release requires the repository owner's explicit public-repository and production
authorization. Deploy through the existing reviewed release path; install optional
private links separately on Mini. Verify owner and anonymous API responses,
visible live state, mobile layout, and existing navigation after deployment.
Rollback uses the previous dashboard release; intake sources remain untouched.
