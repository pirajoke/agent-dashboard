"""JARVIS pipeline card for the Command Center dashboard."""
from __future__ import annotations

import html
import json
import re
import sqlite3
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


JARVIS_REPO = Path.home() / "jarvis"
JARVIS_DB = JARVIS_REPO / "data" / "jarvis.db"
DEPLOY_SCRIPT = JARVIS_REPO / "scripts" / "deploy_macmini.sh"
JARVIS_LOG = Path("/tmp/jarvis-bot.err")
LAUNCHD_SERVICE = "gui/501/com.pirajoke.jarvis-bot"


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 5) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _tail_matching(path: Path, marker: str, *, limit: int = 5000) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for line in reversed(lines[-limit:]):
        if marker in line:
            return line.strip()
    return ""


def _parse_aios(line: str) -> dict:
    data = {}
    for key in ("status", "stale", "schema", "pack", "writes", "blocked_for_writes"):
        match = re.search(rf"\b{key}=([^\s]+)", line)
        if match:
            data[key] = match.group(1)
    return data


def _short_time(value: str) -> str:
    if not value:
        return "none"
    value = value.replace("T", " ").replace("+00:00", "Z")
    return value[:19]


def _trim(value: str, limit: int = 90) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _planning_month_key(today: date) -> str:
    if today.day < 25:
        return today.strftime("%Y-%m")
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1).strftime("%Y-%m")


def _accepted_goal_months(today: date) -> set[str]:
    return {today.strftime("%Y-%m"), _planning_month_key(today)}


def _launchd_status() -> dict:
    raw = _run(["launchctl", "print", LAUNCHD_SERVICE], timeout=6)
    state = ""
    pid = ""
    for line in raw.splitlines():
        clean = line.strip()
        if clean.startswith("state = "):
            state = clean.split("=", 1)[1].strip()
        elif clean.startswith("pid = "):
            pid = clean.split("=", 1)[1].strip()
    pgrep = _run(["pgrep", "-fl", str(JARVIS_REPO / ".venv" / "bin" / "jarvis")], timeout=3)
    if not pid and pgrep:
        pid = pgrep.splitlines()[0].split(" ", 1)[0]
    return {"state": state or "unknown", "pid": pid, "raw_running": bool(pgrep)}


def _git_status() -> dict:
    if not (JARVIS_REPO / ".git").exists():
        return {"ok": False, "head": "no git", "branch": "unknown", "dirty": True, "status": "missing .git"}
    head = _run(["git", "rev-parse", "--short", "HEAD"], cwd=JARVIS_REPO)
    branch = _run(["git", "branch", "--show-current"], cwd=JARVIS_REPO)
    porcelain = _run(["git", "status", "--porcelain"], cwd=JARVIS_REPO)
    sb = _run(["git", "status", "-sb"], cwd=JARVIS_REPO)
    dirty = bool(porcelain)
    status = sb.splitlines()[0] if sb else ("dirty" if dirty else "clean")
    return {"ok": bool(head) and not dirty, "head": head or "unknown", "branch": branch or "unknown", "dirty": dirty, "status": status}


def _source_ledger_status() -> dict:
    if not JARVIS_DB.exists():
        return {"count": 0, "latest": "", "question": "", "source_count": 0}
    try:
        con = sqlite3.connect(str(JARVIS_DB))
        con.row_factory = sqlite3.Row
        count = con.execute("select count(distinct answer_id) from answer_sources").fetchone()[0]
        row = con.execute(
            """
            select answer_id, created_at, question, count(*) as source_count
            from answer_sources
            group by answer_id
            order by max(id) desc
            limit 1
            """
        ).fetchone()
    except Exception:
        return {"count": 0, "latest": "", "question": "", "source_count": 0}
    finally:
        try:
            con.close()
        except Exception:
            pass
    if not row:
        return {"count": int(count or 0), "latest": "", "question": "", "source_count": 0}
    return {
        "count": int(count or 0),
        "latest": str(row["created_at"] or ""),
        "question": str(row["question"] or ""),
        "source_count": int(row["source_count"] or 0),
    }


def _latest_intake_contract() -> dict:
    if not JARVIS_DB.exists():
        return {"ok": False, "detail": "db missing", "summary": "no contract"}
    try:
        con = sqlite3.connect(str(JARVIS_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select id, created_at, text, routed_to, meta
            from captures
            where coalesce(meta, '') != ''
            order by id desc
            limit 40
            """
        ).fetchall()
    except Exception:
        return {"ok": False, "detail": "query failed", "summary": "contract unavailable"}
    finally:
        try:
            con.close()
        except Exception:
            pass

    for row in rows:
        try:
            meta = json.loads(row["meta"] or "{}")
        except json.JSONDecodeError:
            continue
        intent = str(meta.get("intent") or "").strip()
        if not intent:
            continue
        targets = meta.get("write_targets") or []
        if not isinstance(targets, list):
            targets = []
        title = str(meta.get("title") or meta.get("summary") or row["text"] or "")
        routed_to = str(row["routed_to"] or "")
        confidence = meta.get("confidence")
        try:
            confidence_label = f"{float(confidence):.2f}"
        except (TypeError, ValueError):
            confidence_label = "n/a"
        return {
            "ok": True,
            "id": int(row["id"]),
            "created_at": str(row["created_at"] or ""),
            "intent": intent,
            "project": str(meta.get("project") or ""),
            "title": _trim(title, 110),
            "routed_to": routed_to,
            "targets": targets,
            "confidence": confidence_label,
            "needs_review": bool(meta.get("needs_review")),
            "summary": f"{intent} → {routed_to or 'route?'}",
            "detail": f"{confidence_label} / {', '.join(targets) if targets else 'answer'}",
        }
    return {"ok": False, "detail": "no JSON contract", "summary": "no contract"}


def _todo_sync_status() -> dict:
    if not JARVIS_DB.exists():
        return {"ok": False, "open": 0, "linked": 0, "unsynced": 0, "items": [], "detail": "db missing"}
    try:
        con = sqlite3.connect(str(JARVIS_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select id, created_at, updated_at, title, project, source, external_id
            from todos
            where status = 'open'
              and source = 'telegram:personal_task'
            order by
              case when coalesce(external_id, '') = '' then 0 else 1 end,
              created_at desc
            limit 50
            """
        ).fetchall()
    except Exception:
        return {"ok": False, "open": 0, "linked": 0, "unsynced": 0, "items": [], "detail": "query failed"}
    finally:
        try:
            con.close()
        except Exception:
            pass

    open_count = len(rows)
    linked = sum(1 for row in rows if str(row["external_id"] or "").strip())
    unsynced_rows = [row for row in rows if not str(row["external_id"] or "").strip()]
    items = [
        {
            "id": int(row["id"]),
            "project": str(row["project"] or "Personal"),
            "title": _trim(str(row["title"] or "Untitled"), 80),
            "created_at": str(row["created_at"] or ""),
        }
        for row in unsynced_rows[:4]
    ]
    unsynced = len(unsynced_rows)
    return {
        "ok": unsynced == 0,
        "open": open_count,
        "linked": linked,
        "unsynced": unsynced,
        "items": items,
        "detail": f"{linked}/{open_count} linked" if open_count else "no open intake todos",
    }


def _goals_status() -> dict:
    path = JARVIS_REPO / "goals.yaml"
    if not path.exists():
        return {"ok": False, "month": "", "detail": "goals.yaml missing"}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"ok": False, "month": "", "detail": "read failed"}
    match = re.search(r"(?m)^month:\s*['\"]?([^'\"\n]+)", raw)
    month = match.group(1).strip() if match else ""
    today = datetime.now().date()
    accepted = _accepted_goal_months(today)
    ok = bool(month) and month in accepted
    detail = f"{month or 'unknown'} / expected {', '.join(sorted(accepted))}"
    return {"ok": ok, "month": month, "detail": detail}


def _warning_items(*, git: dict, aios: dict, contract: dict, sync: dict, goals: dict) -> list[str]:
    warnings: list[str] = []
    if git.get("dirty"):
        warnings.append("JARVIS runtime checkout is dirty.")
    if aios.get("stale") not in {"", None, "green"}:
        warnings.append(f"AIOS stale-check is {aios.get('stale')}.")
    if not goals.get("ok"):
        warnings.append(f"goals.yaml stale: {goals.get('detail')}.")
    if sync.get("unsynced"):
        warnings.append(f"{sync.get('unsynced')} open Telegram todos are not linked to Linear.")
    if contract.get("needs_review"):
        warnings.append("Latest intake contract needs review.")
    return warnings[:4]


def collect_jarvis_pipeline_data() -> dict:
    launchd = _launchd_status()
    git = _git_status()
    ledger = _source_ledger_status()
    contract = _latest_intake_contract()
    sync = _todo_sync_status()
    goals = _goals_status()
    aios_line = _tail_matching(JARVIS_LOG, "AIOS context startup:")
    start_line = _tail_matching(JARVIS_LOG, "JARVIS bot started")
    aios = _parse_aios(aios_line)
    human_layer = "HUMAN_INTERFACE_GUIDANCE" in (JARVIS_REPO / "src" / "jarvis" / "bot.py").read_text(
        encoding="utf-8",
        errors="ignore",
    ) if (JARVIS_REPO / "src" / "jarvis" / "bot.py").exists() else False

    checks = [
        {"key": "runtime", "label": "Runtime", "ok": bool(launchd["pid"]), "detail": f"pid {launchd['pid'] or '-'}"},
        {"key": "git", "label": "Git", "ok": git["ok"], "detail": f"{git['branch']}@{git['head']}"},
        {"key": "aios", "label": "AIOS", "ok": aios.get("status") == "green" and aios.get("pack") == "fresh", "detail": f"{aios.get('status', 'unknown')} / {aios.get('pack', 'unknown')}"},
        {"key": "source", "label": "Sources", "ok": ledger["count"] > 0, "detail": f"{ledger['count']} answers"},
        {"key": "contract", "label": "Contract", "ok": contract["ok"], "detail": contract["summary"]},
        {"key": "linear", "label": "Linear Sync", "ok": sync["ok"], "detail": sync["detail"]},
        {"key": "goals", "label": "Goals", "ok": goals["ok"], "detail": goals["detail"]},
        {"key": "deploy", "label": "Deploy", "ok": DEPLOY_SCRIPT.exists(), "detail": "git script" if DEPLOY_SCRIPT.exists() else "missing"},
        {"key": "human", "label": "Human Layer", "ok": human_layer, "detail": "enabled" if human_layer else "missing"},
    ]
    warnings = _warning_items(git=git, aios=aios, contract=contract, sync=sync, goals=goals)
    failed = [c for c in checks if not c["ok"]]
    if not failed:
        status = "green"
        next_action = "Use Telegram smoke: что сейчас по Jarvis? → покажи источники."
    elif any(c["key"] in {"runtime", "git", "aios"} for c in failed):
        status = "red"
        next_action = "Run scripts/deploy_macmini.sh and check launchd logs."
    elif sync.get("unsynced"):
        status = "yellow"
        next_action = "Sync or triage local Telegram todos without Linear IDs."
    else:
        status = "yellow"
        next_action = "Run one live source-backed Telegram question, then show sources."

    return {
        "status": status,
        "checks": checks,
        "launchd": launchd,
        "git": git,
        "aios": aios,
        "aios_line": aios_line,
        "started_at": start_line[:19] if start_line else "",
        "ledger": ledger,
        "contract": contract,
        "sync": sync,
        "goals": goals,
        "warnings": warnings,
        "next_action": next_action,
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def build_jarvis_pipeline_html(data: dict) -> str:
    status = data.get("status", "yellow")
    status_cls = {"green": "dot-green", "yellow": "dot-yellow", "red": "dot-red"}.get(status, "dot-dim")
    status_label = {"green": "ready", "yellow": "needs smoke", "red": "attention"}.get(status, "unknown")
    checks_html = ""
    for check in data.get("checks", []):
        dot = "dot-green" if check.get("ok") else "dot-yellow"
        if check.get("key") in {"runtime", "git", "aios"} and not check.get("ok"):
            dot = "dot-red"
        checks_html += (
            '<div class="jpipe-check">'
            f'<span class="status-dot {dot}"></span>'
            f'<span class="jpipe-check-label">{html.escape(str(check.get("label", "")))}</span>'
            f'<span class="jpipe-check-detail">{html.escape(str(check.get("detail", "")))}</span>'
            '</div>'
        )

    ledger = data.get("ledger", {})
    contract = data.get("contract", {})
    sync = data.get("sync", {})
    goals = data.get("goals", {})
    git = data.get("git", {})
    aios = data.get("aios", {})
    question = str(ledger.get("question") or "no live source answer yet")
    if len(question) > 80:
        question = question[:77] + "..."
    contract_title = str(contract.get("title") or "no intake contract")
    unsynced_items = ""
    for item in sync.get("items", [])[:3]:
        unsynced_items += (
            '<div class="jpipe-unsynced-item">'
            f'<span>#{int(item.get("id") or 0)} {html.escape(str(item.get("project") or ""))}</span>'
            f'<strong>{html.escape(str(item.get("title") or ""))}</strong>'
            '</div>'
        )
    if not unsynced_items:
        unsynced_items = '<div class="jpipe-empty">No local fallback todos.</div>'
    warnings = data.get("warnings") or []
    warning_html = ""
    if warnings:
        warning_html = '<div class="jpipe-warnings">' + "".join(
            f'<div><span class="status-dot dot-yellow"></span>{html.escape(str(item))}</div>'
            for item in warnings
        ) + "</div>"

    return f"""
    <div class="jpipe-card jpipe-{status}">
        <div class="jpipe-head">
            <div>
                <div class="jpipe-kicker">Jarvis Pipeline</div>
                <div class="jpipe-title">Mac Mini production</div>
            </div>
            <div class="jpipe-state"><span class="status-dot {status_cls}"></span>{status_label}</div>
        </div>
        <div class="jpipe-grid">{checks_html}</div>
        <div class="jpipe-meta">
            <div><span>HEAD</span><strong>{html.escape(str(git.get("head", "unknown")))}</strong></div>
            <div><span>AIOS</span><strong>{html.escape(str(aios.get("status", "unknown")))}/{html.escape(str(aios.get("pack", "unknown")))}</strong></div>
            <div><span>Sources</span><strong>{int(ledger.get("count") or 0)} answers</strong></div>
            <div><span>Started</span><strong>{html.escape(str(data.get("started_at") or "unknown"))}</strong></div>
        </div>
        <div class="jpipe-latest">
            <span>Latest source question</span>
            <strong>{html.escape(question)}</strong>
        </div>
        <div class="jpipe-signals">
            <div class="jpipe-signal">
                <span>Last intake contract</span>
                <strong>{html.escape(str(contract.get("summary") or "no contract"))}</strong>
                <em>{html.escape(contract_title)} · {html.escape(str(contract.get("detail") or ""))}</em>
            </div>
            <div class="jpipe-signal">
                <span>Linear sync</span>
                <strong>{int(sync.get("linked") or 0)}/{int(sync.get("open") or 0)} linked · {int(sync.get("unsynced") or 0)} unsynced</strong>
                <em>goals.yaml {html.escape(str(goals.get("month") or "unknown"))}</em>
            </div>
        </div>
        <div class="jpipe-unsynced">{unsynced_items}</div>
        {warning_html}
        <div class="jpipe-next">{html.escape(str(data.get("next_action") or ""))}</div>
    </div>"""
