# Command Center owner decisions

The live shell has four main destinations: Machines, Agents, Проекты and
Platforms. Machines nests the unchanged Mac Mini, Air and Pro panels. Existing
`?tab=mac-mini`, `?tab=air` and `?tab=pro` links still select the corresponding
computer. Проекты reuses the existing Platforms directory and its access labels;
it does not infer deployment health from a link.

Agents opens the decision queue. The campus is a separate subview using
`/department-campus.html?view=department`; its department picker shows one of the
seven existing rooms. The standalone campus keeps its original overview. The
existing Agent Pipeline tools and history are available below both subviews.
The Decisions view accepts the existing owner token through “Доступ владельца”.

## Producer contract

Decisions are derived from the newest fresh, verified MAIN MANAGER `status` or
`handoff` snapshot in Bridge task metadata. The snapshot uses the existing
`pixel_events` contract. Only validated `waiting` events become decisions. A
newer event for the same task supersedes an older waiting event. The decision
queue includes all validated blockers within the 100-event snapshot limit,
independently of the campus's three visible task lanes.

An event may include an owner-only `decision` object:

```json
{
  "question": "Какой вариант берём?",
  "reason": "Почему нужен выбор и на каких данных он основан",
  "options": [
    {
      "id": "a",
      "label": "Вариант A",
      "pros": "Преимущества",
      "cons": "Ограничения",
      "summary": "Что будет подготовлено при выборе A",
      "recommended": true
    }
  ]
}
```

One to five options are accepted. IDs must be unique. All four option text
fields are required and validated by the existing owner-summary sanitizer.
Invalid or absent options result in an own-answer field, never invented choices.
Questions are limited to 240 graphemes, reasons to 600, option text to 240.
Canonical Bridge tasks in `blocked`, `waiting`, `needs_input` or `needs_approval`
can also provide a waiting event when no manager snapshot is available.

## Review, confirmation and consumption

`GET /api/manager/decisions` returns `state`, `owner`, `decisions` and `activity`.
Owner requests use the existing `X-Dashboard-Run-Token` on every host. Anonymous
requests receive only the existing privacy-safe activity projection and
`state: owner_required`; they never receive questions, options or responses.

The browser shows a summary after a choice or own answer. Editing the choice or
note clears that review. A changed proposal clears the old choice. Final
confirmation posts to `/api/manager/decisions/respond`:

```json
{
  "task_id": "task-id",
  "revision": "server-provided-sha256",
  "option_id": "a",
  "note": "Дополнение владельца",
  "reviewed": true
}
```

Use `option_id: null` and a nonempty note for an own answer. Notes are at most
500 characters and are sanitized. The server fetches the current proposal again
and compares its complete revision. A changed or completed task returns 409.
The same confirmation is idempotent; a conflicting response for the same
revision also returns 409. Requests require owner authentication and a same
origin when the Origin header is present.

Responses are appended under the existing private Bridge state directory to
`command-center-decisions.jsonl` with mode 0600, file locking and fsync.
Static GET and HEAD requests cannot serve that private state directory,
including the owner token or aliases to it.
`GET /api/manager/decisions/responses` exposes that journal only to the owner
token. MAIN MANAGER can consume this endpoint and deduplicate by task ID and
revision. A recorded revision disappears from the choice queue; a changed
proposal is shown again.

Confirmation records a decision only. It does not dispatch work, invoke a model,
alter a GitHub issue, control a service, merge or deploy. Connecting a manager
consumer to the response journal is a separate integration; the UI does not
claim execution or delivery acknowledgment.

## Verification

Run the existing CI commands from the repository root:

```sh
PYTHONPATH=builder python3 -m unittest discover -s builder/tests -v
python3 -m compileall -q builder
python3 -m json.tool live-feed.json
```

The additional tests cover owner-only projections, complete blocker queues,
changed proposals, malformed requests, journal locking and idempotency, and
frozen preservation of the existing machine panels and runtime controls.
