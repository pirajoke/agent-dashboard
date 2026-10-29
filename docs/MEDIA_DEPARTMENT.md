# Media Department

Owner-only Command Center projection for ai-singularity-news-bot issue #54.
The static HTML contains only a shell. `/api/media` reuses the existing server's
owner authorization; no anonymous metrics/receipt data is embedded in HTML.

Configure in the protected server environment after review:

- `MEDIA_SOURCE_URL`: news service origin (HTTPS or loopback HTTP).
- `MEDIA_EXPORT_TOKEN`: the news service's dedicated read-only token (>=32 chars).
- `MEDIA_NOTIFICATIONS_DB`: optional local Jarvis notification database path.

The server fetches a bounded 128 KiB snapshot with a five-second timeout and no
redirects. It strips unknown top-level aggregate fields and never returns source
configuration or credentials. Missing configuration and upstream failure produce
explicit unavailable states. Data older than five minutes is labelled stale.

The card shows actual Telegram slots/next slot, LinkedIn mirror mode and current
automatic publishing flag, publication totals, scoped editorial costs/rates,
null/unavailable traction metrics, notification status and canonical post links.
The refresh action clears stale private content on loss of owner authentication.
New source settings do not enable auto-publishing, write to the news bot, or
start the Jarvis integration.

Validation performed in the implementation environment: module unit tests, Python
compilation and JavaScript syntax. A real browser render and authenticated host
verification remain necessary before acceptance; this document is not a deploy
receipt. No existing access rules or owner checks are changed.
