"""Sessions open right now on Mark's Macs, for «Сессии» in Агенты (Mark 2026-10-25).

Each Mac writes ``~/.agent-bridge/live-sessions/<machine>.json`` every minute
(``live_sessions_collector.py``); the Mac mini serves them together to the owner only.
A Mac whose file is older than ``MACHINE_STALE`` is shown as out of touch and its sessions are left out:
they may long be closed.

Mark 2026-10-26: «Ждут тебя» holds only sessions that really need him, and the card says what for.
A finished turn needs him when its last reply ends with a question or asks for a decision or a
permission (``need``); one that just reports the result is ``done``. An offer such as «Если хочешь,
могу…» is not a need.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MACHINE_STALE = timedelta(minutes=10)
# A session with no step for this long folds under «Затихли».
QUIET_AFTER = timedelta(hours=2)
MACHINE_LABELS = {"mac-mini": "Mac mini", "macbook-pro": "MacBook Pro", "macbook-air": "MacBook Air"}
STATES = ("approve", "waiting", "working", "done", "stopped")
NEED_LIMIT = 220
# Words of a reply that ask Mark for something, besides a question mark.
ASK_WORDS = ("подтверд", "разреш", "нужно твоё", "нужно твое", "нужен твой", "нужна твоя", "нужно от тебя",
             "выбери", "реши,", "решай", "ответь", "дай знать", "сливать?", "approve", "permission", "confirm",
             "let me know", "please choose", "need your", "waiting for you")
# The start of an optional offer, which does not need an answer.
OFFER_STARTS = ("если ", "если,", "хочешь,", "могу ", "могу,", "if you", "want me to", "would you like",
                "shall i", "should you", "when you")
LINK_RE = re.compile(r"^(?:https://claude\.ai/code/session_[A-Za-z0-9_-]+|codex://threads/[A-Za-z0-9_.-]+)$")
FIELDS = ("id", "tool", "app", "title", "project", "branch", "started_at", "last_at", "reply", "resume")
SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def ask_of(text: object) -> str | None:
    """The sentence near the end of a reply that asks Mark for something, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    sentences = [part.strip() for part in SENTENCE_RE.split(" ".join(text.split())) if part.strip()]
    for sentence in reversed(sentences[-3:]):
        lowered = sentence.lower().lstrip("«\"'*-— ")
        if lowered.startswith(OFFER_STARTS):
            continue
        if sentence.rstrip("»\"'*) ").endswith("?") or any(word in lowered for word in ASK_WORDS):
            return sentence if len(sentence) <= NEED_LIMIT else sentence[: NEED_LIMIT - 1].rstrip() + "…"
    return None


def machine_label(machine: str) -> str:
    return MACHINE_LABELS.get(machine, machine.replace("-", " ").title())


def projection(directory: Path, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sessions: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("sessions"), list):
            continue
        machine = str(record.get("machine") or path.stem)
        collected = _parse(record.get("collected_at"))
        fresh = collected is not None and now - collected <= MACHINE_STALE
        machines.append({"machine": machine, "label": machine_label(machine), "fresh": fresh,
                         "collected_at": record.get("collected_at")})
        if not fresh:
            continue
        for raw in record["sessions"]:
            if not isinstance(raw, dict) or raw.get("state") not in STATES or raw.get("tool") not in {"claude", "codex"}:
                continue
            last = _parse(raw.get("last_at"))
            if last is None:
                continue
            session = {key: raw.get(key) for key in FIELDS}
            session["machine"] = machine_label(machine)
            state, need = raw["state"], None
            if state == "approve":
                need = raw.get("approval") if isinstance(raw.get("approval"), str) else None
            elif state == "waiting":
                need = ask_of(raw.get("ask")) or ask_of(raw.get("reply"))
                state = "waiting" if need else "done"
            session["state"], session["need"] = state, need
            session["quiet"] = state in {"done", "stopped"} or (state == "waiting" and now - last >= QUIET_AFTER)
            link = raw.get("link")
            session["link"] = link if isinstance(link, str) and LINK_RE.match(link) else None
            sessions.append(session)
    order = {state: index for index, state in enumerate(STATES)}
    sessions.sort(key=lambda s: s["last_at"] or "", reverse=True)
    sessions.sort(key=lambda s: (s["quiet"], order[s["state"]]))
    return {"state": "ready", "sessions": sessions, "machines": machines}
