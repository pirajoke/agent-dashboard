"""Project navigation contract (AC-2/3/4, EC-1/2/3/4).

All links are synthetic fixtures, never the owner's private registry.
Projection API: platform_resources_projection(path, owner=False) ->
{state: owner_required|not_configured|unavailable|ready, verified_at: str|None,
 platforms: {runtime_id: {resources: [{kind,label,url,scope}], note?: str}}}.
Bounds: 1 MiB input; 8 resources/card; label 120, note 400, URL 2048 chars.
A rejected resource must not discard a valid independent neighboring resource.
"""
from __future__ import annotations

import copy
import http.server
import importlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_navigation_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
try:
    RESOURCES = importlib.import_module("dashboard_builder.platform_resources")
except ModuleNotFoundError as exc:
    if exc.name != "dashboard_builder.platform_resources":
        raise
    RESOURCES = None

PLATFORM_IDS = {"financial", "mydictionary", "health", "ai-singularity", "context-news", "accountable",
                "jarvis", "property-os", "pixel-agents", "closeness-mirror", "sushi-parisien", "n8n"}
VERIFIED = "2026-10-19T16:00:00Z"
FIXTURE_URL = "https://github.com/example/navigation-fixture"
PUBLIC = {"state": "owner_required", "verified_at": None, "platforms": {}}


def resource(**changes):
    result = {"kind": "code", "label": "Synthetic project source", "url": FIXTURE_URL, "scope": "current"}
    result.update(changes)
    return result


def registry():
    return {"schema_version": 2, "private_owner_name": "Never-project-this-owner", "projects": [], "navigation": {
        "command_center": {"verified_at": VERIFIED, "platforms": {
            "financial": {"resources": [resource()], "note": "Synthetic registry only"}}}}}


class PlatformResourceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(RESOURCES, "RED: owner navigation projection is not implemented")
        self.assertTrue(callable(getattr(RESOURCES, "platform_resources_projection", None)),
                        "RED: missing platform_resources_projection(path, owner=False) contract")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "PORTFOLIO-REGISTRY.json"

    def project(self, data=None, owner=True):
        if data is not None:
            self.path.write_text(json.dumps(data), encoding="utf-8")
        return RESOURCES.platform_resources_projection(self.path, owner=owner)

    def test_ac_3_owner_projects_only_allowlisted_fields_and_existing_ids(self):
        data = registry()
        block = data["navigation"]["command_center"]
        block["private_debug"] = "/private/fixture/never-serve"
        block["platforms"]["invented-project"] = {"resources": [resource(label="Private unknown card")]}
        block["platforms"]["financial"]["owner_name"] = "Private name"
        block["platforms"]["financial"]["resources"][0]["token"] = "private-extra"
        out = self.project(data)
        self.assertEqual(out, {"state": "ready", "verified_at": VERIFIED, "platforms": {
            "financial": {"resources": [resource()], "note": "Synthetic registry only"}}})
        self.assertLessEqual(set(out["platforms"]), PLATFORM_IDS)

    def test_ac_3_all_supported_kinds_and_scopes_survive_with_meaning(self):
        data = registry()
        items = [resource(kind=kind, scope=scope, label=f"Fixture {kind}")
                 for kind, scope in zip(("documents", "notes", "code", "tasks"),
                                        ("current", "archive", "upstream", "reference"))]
        data["navigation"]["command_center"]["platforms"]["financial"]["resources"] = items
        self.assertEqual(self.project(data)["platforms"]["financial"]["resources"], items)

    def test_ec_3_anonymous_does_not_read_stat_or_disclose_registry(self):
        self.path.write_text(json.dumps(registry()))
        with patch.object(Path, "read_text", side_effect=AssertionError("private read")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("private read")), \
             patch.object(Path, "stat", side_effect=AssertionError("private stat")), \
             patch("builtins.open", side_effect=AssertionError("private open")):
            self.assertEqual(self.project(owner=False), PUBLIC)
        self.assertEqual(self.project({"private": "secret"}, owner=False), PUBLIC)

    def test_ec_1_missing_registry_or_navigation_is_honest_and_bounded(self):
        for data in (None, {"schema_version": 2, "projects": []}, {"schema_version": 2, "navigation": {}}):
            with self.subTest(data=data):
                out = self.project(data)
                self.assertEqual(out, {"state": "not_configured", "verified_at": None, "platforms": {}})

    def test_ec_1_malformed_schema_is_unavailable_without_raw_contents(self):
        for data in ([], "private-bad-value", {"schema_version": 1}, {"schema_version": 2, "navigation": []},
                     {"schema_version": 2, "navigation": {"command_center": []}},
                     {"schema_version": 2, "navigation": {"command_center": {"platforms": []}}}):
            with self.subTest(data=data):
                out = self.project(data)
                self.assertEqual(out, {"state": "unavailable", "verified_at": None, "platforms": {}})
        self.path.write_text('{"private-bad-value":')
        self.assertEqual(self.project(), {"state": "unavailable", "verified_at": None, "platforms": {}})

    def test_ec_1_oversized_and_unreadable_registry_fail_closed(self):
        self.path.write_bytes(b" " * (1024 * 1024 + 1))
        expected = {"state": "unavailable", "verified_at": None, "platforms": {}}
        self.assertEqual(self.project(), expected)
        self.path.unlink()
        self.path.mkdir()  # Deterministic unreadable-as-file fixture, including under root.
        self.assertEqual(self.project(), expected)

    def test_ec_1_deeply_nested_json_is_bounded_unavailable(self):
        self.path.write_text('[' * 2000 + '0' + ']' * 2000, encoding="utf-8")
        try:
            result = self.project()
        except RecursionError:
            self.fail("Deep JSON must return bounded unavailable, not raise RecursionError")
        self.assertEqual(result, {"state": "unavailable", "verified_at": None, "platforms": {}})

    def test_ec_1_malformed_utf8_is_bounded_unavailable(self):
        self.path.write_bytes(b'\xff\xfeprivate-corrupt-fixture')
        self.assertEqual(self.project(), {"state": "unavailable", "verified_at": None, "platforms": {}})

    def test_ec_2_reject_unsafe_urls_but_keep_valid_neighbors(self):
        urls = ("javascript:alert(1)", "file:///private/fixture", "http://github.com/example/repo",
                "https://127.0.0.1/", "https://localhost/", "https://192.168.1.1/", "https://[::1]/",
                "https://10.0.0.1/", "https://172.16.0.1/", "https://github.com.evil.invalid/x",
                "https://evil.invalid/github.com", "https://user:pass@github.com/example/repo",
                "https://github.com:8443/example/repo", "https://github.com/example/repo?token=secret",
                "https://drive.google.com/drive/folders/fixture#token", "https://github.com/\nrepo",
                "https://github.com/example/%0Arepo", "https://github.com/example/" + "x" * 2048,
                "https://github.com:bad/example", "https://github.com:99999/example", "https://github.com:/example",
                "https://github.com/example?", "https://github.com/example#", "https://github.com\\example/repo",
                "https://github.com/example/%5Crepo", " https://github.com/example/repo", "https://github.com/example/repo ")
        for url in urls:
            with self.subTest(url=url):
                data = registry()
                data["navigation"]["command_center"]["platforms"]["financial"]["resources"] = [resource(url=url), resource()]
                self.assertEqual(self.project(data)["platforms"]["financial"]["resources"], [resource()])

    def test_ec_2_invalid_resource_types_bounds_and_unknown_values_are_isolated(self):
        invalid = (None, "bad", [], resource(kind="other"), resource(scope="guess"), resource(label=99),
                   resource(url=[]), resource(label=""), resource(label="   "), resource(label="\u200b"), resource(label="x" * 121), resource(label="bad\x00text"))
        for item in invalid:
            with self.subTest(item=item):
                data = registry()
                data["navigation"]["command_center"]["platforms"]["financial"]["resources"] = [item, resource()]
                self.assertEqual(self.project(data)["platforms"]["financial"]["resources"], [resource()])
        data = registry()
        entry = data["navigation"]["command_center"]["platforms"]["financial"]
        entry["resources"] = [resource(label=f"Fixture {i}") for i in range(100)]
        entry["note"] = "x" * 401
        out = self.project(data)["platforms"]["financial"]
        self.assertLessEqual(len(out["resources"]), 8)
        self.assertLessEqual(len(out.get("note", "")), 400)

    def test_ec_2_bad_platform_does_not_drop_independent_valid_platform(self):
        for value in (None, [], "bad", {"resources": "bad"}):
            data = registry()
            data["navigation"]["command_center"]["platforms"]["jarvis"] = value
            with self.subTest(value=value):
                out = self.project(data)
                self.assertEqual(out["platforms"]["financial"]["resources"], [resource()])
                self.assertNotIn("jarvis", out["platforms"])

    def test_ac_3_invalid_verification_date_is_not_presented_as_fresh(self):
        for value in (None, [], "not-a-date", "2026-99-99"):
            data = registry()
            data["navigation"]["command_center"]["verified_at"] = value
            with self.subTest(value=value):
                out = self.project(data)
                self.assertIsNone(out["verified_at"])
                self.assertEqual(out["platforms"]["financial"]["resources"], [resource()])


class PlatformResourcesEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.vault = self.home / "fixture-vault"
        self.registry = self.vault / "35-Systems" / "PORTFOLIO-REGISTRY.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps(registry()))
        (self.home / "registry-alias.json").symlink_to(self.registry)
        (self.home / "vault-alias").symlink_to(self.vault, target_is_directory=True)

    def call(self, path="/api/platform-resources", method="GET", host="localhost:7777", token=None, cloud_owner=False):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = path, method
        handler.headers = {"Host": host}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        handler.wfile = io.BytesIO()
        out = {"headers": {}}
        handler.send_response = lambda status, *args: out.update(status=status)
        handler.send_header = lambda key, value: out["headers"].update({key.lower(): str(value)})
        handler.end_headers = lambda: None
        handler.send_error = lambda status, *args: out.update(status=status)
        with patch.object(SERVER, "HOME", self.home), patch.object(SERVER, "JARVIS_VAULT_ROOT", self.vault), \
             patch.object(SERVER, "_dashboard_run_token", return_value="synthetic-owner-token"), \
             patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=cloud_owner), \
             patch.object(SERVER.subprocess, "Popen") as popen:
            getattr(handler, f"do_{method}")()
            popen.assert_not_called()
        out["body"] = handler.wfile.getvalue().decode("utf-8")
        return out

    def test_ac_2_all_host_names_require_strict_owner_auth(self):
        for host in ("localhost:7777", "127.0.0.1:7777", "command.meshly.fr", "spoofed.invalid"):
            for token in (None, "wrong", "é"):
                with self.subTest(host=host, token=token):
                    out = self.call(host=host, token=token)
                    self.assertIn(out["status"], (200, 401))
                    self.assertEqual(json.loads(out["body"]), PUBLIC)
                    self.assertIn("no-store", out["headers"].get("cache-control", ""))

    def test_ac_2_ac_3_owner_token_and_existing_access_login_use_private_registry(self):
        for host in ("localhost:7777", "command.meshly.fr", "spoofed.invalid"):
            for options in ({"token": "synthetic-owner-token"}, {"cloud_owner": True}):
                with self.subTest(host=host, options=options):
                    out = self.call(host=host, **options)
                    self.assertEqual(out["status"], 200)
                    self.assertEqual(json.loads(out["body"])["platforms"]["financial"]["resources"], [resource()])
                    self.assertIn("no-store", out["headers"].get("cache-control", ""))
                    self.assertNotIn("Never-project-this-owner", out["body"])

    def test_ac_2_direct_get_head_and_symlink_aliases_never_serve_registry(self):
        paths = ("/fixture-vault/35-Systems/PORTFOLIO-REGISTRY.json", "/registry-alias.json",
                 "/vault-alias/35-Systems/PORTFOLIO-REGISTRY.json",
                 "/fixture-vault/35-Systems/../35-Systems/PORTFOLIO-REGISTRY.json")
        for method in ("GET", "HEAD"):
            for path in paths:
                for token in (None, "synthetic-owner-token"):
                    with self.subTest(method=method, path=path, owner=token is not None):
                        out = self.call(path=path, method=method, token=token)
                        self.assertEqual(out["status"], 403)
                        self.assertEqual(out["body"], "")

    def test_ac_2_implicit_directory_index_symlinks_never_serve_registry(self):
        # SimpleHTTPRequestHandler selects an index only after translating the
        # directory. Guard the selected file too, including HEAD and owner calls.
        for filename in ("index.html", "index.htm"):
            alias = self.home / ("directory-alias-" + filename.split(".")[-1])
            alias.mkdir()
            (alias / filename).symlink_to(self.registry)
            for method in ("GET", "HEAD"):
                for host in ("localhost:7777", "127.0.0.1:7777", "spoofed.invalid", "command.meshly.fr"):
                    for token in (None, "synthetic-owner-token"):
                        with self.subTest(index=filename, method=method, host=host, owner=token is not None):
                            out = self.call(path=f"/{alias.name}/", method=method, host=host, token=token)
                            self.assertIn(out["status"], (403, 404),
                                          "An implicit index must not bypass private registry protection")
                            self.assertEqual(out["body"], "")

    def test_ec_3_anonymous_route_does_not_open_registry(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("anonymous read forbidden")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("anonymous read forbidden")), \
             patch("builtins.open", side_effect=AssertionError("anonymous open forbidden")):
            out = self.call(host="command.meshly.fr")
        self.assertEqual(json.loads(out["body"] or "{}"), PUBLIC)

    def test_ec_1_endpoint_read_failure_is_bounded_and_never_cached(self):
        self.registry.write_text("private malformed contents")
        out = self.call(token="synthetic-owner-token")
        self.assertIn(out["status"], (200, 503))
        self.assertEqual(json.loads(out["body"]), {"state": "unavailable", "verified_at": None, "platforms": {}})
        self.assertIn("no-store", out["headers"].get("cache-control", ""))


if __name__ == "__main__":
    unittest.main()
