#!/usr/bin/env python3
"""Probe the Mac mini from GitHub Actions without accepting Access redirects."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


COMMAND_CENTER_URL = "https://command.meshly.fr/api/health"
MYDICTIONARY_URL = "https://mydictionary.meshly.fr/health"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch_url(url: str, headers: dict[str, str], timeout: int) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(4096)
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read(4096)


def _probe(
    name: str,
    url: str,
    *,
    headers: dict[str, str],
    require_json: bool,
    requester,
    sleep,
    attempts: int,
) -> dict:
    detail = "request failed"
    for attempt in range(attempts):
        try:
            status, _content_type, body = requester(url, headers, 15)
            if status != 200:
                detail = f"HTTP {status}"
            elif require_json:
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    return {"name": name, "url": url, "state": "healthy", "detail": "HTTP 200"}
                detail = "invalid JSON response"
            else:
                return {"name": name, "url": url, "state": "healthy", "detail": "HTTP 200"}
        except (OSError, urllib.error.URLError):
            detail = "request failed"
        if attempt + 1 < attempts:
            sleep(20)
    return {"name": name, "url": url, "state": "down", "detail": detail}


def probe_all(env, *, requester=fetch_url, sleep=time.sleep, attempts: int = 3) -> dict:
    checks = []
    client_id = str(env.get("CF_ACCESS_CLIENT_ID", "")).strip()
    client_secret = str(env.get("CF_ACCESS_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        checks.append(
            {
                "name": "Command Center",
                "url": COMMAND_CENTER_URL,
                "state": "unconfigured",
                "detail": "Cloudflare Access service token missing",
            }
        )
    else:
        checks.append(
            _probe(
                "Command Center",
                COMMAND_CENTER_URL,
                headers={
                    "CF-Access-Client-Id": client_id,
                    "CF-Access-Client-Secret": client_secret,
                },
                require_json=True,
                requester=requester,
                sleep=sleep,
                attempts=attempts,
            )
        )
    checks.append(
        _probe(
            "My Dictionary",
            MYDICTIONARY_URL,
            headers={},
            require_json=False,
            requester=requester,
            sleep=sleep,
            attempts=attempts,
        )
    )
    return {
        "down": [f'{item["name"]}: {item["detail"]}' for item in checks if item["state"] == "down"],
        "unconfigured": [
            f'{item["name"]}: {item["detail"]}' for item in checks if item["state"] == "unconfigured"
        ],
        "checks": checks,
    }


def write_github_output(result: dict, path: Path) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f'down={"; ".join(result["down"])}\n')
        output.write(f'unconfigured={"; ".join(result["unconfigured"])}\n')


def main() -> int:
    result = probe_all(os.environ)
    print(json.dumps(result, ensure_ascii=False))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        write_github_output(result, Path(github_output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
