# Pixel Verse continuation queue projection — locked specification

Status: **LOCKED for TDD RED**

Base: `agent-dashboard main@84ba6fe32534458ffc857b6f8b38e9d6ec034a7b`

## Goal

Make the existing Department Campus show the real MAIN MANAGER continuation
queue. The Dashboard reads the canonical queue and route registry directly and
projects them into the existing privacy-safe 13-field campus event contract.
The Dashboard is a read-only view: it is not an executor, a dispatcher, or a
second source of project truth.

## Source boundary

- The canonical work source is `continuation-queue.json`, schema version `1`,
  with exactly `version` and `items` at the top level.
- The canonical destination metadata is `agent-routes.json`:

  ```json
  {
    "schema": "main_manager_agent_routes_v1",
    "version": 1,
    "routes": {
      "dictionary-builder": {
        "hostId": "remote-ssh-discovered:maxxs-mac-mini",
        "threadId": "019fdcb4-af7b-7270-9c6d-7d22b4f2a020",
        "project": "MY DICTIONARY",
        "repository": "pirajoke/mydictionary",
        "departmentId": "development",
        "zoneId": "zone-development",
        "agentRole": "BUILDER",
        "enabled": true
      }
    }
  }
  ```

- Queue and registry paths are injected into the server projection boundary.
  Configured queue mode requires both paths. There is no directory scan or
  auto-discovery.
- When queue mode is configured, it is authoritative. Missing, malformed,
  stale, or empty queue state must not be overlaid with Bridge specialists.
- Existing verified Bridge metadata remains the legacy fallback only when
  queue mode is explicitly unconfigured. Queue and Bridge events are never
  combined.

## Strict queue item shape

Each item contains exactly:

`queue_id`, `dedupe_key`, `project`, `repository`, `source_task_id`,
`completed_at`, `evidence_fingerprint`, `decision`, `owner_gate`, `next_step`,
`next_task`, `status`, `claim`, `ack`, and optionally `dispatch` only for a
lifecycle state that permits it.

- `queued`: null `claim` and `ack`; no `dispatch`.
- `claimed`: claim object; null `ack`; no `dispatch`.
- `sending`: claim object, null `ack`, exact dispatch object.
- `delivery_unknown`: claim object, null `ack`, dispatch with an allowlisted
  non-null reason and observation time.
- `active`: claim object, dispatch object, and sent-to-thread acknowledgement.
- `acked` terminal: claim object, optional dispatch for legacy compatibility,
  and an acknowledgement with terminal status and terminal time.
- `acked` owner gate or stop notice: claim object, no dispatch, and the compact
  notice acknowledgement.

Nested objects are strict:

- claim: `claim_id`, `claimer`, `claimed_at`, `lease_expires_at`;
- dispatch: `route_id`, `hostId`, `threadId`, `registry_sha256`,
  `message_fingerprint`, `prepared_at`, `delivery_reason`, `observed_at`;
- base acknowledgement: `reason`, `acked_at`, `thread_id`;
- terminal acknowledgement additionally: `terminal_status`, `terminal_at`;
- next task: `description`, `agent_role`, `project`, `metadata`, where metadata
  contains only `allowed_side_effects`.

Unknown top-level or nested fields, unsafe identities, invalid status/decision
combinations, and queue/route identity mismatches fail closed for the whole
configured snapshot. The browser never receives a partial projection from a
malformed authoritative snapshot.

## Existing public event contract

Every visible queue row maps to exactly these existing 13 fields:

`event_id`, `task_id`, `department_id`, `department_label`, `project`,
`agent_id`, `role`, `status`, `updated_at`, `next_step`, `evidence_count`,
`ephemeral`, `zone_id`.

No route destination, repository, claim, dispatch, acknowledgement, prompt,
task description, side-effect list, fingerprint, path, token, private URL, raw
error, or raw queue data enters the public projection.

## Acceptance criteria

- **AC-01 — direct authoritative projection.** A valid configured queue and
  route registry produce campus events without calling Bridge, a model,
  subprocess, or network service. Queue events are not combined with a valid
  Bridge snapshot.
- **AC-02 — honest lifecycle mapping.** Queue lifecycle maps as follows:
  `queued -> queued`, `claimed|sending|active -> active`,
  `delivery_unknown -> failed`, `acked terminal completed -> done`,
  `acked terminal failed -> failed`, and owner gate -> `waiting`.
- **AC-03 — transition time.** The event timestamp represents the current
  lifecycle transition. Applicable timestamps are selected in this priority:
  terminal time, delivery observation, send preparation, acknowledgement,
  claim time, then source completion time.
- **AC-04 — exact existing public shape.** Projection keeps the existing six
  top-level fields and 13 event fields. Route registry identity maps to the
  existing canonical Department Campus department, resident, role, and campus
  zone. Route `zoneId` is validation metadata and is never exposed in place of
  the existing `campus-zone-*` identifier.
- **AC-05 — maximum three real lanes.** At most the first three distinct queue
  task lanes are visible. Additional valid lanes are omitted and counted in
  `omitted_task_count`.
- **AC-06 — zero-token read-only idle.** Reading and projecting the queue
  performs no subprocess, model/network request, write, dispatch, task
  creation, projection-file creation, or second-ledger mutation. Empty input
  remains empty without starting work.
- **AC-07 — authoritative failure clears agents.** Missing, malformed,
  mismatched, or stale configured queue/route input returns no specialists.
  It never freezes a prior event or falls back to Bridge data.
- **AC-08 — legacy fallback is exclusive.** When both configured paths are
  explicitly absent, the existing verified Bridge projection still works. A
  half-configured source is unavailable, not a fallback.

## Edge and error criteria

- **EC-01:** Several queue items for one route remain distinct lanes by queue
  id; stable queue order decides which first three are shown.
- **EC-02:** Empty valid queue reports empty state and zero omitted work.
- **EC-03:** Disabled routes, duplicate destination pairs, more than one
  enabled route for one `(project, agentRole)`, or ambiguous project fallback
  are invalid.
- **EC-04:** Exact enabled `(project, repository, requested agent role)` wins.
  If absent, exactly one enabled route for the same project and repository is
  allowed as a destination fallback. More than one is ambiguous.
- **EC-05:** A route must use a canonical campus project and matching
  department/zone/resident identity. Unknown project or department cannot
  create a specialist.
- **ERR-01:** Non-object JSON, wrong versions/schema, wrong field sets,
  malformed timestamps, or future transition times return generic unavailable
  or stale state with no partial events.
- **ERR-02:** Unsafe public text is neutralized; unsafe identity fields reject
  the snapshot. Raw host/thread ids and all private queue fields are absent
  even when they contain secret/path-shaped bait.
- **ERR-03:** A transition older than the existing 30-minute campus freshness
  window returns stale state and no events, even when another lower-priority
  timestamp is fresh.

## Constraints and out of scope

- Python standard library and existing Dashboard stack only.
- Reuse `department_campus_projection`; do not add a second ledger or public
  event schema.
- No live repository change, installation, service restart, deployment,
  credential, pairing, Remote, merge, commit, or push in this RED phase.
- Out of scope: sending messages, claiming/releasing work, reconciling delivery,
  changing queue or routes, creating agents, or changing the campus art/UI.
