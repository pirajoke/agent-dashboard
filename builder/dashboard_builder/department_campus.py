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

_QUEUE_TOP_LEVEL_FIELDS = frozenset({"version", "items"})
_QUEUE_ITEM_FIELDS = frozenset(
    {
        "queue_id",
        "dedupe_key",
        "project",
        "repository",
        "source_task_id",
        "completed_at",
        "evidence_fingerprint",
        "decision",
        "owner_gate",
        "next_step",
        "next_task",
        "status",
        "claim",
        "ack",
    }
)
_QUEUE_ID_FIELDS = (
    "dedupe_key",
    "project",
    "repository",
    "source_task_id",
    "completed_at",
    "evidence_fingerprint",
    "decision",
    "owner_gate",
    "next_step",
    "next_task",
)
_CLAIM_FIELDS = frozenset(
    {"claim_id", "claimer", "claimed_at", "lease_expires_at"}
)
_DISPATCH_FIELDS = frozenset(
    {
        "route_id",
        "hostId",
        "threadId",
        "registry_sha256",
        "message_fingerprint",
        "prepared_at",
        "delivery_reason",
        "observed_at",
    }
)
_ACK_BASE_FIELDS = frozenset({"reason", "acked_at", "thread_id"})
_ACK_TERMINAL_FIELDS = _ACK_BASE_FIELDS | {"terminal_status", "terminal_at"}
_NEXT_TASK_FIELDS = frozenset({"description", "agent_role", "project", "metadata"})
_NEXT_TASK_METADATA_FIELDS = frozenset({"allowed_side_effects"})
_ROUTES_TOP_LEVEL_FIELDS = frozenset({"schema", "version", "routes"})
_ROUTE_FIELDS = frozenset(
    {
        "hostId",
        "threadId",
        "project",
        "repository",
        "departmentId",
        "zoneId",
        "agentRole",
        "enabled",
    }
)
_QUEUE_STATUSES = frozenset(
    {"queued", "claimed", "sending", "delivery_unknown", "active", "acked"}
)
_QUEUE_DECISIONS = frozenset({"auto_continue", "owner_gate", "stop"})
_DELIVERY_UNKNOWN_REASONS = frozenset(
    {
        "tool_timeout",
        "tool_exception",
        "send_tool_timeout",
        "send_tool_error",
        "delivery_unconfirmed",
    }
)
_REPOSITORY_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_QUEUE_ID = re.compile(r"^mmq_[0-9a-f]{64}$")


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


def _strict_object(value: object, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"invalid {label} fields")
    return value


def _strict_version(value: object) -> bool:
    return type(value) is int and value == 1


def _strict_time(value: object, label: str) -> datetime:
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError(f"invalid {label} timestamp")
    return parsed


def _strict_private_id(value: object, label: str) -> str:
    safe = _safe_id(value)
    if safe is None or safe != value:
        raise ValueError(f"invalid {label}")
    return safe


def _strict_repository(value: object) -> str:
    if not isinstance(value, str) or _REPOSITORY_ID.fullmatch(value) is None:
        raise ValueError("invalid repository identity")
    return value


def _strict_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


def _strict_public_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid {label}")
    normalized = _strip_unsafe_formatting(value)
    if normalized != unicodedata.normalize("NFKC", value) or _UNSAFE_TEXT.search(normalized):
        raise ValueError(f"unsafe {label}")
    public = _safe_text(normalized, limit=240)
    if public == _NEUTRAL_TEXT:
        raise ValueError(f"unsafe {label}")
    return public


def _validated_route_registry(routes_data: object) -> dict[str, dict[str, Any]]:
    root = _strict_object(routes_data, _ROUTES_TOP_LEVEL_FIELDS, "route registry")
    if (
        root.get("schema") != "main_manager_agent_routes_v1"
        or not _strict_version(root.get("version"))
        or not isinstance(root.get("routes"), dict)
    ):
        raise ValueError("invalid route registry schema")

    validated: dict[str, dict[str, Any]] = {}
    destinations: set[tuple[str, str]] = set()
    project_roles: set[tuple[str, str]] = set()
    for raw_route_id, raw_route in root["routes"].items():
        route_id = _strict_private_id(raw_route_id, "route id")
        route = _strict_object(raw_route, _ROUTE_FIELDS, "route")
        if route.get("enabled") is not True:
            raise ValueError("disabled route is not a live destination")
        host_id = _strict_private_id(route.get("hostId"), "route host")
        thread_id = _strict_private_id(route.get("threadId"), "route thread")
        project = route.get("project")
        repository = _strict_repository(route.get("repository"))
        department_id = route.get("departmentId")
        agent_role = route.get("agentRole")
        zone_id = route.get("zoneId")
        project_record = _CAMPUS_PROJECT_BY_IDENTITY.get(
            (project, department_id, agent_role)
        )
        if project_record is None or zone_id != f"zone-{department_id}":
            raise ValueError("route does not match the canonical campus identity")

        destination = (host_id, thread_id)
        project_role = (project, agent_role)
        if destination in destinations or project_role in project_roles:
            raise ValueError("ambiguous route registry")
        destinations.add(destination)
        project_roles.add(project_role)
        validated[route_id] = {
            "route_id": route_id,
            "hostId": host_id,
            "threadId": thread_id,
            "project": project,
            "repository": repository,
            "departmentId": department_id,
            "agentRole": agent_role,
        }
    return validated


def _validated_next_task(value: object, *, project: str) -> dict[str, Any]:
    task = _strict_object(value, _NEXT_TASK_FIELDS, "next task")
    if task.get("project") != project:
        raise ValueError("next task project mismatch")
    description = task.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 4000:
        raise ValueError("invalid task description")
    role = _strict_private_id(task.get("agent_role"), "agent role")
    if role not in _CAMPUS_AGENT_DEPARTMENTS:
        raise ValueError("unknown agent role")
    metadata = _strict_object(
        task.get("metadata"), _NEXT_TASK_METADATA_FIELDS, "next task metadata"
    )
    side_effects = metadata.get("allowed_side_effects")
    if not isinstance(side_effects, list) or not side_effects:
        raise ValueError("invalid allowed side effects")
    seen: set[str] = set()
    for side_effect in side_effects:
        checked = _strict_private_id(side_effect, "allowed side effect")
        if checked in seen:
            raise ValueError("duplicate allowed side effect")
        seen.add(checked)
    return task


def _validated_claim(value: object, *, now: datetime) -> dict[str, Any]:
    claim = _strict_object(value, _CLAIM_FIELDS, "claim")
    _strict_private_id(claim.get("claim_id"), "claim id")
    _strict_private_id(claim.get("claimer"), "claimer")
    claimed_at = _strict_time(claim.get("claimed_at"), "claim")
    lease_expires_at = _strict_time(claim.get("lease_expires_at"), "lease")
    if claimed_at > now or lease_expires_at < claimed_at:
        raise ValueError("invalid claim interval")
    return claim


def _validated_dispatch(
    value: object,
    *,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    dispatch = _strict_object(value, _DISPATCH_FIELDS, "dispatch")
    _strict_private_id(dispatch.get("route_id"), "dispatch route id")
    _strict_private_id(dispatch.get("hostId"), "dispatch host")
    _strict_private_id(dispatch.get("threadId"), "dispatch thread")
    _strict_sha256(dispatch.get("registry_sha256"), "registry digest")
    _strict_sha256(dispatch.get("message_fingerprint"), "message fingerprint")
    prepared_at = _strict_time(dispatch.get("prepared_at"), "dispatch preparation")
    if prepared_at > now:
        raise ValueError("future dispatch preparation")
    reason = dispatch.get("delivery_reason")
    observed = dispatch.get("observed_at")
    if status == "delivery_unknown":
        if reason not in _DELIVERY_UNKNOWN_REASONS:
            raise ValueError("invalid delivery-unknown reason")
        observed_at = _strict_time(observed, "delivery observation")
        if observed_at > now or observed_at < prepared_at:
            raise ValueError("invalid delivery observation")
    elif reason is not None or observed is not None:
        raise ValueError("delivery observation is not allowed for this lifecycle")
    return dispatch


def _validated_ack(
    value: object,
    *,
    terminal: bool,
    now: datetime,
) -> dict[str, Any]:
    fields = _ACK_TERMINAL_FIELDS if terminal else _ACK_BASE_FIELDS
    ack = _strict_object(value, fields, "acknowledgement")
    acked_at = _strict_time(ack.get("acked_at"), "acknowledgement")
    if acked_at > now:
        raise ValueError("future acknowledgement")
    thread_id = ack.get("thread_id")
    if thread_id is not None:
        _strict_private_id(thread_id, "acknowledgement thread")
    if terminal:
        if ack.get("terminal_status") not in {"completed", "failed"}:
            raise ValueError("invalid terminal status")
        terminal_at = _strict_time(ack.get("terminal_at"), "terminal")
        if terminal_at > now or terminal_at < acked_at:
            raise ValueError("invalid terminal time")
    return ack


def _route_for_queue_item(
    item: dict[str, Any],
    routes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    dispatch = item.get("dispatch")
    requested_role = (
        item["next_task"].get("agent_role")
        if isinstance(item.get("next_task"), dict)
        else None
    )
    if isinstance(dispatch, dict):
        route = routes.get(dispatch.get("route_id"))
        if route is None:
            raise ValueError("dispatch route is not registered")
        if (
            route["hostId"] != dispatch.get("hostId")
            or route["threadId"] != dispatch.get("threadId")
        ):
            raise ValueError("dispatch destination mismatch")
        if requested_role is not None and route["agentRole"] != requested_role:
            raise ValueError("dispatch role mismatch")
        matches = [route]
    else:
        matches = [
            route
            for route in routes.values()
            if route["project"] == item["project"]
            and route["repository"] == item["repository"]
            and (requested_role is None or route["agentRole"] == requested_role)
        ]
        if not matches and requested_role is not None:
            matches = [
                route
                for route in routes.values()
                if route["project"] == item["project"]
                and route["repository"] == item["repository"]
            ]
    if len(matches) != 1:
        raise ValueError("queue destination is missing or ambiguous")
    route = matches[0]
    if route["project"] != item["project"] or route["repository"] != item["repository"]:
        raise ValueError("queue route identity mismatch")
    return route


def _validated_queue_item(
    value: object,
    *,
    routes: dict[str, dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], datetime]:
    if not isinstance(value, dict):
        raise ValueError("queue item must be an object")
    fields = set(value)
    allowed = _QUEUE_ITEM_FIELDS | {"dispatch"}
    if fields not in (_QUEUE_ITEM_FIELDS, allowed):
        raise ValueError("invalid queue item fields")
    item = value
    queue_id = _strict_private_id(item.get("queue_id"), "queue id")
    project = item.get("project")
    repository = _strict_repository(item.get("repository"))
    source_task_id = _strict_private_id(item.get("source_task_id"), "source task id")
    del source_task_id
    completed_at = _strict_time(item.get("completed_at"), "source completion")
    if completed_at > now:
        raise ValueError("future source completion")
    fingerprint = _strict_sha256(item.get("evidence_fingerprint"), "evidence fingerprint")
    decision = item.get("decision")
    owner_gate = item.get("owner_gate")
    status = item.get("status")
    if (
        project not in {record["project"] for record in CAMPUS_PROJECTS}
        or decision not in _QUEUE_DECISIONS
        or status not in _QUEUE_STATUSES
        or not isinstance(owner_gate, str)
        or _safe_id(owner_gate) != owner_gate
    ):
        raise ValueError("invalid queue identity or lifecycle")
    next_step = _strict_public_text(item.get("next_step"), "next step")
    del next_step
    expected_dedupe = f"{project}|{fingerprint}|{decision}"
    if item.get("dedupe_key") != expected_dedupe:
        raise ValueError("invalid queue dedupe key")
    if _QUEUE_ID.fullmatch(queue_id) is None:
        raise ValueError("invalid queue id")

    next_task = item.get("next_task")
    if decision == "auto_continue":
        _validated_next_task(next_task, project=project)
        if owner_gate != "none":
            raise ValueError("auto continuation cannot require owner gate")
    elif next_task is not None:
        raise ValueError("owner notice cannot contain an executable next task")
    elif decision == "owner_gate" and owner_gate == "none":
        raise ValueError("owner gate is missing")

    has_dispatch = "dispatch" in item
    claim = item.get("claim")
    ack = item.get("ack")
    dispatch: dict[str, Any] | None = None
    if status == "queued":
        if claim is not None or ack is not None or has_dispatch:
            raise ValueError("invalid queued lifecycle")
    else:
        _validated_claim(claim, now=now)

    if status == "claimed":
        if ack is not None or has_dispatch:
            raise ValueError("invalid claimed lifecycle")
    elif status in {"sending", "delivery_unknown", "active"}:
        if not has_dispatch:
            raise ValueError("dispatch is required")
        dispatch = _validated_dispatch(item.get("dispatch"), status=status, now=now)
        if status in {"sending", "delivery_unknown"} and ack is not None:
            raise ValueError("premature acknowledgement")
        if status == "active":
            active_ack = _validated_ack(ack, terminal=False, now=now)
            if (
                active_ack.get("reason") != "sent_to_thread"
                or active_ack.get("thread_id") != dispatch.get("threadId")
            ):
                raise ValueError("invalid active acknowledgement")
    elif status == "acked":
        if decision == "auto_continue":
            if has_dispatch:
                dispatch = _validated_dispatch(item.get("dispatch"), status=status, now=now)
            terminal_ack = _validated_ack(ack, terminal=True, now=now)
            if terminal_ack.get("reason") != "sent_to_thread":
                raise ValueError("invalid terminal acknowledgement")
        else:
            if has_dispatch:
                raise ValueError("owner notice cannot contain dispatch")
            notice_ack = _validated_ack(ack, terminal=False, now=now)
            expected_reason = (
                "owner_gate_reported" if decision == "owner_gate" else "terminal_notice_reported"
            )
            if notice_ack.get("reason") != expected_reason or notice_ack.get("thread_id") is not None:
                raise ValueError("invalid owner notice acknowledgement")

    route = _route_for_queue_item(item, routes)
    if status == "acked" and decision == "auto_continue":
        terminal_ack = item["ack"]
        if terminal_ack.get("thread_id") != route["threadId"]:
            raise ValueError("terminal acknowledgement route mismatch")

    transition_candidates = (
        item.get("ack", {}).get("terminal_at") if isinstance(item.get("ack"), dict) else None,
        dispatch.get("observed_at") if isinstance(dispatch, dict) else None,
        dispatch.get("prepared_at") if isinstance(dispatch, dict) else None,
        item.get("ack", {}).get("acked_at") if isinstance(item.get("ack"), dict) else None,
        item.get("claim", {}).get("claimed_at") if isinstance(item.get("claim"), dict) else None,
        item.get("completed_at"),
    )
    transition = next(
        _strict_time(candidate, "transition")
        for candidate in transition_candidates
        if candidate is not None
    )
    public_status = {
        "queued": "queued",
        "claimed": "active",
        "sending": "active",
        "delivery_unknown": "failed",
        "active": "active",
    }.get(status)
    if status == "acked":
        if decision == "owner_gate":
            public_status = "waiting"
        elif decision == "stop":
            public_status = "done"
        else:
            public_status = "done" if ack.get("terminal_status") == "completed" else "failed"
    assert public_status is not None
    zone = DEPARTMENT_ZONES[route["departmentId"]]
    event = {
        "event_id": queue_id,
        "task_id": queue_id,
        "department_id": route["departmentId"],
        "department_label": zone["label"],
        "project": project,
        "agent_id": route["agentRole"],
        "role": zone["roles"][0],
        "status": public_status,
        "updated_at": transition.isoformat().replace("+00:00", "Z"),
        "next_step": item["next_step"],
        "evidence_count": 1,
        "ephemeral": True,
        "zone_id": zone["zone_id"],
    }
    return event, transition


def continuation_queue_campus_projection(
    queue_data: object,
    routes_data: object,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Read and validate the canonical queue without mutating or dispatching it."""
    current = _utc_now(now)
    try:
        queue = _strict_object(queue_data, _QUEUE_TOP_LEVEL_FIELDS, "queue")
        if not _strict_version(queue.get("version")) or not isinstance(queue.get("items"), list):
            raise ValueError("invalid queue schema")
        routes = _validated_route_registry(routes_data)
        if not queue["items"]:
            return _empty_projection("empty", current)
        events: list[dict[str, Any]] = []
        transitions: list[datetime] = []
        seen_queue_ids: set[str] = set()
        for raw_item in queue["items"]:
            event, transition = _validated_queue_item(raw_item, routes=routes, now=current)
            if event["event_id"] in seen_queue_ids:
                raise ValueError("duplicate queue item")
            seen_queue_ids.add(event["event_id"])
            events.append(event)
            transitions.append(transition)
    except (KeyError, StopIteration, TypeError, ValueError):
        return _empty_projection("unavailable", current)

    if any((current - transition).total_seconds() > _FRESH_SECONDS for transition in transitions):
        return _empty_projection("stale", current)
    return department_campus_projection(events, now=current, max_tasks=3)


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
        ("next_step", "Следующий безопасный шаг", True),
        ("evidence_count", "Подтверждения", True),
    )
    project_detail_rows = "".join(
        (
            '<div data-campus-project-live-only hidden>'
            if live_only
            else "<div>"
        )
        + f'<dt>{label}</dt><dd data-campus-project-detail-field="{field}">—</dd></div>'
        for field, label, live_only in project_details
    )
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
            <dl>{project_detail_rows}</dl>
        </aside>
    </div>
    <span class="campus-status-vocabulary" hidden>
        в очереди · работает · проверяет · ждёт решения · готово · ошибка
        Нет активных задач · Нет свежих данных · Данные временно недоступны
    </span>
</section>"""
