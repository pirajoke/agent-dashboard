#!/usr/bin/env python3
"""Retire Command Center's own employer-replies watcher (Mark 2026-10-25).

Mark: «если мы по работодателям, это задача Job Radar смотреть, зачем это нужно мне тут». Job Radar's
«Ответы» tab reads the job mailbox and alerts in its bot, so Command Center stops doing the same.
Run by deploy_to_scripts.sh; safe to run again. It:

* hands the read-only Gmail grant back to Google and deletes it (it pointed at the wrong inbox);
* deletes the «Ответить …: зовут на собеседование» items it put in «Ждёт тебя» that are still open,
  since those came from personal mail (CAF, Colissimo…), not from employers.

It never prints the token. The rest of ~/.agent-bridge/job-mail (sorted subjects) stays on the Mac mini.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_builder import owner_todo  # noqa: E402

HOME = Path.home()
JOB_MAIL_DIR = Path(os.environ.get("JOB_MAIL_DIR") or HOME / ".agent-bridge" / "job-mail")
OWNER_TODO_FILE = Path(os.environ.get("OWNER_TODO_FILE") or HOME / ".agent-bridge" / "owner-todo.json")
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
WATCHER_NOTE = "Ответ работодателю пишет только Марк"


def revoke(root: Path = JOB_MAIL_DIR, opener=urllib.request.urlopen) -> str:
    token_file = root / "token.json"
    try:
        token = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        token = None
    if not token_file.exists():
        return "no_grant"
    state = "deleted"
    if isinstance(token, dict) and token.get("refresh_token"):
        request = urllib.request.Request(REVOKE_URL, method="POST",
                                         data=urllib.parse.urlencode({"token": token["refresh_token"]}).encode(),
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with opener(request, timeout=20):
                state = "revoked"
        except Exception:  # noqa: BLE001 — revoked already, or Google unreachable: the local copy goes either way.
            state = "deleted_unrevoked"
    for name in ("token.json", "oauth_state.json"):
        try:
            (root / name).unlink()
        except OSError:
            pass
    return state


def drop_items(path: Path = OWNER_TODO_FILE) -> int:
    dropped = 0
    for item in list(owner_todo.load_items(path)["items"]):
        if (not item.get("done") and str(item.get("text", "")).startswith("Ответить ")
                and item.get("triage", {}).get("why") == WATCHER_NOTE):
            try:
                owner_todo.change_items(path, {"action": "delete", "id": item["id"]})
                dropped += 1
            except (OSError, ValueError, LookupError):
                pass
    return dropped


def main() -> int:
    print(json.dumps({"grant": revoke(), "items_deleted": drop_items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
