from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


DASHBOARD_PATH = (
    Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"
)

EXPECTED_PLATFORMS = {
    "financial": (
        "JobRadar / Financial OS",
        (
            "http://127.0.0.1:8792",
            "https://t.me/JobsRadarS_bot",
        ),
    ),
    "mydictionary": (
        "Lexi",
        (
            "http://127.0.0.1:8791/admin",
            "https://t.me/my_dictionnary_tg_bot",
        ),
    ),
    "health": ("Health OS", ("https://health.meshly.fr/",)),
    "ai-singularity": (
        "AI Singularity",
        ("http://127.0.0.1:8790",),
    ),
    "context-news": (
        "Context News France",
        (
            "http://127.0.0.1:8002",
            "https://t.me/croissantfr_bot",
        ),
    ),
    "accountable": (
        "Accountable OS",
        ("http://127.0.0.1:4174",),
    ),
    "jarvis": ("JARVIS", ("https://t.me/max_jarvis_hoian_bot",)),
}


class _CommandCenterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nav_targets: dict[str, str] = {}
        self.platform_section_count = 0
        self.platforms: dict[str, dict[str, object]] = {}
        self._nav_target: str | None = None
        self._nav_text: list[str] = []
        self._platform_id: str | None = None
        self._platform_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        onclick = attributes.get("onclick") or ""
        nav_target = re.fullmatch(r"showSection\(['\"]([^'\"]+)['\"]\)", onclick)
        if tag == "button" and "nav-pill" in classes and nav_target:
            self._nav_target = nav_target.group(1)
            self._nav_text = []

        if attributes.get("id") == "section-platforms":
            self.platform_section_count += 1

        platform_id = attributes.get("data-platform-id")
        if platform_id is not None:
            self._platform_id = platform_id
            self._platform_depth = 1
            self.platforms[platform_id] = {
                "name": attributes.get("data-platform-name"),
                "links": [],
            }
        elif self._platform_id is not None:
            self._platform_depth += 1

        if tag == "a" and self._platform_id is not None:
            links = self.platforms[self._platform_id]["links"]
            assert isinstance(links, list)
            links.append(attributes)

    def handle_data(self, data: str) -> None:
        if self._nav_target is not None:
            self._nav_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._nav_target is not None:
            self.nav_targets[self._nav_target] = " ".join(
                "".join(self._nav_text).split()
            )
            self._nav_target = None
            self._nav_text = []

        if self._platform_id is not None:
            self._platform_depth -= 1
            if self._platform_depth == 0:
                self._platform_id = None


class CommandCenterPlatformsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = DASHBOARD_PATH.read_text(encoding="utf-8")
        cls.parser = _CommandCenterParser()
        cls.parser.feed(cls.html)

    def test_historical_command_center_identity_is_preserved(self):
        self.assertIn("Hello, Maxim", self.html)
        for target, label in (
            ("mac-mini", "Mac Mini"),
            ("air", "Air"),
            ("pro", "Pro"),
            ("agents", "Agents"),
        ):
            self.assertIn(target, self.parser.nav_targets)
            self.assertIn(label, self.parser.nav_targets[target])

    def test_platforms_is_a_reachable_top_level_surface(self):
        self.assertEqual(self.parser.platform_section_count, 1)
        self.assertIn("platforms", self.parser.nav_targets)
        self.assertIn("Platforms", self.parser.nav_targets["platforms"])

        initial_guard = re.search(
            r"\[([^\]]+)\]\.includes\(INITIAL_SECTION\)",
            self.html,
        )
        self.assertIsNotNone(initial_guard, "INITIAL_SECTION needs a safe allowlist")
        allowed = re.findall(r"['\"]([^'\"]+)['\"]", initial_guard.group(1))
        self.assertIn("platforms", allowed)

    def test_platform_directory_has_exact_registry_and_safe_destinations(self):
        self.assertEqual(set(self.parser.platforms), set(EXPECTED_PLATFORMS))

        for platform_id, (expected_name, expected_hrefs) in EXPECTED_PLATFORMS.items():
            with self.subTest(platform=platform_id):
                platform = self.parser.platforms[platform_id]
                self.assertEqual(platform["name"], expected_name)
                links = platform["links"]
                assert isinstance(links, list)
                self.assertEqual(
                    tuple(link.get("href") for link in links),
                    expected_hrefs,
                )
                for link in links:
                    self.assertEqual(link.get("target"), "_blank")
                    self.assertEqual(
                        set((link.get("rel") or "").split()),
                        {"noopener", "noreferrer"},
                    )

                    href = link.get("href") or ""
                    parsed = urlsplit(href)
                    self.assertIsNone(parsed.username)
                    self.assertIsNone(parsed.password)
                    self.assertEqual(parsed.query, "")
                    self.assertEqual(parsed.fragment, "")
                    self.assertNotIn("51.255.36.141", href)
                    self.assertNotRegex(
                        href,
                        r"(?i)(?:file:|/Users/|/home/|/srv/)",
                    )
                    if parsed.hostname == "127.0.0.1":
                        self.assertEqual(parsed.scheme, "http")
                    else:
                        self.assertEqual(parsed.scheme, "https")
                        self.assertIn(
                            parsed.hostname,
                            {"t.me", "health.meshly.fr"},
                        )

    def test_platform_directory_is_responsive_keyboard_safe_and_motion_safe(self):
        self.assertTrue(
            'class="platform-directory"' in self.html,
            "Platforms needs the platform-directory layout hook",
        )
        self.assertTrue(
            re.search(
                r"@media\s*\([^)]*max-width[^)]*\)[\s\S]*?\.platform-directory",
                self.html,
            )
            is not None,
            "platform-directory needs a responsive breakpoint",
        )
        self.assertTrue(
            re.search(r"\.platform-link:focus-visible\s*\{", self.html) is not None,
            "platform links need a visible keyboard focus treatment",
        )
        self.assertTrue(
            re.search(
                r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{"
                r"[\s\S]*?\.platform-link",
                self.html,
            )
            is not None,
            "platform link motion needs a reduced-motion override",
        )


if __name__ == "__main__":
    unittest.main()
