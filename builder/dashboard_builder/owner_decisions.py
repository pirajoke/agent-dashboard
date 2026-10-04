"""Owner choices for real manager events. Records data; never executes work."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .department_campus import _safe_owner_summary

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024


class DecisionConflict(ValueError):
    """The reviewed proposal changed or already has a different response."""


def _text(value: object, limit: int = 240) -> str:
    return _safe_owner_summary(value, limit=limit) or ""


def _proposal(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"options": []}
    result = {"options": []}
    for key, limit in (("question", 240), ("reason", 600)):
        text = _text(raw.get(key), limit)
        if text:
            result[key] = text
    options = raw.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= 5:
        return result
    seen = set()
    validated = []
    for option in options:
        if not isinstance(option, dict):
            return result
        identity = option.get("id")
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in seen:
            return result
        entry = {"id": identity}
        for key in ("label", "pros", "cons", "summary"):
            text = _text(option.get(key))
            if not text:
                return result
            entry[key] = text
        entry["recommended"] = option.get("recommended") is True
        seen.add(identity)
        validated.append(entry)
    result["options"] = validated
    return result


def decision_projection(campus: dict, proposals: dict, records: list, *, owner: bool, waiting_events: list | None = None) -> dict:
    """Only fresh validated waiting events can become owner decisions."""
    activity = campus.get("events") if isinstance(campus.get("events"), list) else []
    result = {
        "state": campus.get("state", "unavailable"),
        "owner": owner,
        "decisions": [],
        "activity": activity,
    }
    if not owner:
        result["state"] = "owner_required"
        return result
    seen = set()
    for event in waiting_events if waiting_events is not None else activity:
        task_id = event.get("task_id")
        if event.get("status") != "waiting" or task_id in seen:
            continue
        seen.add(task_id)
        proposal = _proposal(proposals.get((task_id, event.get("event_id"), event.get("updated_at"))))
        decision = {
            "task_id": task_id,
            "department": event["department_label"],
            "project": event["project"],
            "question": proposal.get("question") or event.get("work_summary") or "Нужно решение владельца",
            "next_step": event.get("next_step") or "Ответ будет доступен MAIN MANAGER.",
            "options": proposal["options"],
            "reason": proposal.get("reason", ""),
            "updated_at": event["updated_at"],
        }
        digest = hashlib.sha256(json.dumps(decision, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        decision["revision"] = digest
        if any(record.get("task_id") == task_id and record.get("revision") == digest for record in records):
            continue
        result["decisions"].append(decision)
    return result


def reviewed_response(payload: object, decisions: list, *, now: datetime | None = None) -> dict:
    """Bind a reviewed choice to the current complete proposal revision."""
    allowed = {"task_id", "revision", "option_id", "note", "reviewed"}
    if not isinstance(payload, dict) or set(payload) - allowed or payload.get("reviewed") is not True:
        raise ValueError("invalid_review")
    task_id, revision = payload.get("task_id"), payload.get("revision")
    current = next((item for item in decisions if item["task_id"] == task_id and item["revision"] == revision), None)
    if current is None:
        raise DecisionConflict("proposal_changed")
    raw_note = payload.get("note", "")
    if not isinstance(raw_note, str) or len(raw_note) > 500:
        raise ValueError("invalid_note")
    note = _text(raw_note, 500) if raw_note.strip() else ""
    if raw_note.strip() and not note:
        raise ValueError("invalid_note")
    option_id = payload.get("option_id")
    option = next((item for item in current["options"] if item["id"] == option_id), None)
    if option_id is not None and option is None:
        raise ValueError("invalid_option")
    if not option and not note:
        raise ValueError("choice_required")
    return {
        "task_id": task_id,
        "revision": revision,
        "option_id": option_id,
        "summary": option["summary"] if option else "Свой ответ владельца",
        "note": note,
        "record_only": True,
        "recorded_at": (now or datetime.now(timezone.utc)).isoformat(),
    }


class DecisionJournal:
    """Locked, owner-only append journal; duplicate confirmations are idempotent."""

    def __init__(self, path: Path):
        self.path = path

    def _open(self, *, write: bool):
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT if write else os.O_RDONLY
        flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            os.close(fd)
            raise OSError("invalid_journal_permissions")
        return os.fdopen(fd, "r+" if write else "r", encoding="utf-8")

    @staticmethod
    def _read(stream) -> list:
        if os.fstat(stream.fileno()).st_size > _MAX_JOURNAL_BYTES:
            raise OSError("journal_limit")
        stream.seek(0)
        try:
            records = [json.loads(line) for line in stream if line.strip()]
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise OSError("invalid_journal") from exc
        if any(not isinstance(record, dict) or record.get("record_only") is not True for record in records):
            raise OSError("invalid_journal")
        return records

    def read(self) -> list:
        try:
            stream = self._open(write=False)
        except FileNotFoundError:
            return []
        with stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            return self._read(stream)

    def record(self, response: dict) -> dict:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._open(write=True) as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            records = self._read(stream)
            for existing in records:
                if existing.get("task_id") == response["task_id"] and existing.get("revision") == response["revision"]:
                    keys = ("option_id", "summary", "note", "record_only")
                    if all(existing.get(key) == response[key] for key in keys):
                        return existing
                    raise DecisionConflict("already_recorded")
            line = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            if os.fstat(stream.fileno()).st_size + len(line.encode()) > _MAX_JOURNAL_BYTES:
                raise OSError("journal_limit")
            stream.seek(0, os.SEEK_END)
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return response
