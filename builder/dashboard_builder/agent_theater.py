"""Human-facing animated agent scene for Jarvis/Bridge work."""
from __future__ import annotations


THEATER_AGENTS = [
    ("USER", "You", "request", 12, 55),
    ("JARVIS", "Jarvis", "understands", 28, 34),
    ("BRIDGE", "Bridge", "queues", 44, 50),
    ("BUILDER", "Builder", "codes", 63, 32),
    ("TESTER", "Tester", "checks", 77, 48),
    ("DEPLOYER", "Deployer", "ships", 86, 69),
    ("VAULT", "Vault", "remembers", 52, 72),
    ("GITHUB", "GitHub", "records", 24, 76),
]


def _person(agent_id: str, name: str, label: str, x: int, y: int) -> str:
    return f"""
        <button class="theater-person-card" data-theater-agent="{agent_id}" style="--x:{x};--y:{y}" title="{name}">
            <span class="theater-person" aria-hidden="true">
                <span class="theater-person-head"></span>
                <span class="theater-person-torso"></span>
                <span class="theater-person-arm theater-person-arm-a"></span>
                <span class="theater-person-arm theater-person-arm-b"></span>
                <span class="theater-person-leg theater-person-leg-a"></span>
                <span class="theater-person-leg theater-person-leg-b"></span>
            </span>
            <span class="theater-person-name">{name}</span>
            <span class="theater-person-job">{label}</span>
            <span class="theater-person-state">idle</span>
        </button>"""


def build_agent_theater_html() -> str:
    people = "".join(_person(*agent) for agent in THEATER_AGENTS)
    return f"""
<div class="section theater-section" id="theater">
    <div class="section-head theater-head">
        <div class="section-dot" style="background:var(--green)"></div>
        <div class="section-title">Agent Theater</div>
        <div class="section-count" id="theater-status">loading</div>
    </div>
    <div class="operator-status" id="theater-operator-status">
        <div class="operator-card">
            <span class="operator-label">Services</span>
            <strong id="theater-ops-services">checking</strong>
        </div>
        <div class="operator-card">
            <span class="operator-label">Live queue</span>
            <strong id="theater-ops-live">checking</strong>
        </div>
        <div class="operator-card operator-card-wide">
            <span class="operator-label">Main blocker</span>
            <strong id="theater-ops-blocker">checking</strong>
        </div>
        <div class="operator-card operator-card-wide">
            <span class="operator-label">Agent auth</span>
            <strong id="theater-ops-auth">checking</strong>
        </div>
        <div class="operator-card operator-card-wide">
            <span class="operator-label">Next action</span>
            <strong id="theater-ops-next">checking</strong>
        </div>
    </div>
    <div class="theater-layout">
        <div class="theater-stage" id="theater-stage">
            <svg class="theater-map" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true">
                <path class="theater-track theater-track-main" d="M120 310 C210 210 300 190 430 285 S600 210 655 170 S790 195 825 285 S840 370 790 425 S655 462 525 410 S340 410 235 450" />
                <path class="theater-track theater-track-memory" d="M435 290 C470 360 500 402 535 425" />
                <path class="theater-track theater-track-git" d="M430 290 C350 380 285 420 235 450" />
                <path class="theater-track theater-track-deploy" d="M770 285 C845 345 890 392 862 440" />
            </svg>
            <div class="theater-cloud theater-cloud-a"></div>
            <div class="theater-cloud theater-cloud-b"></div>
            <div class="theater-field"></div>
            <div class="theater-tree theater-tree-a"></div>
            <div class="theater-tree theater-tree-b"></div>
            <div class="theater-station theater-station-user" style="--x:12;--y:55">Telegram</div>
            <div class="theater-station theater-station-core" style="--x:28;--y:34">Jarvis</div>
            <div class="theater-station theater-station-queue" style="--x:44;--y:50">Bridge</div>
            <div class="theater-station theater-station-code" style="--x:63;--y:32">Code</div>
            <div class="theater-station theater-station-test" style="--x:77;--y:48">Tests</div>
            <div class="theater-station theater-station-prod" style="--x:86;--y:69">Mac Mini</div>
            <div class="theater-station theater-station-memory" style="--x:52;--y:72">Obsidian</div>
            <div class="theater-station theater-station-git" style="--x:24;--y:76">GitHub</div>
            {people}
            <div class="theater-runners" id="theater-runners"></div>
        </div>
        <aside class="theater-panel">
            <div class="theater-panel-top">
                <div>
                    <span class="theater-kicker">Current mission</span>
                    <strong id="theater-current-title">Waiting for Bridge</strong>
                </div>
                <button class="theater-refresh" id="theater-refresh" type="button" title="Refresh">↻</button>
            </div>
            <div class="theater-current" id="theater-current">
                <div class="theater-empty">No live task selected.</div>
            </div>
            <div class="theater-story-head">
                <span class="theater-kicker">Live story</span>
                <span id="theater-story-count">0 events</span>
            </div>
            <div class="theater-story" id="theater-story">
                <div class="theater-empty">Loading task events...</div>
            </div>
        </aside>
    </div>
</div>"""
