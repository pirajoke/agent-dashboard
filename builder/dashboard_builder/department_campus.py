"""Privacy-safe projection and read-only markup for the department campus."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
import unicodedata


DEPARTMENT_ZONES = {
    "hq": {
        "label": "Центр управления",
        "zone_id": "campus-zone-hq",
        "roles": ("Main Manager", "Coordinator", "Supervisor"),
        "owner_permission_boundary": False,
    },
    "sales": {
        "label": "Sales",
        "zone_id": "campus-zone-sales",
        "roles": ("Market Analyst", "Sales Researcher", "Sales Operator"),
        "owner_permission_boundary": False,
    },
    "development": {
        "label": "Development",
        "zone_id": "campus-zone-development",
        "roles": ("Builder", "Developer", "Tester"),
        "owner_permission_boundary": False,
    },
    "design": {
        "label": "Design",
        "zone_id": "campus-zone-design",
        "roles": ("Designer", "Design Reviewer", "UX Researcher"),
        "owner_permission_boundary": False,
    },
    "infrastructure": {
        "label": "Infrastructure",
        "zone_id": "campus-zone-infrastructure",
        "roles": ("Infrastructure Engineer", "Reliability Analyst", "Operator"),
        "owner_permission_boundary": False,
    },
    "internal": {
        "label": "Internal",
        "zone_id": "campus-zone-internal",
        "roles": ("Internal Analyst", "Knowledge Curator", "Auditor"),
        "owner_permission_boundary": False,
    },
    "finance": {
        "label": "Finance",
        "zone_id": "campus-zone-finance",
        "roles": ("Finance Analyst", "Revenue Analyst", "Bookkeeper"),
        "owner_permission_boundary": True,
    },
}

STATUS_LABELS = {
    "queued": "в очереди",
    "active": "работает",
    "testing": "проверяет",
    "waiting": "ждёт решения",
    "done": "готово",
    "failed": "ошибка",
}

_PUBLIC_EVENT_FIELDS = (
    "event_id",
    "task_id",
    "department_id",
    "department_label",
    "project",
    "agent_id",
    "role",
    "status",
    "updated_at",
    "next_step",
    "evidence_count",
    "ephemeral",
    "zone_id",
)
_FRESH_SECONDS = 30 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_UNSAFE_TEXT = re.compile(
    r"(?:"
    r"\b[a-z][a-z0-9+.-]{1,31}://|"
    r"(?<![A-Za-z0-9])/(?:Users|Volumes|workspace|home|opt|private|var|etc|srv|root|tmp)(?:/[^)\]\s,;]+)+|"
    r"(?<![A-Za-z0-9])[A-Z]:[\\/][^)\]\s,;]+|"
    r"(?<![A-Za-z0-9])\\\\[^\\\s]+\\[^\s]+|"
    r"(?:^|\s)//[^/\s]+/[^\s]+|"
    r"(?<![A-Za-z0-9])(?:\.\.[\\/])+(?:[^\\/\s]+[\\/]?)+|"
    r"(?<![A-Za-z0-9])~[\\/][^\s]+|"
    r"(?<![A-Za-z0-9])\.(?:ssh|aws|gnupg)[\\/][^)\]\s,;]+|"
    r"(?<![A-Za-z0-9])config[\\/](?:credentials?|secrets?|tokens?)(?:\.[^)\]\s,;]+)?|"
    r"\b(?:localhost(?::\d+)?|[A-Za-z0-9.-]+)/(?:private|admin|internal|secrets?)(?:[/?.][^\s]*)?|"
    r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):\d{1,5}(?:/[^\s]*)?|"
    r"\b(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+\.local(?::\d{1,5})?(?:/[^\s]*)?|"
    r"[\"'](?:token|secret)[\"']\s*:\s*[\"'][^\"']+[\"']|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b|"
    r"\bbearer\s+[A-Za-z0-9._~+/-]{12,}|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b|"
    r"\b(?:aws[_ -]?secret[_ -]?access[_ -]?key|client[_ -]?secret|"
    r"refresh[_ -]?token|webhook[_ -]?secret|session[_ -]?token|"
    r"api[_ -]?key|password|passwd|credential|token|secret)\s*[=:]\s*\S+|"
    r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bsk_(?:live|test)_[A-Za-z0-9_-]{16,}|"
    r"\bsk-proj-[A-Za-z0-9_-]{20,}|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}|"
    r"\bxox[baprs]-[A-Za-z0-9-]{20,}|"
    r"\bAIza[0-9A-Za-z_-]{20,}|"
    r"\bAKIA[0-9A-Z]{16}"
    r")",
    re.IGNORECASE,
)
_UNSAFE_ID = re.compile(
    r"^(?:token|secret)[._:-](?=[A-Za-z0-9_.:-]{20,}$)(?=[A-Za-z0-9_.:-]*\d{6,})",
    re.IGNORECASE,
)
_NEUTRAL_TEXT = "Недоступно в публичной сводке"
_BIDI_CONTROLS = frozenset(
    chr(codepoint)
    for codepoint in (
        0x061C,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    )
)


def _utc_now(now: datetime) -> datetime:
    return (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = _strip_unsafe_formatting(normalized)
    if cleaned != normalized:
        return None
    value = cleaned.strip()
    if _UNSAFE_TEXT.search(value) or _UNSAFE_ID.search(value):
        return None
    return value if _SAFE_ID.fullmatch(value) else None


def _strip_unsafe_formatting(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        character
        for character in normalized
        if character not in _BIDI_CONTROLS
        and (
            unicodedata.category(character) not in {"Cc", "Cs", "Cf"}
            or character == "\u200d"
        )
    )


def _bounded_grapheme_text(value: str, limit: int) -> str:
    """Bound text while keeping combining marks and ZWJ emoji sequences together."""
    clusters: list[str] = []
    cluster = ""
    for character in value:
        joins_previous = (
            bool(cluster)
            and (
                character == "\u200d"
                or cluster.endswith("\u200d")
                or bool(unicodedata.combining(character))
                or "VARIATION SELECTOR" in unicodedata.name(character, "")
                or 0x1F3FB <= ord(character) <= 0x1F3FF
            )
        )
        if cluster and not joins_previous:
            clusters.append(cluster)
            cluster = ""
        cluster += character
    if cluster:
        clusters.append(cluster)

    bounded: list[str] = []
    used = 0
    for item in clusters:
        if used + len(item) > limit:
            break
        if item.endswith("\u200d"):
            break
        bounded.append(item)
        used += len(item)
    return "".join(bounded)


def _safe_text(value: object, *, limit: int = 180) -> str:
    if not isinstance(value, str):
        return _NEUTRAL_TEXT
    value = _strip_unsafe_formatting(value)
    value = " ".join(value.strip().split())
    if not value or _UNSAFE_TEXT.search(value):
        return _NEUTRAL_TEXT
    return _bounded_grapheme_text(value, limit)


def _empty_projection(state: str, now: datetime) -> dict[str, Any]:
    return {
        "state": state,
        "generated_at": _utc_now(now).isoformat().replace("+00:00", "Z"),
        "visible_task_count": 0,
        "omitted_task_count": 0,
        "events": [],
        "privacy": "public_projection",
    }


def _validated_event(
    event: object,
    *,
    now: datetime,
) -> tuple[dict[str, Any] | None, str, datetime | None]:
    if not isinstance(event, dict):
        return None, "invalid", None
    department_id = event.get("department_id")
    zone = DEPARTMENT_ZONES.get(department_id)
    if zone is None:
        return None, "invalid", None
    if (
        event.get("department_label") != zone["label"]
        or event.get("zone_id") != zone["zone_id"]
        or event.get("role") not in zone["roles"]
    ):
        return None, "invalid", None
    event_id = _safe_id(event.get("event_id"))
    task_id = _safe_id(event.get("task_id"))
    agent_id = _safe_id(event.get("agent_id"))
    status = event.get("status")
    updated = _parse_time(event.get("updated_at"))
    if (
        event_id is None
        or task_id is None
        or agent_id is None
        or status not in STATUS_LABELS
        or type(event.get("ephemeral")) is not bool
        or event.get("ephemeral") is not True
        or updated is None
    ):
        return None, "invalid", None
    age = (_utc_now(now) - updated).total_seconds()
    if age < 0:
        return None, "invalid", None
    if age > _FRESH_SECONDS:
        return None, "stale", None
    evidence = event.get("evidence_count")
    evidence_count = evidence if type(evidence) is int and evidence >= 0 else 0
    public = {
        "event_id": event_id,
        "task_id": task_id,
        "department_id": department_id,
        "department_label": zone["label"],
        "project": _safe_text(event.get("project"), limit=120),
        "agent_id": agent_id,
        "role": event["role"],
        "status": status,
        "updated_at": updated.isoformat().replace("+00:00", "Z"),
        "next_step": _safe_text(event.get("next_step"), limit=240),
        "evidence_count": evidence_count,
        "ephemeral": True,
        "zone_id": zone["zone_id"],
    }
    return public, "valid", updated


def department_campus_projection(
    events: object,
    *,
    now: datetime,
    max_tasks: int = 3,
) -> dict[str, Any]:
    """Return a strict, fresh public projection of verified pixel events."""
    if not isinstance(events, list):
        return _empty_projection("unavailable", now)
    if not events:
        return _empty_projection("empty", now)

    validated: list[tuple[int, dict[str, Any], datetime]] = []
    saw_stale = False
    for index, raw_event in enumerate(events):
        event, validation_state, updated = _validated_event(raw_event, now=now)
        saw_stale = saw_stale or validation_state == "stale"
        if event is not None and updated is not None:
            validated.append((index, event, updated))
    if not validated:
        return _empty_projection("stale" if saw_stale else "empty", now)

    # Newest update wins for both event id and task+agent identity. Python's
    # stable sort preserves the first source item when timestamps tie.
    deduped: list[tuple[int, dict[str, Any], datetime]] = []
    seen_event_ids: set[str] = set()
    seen_identities: set[tuple[str, str]] = set()
    for item in sorted(validated, key=lambda candidate: candidate[2], reverse=True):
        _, event, _ = item
        identity = (event["task_id"], event["agent_id"])
        if event["event_id"] in seen_event_ids or identity in seen_identities:
            continue
        seen_event_ids.add(event["event_id"])
        seen_identities.add(identity)
        deduped.append(item)
    deduped.sort(key=lambda item: item[0])

    requested = max_tasks if type(max_tasks) is int else 3
    lane_limit = min(3, max(0, requested))
    all_tasks: list[str] = []
    for _, event, _ in deduped:
        if event["task_id"] not in all_tasks:
            all_tasks.append(event["task_id"])
    visible_tasks = set(all_tasks[:lane_limit])
    visible_events = [event for _, event, _ in deduped if event["task_id"] in visible_tasks]
    return {
        "state": "active" if visible_events else "empty",
        "generated_at": _utc_now(now).isoformat().replace("+00:00", "Z"),
        "visible_task_count": len(visible_tasks),
        "omitted_task_count": max(0, len(all_tasks) - len(visible_tasks)),
        "events": [
            {field: event[field] for field in _PUBLIC_EVENT_FIELDS}
            for event in visible_events
        ],
        "privacy": "public_projection",
    }


def _zone_html(department_id: str, zone: dict[str, Any]) -> str:
    boundary = (
        '<span class="campus-owner-boundary" aria-label="Требуется разрешение владельца">'
        "🔒 owner permission</span>"
        if zone["owner_permission_boundary"]
        else ""
    )
    coordinator = (
        """
            <div class="campus-static-manager" data-campus-static-manager="true"
                aria-label="Главный координатор, ожидает задач">
                <span class="campus-manager-sprite" aria-hidden="true"></span>
                <strong class="campus-manager-text">Главный координатор</strong>
                <span class="campus-manager-text">ожидает задач</span>
            </div>"""
        if department_id == "hq"
        else ""
    )
    coordinator_presence = (
        """
            <span class="campus-zone-presence" aria-hidden="true">
                <strong>Главный координатор</strong>
                <span><i></i>ожидает задач</span>
            </span>"""
        if department_id == "hq"
        else ""
    )
    return f"""
        <section class="campus-zone campus-zone-{department_id}" id="{zone['zone_id']}"
            data-department-id="{department_id}" aria-labelledby="{zone['zone_id']}-label">
            <header><h3 id="{zone['zone_id']}-label">{zone['label']}</h3>{coordinator_presence}{boundary}</header>
            {coordinator}
            <div class="campus-furniture" aria-hidden="true"><i></i><i></i><i></i></div>
            <div class="campus-zone-agents" data-campus-zone-agents></div>
        </section>"""


def build_department_campus_html() -> str:
    """Build the static seven-zone campus shell; specialists arrive by safe GET."""
    zones = "".join(_zone_html(department_id, zone) for department_id, zone in DEPARTMENT_ZONES.items())
    details = (
        ("task_id", "Task"),
        ("department", "Department"),
        ("project", "Project"),
        ("role", "Role"),
        ("status", "Status"),
        ("updated_at", "Updated"),
        ("next_step", "Next safe step"),
        ("result", "Result"),
        ("evidence_count", "Evidence"),
    )
    detail_rows = "".join(
        f'<div><dt>{label}</dt><dd data-campus-detail-field="{field}">—</dd></div>'
        for field, label in details
    )
    return f"""
<section class="section department-campus" id="department-campus" aria-labelledby="department-campus-title">
    <div class="section-head campus-head">
        <div class="section-dot" style="background:#e6a23c"></div>
        <div><div class="section-title" id="department-campus-title">Pixel Verse · Кампус отделов</div>
        <div class="campus-subtitle">Проверенные события Главного координатора · только просмотр</div></div>
        <div class="section-count" data-campus-count>0 tasks · 0 agents</div>
        <button class="campus-refresh" type="button" data-campus-refresh aria-label="Обновить кампус">↻</button>
    </div>
    <div class="campus-state" data-campus-state aria-live="polite">Загрузка кампуса…</div>
    <div class="campus-map" aria-label="Семь отделов Pixel Verse">
        <div class="campus-boulevard" aria-hidden="true"></div>
        <div class="campus-route-layer" data-campus-route-layer aria-hidden="true"></div>
        {zones}
        <section class="campus-waypoint campus-test-lab" data-campus-waypoint="test-lab" aria-label="Shared Test Lab">
            <strong>Test Lab</strong><span>shared verification waypoint</span>
            <div class="campus-waypoint-agents" data-campus-waypoint-agents></div>
        </section>
        <section class="campus-waypoint campus-github-station" data-campus-waypoint="github-station" aria-label="Shared GitHub Station">
            <strong>GitHub Station</strong><span>completed work waypoint</span>
            <div class="campus-waypoint-agents" data-campus-waypoint-agents></div>
        </section>
    </div>
    <div class="campus-bottom-grid">
        <section class="campus-task-panel" data-campus-task-panel hidden aria-labelledby="campus-task-title">
            <header class="campus-task-head">
                <strong id="campus-task-title">Task lanes</strong>
                <span>up to 3 verified live routes</span>
            </header>
            <div class="campus-task-lanes" data-campus-task-lanes aria-label="До трёх активных маршрутов задач"></div>
        </section>
        <aside class="campus-details" id="campus-agent-details" hidden aria-labelledby="campus-detail-title">
            <header><div><span>Selected specialist</span><h3 id="campus-detail-title">Read-only details</h3></div>
            <button type="button" data-campus-detail-close aria-label="Закрыть сведения">×</button></header>
            <dl>{detail_rows}</dl>
        </aside>
    </div>
    <span class="campus-status-vocabulary" hidden>
        в очереди · работает · проверяет · ждёт решения · готово · ошибка
        Нет активных задач · Нет свежих данных · Данные временно недоступны
    </span>
</section>"""
