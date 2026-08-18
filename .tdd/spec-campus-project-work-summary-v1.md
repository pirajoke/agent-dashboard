# Campus project work summary + GitHub Issue v1

Status: LOCKED
Issue: https://github.com/pirajoke/agent-dashboard/issues/34

## Goal

The read-only Pixel Verse Campus project inspector shows a concise description
of the current verified work and a direct GitHub Issue link for owner-view live
tasks, without publishing private task content.

## Acceptance criteria

- AC-01: A live project inspector can render `Над чем работаем` from a bounded,
  privacy-safe `work_summary` value.
- AC-02: A live project inspector can render one keyboard-operable external
  GitHub Issue link whose visible label is `Issue #N`.
- AC-03: Owner-view canonical Bridge tasks derive `work_summary` only from the
  typed metadata `objective`, never from raw `description`, `result`, messages,
  issue bodies, or logs.
- AC-04: Owner-view issue data is accepted only when metadata contains an
  integer `github_issue_number`, a matching `github_issue_url`, and an exact
  `github_repo` identity. The URL must be HTTPS `github.com/{owner}/{repo}/issues/N`
  with no credentials, port, query, or fragment.
- AC-05: Verified MAIN MANAGER pixel events may carry the same owner-only
  fields through the projection after identical validation.
- AC-06: An anonymous public-host `/api/manager/departments` response never
  contains `work_summary`, `issue_url`, or `issue_number`; a view authenticated
  with the existing dashboard owner token may contain those owner-only fields,
  including when accessed through the public host.

## Edge cases

- EC-01: Missing summary or issue data hides only the corresponding row.
- EC-02: Summary text is whitespace-normalized and bounded without breaking
  the existing responsive inspector.
- EC-03: The link opens in a new tab with `rel="noreferrer"` and remains
  read-only and keyboard accessible.

## Errors and privacy

- ERR-01: A mismatched issue number/repository, non-GitHub URL, credentials,
  port, query, fragment, malformed type, or unsafe summary fails closed.
- ERR-02: Raw task `description`, result, prompt/body, local paths, tokens,
  credentials, logs, and private metadata never enter the projection or DOM.
- ERR-03: Existing project details, focus return, Escape close, empty state,
  three-lane cap, and public privacy behavior remain unchanged.

## Constraints

- No new dependency.
- Source changes stay in `builder/`.
- Read-only UI only; no dispatch, edit, merge, deploy, or publication action.
- Draft PR only. Merge and production deployment are separate stages.
