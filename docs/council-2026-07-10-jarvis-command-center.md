# Council Session: 2026-07-10 — Jarvis Command Center

## Council Members

- CTO: architecture, runtime reliability, control flow.
- COO: operational readiness and daily-use risk.
- CPO/UX: clarity, mobile, confidence, evidence.
- Security/Platform: public endpoints, approvals, secret handling.

## Context Snapshot

- Public dashboard: `https://command.meshly.fr/`
- Pixel Agents: `https://pixel-agents.meshly.fr/`
- Runtime host: Mac Mini, repo `/Users/pirajoke/agent-dashboard`.
- Pipeline route: `Supervisor -> Builder -> Tester`.
- Latest deployed commit: `e64c7d3 fix-jarvis-pipeline-secret-gate`.

## Tests Run

### Health

- `command.meshly.fr`: HTTP 200.
- `pixel-agents.meshly.fr`: HTTP 200.
- Mac Mini local dashboard health: `status: ok`.
- Bridge API, Bridge Worker, Bridge Tunnel, Voice Server, Health API: running.
- Claude CLI auth: ready.

### Full Read-Only E2E

- Run: `20260710-100407-9873d7`.
- Final status: `done`.
- Report: `/Users/pirajoke/Library/Logs/jarvis-agent-pipeline/20260710-100407-9873d7.md`.
- Visible report tokens: `1474`.
- Steps: Supervisor `done`, Builder `done`, Tester `done`.

### Vague Task Guard

- Run: `20260710-092019-c06fea`.
- Final status: `needs_input`.
- Meaning: vague prompts stop before Builder and ask for a concrete task.

### Secret Canary

- Public POST without token: `401`.
- Run with fake secret canary: `20260710-100228-d56c2c`.
- Final status: `blocked_secret`.
- Report: `/Users/pirajoke/Library/Logs/jarvis-agent-pipeline/20260710-100228-d56c2c.md`.
- Canary was redacted in public API/status and report.
- Pixel state did not leak the canary.

## What Changed

- Added secret redaction/blocking in `jarvis-agent-pipeline`.
- Added redaction in dashboard backend public text/status responses.
- Added `blocked_secret` UI status and human-readable explanation.
- Tightened `supervisor_needs_input` so normal phrases like "нужно уточнение" inside a report do not falsely stop a valid pipeline.

## Council Verdict

Controlled user test: **GO**.

Daily production use: **NOT YET**.

The system can now be tested by Max in Command Center. It is not yet a fully reliable daily operator because the latest pass is read-only/structural, not a full runtime E2E with real code edits, Bridge dispatch, Telegram completion, Obsidian write, GitHub push, and mobile UX pass.

## Consensus

1. Pixel Agents must remain a visualization layer, not the source of truth.
2. Every run needs a visible `run_id`, exact task, current agent, status, and evidence.
3. `done` must mean "request-vs-result checked", not only "agents finished talking".
4. Public run endpoints must stay token-protected.
5. Secrets must never be pasted into tasks. The real OpenAI key disclosed in chat must be revoked/rotated.

## Next Gates

1. Run three clean tasks from the dashboard:
   - read-only status check;
   - small safe code/test task;
   - vague prompt that returns `needs_input`.
2. Add stronger runtime E2E:
   - `jarvis.selftest`;
   - Bridge dispatch and poll completion;
   - Obsidian write;
   - GitHub push;
   - Telegram visible result.
3. Add explicit statuses:
   - `route_done`;
   - `structural_pass`;
   - `runtime_pass`;
   - `needs_input`;
   - `blocked_secret`;
   - `blocked_usage_limit`;
   - `failed`.
4. Improve UX:
   - mobile layout;
   - pinned Pixel Agents view;
   - compact evidence panel;
   - no stale events after new run.
5. Enforce budget and approval policy, not only display it.

## User Test Script

Open `https://command.meshly.fr/?tab=agents`, unlock with dashboard token, choose `Cheap`, then run:

```text
Проверь статус Jarvis и дай следующий практический шаг. Не меняй файлы.
```

Expected:

- status progresses through Supervisor, Builder, Tester;
- final status becomes `done`;
- Pixel Agents show current movement/history for the run;
- evidence includes report path and request-vs-result check;
- no old backlog context is substituted for the task.
