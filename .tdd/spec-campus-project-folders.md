# Pixel Verse canonical project folders — locked specification

## Authoritative registry

Exactly these 12 active projects are public campus folders. Each appears once.

| Department | Responsible agent | Project |
| --- | --- | --- |
| hq | COORDINATOR | MAIN MANAGER |
| sales | RESEARCHER | AI STUDIO |
| development | BUILDER | MY DICTIONARY |
| development | BUILDER | ACCOUNTABLE OS |
| development | BUILDER | HEALTH OS |
| development | BUILDER | CONTEXT NEWS |
| design | DESIGNER | PIXELVERSE DASHBOARD |
| infrastructure | INFRASTRUCTURE | JARVIS |
| infrastructure | INFRASTRUCTURE | GITHUB HYGIENE |
| internal | VAULT | SKILLS LIBRARY |
| internal | VAULT | UNFINISHED STUFF |
| finance | ANALYST | FINANCIAL OS |

## Acceptance criteria

- AC-1: All 12 and only these 12 project folders render once in their registered department rooms, including when the live-event payload is empty, stale, or unavailable.
- AC-2: The roster includes idle Designer and Infrastructure Engineer residents in their matching rooms; no resident or folder claims active work without a verified live event.
- AC-3: A verified live event changes status/motion only for the exact matching project and responsible agent. Every other resident and folder remains honestly idle.
- AC-4: Project folders are mouse and keyboard operable. Enter/Space opens one read-only detail surface and Escape closes it with focus return.
- AC-5: Folder detail exposes only project, department, responsible agent, honest status, and—only for a verified matching live event—safe next step and evidence count.
- AC-6: The project-folder presentation reuses the existing campus pixel-art design system and remains usable on desktop and mobile.

## Edge criteria

- EC-1: `prefers-reduced-motion: reduce` disables project and new-resident motion.
- EC-2: Empty, stale, unavailable, malformed, and non-matching live payloads preserve all folders and idle labels.
- EC-3: The locked registry rejects duplicate project names, unknown departments, unknown agents, and agent/department mismatches at build time.
- EC-4: Archived or unverified scanner folders never enter the public campus registry.

## Error and privacy criteria

- ERR-1: Public folder markup, API projection, and detail DOM never contain prompt/body/tool output, credentials, local paths, client/vault/private URLs, raw metadata, or scanner-derived private fields.
- ERR-2: Unknown project or agent values in a live event fail closed and cannot activate any folder or resident.
- ERR-3: Public campus remains strictly read-only: no project mutation controls and no mutating request to the campus endpoint.

## Constraints

- No new dependencies.
- No merge, deployment, restart, install, credential, pairing, or Remote changes.
- Preserve the existing live-event privacy projection, keyboard behavior, mobile layout, and reduced-motion support.

## Out of scope

- Scanning or publishing every vault folder.
- Inventing owners for unverified projects.
- Starting, stopping, or scheduling agent processes.
