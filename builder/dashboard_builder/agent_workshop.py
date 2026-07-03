"""Agent Workshop section for visualizing live Jarvis/Bridge work."""
from __future__ import annotations


AGENT_ROOMS = [
    ("ROUTER", "Router", "Telegram intake", "15%", "22%"),
    ("PLANNER", "Planner", "Scope and steps", "38%", "18%"),
    ("BUILDER", "Builder", "Code changes", "63%", "21%"),
    ("TESTER", "Tester", "Tests and smoke", "84%", "34%"),
    ("DEPLOYER", "Deployer", "Mac Mini rollout", "74%", "68%"),
    ("VAULT", "Vault", "Obsidian memory", "45%", "72%"),
    ("GITHUB", "GitHub", "Commits and issues", "20%", "68%"),
]


def _agent_button(agent_id: str, name: str, room: str, left: str, top: str) -> str:
    return f"""
        <button class="workshop-agent" data-workshop-agent="{agent_id}" style="left:{left};top:{top}" title="{name}">
            <span class="workshop-figure" aria-hidden="true">
                <span class="workshop-head"></span>
                <span class="workshop-body"></span>
                <span class="workshop-leg workshop-leg-a"></span>
                <span class="workshop-leg workshop-leg-b"></span>
            </span>
            <span class="workshop-agent-name">{name}</span>
            <span class="workshop-agent-room">{room}</span>
            <span class="workshop-agent-state">idle</span>
        </button>"""


def build_agent_workshop_html() -> str:
    agents = "".join(_agent_button(*room) for room in AGENT_ROOMS)
    return f"""
<div class="section" id="workshop">
    <div class="section-head">
        <div class="section-dot" style="background:var(--cyan)"></div>
        <div class="section-title">Agent Workshop</div>
        <div class="section-count" id="workshop-status">loading</div>
    </div>
    <div class="workshop-shell">
        <div class="workshop-main">
            <div class="workshop-metrics">
                <div><span id="workshop-count-running">0</span><em>running</em></div>
                <div><span id="workshop-count-pending">0</span><em>pending</em></div>
                <div><span id="workshop-count-blocked">0</span><em>blocked</em></div>
                <div><span id="workshop-count-done">0</span><em>done</em></div>
            </div>
            <div class="workshop-board" id="workshop-board">
                <svg class="workshop-routes" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M160 120 C260 70 330 80 410 110 S560 160 650 120 S805 110 885 190" />
                    <path d="M640 155 C690 245 710 310 760 390" />
                    <path d="M620 150 C555 260 500 330 455 385" />
                    <path d="M425 380 C335 395 250 390 190 365" />
                </svg>
                <div class="workshop-room workshop-room-intake" style="left:6%;top:8%">Telegram</div>
                <div class="workshop-room workshop-room-code" style="left:56%;top:10%">Repo</div>
                <div class="workshop-room workshop-room-runtime" style="left:69%;top:56%">Mac Mini</div>
                <div class="workshop-room workshop-room-memory" style="left:35%;top:58%">Obsidian</div>
                <div class="workshop-room workshop-room-git" style="left:8%;top:56%">GitHub</div>
                {agents}
                <div class="workshop-markers" id="workshop-markers"></div>
            </div>
        </div>
        <aside class="workshop-side">
            <div class="workshop-side-head">
                <div>
                    <span class="workshop-side-kicker">Bridge queue</span>
                    <strong id="workshop-side-title">Recent work</strong>
                </div>
                <button class="workshop-icon-btn" id="workshop-refresh" type="button" title="Refresh workshop">&#8635;</button>
            </div>
            <div class="workshop-task-list" id="workshop-task-list">
                <div class="workshop-empty">Loading live tasks...</div>
            </div>
        </aside>
    </div>
    <div class="workshop-drawer hidden" id="workshop-drawer" aria-live="polite">
        <div class="workshop-drawer-panel">
            <button class="workshop-drawer-close" id="workshop-drawer-close" type="button" title="Close">&times;</button>
            <div id="workshop-drawer-content"></div>
        </div>
    </div>
</div>"""
