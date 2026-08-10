"""Privacy-preserving projection for MAIN MANAGER handoff/status events."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any


EVENT_MAX_AGE = timedelta(hours=6)
EVENT_FUTURE_SKEW = timedelta(minutes=5)

_MANAGER_MARKER_KEYS = {
    "actor",
    "assigned_agent",
    "receiver",
    "sender",
    "source",
    "triggered_by",
}
_QUEUED_STATES = {"pending", "queued", "waiting", "draft", "approved"}
_WORKING_STATES = {"running", "in_progress", "working", "active", "claimed"}
_DONE_STATES = {"done", "complete", "completed", "success", "succeeded"}
_DECISION_STATES = {
    "needs_approval",
    "needs_input",
    "needs_mark_decision",
    "needs_owner",
    "owner_approval",
    "waiting_owner",
    "awaiting_owner",
    "decision_required",
}
_ERROR_STATES = {"failed", "error", "blocked"}
_NEXT_SAFE_STEP = {
    "в очереди": "Ожидать начала работы.",
    "работает": "Дождаться подтверждённого результата.",
    "готово": "Проверить результат перед следующим действием.",
    "нужно решение Марка": "Передать Марку только необходимое решение.",
    "ошибка": "Проверить безопасную причину ошибки.",
}


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalized_marker(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _is_manager_record(record: dict[str, Any]) -> bool:
    meta = _metadata(record.get("metadata", record.get("meta")))
    return any(
        _normalized_marker(source.get(key)) == "MAIN_MANAGER"
        for source in (record, meta)
        for key in _MANAGER_MARKER_KEYS
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_time(record: dict[str, Any]) -> datetime | None:
    for key in ("updated_at", "completed_at", "claimed_at", "created_at", "time"):
        parsed = _parse_time(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _safe_project(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    project = re.sub(r"\s+", " ", value).strip()
    if not project or len(project) > 64:
        return None
    if any(part in project for part in ("/", "\\", "~", "..", ":")):
        return None
    if not re.fullmatch(r"[\w .-]+", project, flags=re.UNICODE):
        return None
    return project


def _project_name(task: dict[str, Any], manager_records: list[dict[str, Any]]) -> str | None:
    candidates: list[Any] = []
    for record in reversed(manager_records):
        candidates.append(_metadata(record.get("metadata", record.get("meta"))).get("project"))
    candidates.extend(
        (
            task.get("project"),
            _metadata(task.get("metadata", task.get("meta"))).get("project"),
        )
    )
    for candidate in candidates:
        project = _safe_project(candidate)
        if project:
            return project
    return None


def _decision_requested(task: dict[str, Any], manager_records: list[dict[str, Any]]) -> bool:
    for record in (task, *manager_records):
        meta = _metadata(record.get("metadata", record.get("meta")))
        for source in (record, meta):
            if source.get("needs_mark_decision") is True or source.get("needs_owner_approval") is True:
                return True
            for key in ("status", "state", "event"):
                value = source.get(key)
                if isinstance(value, str) and value.strip().lower().replace("-", "_") in _DECISION_STATES:
                    return True
    return False


def _mapped_status(task: dict[str, Any], manager_records: list[dict[str, Any]]) -> str | None:
    raw = str(task.get("status") or task.get("state") or "").strip().lower().replace("-", "_")
    if task.get("error") or raw in _ERROR_STATES:
        return "ошибка"
    if _decision_requested(task, manager_records) or raw in _DECISION_STATES:
        return "нужно решение Марка"
    if raw in _DONE_STATES:
        return "готово"
    if raw in _WORKING_STATES:
        return "работает"
    if raw in _QUEUED_STATES:
        return "в очереди"
    return None


def _display_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_main_manager_event(
    task: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, str] | None:
    """Return one allowlisted UI event, or ``None`` for honest idle.

    Qualification uses structured task/message fields only. Prompt, result, error,
    and internal metadata values are never copied into the projection.
    """
    if not isinstance(task, dict):
        return None

    messages = task.get("messages")
    manager_records = [task] if _is_manager_record(task) else []
    if isinstance(messages, list):
        manager_records.extend(
            message
            for message in messages
            if isinstance(message, dict) and _is_manager_record(message)
        )
    if not manager_records:
        return None

    project = _project_name(task, manager_records)
    status = _mapped_status(task, manager_records)
    event_times = [event_time for record in manager_records if (event_time := _record_time(record))]
    if not project or not status or not event_times:
        return None

    event_time = max(event_times)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    age = current_time - event_time
    if age > EVENT_MAX_AGE or age < -EVENT_FUTURE_SKEW:
        return None

    return {
        "project": project,
        "time": _display_time(event_time),
        "status": status,
        "next_safe_step": _NEXT_SAFE_STEP[status],
    }
