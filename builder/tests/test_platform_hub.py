from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import importlib
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
STATIC_INDEX = BUILDER_DIR.parent / "index.html"

EXPECTED_PLATFORM_IDS = (
    "financial-os",
    "mydictionary",
    "health-os",
    "ai-singularity",
    "context-news",
    "accountable-os",
    "jarvis",
)
EXPECTED_PLATFORM_NAMES = (
    "JobRadar / Financial OS",
    "MyDictionary",
    "Health OS",
    "AI Singularity",
    "Context News France",
    "Accountable OS",
    "JARVIS",
)
EXPECTED_LINKS = {
    "financial-os": (
        "http://127.0.0.1:8792",
        "https://t.me/JobsRadarS_bot",
    ),
    "mydictionary": (
        "http://127.0.0.1:8787/admin",
        "https://t.me/max_context_bot",
    ),
    "health-os": ("https://health.meshly.fr/",),
    "ai-singularity": ("http://127.0.0.1:8001",),
    "context-news": (
        "http://127.0.0.1:8002",
        "https://t.me/croissantfr_bot",
    ),
    "accountable-os": ("http://127.0.0.1:4174",),
    "jarvis": ("https://t.me/max_jarvis_hoian_bot",),
}
EXPECTED_LOOPBACK_PORTS = (7777, 8792, 8787, 8001, 8002, 4174)
REQUIRED_PLATFORM_FIELDS = ("id", "name", "description", "tier", "status", "actions")
REQUIRED_ACTION_FIELDS = ("label", "url", "access")


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def _external_links(markup: str) -> list[dict[str, str]]:
    parser = _LinkParser()
    parser.feed(markup)
    return [
        link
        for link in parser.links
        if link.get("href", "").startswith(("http://", "https://"))
    ]


def _platforms_by_id(registry) -> dict[str, dict]:
    return {platform["id"]: platform for platform in registry}


class PlatformHubContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.platforms = importlib.import_module("dashboard_builder.platforms")
        except Exception as exc:  # keep RED discovery explicit rather than aborting import
            self.fail(
                "RED: missing public dashboard_builder.platforms contract "
                f"({type(exc).__name__}: {exc})"
            )

        required = (
            "PLATFORM_REGISTRY",
            "validate_platform_registry",
            "build_platform_hub_html",
            "build_tunnel_command",
        )
        missing = [name for name in required if not hasattr(self.platforms, name)]
        if missing:
            self.fail(f"RED: missing platform hub exports: {', '.join(missing)}")

    def _registry(self):
        return self.platforms.PLATFORM_REGISTRY

    def _mutable_registry(self):
        return deepcopy(list(self._registry()))

    def test_ac_cc_1_registry_is_the_exact_seven_surface_release(self):
        registry = self._registry()
        self.assertIsInstance(registry, (tuple, list))
        self.assertEqual(tuple(item["id"] for item in registry), EXPECTED_PLATFORM_IDS)
        self.assertEqual(tuple(item["name"] for item in registry), EXPECTED_PLATFORM_NAMES)
        self.assertEqual(len(registry), 7)
        for platform in registry:
            with self.subTest(platform=platform.get("id")):
                for field in REQUIRED_PLATFORM_FIELDS:
                    self.assertIn(field, platform)
                    self.assertTrue(platform[field], f"{platform.get('id')} has an empty {field}")

    def test_ac_cc_2_registry_has_exactly_two_primary_product_lanes(self):
        registry = self._registry()
        primary = [item for item in registry if item["tier"] == "primary"]
        active = [item for item in registry if item["tier"] == "active"]
        self.assertEqual([item["id"] for item in primary], ["financial-os", "mydictionary"])
        self.assertEqual([item["id"] for item in active], list(EXPECTED_PLATFORM_IDS[2:]))

        html = self.platforms.build_platform_hub_html()
        self.assertEqual(html.count('data-platform-tier="primary"'), 2)
        self.assertEqual(html.count('data-platform-tier="active"'), 5)
        self.assertLess(html.index("Primary products"), html.index("Active systems"))

    def test_ac_cc_3_registry_uses_exact_current_destinations(self):
        by_id = _platforms_by_id(self._registry())
        for platform_id, expected in EXPECTED_LINKS.items():
            with self.subTest(platform=platform_id):
                actual = tuple(action["url"] for action in by_id[platform_id]["actions"])
                self.assertEqual(actual, expected)
                for action in by_id[platform_id]["actions"]:
                    for field in REQUIRED_ACTION_FIELDS:
                        self.assertIn(field, action)
                        self.assertTrue(action[field])

    def test_ac_cc_4_external_links_are_semantic_and_hardened(self):
        html = self.platforms.build_platform_hub_html()
        links = _external_links(html)
        expected_urls = {url for urls in EXPECTED_LINKS.values() for url in urls}
        self.assertEqual({link.get("href") for link in links}, expected_urls)
        for link in links:
            with self.subTest(url=link.get("href")):
                self.assertEqual(link.get("target"), "_blank")
                self.assertEqual(set(link.get("rel", "").split()), {"noopener", "noreferrer"})
                self.assertNotIn("onclick", link)

    def test_ac_cc_4_explicit_localhost_http_and_approved_https_are_accepted(self):
        registry = self._mutable_registry()
        registry[0]["actions"][0]["url"] = "http://localhost:8792/"
        self.platforms.validate_platform_registry(registry)
        html = self.platforms.build_platform_hub_html(registry=registry)
        self.assertIn('href="http://localhost:8792/"', html)
        self.assertIn('href="https://health.meshly.fr/"', html)

    def test_ac_cc_6_tunnel_command_covers_hub_and_every_loopback_once(self):
        command = self.platforms.build_tunnel_command()
        self.assertIsInstance(command, str)
        self.assertTrue(command.startswith("ssh -N "), command)
        self.assertTrue(command.endswith("ubuntu@51.255.36.141"), command)
        self.assertEqual(command.count("ssh "), 1)
        for port in EXPECTED_LOOPBACK_PORTS:
            with self.subTest(port=port):
                forward = f"-L {port}:127.0.0.1:{port}"
                self.assertEqual(command.count(forward), 1, command)

        rendered = self.platforms.build_platform_hub_html()
        self.assertIn("Secure access", rendered)
        self.assertIn("SSH tunnel", rendered)
        self.assertIn("<code", rendered)
        self.assertIn("data-copy", rendered)
        self.assertIn("aria-label", rendered)

    def test_ac_cc_7_access_state_is_visible_text_not_color_only(self):
        registry = self._registry()
        for platform in registry:
            with self.subTest(platform=platform["id"]):
                self.assertIsInstance(platform["status"], str)
                self.assertTrue(platform["status"].strip())
        html = self.platforms.build_platform_hub_html()
        for label in ("Private OVH", "Public HTTPS", "Telegram"):
            self.assertIn(label, html)

    def test_ec_cc_1_health_link_is_stable_copy_not_a_live_health_claim(self):
        health = _platforms_by_id(self._registry())["health-os"]
        self.assertEqual(tuple(action["url"] for action in health["actions"]), EXPECTED_LINKS["health-os"])
        health_copy = " ".join(
            str(health.get(field, "")) for field in ("name", "description", "status")
        ).lower()
        self.assertNotRegex(health_copy, r"\b(?:live|healthy|online|available now)\b")
        self.assertRegex(health_copy, r"\b(?:stable|static|destination|public)\b")

    def test_ec_cc_2_telegram_only_jarvis_has_no_placeholder_admin_action(self):
        jarvis = _platforms_by_id(self._registry())["jarvis"]
        self.assertEqual(len(jarvis["actions"]), 1)
        self.assertEqual(jarvis["actions"][0]["url"], "https://t.me/max_jarvis_hoian_bot")
        self.assertEqual(jarvis["actions"][0]["access"], "telegram")
        self.assertNotRegex(repr(jarvis).lower(), r"placeholder|coming soon|admin unavailable")

    def test_err_cc_1_invalid_registry_shape_fails_closed(self):
        validate = self.platforms.validate_platform_registry
        canonical = self._mutable_registry()

        duplicate = deepcopy(canonical)
        duplicate[-1]["id"] = duplicate[0]["id"]
        missing_action = deepcopy(canonical)
        missing_action[0]["actions"] = []
        wrong_primary_count = deepcopy(canonical)
        wrong_primary_count[1]["tier"] = "active"

        invalid = [duplicate, missing_action, wrong_primary_count]
        for field in REQUIRED_PLATFORM_FIELDS:
            missing_field = deepcopy(canonical)
            missing_field[0].pop(field, None)
            invalid.append(missing_field)
        for field in REQUIRED_ACTION_FIELDS:
            missing_action_field = deepcopy(canonical)
            missing_action_field[0]["actions"][0].pop(field, None)
            invalid.append(missing_action_field)

        for index, registry in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises((TypeError, ValueError)):
                    validate(registry)

    def test_err_cc_2_unsafe_urls_are_rejected_before_rendering(self):
        unsafe_urls = (
            "http://example.com/admin",
            "http://51.255.36.141:8787/admin",
            "https://example.com/admin",
            "https://evil.t.me/max_context_bot",
            "http://user:password@127.0.0.1:8787/admin",
            "https://t.me/max_context_bot?start=secret",
            "http://127.0.0.1:8787/admin#token",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                registry = self._mutable_registry()
                registry[0]["actions"][0]["url"] = url
                with self.assertRaises((TypeError, ValueError)):
                    self.platforms.validate_platform_registry(registry)
                with self.assertRaises((TypeError, ValueError)):
                    self.platforms.build_platform_hub_html(registry=registry)

    def test_err_cc_3_all_registry_copy_is_html_escaped(self):
        registry = self._mutable_registry()
        registry[0]["name"] = '<script data-x="name">alert(1)</script>'
        registry[0]["description"] = "Owner <b>console</b> & overview"
        registry[0]["status"] = "Private <OVH>"
        registry[0]["actions"][0]["label"] = 'Open <admin> & "review"'
        html = self.platforms.build_platform_hub_html(registry=registry)

        for raw in (
            '<script data-x="name">',
            "<b>console</b>",
            "Private <OVH>",
            "Open <admin>",
        ):
            self.assertNotIn(raw, html)
        for escaped in (
            "&lt;script data-x=&quot;name&quot;&gt;",
            "Owner &lt;b&gt;console&lt;/b&gt; &amp; overview",
            "Private &lt;OVH&gt;",
            "Open &lt;admin&gt; &amp; &quot;review&quot;",
        ):
            self.assertIn(escaped, html)

    def test_security_copy_and_render_never_leak_secrets_or_private_paths(self):
        registry = self._mutable_registry()
        secret_copy = (
            "/Users/mark/.ssh/id_ed25519",
            "/srv/main-manager/.env",
            "BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk",
        )
        for value in secret_copy:
            with self.subTest(value=value):
                tainted = deepcopy(registry)
                tainted[0]["description"] = value
                with self.assertRaises((TypeError, ValueError)):
                    self.platforms.validate_platform_registry(tainted)
                with self.assertRaises((TypeError, ValueError)):
                    self.platforms.build_platform_hub_html(registry=tainted)

        safe_outputs = (
            repr(self._registry()),
            self.platforms.build_tunnel_command(),
            self.platforms.build_platform_hub_html(),
        )
        for rendered in safe_outputs:
            self.assertNotRegex(rendered, r"(?:/Users/|/home/|/srv/|~?/\.ssh/|\.env\b)")
            self.assertNotRegex(rendered, r"\b(?:BOT_TOKEN|API_KEY|PASSWORD)\s*=")
            self.assertNotRegex(rendered, r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")


class PlatformHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.platforms = importlib.import_module("dashboard_builder.platforms")
            self.html_builder = importlib.import_module("dashboard_builder.html_builder")
        except Exception as exc:
            self.fail(
                "RED: Common Center builder integration cannot be imported: "
                f"{type(exc).__name__}: {exc}"
            )

    def _build_dashboard(self) -> str:
        module = self.html_builder
        patches = (
            patch.object(
                module,
                "collect_now_data",
                return_value={"active_agents": 0, "total_agents": 0},
            ),
            patch.object(module, "collect_system_data", return_value={}),
            patch.object(module, "collect_costs_data", return_value={"total_monthly": 0}),
            patch.object(module, "build_now_html", return_value='<section id="now-body"></section>'),
            patch.object(module, "build_system_html", return_value=""),
            patch.object(module, "build_costs_html", return_value=""),
            patch.object(module, "build_command_center_html", return_value='<section id="command-center"></section>'),
            patch.object(module, "build_agent_theater_html", return_value='<section id="theater"></section>'),
            patch.object(module, "build_agent_workshop_html", return_value='<section id="workshop"></section>'),
            patch.object(module, "build_department_campus_html", return_value='<section id="campus"></section>'),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return module.build_html([], "2026-08-23 12:00:00 ICT")

    def test_ac_cc_5_builder_identity_nav_and_first_section_are_common_center(self):
        html = self._build_dashboard()
        self.assertIn("<title>Common Center</title>", html)
        self.assertRegex(html, r'<div class="sidebar-brand">\s*<h1>Common Center</h1>')
        sidebar = html[html.index('<ul class="sidebar-nav">'):html.index('</ul>', html.index('<ul class="sidebar-nav">'))]
        first_nav = re.search(r"<a\b[^>]*>.*?</a>", sidebar, re.DOTALL)
        self.assertIsNotNone(first_nav)
        self.assertIn('href="#common-center"', first_nav.group(0))
        self.assertIn("Common Center", first_nav.group(0))

        main = html[html.index('<main class="main">'):]
        self.assertLess(main.index('id="common-center"'), main.index('id="theater"'))
        for existing in ("theater", "command-center", "now", "projects", "system", "costs"):
            with self.subTest(existing=existing):
                self.assertIn(f'id="{existing}"', main)
                self.assertGreater(main.index(f'id="{existing}"'), main.index('id="common-center"'))

    def test_ac_cc_8_builder_output_and_static_snapshot_share_exact_registry(self):
        built = self._build_dashboard()
        static = STATIC_INDEX.read_text(encoding="utf-8")
        for markup in (built, static):
            with self.subTest(snapshot="built" if markup is built else "static"):
                self.assertIn("<title>Common Center</title>", markup)
                self.assertIn('href="#common-center"', markup)
                self.assertEqual(markup.count('data-platform-id="'), 7)
                for platform_id, platform_name in zip(EXPECTED_PLATFORM_IDS, EXPECTED_PLATFORM_NAMES):
                    self.assertEqual(markup.count(f'data-platform-id="{platform_id}"'), 1)
                    self.assertIn(platform_name, markup)
                hrefs = {link.get("href") for link in _external_links(markup)}
                for expected in {url for urls in EXPECTED_LINKS.values() for url in urls}:
                    self.assertIn(expected, hrefs)

    def test_ac_cc_8_static_snapshot_has_common_center_before_legacy_sections(self):
        static = STATIC_INDEX.read_text(encoding="utf-8")
        main = static[static.index('<main class="main">'):]
        self.assertLess(main.index('id="common-center"'), main.index('id="theater"'))
        for existing in ("command-center", "now", "projects", "system", "costs"):
            self.assertGreater(main.index(f'id="{existing}"'), main.index('id="common-center"'))

    def test_ac_cc_7_ec_cc_3_css_supports_focus_reflow_zoom_and_reduced_motion(self):
        css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.platform-(?:action|link)[^{]*:focus-visible")
        self.assertRegex(css, r"@media\s*\(max-width:\s*(?:[3-9]\d\d|1\d{3})px\)")
        self.assertRegex(css, r"\.platform-(?:primary-grid|grid)[^{]*\{[^}]*grid-template-columns:\s*1fr", re.DOTALL)
        self.assertRegex(css, r"\.platform-[^{]*\{[^}]*min-width:\s*0", re.DOTALL)
        self.assertRegex(css, r"overflow-wrap:\s*(?:anywhere|break-word)")
        reduced_start = css.rfind("@media (prefers-reduced-motion: reduce)")
        self.assertGreaterEqual(reduced_start, 0)
        reduced = css[reduced_start:]
        self.assertIn("animation: none", reduced)
        self.assertIn("transition: none", reduced)

    def test_ac_cc_4_ac_cc_8_static_snapshot_links_are_safe_and_hardened(self):
        static = STATIC_INDEX.read_text(encoding="utf-8")
        external = _external_links(static)
        platform_urls = {url for urls in EXPECTED_LINKS.values() for url in urls}
        platform_links = [link for link in external if link.get("href") in platform_urls]
        self.assertEqual({link.get("href") for link in platform_links}, platform_urls)
        for link in platform_links:
            parsed = urlsplit(link["href"])
            self.assertFalse(parsed.query)
            self.assertFalse(parsed.fragment)
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)
            self.assertEqual(link.get("target"), "_blank")
            self.assertEqual(set(link.get("rel", "").split()), {"noopener", "noreferrer"})
        for forbidden in (
            "/Users/",
            "/home/",
            "/srv/",
            "BOT_TOKEN=",
            "API_KEY=",
            "PASSWORD=",
        ):
            self.assertNotIn(forbidden, static)
        self.assertNotRegex(static, r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")


if __name__ == "__main__":
    unittest.main()
