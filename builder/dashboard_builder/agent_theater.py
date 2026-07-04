"""Human-facing animated agent scene for Jarvis/Bridge work."""
from __future__ import annotations


THEATER_AGENTS = [
    ("USER", "You", "request", 7, 48),
    ("JARVIS", "Jarvis", "understands", 22, 24),
    ("BRIDGE", "Bridge", "queues", 40, 42),
    ("BUILDER", "Builder", "codes", 61, 20),
    ("TESTER", "Tester", "checks", 78, 38),
    ("DEPLOYER", "Deployer", "ships", 84, 68),
    ("VAULT", "Vault", "remembers", 48, 72),
    ("GITHUB", "GitHub", "records", 20, 72),
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
    <div class="theater-layout">
        <div class="theater-stage" id="theater-stage">
            <svg class="theater-map" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true">
                <path class="theater-track theater-track-main" d="M80 280 C160 145 250 125 395 240 S565 160 620 118 S770 150 825 220 S870 325 835 382 S730 460 570 418 S370 420 220 405" />
                <path class="theater-track theater-track-memory" d="M405 248 C455 360 485 398 512 420" />
                <path class="theater-track theater-track-git" d="M405 250 C320 360 245 390 205 407" />
                <path class="theater-track theater-track-deploy" d="M780 225 C850 305 875 355 840 405" />
            </svg>
            <div class="theater-station theater-station-user" style="--x:7;--y:48">Telegram</div>
            <div class="theater-station theater-station-core" style="--x:22;--y:24">Jarvis</div>
            <div class="theater-station theater-station-queue" style="--x:40;--y:42">Bridge</div>
            <div class="theater-station theater-station-code" style="--x:61;--y:20">Code</div>
            <div class="theater-station theater-station-test" style="--x:78;--y:38">Tests</div>
            <div class="theater-station theater-station-prod" style="--x:84;--y:68">Mac Mini</div>
            <div class="theater-station theater-station-memory" style="--x:48;--y:72">Obsidian</div>
            <div class="theater-station theater-station-git" style="--x:20;--y:72">GitHub</div>
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
