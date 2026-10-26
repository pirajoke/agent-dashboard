#!/usr/bin/env python3
"""Check a Command Center release on the Mac mini in one command.

After a merge, an agent runs this instead of asking the owner to look:

    python3 builder/verify_release.py [--sha <merged sha>] [--expect <text>]...

It only reads and never deploys, restarts or pushes. Steps:

1. deploy  - origin/main (or --sha) is what auto-deploy put on the site, and the
             deploy log has no failure or rollback for it;
2. health  - the dashboard answers 200 on :7777 and serves every --expect text;
3. tests   - the full test suite, compileall and live-feed.json check, run on
             the checked commit in a throwaway worktree that is removed after;
4. screens - desktop (1440x1000) and phone (390x844) screenshots taken through
             headless Chrome's DevTools pipe, with exact viewports, no
             horizontal overflow and no uncaught page errors.

Results go to ~/.agent-bridge/release-checks/<UTC time>/ (report.json and the
two PNGs). Exit code: 0 all good, 2 still waiting for auto-deploy, 1 failure.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HOME = Path.home()
REPO_DIR = Path(os.environ.get("AUTO_DEPLOY_REPO_DIR", HOME / "agent-dashboard"))
STATE_DIR = Path(os.environ.get("AUTO_DEPLOY_STATE_DIR", HOME / ".agent-bridge" / "auto-deploy"))
CHECKS_DIR = HOME / ".agent-bridge" / "release-checks"
SITE_URL = "http://127.0.0.1:7777/"
PAGE_PATH = "?tab=work"
DEPLOY_PATHS = ("builder/",)
CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
)
VIEWPORTS = (("pc", 1440, 1000, False), ("phone", 390, 844, True))
PROBLEM_WINDOW = timedelta(hours=24)


def git(*args: str, repo: Path = REPO_DIR) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def step(status: str, summary: str, **details) -> dict:
    return {"status": status, "summary": summary, **details}


def read_log(state_dir: Path = STATE_DIR) -> list[dict]:
    entries = []
    try:
        lines = (state_dir / "deploys.jsonl").read_text().splitlines()
    except OSError:
        return entries
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def recent_problems(entries: list[dict], now: datetime, window: timedelta = PROBLEM_WINDOW) -> list[dict]:
    """Log entries inside the window that are not a clean deploy."""
    problems = []
    for entry in entries:
        if entry.get("result") == "deployed":
            continue
        try:
            at = datetime.strptime(entry.get("at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - at <= window:
            problems.append({k: entry.get(k) for k in ("at", "sha", "result", "rollback")})
    return problems


def deploy_status(target: str, state: dict, changed_since_deploy, is_ancestor) -> dict:
    """Decide whether `target` is live. The callables wrap git so tests can fake them.

    changed_since_deploy(deployed, target) -> list of paths, or None if unknown.
    is_ancestor(a, b) -> True when commit a is contained in b.
    """
    deployed = state.get("deployed_sha")
    short = target[:7]
    if not deployed:
        return step("fail", "auto-deploy has never recorded a deploy", target=target)
    if state.get("failed_sha") == target:
        return step("fail", f"{short} failed to deploy ({state.get('last_result', 'unknown')})",
                    target=target, deployed=deployed)
    if deployed == target or is_ancestor(target, deployed):
        return step("ok", f"{short} is live (deployed {deployed[:7]} at {state.get('deployed_at', '?')})",
                    target=target, deployed=deployed)
    changed = changed_since_deploy(deployed, target)
    if changed is not None and not any(p.startswith(DEPLOY_PATHS) for p in changed):
        return step("ok", f"{short} changes no builder code; {deployed[:7]} is still the live code",
                    target=target, deployed=deployed)
    if state.get("waiting_sha") == target:
        return step("wait", f"{short} waits: {state.get('waiting_reason', 'CI')}",
                    target=target, deployed=deployed)
    return step("wait", f"{short} not deployed yet (live: {deployed[:7]}); auto-deploy runs every 5 min",
                target=target, deployed=deployed)


def check_deploy(target: str, state_dir: Path = STATE_DIR, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        state = json.loads((state_dir / "state.json").read_text())
    except (OSError, ValueError):
        state = {}

    def changed(old: str, new: str):
        try:
            return git("diff", "--name-only", old, new).splitlines()
        except subprocess.SubprocessError:
            return None

    def ancestor(a: str, b: str) -> bool:
        return subprocess.run(["git", "-C", str(REPO_DIR), "merge-base", "--is-ancestor", a, b],
                              capture_output=True).returncode == 0

    result = deploy_status(target, state, changed, ancestor)
    problems = recent_problems(read_log(state_dir), now)
    result["recent_problems"] = problems
    own = [p for p in problems if p.get("sha") == target]
    if own and result["status"] != "fail":
        result = {**result, "status": "fail", "summary": f"{target[:7]}: {own[-1]['result']} in the deploy log"}
    return result


def fetch(url: str, timeout: float = 20) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, OSError) as error:
        return 0, str(error)


def check_health(site: str, expect: list[str], fetcher=fetch) -> dict:
    code, body = fetcher(site)
    if code != 200:
        return step("fail", f"{site} answered {code or 'nothing'}", code=code)
    missing = [text for text in expect if text not in body]
    if missing:
        return step("fail", f"served page lacks {', '.join(missing)}", code=code, missing=missing)
    found = f"; found {len(expect)} expected text(s)" if expect else ""
    return step("ok", f"{site} answered 200{found}", code=code)


def parse_unittest(output: str) -> tuple[int | None, bool, list[str]]:
    ran = re.search(r"^Ran (\d+) tests? in", output, re.M)
    failed = re.findall(r"^(?:FAIL|ERROR): (\S+ \([^)]*\))", output, re.M)
    passed = bool(re.search(r"^OK(?: \(.*\))?$", output, re.M))
    return (int(ran.group(1)) if ran else None), passed, failed


def check_tests(target: str, python: str = sys.executable) -> dict:
    tree = Path(tempfile.mkdtemp(prefix="cc-verify-"))
    try:
        git("worktree", "add", "--quiet", "--detach", str(tree), target)
        env = {**os.environ, "PYTHONPATH": "builder"}
        unit = subprocess.run([python, "-m", "unittest", "discover", "-s", "builder/tests"],
                              cwd=tree, env=env, capture_output=True, text=True, timeout=900)
        ran, passed, failed = parse_unittest(unit.stderr + unit.stdout)
        compiled = subprocess.run([python, "-m", "compileall", "-q", "builder"],
                                  cwd=tree, capture_output=True, text=True, timeout=300)
        feed = subprocess.run([python, "-m", "json.tool", "live-feed.json"],
                              cwd=tree, capture_output=True, text=True, timeout=60)
    finally:
        subprocess.run(["git", "-C", str(REPO_DIR), "worktree", "remove", "--force", str(tree)],
                       capture_output=True)
        shutil.rmtree(tree, ignore_errors=True)
    details = {"ran": ran, "failed": failed[:20], "compile_ok": compiled.returncode == 0,
               "feed_ok": feed.returncode == 0}
    if unit.returncode == 0 and passed and compiled.returncode == 0 and feed.returncode == 0:
        return step("ok", f"Ran {ran} tests: OK; compile ok; live-feed.json ok", **details)
    problems = []
    if unit.returncode != 0 or not passed:
        problems.append(f"tests failed ({len(failed)}): {', '.join(failed[:5])}" if failed
                        else f"unittest exit {unit.returncode}")
    if compiled.returncode != 0:
        problems.append("compileall failed")
    if feed.returncode != 0:
        problems.append("live-feed.json is not valid JSON")
    return step("fail", "; ".join(problems), **details)


class Chrome:
    """Minimal DevTools client over --remote-debugging-pipe (standard library only)."""

    def __init__(self, binary: str):
        self.profile = tempfile.mkdtemp(prefix="cc-verify-chrome-")
        to_chrome_r, self._out = os.pipe()
        self._in, from_chrome_w = os.pipe()

        def wire_pipes():
            # Chrome reads commands from fd 3 and writes replies to fd 4.
            a, b = os.dup(to_chrome_r), os.dup(from_chrome_w)
            os.dup2(a, 3)
            os.dup2(b, 4)

        self.proc = subprocess.Popen(
            [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
             "--mute-audio", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=wire_pipes, pass_fds=(3, 4),
        )
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self._buffer = b""
        self._next_id = 0
        self.events: list[dict] = []

    def _read(self, deadline: float) -> dict | None:
        while b"\0" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self._in], [], [], left)
            if not ready:
                return None
            chunk = os.read(self._in, 1 << 20)
            if not chunk:
                raise RuntimeError("Chrome closed the DevTools pipe")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)

    def send(self, method: str, params: dict | None = None, session: str | None = None,
             timeout: float = 30) -> dict:
        self._next_id += 1
        message = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self._out, json.dumps(message).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            reply = self._read(deadline)
            if reply is None:
                raise TimeoutError(f"{method} got no reply in {timeout}s")
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})
            self.events.append(reply)

    def pump(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while (event := self._read(deadline)) is not None:
            self.events.append(event)

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for fd in (self._in, self._out):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)


def find_chrome() -> str | None:
    for candidate in CHROME_PATHS:
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if path and os.path.exists(path):
            return path
    return None


def page_errors(events: list[dict], session: str) -> list[str]:
    errors = []
    for event in events:
        if event.get("sessionId") != session:
            continue
        if event.get("method") == "Runtime.exceptionThrown":
            details = event["params"]["exceptionDetails"]
            text = (details.get("exception") or {}).get("description") or details.get("text", "")
            errors.append(text.splitlines()[0][:200] if text else "exception")
    return errors


def shoot(chrome: Chrome, url: str, name: str, width: int, height: int, mobile: bool,
          out_dir: Path, settle: float = 3.0) -> dict:
    target = chrome.send("Target.createTarget", {"url": "about:blank"})["targetId"]
    session = chrome.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
    for method in ("Page.enable", "Runtime.enable"):
        chrome.send(method, session=session)
    chrome.send("Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": 2 if mobile else 1, "mobile": mobile},
                session=session)
    if mobile:
        chrome.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=session)
    chrome.send("Page.navigate", {"url": url}, session=session)
    deadline = time.monotonic() + 30
    loaded = False
    while not loaded and time.monotonic() < deadline:
        event = chrome._read(deadline)
        if event is None:
            break
        chrome.events.append(event)
        loaded = event.get("method") == "Page.loadEventFired" and event.get("sessionId") == session
    chrome.pump(settle)
    probe = chrome.send("Runtime.evaluate", {
        "expression": "JSON.stringify({w: innerWidth, h: innerHeight,"
                      " scroll: document.documentElement.scrollWidth, title: document.title})",
        "returnByValue": True}, session=session)
    metrics = json.loads(probe["result"]["value"])
    shot = chrome.send("Page.captureScreenshot", {"format": "png"}, session=session)
    path = out_dir / f"{name}.png"
    path.write_bytes(base64.b64decode(shot["data"]))
    chrome.send("Target.closeTarget", {"targetId": target})
    return {"name": name, "path": str(path), "loaded": loaded, "viewport": [metrics["w"], metrics["h"]],
            "scroll_width": metrics["scroll"], "errors": page_errors(chrome.events, session)}


def judge_shots(shots: list[dict], expected: dict[str, tuple[int, int]]) -> dict:
    problems = []
    for shot in shots:
        width, height = expected[shot["name"]]
        if not shot["loaded"]:
            problems.append(f"{shot['name']}: page did not finish loading")
        if shot["viewport"] != [width, height]:
            problems.append(f"{shot['name']}: viewport {shot['viewport']} instead of {[width, height]}")
        if shot["scroll_width"] > width:
            problems.append(f"{shot['name']}: page is {shot['scroll_width']}px wide, scrolls sideways")
        if shot["errors"]:
            problems.append(f"{shot['name']}: page error: {shot['errors'][0]}")
    paths = [shot["path"] for shot in shots]
    if problems:
        return step("fail", "; ".join(problems), shots=shots)
    return step("ok", "screenshots: " + ", ".join(paths), shots=shots)


def check_screens(url: str, out_dir: Path) -> dict:
    binary = find_chrome()
    if not binary:
        return step("skip", "no Chrome or Chromium found; screenshots not taken")
    chrome = Chrome(binary)
    try:
        shots = [shoot(chrome, url, name, w, h, mobile, out_dir) for name, w, h, mobile in VIEWPORTS]
    except (RuntimeError, TimeoutError, OSError, KeyError, ValueError) as error:
        return step("fail", f"browser check broke: {error}")
    finally:
        chrome.close()
    return judge_shots(shots, {name: (w, h) for name, w, h, _ in VIEWPORTS})


def exit_code(steps: dict) -> int:
    statuses = {result["status"] for result in steps.values()}
    if "fail" in statuses:
        return 1
    if "wait" in statuses:
        return 2
    return 0


LABELS = {"ok": "OK  ", "wait": "WAIT", "fail": "FAIL", "skip": "SKIP"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sha", help="commit that must be live (default: origin/main)")
    parser.add_argument("--expect", action="append", default=[], help="text the served page must contain")
    parser.add_argument("--site", default=SITE_URL)
    parser.add_argument("--page", default=PAGE_PATH, help="path for screenshots, relative to --site")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-screens", action="store_true")
    parser.add_argument("--out", type=Path, help="where to write report.json and screenshots")
    args = parser.parse_args(argv)

    git("fetch", "--quiet", "origin", "main")
    target = git("rev-parse", f"{args.sha}^{{commit}}" if args.sha else "origin/main")
    out_dir = args.out or CHECKS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    steps = {"deploy": check_deploy(target), "health": check_health(args.site, args.expect)}
    steps["tests"] = step("skip", "skipped") if args.skip_tests else check_tests(target)
    steps["screens"] = (step("skip", "skipped") if args.skip_screens
                        else check_screens(args.site.rstrip("/") + "/" + args.page.lstrip("/"), out_dir))

    code = exit_code(steps)
    report = {"checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "target": target, "exit_code": code, "steps": steps}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for name, result in steps.items():
        print(f"{LABELS[result['status']]} {name:<8} {result['summary']}")
    for problem in steps["deploy"].get("recent_problems", []):
        print(f"     deploy log: {problem['at']} {str(problem.get('sha'))[:7]} {problem['result']}")
    print(f"report: {out_dir / 'report.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
