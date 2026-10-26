"""«Архитектура»: how the 24/7 agent system on the Mac mini is put together (Mark 2026-10-26).

Mark: «я должен сразу понимать, где работают агенты, кто ими управляет, как они получают
задания, где сохраняются результаты и что мешает автономной работе». The tab draws one map:
Mark's devices → MAIN MANAGER on the Mac mini → registry and queue → two kinds of executors
(project chats and background services) → result → check → log → next step.

Everything is read, nothing is written. Sources are the installed MAIN MANAGER projections
(routes, onboarding receipts, continuation queue), the canonical department list, launchd and
the department-campus agent activity the server already computes. Architecture (who is wired
to whom) is fixed in ``SERVICES`` and ``LINKS`` from the code and launchd jobs; activity only
comes from fresh events. A live process is shown as «процесс запущен», never as work done.

The answer is the same for every viewer and carries no paths, chat ids, hosts' raw ids or task
text: only names, roles, states, counts and times.
"""
from __future__ import annotations

import hashlib
import json
import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .native_activity import ROUTE_CONTRACT

SCHEMA = "command_center_architecture_v1"
MINI_HOST_SUFFIX = "maxxs-mac-mini"
MAX_JSON_BYTES = 1024 * 1024
# A queue item counts as current until it is acknowledged; older acknowledged items are history.
OPEN_QUEUE_STATUSES = {"queued", "pending", "claimed", "sending", "active", "delivery_unknown"}

DEPARTMENT_LABELS = {
    "hq": "Штаб",
    "infrastructure": "Инфраструктура",
    "development": "Разработка",
    "finance": "Финансы",
    "internal": "Внутреннее",
}
DEPARTMENT_ORDER = ("hq", "infrastructure", "development", "finance", "internal")
ROLE_LABELS = {
    "COORDINATOR": "координатор",
    "BUILDER": "разработчик",
    "ANALYST": "аналитик",
    "RESEARCHER": "исследователь",
}
AGENT_NAMES = {
    "accountable-os": "Accountable OS",
    "ai-studio": "AI Studio",
    "context-news": "Context News",
    "financial-os": "Financial OS",
    "github-hygiene": "GitHub Hygiene",
    "health-os": "Health OS",
    "jarvis": "JARVIS",
    "main-manager": "MAIN MANAGER",
    "my-dictionary": "My Dictionary",
    "pixelverse-dashboard": "Командный центр",
    "skills-library": "Skills Library",
    "unfinished-stuff": "Unfinished Stuff",
}

# Background services, from the launchd jobs on the Mac mini. ``labels`` may end with ``*``
# for a family of jobs (Bridge workers). ``feeds`` names the nodes this service hands work to.
SERVICES = (
    {"id": "continuation", "group": "control", "name": "Планировщик продолжения",
     "labels": ("com.pirajoke.main-manager-portfolio-continuation",), "runs": "каждые 15 минут",
     "does": "Собирает завершённые задачи Bridge в общую очередь MAIN MANAGER и решает, что продолжать."},
    {"id": "dispatcher", "group": "control", "name": "Диспетчер",
     "labels": ("com.pirajoke.main-manager-dispatcher",), "runs": "раз в минуту и по событию",
     "does": "Новые входящие MAIN MANAGER превращает в задания для Bridge (до 6 только на чтение)."},
    {"id": "status-publisher", "group": "report", "name": "Публикатор статуса",
     "labels": ("com.pirajoke.main-manager-status-publisher",), "runs": "каждые 5 минут",
     "does": "Переносит открытые пункты очереди в Bridge как статус для командного центра."},
    {"id": "notifier", "group": "report", "name": "Уведомления в Telegram",
     "labels": ("com.pirajoke.main-manager-telegram-notifier",), "runs": "раз в минуту",
     "does": "Сообщает на телефон о решениях, блокерах и важных завершениях."},
    {"id": "bridge-api", "group": "execute", "name": "Bridge API",
     "labels": ("com.pirajoke.bridge-api",), "runs": "постоянно",
     "does": "Общая очередь заданий для фоновых исполнителей и журнал их работы."},
    {"id": "bridge-workers", "group": "execute", "name": "Исполнители Bridge",
     "labels": ("com.pirajoke.bridge-worker*",), "runs": "постоянно, опрос раз в 30 секунд",
     "does": "Берут задания из Bridge и выполняют их через Codex или Claude."},
    {"id": "agent-task-runner", "group": "execute", "name": "Запуск задач с сайта",
     "labels": ("com.pirajoke.agent-task-runner",), "runs": "каждые 5 минут",
     "does": "Передаёт исполнителям задачи, поставленные из командного центра."},
    {"id": "jarvis-bot", "group": "product", "name": "JARVIS",
     "labels": ("com.pirajoke.jarvis-bot",), "runs": "постоянно",
     "does": "Telegram-бот JARVIS: отвечает и принимает поручения."},
    {"id": "news", "group": "product", "name": "Context News",
     "labels": ("com.pirajoke.ai-singularity-news-web", "com.pirajoke.ai-singularity-news-worker"),
     "runs": "постоянно", "does": "Сайт и фоновый сборщик новостей."},
    {"id": "job-radar", "group": "product", "name": "Job Radar",
     "labels": ("com.pirajoke.job-radar-local", "com.pirajoke.job-radar-worker"), "runs": "постоянно",
     "does": "Поиск вакансий: сайт и фоновый исполнитель."},
    {"id": "project-update", "group": "report", "name": "Журнал изменений",
     "labels": ("com.pirajoke.project-update-webhook",), "runs": "постоянно",
     "does": "Принимает итоги работы и записывает их в журнал проектов в Obsidian."},
    {"id": "dashboard", "group": "report", "name": "Командный центр",
     "labels": ("com.pirajoke.dashboard-server-m4",), "runs": "постоянно",
     "does": "Этот сайт: показывает состояние и ждущие решения."},
    {"id": "auto-deploy", "group": "report", "name": "Автовыкат сайта",
     "labels": ("com.pirajoke.dashboard-auto-deploy",), "runs": "каждые 5 минут",
     "does": "Ставит слитые изменения командного центра на Mac mini и проверяет сайт."},
)
SERVICE_GROUPS = (
    ("control", "Управление"),
    ("execute", "Исполнение"),
    ("product", "Продукты"),
    ("report", "Отчёт и журнал"),
)

# Who hands what to whom. Node ids: owner, main-manager, registry, queue, onboarding, chats,
# results, check, log, plus the SERVICES ids. Checked against the code and launchd jobs.
LINKS = (
    ("owner", "main-manager", "запрос и цель"),
    ("main-manager", "registry", "кому можно поручить"),
    ("main-manager", "queue", "что делать дальше"),
    ("onboarding", "registry", "новый агент после проверки"),
    ("queue", "chats", "задание в закреплённый чат проекта"),
    ("dispatcher", "bridge-api", "задание только на чтение"),
    ("bridge-api", "bridge-workers", "очередь Bridge"),
    ("agent-task-runner", "bridge-workers", "задача с сайта"),
    ("chats", "results", "PR, тесты, отчёт"),
    ("bridge-workers", "results", "итог задания"),
    ("results", "check", "доказательства"),
    ("bridge-api", "continuation", "завершённые задачи"),
    ("continuation", "queue", "проверенный следующий шаг"),
    ("check", "log", "итог"),
    ("log", "project-update", "запись в журнал"),
    ("queue", "status-publisher", "открытые пункты"),
    ("status-publisher", "dashboard", "статус"),
    ("check", "notifier", "решения и блокеры"),
    ("notifier", "owner", "Telegram"),
    ("dashboard", "owner", "командный центр"),
)

# What a queue item waits on, in Mark's words. Unknown kinds stay generic.
GATE_LABELS = {
    "merge": "решение о слиянии",
    "deploy": "решение о выкате",
    "publication": "решение о публикации",
    "payment": "решение о расходах",
    "credentials": "доступы или ключи",
}

STATE_LABELS = {
    "working": "работает",
    "needs_mark": "ждёт тебя",
    "waiting": "ждёт",
    "blocked": "заблокирован",
    "idle": "свободен",
    "done": "готово",
    "unknown": "нет свежего события",
    "running": "процесс запущен",
    "scheduled": "по расписанию",
    "failed": "последний запуск с ошибкой",
    "stopped": "не загружена",
}


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def read_json(path: Path) -> Any:
    """A small JSON file, or None when it is missing, too big or broken."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _agent_state(native: dict | None, gate: dict | None) -> tuple[str, str | None, str]:
    """(state, time, source) for one project chat. A gate in the queue beats missing activity."""
    if gate:
        return "needs_mark", gate.get("updated_at"), "очередь MAIN MANAGER"
    if isinstance(native, dict) and native.get("freshness") == "fresh":
        state = {"running": "working", "idle": "idle", "waiting": "waiting", "blocked": "blocked",
                 "done": "done"}.get(str(native.get("state") or ""), "unknown")
        return state, native.get("state_at"), "активность чата на Mac mini"
    return "unknown", None, "активность чата на Mac mini"


def project_agents(routes: Any, campus: dict | None) -> list[dict]:
    """Registered project chats with their department, role and last confirmed state."""
    entries = routes.get("routes") if isinstance(routes, dict) else None
    if not isinstance(entries, dict):
        return []
    campus = campus if isinstance(campus, dict) else {}
    native = {a.get("route_id"): a for a in campus.get("agents") or [] if isinstance(a, dict)}
    gates = {}
    for event in campus.get("owner_gates") or []:
        if isinstance(event, dict) and event.get("project"):
            gates.setdefault(_key(event["project"]), event)
    agents = []
    for route_id, route in sorted(entries.items()):
        if not isinstance(route, dict):
            continue
        department = str(route.get("departmentId") or "")
        gate = gates.get(_key(route.get("project"))) or gates.get(_key(AGENT_NAMES.get(route_id)))
        state, state_at, source = _agent_state(native.get(route_id), gate)
        if not route.get("enabled", False):
            state, state_at = "stopped", None
        host = str(route.get("hostId") or "")
        agents.append({
            "id": route_id,
            "name": AGENT_NAMES.get(route_id) or str(route.get("project") or route_id).title(),
            "department": department,
            "department_label": DEPARTMENT_LABELS.get(department, department or "без отдела"),
            "role": ROLE_LABELS.get(str(route.get("agentRole") or ""), str(route.get("agentRole") or "").lower()),
            "host": "Mac mini" if host.endswith(MINI_HOST_SUFFIX) else ("другой компьютер" if host else "не указан"),
            "chat_registered": bool(route.get("threadId")),
            "enabled": bool(route.get("enabled", False)),
            "state": state,
            "state_label": STATE_LABELS[state],
            "state_at": state_at,
            "source": source,
            "next_step": "Нужно твоё решение" if gate else None,
        })
    return agents


def departments(definitions: Any, agents: list[dict]) -> list[dict]:
    known = definitions.get("departments") if isinstance(definitions, dict) else None
    ids = [d for d in DEPARTMENT_ORDER if not known or d in known]
    ids += sorted({a["department"] for a in agents} - set(ids))
    return [{"id": d, "label": DEPARTMENT_LABELS.get(d, d), "agents": sum(a["department"] == d for a in agents)}
            for d in ids]


def queue_summary(queue: Any, scheduler_state: Any) -> dict:
    items = queue.get("items") if isinstance(queue, dict) else None
    if not isinstance(items, list):
        return {"available": False}
    open_items = [i for i in items if isinstance(i, dict) and str(i.get("status")) in OPEN_QUEUE_STATUSES]
    gates = [i for i in open_items if str(i.get("owner_gate") or "none") not in {"", "none"}]
    times = [_parse(i.get("completed_at")) for i in items if isinstance(i, dict)]
    times += [_parse((i.get("ack") or {}).get("acked_at")) for i in items if isinstance(i, dict) and isinstance(i.get("ack"), dict)]
    cursor = scheduler_state.get("cursor") if isinstance(scheduler_state, dict) else None
    collected = _parse(cursor.get("completed_at")) if isinstance(cursor, dict) else None
    cooldown = _parse(scheduler_state.get("cooldown_until")) if isinstance(scheduler_state, dict) else None
    return {
        "available": True,
        "total": len(items),
        "open": len(open_items),
        "owner_gates": len(gates),
        "executable": len(open_items) - len(gates),
        "gate_projects": sorted({str(i.get("project") or "") for i in gates} - {""}),
        "last_change_at": _iso(max((t for t in times if t), default=None)),
        "last_collected_at": _iso(collected),
        "cooldown_until": _iso(cooldown),
    }


def _gate_kinds(queue: Any) -> dict[str, str]:
    """Open owner gates by project: {project key: gate kind}. Only the kind, never the task text."""
    items = queue.get("items") if isinstance(queue, dict) else None
    kinds = {}
    for item in items if isinstance(items, list) else []:
        if (isinstance(item, dict) and str(item.get("status")) in OPEN_QUEUE_STATUSES
                and str(item.get("owner_gate") or "none") not in {"", "none"}):
            kinds[_key(item.get("project"))] = str(item["owner_gate"])
    return kinds


def onboarding_summary(state_dir: Path, *, installed_helper: Path, canonical_helper: Path,
                       installed_routes: Path, canonical_routes: Path) -> dict:
    """Registration receipts and whether the installed helper and registry match the canonical copy."""
    original = {route[0] for route in ROUTE_CONTRACT}
    receipts = []
    try:
        paths = sorted(state_dir.glob("*.receipt.json")) if state_dir.is_dir() else []
    except OSError:
        paths = []
    for path in paths[:200]:
        receipt = read_json(path)
        if not isinstance(receipt, dict):
            continue
        identity = receipt.get("identity") if isinstance(receipt.get("identity"), dict) else {}
        route_id = str(identity.get("route_id") or "")
        receipts.append({"route": AGENT_NAMES.get(route_id, route_id or "?"),
                         "at": _iso(_parse(receipt.get("registered_at"))),
                         "new_agent": bool(route_id) and route_id not in original})
    receipts.sort(key=lambda r: r["at"] or "", reverse=True)
    helper = file_digest(installed_helper)
    routes = file_digest(installed_routes)
    return {
        "receipts": len(receipts),
        "last": receipts[0] if receipts else None,
        "new_agents_registered": sum(r["new_agent"] for r in receipts),
        "recovery_pending": (state_dir / "pending.json").exists(),
        "helper_installed": helper is not None,
        "helper_matches_canonical": helper is not None and helper == file_digest(canonical_helper),
        "registry_matches_canonical": routes is not None and routes == file_digest(canonical_routes),
    }


def _job_matches(label: str, patterns: tuple[str, ...]) -> bool:
    return any(label.startswith(p[:-1]) if p.endswith("*") else label == p for p in patterns)


def parse_launchctl(raw: str) -> dict[str, dict]:
    """``launchctl list`` → {label: {"pid": int|None, "exit": int|None}}."""
    jobs = {}
    for line in raw.splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3 or parts[0] == "PID":
            continue
        pid = int(parts[0]) if parts[0].strip().isdigit() else None
        try:
            status = int(parts[1])
        except ValueError:
            status = None
        jobs[parts[2].strip()] = {"pid": pid, "exit": status}
    return jobs


def service_log_times(agents_dir: Path, labels: list[str]) -> dict[str, datetime]:
    """Last write to each job's own log, from its plist. Only the time leaves this function."""
    times = {}
    for label in labels:
        try:
            with (agents_dir / f"{label}.plist").open("rb") as handle:
                plist = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        stamps = []
        for key in ("StandardOutPath", "StandardErrorPath"):
            value = plist.get(key)
            if isinstance(value, str) and value:
                try:
                    stamps.append(Path(value).stat().st_mtime)
                except OSError:
                    pass
        if stamps:
            times[label] = datetime.fromtimestamp(max(stamps), timezone.utc)
    return times


def services(jobs: dict[str, dict] | None, log_times: dict[str, datetime]) -> list[dict]:
    out = []
    for spec in SERVICES:
        if jobs is None:
            matched = []
        else:
            matched = sorted(label for label in jobs if _job_matches(label, spec["labels"]))
        running = [label for label in matched if jobs[label]["pid"]]
        failed = [label for label in matched if not jobs[label]["pid"] and jobs[label]["exit"] not in (0, None)]
        expected = len([p for p in spec["labels"] if not p.endswith("*")]) or max(len(matched), 1)
        if jobs is None:
            state = "unknown"
        elif not matched:
            state = "stopped"
        elif failed:
            state = "failed"
        elif running:
            state = "running"
        else:
            state = "scheduled"
        stamps = [log_times[label] for label in matched if label in log_times]
        out.append({
            "id": spec["id"],
            "group": spec["group"],
            "name": spec["name"],
            "runs": spec["runs"],
            "does": spec["does"],
            "state": state,
            "state_label": STATE_LABELS[state],
            "jobs": len(matched),
            "jobs_expected": expected,
            "processes": len(running),
            "failed_jobs": len(failed),
            "last_log_at": _iso(max(stamps)) if stamps else None,
        })
    return out


def bridge_activity(bridge_tasks: Any) -> dict:
    """Last task change in Bridge: the newest real event the background executors left."""
    tasks = bridge_tasks.get("tasks") if isinstance(bridge_tasks, dict) else bridge_tasks
    if not isinstance(tasks, list):
        return {"available": False}
    stamps, running = [], 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for field in ("updated_at", "completed_at", "created_at"):
            moment = _parse(task.get(field))
            if moment:
                stamps.append(moment)
                break
        if str(task.get("status") or "") in {"running", "in_progress", "claimed"}:
            running += 1
    return {"available": True, "last_event_at": _iso(max(stamps, default=None)), "running": running}


def architecture_projection(*, routes: Any, department_defs: Any, campus: dict | None, queue: Any,
                            scheduler_state: Any, onboarding: dict, jobs: dict[str, dict] | None,
                            log_times: dict[str, datetime], bridge_tasks: Any, now: datetime) -> dict:
    agents = project_agents(routes, campus)
    for kind_project, kind in _gate_kinds(queue).items():
        for agent in agents:
            if agent["state"] == "needs_mark" and kind_project in {_key(agent["name"]), _key(agent["id"])}:
                agent["next_step"] = f"Нужно твоё решение: {GATE_LABELS.get(kind, 'решение по следующему шагу')}"
    service_list = services(jobs, log_times)
    counts = {state: sum(a["state"] == state for a in agents) for state in STATE_LABELS}
    blockers = []
    if counts["needs_mark"]:
        names = ", ".join(a["name"] for a in agents if a["state"] == "needs_mark")
        blockers.append(f"Ждёт твоего решения: {names}.")
    if agents and counts["unknown"] == len(agents):
        blockers.append("Ни один проектный чат не оставил свежего подтверждённого события: "
                        "активность агентов сейчас не видна.")
    for service in service_list:
        if service["state"] in {"failed", "stopped"}:
            blockers.append(f"{service['name']}: {service['state_label']}.")
    if onboarding.get("recovery_pending"):
        blockers.append("Подключение агента прервалось и ждёт сверки, новые агенты не выдаются в работу.")
    if not onboarding.get("new_agents_registered"):
        blockers.append("Создание нового агента целиком ещё не проверено: была только повторная регистрация.")
    return {
        "schema": SCHEMA,
        "generated_at": _iso(now),
        "agents": agents,
        "departments": departments(department_defs, agents),
        "agent_counts": {
            "registered": len(agents),
            "working": counts["working"],
            "needs_mark": counts["needs_mark"],
            "idle": counts["idle"],
            "unknown": counts["unknown"],
        },
        "services": service_list,
        "service_groups": [{"id": g, "label": label} for g, label in SERVICE_GROUPS],
        "service_counts": {
            "total": len(service_list),
            "ok": sum(s["state"] in {"running", "scheduled"} for s in service_list),
            "problem": sum(s["state"] in {"failed", "stopped"} for s in service_list),
        },
        "queue": queue_summary(queue, scheduler_state),
        "onboarding": onboarding,
        "bridge": bridge_activity(bridge_tasks),
        "links": [{"from": a, "to": b, "label": label} for a, b, label in LINKS],
        "blockers": blockers,
    }


def collect_architecture(*, home: Path, campus: dict | None, bridge_tasks: Any, launchctl_raw: str | None,
                         now: datetime | None = None) -> dict:
    """Read the Mac mini's own files and build the projection. Never writes."""
    now = now or datetime.now(timezone.utc)
    runtime = home / "Library/Application Support/MainManagerPortfolioContinuation"
    canonical = home / "Documents/ChatGPT/MAIN MANAGER"
    jobs = parse_launchctl(launchctl_raw) if launchctl_raw else None
    wanted = [label for label in (jobs or {}) if any(_job_matches(label, s["labels"]) for s in SERVICES)]
    onboarding = onboarding_summary(
        runtime / "state/onboarding",
        installed_helper=runtime / "agent_onboarding.py",
        canonical_helper=canonical / "scripts/agent_onboarding.py",
        installed_routes=runtime / "agent-routes.json",
        canonical_routes=canonical / "config/agent-routes.json",
    )
    return architecture_projection(
        routes=read_json(runtime / "agent-routes.json"),
        department_defs=read_json(canonical / "config/departments.json"),
        campus=campus,
        queue=read_json(runtime / "state/continuation-queue.json"),
        scheduler_state=read_json(runtime / "state/scheduler-state.json"),
        onboarding=onboarding,
        jobs=jobs,
        log_times=service_log_times(home / "Library/LaunchAgents", wanted),
        bridge_tasks=bridge_tasks,
        now=now,
    )
