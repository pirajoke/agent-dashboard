"""Privacy-safe projection and read-only markup for the department campus."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import re
from types import MappingProxyType
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

_CAMPUS_AGENT_DEPARTMENTS = {
    "COORDINATOR": "hq",
    "RESEARCHER": "sales",
    "BUILDER": "development",
    "DESIGNER": "design",
    "INFRASTRUCTURE": "infrastructure",
    "VAULT": "internal",
    "ANALYST": "finance",
}
_SAFE_CAMPUS_PROJECT_NAME = re.compile(r"^[A-Z0-9][A-Z0-9 &+.'-]{0,119}$")
_UNSAFE_CAMPUS_PROJECT_NAME = re.compile(
    r"\b(?:TOKEN|SECRET|CREDENTIAL|PASSWORD|PRIVATE|PROMPT|BODY|TOOL OUTPUT|RAW METADATA)\b"
)
_CAMPUS_PROJECT_RECORDS = (
    {"project": "MAIN MANAGER", "department_id": "hq", "agent_id": "COORDINATOR"},
    {"project": "AI STUDIO", "department_id": "sales", "agent_id": "RESEARCHER"},
    {"project": "MY DICTIONARY", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "ACCOUNTABLE OS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "HEALTH OS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "CONTEXT NEWS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "PIXELVERSE DASHBOARD", "department_id": "design", "agent_id": "DESIGNER"},
    {"project": "JARVIS", "department_id": "infrastructure", "agent_id": "INFRASTRUCTURE"},
    {"project": "GITHUB HYGIENE", "department_id": "infrastructure", "agent_id": "INFRASTRUCTURE"},
    {"project": "SKILLS LIBRARY", "department_id": "internal", "agent_id": "VAULT"},
    {"project": "UNFINISHED STUFF", "department_id": "internal", "agent_id": "VAULT"},
    {"project": "FINANCIAL OS", "department_id": "finance", "agent_id": "ANALYST"},
)


def validate_campus_project_registry(projects: object) -> tuple[MappingProxyType, ...]:
    """Validate and freeze a public project registry without retaining caller data."""
    if not isinstance(projects, (list, tuple)) or not projects:
        raise ValueError("campus project registry must be a non-empty sequence")

    validated: list[MappingProxyType] = []
    seen_projects: set[str] = set()
    expected_fields = ("project", "department_id", "agent_id")
    for record in projects:
        if not isinstance(record, dict) or set(record) != set(expected_fields):
            raise ValueError("campus project records must contain only public identity fields")
        project = record.get("project")
        department_id = record.get("department_id")
        agent_id = record.get("agent_id")
        normalized_project = (
            unicodedata.normalize("NFKC", project)
            if isinstance(project, str)
            else None
        )
        if (
            not isinstance(project, str)
            or not project
            or project != project.strip()
            or normalized_project != project
            or not _SAFE_CAMPUS_PROJECT_NAME.fullmatch(project)
            or _UNSAFE_CAMPUS_PROJECT_NAME.search(project)
            or any(unicodedata.category(character).startswith("C") for character in project)
            or project in seen_projects
            or department_id not in DEPARTMENT_ZONES
            or agent_id not in _CAMPUS_AGENT_DEPARTMENTS
            or _CAMPUS_AGENT_DEPARTMENTS.get(agent_id) != department_id
        ):
            raise ValueError("invalid campus project identity")
        seen_projects.add(project)
        validated.append(
            MappingProxyType(
                {
                    "project": project,
                    "department_id": department_id,
                    "agent_id": agent_id,
                }
            )
        )
    return tuple(validated)


CAMPUS_PROJECTS = validate_campus_project_registry(_CAMPUS_PROJECT_RECORDS)
_CAMPUS_PROJECT_BY_IDENTITY = MappingProxyType(
    {
        (record["project"], record["department_id"], record["agent_id"]): record
        for record in CAMPUS_PROJECTS
    }
)


def campus_project_for_event(event: object) -> MappingProxyType | None:
    """Return the exact registered project identity for a public event, if any."""
    if not isinstance(event, dict):
        return None
    identity = (
        event.get("project"),
        event.get("department_id"),
        event.get("agent_id"),
    )
    if not all(isinstance(value, str) for value in identity):
        return None
    return _CAMPUS_PROJECT_BY_IDENTITY.get(identity)

_CAMPUS_RESIDENT_PROFILES = {
    "COORDINATOR": {
        "name": "Главный координатор",
        "department_id": "hq",
        "aliases": ("coordinator", "main manager", "supervisor", "главный координатор"),
        "sprite_x": "-192px",
        "sprite_step_x": "-224px",
        "sprite_y": "-192px",
        "wandering": False,
        "walk_duration": "0s",
        "walk_delay": "0s",
    },
    "RESEARCHER": {
        "name": "Исследователь",
        "department_id": "sales",
        "aliases": ("researcher", "editor", "sales researcher", "market analyst", "sales operator"),
        "sprite_x": "-96px",
        "sprite_step_x": "-128px",
        "sprite_y": "-192px",
        "wandering": True,
        "walk_duration": "11s",
        "walk_delay": "-4s",
    },
    "BUILDER": {
        "name": "Разработчик",
        "department_id": "development",
        "aliases": (
            "builder",
            "developer",
            "tester",
            "devops",
        ),
        "sprite_x": "-288px",
        "sprite_step_x": "-320px",
        "sprite_y": "-192px",
        "wandering": True,
        "walk_duration": "13s",
        "walk_delay": "-7s",
    },
    "DESIGNER": {
        "name": "Дизайнер",
        "department_id": "design",
        "aliases": ("designer", "design reviewer", "ux researcher"),
        "sprite_x": "-192px",
        "sprite_step_x": "-224px",
        "sprite_y": "-64px",
        "wandering": True,
        "walk_duration": "14s",
        "walk_delay": "-5s",
    },
    "INFRASTRUCTURE": {
        "name": "Инженер инфраструктуры",
        "department_id": "infrastructure",
        "aliases": ("infrastructure", "infrastructure engineer", "reliability analyst", "operator"),
        "sprite_x": "-288px",
        "sprite_step_x": "-320px",
        "sprite_y": "-64px",
        "wandering": True,
        "walk_duration": "15s",
        "walk_delay": "-9s",
    },
    "VAULT": {
        "name": "Хранитель знаний",
        "department_id": "internal",
        "aliases": ("vault", "vault keeper", "internal analyst", "knowledge curator", "auditor"),
        "sprite_x": "0px",
        "sprite_step_x": "-32px",
        "sprite_y": "-64px",
        "wandering": True,
        "walk_duration": "12s",
        "walk_delay": "-2s",
    },
    "ANALYST": {
        "name": "Аналитик",
        "department_id": "finance",
        "aliases": ("analyst", "finance analyst", "revenue analyst", "bookkeeper"),
        "sprite_x": "-96px",
        "sprite_step_x": "-128px",
        "sprite_y": "-64px",
        "wandering": True,
        "walk_duration": "10s",
        "walk_delay": "-6s",
    },
}

CAMPUS_RESIDENTS = tuple(
    {
        "agent_id": agent_id,
        **profile,
    }
    for agent_id, profile in _CAMPUS_RESIDENT_PROFILES.items()
)

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
_OWNER_EVENT_FIELDS = (
    "work_summary",
    "issue_number",
    "issue_url",
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


def _safe_owner_summary(value: object, *, limit: int = 240) -> str | None:
    """Return a bounded owner summary, rejecting rather than repairing unsafe input."""
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value)
    summary = " ".join(normalized.strip().split())
    if (
        not summary
        or _strip_unsafe_formatting(summary) != summary
        or _UNSAFE_TEXT.search(summary)
    ):
        return None
    bounded = _bounded_grapheme_text(summary, limit)
    return bounded or None


def _validated_owner_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Validate optional owner-only fields independently and fail closed."""
    owner_fields: dict[str, Any] = {}
    summary = _safe_owner_summary(event.get("work_summary"))
    if summary is not None:
        owner_fields["work_summary"] = summary

    repo = event.get("github_repo")
    issue_number = event.get("github_issue_number")
    issue_url = event.get("github_issue_url")
    repo_parts = repo.split("/", 1) if isinstance(repo, str) else ()
    github_owner = repo_parts[0] if len(repo_parts) == 2 else ""
    github_name = repo_parts[1] if len(repo_parts) == 2 else ""
    if (
        not isinstance(repo, str)
        or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?",
            github_owner,
        )
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", github_name)
        or github_name in {".", ".."}
        or type(issue_number) is not int
        or issue_number <= 0
        or not isinstance(issue_url, str)
        or issue_url != f"https://github.com/{repo}/issues/{issue_number}"
    ):
        return owner_fields

    owner_fields["issue_number"] = issue_number
    owner_fields["issue_url"] = issue_url
    return owner_fields


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
    owner_view: bool = False,
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
    if owner_view is True:
        public.update(_validated_owner_fields(event))
    return public, "valid", updated


def department_campus_projection(
    events: object,
    *,
    now: datetime,
    max_tasks: int = 3,
    owner_view: bool = False,
) -> dict[str, Any]:
    """Return a strict projection, optionally including validated owner fields."""
    if not isinstance(events, list):
        return _empty_projection("unavailable", now)
    if not events:
        return _empty_projection("empty", now)

    validated: list[tuple[int, dict[str, Any], datetime]] = []
    saw_stale = False
    for index, raw_event in enumerate(events):
        event, validation_state, updated = _validated_event(
            raw_event,
            now=now,
            owner_view=owner_view,
        )
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
            {
                field: event[field]
                for field in _PUBLIC_EVENT_FIELDS + _OWNER_EVENT_FIELDS
                if field in event
            }
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
    manager_presence = ""
    if department_id == "hq":
        manager = _CAMPUS_RESIDENT_PROFILES["COORDINATOR"]
        manager_dom_id = "campus-resident-coordinator"
        manager_presence = f"""
            <div class="campus-zone-presence" data-campus-manager-presence>
                <strong id="{manager_dom_id}-name" data-campus-manager-name>{manager['name']}</strong>
                <span class="campus-zone-presence-status">
                    <i aria-hidden="true"></i>
                    <span id="{manager_dom_id}-status" data-campus-manager-status>ожидает задач</span>
                </span>
            </div>"""
    residents = []
    for resident in CAMPUS_RESIDENTS:
        if resident["department_id"] != department_id:
            continue
        is_coordinator = resident["agent_id"] == "COORDINATOR"
        classes = "campus-resident"
        if resident["wandering"]:
            classes += " is-wandering"
        if is_coordinator:
            classes += " campus-static-manager"
        manager_contract = ' data-campus-static-manager="true"' if is_coordinator else ""
        sprite_class = "campus-resident-sprite"
        if is_coordinator:
            sprite_class += " campus-manager-sprite"
        aliases = "|".join(resident["aliases"])
        resident_dom_id = f"campus-resident-{resident['agent_id'].lower()}"
        style = (
            f"--campus-sprite-x:{resident['sprite_x']};"
            f"--campus-sprite-step-x:{resident['sprite_step_x']};"
            f"--campus-sprite-y:{resident['sprite_y']};"
            f"--campus-walk-duration:{resident['walk_duration']};"
            f"--campus-walk-delay:{resident['walk_delay']}"
        )
        resident_caption = ""
        if not is_coordinator:
            resident_caption = f"""
                <span class="campus-resident-caption">
                    <strong id="{resident_dom_id}-name">{resident['name']}</strong>
                    <span id="{resident_dom_id}-status"><i></i>ожидает задач</span>
                </span>"""
        residents.append(
            f"""
            <div class="{classes}" data-campus-roster-agent="{resident['agent_id']}"
                data-campus-resident-department="{department_id}"
                data-campus-roster-aliases="{aliases}"{manager_contract}
                style="{style}"
                aria-labelledby="{resident_dom_id}-name {resident_dom_id}-status">
                <span class="{sprite_class}" aria-hidden="true"></span>
                {resident_caption}
            </div>"""
        )
    residents_html = "".join(residents)
    department_projects = tuple(
        project
        for project in CAMPUS_PROJECTS
        if project["department_id"] == department_id
    )
    project_folders = []
    for project in department_projects:
        project_name = project["project"]
        agent_name = _CAMPUS_RESIDENT_PROFILES[project["agent_id"]]["name"]
        visible_name = (
            "Координация"
            if project_name == "MAIN MANAGER"
            else project_name
        )
        project_folders.append(
            f"""
            <button class="campus-project-folder" type="button"
                data-campus-project-folder data-campus-project="{escape(project_name)}"
                data-campus-project-label="{escape(visible_name)}"
                data-campus-project-agent="{escape(project['agent_id'])}"
                data-campus-project-department="{escape(department_id)}"
                data-campus-project-agent-label="{escape(agent_name)}"
                data-campus-project-department-label="{escape(zone['label'])}"
                data-campus-project-status="idle"
                aria-controls="campus-project-details" aria-haspopup="dialog"
                aria-expanded="false"
                aria-label="Проект {escape(visible_name)}, {escape(agent_name)}, {escape(zone['label'])}">
                <span class="campus-project-folder-icon" aria-hidden="true"></span>
                <strong>{escape(visible_name)}</strong>
                <span data-campus-project-folder-status>нет активных задач</span>
            </button>"""
        )
    project_folders_html = (
        '<div class="campus-project-shelf campus-project-rail" '
        'data-campus-project-rail '
        f'data-campus-project-count="{len(department_projects)}" '
        f'style="--campus-project-count:{len(department_projects)};" '
        'aria-label="Проекты отдела">'
        + "".join(project_folders)
        + "</div>"
    )
    return f"""
        <section class="campus-zone campus-zone-{department_id}" id="{zone['zone_id']}"
            data-department-id="{department_id}" aria-labelledby="{zone['zone_id']}-label">
            <header><h3 id="{zone['zone_id']}-label">{zone['label']}</h3>{manager_presence}{boundary}</header>
            {residents_html}
            {project_folders_html}
            <div class="campus-furniture" aria-hidden="true"><i></i><i></i><i></i></div>
            <div class="campus-zone-agents" data-campus-zone-agents></div>
        </section>"""


def build_department_campus_html() -> str:
    """Build the known roster plus privacy-safe live-event destinations."""
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
    project_details = (
        ("project", "Проект", False),
        ("department_id", "Отдел", False),
        ("agent_id", "Ответственный агент", False),
        ("status", "Статус", False),
        ("work_summary", "Над чем работаем", True),
        ("issue_url", "GitHub Issue", True),
        ("next_step", "Следующий безопасный шаг", True),
        ("evidence_count", "Подтверждения", True),
    )
    project_detail_rows = []
    for field, label, live_only in project_details:
        row_start = (
            '<div data-campus-project-live-only hidden>'
            if live_only
            else "<div>"
        )
        if field == "issue_url":
            value = (
                '<dd><a data-campus-project-detail-field="issue_url" '
                'data-campus-project-issue-link target="_blank" '
                'rel="noreferrer">—</a></dd>'
            )
        else:
            value = f'<dd data-campus-project-detail-field="{field}">—</dd>'
        project_detail_rows.append(f"{row_start}<dt>{label}</dt>{value}</div>")
    project_detail_rows_html = "".join(project_detail_rows)
    return f"""
<section class="section department-campus" id="department-campus" aria-labelledby="department-campus-title">
    <div class="section-head campus-head">
        <div class="section-dot" style="background:#e6a23c"></div>
        <div><div class="section-title" id="department-campus-title">Pixel Verse · Кампус отделов</div>
        <div class="campus-subtitle">Проверенные события Главного координатора · только просмотр</div></div>
        <div class="section-count" data-campus-count>{len(CAMPUS_RESIDENTS)} в команде · все ожидают задач</div>
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
        <aside class="campus-details campus-project-detail" data-campus-project-detail
            id="campus-project-details" role="dialog" hidden
            aria-labelledby="campus-project-detail-title">
            <header><div><span>Папка проекта</span>
            <h3 id="campus-project-detail-title">Сведения о проекте · только просмотр</h3></div>
            <button type="button" data-campus-project-detail-close aria-label="Закрыть сведения о проекте">×</button></header>
            <dl>{project_detail_rows_html}</dl>
        </aside>
    </div>
    <span class="campus-status-vocabulary" hidden>
        в очереди · работает · проверяет · ждёт решения · готово · ошибка
        Нет активных задач · Нет свежих данных · Данные временно недоступны
    </span>
</section>"""
