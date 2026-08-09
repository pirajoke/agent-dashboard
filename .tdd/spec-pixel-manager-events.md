# Pixel MAIN MANAGER event projection

Locked scope: render a privacy-safe, fresh projection of existing Dashboard/JARVIS/Bridge metadata inside Agent Theater. Do not create or persist a second event stream.

## Acceptance criteria

- AC-1: A fresh allowlisted handoff/status event maps to one of exactly five user-facing states: `в очереди`, `работает`, `готово`, `нужно решение Марка`, `ошибка`.
- AC-2: A fresh mapped event moves the `MAIN MANAGER` sprite to the station assigned to its allowlisted target project.
- AC-3: Selecting the sprite/event exposes exactly four safe detail fields: project, time, mapped status, and next safe step.
- AC-4: Existing Dashboard/JARVIS/Bridge task metadata is the only source; no synthetic event or second persistence channel is introduced.
- AC-5: Motion communicates mapped state and retains the existing Pixel Verse visual language.

## Edge criteria

- EC-1: Missing, unknown, malformed, or stale events render honest idle and do not imply active work.
- EC-2: Unknown project identifiers do not move the manager to an invented station.
- EC-3: `prefers-reduced-motion` disables movement animation while preserving state and position.

## Error and privacy criteria

- ERR-1: Prompt/body/result/error/tool output, secrets, credentials, and local client/vault paths never enter the public manager projection or detail UI.
- ERR-2: Unsafe or non-allowlisted next-step values fail closed to a neutral safe fallback.

## Out of scope

- No merge, install, runtime deploy, production change, credentials, Remote/pairing, or publication of private data.
- No new database, event log, dependency, or simulated work. A read-only sanitized projection endpoint over the existing Bridge feed is allowed when needed to keep unsafe source fields out of the browser.
