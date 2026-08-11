# Compact Agent Pipeline — locked acceptance contract

## Scope

Replace the oversized white Agent Pipeline console with a compact Pixel Verse HUD. Keep the existing GitHub-backed completed-task history, reduce it to concise safe links, and add an explicit manual ping for each real pipeline role.

## Acceptance criteria

### AC1 — Compact Pixel Verse presentation

- The section remains inside the Agents tab and keeps the existing `Agent Pipeline` identity.
- Supervisor, Builder, and Tester are presented as one compact role strip using the Pixel Verse graphite/walnut/amber/green visual language, not three large white cards.
- Each role shows its name, one short Russian description, an honest status, and one native button labelled `Пинг`.
- The panel is materially shorter than the current 340px console: no always-open large history cards and no verbose task composer.

### AC2 — Concise GitHub history

- Completed-task history remains sourced from `/api/jarvis/pipeline/history`.
- History is collapsed by default and renders at most five compact rows.
- Each row contains only a safe GitHub link, a short result description, and concise timestamp/freshness metadata.
- Client rendering accepts links only from `https://github.com/`; malformed or non-GitHub URLs are rendered as plain text.
- No prompt/body/tool output, credential, local path, client data, private URL, or raw report tail is displayed.

### AC3 — Honest role-specific ping

- `POST /api/jarvis/pipeline/ping` accepts exactly one role from `supervisor`, `builder`, or `tester`.
- Public requests require the existing dashboard run token; missing/invalid auth returns 401 and starts no subprocess.
- Unknown roles, extra caller-supplied prompt/task text, oversized/malformed bodies, missing runtime prerequisites, and duplicate busy pings fail closed.
- A successful request starts exactly the selected role in a fixed, server-generated, read-only ping mode; it must not start the full Supervisor → Builder → Tester route.
- The server response and report use no local paths in the public JSON response.
- The UI changes a role to `проверяем…` only after the server accepts the request, polls the existing authenticated status endpoint, and reports `на связи` only after a completed agent response. Errors remain visible and do not masquerade as activity.

### AC4 — Accessible responsive behavior

- Ping controls are keyboard-operable, have visible focus, and have at least a 44×44 CSS-pixel target.
- Buttons are disabled while their ping is running and re-enabled on terminal result/error.
- At desktop and mobile widths the role strip/history do not create page-level horizontal scrolling.
- At `prefers-reduced-motion: reduce`, ping/status motion is disabled without hiding state.

## Edge cases

- Empty GitHub history keeps a compact empty message.
- Stale history stays labelled stale; it never looks live.
- A second ping while another ping process is active returns 409 and launches nothing.
- Status polling with an invalid run id continues to use the existing fail-closed status validation.

## Out of scope

- General task composition, free-form prompts, changing project ownership, editing GitHub history, deploy/restart, merge, credentials, and changes to the Department Campus surface.

## Verification

- RED tests cover compact DOM/CSS, safe history links, exact role allowlist, auth, fixed prompt, one-role launch, duplicate protection, status transitions, mobile, focus, and reduced motion.
- GREEN runs the targeted tests plus the complete builder test suite.
- Final desktop and mobile browser screenshots verify real computed geometry and no overflow.
