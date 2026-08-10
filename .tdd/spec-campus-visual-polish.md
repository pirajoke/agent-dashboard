# Department Campus visual polish — locked spec

## Goal

Make canonical project folders feel built into each Pixel Verse room instead of
covering the room and its resident. Preserve the existing honest, read-only
event projection and all twelve canonical projects.

## Acceptance criteria

- **AC-1 — Architectural project rail.** Every department renders exactly one
  room-local project rail with an explicit, validated project count. The rail
  uses that count to place all folders in a single compact row and remains a
  visual part of the room furniture.
- **AC-2 — Clear floor for residents.** Idle residents and the coordinator are
  positioned above the project rail, inside their own room, with the sprite,
  floor shadow, and caption unobstructed by project folders.
- **AC-3 — Readable project labels.** All twelve registered projects retain a
  visible owner-safe label without ellipsis; labels may wrap to two compact
  lines. The registered `MAIN MANAGER` identity keeps its previously approved
  visible label «Координация». The 44px minimum pointer/keyboard target and
  existing focus treatment remain.
- **AC-4 — Honest state hierarchy.** Idle folders stay visually quiet. Only an
  exact matching live event may add the existing live status treatment or
  motion. No fictional task, count, route, or busy state is introduced.
- **AC-5 — Responsive room composition.** At 390px and desktop widths the page
  has no horizontal overflow, every room remains inside the campus viewport,
  and every resident and project rail remains inside its room.
- **AC-6 — Interaction and motion safety.** Existing read-only details,
  keyboard focus return, 44px targets, and `prefers-reduced-motion` behavior
  remain unchanged.

## Edge cases

- **EC-1.** Departments with one, two, or four projects use the same rail
  component without empty fictional folders.
- **EC-2.** Long names such as `PIXELVERSE DASHBOARD` and `UNFINISHED STUFF`
  wrap without escaping their folder.

## Constraints

- Reuse the existing pixel campus background, sprite sheet, palette, and
  semantic markup.
- Do not add dependencies, mutable controls, private data, local paths, or fake
  live activity.
- Preserve the exact canonical registry and public read-only transport.

## Out of scope

- Registry changes, new projects, new agents, backend event changes, outer
  Command Center navigation, merge, deploy, or service restart.
