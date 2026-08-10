from __future__ import annotations

from html.parser import HTMLParser
import importlib
from pathlib import Path
import re
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = BUILDER_DIR / "mac-mini-dashboard" / "index.html"
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
CANONICAL_DEPARTMENTS = (
    "hq",
    "sales",
    "development",
    "design",
    "infrastructure",
    "internal",
    "finance",
)


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.navigation: list[dict[str, object]] = []
        self.active_sections: list[str] = []
        self._button: dict[str, object] | None = None
        self._button_span_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        onclick = attributes.get("onclick") or ""
        target = re.fullmatch(r"showSection\(['\"]([^'\"]+)['\"]\)", onclick)
        if tag == "button" and "nav-pill" in classes and target:
            self._button = {
                "target": target.group(1),
                "active": "active" in classes,
                "text": [],
            }
            self._button_span_depth = 0
        elif self._button is not None and tag == "span":
            self._button_span_depth += 1

        section_id = attributes.get("id") or ""
        if tag == "div" and section_id.startswith("section-") and "active" in classes:
            self.active_sections.append(section_id.removeprefix("section-"))

    def handle_data(self, data: str) -> None:
        if self._button is not None and self._button_span_depth == 0:
            text = self._button["text"]
            assert isinstance(text, list)
            text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._button is None:
            return
        if tag == "span" and self._button_span_depth:
            self._button_span_depth -= 1
        elif tag == "button":
            text = self._button["text"]
            assert isinstance(text, list)
            self._button["text"] = " ".join("".join(text).split())
            self.navigation.append(self._button)
            self._button = None
            self._button_span_depth = 0


class _CampusStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self.zone_ids: list[str] = []
        self.coordinator_locations: list[str | None] = []
        self.coordinator_direct_parents: list[str | None] = []
        self.hq_heading_text: list[str] = []
        self.coordinator_name_text: list[str] = []
        self.coordinator_status_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        department_id = attributes.get("data-department-id")
        if department_id is not None:
            self.zone_ids.append(department_id)

        if attributes.get("data-campus-static-manager") == "true":
            ancestors = [
                ancestor_attrs.get("data-department-id")
                for _ancestor_tag, ancestor_attrs in self._stack
                if ancestor_attrs.get("data-department-id") is not None
            ]
            self.coordinator_locations.append(ancestors[-1] if ancestors else None)
            direct_parent = self._stack[-1][1] if self._stack else {}
            self.coordinator_direct_parents.append(
                direct_parent.get("data-department-id")
            )

        self._stack.append((tag, attributes))

    def handle_data(self, data: str) -> None:
        if any(attributes.get("id") == "campus-zone-hq-label" for _, attributes in self._stack):
            self.hq_heading_text.append(data)

        inside_coordinator = any(
            attributes.get("data-campus-static-manager") == "true"
            for _, attributes in self._stack
        )
        if not inside_coordinator:
            return
        if any(tag == "strong" for tag, _attributes in self._stack):
            self.coordinator_name_text.append(data)
        elif any(
            tag == "span" and "campus-manager-sprite" not in (attributes.get("class") or "").split()
            for tag, attributes in self._stack
        ):
            self.coordinator_status_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return


class _VisibleTextParser(HTMLParser):
    def __init__(self, scope_class: str | None = None) -> None:
        super().__init__()
        self.scope_class = scope_class
        self._stack: list[tuple[str, bool, bool]] = []
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        parent_in_scope = self._stack[-1][1] if self._stack else False
        parent_suppressed = self._stack[-1][2] if self._stack else False
        in_scope = (
            self.scope_class is None
            or parent_in_scope
            or self.scope_class in classes
        )
        suppressed = (
            parent_suppressed
            or tag in {"script", "style", "template"}
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
        )
        self._stack.append((tag, in_scope, suppressed))

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1][1] and not self._stack[-1][2]:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return

    def visible_text(self) -> str:
        return " ".join("".join(self._text).split())


class DepartmentCampusVisualIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard_html = DASHBOARD_PATH.read_text(encoding="utf-8")
        cls.css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        cls.script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")
        cls.campus = importlib.import_module("dashboard_builder.department_campus")
        cls.campus_html = cls.campus.build_department_campus_html()

    def _dashboard(self) -> _DashboardParser:
        parser = _DashboardParser()
        parser.feed(self.dashboard_html)
        return parser

    def _campus_structure(self) -> _CampusStructureParser:
        parser = _CampusStructureParser()
        parser.feed(self.campus_html)
        return parser

    def _css_declarations(self, selector_fragment: str) -> str:
        matches = []
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", self.css):
            if selector_fragment in selector:
                matches.append(declarations)
        return "\n".join(matches)

    def test_ac_1_top_navigation_contains_only_the_four_public_surfaces(self):
        parser = self._dashboard()

        self.assertEqual(
            [(item["target"], item["text"]) for item in parser.navigation],
            [
                ("mac-mini", "Mac Mini"),
                ("air", "Air"),
                ("pro", "Pro"),
                ("agents", "Agents"),
            ],
        )

    def test_ac_2_agents_is_default_and_legacy_tabs_cannot_be_selected(self):
        parser = self._dashboard()
        active_navigation = [
            item["target"] for item in parser.navigation if item["active"]
        ]
        self.assertEqual(active_navigation, ["agents"])
        self.assertEqual(parser.active_sections, ["agents"])

        initial_guard = re.search(
            r"\[([^\]]+)\]\.includes\(INITIAL_SECTION\)",
            self.dashboard_html,
        )
        self.assertIsNotNone(
            initial_guard,
            "query-string tab restoration must retain an explicit safe allowlist",
        )
        allowed = re.findall(r"['\"]([^'\"]+)['\"]", initial_guard.group(1))
        self.assertEqual(allowed, ["mac-mini", "air", "pro", "agents"])

    def test_ac_3_hq_keeps_its_id_but_uses_the_new_visible_russian_copy(self):
        structure = self._campus_structure()

        self.assertIn("hq", self.campus.DEPARTMENT_ZONES)
        self.assertEqual(self.campus.DEPARTMENT_ZONES["hq"]["label"], "Центр управления")
        self.assertEqual(
            " ".join("".join(structure.hq_heading_text).split()),
            "Центр управления",
        )
        self.assertEqual(
            " ".join("".join(structure.coordinator_name_text).split()),
            "Главный координатор",
        )
        self.assertEqual(
            " ".join("".join(structure.coordinator_status_text).split()),
            "ожидает задач",
        )

    def test_ac_3_visible_owner_copy_has_no_legacy_manager_hq_or_idle_terms(self):
        dashboard_copy = _VisibleTextParser("pixel-agents-gamebar-title")
        dashboard_copy.feed(self.dashboard_html)
        campus_copy = _VisibleTextParser()
        campus_copy.feed(self.campus_html)

        legacy_visible_copy = re.compile(
            r"(?<![\w-])(?:MAIN MANAGER|HQ|idle)(?![\w-])",
            re.IGNORECASE,
        )
        for surface, visible_text in (
            ("dashboard gamebar", dashboard_copy.visible_text()),
            ("department campus", campus_copy.visible_text()),
        ):
            with self.subTest(surface=surface):
                self.assertEqual(
                    legacy_visible_copy.findall(visible_text),
                    [],
                    f"{surface} still exposes legacy owner-facing copy: {visible_text!r}",
                )

    def test_ac_4_coordinator_is_physically_nested_in_the_hq_zone(self):
        structure = self._campus_structure()

        self.assertEqual(
            structure.coordinator_locations,
            ["hq"],
            "the one persistent coordinator must be a DOM descendant of the hq room",
        )
        self.assertEqual(
            structure.coordinator_direct_parents,
            ["hq"],
            "the coordinator must be placed directly in the control-room DOM, not on the global map",
        )

    def test_ac_4_coordinator_is_room_local_without_black_floating_plates(self):
        manager_css = self._css_declarations(".campus-static-manager")
        zone_css = self._css_declarations(".campus-zone")
        plate_css = "\n".join(
            declarations
            for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", self.css)
            if ".campus-static-manager strong" in selector
            or ".campus-static-manager > span:last-child" in selector
        )

        self.assertRegex(manager_css, r"position:\s*absolute")
        self.assertRegex(manager_css, r"(?:bottom|inset-block-end):")
        self.assertRegex(zone_css, r"position:\s*relative")
        self.assertNotRegex(manager_css, r"overflow:\s*(?:hidden|clip)")
        self.assertNotRegex(
            plate_css,
            r"background(?:-color)?:\s*(?:#(?:09090b|101014|17171c)|rgba?\(\s*9\s*,\s*9\s*,\s*11)",
            "coordinator identity and status must not render as floating black plates",
        )

    def test_ac_4_coordinator_sprite_keeps_native_pixel_scale_and_environment_tone(self):
        manager_css = self._css_declarations(".campus-static-manager")
        sprite_css = self._css_declarations(".campus-manager-sprite")

        self.assertRegex(sprite_css, r"width:\s*32px")
        self.assertRegex(sprite_css, r"height:\s*32px")
        self.assertRegex(sprite_css, r"image-rendering:\s*pixelated")
        self.assertNotRegex(
            manager_css + sprite_css,
            r"transform:\s*scale\(",
            "the persistent coordinator must not be down-scaled below its native pixel size",
        )
        self.assertRegex(
            sprite_css,
            r"(?:filter|mix-blend-mode|opacity|--[\w-]*(?:tone|tint))\s*:",
            "the coordinator sprite needs an environment-toned treatment",
        )

    def test_ac_4_coordinator_has_a_floor_contact_shadow(self):
        manager_css = self._css_declarations(".campus-static-manager")
        sprite_css = self._css_declarations(".campus-manager-sprite")

        self.assertRegex(
            manager_css + sprite_css,
            r"(?:drop-shadow\(|box-shadow:)",
            "the coordinator needs a contact shadow that visually anchors it to the room",
        )

    def test_ac_5_file_dashboard_uses_reachable_campus_and_matching_message_origin(self):
        required_contracts = (
            (
                "const PIXEL_AGENTS_BASE = IS_FILE_DASHBOARD "
                "? 'https://command.meshly.fr' : window.location.origin;",
                "file:// must use the reachable HTTPS campus while http(s) stays same-origin",
            ),
            (
                "const PIXEL_AGENTS_URL = `${PIXEL_AGENTS_BASE}/department-campus.html`;",
                "iframe and Full screen must share one selected campus URL",
            ),
            (
                "const PIXEL_AGENTS_ORIGIN = new URL(PIXEL_AGENTS_URL).origin;",
                "postMessage origin must be derived from the selected campus URL",
            ),
            ("frame.src = PIXEL_AGENTS_URL;", "iframe must receive the selected campus URL"),
            (
                "fullScreen.href = PIXEL_AGENTS_URL;",
                "Full screen must receive the selected campus URL",
            ),
            (
                "initPixelAgentsFrame();",
                "the selected campus URL must be applied during initialization",
            ),
        )
        for snippet, contract in required_contracts:
            self.assertTrue(
                snippet in self.dashboard_html,
                f"AC-5 missing contract: {contract}; expected {snippet!r}",
            )
        self.assertLess(
            self.dashboard_html.index("initPixelAgentsFrame();"),
            self.dashboard_html.index("initPixelAgentsPin();"),
            "the file:// iframe URL must be selected before postMessage pin setup",
        )

    def test_ec_1_seven_zone_public_shell_stays_read_only_and_unsynthesized(self):
        structure = self._campus_structure()

        self.assertEqual(tuple(self.campus.DEPARTMENT_ZONES), CANONICAL_DEPARTMENTS)
        self.assertEqual(tuple(structure.zone_ids), CANONICAL_DEPARTMENTS)
        self.assertNotRegex(self.campus_html, r"<(?:form|input|textarea|select)\b")
        self.assertNotIn("data-campus-agent-trigger", self.campus_html)
        self.assertNotIn("data-campus-route-task-id", self.campus_html)

    def test_ec_2_mobile_keyboard_focus_and_reduced_motion_contracts_remain(self):
        parser = self._dashboard()
        self.assertTrue(parser.navigation)
        self.assertNotRegex(
            self.dashboard_html,
            r"<a\b[^>]*class=['\"][^'\"]*\bnav-pill\b",
            "top-level surfaces must remain native keyboard-operable buttons",
        )
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*900px\)")
        self.assertIn(":focus-visible", self.css)
        self.assertRegex(self.css, r"min-(?:width|height):\s*44px")
        self.assertIn("prefers-reduced-motion: reduce", self.css)
        self.assertIn("animation: none !important", self.css)
        for keyboard_contract in ("Enter", "Space", "Escape", "focus()"):
            with self.subTest(keyboard_contract=keyboard_contract):
                self.assertIn(keyboard_contract, self.script)


if __name__ == "__main__":
    unittest.main()
