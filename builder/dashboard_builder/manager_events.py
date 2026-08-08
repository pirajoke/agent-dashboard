"""Privacy-safe projection of live Bridge metadata for the Pixel MAIN MANAGER."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


MANAGER_STATES = (
    "в очереди",
    "работает",
    "готово",
    "нужно решение Марка",
    "ошибка",
)

PROJECT_STATIONS = {
    "JARVIS": {"id": "jarvis", "x": 14, "y": 23},
    "MyDictionary": {"id": "mydictionary", "x": 35, "y": 17},
    "Context News": {"id": "context-news", "x": 61, "y": 17},
    "Financial OS": {"id": "financial-os", "x": 84, "y": 24},
    "AI Studio": {"id": "ai-studio", "x": 86, "y": 49},
    "Accountable OS": {"id": "accountable-os", "x": 82, "y": 77},
    "GitHub Hygiene": {"id": "github-hygiene", "x": 59, "y": 83},
    "Skills Library": {"id": "skills-library", "x": 34, "y": 82},
    "Unfinished Stuff": {"id": "unfinished-stuff", "x": 13, "y": 72},
}

SAFE_NEXT_STEPS = {
    "wait_for_start": "Дождаться запуска задачи.",
    "wait_for_result": "Дождаться следующего подтверждённого статуса.",
    "verify_evidence": "Проверить evidence и следующий безопасный шаг.",
    "mark_decision": "Марк принимает решение по следующему gated-шагу.",
    "inspect_failure": "Проверить ошибку без изменения production.",
}
NEUTRAL_NEXT_STEP = "Проверить безопасный статус проекта перед следующим действием."

_IDLE = {"active": False, "state": "idle", "station": None, "details": None}
_STALE_AFTER_SECONDS = 6 * 60 * 60
_ALLOWED_EVENT_TYPES = {"handoff", "status"}
_STATUS_LABELS = {
    "pending": "в очереди",
    "queued": "в очереди",
    "draft": "в очереди",
    "running": "работает",
    "in_progress": "работает",
    "working": "работает",
    "active": "работает",
    "done": "готово",
    "complete": "готово",
    "completed": "готово",
    "success": "готово",
    "succeeded": "готово",
    "blocked": "нужно решение Марка",
    "waiting": "нужно решение Марка",
    "needs_input": "нужно решение Марка",
    "needs_approval": "нужно решение Марка",
    "failed": "ошибка",
    "error": "ошибка",
}
_STATE_NEXT_CODES = {
    "в очереди": "wait_for_start",
    "работает": "wait_for_result",
    "готово": "verify_evidence",
    "нужно решение Марка": "mark_decision",
    "ошибка": "inspect_failure",
}
_PROJECT_ALIASES = {
    "jarvis": "JARVIS",
    "mydictionary": "MyDictionary",
    "mydictionnary": "MyDictionary",
    "contextnews": "Context News",
    "financialos": "Financial OS",
    "aistudio": "AI Studio",
    "grachevaistudio": "AI Studio",
    "accountableos": "Accountable OS",
    "githubhygiene": "GitHub Hygiene",
    "skillslibrary": "Skills Library",
    "unfinishedstuff": "Unfinished Stuff",
}


def _idle() -> dict[str, Any]:
    return dict(_IDLE)


def _project_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _parse_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def project_manager_event(event: object, *, now: datetime) -> dict[str, Any]:
    """Return an allowlisted view of one real Bridge handoff/status event."""
    if not isinstance(event, dict):
        return _idle()
    if event.get("event_type") not in _ALLOWED_EVENT_TYPES:
        return _idle()

    canonical_project = _PROJECT_ALIASES.get(_project_key(event.get("project")))
    state = _STATUS_LABELS.get(str(event.get("status") or "").strip().lower())
    updated = _parse_time(event.get("updated_at"))
    if not canonical_project or not state or updated is None:
        return _idle()

    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_seconds = (current.astimezone(timezone.utc) - updated).total_seconds()
    if age_seconds < -300 or age_seconds > _STALE_AFTER_SECONDS:
        return _idle()

    metadata = event.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if "next_safe_step" in metadata:
        next_code = str(metadata.get("next_safe_step") or "")
        next_step = SAFE_NEXT_STEPS.get(next_code, NEUTRAL_NEXT_STEP)
    else:
        next_step = SAFE_NEXT_STEPS[_STATE_NEXT_CODES[state]]

    return {
        "active": True,
        "state": state,
        "station": dict(PROJECT_STATIONS[canonical_project]),
        "details": {
            "project": canonical_project,
            "time": str(event.get("updated_at")),
            "status": state,
            "next_step": next_step,
        },
    }
