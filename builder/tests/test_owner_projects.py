"""Owner project cards in MAIN MANAGER («Личное»).

A card is a short status plus links to the documents that keep the real record.
It comes from `navigation.command_center.projects` in the private Portfolio
Registry, only for the owner, and never reaches the public page. All data here
is synthetic.
"""
from __future__ import annotations

import io
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.platform_resources import owner_projects_projection

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_owner_projects_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
TOOL = BUILDER / "owner_project_card.py"
SECRET = "Synthetic-private-fact-7f3a"
PUBLIC = {"state": "owner_required", "verified_at": None, "projects": []}


def card(**changes):
    result = {"id": "fixture-project", "name": "FIXTURE PROJECT", "status": "Preparing; nothing filed.",
              "checked": "2026-10-20",
              "facts": [{"label": "Route", "text": SECRET}],
              "tasks": ["Fixture task one", "Fixture task two"],
              "links": [{"label": "Inventory", "url": "https://docs.google.com/document/d/fixture-doc/edit"},
                        {"label": "Checklist", "url": "https://docs.google.com/spreadsheets/d/fixture-sheet/edit"}]}
    result.update(changes)
    return result


def registry(*cards, **block):
    return {"schema_version": 2, "projects": [{"name": "Untouched canonical record"}],
            "navigation": {"command_center": {"platforms": {}, "projects": list(cards), **block}}}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "PORTFOLIO-REGISTRY.json"

    def project(self, data, owner=True):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return owner_projects_projection(self.path, owner=owner)

    def test_owner_sees_card_with_only_allowlisted_fields(self):
        extra = card(private_path="/Users/someone/vault", owner_email="someone@example.com")
        extra["facts"][0]["source_file"] = "/private/never"
        out = self.project(registry(extra))
        self.assertEqual(out["state"], "ready")
        self.assertEqual(out["projects"], [card()])

    def test_anonymous_gets_nothing_and_registry_is_not_read(self):
        self.path.write_text(json.dumps(registry(card())), encoding="utf-8")
        with patch.object(Path, "open", side_effect=AssertionError("read")):
            self.assertEqual(owner_projects_projection(self.path, owner=False), PUBLIC)

    def test_repeated_id_never_shows_a_second_card(self):
        out = self.project(registry(card(), card(status="Older duplicate")))
        self.assertEqual([p["status"] for p in out["projects"]], ["Preparing; nothing filed."])

    def test_unsafe_links_and_overlong_text_are_dropped_not_the_card(self):
        bad_links = [{"label": "Query", "url": "https://docs.google.com/document/d/x/edit?usp=sharing"},
                     {"label": "Other host", "url": "https://example.com/doc"},
                     {"label": "Plain http", "url": "http://docs.google.com/document/d/x"},
                     {"label": "Inventory", "url": "https://docs.google.com/document/d/fixture-doc/edit"}]
        out = self.project(registry(card(links=bad_links, tasks=["x" * 201, "ok"],
                                         facts=[{"label": "L", "text": "y" * 401}, {"label": "Fine", "text": "z"}])))
        shown = out["projects"][0]
        self.assertEqual([link["label"] for link in shown["links"]], ["Inventory"])
        self.assertEqual(shown["tasks"], ["ok"])
        self.assertEqual(shown["facts"], [{"label": "Fine", "text": "z"}])

    def test_card_without_id_name_or_status_is_skipped(self):
        out = self.project(registry(card(id="Bad Id"), card(id="no-name", name=""), card(id="no-status", status=None),
                                    card(id="kept")))
        self.assertEqual([p["id"] for p in out["projects"]], ["kept"])

    def test_missing_or_broken_registry_is_honest(self):
        self.assertEqual(owner_projects_projection(self.path, owner=True)["state"], "not_configured")
        self.assertEqual(self.project({"schema_version": 2, "navigation": {"command_center": {"projects": {}}}})["state"],
                         "unavailable")
        self.assertEqual(self.project({"schema_version": 1})["state"], "unavailable")

    def test_projects_only_registry_keeps_platform_links_ready(self):
        from dashboard_builder.platform_resources import platform_resources_projection
        self.path.write_text(json.dumps({"schema_version": 2, "navigation": {"command_center": {"projects": [card()]}}}))
        self.assertEqual(platform_resources_projection(self.path, owner=True)["state"], "ready")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.vault = self.home / "fixture-vault"
        path = self.vault / "35-Systems" / "PORTFOLIO-REGISTRY.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(registry(card())))

    def call(self, host="command.meshly.fr", token=None, cloud_owner=False):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/owner-projects", "GET"
        handler.headers = {"Host": host}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        handler.wfile = io.BytesIO()
        out = {"headers": {}}
        handler.send_response = lambda status, *args: out.update(status=status)
        handler.send_header = lambda key, value: out["headers"].update({key.lower(): str(value)})
        handler.end_headers = lambda: None
        with patch.object(SERVER, "HOME", self.home), patch.object(SERVER, "JARVIS_VAULT_ROOT", self.vault), \
             patch.object(SERVER, "_dashboard_run_token", return_value="synthetic-owner-token"), \
             patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=cloud_owner):
            handler.do_GET()
        out["body"] = handler.wfile.getvalue().decode("utf-8")
        return out

    def test_every_host_needs_strict_owner(self):
        for host in ("localhost:7777", "127.0.0.1:7777", "command.meshly.fr", "spoofed.invalid"):
            for token in (None, "wrong"):
                with self.subTest(host=host, token=token):
                    out = self.call(host=host, token=token)
                    self.assertEqual(json.loads(out["body"]), PUBLIC)
                    self.assertNotIn(SECRET, out["body"])
                    self.assertIn("no-store", out["headers"]["cache-control"])

    def test_owner_by_token_or_google_login_gets_card(self):
        for options in ({"token": "synthetic-owner-token"}, {"cloud_owner": True}):
            with self.subTest(options=options):
                out = self.call(**options)
                self.assertEqual(json.loads(out["body"])["projects"], [card()])
                self.assertNotIn("Untouched canonical record", out["body"])


class UpsertToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "PORTFOLIO-REGISTRY.json"
        self.path.write_text(json.dumps({"schema_version": 2, "projects": [{"name": "Untouched canonical record"}],
                                         "navigation": {"command_center": {"platforms": {"jarvis": {"resources": []}}}}}))

    def run_tool(self, payload):
        return subprocess.run([sys.executable, str(TOOL), "--registry", str(self.path)], input=json.dumps(payload),
                              capture_output=True, text=True, check=False)

    def test_add_then_update_keeps_one_card_and_the_rest_of_the_registry(self):
        self.assertEqual(self.run_tool(card()).returncode, 0)
        result = self.run_tool(card(status="Updated status"))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["projects"], [{"name": "Untouched canonical record"}])
        self.assertEqual(data["navigation"]["command_center"]["platforms"], {"jarvis": {"resources": []}})
        cards = data["navigation"]["command_center"]["projects"]
        self.assertEqual([c["status"] for c in cards], ["Updated status"])
        self.assertEqual(len(list(self.path.parent.glob("PORTFOLIO-REGISTRY.json.bak-*"))) >= 1, True)
        self.assertEqual(owner_projects_projection(self.path, owner=True)["projects"], [card(status="Updated status")])

    def test_card_the_server_would_trim_is_refused_and_registry_unchanged(self):
        before = self.path.read_text()
        result = self.run_tool(card(links=[{"label": "Bad", "url": "https://docs.google.com/d?x=1"}]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.path.read_text(), before)

    def test_missing_registry_is_not_created(self):
        self.path.unlink()
        self.assertEqual(self.run_tool(card()).returncode, 2)
        self.assertFalse(self.path.exists())


class PageTests(unittest.TestCase):
    def test_owner_cards_are_loaded_at_runtime_never_baked_into_the_page(self):
        page = (BUILDER / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mm-owner-projects" hidden', page)
        self.assertIn("/api/owner-projects", page)


if __name__ == "__main__":
    unittest.main()
