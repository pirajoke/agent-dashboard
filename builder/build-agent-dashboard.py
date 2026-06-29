#!/usr/bin/env python3
"""Agent Dashboard Generator — thin wrapper over dashboard_builder package."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from dashboard_builder.config import AGENTS, VAULT, HTML_OUT
from dashboard_builder.projects import scan_projects
from dashboard_builder.comms import read_comms
from dashboard_builder.html_builder import build_html
from dashboard_builder.md_builder import build_md

TODAY = datetime.now().strftime("%Y-%m-%d")
MD_OUT = VAULT / "90-Operations" / "second-brain" / "reports" / f"{TODAY} -- agents-dashboard.md"


def main():
    ict = timezone(timedelta(hours=7))
    timestamp = datetime.now(ict).strftime("%Y-%m-%d %H:%M:%S ICT")
    md_snapshot_label = datetime.now(ict).strftime("%Y-%m-%d ICT")
    projects = scan_projects()

    html = build_html(projects, timestamp)
    HTML_OUT.write_text(html, encoding="utf-8")
    print(f"✓ HTML → {HTML_OUT}")

    comms = read_comms(50)
    md = build_md(projects, md_snapshot_label, comms)
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(md, encoding="utf-8")
    print(f"✓ MD   → {MD_OUT}")

    total_open = sum(p["open_todos"] for p in projects)
    total_closed = sum(p["closed_todos"] for p in projects)
    print(f"\n  {len(AGENTS)} agents | {len(projects)} projects | {total_open} open | {total_closed} closed")


if __name__ == "__main__":
    main()
