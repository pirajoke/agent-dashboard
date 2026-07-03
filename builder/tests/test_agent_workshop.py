from __future__ import annotations

import unittest

from dashboard_builder.agent_workshop import AGENT_ROOMS, build_agent_workshop_html
from dashboard_builder.html_builder import build_html


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


if __name__ == "__main__":
    unittest.main()
