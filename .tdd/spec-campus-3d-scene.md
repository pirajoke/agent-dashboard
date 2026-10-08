# Campus 3D scene — locked specification

Status: locked with the first 3D release

## Outcome

The Department Campus gains a low-poly 3D view of the same seven rooms, twelve
project desks and seven residents. The 3D view is a visual mirror of the
existing semantic 2D campus: it reads the state the campus has already rendered
from the public MAIN MANAGER projection and never invents activity. When the
projection is empty, stale or unavailable, every resident stands idle at their
own room and no frame loop runs.

## Acceptance criteria

- AC-1: The campus document ships a native `3D` view toggle (`aria-pressed`) and
  a 3D stage marked `aria-hidden="true"`. Both stay hidden until the browser
  proves WebGL support and the renderer loads, so the 2D campus remains the
  fallback for any failure.
- AC-2: The renderer is the vendored, MIT-licensed `three.module.min.js` served
  same-origin from `/dashboard-assets/`. No CDN or other external origin is
  contacted, and the public file allowlist names only that one new asset.
- AC-3: The 3D block performs no `fetch`, XHR, WebSocket, POST, dispatch or
  model call. Its only inputs are the rendered 2D campus DOM: the campus state,
  project folder status, and live agent buttons.
- AC-4: A character walks only when its 2D live agent button reports
  `data-campus-moving="true"`, which the campus sets solely for new verified
  `active` or `testing` journeys. Every other state is placed without motion.
- AC-5: A new journey visits the MAIN MANAGER desk in HQ first (a short handoff
  showing the public task id in a bubble on both characters), then walks the
  boulevard to its project desk or to Test Lab. `done` work is placed at GitHub
  Station without animation.
- AC-6: Up to three amber task routes mirror the verified task lanes.
- AC-7: Empty, stale and unavailable states return every resident to their own
  room, labelled `ожидает задач`, with no routes and no running frame loop.
- AC-8: Frames are rendered on demand. A frame loop runs only while a verified
  journey or active/testing work is on screen, and never under
  `prefers-reduced-motion: reduce`, where characters are placed directly.
- AC-9: Keyboard and screen reader users keep the semantic 2D controls: in the
  3D view the map is visually clipped, not removed, so folders and agents stay
  focusable, and the 3D view draws a focus ring on the focused object. Pointer
  clicks on 3D labels, desks or characters activate the same 2D control.
- AC-10: Status is never conveyed by colour alone; each 3D status chip carries
  a glyph and the canonical Russian status text.
- AC-11: The chosen view persists per browser when storage is available. The
  single-department iframe (`?view=department`) keeps its 2D room crops.
- AC-12: Live agent buttons expose only already-public projection fields as
  data attributes (agent, department, task, status, project).

## Constraints

- The 2D campus block keeps its existing contract (no animation frames, no
  POST, no dispatch). The 3D code lives in its own `Campus 3D Scene` block.
- Text in the 3D overlay is set with `textContent`, never `innerHTML`.
- Portrait screens rotate the campus a quarter turn so the boulevard runs down
  the screen.

## Out of scope

- Producing MAIN MANAGER events or restoring the live projection.
- Owner actions, editing, or any write path from the 3D view.
- Decorative idle walking or ambient animation.
