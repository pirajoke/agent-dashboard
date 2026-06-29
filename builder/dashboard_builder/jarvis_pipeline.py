"""JARVIS pipeline card for the Command Center dashboard."""
from __future__ import annotations

import html
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
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


def collect_jarvis_pipeline_data() -> dict:
    launchd = _launchd_status()
    git = _git_status()
    ledger = _source_ledger_status()
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
        {"key": "deploy", "label": "Deploy", "ok": DEPLOY_SCRIPT.exists(), "detail": "git script" if DEPLOY_SCRIPT.exists() else "missing"},
        {"key": "human", "label": "Human Layer", "ok": human_layer, "detail": "enabled" if human_layer else "missing"},
    ]
    failed = [c for c in checks if not c["ok"]]
    if not failed:
        status = "green"
        next_action = "Use Telegram smoke: что сейчас по Jarvis? → покажи источники."
    elif any(c["key"] in {"runtime", "git", "aios"} for c in failed):
        status = "red"
        next_action = "Run scripts/deploy_macmini.sh and check launchd logs."
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
    git = data.get("git", {})
    aios = data.get("aios", {})
    question = str(ledger.get("question") or "no live source answer yet")
    if len(question) > 80:
        question = question[:77] + "..."

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
        <div class="jpipe-next">{html.escape(str(data.get("next_action") or ""))}</div>
    </div>"""
