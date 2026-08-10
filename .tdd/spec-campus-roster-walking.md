# Pixel Verse campus roster and walking — locked specification

## Acceptance criteria

- AC-1: The public campus always renders the five configured core agents: Coordinator, Researcher, Analyst, Vault Keeper, and Builder.
- AC-2: A resident without a verified live event is explicitly labelled `ожидает задач`; walking must not imply active work.
- AC-3: The four non-coordinator residents wander within their own department rooms at native 32×32 pixel scale. The coordinator remains at the control-room workstation.
- AC-4: A verified live event temporarily replaces the matching idle resident instead of rendering a duplicate character.
- AC-5: The coordinator identity plaque is placed with the coordinator inside the room, not beside the department title.
- AC-6: The campus counter distinguishes the known team roster from verified active events.

## Edge criteria

- EC-1: `prefers-reduced-motion: reduce` disables resident and sprite animation.
- EC-2: Empty, stale, and unavailable live payloads preserve the known roster and never invent active task state.
- EC-3: Public rendering remains read-only and does not expose private task or process data.
- EC-4: Resident captions and sprites remain contained at desktop and 390px mobile layouts.

## Out of scope

- Starting agent processes or creating synthetic live events.
- Replacing the existing privacy-safe manager event endpoint.
- Installing or embedding the upstream Pixel Agents runtime.
