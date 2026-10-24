# Project navigation and source freshness — locked 2026-10-19

Scope: local draft only; no commit, push, deploy, production/configuration changes. Existing public platform directory remains useful without owner data. Existing canonical Portfolio Registry v2 remains the identity/data owner; no second task or document database. Real private links live only in a separately prepared private registry patch outside this public checkout.

Active trace: builder/mac-mini-dashboard/index.html is the installed interface. builder/dashboard_builder/platforms.py generates the alternate/static catalogue. Server GET routing is builder/dashboard-server-m4.py. Daily source projection is dashboard_builder/daily_work.py; installed UI already has mmRenderSources. Tests use standard-library unittest plus existing Node harness conventions.

## Acceptance criteria
- AC-1: Both installed platform catalogue and static renderer name the existing compatible financial/financial-os card JobRadar and route its web action to https://jobradar.meshly.fr/job-radar/. Keep Telegram bot. Accountable OS description identifies French Micro BNC financial/admin work, not personal accountability. Keep existing card IDs and other app routes.
- AC-2: New GET /api/platform-resources uses the existing strict _decision_owner_authorized check on every host; no changes to auth functions. Anonymous or spoofed localhost/Host callers cannot obtain private names/links. Direct GET/HEAD and symlink aliases cannot serve the configured registry file.
- AC-3: For authorized owner, read optional navigation.command_center from the existing Portfolio Registry v2 file at JARVIS_VAULT_ROOT/35-Systems/PORTFOLIO-REGISTRY.json. Shape: {verified_at: ISO date/time, platforms: {<existing runtime platform id>: {resources: [{kind: documents|notes|code|tasks, label: string, url: https URL, scope: current|archive|upstream|reference}], note: optional short string}}}. Runtime platform IDs: financial,mydictionary,health,ai-singularity,context-news,accountable,jarvis,property-os,pixel-agents,closeness-mirror,sushi-parisien,n8n. Only these known IDs and allowlisted fields returned. Project canonical identities are not invented or rewritten by this projection.
- AC-4: Each installed platform card gets an owner resource area. It shows useful link labels and distinguishes archive/upstream/reference from current resources. No resource => honest not-linked state. Loading failure and authorization loss clear any previously displayed private resources and show a readable state. Never include actual private links in static HTML/JS/fixtures.
- AC-5: Daily work sources each expose collected_at plus state/age independently: live through six hours, stale beyond six hours, unknown for missing/invalid/future timestamps, unavailable for explicit source failure. A fresh Mini must not mark stale Pro as fresh; generated_at is never the source timestamp. Preserve existing root compatibility fields and anonymized public machine identities.
- AC-6: Existing source display shows each source's state and readable collection time in Europe/Paris, keeps session-time estimate wording, and handles missing/error data without asserting zero or green.

## Boundaries and failures
- EC-1: Missing file, missing navigation block, malformed JSON/schema, oversized (>1 MiB) or unreadable registry => bounded unavailable/not-configured response, no raw filesystem/error content. Unrelated existing public app links continue working.
- EC-2: Reject executable/file/loopback/private-network URLs, credentials, query/fragments, unapproved domains, control characters, unknown resource kinds/scopes/IDs, invalid field types, and unbounded label/count input. Initial resource hosts allowed: github.com and drive.google.com only. Invalid entries isolated; valid independent entries retained. Labels/notes escaped as text; never executable markup.
- EC-3: Anonymous projection does not read private registry and does not reveal private counts, paths, labels, URLs or errors. Public generated output stays unchanged except verified public JobRadar/Accountable copy correction.
- EC-4: Owner endpoint responses are no-store; error/access-loss render removes stale private links. Keyboard focus, responsive 390px layout and reduced-motion remain usable.
- EC-5: Exactly six hours is live, strictly greater is stale. Missing source timestamps remain unknown even if response generated_at is current.

## Explicit exclusions
No authentication redesign, account changes, service restart, public publication, repository renames, physical folder moves, task migrations, health data contents, or new identities. Existing registry augmentation is a private draft to review; it is not applied to the active vault/runtime in this stage. Do not edit AGENTS/CLAUDE/release scripts.

## Final scope correction after active DOM trace — 19 October

The user clarified private Google access across devices. Production Cloudflare eager-cookie redirects were repaired separately; owner policy unchanged.

- AC-7/8 withdrawn before publication: their legacy Jarvis draft controls do not exist in the installed DOM. The previous tests manufactured absent elements. Do not add those controls or a new owner-session endpoint/polling. Restore only this cycle's edits to legacy auth UI/functions, retaining existing active Google authorization.
- Disposition of cycle-created `builder/tests/test_owner_session.py`: archive it outside the repo with this trace; exclude it from delivered tests. No pre-existing tests may be removed.
- Verify the active paths instead: Google-owner (no stored key) can read strict platform resources and existing owner decisions; anonymous responses show no private resources.
- Review refinements: resource renderer rejects unsafe href independently; delayed earlier success cannot restore private links after newer failure; raw registry access stays blocked even with owner token; malformed UTF-8, deep JSON recursion, malformed ports and whitespace labels fail boundedly; newer invalid/failure machine observations cannot be hidden by older valid history (select current snapshot by declared day, then collection time for same day).
- AC-1 snapshot exception: deterministic replacement of only the public platform catalogue block in root index.html is allowed by existing catalogue parity tests. No owner resources or other generated telemetry changes enter that snapshot.
- The existing platform-order test must forbid network persistence of order while permitting the new read-only GET /api/platform-resources. Replace its broad whole-file regex with precise/executed reorder behavior checks; preserve the local-only-order assertion.
- Browser fixture simulates the public origin flags only in its served HTML and uses synthetic server-side owner status, never live Google credentials or real task creation.
