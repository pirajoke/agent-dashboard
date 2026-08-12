# Canonical Agent Roster — locked acceptance contract

## Scope

Adapt the compact Agent Pipeline surface to the real Pixel Verse operating model. Replace the three permanent technical-stage cards with the exact seven canonical department residents already verified by the Department Campus registry, while preserving concise GitHub history and safe manual read-only pings.

## Canonical roster

The permanent visible roster is exactly:

| Agent ID | Visible name | Department | Ping role |
| --- | --- | --- | --- |
| `COORDINATOR` | Главный координатор | Центр управления | `coordinator` |
| `RESEARCHER` | Исследователь | Sales | `researcher` |
| `BUILDER` | Разработчик | Development | `builder` |
| `DESIGNER` | Дизайнер | Design | `designer` |
| `INFRASTRUCTURE` | Инженер инфраструктуры | Infrastructure | `infrastructure` |
| `VAULT` | Хранитель знаний | Internal | `vault` |
| `ANALYST` | Аналитик | Finance | `analyst` |

`Supervisor` and `Tester` remain ephemeral full-pipeline stages. Legacy aliases such as Editor, Planner, DevOps, Bridge, and Comms map to canonical responsibility and must not create duplicate permanent cards.

## Acceptance criteria

### AC-1 — Exact verified team

- The roster contains every canonical Department Campus resident exactly once and no other permanent agent.
- Each card shows the verified localized name and department.
- All seven cards remain visible when there are zero live events or the status source is stale/unavailable.

### AC-2 — Honest live state

- Default copy is `ожидает задач`; no agent appears active merely because it is configured.
- The roster reads the existing privacy-safe `/api/manager/departments` projection.
- Only an exact matching canonical `agent_id` may change that card's state.
- UI state maps only the public status vocabulary: queued, active, testing, waiting, done, failed.
- Unknown, duplicate, malformed, stale, or unavailable events fail closed and never create a card or fictional activity.
- Dynamic task text, prompt/body/tool output, credentials, local paths, private URLs, and raw provider output never render in the roster.

### AC-3 — Real bounded manual ping for every canonical agent

- Every canonical card has one native `Пинг` button with a 44×44 CSS-pixel minimum target.
- `POST /api/jarvis/pipeline/ping` accepts exactly the seven canonical lowercase ping roles and rejects unknown or legacy aliases.
- The shell path accepts the same exact role set, runs only the selected role with the fixed read-only task, requires a real `PONG`, and preserves the existing auth, busy lock, provider fallback, path-free response, and fail-closed behavior.
- The UI shows `проверяем…` only after server acceptance and `на связи` only after the exact role/run reaches a successful terminal status.

### AC-4 — Compact responsive product UI

- Wide desktop presents the seven agents as a compact four-column grid (four cards, then three) so each sprite/copy/button lane remains readable.
- Intermediate widths reflow to three columns without clipping; widths at or below `640px` use a two-column touch layout.
- At widths at or below `640px`, each card keeps sprite and copy on the first row and moves its ping control onto a full-width second row, so long names are not squeezed by a third fixed button track.
- At 390px, all seven and the collapsed history summary remain reachable without an inner roster scroll or page-level horizontal overflow; the compact HUD remains bounded to at most `640px` high.
- Long Russian names wrap without ellipsis.
- Keyboard focus, disabled/loading/error states, and `prefers-reduced-motion` remain explicit.
- The roster uses the existing Pixel Verse sprites, graphite/walnut/amber/green palette, and component vocabulary.

### AC-5 — GitHub history remains concise and safe

- Completed-task history stays collapsed by default.
- It still renders at most five safe HTTPS `github.com` links with concise descriptions and freshness metadata.

## Out of scope

- Inventing activity, duplicating aliases as agents, free-form prompts, dispatching real work, editing project ownership, installing providers, changing credentials, merge/deploy controls, and exposing private task content.

## Verification

- RED maps the exact roster, idle/live/stale behavior, exact ping allowlists, privacy, responsive geometry, keyboard, reduced motion, and unchanged GitHub history.
- GREEN runs focused roster/ping tests and the full builder suite.
- REFACTOR reviews source-of-truth alignment, duplication, accessibility, and visual density without adding behavior.
- 1440px desktop and 390px production-like browser smoke verify computed geometry and visible copy before any production rollout.
