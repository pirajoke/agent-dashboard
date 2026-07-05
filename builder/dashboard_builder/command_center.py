"""Live systems command center for machine health and agent flow."""
from __future__ import annotations


FLOW_NODES = [
    ("USER", "You", "request"),
    ("JARVIS", "Jarvis", "intent + context"),
    ("SUPERVISOR", "Supervisor", "routing decision"),
    ("BRIDGE", "Bridge", "task queue"),
    ("AGENT", "Agent", "work execution"),
    ("SYSTEM", "System", "Mac Mini / Air / Pro"),
    ("VAULT", "Vault", "Obsidian memory"),
    ("GITHUB", "GitHub", "source control"),
]


def _flow_node(node_id: str, label: str, detail: str) -> str:
    return f"""
        <div class="command-flow-node" data-command-flow-node="{node_id}">
            <strong>{label}</strong>
            <span>{detail}</span>
        </div>"""


def build_command_center_html() -> str:
    flow_nodes = "".join(_flow_node(*node) for node in FLOW_NODES)
    return f"""
<div class="section command-center" id="command-center">
    <div class="section-head command-head">
        <div class="section-dot" style="background:var(--blue)"></div>
        <div class="section-title">Systems Command Center</div>
        <div class="section-count" id="command-status">checking</div>
    </div>
    <div class="command-layout">
        <div class="command-systems">
            <article class="command-system-card" id="command-system-mini" data-command-system="mac-mini">
                <div class="command-system-top">
                    <div>
                        <span class="command-kicker">Production runtime</span>
                        <strong>Mac Mini</strong>
                    </div>
                    <span class="command-state" id="command-mini-status">checking</span>
                </div>
                <div class="command-system-summary" id="command-mini-summary">Waiting for /api/health</div>
                <div class="command-system-metrics">
                    <div><span id="command-mini-services-count">-</span><em>services</em></div>
                    <div><span id="command-mini-auth">-</span><em>agent auth</em></div>
                    <div><span id="command-mini-updated">-</span><em>updated</em></div>
                </div>
                <div class="command-service-list" id="command-mini-services">
                    <div class="command-empty">Loading Mac Mini services...</div>
                </div>
            </article>
            <article class="command-system-card" id="command-system-air" data-command-system="macbook-air">
                <div class="command-system-top">
                    <div>
                        <span class="command-kicker">Local workstation</span>
                        <strong>MacBook Air</strong>
                    </div>
                    <span class="command-state" id="command-air-status">checking</span>
                </div>
                <div class="command-system-summary" id="command-air-summary">Waiting for /api/air/health</div>
                <div class="command-system-metrics">
                    <div><span id="command-air-services-count">-</span><em>services</em></div>
                    <div><span id="command-air-auth">-</span><em>agent auth</em></div>
                    <div><span id="command-air-updated">-</span><em>updated</em></div>
                </div>
                <div class="command-service-list" id="command-air-services">
                    <div class="command-empty">Loading MacBook Air services...</div>
                </div>
            </article>
            <article class="command-system-card" id="command-system-pro" data-command-system="macbook-pro">
                <div class="command-system-top">
                    <div>
                        <span class="command-kicker">Primary workstation</span>
                        <strong>MacBook Pro</strong>
                    </div>
                    <span class="command-state" id="command-pro-status">checking</span>
                </div>
                <div class="command-system-summary" id="command-pro-summary">Waiting for /api/pro/health</div>
                <div class="command-system-metrics">
                    <div><span id="command-pro-services-count">-</span><em>services</em></div>
                    <div><span id="command-pro-auth">-</span><em>agent auth</em></div>
                    <div><span id="command-pro-updated">-</span><em>updated</em></div>
                </div>
                <div class="command-service-list" id="command-pro-services">
                    <div class="command-empty">Loading MacBook Pro services...</div>
                </div>
            </article>
        </div>
        <aside class="command-flow-panel">
            <div class="command-flow-head">
                <div>
                    <span class="command-kicker">Agent flow</span>
                    <strong id="command-flow-task">Waiting for Bridge</strong>
                </div>
                <button class="command-refresh" id="command-refresh" type="button" title="Refresh command center">&#8635;</button>
            </div>
            <div class="command-flow-strip" id="command-flow">
                {flow_nodes}
            </div>
            <div class="command-flow-meta">
                <div>
                    <span>Route</span>
                    <strong id="command-flow-route">-</strong>
                </div>
                <div>
                    <span>State</span>
                    <strong id="command-flow-state">-</strong>
                </div>
                <div>
                    <span>Blocker</span>
                    <strong id="command-flow-blocker">-</strong>
                </div>
            </div>
            <div class="command-live-log" id="command-live-log">
                <div class="command-empty">No live flow events yet.</div>
            </div>
        </aside>
    </div>
</div>"""
