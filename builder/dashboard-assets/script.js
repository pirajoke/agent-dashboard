// ── Prevent hash-triggered scroll jumps on interactive clicks ──
(function() {
    const p = new URLSearchParams(location.search).get('token');
    if (p) {
        fetch('http://localhost:7777/api/github/token', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: p})
        }).finally(() => history.replaceState(null, '', location.pathname + location.hash));
    }
    // Sidebar nav: scroll + active highlight
    const navLinks = document.querySelectorAll('.sidebar-nav a[data-target]');
    navLinks.forEach(a => {
        a.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.dataset.target);
            if (target) target.scrollIntoView({behavior:'smooth'});
            navLinks.forEach(l => l.classList.remove('active'));
            this.classList.add('active');
        });
    });
    // Scroll spy: highlight active nav on scroll
    const sections = Array.from(navLinks).map(a => document.querySelector(a.dataset.target)).filter(Boolean);
    let ticking = false;
    window.addEventListener('scroll', () => {
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(() => {
                let current = sections[0];
                for (const s of sections) {
                    if (s.getBoundingClientRect().top <= 120) current = s;
                }
                navLinks.forEach(a => {
                    a.classList.toggle('active', a.dataset.target === '#' + current.id);
                });
                ticking = false;
            });
        }
    });
})();

const GH_REPO = 'pirajoke/agent-dashboard';
const GH_MODE_PATH = 'mode-request.json';
const LOCAL_API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:7777'
    : window.location.origin;

// ══════════════════════════════════════════════════════════════
// ── Phase 1: Staleness Banner ──
// ══════════════════════════════════════════════════════════════
(function initStaleness() {
    const tsEl = document.querySelector('.topbar-meta .tm-item:last-child');
    if (!tsEl) return;
    const tsText = tsEl.textContent.trim();
    // Parse "2026-04-20 14:30:00 ICT" format
    const match = tsText.match(/(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/);
    if (!match) return;
    const buildTime = new Date(`${match[1]}T${match[2]}+07:00`); // ICT = UTC+7
    const now = new Date();
    const ageMin = Math.floor((now - buildTime) / 60000);

    if (ageMin > 30) {
        const banner = document.createElement('div');
        banner.className = 'staleness-banner';
        const ageLabel = ageMin > 1440 ? `${Math.floor(ageMin/1440)}d ago` :
                         ageMin > 60 ? `${Math.floor(ageMin/60)}h ago` : `${ageMin}m ago`;
        banner.innerHTML = `<span class="stale-icon">⚠</span> Dashboard data is stale (built ${ageLabel}). <span class="stale-action" onclick="location.reload()">Refresh</span>`;
        document.querySelector('.main').prepend(banner);
    }
})();

// ══════════════════════════════════════════════════════════════
// ── Phase 1: "Since Last Visit" Block ──
// ══════════════════════════════════════════════════════════════
(function initSinceLastVisit() {
    const STORAGE_KEY = 'cc_last_visit';
    const SNAPSHOT_KEY = 'cc_snapshot';
    const now = Date.now();
    const lastVisit = localStorage.getItem(STORAGE_KEY);
    const prevSnapshot = localStorage.getItem(SNAPSHOT_KEY);

    // Collect current state snapshot
    const currentSnapshot = {
        agents: [],
        projects: [],
        openTasks: 0,
        closedTasks: 0,
    };

    // Parse agents
    document.querySelectorAll('.ag').forEach(el => {
        const id = el.querySelector('.ag-id')?.textContent?.trim() || '';
        const health = el.classList.contains('ag-active') ? 'active' :
                       el.classList.contains('ag-blocked') ? 'blocked' : 'idle';
        const tasks = parseInt(el.querySelector('.ag-tasks')?.textContent) || 0;
        currentSnapshot.agents.push({id, health, tasks});
    });

    // Parse projects from table
    document.querySelectorAll('#projects tbody tr').forEach(tr => {
        const name = tr.querySelector('.proj-name')?.textContent?.trim() || '';
        const status = tr.querySelector('.status-pill')?.textContent?.trim() || '';
        const open = parseInt(tr.children[2]?.textContent) || 0;
        currentSnapshot.projects.push({name, status, open});
        currentSnapshot.openTasks += open;
    });

    // Parse stats
    const statVals = document.querySelectorAll('.stat-val');
    if (statVals.length >= 4) {
        currentSnapshot.openTasks = parseInt(statVals[2]?.textContent) || 0;
        currentSnapshot.closedTasks = parseInt(statVals[3]?.textContent) || 0;
    }

    // Save current visit
    localStorage.setItem(STORAGE_KEY, now.toString());
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(currentSnapshot));

    // If no previous visit, skip
    if (!lastVisit || !prevSnapshot) return;

    let prev;
    try { prev = JSON.parse(prevSnapshot); } catch(e) { return; }

    // Compute diff
    const changes = [];
    const lastTime = parseInt(lastVisit);
    const agoMin = Math.floor((now - lastTime) / 60000);
    const agoLabel = agoMin > 1440 ? `${Math.floor(agoMin/1440)}d` :
                     agoMin > 60 ? `${Math.floor(agoMin/60)}h` : `${agoMin}m`;

    // Task delta
    const taskDelta = currentSnapshot.openTasks - (prev.openTasks || 0);
    const closedDelta = currentSnapshot.closedTasks - (prev.closedTasks || 0);
    if (closedDelta > 0) changes.push(`<span class="slv-good">+${closedDelta} tasks completed</span>`);
    if (taskDelta > 0) changes.push(`<span class="slv-warn">+${taskDelta} new open tasks</span>`);
    if (taskDelta < 0 && closedDelta <= 0) changes.push(`<span class="slv-good">${Math.abs(taskDelta)} tasks resolved</span>`);

    // Agent health changes
    const prevAgentMap = {};
    (prev.agents || []).forEach(a => prevAgentMap[a.id] = a);
    currentSnapshot.agents.forEach(a => {
        const pa = prevAgentMap[a.id];
        if (pa && pa.health !== a.health) {
            const icon = a.health === 'blocked' ? '🔴' : a.health === 'active' ? '🟢' : '🟡';
            changes.push(`${icon} <strong>${a.id}</strong> ${pa.health} → ${a.health}`);
        }
    });

    // Project changes
    const prevProjMap = {};
    (prev.projects || []).forEach(p => prevProjMap[p.name] = p);
    currentSnapshot.projects.forEach(p => {
        const pp = prevProjMap[p.name];
        if (!pp) {
            changes.push(`<span class="slv-new">New project: ${p.name}</span>`);
        } else if (pp.status !== p.status) {
            changes.push(`<strong>${p.name}</strong> status: ${pp.status} → ${p.status}`);
        }
    });

    if (changes.length === 0) changes.push('<span class="slv-calm">No changes since your last visit</span>');

    // Render block
    const block = document.createElement('div');
    block.className = 'since-last-visit';
    block.innerHTML = `
        <div class="slv-header">
            <span class="slv-title">Since last visit</span>
            <span class="slv-ago">${agoLabel} ago</span>
        </div>
        <div class="slv-items">${changes.map(c => `<div class="slv-item">${c}</div>`).join('')}</div>
    `;

    // Insert after stats
    const stats = document.querySelector('.stats');
    if (stats) stats.after(block);
})();

// ══════════════════════════════════════════════════════════════
// ── Phase 1: Exception-based Agent Display ──
// ══════════════════════════════════════════════════════════════
(function initExceptionView() {
    const agentsContainer = document.querySelector('.agents');
    if (!agentsContainer) return;
    const agents = agentsContainer.querySelectorAll('.ag');
    const healthy = [];
    const problematic = [];
    agents.forEach(el => {
        if (el.classList.contains('ag-active')) healthy.push(el);
        else problematic.push(el);
    });
    // If all healthy or all problematic, don't rearrange
    if (problematic.length === 0 || healthy.length === 0) return;
    // Move problematic first
    problematic.forEach(el => agentsContainer.prepend(el));
    // Collapse healthy agents
    if (healthy.length > 2) {
        const toggle = document.createElement('div');
        toggle.className = 'agents-collapse-toggle';
        toggle.innerHTML = `<span class="act-text">Show ${healthy.length} healthy agents</span>`;
        toggle.style.cursor = 'pointer';
        let collapsed = true;
        healthy.forEach(el => el.classList.add('ag-collapsed'));
        toggle.addEventListener('click', () => {
            collapsed = !collapsed;
            healthy.forEach(el => el.classList.toggle('ag-collapsed', collapsed));
            toggle.querySelector('.act-text').textContent = collapsed
                ? `Show ${healthy.length} healthy agents`
                : `Hide healthy agents`;
        });
        // Insert toggle after last problematic
        const lastProb = problematic[problematic.length - 1];
        lastProb.after(toggle);
    }
})();

// ══════════════════════════════════════════════════════════════
// ── Builder Dialogue ──
// ══════════════════════════════════════════════════════════════
(function initBuilderDialogue() {
    const feed = document.getElementById('builder-feed');
    const form = document.getElementById('builder-form');
    const statusEl = document.getElementById('builder-status');
    if (!feed) return;

    const esc = (value) => String(value || '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));

    function shortTime(raw) {
        if (!raw) return '';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return raw.slice(0, 16);
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    function renderTask(task) {
        const messages = (task.messages || []).slice(-5).map((m) => `
            <div class="builder-msg" data-sender="${esc(m.sender)}">
                <div class="builder-msg-meta">${esc(shortTime(m.created_at))} · ${esc(m.sender)} → ${esc(m.receiver)} · ${esc(m.type)}</div>
                <div class="builder-msg-body">${esc(m.body).slice(0, 1200)}</div>
            </div>
        `).join('');
        return `
            <div class="builder-task">
                <div class="builder-task-head">
                    <code class="builder-task-id">${esc(task.id)}</code>
                    <span class="builder-task-role">${esc(task.agent_role || 'AUTO')}</span>
                    <span class="builder-task-state ${esc(task.status)}">${esc(task.status)}</span>
                </div>
                <div class="builder-task-desc">${esc(task.description)}</div>
                <div class="builder-messages">${messages || '<div class="builder-empty">No dialogue yet</div>'}</div>
            </div>
        `;
    }

    async function refreshBuilder() {
        try {
            const res = await fetch('/api/bridge/tasks?limit=12&include_messages=1', {cache: 'no-store'});
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const tasks = data.tasks || [];
            const builderTasks = tasks.filter((t) => !t.agent_role || String(t.agent_role).toUpperCase() === 'BUILDER');
            if (statusEl) statusEl.textContent = `${builderTasks.length} recent`;
            feed.innerHTML = builderTasks.length
                ? builderTasks.map(renderTask).join('')
                : '<div class="builder-empty">No Builder tasks yet</div>';
        } catch (err) {
            if (statusEl) statusEl.textContent = 'offline';
            feed.innerHTML = `<div class="builder-empty">Bridge unavailable: ${esc(err.message)}</div>`;
        }
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = form.querySelector('[name="description"]');
            const description = input.value.trim();
            if (!description) return;
            form.querySelector('button').disabled = true;
            try {
                await fetch('/api/bridge/dispatch', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({description, agent_role: 'BUILDER'})
                });
                input.value = '';
                await refreshBuilder();
            } finally {
                form.querySelector('button').disabled = false;
            }
        });
    }

    refreshBuilder();
    setInterval(refreshBuilder, 5000);
})();

// ══════════════════════════════════════════════════════════════
// ── Agent Workshop ──
// ══════════════════════════════════════════════════════════════
(function initAgentWorkshop() {
    const board = document.getElementById('workshop-board');
    const markersEl = document.getElementById('workshop-markers');
    const taskList = document.getElementById('workshop-task-list');
    const statusEl = document.getElementById('workshop-status');
    const refreshBtn = document.getElementById('workshop-refresh');
    const drawer = document.getElementById('workshop-drawer');
    const drawerContent = document.getElementById('workshop-drawer-content');
    const drawerClose = document.getElementById('workshop-drawer-close');
    const selectedTaskEl = document.getElementById('workshop-selected-task');
    const causalSummaryEl = document.getElementById('workshop-causal-summary');
    const causalGraphEl = document.getElementById('workshop-causal-graph');
    const causalReasonsEl = document.getElementById('workshop-causal-reasons');
    const causalTimelineEl = document.getElementById('workshop-causal-timeline');
    if (!board || !markersEl || !taskList) return;

    const AGENT_POSITIONS = {
        ROUTER: {x: 15, y: 22},
        PLANNER: {x: 38, y: 18},
        BUILDER: {x: 63, y: 21},
        TESTER: {x: 84, y: 34},
        DEPLOYER: {x: 74, y: 68},
        VAULT: {x: 45, y: 72},
        GITHUB: {x: 20, y: 68},
    };
    const AGENT_LABELS = {
        ROUTER: 'Router',
        PLANNER: 'Planner',
        BUILDER: 'Builder',
        TESTER: 'Tester',
        DEPLOYER: 'Deployer',
        VAULT: 'Vault',
        GITHUB: 'GitHub',
    };
    let latestTasks = [];
    let selectedTaskId = null;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));

    function shortTime(raw) {
        if (!raw) return '';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return String(raw).slice(0, 16);
        return d.toLocaleString([], {month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'});
    }

    function asText(value) {
        if (value == null) return '';
        if (typeof value === 'string') return value;
        try {
            return JSON.stringify(value);
        } catch (_) {
            return String(value);
        }
    }

    function compact(value, limit = 160) {
        const text = asText(value).replace(/\s+/g, ' ').trim();
        if (!text) return '';
        return text.length > limit ? text.slice(0, limit - 3).trim() + '...' : text;
    }

    function taskId(task) {
        return String(task?.id ?? '');
    }

    function readMetadata(item) {
        const raw = item?.metadata ?? item?.meta ?? null;
        if (!raw) return {};
        if (typeof raw === 'object') return raw;
        try {
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_) {
            return {};
        }
    }

    function messageMetadata(task) {
        return (task.messages || []).map(readMetadata).filter((meta) => Object.keys(meta).length);
    }

    function firstMetadataValue(task, keys) {
        const metas = [readMetadata(task), ...messageMetadata(task)];
        for (const meta of metas) {
            for (const key of keys) {
                if (meta[key] != null && meta[key] !== '') return meta[key];
            }
        }
        return '';
    }

    const TOOL_DETAILS = {
        telegram: {label: 'Telegram', detail: 'user message and bot reply'},
        obsidian: {label: 'Obsidian', detail: 'memory, status, project notes'},
        github: {label: 'GitHub', detail: 'commits, push, issues, source control'},
        repo: {label: 'Repo', detail: 'local code checkout'},
        tests: {label: 'Tests', detail: 'unit tests, smoke checks, compile'},
        macmini: {label: 'Mac Mini', detail: 'production runtime and launchd'},
        linear: {label: 'Linear', detail: 'project/task tracking'},
        bridge: {label: 'Bridge', detail: 'task queue and agent messages'},
        claude: {label: 'Claude', detail: 'worker execution model'},
    };

    function normalizeToolName(value) {
        return String(value || '').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '');
    }

    function structuredTools(task) {
        const names = [];
        const metas = [readMetadata(task), ...messageMetadata(task)];
        metas.forEach((meta) => {
            [...(Array.isArray(meta.tools) ? meta.tools : []), ...(Array.isArray(meta.tool_hints) ? meta.tool_hints : [])]
                .forEach((tool) => names.push(normalizeToolName(tool)));
            (Array.isArray(meta.calls) ? meta.calls : []).forEach((call) => {
                const callName = normalizeToolName(call);
                if (callName.includes('claude')) names.push('claude');
                if (callName.includes('bridge')) names.push('bridge');
                if (callName.includes('test')) names.push('tests');
            });
        });
        return [...new Set(names)]
            .filter(Boolean)
            .map((name) => TOOL_DETAILS[name] || {label: name, detail: 'structured Bridge metadata'});
    }

    function normalizedState(task) {
        const raw = String(task.status || task.state || '').toLowerCase();
        const outcome = `${task.error || ''} ${asText(task.result)}`.toLowerCase();
        if (outcome.match(/\b(authentication_error|failed|traceback|exception|exit code [1-9]|error: 4\d\d|error: 5\d\d)\b/)) {
            return 'failed';
        }
        if (['done', 'complete', 'completed', 'success', 'succeeded'].includes(raw)) return 'done';
        if (['failed', 'error'].includes(raw)) return 'failed';
        if (['blocked', 'waiting', 'needs_input'].includes(raw)) return 'blocked';
        if (['cancelled', 'canceled'].includes(raw)) return 'cancelled';
        if (['running', 'in_progress', 'working', 'active'].includes(raw)) return 'running';
        return 'pending';
    }

    function taskText(task) {
        const msgText = (task.messages || []).map((m) => [m.sender, m.receiver, m.type, m.body].join(' ')).join(' ');
        const metaText = [readMetadata(task), ...messageMetadata(task)].map(asText).join(' ');
        return `${task.description || ''} ${task.agent_role || ''} ${task.error || ''} ${asText(task.result)} ${msgText} ${metaText}`.toLowerCase();
    }

    function deriveAgent(task) {
        const text = taskText(task);
        const role = String(task.agent_role || '').toUpperCase().replace(/[^A-Z_]/g, '');
        if (['ROUTER', 'PLANNER', 'BUILDER', 'TESTER', 'DEPLOYER', 'VAULT', 'GITHUB'].includes(role)) return role;
        if (text.match(/\b(pytest|test|selftest|smoke|compileall|validation)\b/)) return 'TESTER';
        if (text.match(/\b(deploy|launchd|restart|rollout|mac mini|macmini|service)\b/)) return 'DEPLOYER';
        if (text.match(/\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|source-aware)\b/)) return 'VAULT';
        if (text.match(/\b(github|git push|commit|pull request|linear|issue)\b/)) return 'GITHUB';
        if (text.match(/\b(plan|scope|breakdown|handoff|acceptance)\b/)) return 'PLANNER';
        if (text.match(/\b(route|router|telegram intake|intent)\b/)) return 'ROUTER';
        return 'BUILDER';
    }

    function taskTitle(task) {
        const raw = String(task.description || task.title || 'Untitled task').replace(/\s+/g, ' ').trim();
        return raw.length > 110 ? raw.slice(0, 107).trim() + '...' : raw;
    }

    function agentReason(task, agent) {
        const text = taskText(task);
        const role = String(task.agent_role || '').toUpperCase().replace(/[^A-Z_]/g, '');
        const structuredReason = firstMetadataValue(task, ['route_reason', 'reason']);
        const routeSource = firstMetadataValue(task, ['route_source', 'entrypoint']);
        if (structuredReason) {
            const suffix = routeSource ? ` (${routeSource})` : '';
            return `${AGENT_LABELS[agent] || agent} selected from structured Bridge event${suffix}: ${structuredReason}.`;
        }
        if (agent === 'TESTER' && text.match(/\b(pytest|test|selftest|smoke|compileall|validation)\b/)) {
            return 'TESTER selected because the task mentions validation, smoke tests, compile checks, or pytest.';
        }
        if (agent === 'DEPLOYER' && text.match(/\b(deploy|launchd|restart|rollout|mac mini|macmini|service)\b/)) {
            return 'DEPLOYER selected because the task touches rollout, launchd, service restart, or Mac Mini runtime.';
        }
        if (agent === 'VAULT' && text.match(/\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|source-aware)\b/)) {
            return 'VAULT selected because the task needs Obsidian memory, status files, or source-aware notes.';
        }
        if (agent === 'GITHUB' && text.match(/\b(github|git push|commit|pull request|linear|issue)\b/)) {
            return 'GITHUB selected because the task mentions commits, GitHub, pull requests, Linear, or issues.';
        }
        if (agent === 'PLANNER' && text.match(/\b(plan|scope|breakdown|handoff|acceptance)\b/)) {
            return 'PLANNER selected because the task asks for planning, scope, breakdown, handoff, or acceptance criteria.';
        }
        if (agent === 'ROUTER' && text.match(/\b(route|router|telegram intake|intent)\b/)) {
            return 'ROUTER selected because the task is about Telegram intake, routing, or intent detection.';
        }
        if (role && AGENT_LABELS[role]) {
            return `${AGENT_LABELS[role]} selected from explicit Bridge role ${role}.`;
        }
        return `${AGENT_LABELS[agent] || agent} selected as the default code/problem-solving agent.`;
    }

    function inferTools(task) {
        const structured = structuredTools(task);
        if (structured.length) return structured;
        const text = taskText(task);
        const rules = [
            {id: 'telegram', label: 'Telegram', detail: 'user message and bot reply', re: /\b(telegram|bot|intake|reply|message)\b/},
            {id: 'obsidian', label: 'Obsidian', detail: 'memory, status, project notes', re: /\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|claude\.md)\b/},
            {id: 'github', label: 'GitHub', detail: 'commits, push, issues, source control', re: /\b(github|git push|commit|pull request|pr\b|issue)\b/},
            {id: 'repo', label: 'Repo', detail: 'local code checkout', re: /\b(repo|code|fix|patch|script|python|javascript|css|html)\b/},
            {id: 'tests', label: 'Tests', detail: 'unit tests, smoke checks, compile', re: /\b(pytest|unittest|test|smoke|compileall|validation|node --check)\b/},
            {id: 'macmini', label: 'Mac Mini', detail: 'production runtime and launchd', re: /\b(mac mini|macmini|launchd|deploy|restart|service|runtime)\b/},
            {id: 'linear', label: 'Linear', detail: 'project/task tracking', re: /\b(linear|issue|dashboard)\b/},
        ];
        const tools = rules.filter((rule) => rule.re.test(text));
        if (tools.length) return tools;
        return [{id: 'bridge', label: 'Bridge', detail: 'task queue and agent messages'}];
    }

    function failureReason(task) {
        const structuredReason = firstMetadataValue(task, ['blocked_reason', 'failure_reason']);
        if (structuredReason) return compact(structuredReason, 260);
        const candidates = [
            task.error,
            task.result,
            ...(task.messages || []).map((message) => message.body),
        ].map(asText).filter(Boolean);
        const important = /(authentication_error|permission denied|fatal:|traceback|exception|failed|error:|exit code [1-9]|mmap failed|resource deadlock|blocked)/i;
        const found = candidates
            .flatMap((text) => text.split(/\n+/))
            .map((line) => line.trim())
            .find((line) => important.test(line));
        if (!found) return '';
        if (/authentication_error/i.test(found)) return 'authentication_error: credentials are invalid, expired, or unavailable.';
        if (/permission denied/i.test(found)) return 'Permission denied: the agent could not access the required GitHub/repo resource.';
        if (/mmap failed|resource deadlock/i.test(found)) return 'Git operation hit a resource/deadlock problem; retry or serialize git sync.';
        return compact(found, 260);
    }

    function buildCausalModel(task) {
        const agent = deriveAgent(task);
        const state = normalizedState(task);
        const tools = inferTools(task);
        const failure = failureReason(task);
        const meta = readMetadata(task);
        const trigger = firstMetadataValue(task, ['triggered_by']) || 'User';
        const entrypoint = firstMetadataValue(task, ['entrypoint']) || 'parses request and decides whether to route, remember, answer, or code';
        const nodes = [
            {label: trigger === 'telegram' ? 'User / Telegram' : compact(trigger, 42), detail: compact(taskTitle(task), 84), tone: 'user'},
            {label: 'JARVIS', detail: compact(entrypoint, 96), tone: 'core'},
            {label: 'Bridge queue', detail: compact(task.id || 'task dispatch', 84), tone: 'bridge'},
            {label: AGENT_LABELS[agent] || agent, detail: compact(agentReason(task, agent), 96), tone: 'agent'},
            {label: tools.map((tool) => tool.label).join(' + '), detail: tools.map((tool) => tool.detail).join(' / '), tone: 'tool'},
            {label: state === 'failed' ? 'Failed' : state === 'blocked' ? 'Blocked' : state === 'done' ? 'Done' : state === 'running' ? 'Running' : 'Pending', detail: failure || compact(task.result || task.error || 'waiting for next event', 96), tone: state},
        ];
        return {agent, state, tools, failure, nodes, meta};
    }

    function timelineEvents(task) {
        const events = [];
        if (task.created_at) {
            events.push({
                time: task.created_at,
                actor: 'Bridge',
                title: 'Task created',
                body: taskTitle(task),
            });
        }
        (task.messages || []).slice(-10).forEach((message) => {
            const meta = readMetadata(message);
            const detail = meta.blocked_reason || meta.route_reason || meta.status || meta.event || message.body || '';
            events.push({
                time: message.created_at,
                actor: `${message.sender || '?'} -> ${message.receiver || '?'}`,
                title: meta.event || message.type || 'message',
                body: compact(detail === meta.event ? message.body || '' : detail, 280),
            });
        });
        const failure = failureReason(task);
        if (failure || task.result || task.error) {
            events.push({
                time: task.updated_at || task.created_at,
                actor: 'Result',
                title: normalizedState(task),
                body: failure || compact(task.result || task.error, 280),
            });
        } else if (task.updated_at && task.updated_at !== task.created_at) {
            events.push({
                time: task.updated_at,
                actor: 'Bridge',
                title: 'Last update',
                body: normalizedState(task),
            });
        }
        return events;
    }

    function renderCausalView(task) {
        if (!selectedTaskEl || !causalSummaryEl || !causalGraphEl || !causalReasonsEl || !causalTimelineEl) return;
        if (!task) {
            selectedTaskEl.textContent = 'No task selected';
            causalSummaryEl.textContent = 'Waiting for Bridge data';
            causalGraphEl.innerHTML = '<div class="workshop-empty">No recent Bridge tasks.</div>';
            causalReasonsEl.innerHTML = '<div class="workshop-empty">No decision data yet.</div>';
            causalTimelineEl.innerHTML = '<div class="workshop-empty">No messages yet.</div>';
            return;
        }

        const model = buildCausalModel(task);
        const messageCount = (task.messages || []).length;
        selectedTaskEl.textContent = taskTitle(task);
        causalSummaryEl.textContent = `${model.state} · ${AGENT_LABELS[model.agent] || model.agent} · ${messageCount} messages · ${shortTime(task.updated_at || task.created_at)}`;
        causalGraphEl.innerHTML = model.nodes.map((node, idx) => `
            <div class="workshop-flow-step workshop-flow-${esc(node.tone)}">
                <div class="workshop-flow-node">
                    <strong>${esc(node.label)}</strong>
                    <span>${esc(node.detail)}</span>
                </div>
                ${idx < model.nodes.length - 1 ? '<div class="workshop-flow-edge"><span>triggers</span></div>' : ''}
            </div>
        `).join('');

        const reasons = [
            agentReason(task, model.agent),
            `Tools inferred: ${model.tools.map((tool) => `${tool.label} (${tool.detail})`).join(', ')}.`,
            `State normalized from Bridge status/result as ${model.state}.`,
        ];
        if (model.meta.entrypoint) reasons.unshift(`Entrypoint: ${model.meta.entrypoint}.`);
        if (Array.isArray(model.meta.calls) && model.meta.calls.length) {
            reasons.push(`Calls planned: ${model.meta.calls.join(' -> ')}.`);
        }
        if (model.failure) reasons.push(`Blocker: ${model.failure}`);
        causalReasonsEl.innerHTML = reasons.map((reason) => `<div class="workshop-reason">${esc(reason)}</div>`).join('');

        const events = timelineEvents(task);
        causalTimelineEl.innerHTML = events.length ? events.map((event) => `
            <div class="workshop-time-event">
                <div class="workshop-time-meta">
                    <span>${esc(shortTime(event.time))}</span>
                    <strong>${esc(event.actor)}</strong>
                    <em>${esc(event.title)}</em>
                </div>
                <p>${esc(event.body || '-')}</p>
            </div>
        `).join('') : '<div class="workshop-empty">No messages yet.</div>';
    }

    function markSelectedTask() {
        document.querySelectorAll('[data-task-id]').forEach((el) => {
            el.classList.toggle('is-selected', String(el.dataset.taskId) === String(selectedTaskId));
        });
    }

    function updateCounters(tasks) {
        const counts = {running: 0, pending: 0, blocked: 0, done: 0};
        tasks.forEach((task) => {
            const state = normalizedState(task);
            if (state === 'failed' || state === 'blocked') counts.blocked += 1;
            else if (state === 'done') counts.done += 1;
            else if (state === 'running') counts.running += 1;
            else if (state === 'pending') counts.pending += 1;
        });
        Object.entries(counts).forEach(([key, value]) => {
            const el = document.getElementById(`workshop-count-${key}`);
            if (el) el.textContent = value;
        });
    }

    function updateAgents(tasks) {
        const byAgent = {};
        document.querySelectorAll('[data-workshop-agent]').forEach((el) => {
            const id = el.dataset.workshopAgent;
            byAgent[id] = {el, states: [], count: 0};
            el.classList.remove('is-running', 'is-pending', 'is-done', 'is-blocked', 'is-failed', 'is-active');
        });

        tasks.forEach((task) => {
            const agent = deriveAgent(task);
            if (!byAgent[agent]) return;
            byAgent[agent].states.push(normalizedState(task));
            byAgent[agent].count += 1;
        });

        Object.entries(byAgent).forEach(([agent, entry]) => {
            const stateEl = entry.el.querySelector('.workshop-agent-state');
            if (!entry.count) {
                if (stateEl) stateEl.textContent = 'idle';
                return;
            }
            const states = entry.states;
            let state = 'pending';
            if (states.some((s) => s === 'running')) state = 'running';
            else if (states.some((s) => s === 'blocked' || s === 'failed')) state = 'blocked';
            else if (states.some((s) => s === 'pending')) state = 'pending';
            else if (states.every((s) => s === 'done' || s === 'cancelled')) state = 'done';
            entry.el.classList.add('is-active', `is-${state}`);
            if (stateEl) stateEl.textContent = `${state} · ${entry.count}`;
        });
    }

    function renderMarkers(tasks) {
        const visible = tasks.slice(0, 18);
        markersEl.innerHTML = visible.map((task, idx) => {
            const agent = deriveAgent(task);
            const pos = AGENT_POSITIONS[agent] || AGENT_POSITIONS.BUILDER;
            const state = normalizedState(task);
            const selected = String(taskId(task)) === String(selectedTaskId) ? ' is-selected' : '';
            const dx = ((idx % 3) - 1) * 3.2;
            const dy = (Math.floor(idx / 3) % 3) * 5.5;
            return `
                <button class="workshop-marker workshop-marker-${state}${selected}" data-task-id="${esc(task.id)}"
                    style="left:${pos.x + dx}%;top:${pos.y + 12 + dy}%"
                    title="${esc(taskTitle(task))}">
                    <span>${esc(agent.slice(0, 2))}</span>
                </button>`;
        }).join('');
    }

    function renderTaskList(tasks) {
        if (!tasks.length) {
            taskList.innerHTML = '<div class="workshop-empty">No recent Bridge tasks.</div>';
            return;
        }
        taskList.innerHTML = tasks.slice(0, 12).map((task) => {
            const state = normalizedState(task);
            const agent = deriveAgent(task);
            const messageCount = (task.messages || []).length;
            const selected = String(taskId(task)) === String(selectedTaskId) ? ' is-selected' : '';
            return `
                <button class="workshop-task workshop-task-${state}${selected}" data-task-id="${esc(task.id)}">
                    <span class="workshop-task-top">
                        <code>${esc(String(task.id || '').slice(0, 12))}</code>
                        <em>${esc(AGENT_LABELS[agent] || agent)}</em>
                        <strong>${esc(state)}</strong>
                    </span>
                    <span class="workshop-task-title">${esc(taskTitle(task))}</span>
                    <span class="workshop-task-meta">${esc(shortTime(task.updated_at || task.created_at))} · ${messageCount} messages</span>
                </button>`;
        }).join('');
    }

    function messageTimeline(task) {
        const messages = (task.messages || []).slice(-12);
        if (!messages.length) return '<div class="workshop-empty">No Bridge messages yet.</div>';
        return messages.map((message) => `
            <div class="workshop-trace-msg">
                <div class="workshop-trace-meta">
                    <span>${esc(shortTime(message.created_at))}</span>
                    <strong>${esc(message.sender || '?')} -> ${esc(message.receiver || '?')}</strong>
                    <em>${esc(message.type || 'message')}</em>
                </div>
                <div class="workshop-trace-body">${esc(message.body || '').slice(0, 2000)}</div>
            </div>
        `).join('');
    }

    function openTask(taskId) {
        const task = latestTasks.find((item) => String(item.id) === String(taskId));
        if (!task || !drawer || !drawerContent) return;
        selectedTaskId = String(task.id || '');
        renderCausalView(task);
        markSelectedTask();
        const state = normalizedState(task);
        const agent = deriveAgent(task);
        drawerContent.innerHTML = `
            <div class="workshop-drawer-head">
                <div>
                    <span class="workshop-side-kicker">${esc(AGENT_LABELS[agent] || agent)} trace</span>
                    <h3>${esc(taskTitle(task))}</h3>
                </div>
                <span class="workshop-drawer-state workshop-task-${state}">${esc(state)}</span>
            </div>
            <div class="workshop-drawer-grid">
                <div><span>Task</span><strong>${esc(task.id || '-')}</strong></div>
                <div><span>Role</span><strong>${esc(task.agent_role || 'AUTO')}</strong></div>
                <div><span>Created</span><strong>${esc(shortTime(task.created_at))}</strong></div>
                <div><span>Updated</span><strong>${esc(shortTime(task.updated_at))}</strong></div>
            </div>
            <div class="workshop-trace">${messageTimeline(task)}</div>
        `;
        drawer.classList.remove('hidden');
    }

    function bindTaskClicks() {
        document.querySelectorAll('[data-task-id]').forEach((el) => {
            el.addEventListener('click', () => openTask(el.dataset.taskId));
        });
    }

    async function refreshWorkshop() {
        if (statusEl) statusEl.textContent = 'loading';
        try {
            const res = await fetch('/api/bridge/tasks?limit=40&include_messages=1', {cache: 'no-store'});
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            latestTasks = data.tasks || [];
            if (!latestTasks.some((task) => String(task.id || '') === String(selectedTaskId))) {
                selectedTaskId = latestTasks.length ? String(latestTasks[0].id || '') : null;
            }
            updateCounters(latestTasks);
            updateAgents(latestTasks);
            renderMarkers(latestTasks);
            renderTaskList(latestTasks);
            bindTaskClicks();
            renderCausalView(latestTasks.find((task) => String(task.id || '') === String(selectedTaskId)));
            markSelectedTask();
            if (statusEl) statusEl.textContent = `${latestTasks.length} tasks`;
        } catch (err) {
            latestTasks = [];
            selectedTaskId = null;
            updateCounters([]);
            updateAgents([]);
            markersEl.innerHTML = '';
            taskList.innerHTML = `<div class="workshop-empty">Bridge unavailable: ${esc(err.message)}</div>`;
            renderCausalView(null);
            if (statusEl) statusEl.textContent = 'offline';
        }
    }

    document.querySelectorAll('[data-workshop-agent]').forEach((el) => {
        el.addEventListener('click', () => {
            const agent = el.dataset.workshopAgent;
            const task = latestTasks.find((item) => deriveAgent(item) === agent);
            if (task) openTask(task.id);
        });
    });
    if (refreshBtn) refreshBtn.addEventListener('click', refreshWorkshop);
    if (drawerClose) drawerClose.addEventListener('click', () => drawer.classList.add('hidden'));
    if (drawer) drawer.addEventListener('click', (event) => {
        if (event.target === drawer) drawer.classList.add('hidden');
    });

    window.AgentWorkshopRefresh = refreshWorkshop;
    refreshWorkshop();
    setInterval(refreshWorkshop, 5000);
})();

// ══════════════════════════════════════════════════════════════
// ── Phase 1: Cmd+K Command Palette ──
// ══════════════════════════════════════════════════════════════
(function initCommandPalette() {
    // Build palette data
    const commands = [];

    // Navigation commands
    document.querySelectorAll('.sidebar-nav a[data-target]').forEach(a => {
        const label = a.textContent.trim().replace(/\d+$/, '').trim();
        commands.push({
            label: `Go to ${label}`,
            category: 'nav',
            action: () => { a.click(); }
        });
    });

    // Agent commands
    document.querySelectorAll('.ag').forEach(el => {
        const id = el.querySelector('.ag-id')?.textContent?.trim();
        if (id) {
            commands.push({
                label: `Agent: ${id}`,
                category: 'agent',
                action: () => { el.scrollIntoView({behavior:'smooth'}); el.classList.add('ag-highlight'); setTimeout(()=>el.classList.remove('ag-highlight'),2000); }
            });
        }
    });

    // Project commands
    document.querySelectorAll('#projects tbody tr').forEach(tr => {
        const name = tr.querySelector('.proj-name')?.textContent?.trim();
        if (name) {
            commands.push({
                label: `Project: ${name}`,
                category: 'project',
                action: () => { tr.scrollIntoView({behavior:'smooth'}); tr.classList.add('row-highlight'); setTimeout(()=>tr.classList.remove('row-highlight'),2000); }
            });
        }
    });

    // Focus commands from projects
    document.querySelectorAll('#projects tbody tr').forEach(tr => {
        const name = tr.querySelector('.proj-name')?.textContent?.trim();
        if (name) {
            commands.push({
                label: `Focus: ${name}`,
                category: 'focus',
                action: () => { location.href = `${location.pathname}?focus=${encodeURIComponent(name)}`; }
            });
        }
    });

    // Action commands
    commands.push({
        label: 'Rebuild Dashboard',
        category: 'action',
        action: () => postLocal('/api/rebuild').then(ok => {
            if (ok) showToast('Rebuild triggered');
            else showToast('Local API offline', 'warn');
        })
    });
    commands.push({
        label: 'Launch Agents',
        category: 'action',
        action: () => { document.getElementById('launchBtn')?.click(); }
    });
    commands.push({
        label: 'Refresh Page',
        category: 'action',
        action: () => location.reload()
    });
    commands.push({
        label: 'Clear Focus',
        category: 'action',
        action: () => { location.href = location.pathname; }
    });

    // Create palette DOM
    const palette = document.createElement('div');
    palette.className = 'cmd-palette hidden';
    palette.innerHTML = `
        <div class="cmd-backdrop"></div>
        <div class="cmd-dialog">
            <input class="cmd-input" type="text" placeholder="Search commands, agents, projects..." autofocus>
            <div class="cmd-results"></div>
            <div class="cmd-footer">
                <span class="cmd-hint">↑↓ navigate</span>
                <span class="cmd-hint">↵ select</span>
                <span class="cmd-hint">esc close</span>
            </div>
        </div>
    `;
    document.body.appendChild(palette);

    const input = palette.querySelector('.cmd-input');
    const results = palette.querySelector('.cmd-results');
    const backdrop = palette.querySelector('.cmd-backdrop');
    let selectedIdx = 0;
    let filtered = [];

    function render(query) {
        filtered = query
            ? commands.filter(c => c.label.toLowerCase().includes(query.toLowerCase()))
            : commands.slice(0, 10);
        selectedIdx = 0;
        results.innerHTML = filtered.map((c, i) => `
            <div class="cmd-item ${i===0?'cmd-selected':''}" data-idx="${i}">
                <span class="cmd-cat">${c.category}</span>
                <span class="cmd-label">${c.label}</span>
            </div>
        `).join('') || '<div class="cmd-empty">No results</div>';
    }

    function updateSelection() {
        results.querySelectorAll('.cmd-item').forEach((el, i) => {
            el.classList.toggle('cmd-selected', i === selectedIdx);
        });
        results.querySelector('.cmd-selected')?.scrollIntoView({block:'nearest'});
    }

    function execute() {
        if (filtered[selectedIdx]) {
            close();
            filtered[selectedIdx].action();
        }
    }

    function open() {
        palette.classList.remove('hidden');
        input.value = '';
        render('');
        setTimeout(() => input.focus(), 50);
    }

    function close() {
        palette.classList.add('hidden');
    }

    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); selectedIdx = Math.min(selectedIdx+1, filtered.length-1); updateSelection(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); selectedIdx = Math.max(selectedIdx-1, 0); updateSelection(); }
        else if (e.key === 'Enter') { e.preventDefault(); execute(); }
        else if (e.key === 'Escape') { close(); }
    });
    results.addEventListener('click', (e) => {
        const item = e.target.closest('.cmd-item');
        if (item) { selectedIdx = parseInt(item.dataset.idx); execute(); }
    });
    backdrop.addEventListener('click', close);

    // Global shortcut: Cmd+K or Ctrl+K
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            palette.classList.contains('hidden') ? open() : close();
        }
    });

    // Expose for keyboard shortcut
    window._cmdPalette = { open, close };
})();

// ══════════════════════════════════════════════════════════════
// ── Phase 1: Keyboard Shortcuts ──
// ══════════════════════════════════════════════════════════════
(function initKeyboardShortcuts() {
    const navLinks = document.querySelectorAll('.sidebar-nav a[data-target]');
    const navArray = Array.from(navLinks);

    document.addEventListener('keydown', (e) => {
        // Skip if in input/textarea or palette open
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;

        // 1-8 for sections
        const num = parseInt(e.key);
        if (num >= 1 && num <= navArray.length) {
            e.preventDefault();
            navArray[num - 1].click();
            return;
        }

        switch(e.key) {
            case 'r':
                e.preventDefault();
                location.reload();
                break;
            case '/':
                e.preventDefault();
                if (window._cmdPalette) window._cmdPalette.open();
                break;
            case '?':
                showToast('Shortcuts: 1-8 sections, / search, r refresh, ? help');
                break;
        }
    });
})();

// ══════════════════════════════════════════════════════════════
// ── Phase 2: Focus Mode ──
// ══════════════════════════════════════════════════════════════
(function initFocusMode() {
    const params = new URLSearchParams(location.search);
    const focus = params.get('focus');
    if (!focus) return;

    const focusLower = focus.toLowerCase();

    // Show focus indicator
    const indicator = document.createElement('div');
    indicator.className = 'focus-indicator';
    indicator.innerHTML = `<span class="focus-label">Focus: <strong>${focus}</strong></span><a class="focus-clear" href="${location.pathname}">× Clear</a>`;
    document.querySelector('.main')?.prepend(indicator);

    // Filter project rows — hide non-matching
    document.querySelectorAll('#projects tbody tr, #done tbody tr').forEach(tr => {
        const name = tr.querySelector('.proj-name')?.textContent?.trim().toLowerCase() || '';
        if (!name.includes(focusLower)) {
            tr.style.display = 'none';
        }
    });

    // Filter agent cards — dim non-matching
    document.querySelectorAll('.ag').forEach(el => {
        const badges = el.querySelector('.ag-badges')?.textContent?.toLowerCase() || '';
        const id = el.querySelector('.ag-id')?.textContent?.toLowerCase() || '';
        if (!badges.includes(focusLower) && !id.includes(focusLower)) {
            el.style.opacity = '0.3';
            el.style.pointerEvents = 'none';
        }
    });
})();

// ══════════════════════════════════════════════════════════════
// ── Toast notification helper ──
// ══════════════════════════════════════════════════════════════
function showToast(msg, type) {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'warn' ? 'toast-warn' : 'toast-info'}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('toast-out'); setTimeout(() => toast.remove(), 300); }, 3000);
}

// ══════════════════════════════════════════════════════════════
// ── Existing functionality ──
// ══════════════════════════════════════════════════════════════

function setOrchMeta(text) {
    const metaEl = document.querySelector('.orch-meta');
    if (metaEl) metaEl.textContent = text;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

async function postLocal(path, data) {
    try {
        const res = await fetch(`${LOCAL_API}${path}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data || {})
        });
        if (!res.ok) return false;
        return true;
    } catch (e) {
        return false;
    }
}

async function refreshLocalServices() {
    const summaryEl = document.getElementById('local-services-summary');
    const listEl = document.getElementById('local-services-list');
    if (!summaryEl || !listEl) return;
    try {
        const res = await fetch(`${LOCAL_API}/api/local-services?ts=${Date.now()}`, {cache: 'no-store'});
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        summaryEl.textContent = `${data.enabled_count}/${data.launchd_total} launchd enabled · ${data.running_count}/${data.total} running`;
        const rows = (data.items || []).map(item => {
            const dotCls = item.running
                ? 'live-health-ok'
                : (item.status === 'disabled' ? 'live-health-off' : 'live-health-warn');
            const enabledLabel = item.enabled === null
                ? item.status
                : (item.enabled ? 'enabled' : 'disabled');
            const meta = [enabledLabel, item.kind, item.detail].filter(Boolean).join(' · ');
            return `<div class="live-svc"><span class="live-dot-sm ${dotCls}"></span><span class="live-svc-name">${escapeHtml(item.name)}</span><span class="live-svc-age">${escapeHtml(meta)}</span></div>`;
        }).join('');
        listEl.innerHTML = rows || '<div class="live-empty">No local services configured</div>';
    } catch (e) {
        summaryEl.textContent = 'Local API unavailable';
        listEl.innerHTML = '<div class="live-empty">Open the dashboard on this Mac while `dashboard-server.py` is running to see local service state.</div>';
    }
}

async function ensureGithubToken(allowPrompt) {
    if (!allowPrompt) return false;
    try {
        const statusRes = await fetch(`${LOCAL_API}/api/github/token`);
        if (statusRes.ok) {
            const status = await statusRes.json();
            if (status && status.has_token) return true;
        }
    } catch (e) {}
    const token = prompt('GitHub PAT (stored on local dashboard server only):');
    if (!token) return false;
    try {
        const saveRes = await fetch(`${LOCAL_API}/api/github/token`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token})
        });
        return saveRes.ok;
    } catch (e) {
        return false;
    }
}

document.querySelectorAll('.oslider-item:not(.agent-model-item)').forEach(el => {
    el.style.cursor = 'pointer';
    el.addEventListener('click', async function(e) {
        e.preventDefault(); e.stopPropagation();
        const modeMap = {'CC':'claude-claude','CX':'claude-codex','XX':'codex-codex'};
        const mode = modeMap[this.textContent.trim()];
        if (!mode) return;
        this.closest('.oslider').querySelectorAll('.oslider-item').forEach(s => s.classList.remove('oslider-active'));
        this.classList.add('oslider-active');
        const descMap = {'claude-claude':'Claude + Claude','claude-codex':'Claude + Codex','codex-codex':'Codex + Codex'};
        const descEl = document.querySelector('.orch-desc');
        if (descEl) descEl.textContent = descMap[mode] || mode;
        setOrchMeta('Applying mode...');
        const localOk = await postLocal('/api/mode', {mode});
        let ghOk = false;
        if (localOk) {
            ghOk = await ghCommit(
                GH_MODE_PATH,
                {mode, ts: new Date().toISOString(), source: 'dashboard'},
                `mode: ${mode}`,
                {allowPrompt: false}
            );
            setOrchMeta(ghOk ? 'Applied locally + synced to GitHub' : 'Applied locally (cloud sync pending)');
        } else {
            setOrchMeta('Local API offline; queueing via GitHub...');
            ghOk = await ghCommit(
                GH_MODE_PATH,
                {mode, ts: new Date().toISOString(), source: 'dashboard'},
                `mode: ${mode}`,
                {allowPrompt: true}
            );
            if (ghOk) setOrchMeta('Queued — applies on next rebuild (~5 min)');
        }
        const ok = localOk || ghOk;
        if (ok) {
            return;
        } else {
            setOrchMeta('Mode switch failed (local + GitHub).');
            location.reload();
        }
    });
});

// ── Orchestrator ON/OFF toggle — GitHub API + local apply ──
const orchToggleInput = document.getElementById('orchToggleInput');
if (orchToggleInput) orchToggleInput.addEventListener('change', async function() {
    const cb = this;
    const on = cb.checked;
    const grid = document.querySelector('.orch-grid');
    const status = document.querySelector('.orch-master-status');
    status.textContent = on ? 'STARTING...' : 'STOPPING...';
    status.className = 'orch-master-status';

    const localOk = await postLocal('/api/orchestrator/toggle', {active: on});
    const ghOk = await ghCommit(
        'pause-request.json',
        {paused: !on, ts: new Date().toISOString(), source: 'dashboard'},
        `orchestrator: ${on ? 'resume' : 'pause'}`,
        {allowPrompt: !localOk}
    );
    const applied = localOk || ghOk;

    // 3. Update UI
    if (on) {
        grid.classList.remove('orch-disabled');
        status.textContent = localOk ? 'RUNNING (local)' : (ghOk ? 'RUNNING (queued)' : 'RUNNING (failed)');
        status.className = 'orch-master-status orch-status-on';
    } else {
        grid.classList.add('orch-disabled');
        status.textContent = localOk ? 'PAUSED (local)' : (ghOk ? 'PAUSED (queued)' : 'PAUSED (failed)');
        status.className = 'orch-master-status orch-status-off';
    }
    if (!applied) {
        // Revert checkbox if neither method worked
        cb.checked = !on;
        status.textContent = on ? 'PAUSED' : 'RUNNING';
        status.className = on ? 'orch-master-status orch-status-off' : 'orch-master-status orch-status-on';
        grid.classList.toggle('orch-disabled', on);
        alert('Could not toggle orchestrator. Check GitHub token or localhost server.');
    }
});

// ── Launch Agents ──
async function ghCommit(path, data, msg, options) {
    const opts = options || {};
    const allowPrompt = opts.allowPrompt !== false;
    const hasToken = await ensureGithubToken(allowPrompt);
    if (!hasToken) return false;
    try {
        const res = await fetch(`${LOCAL_API}/api/github/commit`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path, message: msg, data})
        });
        if (res.ok) return true;
        if (res.status === 401 && allowPrompt) {
            await fetch(`${LOCAL_API}/api/github/token`, {method: 'DELETE'});
            const refreshed = await ensureGithubToken(true);
            if (!refreshed) return false;
            const retry = await fetch(`${LOCAL_API}/api/github/commit`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path, message: msg, data})
            });
            return retry.ok;
        }
    } catch (e) {}
    return false;
}

async function launchAgents() {
    const btn = document.getElementById('launchBtn');
    if (!btn) return;
    btn.textContent = 'Launching...';
    btn.classList.add('running');
    const localOk = await postLocal('/api/orchestrator/run', {source:'dashboard'});
    const ghOk = await ghCommit(
        'run-request.json',
        {action:'run', ts: new Date().toISOString(), source:'dashboard'},
        'run: launch agents',
        {allowPrompt: !localOk}
    );
    if (localOk || ghOk) {
        btn.textContent = localOk ? 'Launched now (local)' : 'Queued — starts on next cycle (~5 min)';
        setTimeout(() => { btn.textContent = 'Launch Agents'; btn.classList.remove('running'); }, 5000);
    } else {
        btn.textContent = 'Launch Agents';
        btn.classList.remove('running');
    }
}

// ── Per-agent model switcher ──
document.querySelectorAll('.agent-model-item').forEach(el => {
    el.addEventListener('click', async function(e) {
        e.preventDefault(); e.stopPropagation();
        const agent = this.dataset.agent;
        const model = this.dataset.model;
        if (!agent || !model) return;
        // Update UI: only within same agent's slider
        this.closest('.agent-model-slider').querySelectorAll('.oslider-item').forEach(s => s.classList.remove('oslider-active'));
        this.classList.add('oslider-active');
        const label = this.closest('.agent-model-card').querySelector('.agent-model-current');
        if (label) label.textContent = model;
        const localOk = await postLocal('/api/model', {agent, model});
        const ghOk = await ghCommit(
            'model-request.json',
            {agent, model, ts: new Date().toISOString(), source: 'dashboard'},
            `model: ${agent}=${model}`,
            {allowPrompt: !localOk}
        );
        if (localOk || ghOk) {
            if (label) label.textContent = localOk ? (model + ' (applied)') : (model + ' (queued)');
        } else {
            // Rollback UI
            if (label) label.textContent = 'error — reload';
            setTimeout(() => location.reload(), 2000);
        }
    });
});
refreshLocalServices();
setInterval(refreshLocalServices, 15000);

// ══════════════════════════════════════════════════════════════
// ── Atlas: Hygiene Timer ──
// ══════════════════════════════════════════════════════════════
(function initHygieneTimer() {
    function update() {
        var el = document.getElementById('hygiene-timer');
        if (!el) return;
        var now = new Date();
        var utcMs = now.getTime() + now.getTimezoneOffset() * 60000;
        var klNow = new Date(utcMs + 8 * 3600000);
        var next = new Date(klNow);
        next.setHours(9, 0, 0, 0);
        if (klNow.getHours() >= 9) next.setDate(next.getDate() + 1);
        var diffMs = next.getTime() - klNow.getTime();
        var hours = Math.floor(diffMs / 3600000);
        var mins = Math.floor((diffMs % 3600000) / 60000);
        if (hours === 0 && mins <= 5) {
            el.innerHTML = '<span class="timer-active">Running now...</span>';
        } else {
            el.textContent = hours + 'h ' + mins + 'm';
        }
    }
    update();
    setInterval(update, 60000);
})();

// ══════════════════════════════════════════════════════════════
// ── Agent Theater: animated human-facing task flow ──
// ══════════════════════════════════════════════════════════════
(function initAgentTheater() {
    const stage = document.getElementById('theater-stage');
    const runnersEl = document.getElementById('theater-runners');
    const statusEl = document.getElementById('theater-status');
    const currentTitleEl = document.getElementById('theater-current-title');
    const currentEl = document.getElementById('theater-current');
    const storyEl = document.getElementById('theater-story');
    const storyCountEl = document.getElementById('theater-story-count');
    const refreshBtn = document.getElementById('theater-refresh');
    if (!stage || !runnersEl || !currentEl || !storyEl) return;

    const STATIONS = {
        USER: {x: 12, y: 55},
        JARVIS: {x: 28, y: 34},
        BRIDGE: {x: 44, y: 50},
        ROUTER: {x: 28, y: 34},
        PLANNER: {x: 44, y: 50},
        BUILDER: {x: 63, y: 32},
        TESTER: {x: 77, y: 48},
        DEPLOYER: {x: 86, y: 69},
        VAULT: {x: 52, y: 72},
        GITHUB: {x: 24, y: 76},
    };
    const LABELS = {
        USER: 'You',
        JARVIS: 'Jarvis',
        BRIDGE: 'Bridge',
        ROUTER: 'Router',
        PLANNER: 'Planner',
        BUILDER: 'Builder',
        TESTER: 'Tester',
        DEPLOYER: 'Deployer',
        VAULT: 'Vault',
        GITHUB: 'GitHub',
    };
    const ROUTES = {
        ROUTER: ['USER', 'JARVIS', 'BRIDGE', 'JARVIS'],
        PLANNER: ['USER', 'JARVIS', 'BRIDGE', 'PLANNER'],
        BUILDER: ['USER', 'JARVIS', 'BRIDGE', 'BUILDER'],
        TESTER: ['USER', 'JARVIS', 'BRIDGE', 'BUILDER', 'TESTER'],
        DEPLOYER: ['USER', 'JARVIS', 'BRIDGE', 'BUILDER', 'TESTER', 'DEPLOYER'],
        VAULT: ['USER', 'JARVIS', 'BRIDGE', 'VAULT'],
        GITHUB: ['USER', 'JARVIS', 'BRIDGE', 'BUILDER', 'GITHUB'],
    };
    let theaterTasks = [];
    let theaterSelectedId = null;
    let theaterAnimationStarted = false;

    const escTheater = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));

    function theaterText(value) {
        if (value == null) return '';
        if (typeof value === 'string') return value;
        try { return JSON.stringify(value); } catch (_) { return String(value); }
    }

    function theaterCompact(value, limit = 120) {
        const text = theaterText(value).replace(/\s+/g, ' ').trim();
        return text.length > limit ? text.slice(0, limit - 3).trim() + '...' : text;
    }

    function theaterTime(raw) {
        if (!raw) return '';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return String(raw).slice(0, 16);
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    function theaterMeta(item) {
        const raw = item?.metadata ?? item?.meta ?? null;
        if (!raw) return {};
        if (typeof raw === 'object') return raw;
        try {
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_) {
            return {};
        }
    }

    function theaterAllMeta(task) {
        return [theaterMeta(task), ...(task.messages || []).map(theaterMeta)];
    }

    function theaterFirstMeta(task, keys) {
        for (const meta of theaterAllMeta(task)) {
            for (const key of keys) {
                if (meta[key] != null && meta[key] !== '') return meta[key];
            }
        }
        return '';
    }

    function theaterState(task) {
        const raw = String(task.status || task.state || '').toLowerCase();
        const result = `${task.error || ''} ${theaterText(task.result)}`.toLowerCase();
        if (result.match(/\b(authentication_error|failed|traceback|exception|exit code [1-9]|permission denied|fatal:|error: 4\d\d|error: 5\d\d)\b/)) return 'failed';
        if (['done', 'complete', 'completed', 'success', 'succeeded'].includes(raw)) return 'done';
        if (['failed', 'error'].includes(raw)) return 'failed';
        if (['blocked', 'waiting', 'needs_input'].includes(raw)) return 'blocked';
        if (['cancelled', 'canceled'].includes(raw)) return 'cancelled';
        if (['running', 'in_progress', 'working', 'active'].includes(raw)) return 'running';
        return 'pending';
    }

    function theaterTaskText(task) {
        const messages = (task.messages || []).map((m) => `${m.sender} ${m.receiver} ${m.type} ${m.body}`).join(' ');
        const meta = theaterAllMeta(task).map(theaterText).join(' ');
        return `${task.description || ''} ${task.agent_role || ''} ${task.error || ''} ${theaterText(task.result)} ${messages} ${meta}`.toLowerCase();
    }

    function theaterAgent(task) {
        const explicit = String(theaterFirstMeta(task, ['assigned_agent']) || task.agent_role || '').toUpperCase().replace(/[^A-Z_]/g, '');
        if (LABELS[explicit]) return explicit;
        const text = theaterTaskText(task);
        if (text.match(/\b(pytest|test|selftest|smoke|compileall|validation)\b/)) return 'TESTER';
        if (text.match(/\b(deploy|launchd|restart|rollout|mac mini|macmini|service)\b/)) return 'DEPLOYER';
        if (text.match(/\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|source-aware)\b/)) return 'VAULT';
        if (text.match(/\b(github|git push|commit|pull request|pr\b|linear|issue)\b/)) return 'GITHUB';
        if (text.match(/\b(plan|scope|breakdown|handoff|acceptance)\b/)) return 'PLANNER';
        if (text.match(/\b(route|router|telegram intake|intent)\b/)) return 'ROUTER';
        return 'BUILDER';
    }

    function theaterTitle(task) {
        return theaterCompact(task?.description || task?.title || 'Untitled task', 116);
    }

    function theaterReason(task, agent) {
        const structured = theaterFirstMeta(task, ['route_reason', 'reason']);
        if (structured) return theaterCompact(structured, 190);
        const state = theaterState(task);
        if (state === 'failed' || state === 'blocked') {
            const text = [task.error, task.result, ...(task.messages || []).map((m) => m.body)]
                .map(theaterText).join('\n');
            const line = text.split(/\n+/).map((x) => x.trim()).find((x) => /(permission denied|fatal:|error|failed|blocked|traceback|exception|mmap)/i.test(x));
            if (line) return theaterCompact(line, 190);
        }
        return `${LABELS[agent] || agent} is handling this task from Bridge queue.`;
    }

    function theaterRoute(task) {
        const agent = theaterAgent(task);
        const text = theaterTaskText(task);
        let route = ROUTES[agent] || ROUTES.BUILDER;
        if (agent === 'BUILDER' && text.match(/\b(test|selftest|smoke|compileall)\b/)) route = ROUTES.TESTER;
        if (text.match(/\b(deploy|launchd|restart|mac mini|runtime)\b/)) route = ROUTES.DEPLOYER;
        if (text.match(/\b(obsidian|vault|memory|status\.md|todo\.md)\b/)) route = [...route, 'VAULT'];
        if (text.match(/\b(github|commit|push|issue|linear)\b/)) route = [...route, 'GITHUB'];
        return [...new Set(route)];
    }

    function theaterSeed(id) {
        return String(id || '').split('').reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 5000;
    }

    function routePoint(route, progress) {
        const points = route.map((name) => STATIONS[name] || STATIONS.BUILDER);
        if (points.length <= 1) return points[0] || STATIONS.BUILDER;
        const bounded = Math.max(0, Math.min(0.995, progress));
        const scaled = bounded * (points.length - 1);
        const index = Math.floor(scaled);
        const local = scaled - index;
        const a = points[index];
        const b = points[Math.min(index + 1, points.length - 1)];
        return {
            x: a.x + (b.x - a.x) * local,
            y: a.y + (b.y - a.y) * local,
        };
    }

    function progressForRunner(runner, now) {
        const state = runner.dataset.state;
        const seed = Number(runner.dataset.seed || 0);
        if (state === 'done' || state === 'cancelled') return 0.985;
        if (state === 'failed' || state === 'blocked') return 0.72;
        if (state === 'pending') return 0.16 + ((Math.sin((now + seed) / 900) + 1) * 0.025);
        const duration = 10500 + seed;
        return ((now + seed) % duration) / duration;
    }

    function animateTheater() {
        const now = Date.now();
        document.querySelectorAll('.theater-runner').forEach((runner) => {
            const route = String(runner.dataset.route || 'USER,JARVIS,BRIDGE,BUILDER').split(',');
            const point = routePoint(route, progressForRunner(runner, now));
            runner.style.left = `${point.x}%`;
            runner.style.top = `${point.y}%`;
            runner.style.transform = 'translate(-50%, -50%)';
        });
        requestAnimationFrame(animateTheater);
    }

    function updateTheaterPeople(tasks) {
        const personState = {};
        Object.keys(LABELS).forEach((agent) => { personState[agent] = []; });
        tasks.slice(0, 16).forEach((task) => {
            const state = theaterState(task);
            theaterRoute(task).forEach((agent) => {
                if (personState[agent]) personState[agent].push(state);
            });
        });
        document.querySelectorAll('[data-theater-agent]').forEach((el) => {
            const agent = el.dataset.theaterAgent;
            const states = personState[agent] || [];
            el.classList.remove('is-active', 'is-running', 'is-pending', 'is-done', 'is-blocked', 'is-failed');
            const label = el.querySelector('.theater-person-state');
            if (!states.length) {
                if (label) label.textContent = 'idle';
                return;
            }
            let state = 'pending';
            if (states.some((s) => s === 'running')) state = 'running';
            else if (states.some((s) => s === 'failed' || s === 'blocked')) state = 'blocked';
            else if (states.some((s) => s === 'pending')) state = 'pending';
            else if (states.every((s) => s === 'done' || s === 'cancelled')) state = 'done';
            el.classList.add('is-active', `is-${state}`);
            if (label) {
                const neutralAgents = ['USER', 'JARVIS', 'BRIDGE'];
                if (neutralAgents.includes(agent)) label.textContent = `${states.length} tasks`;
                else if (state === 'blocked') label.textContent = `check · ${states.length}`;
                else if (state === 'running') label.textContent = `moving · ${states.length}`;
                else label.textContent = `${state} · ${states.length}`;
            }
        });
    }

    function renderTheaterRunners(tasks) {
        const activeFirst = [...tasks].sort((a, b) => {
            const rank = {running: 0, pending: 1, failed: 2, blocked: 2, done: 3, cancelled: 4};
            return (rank[theaterState(a)] ?? 5) - (rank[theaterState(b)] ?? 5);
        });
        const visible = activeFirst.slice(0, 5);
        runnersEl.innerHTML = visible.map((task) => {
            const state = theaterState(task);
            const agent = theaterAgent(task);
            const route = theaterRoute(task).join(',');
            const id = String(task.id || '');
            return `
                <div class="theater-runner theater-runner-${escTheater(state)}" data-task-id="${escTheater(id)}"
                    data-route="${escTheater(route)}" data-state="${escTheater(state)}"
                    data-runner-agent="${escTheater(agent)}" data-seed="${theaterSeed(id)}">
                    <span class="theater-mini-person" aria-hidden="true"></span>
                    <span class="theater-runner-label">${escTheater(LABELS[agent] || agent)} · ${escTheater(state)}</span>
                </div>`;
        }).join('');
        if (!theaterAnimationStarted) {
            theaterAnimationStarted = true;
            requestAnimationFrame(animateTheater);
        }
    }

    function renderTheaterCurrent(task) {
        if (!task) {
            if (currentTitleEl) currentTitleEl.textContent = 'Waiting for Bridge';
            currentEl.innerHTML = '<div class="theater-empty">No recent Bridge task.</div>';
            return;
        }
        const state = theaterState(task);
        const agent = theaterAgent(task);
        const route = theaterRoute(task);
        const messageCount = (task.messages || []).length;
        if (currentTitleEl) currentTitleEl.textContent = theaterTitle(task);
        currentEl.innerHTML = `
            <div class="theater-current-grid">
                <div class="theater-current-item"><span>agent</span><strong>${escTheater(LABELS[agent] || agent)}</strong></div>
                <div class="theater-current-item"><span>state</span><strong>${escTheater(state)}</strong></div>
                <div class="theater-current-item"><span>route</span><strong>${escTheater(route.map((r) => LABELS[r] || r).join(' -> '))}</strong></div>
                <div class="theater-current-item"><span>events</span><strong>${messageCount} messages</strong></div>
            </div>
            <div class="theater-current-reason">${escTheater(theaterReason(task, agent))}</div>`;
    }

    function renderTheaterStory(task) {
        if (!task) {
            if (storyCountEl) storyCountEl.textContent = '0 events';
            storyEl.innerHTML = '<div class="theater-empty">No events yet.</div>';
            return;
        }
        const events = [];
        if (task.created_at) {
            events.push({time: task.created_at, state: 'pending', actor: 'Bridge', body: `Task created: ${theaterTitle(task)}`});
        }
        (task.messages || []).slice(-8).forEach((message) => {
            const meta = theaterMeta(message);
            events.push({
                time: message.created_at,
                state: theaterState(task),
                actor: meta.event || message.type || `${message.sender || '?'} -> ${message.receiver || '?'}`,
                body: theaterCompact(meta.route_reason || meta.blocked_reason || message.body || '', 180),
            });
        });
        if (task.result || task.error) {
            events.push({time: task.updated_at || task.created_at, state: theaterState(task), actor: 'Result', body: theaterCompact(task.error || task.result, 180)});
        }
        if (storyCountEl) storyCountEl.textContent = `${events.length} events`;
        storyEl.innerHTML = events.length ? events.map((event) => `
            <div class="theater-event theater-event-${escTheater(event.state)}">
                <div class="theater-event-top">
                    <strong>${escTheater(event.actor)}</strong>
                    <span>${escTheater(theaterTime(event.time))}</span>
                </div>
                <p>${escTheater(event.body || '-')}</p>
            </div>`).join('') : '<div class="theater-empty">No events yet.</div>';
    }

    function chooseTheaterTask(tasks) {
        if (!tasks.length) return null;
        const active = tasks.find((task) => ['running', 'pending', 'blocked', 'failed'].includes(theaterState(task)));
        return active || tasks[0];
    }

    function renderTheater(tasks) {
        theaterTasks = tasks;
        const selected = tasks.find((task) => String(task.id) === String(theaterSelectedId)) || chooseTheaterTask(tasks);
        theaterSelectedId = selected ? String(selected.id || '') : null;
        const running = tasks.filter((task) => theaterState(task) === 'running').length;
        const blocked = tasks.filter((task) => ['blocked', 'failed'].includes(theaterState(task))).length;
        if (statusEl) statusEl.textContent = `${tasks.length} tasks · ${running} moving · ${blocked} blocked`;
        updateTheaterPeople(tasks);
        renderTheaterRunners(tasks);
        renderTheaterCurrent(selected);
        renderTheaterStory(selected);
    }

    async function refreshTheater() {
        if (statusEl) statusEl.textContent = 'loading';
        try {
            const res = await fetch('/api/bridge/tasks?limit=24&include_messages=1', {cache: 'no-store'});
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderTheater(data.tasks || []);
        } catch (err) {
            if (statusEl) statusEl.textContent = 'offline';
            currentEl.innerHTML = `<div class="theater-empty">Bridge unavailable: ${escTheater(err.message)}</div>`;
            storyEl.innerHTML = '<div class="theater-empty">No live events.</div>';
        }
    }

    stage.addEventListener('click', (event) => {
        const runner = event.target.closest?.('.theater-runner');
        if (!runner) return;
        theaterSelectedId = runner.dataset.taskId;
        const selected = theaterTasks.find((task) => String(task.id) === String(theaterSelectedId));
        renderTheaterCurrent(selected);
        renderTheaterStory(selected);
    });
    if (refreshBtn) refreshBtn.addEventListener('click', refreshTheater);
    refreshTheater();
    setInterval(refreshTheater, 5000);
})();
