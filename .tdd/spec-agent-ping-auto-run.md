# Agent Ping Auto-Run — Locked Specification

## Outcome

From the existing seven-card Agent Pipeline, a manual `Пинг` must contact the selected canonical agent, report an honest safe status and next step inline, and automatically start at most one already-approved JARVIS task assigned to that exact agent.

## Acceptance criteria

### AC1 — exact canonical role and real response

- The request body remains exactly one lowercase `role` from: `coordinator`, `researcher`, `builder`, `designer`, `infrastructure`, `vault`, `analyst`.
- The existing authenticated, one-process-at-a-time ping endpoint remains the only browser mutation surface.
- The selected provider must return a valid `PONG` before task discovery or dispatch is attempted.
- Unknown roles, malformed bodies, unavailable provider, timeout, and concurrent ping fail closed.

### AC2 — safe status contract

- Ping status exposes only: run id, exact role, safe state, localized public summary, localized next step, optional public GitHub issue URL/number, `auto_started`, and timestamp.
- Allowed safe states are `checking`, `working`, `idle`, `blocked`, `failed`.
- It never exposes prompts, task/issue body, tool/model output, credentials, environment values, local paths, Bridge task ids, private URLs, or stack traces.
- Missing/malformed runner output becomes a generic `failed` result.

### AC3 — auto-start eligibility

- Auto-start considers only an open GitHub issue that has exactly: `ai-task`, `jarvis:approved`, and one exact `agent:<role>` matching the button.
- `agent:any`, missing role, conflicting role labels, unknown role labels, draft/running/done/failed/cancelled lifecycle labels, unregistered project/repository, stale or dirty context, invalid outcome contract, and ambiguous duplicate candidates do not dispatch.
- When zero eligible tasks exist, return `idle`, `auto_started=false`, and the next step `Нет одобренной задачи для этого агента.`
- When more than one eligible task exists, return `blocked`, dispatch none, and ask to leave exactly one approved task for that agent.

### AC4 — reuse JARVIS transaction

- Agent Dashboard delegates task selection and dispatch to the installed JARVIS runner; it must not implement GitHub/Bridge mutation logic itself.
- The runner reuses `TaskLifecycleService.prepare_execution`, verifies Bridge health, dispatches the execution envelope, and only then transitions the issue to `jarvis:running`.
- Dispatch rejection leaves the issue approved.
- If the issue transition fails after dispatch, the runner cancels that Bridge task and reports `blocked`.
- The envelope role is the exact approved `agent:<role>` and must be one of the seven canonical roles; the project registry default may not silently replace it.
- Existing isolated-worktree, validation, no-deploy, no-publish, no-secret and idempotency guarantees remain intact.

### AC5 — inline product behavior

- Every canonical card keeps one 44px keyboard-operable `Пинг` button.
- The card shows two concise lines: `Статус: …` and `Дальше: …`; long Russian text wraps without clipping.
- Button/status transitions are honest: `Пинг` → `Проверяем…` → `Работает` or back to `Пинг` for idle/blocked/failed.
- A safe GitHub task link is shown only when the runner returns an `https://github.com/` issue URL.
- Existing four/three/two-column responsive geometry, visible focus, reduced-motion behavior, and collapsed maximum-five Git history remain unchanged.

## Edge cases

- Repeated clicks while the selected/global ping is active do not start a second run.
- A role already running an exact Bridge/GitHub task returns `working` and does not dispatch another.
- Stale status polling cannot overwrite a newer run for the same role.
- Private/non-GitHub links are never rendered.

## Out of scope

- Creating or approving tasks.
- Changing project ownership.
- Merge, deploy, restart, install, credentials, permissions, pairing, Remote, publication, payments, or external-account mutation.
