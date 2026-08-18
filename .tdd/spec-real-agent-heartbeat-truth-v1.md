# Real Agent Heartbeat Truth v1

## Problem

The Department Campus currently treats any fresh lifecycle event as live work,
including terminal `done` and `failed` events, while six idle residents animate
without a running task. Bridge lifecycle timestamps do not prove that an AI
process is still executing.

## Locked criteria

### AC-1 — live state requires a verified heartbeat

- Campus `state=active` and live agent sprites are driven only by fresh,
  verified heartbeat records in `working` state.
- The heartbeat identifies an exact canonical project, its responsible
  canonical agent, a safe run id, a safe session id, and a UTC heartbeat time.
- A valid heartbeat is no older than 45 seconds and is not in the future.

### AC-2 — lifecycle history is not live presence

- Bridge `pending`, `running`, `done`, and `failed` rows do not create live
  Campus agents without a matching verified heartbeat.
- Direct terminal projection events (`done` and `failed`) never produce
  `state=active`, active-agent counts, movement, or live routes.
- Existing completed-task and Git history surfaces remain unchanged.

### AC-3 — exact fail-closed identity

- The heartbeat project must exist in `CAMPUS_PROJECTS` and its `agent_id` must
  equal that project's registered owner.
- Unknown projects/agents, mismatches, unsafe ids, duplicate live identities,
  malformed JSON, missing fields, stale timestamps, and future timestamps are
  omitted without partial or inferred activity.
- Raw task text, prompts, paths, tool output, credentials, and heartbeat file
  contents never enter the public projection.

### AC-4 — honest motion

- All seven persistent residents are static while idle.
- Only a verified live ephemeral agent may hide its matching resident and use
  route/sprite movement.
- Existing keyboard, mobile, and `prefers-reduced-motion` behavior remains.

### AC-5 — JARVIS producer keeps truth fresh only while a provider runs

- `jarvis-pixel-agent-event` stores the canonical project, canonical agent id,
  run id, session id, state, and heartbeat timestamp atomically.
- A `heartbeat` command refreshes an existing working record without changing
  its task/status copy and without posting a synthetic Pixel tool event.
- `jarvis-agent-pipeline` refreshes heartbeat at a bounded interval while the
  Claude/Codex provider process runs, stops the loop afterward, and writes idle
  on completion/failure.

## Error and boundary criteria

- ERR-1: unreadable or malformed heartbeat storage returns no live events.
- ERR-2: a valid heartbeat mixed with a duplicate or identity conflict for the
  same canonical agent fails that identity closed.
- EC-1: exactly 45 seconds old is accepted; older is stale.
- EC-2: terminal Bridge history may remain available elsewhere but never
  changes Campus live counts or motion.

## Constraints

- Public/read-only behavior and owner-field privacy remain unchanged.
- No new dependency, credential, network service, dispatch control, or public
  mutation endpoint.
- Maximum three visible live tasks remains.

## Out of scope

- Codex desktop tasks that do not emit the heartbeat contract.
- Merge, deploy, restart, credentials, permissions, pairing, or Remote changes.
