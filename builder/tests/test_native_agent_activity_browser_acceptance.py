"""Browser-acceptance regressions for the native campus roster.

These tests keep the deterministic suite dependency-free.  The count contract is
executed with Node; the Three.js contract is checked at the explicit 2D/3D DOM
boundary that the standalone campus document ships to the browser.
"""
from __future__ import annotations

from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest


BUILDER = Path(__file__).resolve().parents[1]
ASSETS = BUILDER / "dashboard-assets"
SERVER_PATH = BUILDER / "dashboard-server-m4.py"
SCENE_START = "// ── Campus 3D Scene ──"
SCENE_END = "// ── End Campus 3D Scene ──"
CAMPUS_START = "// ── Department Campus ──"
CAMPUS_END = "// ── End Department Campus ──"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin + len(start))]


SERVER = _load("native_browser_acceptance_server", SERVER_PATH)
FIXTURE = _load(
    "native_browser_acceptance_fixture",
    BUILDER / "tests" / "test_native_agent_activity_projection.py",
)


class NativeActivityBrowserAcceptanceRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ASSETS / "script.js").read_text(encoding="utf-8")
        cls.campus_script = _block(cls.script, CAMPUS_START, CAMPUS_END)
        cls.scene = _block(cls.script, SCENE_START, SCENE_END)
        cls.document = SERVER._department_campus_document()

    def test_native_totals_are_visible_but_legacy_loading_count_stays_hidden(self):
        count_tag = re.search(r"<[^>]+data-campus-count[^>]*>", self.document)
        self.assertIsNotNone(count_tag)
        self.assertIn(" hidden", count_tag.group(0))

        set_state = _block(
            self.campus_script,
            "function setCampusState",
            "function openCampusDetails",
        )
        harness = f"""
const stateEl = {{textContent: ''}};
const countEl = {{textContent: '', hidden: true}};
const campus = {{dataset: {{}}}};
const campusQueueUpdatedAt = null;
const stateMessages = {{active: 'active', loading: 'loading', unavailable: 'unavailable'}};
const rosterCount = 7;
function formatCampusQueueTime() {{ return ''; }}
function notifyCampusContentHeight() {{}}
{set_state}
setCampusState('active', 0, 1, 0, {{enabled: 12, running: 1, unavailable: 10}});
const native = {{hidden: countEl.hidden, text: countEl.textContent}};
countEl.hidden = true;
setCampusState('loading', 0, 0, 0, null);
process.stdout.write(JSON.stringify({{native, legacyHidden: countEl.hidden}}));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(result.stdout)
        self.assertEqual(
            observed["native"]["text"],
            "12 маршрутов · работают: 1 · без подтверждения: 10",
        )
        self.assertFalse(
            observed["native"]["hidden"],
            "a validated native roster must reveal its truthful aggregate count",
        )
        self.assertTrue(
            observed["legacyHidden"],
            "revealing native totals must not expose the legacy/loading placeholder",
        )

    def test_owner_gate_does_not_manufacture_a_working_native_roster(self):
        checkpoint = FIXTURE.NativeActivityProjectionRedTests()._checkpoint()
        for agent in checkpoint["agents"]:
            agent.update(
                state=None,
                availability="unavailable",
                freshness="unavailable",
                state_at=None,
                outcome_stage=None,
            )
        fixture = FIXTURE.NativeActivityProjectionRedTests()
        payload = SERVER._department_campus_payload(
            FIXTURE._bridge(fixture._snapshot(checkpoint)),
            now=FIXTURE.NOW + timedelta(minutes=1),
            owner_view=True,
        )

        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["activity_counts"]["running"], 0)
        self.assertEqual(payload["activity_counts"]["unavailable"], 12)
        self.assertEqual(len(payload["owner_gates"]), 1)
        self.assertEqual(payload["owner_gates"][0]["project"], "JARVIS")
        self.assertIs(payload["owner_gates"][0]["needs_mark"], True)

        render_campus = _block(
            self.campus_script,
            "function renderDepartmentCampus",
            "async function refreshDepartmentCampus",
        )
        harness = f"""
const payload = {json.dumps(payload, ensure_ascii=False)};
let campusQueueUpdatedAt = null;
const journeySignatures = new Set();
const statusLabels = {{waiting: 'ждёт решения'}};
const movingStatuses = ['active', 'testing'];
const managerMarkerEl = null;
const focusedDepartment = false;
const campus = {{dataset: {{}}}};
const calls = [];
const activatedProjects = [];
function clearCampusAgents() {{}}
function renderNativeAgents() {{}}
function setCampusState(...args) {{ calls.push(args); }}
function projectFolderForEvent(event) {{
    return {{closest() {{ return {{querySelector() {{ return {{}}; }}}}; }}}};
}}
function setManagerPresence() {{}}
function journeySignature(event) {{ return JSON.stringify([event.task_id, event.status]); }}
function renderCampusTaskLanes() {{}}
function renderCampusRoutes() {{}}
function activateCampusProjectFolder(_folder, event) {{ activatedProjects.push(event.project); }}
function destinationForEvent() {{ return {{append() {{}}}}; }}
function residentForEvent() {{ return null; }}
function createCampusAgent() {{ return {{}}; }}
function animateCampusJourney() {{}}
{render_campus}
renderDepartmentCampus(payload);
process.stdout.write(JSON.stringify({{calls, activatedProjects}}));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(result.stdout)
        self.assertIn(
            "JARVIS",
            observed["activatedProjects"],
            "the separate owner gate must stay represented in the project layer",
        )
        self.assertTrue(observed["calls"])
        self.assertNotEqual(
            observed["calls"][-1][0],
            "active",
            "zero confirmed native runs must not render the top-level `Команда работает` state",
        )

    def test_native_route_buttons_include_project_in_the_accessible_name(self):
        create_agent = _block(
            self.campus_script,
            "function createCampusAgent",
            "function renderCampusTaskLanes",
        )
        aria_label = re.search(
            r"button\.setAttribute\('aria-label',([\s\S]*?)\);",
            create_agent,
        )
        self.assertIsNotNone(aria_label)
        self.assertIn(
            "event.project",
            aria_label.group(1),
            "duplicate BUILDER/ANALYST routes need their project in the accessible name",
        )

    def test_native_roster_replaces_default_residents_in_both_2d_and_3d(self):
        render_native = _block(
            self.campus_script,
            "function renderNativeAgents",
            "function renderDepartmentCampus",
        )
        render_campus = _block(
            self.campus_script,
            "function renderDepartmentCampus",
            "async function refreshDepartmentCampus",
        )

        for source, contract in (
            (render_campus, "nativeRosterDeclared"),
            (render_native, "nativeRosterDeclared"),
            (render_campus, "campusNativeRoster"),
            (self.scene, "campusNativeRoster"),
            (self.scene, "button.dataset.campusRouteId"),
        ):
            with self.subTest(contract=contract):
                self.assertTrue(
                    contract in source,
                    "the 2D/3D boundary must distinguish a declared route roster from legacy residents",
                )

        resident_visibility = re.search(
            r"residents\.forEach\(\(actor\)\s*=>\s*\{([\s\S]*?)\n\s*\}\);",
            self.scene,
        )
        self.assertIsNotNone(resident_visibility)
        self.assertTrue(
            re.search(
                r"nativeRosterDeclared[\s\S]*?(?:\.visible\s*=|scene\.remove\()",
                resident_visibility.group(1),
            ) is not None,
            "a native roster must hide/remove every unmatched default 3D resident",
        )

    def test_declared_but_stale_native_lane_never_restores_fabricated_residents(self):
        fixture = FIXTURE.NativeActivityProjectionRedTests()
        snapshot = fixture._snapshot(fixture._checkpoint())
        payload = SERVER._department_campus_payload(
            FIXTURE._bridge(snapshot),
            now=FIXTURE.NOW + timedelta(hours=2),
        )

        self.assertEqual(payload["state"], "stale")
        self.assertIn(
            "agents",
            payload,
            "the empty agents list is the safe declaration that the native lane exists",
        )
        self.assertEqual(payload["agents"], [])
        self.assertIn("activity_counts", payload)

        render_campus = _block(
            self.campus_script,
            "function renderDepartmentCampus",
            "async function refreshDepartmentCampus",
        )
        self.assertTrue(
            re.search(
                r"nativeRosterDeclared\s*=\s*Array\.isArray\(payload(?:\?\.)?agents\)",
                render_campus,
            ) is not None,
            "declared-but-empty native data must not be mistaken for the legacy campus",
        )
        render_native = _block(
            self.campus_script,
            "function renderNativeAgents",
            "function renderDepartmentCampus",
        )
        self.assertTrue(
            re.search(
                r"resident\.hidden\s*=\s*nativeRosterDeclared",
                render_native,
            ) is not None,
            "stale native data must suppress invented 2D idle residents",
        )
        self.assertTrue(
            re.search(
                r"nativeRosterDeclared[\s\S]{0,1200}residents\.forEach",
                self.scene,
            ) is not None,
            "stale native data must suppress invented 3D idle residents",
        )

    def test_only_confirmed_native_running_gets_3d_activity_affordances(self):
        sync = _block(self.scene, "function sync()", "// ── Motion")
        harness = f"""
function run(status) {{
    const button = {{
        dataset: {{
            campusAgentId: 'BUILDER',
            campusTaskId: 'route-one',
            campusRouteId: 'route-one',
            campusProject: 'PROJECT ONE',
            campusStatus: status,
            campusMoving: 'false',
            campusDepartmentId: 'development',
        }},
        getAttribute() {{ return 'department'; }},
        querySelector(selector) {{
            return {{textContent: selector === 'strong' ? 'BUILDER' : status}};
        }},
    }};
    const actor = {{
        agentId: 'BUILDER', name: 'BUILDER', homeRoom: 'development', room: 'development',
        home: {{}}, homeFacing: 0, steps: [], mode: 'idle', status: null,
        destinationKey: null, taskId: null, routeId: 'route-one', projectLabel: null,
        suspended: false, button,
        person: {{group: {{visible: true}}, ring: {{visible: false, material: {{color: {{setHex() {{}}}}}}}}}},
        label: {{visible: true, el: {{dataset: {{}}, classList: {{add() {{}}, remove() {{}}}}}}}},
        bubble: {{visible: false}},
    }};
    const campus = {{
        dataset: {{
            campusState: 'active',
            campusNativeRoster: JSON.stringify([{{routeId: 'route-one', project: 'PROJECT ONE'}}]),
        }},
        querySelectorAll() {{ return [button]; }},
        querySelector() {{ return null; }},
    }};
    const stage = {{setAttribute() {{}}}};
    const actors = [actor];
    const residents = new Map();
    const liveActors = new Map([['route:route-one', actor]]);
    const folderViews = [];
    const labels = [];
    const pickRoots = [];
    const scene = {{remove() {{}}}};
    const coordinator = null;
    const reducedMotion = {{matches: true}};
    const ROUTE_PRECEDENCE = ['running', 'idle', 'unavailable', 'uncertain'];
    const STATUS_COLORS = {{running: 1, idle: 2, unavailable: 3, uncertain: 4}};
    const renderDeptCard = null;
    const deptOpen = null;
    const deptCard = {{hidden: false}};
    let primarySize = null;
    function destinationFor() {{ return {{key: 'desk', point: {{}}, room: 'development', facing: 0}}; }}
    function residentInfo() {{ return null; }}
    function createActor() {{ throw new Error('existing route actor should be reused'); }}
    function placeActor(target, _point, _facing) {{ target.steps = []; }}
    function startJourney() {{ throw new Error('non-moving fixture must not walk'); }}
    function describeStatus(_status, text) {{ return text; }}
    function setLabelText() {{}}
    function renderRoutes(primary) {{ primarySize = primary.size; }}
    function requestRender() {{}}
    {sync}
    sync();
    return {{ring: actor.person.ring.visible, primarySize}};
}}
const observed = {{
    running: run('running'),
    idle: run('idle'),
    unavailable: run('unavailable'),
    uncertain: run('uncertain'),
}};
process.stdout.write(JSON.stringify(observed));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(result.stdout)
        self.assertEqual(observed["running"], {"ring": True, "primarySize": 1})
        for status in ("idle", "unavailable", "uncertain"):
            with self.subTest(status=status):
                self.assertEqual(
                    observed[status],
                    {"ring": False, "primarySize": 0},
                    "unconfirmed native presence must not create rings or amber routes",
                )

    def test_3d_picking_skips_suspended_and_invisible_native_replacements(self):
        pick_at = _block(self.scene, "function pickAt", "const drag =")
        harness = f"""
function run(hiddenActor) {{
    const hiddenButton = {{id: 'hidden', isConnected: true}};
    const visibleButton = {{id: 'visible', isConnected: true}};
    hiddenActor.button = hiddenButton;
    const visibleActor = {{
        suspended: false,
        person: {{group: {{visible: true}}}},
        button: visibleButton,
    }};
    const hiddenNode = {{userData: {{pickActor: hiddenActor}}, parent: null}};
    const visibleNode = {{userData: {{pickActor: visibleActor}}, parent: null}};
    const renderer = {{domElement: {{getBoundingClientRect() {{ return {{left: 0, top: 0, width: 10, height: 10}}; }}}}}};
    const pointer = {{set() {{}}}};
    const camera = {{}};
    const raycaster = {{
        setFromCamera() {{}},
        intersectObjects() {{ return [{{object: hiddenNode}}, {{object: visibleNode}}]; }},
    }};
    const pickRoots = [];
    {pick_at}
    return pickAt(5, 5)?.id || null;
}}
process.stdout.write(JSON.stringify({{
    suspended: run({{suspended: true, person: {{group: {{visible: true}}}}}}),
    invisible: run({{suspended: false, person: {{group: {{visible: false}}}}}}),
}}));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"suspended": "visible", "invisible": "visible"},
            "raycasting must continue past native-replaced actors that cannot be seen",
        )

    def test_native_project_actor_is_listed_only_in_its_current_route_room(self):
        dept_card = _block(self.scene, "function renderDeptCard", "// ── Characters")
        predicate = re.search(
            r"actors\.filter\(\(actor\)\s*=>\s*\(([\s\S]*?)\)\)\.forEach",
            dept_card,
        )
        self.assertIsNotNone(predicate, "the room-card actor predicate must remain testable")
        harness = f"""
const actor = {{
    suspended: false,
    routeId: 'pixelverse-dashboard',
    homeRoom: 'development',
    room: 'infrastructure',
}};
const rooms = ['development', 'infrastructure'];
const matched = rooms.filter((roomId) => {{
    const room = {{id: roomId}};
    return ({predicate.group(1)});
}});
process.stdout.write(JSON.stringify(matched));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            ["infrastructure"],
            "a native route actor belongs only to its current route room card",
        )


if __name__ == "__main__":
    unittest.main()
