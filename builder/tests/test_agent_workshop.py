from __future__ import annotations

from pathlib import Path
import unittest

from dashboard_builder.agent_theater import THEATER_AGENTS, build_agent_theater_html
from dashboard_builder.agent_workshop import AGENT_ROOMS, build_agent_workshop_html
from dashboard_builder.command_center import FLOW_NODES, build_command_center_html
from dashboard_builder.html_builder import build_html

ASSETS_DIR = Path(__file__).resolve().parents[1] / "dashboard-assets"
BUILDER_DIR = Path(__file__).resolve().parents[1]


class AgentTheaterTests(unittest.TestCase):
    def test_agent_theater_html_contains_scene_hooks(self):
        html = build_agent_theater_html()

        self.assertIn('id="theater"', html)
        self.assertIn('id="theater-stage"', html)
        self.assertIn('id="theater-runners"', html)
        self.assertIn('id="theater-operator-status"', html)
        self.assertIn('id="theater-ops-services"', html)
        self.assertIn('id="theater-ops-blocker"', html)
        self.assertIn('id="theater-ops-auth"', html)
        self.assertIn('id="theater-current"', html)
        self.assertIn('id="theater-story"', html)
        self.assertIn('data-theater-agent="JARVIS"', html)
        self.assertIn('data-theater-agent="SUPERVISOR"', html)
        self.assertIn('theater-station-supervisor', html)
        self.assertIn('data-theater-agent="BUILDER"', html)
        self.assertIn('data-theater-agent="VAULT"', html)
        self.assertGreaterEqual(len(THEATER_AGENTS), 9)

    def test_full_dashboard_includes_theater_navigation(self):
        html = build_html([], "2026-07-04 12:00:00 ICT")

        self.assertIn('data-target="#theater"', html)
        self.assertIn('<li><a data-target="#theater" href="javascript:void(0)" class="active">', html)
        self.assertIn("Agent Theater", html)
        self.assertIn("initAgentTheater", html)
        self.assertIn("theater-runners", html)
        self.assertIn("theaterPersonWalk", html)
        self.assertLess(html.index("Agent Theater"), html.index("Systems Command Center"))

    def test_agent_theater_uses_ai_town_sprite_asset(self):
        css = (ASSETS_DIR / "style.css").read_text()
        script = (ASSETS_DIR / "script.js").read_text()

        self.assertIn("ai-town-32x32folk.png", css)
        self.assertIn("data-runner-agent", script)
        self.assertIn("focus task", script)
        self.assertIn("slice(0, 1)", script)
        self.assertNotIn("slice(0, 5)", script)
        self.assertIn("theaterIsLiveTask", script)
        self.assertIn("renderOperatorStatus", script)
        self.assertIn("theaterAuthState", script)
        self.assertIn("Claude login required", script)
        self.assertIn("Recent Bridge task failed", script)
        self.assertIn("SUPERVISOR", script)
        self.assertIn("'USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE'", script)
        self.assertIn("is-doing", script)
        self.assertIn("theaterAgentAction", script)
        self.assertIn("data-action", css)
        self.assertIn("theaterAgentPatrol", css)
        self.assertTrue((ASSETS_DIR / "ai-town-32x32folk.png").exists())
        self.assertGreater((ASSETS_DIR / "ai-town-32x32folk.png").stat().st_size, 1000)


class AgentWorkshopTests(unittest.TestCase):
    def test_agent_workshop_html_contains_live_bridge_hooks(self):
        html = build_agent_workshop_html()

        self.assertIn('id="workshop"', html)
        self.assertIn('id="workshop-board"', html)
        self.assertIn('id="workshop-task-list"', html)
        self.assertIn('id="workshop-drawer"', html)
        self.assertIn('id="workshop-control-room"', html)
        self.assertIn('id="workshop-selected-task"', html)
        self.assertIn('id="workshop-causal-graph"', html)
        self.assertIn('id="workshop-causal-reasons"', html)
        self.assertIn('id="workshop-causal-timeline"', html)
        self.assertIn('data-workshop-agent="BUILDER"', html)
        self.assertIn('data-workshop-agent="VAULT"', html)
        self.assertGreaterEqual(len(AGENT_ROOMS), 7)

    def test_full_dashboard_includes_workshop_navigation(self):
        html = build_html([], "2026-07-03 12:00:00 ICT")

        self.assertIn('data-target="#workshop"', html)
        self.assertIn("Agent Workshop", html)
        self.assertIn("Control Room", html)
        self.assertIn("initAgentWorkshop", html)
        self.assertIn("renderCausalView", html)
        self.assertIn("readMetadata", html)
        self.assertIn("structured Bridge event", html)


class SystemsCommandCenterTests(unittest.TestCase):
    def test_command_center_html_contains_system_and_flow_hooks(self):
        html = build_command_center_html()

        self.assertIn('id="command-center"', html)
        self.assertIn('id="command-system-mini"', html)
        self.assertIn('id="command-system-air"', html)
        self.assertIn('id="command-system-pro"', html)
        self.assertIn('id="command-mini-services"', html)
        self.assertIn('id="command-air-services"', html)
        self.assertIn('id="command-pro-services"', html)
        self.assertIn('id="command-flow"', html)
        self.assertIn('data-command-flow-node="SUPERVISOR"', html)
        self.assertIn('data-command-flow-node="SYSTEM"', html)
        self.assertGreaterEqual(len(FLOW_NODES), 8)

    def test_full_dashboard_includes_systems_command_center(self):
        html = build_html([], "2026-07-05 12:00:00 ICT")

        self.assertIn('data-target="#command-center"', html)
        self.assertIn("Systems Command Center", html)
        self.assertIn("initSystemsCommandCenter", html)
        self.assertIn("/api/air/health", html)
        self.assertIn("/api/pro/health", html)
        self.assertIn("/api/local-services", html)
        self.assertIn("SystemsCommandCenterRefresh", html)


class JarvisPipelineLaunchTests(unittest.TestCase):
    def test_public_dashboard_locks_run_until_token_is_present(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text()

        self.assertLess(html.index('id="jarvis-token-box"'), html.index('class="jarvis-run-form"'))
        self.assertIn("runButton.disabled = locked", html)
        self.assertIn("locked ? 'Token required' : 'Create draft'", html)
        self.assertIn("Unlock this browser before launching agents.", html)
        self.assertIn("JARVIS_TASK_DRAFT_API", html)
        self.assertIn("GitHub draft created", html)
        self.assertIn("@media (max-width: 1100px)", html)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", html)

    def test_unlock_helper_and_server_restart_are_deployable(self):
        helper = (BUILDER_DIR / "mm-command-center-auth").read_text()
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        server = (BUILDER_DIR / "dashboard-server-m4.py").read_text()

        self.assertIn("dashboard_run_token", helper)
        self.assertIn('ssh "$MAC_MINI_HOST"', helper)
        self.assertIn('open "${COMMAND_CENTER_URL}#dashboard_run_token=${token}"', helper)
        self.assertIn('mm-command-center-auth"', deploy)
        self.assertIn("launchctl kickstart -k", deploy)
        self.assertIn("/api/jarvis/tasks/draft", server)
        self.assertIn("jarvis.dashboard_task_intake", server)
        self.assertIn("task contains secret-like text", server)


if __name__ == "__main__":
    unittest.main()
