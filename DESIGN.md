# Pixel Verse Department Campus

## Approved direction

Direction B — Department Boulevard.

- One continuous top-down campus boulevard inside the existing dark Command
  Center shell.
- Exactly seven spatial rooms: HQ, Sales, Development, Design,
  Infrastructure, Internal, and Finance.
- MAIN MANAGER stays at the HQ dispatch desk.
- No more than three real task routes are visible at once.
- A selected ephemeral specialist opens one read-only inspector below the map.
- Finance has a visible but restrained owner-permission threshold.

The approved mock is a composition and atmosphere contract, not a source of
product data. Generated raster references remain local review artifacts and
are intentionally excluded from the first code PR. Names, projects,
timestamps, counts, and status copy in production come only from the
privacy-safe MAIN MANAGER event projection.

## Palette

The campus preserves the existing graphite Command Center identity while
introducing warm, functional spatial wayfinding.

| Role | Value | Use |
| --- | --- | --- |
| Graphite background | `#09090b` | Page and canvas surround |
| Raised charcoal | `#17171c` | Rooms, inspector, elevated controls |
| Warm walnut | `#7b4f32` | Room floors and furniture accents |
| Botanical green | `#4e7a5a` | Calm campus materials and safe active cues |
| Amber | `#e6a23c` | Route, focus, queue, and wayfinding accent |
| Soft off-white | `#f2f0ea` | Primary readable text |

Semantic red and blue remain restrained and are always paired with shape and
text. The new surface uses explicit solid colors rather than decorative
glassmorphism or broad translucent overlays.

## Typography

- Product text: the existing Inter-compatible sans stack.
- Metadata and compact state labels: JetBrains Mono-compatible monospace.
- Fixed `rem` type scale; no fluid product headings.
- Status, next step, and evidence values must remain readable at 200% zoom.

## Mock fidelity inventory

| Visible ingredient | Production treatment |
| --- | --- |
| Graphite Command Center shell | Preserve existing page structure and tokens |
| Continuous boulevard campus | Semantic HTML/CSS layout with responsive reflow |
| Seven distinct department rooms | Native labelled regions with department metadata |
| MAIN MANAGER in HQ | Static labelled marker, excluded from agent/task counts |
| Three route lines | SVG/CSS routes derived from visible privacy-safe tasks |
| Pixel specialists | Existing `ai-town-32x32folk.png` sprite sheet |
| Status badges | CSS shapes plus localized text; never color-only |
| Bottom inspector | Semantic read-only detail surface with focus management |
| Furniture and room identity | CSS geometry and small native decorative elements |
| Queue strip | Real projected task lanes only; no fictional metrics |

No new production raster asset is required. The approved mock remains a design
reference, while live text, rooms, routes, and details stay semantic and
responsive.

## Motion

- Only specialists in `active` or `testing` may move.
- Route movement is transform-based and bounded to the campus canvas.
- Inspector state changes use 150–250 ms ease-out transitions.
- Empty state starts no specialist animation loop.
- `prefers-reduced-motion: reduce` removes route movement and transitions while
  preserving final placement, labels, and controls.

## Interaction and safety

- First release is read-only.
- Native buttons open the same detail surface for pointer, keyboard, and touch.
- Escape/close returns focus to the selected specialist.
- The interface exposes no merge, deploy, credentials, pairing, payment,
  publication, deletion, or dispatch control.
- Dynamic values are rendered through safe text APIs or equivalent escaping.
- Only the strict public event allowlist may reach the browser.

## Do not literalize

- Do not copy placeholder names, projects, evidence counts, or timestamps from
  the mock.
- Do not rasterize interface text or the inspector.
- Do not create permanent idle specialists or decorative fake activity.
- Do not turn departments into identical cards.
- Do not introduce cyberpunk neon, gradient text, glass cards, blue-purple
  gradients, oversized rounded panels, or decorative motion.
