"""Linear issue fetching and HTML rendering."""
from __future__ import annotations

import html
import json
import os
import shlex
import sqlite3
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


LINEAR_API_URL = "https://api.linear.app/graphql"
JARVIS_DB = Path.home() / "jarvis" / "data" / "jarvis.db"
JARVIS_REMOTE = "maxx@100.77.209.73"
JARVIS_REMOTE_DB = "/Users/pirajoke/jarvis/data/jarvis.db"
HOMEBREW_CA_BUNDLE = Path("/opt/homebrew/etc/openssl@3/cert.pem")

if not os.environ.get("SSL_CERT_FILE") and HOMEBREW_CA_BUNDLE.exists():
    os.environ["SSL_CERT_FILE"] = str(HOMEBREW_CA_BUNDLE)


def _linear_token() -> str:
    token = os.environ.get("LINEAR_API_KEY", "").strip()
    if token:
        return token
    token_path = Path.home() / ".config" / "linear" / "token"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def _linear_gql(query: str, variables: dict | None = None) -> dict:
    token = _linear_token()
    if not token:
        return {}
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        LINEAR_API_URL,
        payload,
        {"Authorization": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}
    if body.get("errors"):
        return {}
    return body.get("data", {})


def fetch_linear_issues() -> list[dict]:
    """Fetch active Personal Linear issues with enough metadata for dashboard routing."""
    data = _linear_gql(
        """
        query($team: String!, $state: String!, $limit: Int!) {
          issues(
            first: $limit,
            filter: {
              team: { name: { eq: $team } },
              state: { type: { eq: $state } }
            },
            orderBy: updatedAt
          ) {
            nodes {
              id identifier title url priority
              createdAt updatedAt description
              state { name type }
              project { id name url }
              assignee { name }
              labels { nodes { name } }
            }
          }
        }
        """,
        {"team": "Personal", "state": "started", "limit": 50},
    )
    issues = data.get("issues", {}).get("nodes", []) if data else []
    return issues + fetch_jarvis_local_todos()


def fetch_jarvis_local_todos() -> list[dict]:
    """Fetch local JARVIS personal tasks that could not be synced to Linear."""
    rows = _fetch_remote_jarvis_todos()
    if not rows:
        rows = _fetch_local_jarvis_todos(JARVIS_DB)
    return [_todo_row_to_issue(row) for row in rows]


def _fetch_local_jarvis_todos(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT id, created_at, updated_at, title, project, notes, source
                FROM todos
                WHERE status = 'open'
                  AND project = 'Personal'
                  AND source = 'telegram:personal_task'
                  AND COALESCE(external_id, '') = ''
                ORDER BY created_at DESC
                LIMIT 25
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _fetch_remote_jarvis_todos() -> list[dict]:
    query = (
        "SELECT id, created_at, updated_at, title, project, notes, source "
        "FROM todos "
        "WHERE status = 'open' "
        "AND project = 'Personal' "
        "AND source = 'telegram:personal_task' "
        "AND COALESCE(external_id, '') = '' "
        "ORDER BY created_at DESC "
        "LIMIT 25"
    )
    script = (
        "import json, sqlite3; "
        f"con = sqlite3.connect({JARVIS_REMOTE_DB!r}); "
        "con.row_factory = sqlite3.Row; "
        f"rows = con.execute({query!r}).fetchall(); "
        "print(json.dumps([dict(row) for row in rows], ensure_ascii=False))"
    )
    remote_cmd = f"/Users/pirajoke/jarvis/.venv/bin/python -c {shlex.quote(script)}"
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=10",
                JARVIS_REMOTE,
                remote_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _todo_row_to_issue(row: dict) -> dict:
    todo_id = row.get("id", "?")
    created_at = str(row.get("created_at") or "")
    updated_at = str(row.get("updated_at") or created_at)
    notes = str(row.get("notes") or "")
    return {
        "id": f"jarvis-todo-{todo_id}",
        "identifier": f"JARVIS-{todo_id}",
        "title": str(row.get("title") or "Untitled"),
        "url": "",
        "priority": 0,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "description": f"Source: JARVIS local todo\n\n{notes}",
        "team": {"key": "JARVIS", "name": "JARVIS"},
        "state": {"name": "Local", "type": "local"},
        "project": {"id": "jarvis-local", "name": "JARVIS Local", "url": ""},
        "assignee": {"name": ""},
        "labels": {"nodes": [{"name": "local-fallback"}]},
    }


def group_linear_issues(issues: list[dict]) -> dict[str, list[dict]]:
    groups = {}
    for issue in issues:
        proj = issue.get("project", {})
        proj_name = proj.get("name", "No Project") if proj else "No Project"
        groups.setdefault(proj_name, []).append(issue)
    return groups


def _priority_label(p: int) -> tuple[str, str]:
    return {
        0: ("None", "#64748b"),
        1: ("Urgent", "#ef4444"),
        2: ("High", "#f97316"),
        3: ("Medium", "#eab308"),
        4: ("Low", "#64748b"),
    }.get(p, ("?", "#64748b"))


def _source_label(issue: dict) -> str:
    labels = issue.get("labels", {})
    label_nodes = labels.get("nodes", []) if labels else []
    for lbl in label_nodes:
        name = str(lbl.get("name", ""))
        if name.lower().startswith(("source/", "source:")):
            return name

    description = str(issue.get("description") or "")
    first_line = description.splitlines()[0].strip() if description else ""
    if first_line.lower().startswith("source:"):
        source = first_line.split(":", 1)[1].strip()
        if source.lower().startswith("jarvis telegram personal task"):
            return "JARVIS task"
        if source.lower().startswith("jarvis telegram personal note"):
            return "JARVIS note"
        if source.lower().startswith("jarvis local todo"):
            return "JARVIS local"
        return source[:40]
    return ""


def _short_date(value: str) -> str:
    return value[:10] if value else ""


def build_linear_html(issues: list[dict]) -> str:
    if not issues:
        return '<div class="linear-wrap"><div class="linear-empty">No active Personal issues in Linear.</div></div>'

    grouped = group_linear_issues(issues)
    out = '<div class="linear-wrap">'

    for proj_name, proj_issues in sorted(grouped.items()):
        proj_display = html.escape(proj_name)
        out += f'<div class="linear-project">'
        out += f'<div class="linear-project-header">'
        out += f'<span class="linear-project-name">{proj_display}</span>'
        out += f'<span class="linear-project-count">{len(proj_issues)}</span>'
        out += f'</div>'

        for issue in proj_issues:
            identifier = html.escape(str(issue.get("identifier", "?")))
            title = html.escape(str(issue.get("title", "Untitled")))
            url = html.escape(str(issue.get("url", "")), quote=True)
            state = issue.get("state", {})
            state_name = html.escape(str(state.get("name", "?") if state else "?"))
            state_type = state.get("type", "") if state else ""
            priority = issue.get("priority", 0)
            labels = issue.get("labels", {})
            label_nodes = labels.get("nodes", []) if labels else []
            source = _source_label(issue)
            updated = _short_date(str(issue.get("updatedAt", "")))

            state_colors = {
                "started": ("#3b82f6", "rgba(59,130,246,0.12)"),
                "local": ("#06b6d4", "rgba(6,182,212,0.12)"),
                "unstarted": ("#64748b", "rgba(100,116,139,0.12)"),
                "completed": ("#22c55e", "rgba(34,197,94,0.12)"),
                "cancelled": ("#ef4444", "rgba(239,68,68,0.12)"),
            }
            st_fg, st_bg = state_colors.get(state_type, ("#64748b", "rgba(100,116,139,0.12)"))

            pri_label, pri_color = _priority_label(priority)
            pri_dot = f'<span class="linear-priority" style="background:{pri_color}" title="{pri_label}"></span>' if priority > 0 else '<span class="linear-priority" style="background:transparent"></span>'

            labels_html = ""
            for lbl in label_nodes:
                lname = html.escape(str(lbl.get("name", "")))
                labels_html += f'<span class="linear-label">{lname}</span>'

            source_html = f'<span class="linear-source">{html.escape(source)}</span>' if source else ""
            updated_html = f'<span>updated {html.escape(updated)}</span>' if updated else ""
            ident_html = (
                f'<a class="linear-id" href="{url}" target="_blank" rel="noopener noreferrer">{identifier}</a>'
                if url else f'<span class="linear-id">{identifier}</span>'
            )

            out += f"""
            <div class="linear-issue">
                {pri_dot}
                {ident_html}
                <div class="linear-main">
                    <span class="linear-title">{title}</span>
                    <div class="linear-meta"><span>{proj_display}</span>{updated_html}</div>
                </div>
                <div class="linear-issue-right">
                    {source_html}
                    {labels_html}
                    <span class="linear-state" style="color:{st_fg};background:{st_bg}">{state_name}</span>
                </div>
            </div>"""

        out += '</div>'

    out += '</div>'
    return out
