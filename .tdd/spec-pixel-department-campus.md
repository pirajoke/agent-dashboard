# Locked TDD Spec — Pixel Verse Department Campus

Status: locked for RED after visual-direction approval

## Outcome

Command Center renders one read-only Pixel Verse campus with the seven canonical
department zones and only fresh, verified, privacy-safe ephemeral agent events
emitted by MAIN MANAGER. It never invents work, exposes owner-only actions, or
spends model tokens for idle visuals.

## Public contract

- Exactly seven departments: `hq`, `sales`, `development`, `design`,
  `infrastructure`, `internal`, and `finance`.
- MAIN MANAGER remains a static headquarters marker; specialists are ephemeral.
- The public projection keeps only these event fields:
  `event_id`, `task_id`, `department_id`, `department_label`, `project`,
  `agent_id`, `role`, `status`, `updated_at`, `next_step`, `evidence_count`,
  `ephemeral`, and `zone_id`.
- Bridge metadata remains the only source. A snapshot is accepted only when the
  same metadata object contains an allowlisted manager event marker, normalized
  MAIN MANAGER provenance, and a `pixel_events` list.
- The browser consumes one public read-only GET projection. There is no new
  persistence layer and no mutation endpoint.

## Acceptance criteria

### AC-1 — Seven canonical zones

The campus always renders exactly the seven canonical department ids and
labels. Finance is visibly identified as a separate owner-permission boundary.
Unknown departments never create an eighth zone.

### AC-2 — Read-only surface

The campus contains no editable fields or controls for dispatch, merge, deploy,
credentials, pairing/Remote, payments, publication, deletion, or any other
mutation. Allowed interactions are safe detail open/close and GET refresh.

### AC-3 — Verified source only

Only the newest valid snapshot with the manager event and provenance markers in
the same metadata object is accepted. Ordinary Bridge tasks, split markers,
simulation events, and raw task content create no specialist.

### AC-4 — Honest lifecycle

Canonical states render as:

- `queued` → `в очереди`
- `active` → `работает`
- `testing` → `проверяет`
- `waiting` → `ждёт решения`
- `done` → `готово`
- `failed` → `ошибка`

Only active and testing specialists may move. Every state is also expressed by
text and an accessible cue, never by color or motion alone.

### AC-5 — Maximum three task lanes

The projection includes events belonging to at most the first three distinct
task ids, even when a larger limit is requested. Support agents for those tasks
may render without consuming extra task lanes. Omitted distinct-task count is
reported honestly.

### AC-6 — Correct department placement

Every valid specialist renders only in its emitted canonical zone. Cross-
department support agents occupy their own zones. Department id, label, zone id,
and role must agree with the public registry or the event is rejected.

### AC-7 — No synthetic workforce

A specialist appears only for a fresh event with `ephemeral=true` and disappears
for empty, stale, or unavailable state. One static idle MAIN MANAGER marker may
remain in HQ and is excluded from task and agent counts.

### AC-8 — Privacy-safe details

An agent trigger opens exactly nine display fields: task id, department,
project, role, status, updated time, next safe step, safe result, and evidence
count. The result is derived only from the canonical public status; raw task
bodies, prompts, results, errors, messages, tool output, file contents, local
paths, tokens, credentials, private URLs, and evidence text never enter the
public payload, HTML, attributes, title text, or detail surface. Dynamic text
uses safe text APIs or equivalent escaping.

### AC-9 — Keyboard and touch parity

Every agent/detail trigger is a native button with an accessible name,
`aria-controls`, and synchronized `aria-expanded`. Enter, Space, and click open
the same detail surface; Escape/close returns focus to the trigger. There is no
hover-only information. Touch targets are at least 44×44 CSS pixels.

### AC-10 — Reduced motion

`prefers-reduced-motion: reduce` removes campus animation and transitions and
prevents animation-frame movement while preserving final zone placement, state
text, details, and interactions.

### AC-11 — Complete UI states

Loading shows all seven zones, an `aria-live` message, and no specialists.
Empty says `Нет активных задач`; stale says `Нет свежих данных`; upstream or
parse failure shows a generic unavailable message. Stale/error refresh clears
previous agents instead of freezing fictional work.

### AC-12 — Freshness and deduplication

Snapshot and event times are validated against injectable `now`. The freshness
window is 30 minutes, equal to two normal manager pulses. Stale, malformed, or
future events never display as active. The newest valid event wins for duplicate
task+agent identity, with stable source-order tie-breaking.

### AC-13 — Zero-token idle

Projection and rendering perform no model call, subprocess, write, background
worker, or dispatch. Empty render starts no specialist animation loop. Refresh
may perform only the existing read-only GET flow and never POST or create work.

### AC-14 — Existing Dashboard integration

The generated Dashboard contains one department campus, its public GET hook,
responsive layout, and safe details. Existing Agent Theater may coexist but is
not a second source and must not duplicate specialists. Workshop and Command
Center continue serving their current diagnostic responsibilities.

### AC-15 — Visible boulevard journeys and destinations

The campus exposes one visible central boulevard, a task-lane strip capped at
three distinct real task ids, and two shared non-department waypoints: Test Lab
and GitHub Station. Active specialists visibly travel from the HQ/boulevard
entry to their emitted department desk; testing specialists travel to Test Lab;
done specialists are placed at GitHub Station without animation. Queued,
waiting, failed, and done states remain stationary. Routes and destinations are
derived only from canonical status and registry metadata, never prompt text.
Reduced-motion mode places characters directly at the destination.

### AC-16 — Bounded read-only live refresh

After the initial load, the campus refreshes from the same public GET endpoint
on a bounded 15-second interval while the page is visible. It performs no POST,
model call, dispatch, or task creation. Unavailable or stale refreshes clear
specialists immediately, and repeated initialization does not create duplicate
timers.

## Edge cases

- EC-1: empty events → honest empty state, zero counts, all zones idle.
- EC-2: requested lane limit below one → zero visible; above three → three.
- EC-3: several agents for one task use one lane; duplicate event ids dedupe.
- EC-4: unknown or mismatched department, label, zone, or role is rejected.
- EC-5: boolean, negative, or malformed evidence becomes zero; safe
  nonnegative integers survive; evidence bodies never survive.
- EC-6: missing/unknown status never becomes active.
- EC-7: stale refresh removes previously active DOM agents.
- EC-8: safe text is length-bounded without breaking Unicode; unsafe
  URL/path/secret-shaped text fails closed to a neutral value or rejection.
- EC-9: newest valid task+agent update wins; ties preserve source order.
- EC-10: mobile layout has no horizontal page overflow and keeps every zone and
  detail surface reachable.
- EC-11: task-lane labels use only the already-sanitized public task id, preserve
  source order, and never exceed three lanes.
- EC-12: shared Test Lab and GitHub Station are waypoints, not eighth or ninth
  departments and never change the seven-zone count.

## Error handling

- ERR-1: non-object Bridge payload or non-list `pixel_events` fails closed with
  no partial specialists.
- ERR-2: source failure returns a generic unavailable response without internal
  URL, path, token, credential, or traceback.
- ERR-3: unsafe source strings are neutralized before public output; high-risk
  identity or registry mismatch drops the event.
- ERR-4: the public output is a strict allowlist; extra and nested input keys do
  not survive.
- ERR-5: no verified same-metadata MAIN marker yields honest empty state.
- ERR-6: malformed/future time, non-ephemeral event, or invalid status cannot
  produce a moving specialist.

## Constraints

- Python standard library and the existing static JavaScript/CSS stack only.
- Deterministic injectable time; no new dependency or persistence.
- Existing Bridge metadata is the sole event source.
- Public GET only; no owner actions in the first release.
- Browser polling is limited to the read-only campus GET every 15 seconds and
  pauses while the document is hidden.
- WCAG 2.2 AA target and mandatory browser QA for keyboard, touch, responsive,
  reduced-motion, and focus-return behavior.

## Out of scope

Actual task execution, agent spawning, merge, deploy, restart, installation,
credentials, pairing/Remote, payments, publication, deletion, owner write
controls, a new event database, fictional idle specialists, and redesign of
unrelated Command Center sections.
