from __future__ import annotations

from collections import Counter, defaultdict
from html.parser import HTMLParser
import importlib
from pathlib import Path
import re
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
MOBILE_VIEWPORT_WIDTH = 390
CSS_ROOT_FONT_SIZE_PX = 16


def _classes(attributes: dict[str, str | None]) -> set[str]:
    return set((attributes.get("class") or "").split())


class _CampusPolishParser(HTMLParser):
    """Collect the rendered room/folder contract without inspecting builder internals."""

    def __init__(self) -> None:
        super().__init__()
        self._stack: list[dict[str, object]] = []
        self.zones: list[str] = []
        self.rails: dict[str, list[dict[str, object]]] = defaultdict(list)
        self.stages: dict[str, int] = defaultdict(int)
        self.residents: dict[str, list[dict[str, str | None]]] = defaultdict(list)
        self.folders: list[dict[str, object]] = []

    def _current_zone(self) -> str | None:
        for item in reversed(self._stack):
            zone = item.get("zone")
            if isinstance(zone, str):
                return zone
        return None

    def _current_folder(self) -> dict[str, object] | None:
        for item in reversed(self._stack):
            folder = item.get("folder")
            if isinstance(folder, dict):
                return folder
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        zone = attributes.get("data-department-id") if tag == "section" else None
        if zone is not None:
            self.zones.append(zone)
        current_zone = zone or self._current_zone()

        item: dict[str, object] = {"tag": tag}
        if zone is not None:
            item["zone"] = zone

        if "data-campus-project-rail" in attributes:
            rail = {"attrs": attributes, "folders": []}
            assert current_zone is not None, "a project rail must be nested in a department room"
            self.rails[current_zone].append(rail)
            item["rail"] = rail

        if "data-campus-resident-stage" in attributes:
            assert current_zone is not None, "a resident stage must be nested in a department room"
            self.stages[current_zone] += 1

        if "campus-resident" in _classes(attributes):
            assert current_zone is not None, "a resident must be nested in a department room"
            self.residents[current_zone].append(attributes)

        if tag == "button" and "data-campus-project-folder" in attributes:
            folder: dict[str, object] = {
                "attrs": attributes,
                "label_parts": [],
                "inside_label": False,
                "zone": current_zone,
            }
            self.folders.append(folder)
            for ancestor in reversed(self._stack):
                rail = ancestor.get("rail")
                if isinstance(rail, dict):
                    rail["folders"].append(folder)
                    break
            item["folder"] = folder

        folder = self._current_folder()
        if folder is not None and tag == "strong":
            folder["inside_label"] = True
        self._stack.append(item)

    def handle_data(self, data: str) -> None:
        folder = self._current_folder()
        if folder is not None and folder["inside_label"]:
            folder["label_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        folder = self._current_folder()
        if folder is not None and tag == "strong":
            folder["inside_label"] = False
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return


def _css_rules(css: str) -> list[tuple[str, str]]:
    return [
        (" ".join(selector.split()), declarations)
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _selector_declarations(css: str, selector: str) -> str:
    declarations = []
    for selectors, body in _css_rules(css):
        if selector in [part.strip() for part in selectors.split(",")]:
            declarations.append(body)
    return "\n".join(declarations)


def _first_selector_declarations(css: str, selector: str) -> str:
    for selectors, body in _css_rules(css):
        if selector in [part.strip() for part in selectors.split(",")]:
            return body
    return ""


def _absolute_css_length_px(value: str, unit: str) -> float:
    length = float(value)
    return length * CSS_ROOT_FONT_SIZE_PX if unit == "rem" else length


def _rail_declarations(css: str) -> str:
    declarations = []
    for selectors, body in _css_rules(css):
        if any(
            marker in selectors
            for marker in (
                "[data-campus-project-rail]",
                ".campus-project-rail",
                ".campus-project-shelf",
            )
        ):
            declarations.append(body)
    return "\n".join(declarations)


def _media_blocks(css: str) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    marker = re.compile(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{")
    for match in marker.finditer(css):
        depth = 1
        cursor = match.end()
        while cursor < len(css) and depth:
            if css[cursor] == "{":
                depth += 1
            elif css[cursor] == "}":
                depth -= 1
            cursor += 1
        if depth == 0:
            blocks.append((int(match.group(1)), css[match.end():cursor - 1]))
    return blocks


class DepartmentCampusVisualPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campus = importlib.import_module("dashboard_builder.department_campus")
        cls.html = cls.campus.build_department_campus_html()
        cls.css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        cls.script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")
        cls.structure = _CampusPolishParser()
        cls.structure.feed(cls.html)
        cls.expected_projects = tuple(cls.campus.CAMPUS_PROJECTS)
        cls.expected_counts = Counter(
            project["department_id"] for project in cls.expected_projects
        )

    def test_ac_1_ec_1_each_room_has_one_count_driven_single_row_project_rail(self):
        self.assertEqual(set(self.structure.zones), set(self.expected_counts))
        self.assertEqual(
            {department: len(self.structure.rails[department]) for department in self.expected_counts},
            {department: 1 for department in self.expected_counts},
            "each room must expose exactly one semantic project rail",
        )

        for department_id, expected_count in self.expected_counts.items():
            with self.subTest(department_id=department_id):
                rails = self.structure.rails[department_id]
                rail = rails[0]
                attributes = rail["attrs"]
                self.assertEqual(
                    attributes.get("data-campus-project-count"),
                    str(expected_count),
                    "the rendered count must be explicit and agree with the canonical registry",
                )
                self.assertEqual(len(rail["folders"]), expected_count)
                self.assertRegex(
                    attributes.get("style") or "",
                    rf"--campus-project-count:\s*{expected_count}(?:;|$)",
                    "the validated count must drive the rail's column count",
                )

        rail_css = _rail_declarations(self.css)
        self.assertRegex(rail_css, r"display:\s*grid")
        self.assertRegex(
            rail_css,
            r"grid-template-columns:\s*repeat\(var\(--campus-project-count\),\s*minmax\(0,\s*1fr\)\)",
        )
        self.assertNotRegex(rail_css, r"flex-wrap:\s*wrap|grid-auto-flow:\s*row")

        folder_css = _first_selector_declarations(self.css, ".campus-project-folder")
        self.assertRegex(folder_css, r"min-width:\s*44px")
        cap = re.search(
            r"max-(?:width|inline-size):\s*(\d+(?:\.\d+)?)(px|rem)\b",
            folder_css,
        )
        self.assertIsNotNone(
            cap,
            "a one-project rail needs an explicit folder max-width/max-inline-size cap",
        )
        cap_px = _absolute_css_length_px(cap.group(1), cap.group(2))
        self.assertGreaterEqual(cap_px, 44)
        self.assertLessEqual(
            cap_px,
            160,
            "a one-project folder must stay compact enough to read as room furniture",
        )

    def test_ac_2_residents_and_coordinator_have_a_clear_floor_above_the_rail(self):
        self.assertEqual(
            {department: len(residents) for department, residents in self.structure.residents.items()},
            {department: 1 for department in self.expected_counts},
            "each room must retain exactly one idle resident, including the coordinator",
        )

        zone_css = _selector_declarations(self.css, ".campus-zone")
        resident_css = _selector_declarations(self.css, ".campus-resident")
        coordinator_css = _selector_declarations(self.css, ".campus-static-manager")

        safe_gap_variables = []
        for name, value, unit in re.findall(
            r"(--[\w-]*(?:gap|clearance)[\w-]*):\s*(\d+(?:\.\d+)?)(px|rem)\b",
            zone_css,
        ):
            if _absolute_css_length_px(value, unit) >= 8:
                safe_gap_variables.append(name)
        self.assertTrue(
            safe_gap_variables,
            "rooms need a named positive rail gap of at least 8px/0.5rem to absorb the +4px wander offset",
        )

        def uses_safe_rail_clearance(declarations: str, gap_variable: str) -> bool:
            bottom_values = re.findall(
                r"(?:bottom|inset-block-end):\s*([^;]+)",
                declarations,
            )
            return bool(bottom_values) and all(
                re.search(r"var\(--campus-project-(?:rail|shelf)-height\)", value)
                and f"var({gap_variable})" in value
                for value in bottom_values
            )

        self.assertTrue(
            any(
                uses_safe_rail_clearance(resident_css, gap_variable)
                and uses_safe_rail_clearance(coordinator_css, gap_variable)
                for gap_variable in safe_gap_variables
            ),
            "resident and coordinator bottom offsets must add the same named safety gap to rail height at every breakpoint",
        )

        sprite_css = _selector_declarations(self.css, ".campus-resident-sprite")
        caption_css = _selector_declarations(self.css, ".campus-resident-caption")
        self.assertRegex(sprite_css, r"drop-shadow\(")
        self.assertRegex(caption_css, r"position:\s*absolute")
        self.assertIn("campus-resident-caption", self.html)

    def test_ac_3_ec_2_canonical_names_wrap_to_two_lines_without_ellipsis(self):
        canonical_identities = tuple(
            folder["attrs"].get("data-campus-project")
            for folder in self.structure.folders
        )
        rendered_labels = tuple(
            " ".join("".join(folder["label_parts"]).split())
            for folder in self.structure.folders
        )
        expected_labels = tuple(
            "Координация" if project["project"] == "MAIN MANAGER" else project["project"]
            for project in self.expected_projects
        )
        self.assertEqual(
            canonical_identities,
            tuple(project["project"] for project in self.expected_projects),
        )
        self.assertEqual(
            rendered_labels,
            expected_labels,
        )
        self.assertNotIn("MAIN MANAGER", rendered_labels)
        self.assertIn("PIXELVERSE DASHBOARD", rendered_labels)
        self.assertIn("UNFINISHED STUFF", rendered_labels)

        folder_css = _selector_declarations(self.css, ".campus-project-folder")
        label_css = _selector_declarations(self.css, ".campus-project-folder strong")
        self.assertRegex(folder_css, r"min-width:\s*44px")
        self.assertRegex(folder_css, r"min-height:\s*44px")
        self.assertRegex(label_css, r"white-space:\s*normal")
        self.assertRegex(label_css, r"(?:overflow-wrap:\s*(?:anywhere|break-word)|word-break:\s*break-word)")
        self.assertNotRegex(label_css, r"text-overflow:\s*ellipsis|white-space:\s*nowrap")
        self.assertTrue(
            any(".campus-project-folder:focus-visible" in selector for selector, _ in _css_rules(self.css)),
            "project folders must retain a visible keyboard focus treatment",
        )

    def test_ac_4_ac_6_live_promotion_and_existing_interactions_remain_safe(self):
        for folder in self.structure.folders:
            attributes = folder["attrs"]
            classes = _classes(attributes)
            self.assertEqual(attributes.get("data-campus-project-status"), "idle")
            self.assertTrue(classes.isdisjoint({
                "is-live", "is-active", "is-testing", "is-waiting", "is-queued",
                "is-done", "is-failed", "is-busy",
            }))

        project = self.expected_projects[2]
        exact = {
            "project": project["project"],
            "department_id": project["department_id"],
            "agent_id": project["agent_id"],
        }
        self.assertEqual(self.campus.campus_project_for_event(exact), project)
        for field, value in (
            ("project", "UNVERIFIED"),
            ("department_id", "design"),
            ("agent_id", "DESIGNER"),
        ):
            event = dict(exact)
            event[field] = value
            with self.subTest(field=field):
                self.assertIsNone(self.campus.campus_project_for_event(event))

        animated_folder_rules = []
        for selector, declarations in _css_rules(self.css):
            if ".campus-project-folder" not in selector:
                continue
            animation_values = re.findall(r"animation:\s*([^;]+)", declarations)
            if any(not value.lstrip().startswith("none") for value in animation_values):
                animated_folder_rules.append(selector)
        self.assertTrue(animated_folder_rules)
        for selector in animated_folder_rules:
            with self.subTest(selector=selector):
                self.assertRegex(selector, r"\.is-(?:active|testing)\b")
        self.assertNotRegex(
            self.html,
            r"data-campus-project-(?:task-count|busy|route)|data-campus-route-task-id",
        )

        detail = re.search(
            r'<([a-z]+)\b[^>]*data-campus-project-detail(?=[\s=>])[^>]*',
            self.html,
        )
        self.assertIsNotNone(detail)
        self.assertRegex(self.html, r"<button\b[^>]*data-campus-project-detail-close")
        for folder in self.structure.folders:
            attributes = folder["attrs"]
            self.assertEqual(attributes.get("type"), "button")
            self.assertEqual(attributes.get("aria-haspopup"), "dialog")
            self.assertTrue(attributes.get("aria-controls"))
        self.assertRegex(
            self.script,
            r"(?s)data-campus-project-folder.{0,5000}Escape.{0,800}\.focus\(\)",
        )
        reduced = self.css[self.css.rfind("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn(".campus-project-folder", reduced)
        self.assertIn(".campus-resident", reduced)
        self.assertRegex(reduced, r"animation:\s*none\s*!important")
        self.assertRegex(reduced, r"transition:\s*none\s*!important")

    def test_ac_5_390px_and_desktop_layouts_do_not_scroll_or_clip_project_rails(self):
        map_css = _selector_declarations(self.css, ".campus-map")
        zone_css = _selector_declarations(self.css, ".campus-zone")
        rail_css = _rail_declarations(self.css)

        self.assertRegex(map_css, r"width:\s*100%")
        self.assertRegex(zone_css, r"min-width:\s*0")
        self.assertNotRegex(
            rail_css,
            r"overflow(?:-x|-inline)?:\s*(?:auto|scroll)",
            "room-local rails must fit rather than becoming nested horizontal scrollers",
        )

        mobile_css = "\n".join(
            block
            for max_width, block in _media_blocks(self.css)
            if MOBILE_VIEWPORT_WIDTH <= max_width
        )
        mobile_map_css = _selector_declarations(mobile_css, ".campus-map")
        mobile_rail_css = _rail_declarations(mobile_css)
        self.assertTrue(mobile_map_css, "390px must have an explicit responsive room composition")
        self.assertNotRegex(
            mobile_map_css,
            r"grid-template-columns:\s*repeat\(12\b",
            "the desktop twelve-column room grid leaves 44px targets outside narrow rooms at 390px",
        )
        self.assertNotRegex(
            mobile_rail_css,
            r"overflow(?:-x|-inline)?:\s*(?:auto|scroll)",
        )

if __name__ == "__main__":
    unittest.main()
