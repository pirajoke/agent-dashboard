# MAIN MANAGER ↔ project-agent visualization

Locked: 2026-08-08

## Acceptance criteria

- **AC-01 — explicit source:** Only a Bridge task or message whose structured metadata explicitly identifies `MAIN_MANAGER` can produce a manager event. The project comes only from the structured task/metadata project field.
- **AC-02 — truthful mapping:** The public visualization maps source state to exactly one of: `в очереди`, `работает`, `готово`, `нужно решение Марка`, `ошибка`.
- **AC-03 — minimum details:** A projected event exposes exactly `project`, `time`, `status`, and `next_safe_step`. Prompt/description/result/error/messages, secrets, repository paths, and vault paths never appear in the projection or click details.
- **AC-04 — movement:** A fresh projected event creates a project station and positions the MAIN MANAGER sprite at that station. Without a fresh event, the sprite stays at its home position and the UI says it is idle.
- **AC-05 — motion semantics:** Movement and sprite animation communicate the mapped state. `prefers-reduced-motion` disables movement and animation without hiding state.

## Edge and error criteria

- **EC-01 — stale event:** An otherwise valid event older than six hours is not projected.
- **EC-02 — unsafe project:** Missing, path-like, or malformed project values are rejected rather than displayed.
- **ERR-01 — unavailable source:** Bridge failure returns a generic unavailable response with no internal error detail and the UI falls back to honest idle.

## Out of scope

- No task creation, approval, retry, cancellation, merge, deploy, installation, credentials, or Remote/pairing.
- No changes to the separate dirty Pixel Agents checkout.
- No simulated or demo event in production data.
