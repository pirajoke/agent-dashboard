# Common Center platform hub — locked specification

Status: locked on 2026-08-23

## Purpose and design direction

Turn the existing Pixelverse Command Center into **Common Center**, the single
operator launch surface for Mark's active products and administration tools.
The first viewport is a calm graphite switchboard: two visibly prioritised
product lanes followed by a compact active-systems directory. It must feel like
an operating map, not a generic SaaS card grid.

## Acceptance criteria

- **AC-CC-1 — Complete registry.** The canonical registry contains exactly the
  active surfaces requested for this release: JobRadar / Financial OS,
  Lexi (formerly MyDictionary), Health OS, AI Singularity, Context News France,
  Accountable OS, and JARVIS.
- **AC-CC-2 — Priority hierarchy.** JobRadar / Financial OS and Lexi
  are the two primary product lanes. The other five surfaces are visibly
  grouped as active systems without being represented as current product P0s.
- **AC-CC-3 — Useful destinations.** Every surface has at least one real link.
  Financial OS, Lexi admin, AI Singularity, and Accountable OS use their current loopback Mac mini ports. Health OS links to its
  existing HTTPS page. Lexi (@my_dictionnary_tg_bot), JobRadar, Context News (@contextnews_bot), and JARVIS expose
  their verified Telegram links where available.
- **AC-CC-4 — Safe link contract.** Links are limited to explicit HTTPS hosts
  (`t.me`, `health.meshly.fr`) or loopback HTTP (`127.0.0.1`/`localhost`).
  Rendered external links open in a new tab with `noopener noreferrer`. No
  token, credential, query string, fragment secret, raw environment value, or
  private filesystem path is rendered.
- **AC-CC-5 — Common Center identity.** The page title, sidebar brand, first
  navigation item, and first main section identify the product as Common
  Center. Existing Command Center sections remain available below it.
- **AC-CC-6 — Secure-access guidance.** The section clearly distinguishes
  public, Telegram, and private Mac mini destinations and contains one copyable
  SSH tunnel command (to the Mac mini over Tailscale) covering Common Center and every linked loopback port.
- **AC-CC-7 — Responsive and accessible.** Semantic links have visible focus,
  status is not color-only, the hierarchy reflows to one column on narrow
  screens, and motion is removed under `prefers-reduced-motion`.
- **AC-CC-8 — Deployable snapshot.** Both the builder source and the committed
  static `index.html` contain the same Common Center registry and navigation so
  the OVH nginx snapshot works without Mac-mini runtime data.

## Edge cases

- **EC-CC-1.** Health OS may be temporarily unavailable; the hub still renders
  its stable destination without claiming that a static link is a live health
  check.
- **EC-CC-2.** A platform with only a Telegram destination (JARVIS) renders
  correctly without an admin placeholder link.
- **EC-CC-3.** Long labels and action sets wrap without horizontal page
  overflow at 320 CSS pixels and at 200% zoom.

## Error requirements

- **ERR-CC-1.** Duplicate platform IDs, missing required fields, an incorrect
  primary count, or a platform without actions fail registry validation.
- **ERR-CC-2.** Non-loopback HTTP, unapproved HTTPS hosts, credential-bearing
  URLs, and URLs with query strings are rejected before rendering.
- **ERR-CC-3.** Link labels and platform copy are HTML-escaped.

## Constraints and out of scope

- Static HTML/CSS with the existing standard-library Python builder; no new
  dependencies.
- Read-only navigation only. No credentials, deploy controls, payments,
  publishing, destructive actions, or service restarts in the browser.
- No new public exposure of private OVH ports. Access remains through SSH
  forwarding until a separately approved domain/auth/TLS design exists.
- Existing `.impeccable/` and `docs/design/` untracked user files are preserved.

## Revision 2026-10-08

Everything runs on the Mac mini, not OVH (owner decision). MyDictionary was
replaced by the Lexi bot. Private ports now match the Mac mini: Lexi admin
8791, AI Singularity 8790. Context News is reached through its Mac mini bot
@contextnews_bot; the old port 8002 and @croissantfr_bot are not running.
