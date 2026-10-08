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
    // Common Center: copy the safe, credential-free SSH forwarding command.
    document.querySelectorAll('[data-copy]').forEach((button) => {
        const originalText = button.textContent;
        const originalLabel = button.getAttribute('aria-label');
        let restoreTimer;
        const announceCopyState = (text, label) => {
            window.clearTimeout(restoreTimer);
            button.textContent = text;
            button.setAttribute('aria-label', label);
            restoreTimer = window.setTimeout(() => {
                button.textContent = originalText;
                if (originalLabel) button.setAttribute('aria-label', originalLabel);
            }, 1600);
        };
        button.addEventListener('click', async () => {
            const source = document.querySelector(button.dataset.copy);
            if (!source) return;
            const value = source.textContent.trim();
            try {
                await navigator.clipboard.writeText(value);
                announceCopyState('Copied', 'SSH tunnel command copied');
            } catch (_error) {
                const range = document.createRange();
                range.selectNodeContents(source);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                announceCopyState('Selected', 'SSH tunnel command selected; press Command-C to copy');
            }
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

// ── Department Campus ──
(function initDepartmentCampus() {
    const campus = document.getElementById('department-campus');
    if (!campus) return;
    if (campus.dataset.campusRefreshBound === 'true') return;
    campus.dataset.campusRefreshBound = 'true';

    const focusedDepartment = new URLSearchParams(window.location.search).get('view') === 'department';
    const departmentSelect = document.createElement('select');
    departmentSelect.dataset.campusDepartmentSelect = '';
    departmentSelect.setAttribute('aria-label', 'Выбрать отдел');
    campus.querySelectorAll('.campus-zone').forEach(zone => {
        const option = document.createElement('option');
        option.value = zone.dataset.departmentId;
        option.textContent = zone.querySelector('h3').textContent;
        departmentSelect.append(option);
    });
    const departmentPicker = campus.querySelector('[data-campus-department-picker]');
    const departmentCrops = {
        hq: [56, 547, 238, 283], sales: [146, 112, 342, 223],
        development: [592, 108, 375, 232], design: [1085, 114, 342, 221],
        infrastructure: [390, 558, 343, 275], internal: [809, 556, 350, 276],
        finance: [1238, 554, 223, 277],
    };
    function selectCampusDepartment() {
        if (!focusedDepartment || !departmentSelect) return;
        const selected = departmentSelect.value;
        const crop = departmentCrops[selected];
        if (!crop) return;
        campus.querySelectorAll('.campus-zone').forEach(zone => {
            zone.hidden = zone.dataset.departmentId !== selected;
        });
        const map = campus.querySelector('.campus-map');
        const [x, y, width, height] = crop;
        map.style.setProperty('--campus-room-size', `${1536 / width * 100}% ${1024 / height * 100}%`);
        map.style.setProperty('--campus-room-position', `${x / (1536 - width) * 100}% ${y / (1024 - height) * 100}%`);
        notifyCampusContentHeight();
    }
    if (focusedDepartment && departmentSelect && departmentPicker) {
        campus.classList.add('is-department-focus');
        departmentPicker.querySelector('[data-campus-department-picker-slot]').replaceWith(departmentSelect);
        departmentPicker.hidden = false;
        const requested = new URLSearchParams(window.location.search).get('department');
        departmentSelect.value = Object.hasOwn(departmentCrops, requested) ? requested : 'development';
        departmentSelect.addEventListener('change', () => {
            closeCampusDetails(false);
            closeCampusProjectDetails(false);
            selectCampusDepartment();
        });
        selectCampusDepartment();
    }

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    campus.dataset.reducedMotion = String(reducedMotion.matches);

    const stateEl = campus.querySelector('[data-campus-state]');
    const countEl = campus.querySelector('[data-campus-count]');
    const detailEl = campus.querySelector('#campus-agent-details');
    const closeEl = campus.querySelector('[data-campus-detail-close]');
    const projectDetailEl = campus.querySelector('[data-campus-project-detail]');
    const projectDetailCloseEl = campus.querySelector('[data-campus-project-detail-close]');
    const refreshEl = campus.querySelector('[data-campus-refresh]');
    const taskLanesEl = campus.querySelector('[data-campus-task-lanes]');
    const taskPanelEl = campus.querySelector('[data-campus-task-panel]');
    const routeLayerEl = campus.querySelector('[data-campus-route-layer]');
    const managerMarkerEl = campus.querySelector('[data-campus-static-manager]');
    const managerPresenceEl = campus.querySelector('[data-campus-manager-presence]');
    const managerStatusEl = campus.querySelector('[data-campus-manager-status]');
    const boulevardEl = campus.querySelector('.campus-boulevard');
    const rosterEls = Array.from(campus.querySelectorAll('[data-campus-roster-agent]'));
    const projectFolderEls = Array.from(campus.querySelectorAll('[data-campus-project-folder]'));
    const rosterCount = rosterEls.length;
    const detailFields = {};
    campus.querySelectorAll('[data-campus-detail-field]').forEach((el) => {
        detailFields[el.dataset.campusDetailField] = el;
    });
    const projectDetailFields = {};
    campus.querySelectorAll('[data-campus-project-detail-field]').forEach((el) => {
        projectDetailFields[el.dataset.campusProjectDetailField] = el;
    });
    const projectLiveOnlyEls = Array.from(
        campus.querySelectorAll('[data-campus-project-live-only]'),
    );
    const projectEventByFolder = new WeakMap();

    const statusLabels = {
        queued: 'в очереди',
        active: 'работает',
        testing: 'проверяет',
        waiting: 'ждёт решения',
        done: 'готово',
        failed: 'ошибка',
    };
    const resultLabels = {
        queued: 'Ожидает выполнения',
        active: 'В работе',
        testing: 'На проверке',
        waiting: 'Ожидает решения',
        done: 'Завершено',
        failed: 'Завершено с ошибкой',
    };
    const destinationByStatus = {
        active: 'department',
        testing: 'test-lab',
        done: 'github-station',
        queued: 'department',
        waiting: 'department',
        failed: 'department',
    };
    const movingStatuses = ['active', 'testing'];
    const stateMessages = {
        loading: 'Загрузка кампуса…',
        empty: 'Команда на местах · ждёт задачи',
        stale: 'Команда на местах · свежих событий пока нет',
        unavailable: 'Команда на местах · live-данные временно недоступны',
        active: 'Показаны свежие подтверждённые события',
    };

    function campusOwnerHeaders() {
        const headers = {};
        try {
            const token = window.localStorage
                .getItem('command-center.jarvis-run-token')
                ?.trim();
            if (token) headers['X-Dashboard-Run-Token'] = token;
        } catch (_error) {
            // Storage can be unavailable; the endpoint then returns its public projection.
        }
        return headers;
    }

    function verifiedCampusIssue(event) {
        const issueNumber = event?.issue_number;
        const issueUrl = event?.issue_url;
        if (!Number.isInteger(issueNumber) || issueNumber <= 0 || typeof issueUrl !== 'string') {
            return null;
        }
        try {
            const parsed = new URL(issueUrl);
            const match = parsed.pathname.match(
                /^\/[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*\/issues\/([1-9]\d*)$/,
            );
            if (
                parsed.protocol !== 'https:'
                || parsed.hostname !== 'github.com'
                || parsed.username
                || parsed.password
                || parsed.port
                || parsed.search
                || parsed.hash
                || !match
                || Number(match[1]) !== issueNumber
            ) {
                return null;
            }
        } catch (_error) {
            return null;
        }
        return {number: issueNumber, url: issueUrl};
    }
    let lastTrigger = null;
    let intervalId = null;
    let refreshInFlight = false;
    let refreshController = null;
    let refreshGeneration = 0;
    const journeySignatures = new Set();

    function notifyCampusContentHeight() {
        if (window.parent === window) return;
        window.queueMicrotask(() => {
            const height = Math.ceil(campus.getBoundingClientRect().height);
            if (!Number.isFinite(height) || height <= 0) return;
            window.parent.postMessage(
                {type: 'pixelAgentsContentHeight', height},
                '*',
            );
        });
    }

    function closeCampusDetails(returnFocus) {
        if (!detailEl) return;
        detailEl.hidden = true;
        campus.querySelectorAll('[data-campus-agent-trigger]').forEach((button) => {
            button.setAttribute('aria-expanded', 'false');
        });
        if (returnFocus && lastTrigger?.isConnected) lastTrigger.focus();
        notifyCampusContentHeight();
    }

    function closeCampusProjectDetails(returnFocus) {
        if (!projectDetailEl) return;
        projectDetailEl.hidden = true;
        projectFolderEls.forEach((folder) => folder.setAttribute('aria-expanded', 'false'));
        if (returnFocus && lastTrigger?.isConnected) lastTrigger.focus();
        notifyCampusContentHeight();
    }

    function resetCampusProjectFolders() {
        projectFolderEls.forEach((folder) => {
            folder.classList.remove(
                'is-live',
                'is-queued',
                'is-active',
                'is-testing',
                'is-waiting',
                'is-done',
                'is-failed',
            );
            folder.dataset.campusProjectStatus = 'idle';
            folder.setAttribute('aria-expanded', 'false');
            const status = folder.querySelector('[data-campus-project-folder-status]');
            if (status) status.textContent = 'нет активных задач';
            projectEventByFolder.delete(folder);
        });
    }

    function clearCampusAgents() {
        campus.querySelectorAll('[data-campus-live-agent]').forEach((agent) => agent.remove());
        campus.querySelectorAll('[data-campus-waypoint-agents]').forEach((destination) => {
            destination.replaceChildren();
        });
        campus.querySelectorAll('[data-campus-roster-agent]').forEach((resident) => {
            resident.hidden = false;
        });
        if (taskLanesEl) taskLanesEl.replaceChildren();
        if (taskPanelEl) taskPanelEl.hidden = true;
        if (routeLayerEl) routeLayerEl.replaceChildren();
        closeCampusDetails(false);
        closeCampusProjectDetails(false);
        resetCampusProjectFolders();
        setManagerPresence();
        lastTrigger = null;
    }

    function setManagerPresence(event = null) {
        if (!managerPresenceEl || !managerStatusEl) return;
        const status = event && Object.prototype.hasOwnProperty.call(statusLabels, event.status)
            ? statusLabels[event.status]
            : 'ожидает задач';
        managerStatusEl.textContent = status;
        managerPresenceEl.dataset.campusManagerState = event?.status || 'idle';
    }

    function setCampusState(state, visibleTasks, agentCount, omittedTasks) {
        if (stateEl) stateEl.textContent = stateMessages[state] || stateMessages.unavailable;
        if (countEl) {
            const omitted = omittedTasks > 0 ? ` · скрыто задач: ${omittedTasks}` : '';
            const live = agentCount > 0
                ? `активных агентов: ${agentCount} · задач: ${visibleTasks}`
                : 'все ожидают задач';
            countEl.textContent = `${rosterCount} в команде · ${live}${omitted}`;
        }
        campus.dataset.campusState = state;
        notifyCampusContentHeight();
    }

    function openCampusDetails(button, event) {
        if (!detailEl) return;
        closeCampusProjectDetails(false);
        if (lastTrigger && lastTrigger !== button) {
            lastTrigger.setAttribute('aria-expanded', 'false');
        }
        lastTrigger = button;
        button.setAttribute('aria-expanded', 'true');
        detailFields.task_id.textContent = event.task_id;
        detailFields.department.textContent = event.department_label;
        detailFields.project.textContent = event.project;
        detailFields.role.textContent = event.role;
        detailFields.status.textContent = statusLabels[event.status] || '—';
        detailFields.updated_at.textContent = event.updated_at;
        detailFields.next_step.textContent = event.next_step;
        detailFields.result.textContent = resultLabels[event.status] || '—';
        detailFields.evidence_count.textContent = String(event.evidence_count);
        detailEl.hidden = false;
        notifyCampusContentHeight();
    }

    function openCampusProjectDetails(folder) {
        if (!projectDetailEl) return;
        closeCampusDetails(false);
        if (lastTrigger && lastTrigger !== folder) {
            lastTrigger.setAttribute('aria-expanded', 'false');
        }
        lastTrigger = folder;
        folder.setAttribute('aria-expanded', 'true');
        const event = projectEventByFolder.get(folder) || null;
        const nextStep = typeof event?.next_step === 'string' && event.next_step.trim()
            ? event.next_step
            : null;
        const hasEvidence = Number.isInteger(event?.evidence_count) && event.evidence_count >= 0;
        const workSummary = typeof event?.work_summary === 'string' && event.work_summary.trim()
            ? event.work_summary
            : null;
        const issue = verifiedCampusIssue(event);
        projectDetailFields.project.textContent = (
            folder.dataset.campusProjectLabel || folder.dataset.campusProject || '—'
        );
        projectDetailFields.department_id.textContent = (
            folder.dataset.campusProjectDepartmentLabel || '—'
        );
        projectDetailFields.agent_id.textContent = folder.dataset.campusProjectAgentLabel || '—';
        projectDetailFields.status.textContent = event
            ? (statusLabels[event.status] || '—')
            : 'нет активных задач';
        projectDetailFields.work_summary.textContent = workSummary || '—';
        projectDetailFields.issue_url.removeAttribute('href');
        projectDetailFields.issue_url.textContent = '—';
        if (issue) {
            projectDetailFields.issue_url.setAttribute('href', issue.url);
            projectDetailFields.issue_url.textContent = `Issue #${issue.number}`;
        }
        projectDetailFields.next_step.textContent = nextStep || '—';
        projectDetailFields.evidence_count.textContent = hasEvidence
            ? String(event.evidence_count)
            : '—';
        projectLiveOnlyEls.forEach((row) => {
            const field = row.querySelector('[data-campus-project-detail-field]')
                ?.dataset.campusProjectDetailField;
            const visible = {
                work_summary: Boolean(workSummary),
                issue_url: Boolean(issue),
                next_step: Boolean(nextStep),
                evidence_count: hasEvidence,
            };
            row.hidden = !visible[field];
        });
        projectDetailEl.hidden = false;
        projectDetailCloseEl?.focus();
        notifyCampusContentHeight();
    }

    function journeySignature(event) {
        return JSON.stringify([event.task_id, event.agent_id, event.status]);
    }

    function residentForEvent(event) {
        return rosterEls.find((resident) => (
            resident.dataset.campusRosterAgent === String(event?.agent_id || '')
            && resident.dataset.campusResidentDepartment === String(event?.department_id || '')
        )) || null;
    }

    function projectFolderForEvent(event) {
        if (!event || typeof event !== 'object') return null;
        return projectFolderEls.find((folder) => (
            folder.dataset.campusProject === String(event.project || '')
            && folder.dataset.campusProjectAgent === String(event.agent_id || '')
            && folder.dataset.campusProjectDepartment === String(event.department_id || '')
        )) || null;
    }

    function activateCampusProjectFolder(folder, event) {
        folder.classList.add('is-live', `is-${event.status}`);
        folder.dataset.campusProjectStatus = event.status;
        const status = folder.querySelector('[data-campus-project-folder-status]');
        if (status) status.textContent = statusLabels[event.status] || '—';
        projectEventByFolder.set(folder, event);
    }

    function animateCampusJourney(button, shouldAnimate, managerOriginRect) {
        if (reducedMotion.matches || !shouldAnimate) return;
        if (focusedDepartment) {
            if (button.getBoundingClientRect().width && typeof button.animate === 'function') {
                const arrival = button.animate(
                    [{transform: 'translateX(-18px)', opacity: 0.45}, {transform: 'translateX(0)', opacity: 1}],
                    {duration: 700, easing: 'ease-out'},
                );
                arrival.finished.then(() => { button.dataset.campusMoving = 'false'; }).catch(() => {});
            }
            return;
        }
        if (!managerMarkerEl || !boulevardEl || typeof button.animate !== 'function') return;
        const managerRect = managerOriginRect || managerMarkerEl.getBoundingClientRect();
        const boulevardRect = boulevardEl.getBoundingClientRect();
        const destinationRect = button.getBoundingClientRect();
        const destinationX = destinationRect.left + (destinationRect.width / 2);
        const destinationY = destinationRect.top + (destinationRect.height / 2);
        const startX = managerRect.left + (managerRect.width / 2) - destinationX;
        const startY = managerRect.top + (managerRect.height / 2) - destinationY;
        const boulevardX = boulevardRect.left + (boulevardRect.width / 2) - destinationX;
        const boulevardY = boulevardRect.top + (boulevardRect.height / 2) - destinationY;
        button.animate(
            [
                {transform: `translate(${startX}px, ${startY}px)`, opacity: 0.35},
                {transform: `translate(${boulevardX}px, ${boulevardY}px)`, opacity: 0.8, offset: 0.55},
                {transform: 'translate(0px, 0px)', opacity: 1},
            ],
            {duration: 900, easing: 'ease-out'},
        );
    }

    function createCampusAgent(event, shouldAnimate, resident) {
        const destination = destinationByStatus[event.status] || 'department';
        const moving = shouldAnimate && !reducedMotion.matches;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `campus-agent is-${event.status}`;
        button.dataset.campusLiveAgent = '';
        button.dataset.campusAgentTrigger = '';
        button.setAttribute('data-campus-destination', destination);
        button.setAttribute('data-campus-moving', String(moving));
        // Public projection fields only; the 3D scene mirrors these buttons.
        button.dataset.campusAgentId = String(event.agent_id || '');
        button.dataset.campusDepartmentId = String(event.department_id || '');
        button.dataset.campusTaskId = String(event.task_id || '');
        button.dataset.campusStatus = String(event.status || '');
        button.dataset.campusProject = String(event.project || '');
        button.setAttribute('aria-label', `${event.role}, ${statusLabels[event.status] || event.status}`);
        button.setAttribute('aria-controls', 'campus-agent-details');
        button.setAttribute('aria-expanded', 'false');

        const sprite = document.createElement('span');
        sprite.className = 'campus-agent-sprite';
        sprite.setAttribute('aria-hidden', 'true');
        if (resident) {
            for (const property of (
                ['--campus-sprite-x', '--campus-sprite-step-x', '--campus-sprite-y']
            )) {
                sprite.style.setProperty(property, resident.style.getPropertyValue(property));
            }
        }
        const name = document.createElement('strong');
        name.textContent = event.role;
        const status = document.createElement('span');
        status.className = 'campus-agent-status';
        status.textContent = statusLabels[event.status] || '—';
        button.append(sprite, name, status);
        button.addEventListener('click', () => openCampusDetails(button, event));
        button.addEventListener('keydown', (keyEvent) => {
            if (
                !keyEvent.repeat
                && (keyEvent.key === 'Enter' || keyEvent.key === ' ' || keyEvent.key === 'Spacebar')
            ) {
                keyEvent.preventDefault();
                openCampusDetails(button, event);
            }
        });
        return button;
    }

    function renderCampusTaskLanes(events) {
        if (!taskLanesEl) return;
        const taskIds = [];
        events.forEach((event) => {
            if (taskIds.length < 3 && !taskIds.includes(event.task_id)) {
                taskIds.push(event.task_id);
                const lane = document.createElement('span');
                lane.className = 'campus-task-lane';
                lane.textContent = event.task_id;
                taskLanesEl.append(lane);
            }
        });
        if (taskPanelEl) taskPanelEl.hidden = taskIds.length === 0;
    }

    function renderCampusRoutes(events, newJourneySignatures) {
        if (!routeLayerEl) return;
        const route_status_precedence = ['testing', 'active', 'done', 'queued', 'waiting', 'failed'];
        const routedTasks = new Set();
        events.forEach((event) => {
            if (routedTasks.size >= 3 || routedTasks.has(event.task_id)) return;
            routedTasks.add(event.task_id);
            const routeEvent = route_status_precedence
                .map((status) => events.find((candidate) => (
                    candidate.task_id === event.task_id && candidate.status === status
                )))
                .find(Boolean) || event;
            const destination = destinationByStatus[routeEvent.status];
            const moving = !reducedMotion.matches
                && newJourneySignatures.has(journeySignature(routeEvent));
            const route = document.createElement('span');
            route.className = 'campus-route';
            route.setAttribute('data-campus-destination', destination);
            route.setAttribute('data-campus-moving', String(moving));
            route.setAttribute('data-campus-route-task-id', event.task_id);
            route.setAttribute('data-campus-route-status', routeEvent.status);
            route.style.setProperty('--campus-route-index', String(routedTasks.size - 1));
            routeLayerEl.append(route);
        });
    }

    function destinationForEvent(event) {
        const destination = destinationByStatus[event.status] || 'department';
        if (destination === 'test-lab' || destination === 'github-station') {
            return campus.querySelector(
                `[data-campus-waypoint="${destination}"] [data-campus-waypoint-agents]`,
            );
        }
        return campus.querySelector(
            `[data-department-id="${event.department_id}"] [data-campus-zone-agents]`,
        );
    }

    function renderDepartmentCampus(payload) {
        const state = payload && typeof payload.state === 'string' ? payload.state : 'unavailable';
        const events = state === 'active' && Array.isArray(payload.events) ? payload.events : [];
        if (
            state === 'empty'
            || state === 'stale'
            || state === 'unavailable'
            || (state === 'active' && !events.length)
        ) {
            journeySignatures.clear();
        }
        clearCampusAgents();
        if (state !== 'active' || !events.length) {
            setCampusState(
                state === 'active' ? 'empty' : state,
                0,
                0,
                Number(payload?.omitted_task_count) || 0,
            );
            return;
        }
        const matchedEvents = [];
        events.forEach((event) => {
            if (!Object.prototype.hasOwnProperty.call(statusLabels, event?.status)) return;
            const folder = projectFolderForEvent(event);
            if (!folder) return;
            matchedEvents.push(event);
        });
        if (!matchedEvents.length) {
            journeySignatures.clear();
            setCampusState('empty', 0, 0, Number(payload?.omitted_task_count) || 0);
            return;
        }
        setManagerPresence(
            matchedEvents.find((event) => event.agent_id === 'COORDINATOR') || null,
        );
        const newJourneySignatures = new Set();
        const managerOriginRect = managerMarkerEl?.getBoundingClientRect() || null;
        matchedEvents.forEach((event) => {
            const signature = journeySignature(event);
            const unseen = !journeySignatures.has(signature);
            if (unseen) journeySignatures.add(signature);
            if (unseen && movingStatuses.includes(event.status)) {
                newJourneySignatures.add(signature);
            }
        });
        renderCampusTaskLanes(matchedEvents);
        renderCampusRoutes(matchedEvents, newJourneySignatures);
        matchedEvents.forEach((event) => {
            const folder = projectFolderForEvent(event);
            if (!folder) return;
            activateCampusProjectFolder(folder, event);
            const destination = focusedDepartment
                ? folder.closest('.campus-zone')?.querySelector('[data-campus-zone-agents]')
                : destinationForEvent(event);
            if (!destination) return;
            const shouldAnimate = newJourneySignatures.has(journeySignature(event));
            const resident = residentForEvent(event);
            if (resident) resident.hidden = true;
            const button = createCampusAgent(event, shouldAnimate, resident);
            destination.append(button);
            animateCampusJourney(button, shouldAnimate, managerOriginRect);
        });
        const activeAgentCount = new Set(
            matchedEvents.map((event) => String(event.agent_id || '')).filter(Boolean),
        ).size;
        setCampusState(
            'active',
            new Set(matchedEvents.map((event) => event.task_id)).size,
            activeAgentCount,
            Number(payload.omitted_task_count) || 0,
        );
    }

    async function refreshDepartmentCampus(force = false) {
        if (document.hidden) return;
        if (refreshInFlight && !force) return;
        const generation = ++refreshGeneration;
        if (refreshController) refreshController.abort();
        const controller = new AbortController();
        refreshController = controller;
        refreshInFlight = true;
        clearCampusAgents();
        setCampusState('loading', 0, 0, 0);
        try {
            const response = await fetch('/api/manager/departments', {
                cache: 'no-store',
                signal: controller.signal,
                headers: campusOwnerHeaders(),
            });
            if (!response.ok) throw new Error('unavailable');
            const payload = await response.json();
            if (generation !== refreshGeneration || document.hidden) return;
            renderDepartmentCampus(payload);
        } catch (error) {
            if (generation !== refreshGeneration || document.hidden || error.name === 'AbortError') return;
            renderDepartmentCampus({state: 'unavailable', events: []});
        } finally {
            if (generation === refreshGeneration) {
                refreshInFlight = false;
                refreshController = null;
            }
        }
    }

    function startCampusRefresh() {
        if (intervalId || document.hidden) return;
        intervalId = window.setInterval(() => {
            if (!document.hidden) refreshDepartmentCampus();
        }, 15000);
    }

    function stopCampusRefresh() {
        if (!intervalId) return;
        window.clearInterval(intervalId);
        intervalId = null;
    }

    if (closeEl) closeEl.addEventListener('click', () => closeCampusDetails(true));
    if (projectDetailCloseEl) {
        projectDetailCloseEl.addEventListener('click', () => closeCampusProjectDetails(true));
    }
    if (refreshEl) refreshEl.addEventListener('click', () => refreshDepartmentCampus());
    campus.querySelectorAll('[data-campus-project-folder]').forEach((folder) => {
        folder.addEventListener('click', () => openCampusProjectDetails(folder));
        folder.addEventListener('keydown', (event) => {
            if (!event.repeat && (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar')) {
                event.preventDefault();
                openCampusProjectDetails(folder);
            }
        });
    });
    campus.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && projectDetailEl && !projectDetailEl.hidden) {
            event.preventDefault();
            closeCampusProjectDetails(false);
            if (lastTrigger?.isConnected) lastTrigger.focus();
            return;
        }
        if (event.key === 'Escape' && detailEl && !detailEl.hidden) {
            event.preventDefault();
            closeCampusDetails(true);
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            refreshGeneration += 1;
            if (refreshController) refreshController.abort();
            refreshController = null;
            refreshInFlight = false;
            stopCampusRefresh();
            return;
        }
        if (!document.hidden) {
            refreshDepartmentCampus(true);
            startCampusRefresh();
        }
    });
    window.addEventListener('resize', notifyCampusContentHeight);
    if (!document.hidden) {
        refreshDepartmentCampus();
        startCampusRefresh();
    }
})();
// ── End Department Campus ──

// ── Campus 3D Scene ──
// Read-only 3D mirror of the Department Campus. The semantic 2D campus stays
// the single source of truth: this block never fetches events itself, it only
// reads the public state the campus has already rendered. Characters walk only
// for verified active/testing journeys; idle, stale and unavailable states keep
// everyone at their own desk and stop the frame loop.
(function initCampus3dScene() {
    const campus = document.getElementById('department-campus');
    if (!campus || campus.dataset.campus3dBound === 'true') return;
    campus.dataset.campus3dBound = 'true';
    const stage = campus.querySelector('[data-campus-3d]');
    const labelsEl = campus.querySelector('[data-campus-3d-labels]');
    const focusEl = campus.querySelector('[data-campus-3d-focus]');
    const map = campus.querySelector('.campus-map');
    const toggle = campus.querySelector('[data-campus-view-toggle]');
    if (!stage || !labelsEl || !focusEl || !map || !toggle) return;
    // The focused single-department iframe keeps its 2D room crops.
    if (new URLSearchParams(window.location.search).get('view') === 'department') return;

    const VIEW_KEY = 'command-center.campus.view';
    const THREE_URL = new URL('/dashboard-assets/three.module.min.js', window.location.href).href;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    function webglSupported() {
        if (typeof window.WebGLRenderingContext === 'undefined') return false;
        try {
            const probe = document.createElement('canvas');
            const context = probe.getContext('webgl2') || probe.getContext('webgl');
            context?.getExtension('WEBGL_lose_context')?.loseContext();
            return Boolean(context);
        } catch (_error) {
            return false;
        }
    }
    if (!webglSupported()) return;

    function readViewPreference() {
        try {
            return window.localStorage.getItem(VIEW_KEY);
        } catch (_error) {
            return null;
        }
    }

    function writeViewPreference(view) {
        try {
            window.localStorage.setItem(VIEW_KEY, view);
        } catch (_error) {
            // Storage can be unavailable; the view then resets on reload.
        }
    }

    function postContentHeight() {
        if (window.parent === window) return;
        window.queueMicrotask(() => {
            const height = Math.ceil(campus.getBoundingClientRect().height);
            if (!Number.isFinite(height) || height <= 0) return;
            window.parent.postMessage({type: 'pixelAgentsContentHeight', height}, '*');
        });
    }

    let scene3d = null;
    let scenePromise = null;
    let active = false;

    function applyView(want3d) {
        active = Boolean(want3d && scene3d);
        campus.classList.toggle('is-3d-view', active);
        stage.hidden = !active;
        toggle.setAttribute('aria-pressed', String(active));
        toggle.textContent = active ? '2D' : '3D';
        toggle.setAttribute('aria-label', active ? 'Плоский план кампуса' : 'Объёмный 3D-вид кампуса');
        if (active) {
            scene3d.resize();
            scene3d.sync();
        } else {
            focusEl.hidden = true;
        }
        postContentHeight();
    }

    function loadScene() {
        if (!scenePromise) {
            stage.setAttribute('data-campus-3d-state', 'loading');
            scenePromise = import(THREE_URL)
                .then((THREE) => {
                    stage.hidden = false;
                    scene3d = createCampusScene(THREE);
                    stage.setAttribute('data-campus-3d-state', 'ready');
                    return scene3d;
                })
                .catch(() => {
                    stage.hidden = true;
                    stage.setAttribute('data-campus-3d-state', 'unavailable');
                    toggle.hidden = true;
                    return null;
                });
        }
        return scenePromise;
    }

    async function show3d(persist) {
        const ready = await loadScene();
        applyView(Boolean(ready));
        if (persist && ready) writeViewPreference('3d');
    }

    toggle.hidden = false;
    toggle.addEventListener('click', () => {
        if (active) {
            applyView(false);
            writeViewPreference('2d');
            return;
        }
        show3d(true);
    });
    if (readViewPreference() !== '2d') show3d(false);

    function createCampusScene(THREE) {
        const STATUS_GLYPHS = {
            queued: '…', active: '▶', testing: '◎', waiting: '‖', done: '✓', failed: '✕',
        };
        const STATUS_COLORS = {
            queued: 0x9e9aa0, active: 0xe6a23c, testing: 0x6fa8dc,
            waiting: 0xc792ea, done: 0x5fae74, failed: 0xe06c5a,
        };
        const ROUTE_PRECEDENCE = ['testing', 'active', 'done', 'queued', 'waiting', 'failed'];
        const WALK_SPEED = 4.6;
        const MEETING_SECONDS = 1.4;
        const LOOKS = {
            COORDINATOR: {shirt: '#e6a23c', pants: '#3a2c22', skin: '#e9bf98', hair: '#3b2a20'},
            RESEARCHER: {shirt: '#d9708f', pants: '#2b2b38', skin: '#f1cdb0', hair: '#c94f7c'},
            BUILDER: {shirt: '#4f7cc2', pants: '#26262e', skin: '#f0c9a4', hair: '#d7b46a'},
            DESIGNER: {shirt: '#4e7a5a', pants: '#2d2a26', skin: '#c99068', hair: '#2a2a2a'},
            INFRASTRUCTURE: {shirt: '#7c838e', pants: '#22252b', skin: '#e3b693', hair: '#e8e6e1'},
            VAULT: {shirt: '#8a6bb0', pants: '#26242c', skin: '#8d5a3b', hair: '#1f1a17'},
            ANALYST: {shirt: '#3f9a8f', pants: '#24282a', skin: '#6f4630', hair: '#151515'},
        };
        const ROOMS = {
            sales: {x: -8.25, z: -6, w: 6.5, d: 6.5, tint: '#7b4f32'},
            development: {x: -0.5, z: -6, w: 8, d: 6.5, tint: '#80553a'},
            design: {x: 7.75, z: -6, w: 6.5, d: 6.5, tint: '#7b4f32'},
            hq: {x: -11, z: 6, w: 6, d: 6.5, tint: '#845a3b'},
            infrastructure: {x: -4.25, z: 6, w: 6.5, d: 6.5, tint: '#6f4a33'},
            internal: {x: 2.75, z: 6, w: 6.5, d: 6.5, tint: '#7b4f32'},
            finance: {x: 9.5, z: 6, w: 6, d: 6.5, tint: '#7a5236'},
        };
        Object.entries(ROOMS).forEach(([id, room]) => {
            room.id = id;
            room.top = room.z < 0;
            room.farZ = room.z - room.d / 2;
            room.nearZ = room.z + room.d / 2;
            room.doorZ = room.top ? room.nearZ : room.farZ;
            room.doorInner = new THREE.Vector3(room.x, 0, room.top ? room.doorZ - 0.9 : room.doorZ + 0.9);
            room.doorOuter = new THREE.Vector3(room.x, 0, room.top ? -1.5 : 1.5);
            room.aisleZ = room.farZ + 2.3;
        });
        const WAYPOINTS = {
            'test-lab': {x: 2.6, z: 0, color: 0x6fa8dc, label: 'Test Lab'},
            'github-station': {x: 10.4, z: 0, color: 0x5fae74, label: 'GitHub Station'},
        };

        const renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'low-power'});
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.setClearColor(0x09090b, 1);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.domElement.className = 'campus-3d-canvas';
        stage.prepend(renderer.domElement);

        const scene = new THREE.Scene();
        scene.fog = new THREE.Fog(0x09090b, 46, 90);
        const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 200);
        const lookTarget = new THREE.Vector3(-0.8, 0, 0);
        const view = {azimuth: 0, elevation: 0.9};

        scene.add(new THREE.HemisphereLight(0xfff0db, 0x1b1511, 1.25));
        const sun = new THREE.DirectionalLight(0xffe0b5, 2.1);
        sun.position.set(-9, 26, 15);
        sun.castShadow = true;
        sun.shadow.mapSize.set(2048, 2048);
        Object.assign(sun.shadow.camera, {left: -19, right: 19, top: 14, bottom: -14, near: 2, far: 70});
        sun.shadow.bias = -0.0006;
        sun.shadow.normalBias = 0.02;
        scene.add(sun);

        const materials = new Map();
        function material(color, options = {}) {
            const key = JSON.stringify([color, options]);
            if (!materials.has(key)) {
                materials.set(key, new THREE.MeshStandardMaterial({
                    color, roughness: 0.82, metalness: 0.04, flatShading: true, ...options,
                }));
            }
            return materials.get(key);
        }

        function box(parent, w, h, d, color, x, y, z, options) {
            const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material(color, options));
            mesh.position.set(x, y + h / 2, z);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            parent.add(mesh);
            return mesh;
        }

        function canvasTexture(size, draw, repeatX, repeatY) {
            const canvas = document.createElement('canvas');
            canvas.width = size;
            canvas.height = size;
            draw(canvas.getContext('2d'), size);
            const texture = new THREE.CanvasTexture(canvas);
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.repeat.set(repeatX, repeatY);
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = 4;
            return texture;
        }

        const plankTexture = canvasTexture(128, (ctx, size) => {
            const rows = 4;
            for (let row = 0; row < rows; row += 1) {
                ctx.fillStyle = row % 2 ? '#b98a64' : '#c79a72';
                ctx.fillRect(0, row * size / rows, size, size / rows);
                ctx.fillStyle = '#8a6142';
                ctx.fillRect(0, (row + 1) * size / rows - 2, size, 2);
                ctx.fillRect((row * 53) % size, row * size / rows, 2, size / rows);
            }
        }, 3, 3);
        const tileTexture = canvasTexture(128, (ctx, size) => {
            ctx.fillStyle = '#3b352d';
            ctx.fillRect(0, 0, size, size);
            ctx.fillStyle = '#463f35';
            ctx.fillRect(3, 3, size / 2 - 6, size / 2 - 6);
            ctx.fillRect(size / 2 + 3, size / 2 + 3, size / 2 - 6, size / 2 - 6);
            ctx.fillStyle = '#413a31';
            ctx.fillRect(size / 2 + 3, 3, size / 2 - 6, size / 2 - 6);
            ctx.fillRect(3, size / 2 + 3, size / 2 - 6, size / 2 - 6);
        }, 14, 3);

        // ── Ground and boulevard ──
        const ground = new THREE.Mesh(
            new THREE.PlaneGeometry(80, 60),
            material('#121115', {flatShading: false}),
        );
        ground.rotation.x = -Math.PI / 2;
        ground.receiveShadow = true;
        scene.add(ground);
        const boulevard = new THREE.Mesh(
            new THREE.BoxGeometry(29.5, 0.06, 5.5),
            new THREE.MeshStandardMaterial({map: tileTexture, roughness: 0.95}),
        );
        boulevard.position.set(-0.75, 0.03, 0);
        boulevard.receiveShadow = true;
        scene.add(boulevard);
        [-2.82, 2.82].forEach((z) => box(scene, 29.5, 0.1, 0.12, '#5c4a3a', -0.75, 0, z));

        // ── Rooms ──
        const WALL = '#2a272c';
        const TRIM = '#5a3b27';
        const pickRoots = [];
        const lampLights = [];

        function plant(parent, x, z, scale = 1) {
            const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.2 * scale, 0.16 * scale, 0.32 * scale, 8), material('#6b4a35'));
            pot.position.set(x, 0.16 * scale + 0.12, z);
            pot.castShadow = true;
            parent.add(pot);
            const leaves = new THREE.Mesh(new THREE.IcosahedronGeometry(0.36 * scale, 0), material('#4e7a5a'));
            leaves.position.set(x, 0.62 * scale + 0.12, z);
            leaves.castShadow = true;
            parent.add(leaves);
            const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.24 * scale, 0), material('#5f9168'));
            crown.position.set(x + 0.08, 0.92 * scale + 0.12, z - 0.05);
            crown.castShadow = true;
            parent.add(crown);
        }

        function lamp(parent, x, z) {
            box(parent, 0.08, 1.1, 0.08, '#3a3330', x, 0.12, z);
            const bulb = new THREE.Mesh(
                new THREE.SphereGeometry(0.16, 10, 8),
                material('#ffd28a', {emissive: '#ffb347', emissiveIntensity: 1.6}),
            );
            bulb.position.set(x, 1.32, z);
            parent.add(bulb);
            const light = new THREE.PointLight(0xffb85c, 5, 6.5, 1.6);
            light.position.set(x, 1.5, z);
            parent.add(light);
            lampLights.push(light);
        }

        function buildRoom(room) {
            const group = new THREE.Group();
            scene.add(group);
            const floorMaterial = new THREE.MeshStandardMaterial({
                map: plankTexture, color: room.tint, roughness: 0.9,
            });
            const floor = new THREE.Mesh(new THREE.BoxGeometry(room.w, 0.12, room.d), floorMaterial);
            floor.position.set(room.x, 0.06, room.z);
            floor.receiveShadow = true;
            group.add(floor);

            const tall = 1.15;
            const low = 0.42;
            const thick = 0.18;
            const left = room.x - room.w / 2;
            const right = room.x + room.w / 2;
            const door = 1.9;
            const segment = (room.w - door) / 2;
            // The far wall is tall; the wall facing the camera stays low so the
            // room interior is always visible.
            const farHeight = room.top ? tall : tall * 0.85;
            const nearHeight = low;
            const farDoor = !room.top;
            [[room.farZ, farHeight, farDoor], [room.nearZ, nearHeight, !farDoor]].forEach(([z, height, hasDoor]) => {
                if (hasDoor) {
                    box(group, segment, height, thick, WALL, left + segment / 2, 0.12, z);
                    box(group, segment, height, thick, WALL, right - segment / 2, 0.12, z);
                    box(group, segment, 0.06, thick + 0.04, TRIM, left + segment / 2, 0.12 + height, z);
                    box(group, segment, 0.06, thick + 0.04, TRIM, right - segment / 2, 0.12 + height, z);
                } else {
                    box(group, room.w, height, thick, WALL, room.x, 0.12, z);
                    box(group, room.w, 0.06, thick + 0.04, TRIM, room.x, 0.12 + height, z);
                }
            });
            [left, right].forEach((x) => {
                // Side walls taper from the far height to the near height.
                box(group, thick, farHeight, room.d * 0.5, WALL, x, 0.12, room.farZ + room.d * 0.25);
                box(group, thick, nearHeight, room.d * 0.5, WALL, x, 0.12, room.nearZ - room.d * 0.25);
            });
            plant(group, left + 0.55, room.nearZ - 0.55);
            plant(group, right - 0.55, room.nearZ - 0.55, 0.85);
            lamp(group, right - 0.5, room.farZ + 0.55);
            buildRoomProps(group, room);
            return group;
        }

        function buildRoomProps(group, room) {
            const left = room.x - room.w / 2;
            const right = room.x + room.w / 2;
            const midZ = room.z + 0.6;
            if (room.id === 'hq') {
                const rug = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.02, 1.8), material('#4e7a5a'));
                rug.position.set(room.x - 0.6, 0.13, midZ + 0.4);
                rug.receiveShadow = true;
                group.add(rug);
                box(group, 0.9, 0.9, 0.5, '#3a2c22', left + 0.6, 0.12, room.farZ + 0.5);
            } else if (room.id === 'sales') {
                box(group, 1.8, 0.4, 0.7, '#3d5f47', left + 1.3, 0.12, midZ + 0.6);
                box(group, 1.8, 0.45, 0.18, '#355440', left + 1.3, 0.52, midZ + 0.95);
                box(group, 0.5, 1.5, 1.6, '#5a3b27', right - 0.4, 0.12, midZ - 0.2);
            } else if (room.id === 'development') {
                const wallScreen = box(group, 2.4, 0.9, 0.06, '#1c2a24', room.x, 0.5, room.farZ + 0.14, {
                    emissive: '#2f6b4f', emissiveIntensity: 0.55,
                });
                wallScreen.castShadow = false;
            } else if (room.id === 'design') {
                box(group, 0.08, 1.4, 0.08, '#5a3b27', right - 1.1, 0.12, midZ);
                box(group, 1.1, 0.8, 0.06, '#f2f0ea', right - 1.1, 0.75, midZ + 0.06);
                ['#e6a23c', '#4e7a5a', '#d9708f', '#6fa8dc'].forEach((color, index) => {
                    box(group, 0.2, 0.2, 0.02, color, right - 1.4 + (index % 2) * 0.55, 0.85 + Math.floor(index / 2) * 0.3, midZ + 0.1);
                });
                box(group, 1.2, 0.35, 0.8, '#3d5f47', left + 1.0, 0.12, midZ + 0.7);
            } else if (room.id === 'infrastructure') {
                [0, 1, 2].forEach((index) => {
                    const z = room.z - 0.4 + index * 0.75;
                    box(group, 0.6, 1.6, 0.6, '#1f2126', left + 0.55, 0.12, z);
                    [0, 1, 2, 3].forEach((row) => {
                        box(group, 0.04, 0.05, 0.4, '#6fd39a', left + 0.87, 0.4 + row * 0.32, z, {
                            emissive: '#3fbf7f', emissiveIntensity: 1.1,
                        }).castShadow = false;
                    });
                });
            } else if (room.id === 'internal') {
                [-0.9, 0.9].forEach((offset) => {
                    box(group, 0.5, 1.6, 1.3, '#5a3b27', right - 0.4, 0.12, room.z + 0.4 + offset);
                    ['#e6a23c', '#4e7a5a', '#8a6bb0', '#d9708f'].forEach((color, index) => {
                        box(group, 0.06, 0.28, 1.1, color, right - 0.68, 0.3 + index * 0.34, room.z + 0.4 + offset);
                    });
                });
            } else if (room.id === 'finance') {
                const safe = box(group, 0.9, 0.95, 0.8, '#4a4d55', left + 0.75, 0.12, midZ, {metalness: 0.45, roughness: 0.5});
                const dial = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.06, 12), material('#c9a45c', {metalness: 0.6, roughness: 0.4}));
                dial.rotation.x = Math.PI / 2;
                dial.position.set(left + 0.75, 0.62, midZ + 0.42);
                group.add(dial);
                safe.userData.campusSafe = true;
                // Owner-permission threshold: a restrained amber frame inside the room.
                const frame = material('#e6a23c', {emissive: '#e6a23c', emissiveIntensity: 0.35});
                const inset = 0.35;
                const fw = room.w - inset * 2;
                const fd = room.d - inset * 2;
                [[fw, 0.05, room.x, room.farZ + inset], [fw, 0.05, room.x, room.nearZ - inset]].forEach(([w, d, x, z]) => {
                    const strip = new THREE.Mesh(new THREE.BoxGeometry(w, 0.02, d), frame);
                    strip.position.set(x, 0.135, z);
                    group.add(strip);
                });
                [room.x - fw / 2, room.x + fw / 2].forEach((x) => {
                    const strip = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.02, fd), frame);
                    strip.position.set(x, 0.135, room.z);
                    group.add(strip);
                });
            }
        }

        Object.values(ROOMS).forEach(buildRoom);

        // ── Shared waypoints ──
        Object.entries(WAYPOINTS).forEach(([id, waypoint]) => {
            const pad = new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.35, 0.1, 24), material('#1f1e24'));
            pad.position.set(waypoint.x, 0.11, waypoint.z);
            pad.receiveShadow = true;
            scene.add(pad);
            const ring = new THREE.Mesh(
                new THREE.TorusGeometry(1.15, 0.045, 6, 40),
                material(waypoint.color, {emissive: waypoint.color, emissiveIntensity: 0.7}),
            );
            ring.rotation.x = Math.PI / 2;
            ring.position.set(waypoint.x, 0.18, waypoint.z);
            scene.add(ring);
            box(scene, 0.5, 0.75, 0.35, '#2a272c', waypoint.x, 0.16, waypoint.z - 0.85);
            box(scene, 0.42, 0.26, 0.04, '#111', waypoint.x, 0.62, waypoint.z - 0.66, {
                emissive: waypoint.color, emissiveIntensity: 0.5,
            });
            waypoint.id = id;
        });

        // ── Desks and project folders (mirrors the 2D project buttons) ──
        const folderViews = [];
        const roomFolders = {};
        campus.querySelectorAll('[data-campus-project-folder]').forEach((el) => {
            const department = el.dataset.campusProjectDepartment;
            if (!ROOMS[department]) return;
            (roomFolders[department] ||= []).push(el);
        });

        function deskSlots(room, count) {
            const slots = [];
            const usable = room.w - 1.2;
            if (room.top) {
                for (let index = 0; index < count; index += 1) {
                    slots.push(room.x - usable / 2 + usable * (index + 0.5) / count);
                }
                return slots;
            }
            // Bottom rooms keep the boulevard doorway clear.
            if (count === 1) return [room.x + room.w * 0.22];
            for (let index = 0; index < count; index += 1) {
                const side = index % 2 === 0 ? -1 : 1;
                const rank = Math.floor(index / 2);
                slots.push(room.x + side * (room.w * 0.27 + rank * 1.4));
            }
            return slots.sort((a, b) => a - b);
        }

        function buildDesk(room, x, folderEl, index) {
            const group = new THREE.Group();
            scene.add(group);
            const isHq = room.id === 'hq';
            const deskZ = room.farZ + (isHq ? 1.75 : 1.35);
            const width = isHq ? 1.9 : 1.35;
            box(group, width, 0.07, 0.72, '#4a2f1f', x, 0.8, deskZ);
            [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sz]) => {
                box(group, 0.07, 0.68, 0.07, '#3a2418', x + sx * (width / 2 - 0.08), 0.12, deskZ + sz * 0.28);
            });
            const screenColor = room.id === 'infrastructure' ? '#3fbf7f' : room.id === 'design' ? '#d9708f' : '#6fa8dc';
            box(group, 0.62, 0.4, 0.05, '#18181c', x - 0.15, 0.95, deskZ - 0.18);
            const screen = box(group, 0.54, 0.32, 0.01, '#111', x - 0.15, 0.99, deskZ - 0.15, {
                emissive: screenColor, emissiveIntensity: 0.45,
            });
            screen.castShadow = false;
            const folder = box(group, 0.36, 0.05, 0.26, '#d9a85b', x + 0.38, 0.87, deskZ + 0.05);
            folder.material = folder.material.clone();
            box(group, 0.14, 0.02, 0.26, '#c48f43', x + 0.27, 0.92, deskZ + 0.05);
            // Chair on the camera side of the desk.
            // Chair pushed to the side: specialists stand at the desk while working.
            const chairX = x - width / 2 - 0.2;
            box(group, 0.5, 0.08, 0.5, '#3d5f47', chairX, 0.5, deskZ + 0.35);
            box(group, 0.08, 0.5, 0.5, '#355440', chairX - 0.24, 0.58, deskZ + 0.35);
            box(group, 0.06, 0.38, 0.06, '#222', chairX, 0.12, deskZ + 0.35);
            group.userData.pickTarget = folderEl;
            pickRoots.push(group);
            const workSpot = new THREE.Vector3(x, 0, deskZ + 0.62);
            const view = {
                el: folderEl,
                room,
                folder,
                workSpot,
                meetingSpot: new THREE.Vector3(x + 0.2, 0, deskZ + 2.1),
                // Crowded rooms stagger their wall signs so names stay readable.
                labelAnchor: new THREE.Vector3(x, (room.top ? 1.95 : 1.65) + (index % 2) * 0.95, room.farZ),
                label: null,
            };
            folderViews.push(view);
            return view;
        }

        Object.values(ROOMS).forEach((room) => {
            const folders = roomFolders[room.id] || [];
            deskSlots(room, folders.length).forEach((x, index) => buildDesk(room, x, folders[index], index));
        });
        const hqDesk = folderViews.find((view) => view.room.id === 'hq');

        // ── Overlay labels (visual mirror; the 2D map keeps the semantics) ──
        const labels = [];
        function addLabel(kind, anchor, target) {
            const el = document.createElement('span');
            el.className = `campus-3d-label is-${kind}`;
            labelsEl.append(el);
            const label = {el, anchor, visible: true};
            if (target) {
                el.dataset.clickable = 'true';
                el.addEventListener('click', () => target.click());
            }
            labels.push(label);
            return label;
        }
        function setLabelText(label, title, detail) {
            const strong = document.createElement('strong');
            strong.textContent = title;
            if (detail) {
                const small = document.createElement('small');
                small.textContent = detail;
                label.el.replaceChildren(strong, small);
            } else {
                label.el.replaceChildren(strong);
            }
        }

        campus.querySelectorAll('.campus-zone').forEach((zone) => {
            const room = ROOMS[zone.dataset.departmentId];
            if (!room) return;
            const label = addLabel('department', new THREE.Vector3(room.x - room.w / 2 + 0.9, room.top ? 3.8 : 3.6, room.farZ));
            const boundary = zone.querySelector('.campus-owner-boundary');
            setLabelText(label, zone.querySelector('h3')?.textContent || room.id, boundary ? boundary.textContent.trim() : '');
            if (boundary) label.el.classList.add('has-boundary');
        });
        Object.values(WAYPOINTS).forEach((waypoint) => {
            const label = addLabel('waypoint', new THREE.Vector3(waypoint.x, 0.2, waypoint.z - 1.45));
            setLabelText(label, waypoint.label);
        });
        folderViews.forEach((view) => {
            view.label = addLabel('project', view.labelAnchor, view.el);
        });

        // ── Characters ──
        function makePerson(look) {
            const group = new THREE.Group();
            const body = new THREE.Group();
            group.add(body);
            const limb = (color, w, h, d, x, y) => {
                const pivot = new THREE.Group();
                pivot.position.set(x, y, 0);
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material(color));
                mesh.position.y = -h / 2;
                mesh.castShadow = true;
                pivot.add(mesh);
                body.add(pivot);
                return pivot;
            };
            const legs = [limb(look.pants, 0.15, 0.5, 0.17, -0.1, 0.62), limb(look.pants, 0.15, 0.5, 0.17, 0.1, 0.62)];
            const torso = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.52, 0.27), material(look.shirt));
            torso.position.y = 0.88;
            torso.castShadow = true;
            body.add(torso);
            const arms = [limb(look.shirt, 0.12, 0.46, 0.14, -0.29, 1.1), limb(look.shirt, 0.12, 0.46, 0.14, 0.29, 1.1)];
            arms.forEach((arm) => {
                const hand = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.1, 0.12), material(look.skin));
                hand.position.y = -0.5;
                arm.add(hand);
            });
            const head = new THREE.Group();
            head.position.y = 1.36;
            body.add(head);
            const face = new THREE.Mesh(new THREE.IcosahedronGeometry(0.22, 1), material(look.skin));
            face.castShadow = true;
            head.add(face);
            const hair = new THREE.Mesh(
                new THREE.SphereGeometry(0.235, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.52),
                material(look.hair),
            );
            hair.position.set(0, 0.03, -0.02);
            hair.rotation.x = -0.25;
            head.add(hair);
            [-0.08, 0.08].forEach((x) => {
                const eye = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.05, 0.02), material('#1b1b1f'));
                eye.position.set(x, 0.0, 0.205);
                head.add(eye);
            });
            const ring = new THREE.Mesh(
                new THREE.RingGeometry(0.36, 0.46, 28),
                new THREE.MeshBasicMaterial({color: 0xe6a23c, side: THREE.DoubleSide}),
            );
            ring.rotation.x = -Math.PI / 2;
            ring.position.y = 0.15;
            ring.visible = false;
            group.add(ring);
            scene.add(group);
            return {group, body, legs, arms, head, ring};
        }

        function residentInfo(agentId) {
            const resident = campus.querySelector(`[data-campus-roster-agent="${agentId}"]`);
            if (!resident) return null;
            const name = agentId === 'COORDINATOR'
                ? campus.querySelector('[data-campus-manager-name]')?.textContent
                : resident.querySelector('.campus-resident-caption strong')?.textContent;
            return {department: resident.dataset.campusResidentDepartment, name: (name || agentId).trim()};
        }

        const actors = [];
        const residents = new Map();
        const liveActors = new Map();

        function createActor(agentId, info) {
            const person = makePerson(LOOKS[agentId] || LOOKS.BUILDER);
            const actor = {
                agentId,
                name: info?.name || agentId,
                home: null,
                homeRoom: info?.department || null,
                homeFacing: 0,
                room: info?.department || null,
                person,
                position: new THREE.Vector3(),
                facing: 0,
                steps: [],
                mode: 'idle',
                phase: Math.random() * Math.PI * 2,
                status: null,
                destinationKey: null,
                taskId: null,
                button: null,
                label: null,
                bubble: null,
            };
            actor.label = addLabel('agent', {
                copy: (out) => out.copy(actor.position).setY(1.95),
            }, null);
            actor.bubble = addLabel('bubble', {
                copy: (out) => out.copy(actor.position).setY(2.6),
            }, null);
            actor.bubble.visible = false;
            actor.label.el.addEventListener('click', () => {
                if (actor.button?.isConnected) actor.button.click();
            });
            person.group.userData.pickActor = actor;
            pickRoots.push(person.group);
            actors.push(actor);
            return actor;
        }

        function placeActor(actor, point, facing) {
            actor.position.copy(point);
            actor.facing = facing;
            actor.steps = [];
        }

        // One resident per known roster agent, standing in their own room.
        ['COORDINATOR', 'RESEARCHER', 'BUILDER', 'DESIGNER', 'INFRASTRUCTURE', 'VAULT', 'ANALYST'].forEach((agentId) => {
            const info = residentInfo(agentId);
            if (!info || !ROOMS[info.department]) return;
            const actor = createActor(agentId, info);
            const room = ROOMS[info.department];
            if (agentId === 'COORDINATOR' && hqDesk) {
                actor.home = hqDesk.workSpot.clone();
                actor.homeFacing = Math.PI;
            } else {
                actor.home = new THREE.Vector3(room.x - room.w * 0.2, 0, room.z + room.d * 0.18);
                actor.homeFacing = 0.35;
            }
            placeActor(actor, actor.home, actor.homeFacing);
            residents.set(agentId, actor);
        });
        const coordinator = residents.get('COORDINATOR') || null;

        function roomPath(fromRoom, toRoom) {
            const points = [];
            if (fromRoom === toRoom) return points;
            if (fromRoom && ROOMS[fromRoom]) {
                points.push(ROOMS[fromRoom].doorInner.clone(), ROOMS[fromRoom].doorOuter.clone());
            }
            if (toRoom && ROOMS[toRoom]) {
                points.push(ROOMS[toRoom].doorOuter.clone(), ROOMS[toRoom].doorInner.clone());
                points.push(new THREE.Vector3(ROOMS[toRoom].x, 0, ROOMS[toRoom].aisleZ));
            }
            return points;
        }

        function destinationFor(button, slotIndex) {
            const status = button.dataset.campusStatus;
            const agentId = button.dataset.campusAgentId;
            if (agentId === 'COORDINATOR' && coordinator) {
                return {key: 'hq-desk', point: coordinator.home.clone(), room: 'hq', facing: Math.PI};
            }
            const waypointId = button.getAttribute('data-campus-destination');
            const waypoint = WAYPOINTS[waypointId];
            if (waypoint) {
                const offsets = [[-0.5, 0.35], [0.5, 0.35], [0, -0.3], [-0.6, -0.4], [0.6, -0.4]];
                const [dx, dz] = offsets[slotIndex % offsets.length];
                return {
                    key: `${waypointId}:${slotIndex}`,
                    point: new THREE.Vector3(waypoint.x + dx, 0.06, waypoint.z + dz),
                    room: null,
                    facing: 0,
                };
            }
            const desk = folderViews.find((view) => (
                view.el?.dataset.campusProject === button.dataset.campusProject
                && view.el?.dataset.campusProjectDepartment === button.dataset.campusDepartmentId
            ));
            if (desk) {
                return {key: `desk:${desk.el.dataset.campusProject}`, point: desk.workSpot.clone(), room: desk.room.id, facing: Math.PI, status};
            }
            const room = ROOMS[button.dataset.campusDepartmentId];
            return room
                ? {key: `room:${room.id}`, point: new THREE.Vector3(room.x, 0, room.z), room: room.id, facing: 0}
                : null;
        }

        function startJourney(actor, destination, taskId) {
            const steps = [];
            const pushPoints = (points, room) => points.forEach((point, index) => {
                steps.push({to: point, room: index === points.length - 1 ? room : undefined});
            });
            // Handoff with MAIN MANAGER first: the verified event came from HQ.
            if (coordinator && actor !== coordinator && hqDesk) {
                const meeting = hqDesk.meetingSpot.clone();
                const toHq = roomPath(actor.room, 'hq');
                toHq.forEach((point) => steps.push({to: point}));
                steps.push({to: meeting, room: 'hq'});
                steps.push({pause: MEETING_SECONDS, taskId});
                pushPoints(roomPath('hq', destination.room), destination.room);
            } else {
                pushPoints(roomPath(actor.room, destination.room), destination.room);
            }
            steps.push({to: destination.point, room: destination.room, facing: destination.facing});
            actor.steps = steps;
            actor.mode = 'walk';
        }

        // ── Task routes: amber footprints along up to three verified journeys ──
        const routeGroup = new THREE.Group();
        scene.add(routeGroup);
        const routeDot = new THREE.CircleGeometry(0.075, 8);
        const routeMaterial = new THREE.MeshBasicMaterial({color: 0xe6a23c});
        function renderRoutes(primaryByTask) {
            routeGroup.children.forEach((child) => child.dispose?.());
            routeGroup.clear();
            primaryByTask.forEach(({destination}) => {
                if (!destination || !hqDesk) return;
                const points = [hqDesk.meetingSpot.clone()];
                points.push(...roomPath('hq', destination.room), destination.point.clone());
                const dots = [];
                for (let index = 1; index < points.length; index += 1) {
                    const from = points[index - 1];
                    const to = points[index];
                    const length = from.distanceTo(to);
                    for (let travelled = 0; travelled < length; travelled += 0.42) {
                        dots.push(from.clone().lerp(to, travelled / length));
                    }
                }
                if (!dots.length) return;
                const mesh = new THREE.InstancedMesh(routeDot, routeMaterial, dots.length);
                const matrix = new THREE.Matrix4();
                const rotation = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
                const scale = new THREE.Vector3(1, 1, 1);
                dots.forEach((point, index) => {
                    matrix.compose(point.clone().setY(0.16), rotation, scale);
                    mesh.setMatrixAt(index, matrix);
                });
                routeGroup.add(mesh);
            });
        }

        // ── Sync from the rendered 2D campus ──
        function describeStatus(status, text) {
            return `${STATUS_GLYPHS[status] || '·'} ${text}`;
        }

        function sync() {
            const state = campus.dataset.campusState || 'loading';
            if (state === 'loading') return;
            stage.setAttribute('data-campus-3d-live', state);

            folderViews.forEach((view) => {
                const status = view.el?.dataset.campusProjectStatus || 'idle';
                const live = status !== 'idle';
                const statusText = view.el?.querySelector('[data-campus-project-folder-status]')?.textContent || '';
                view.folder.material.emissive.set(live ? 0xe6a23c : 0x000000);
                view.folder.material.emissiveIntensity = live ? 0.9 : 0;
                setLabelText(view.label, view.el?.dataset.campusProjectLabel || '', live ? describeStatus(status, statusText) : statusText);
                view.label.el.classList.toggle('is-live', live);
            });

            const buttons = Array.from(campus.querySelectorAll('[data-campus-live-agent]'))
                .filter((button) => button.dataset.campusAgentId && button.dataset.campusTaskId);
            const wanted = new Map();
            buttons.forEach((button) => {
                wanted.set(`${button.dataset.campusTaskId}|${button.dataset.campusAgentId}`, button);
            });

            liveActors.forEach((actor, key) => {
                if (wanted.has(key)) return;
                liveActors.delete(key);
                if (residents.get(actor.agentId) === actor) {
                    // Stale, empty or finished: the resident is simply back at their desk.
                    actor.status = null;
                    actor.destinationKey = null;
                    actor.taskId = null;
                    actor.button = null;
                    actor.room = actor.homeRoom;
                    actor.mode = 'idle';
                    placeActor(actor, actor.home, actor.homeFacing);
                } else {
                    scene.remove(actor.person.group);
                    actor.label.el.remove();
                    actor.bubble.el.remove();
                    labels.splice(labels.indexOf(actor.label), 1);
                    labels.splice(labels.indexOf(actor.bubble), 1);
                    pickRoots.splice(pickRoots.indexOf(actor.person.group), 1);
                    actors.splice(actors.indexOf(actor), 1);
                }
            });

            const slotCounters = {};
            const primaryByTask = new Map();
            wanted.forEach((button, key) => {
                const agentId = button.dataset.campusAgentId;
                const status = button.dataset.campusStatus;
                let actor = liveActors.get(key);
                if (!actor) {
                    const resident = residents.get(agentId);
                    const residentBusy = Array.from(liveActors.values()).includes(resident);
                    actor = resident && !residentBusy ? resident : createActor(agentId, residentInfo(agentId));
                    if (actor !== resident) {
                        actor.room = actor.homeRoom;
                        actor.home = resident ? resident.home.clone() : new THREE.Vector3();
                        placeActor(actor, resident ? resident.position : actor.home, 0);
                    }
                    liveActors.set(key, actor);
                }
                const slotKey = button.getAttribute('data-campus-destination');
                slotCounters[slotKey] = (slotCounters[slotKey] || 0) + 1;
                const destination = destinationFor(button, slotCounters[slotKey] - 1);
                actor.button = button;
                actor.taskId = button.dataset.campusTaskId;
                const role = button.querySelector('strong')?.textContent || actor.name;
                const statusText = button.querySelector('.campus-agent-status')?.textContent || '';
                setLabelText(actor.label, role, describeStatus(status, statusText));
                actor.label.el.dataset.clickable = 'true';
                actor.label.el.classList.add('is-live');
                actor.person.ring.visible = true;
                actor.person.ring.material.color.setHex(STATUS_COLORS[status] || 0xe6a23c);
                if (!destination) return;
                const changed = actor.destinationKey !== destination.key || actor.status !== status;
                const moving = button.dataset.campusMoving === 'true' && !reducedMotion.matches;
                if (changed && moving && actor !== coordinator) {
                    startJourney(actor, destination, actor.taskId);
                } else if (changed) {
                    placeActor(actor, destination.point, destination.facing);
                    actor.room = destination.room;
                }
                if (!actor.steps.length) actor.mode = 'arrived';
                actor.status = status;
                actor.destinationKey = destination.key;

                const taskId = actor.taskId;
                const current = primaryByTask.get(taskId);
                const rank = ROUTE_PRECEDENCE.indexOf(status);
                // Cap new tasks at three lanes, but let a known task take a higher-precedence event.
                if (agentId !== 'COORDINATOR' && (current ? rank < current.rank : primaryByTask.size < 3)) {
                    primaryByTask.set(taskId, {rank, destination});
                }
            });

            residents.forEach((actor) => {
                if (Array.from(liveActors.values()).includes(actor)) return;
                const managerStatus = actor === coordinator
                    ? campus.querySelector('[data-campus-manager-status]')?.textContent
                    : null;
                setLabelText(actor.label, actor.name, `· ${(managerStatus || 'ожидает задач').trim()}`);
                actor.label.el.classList.remove('is-live');
                delete actor.label.el.dataset.clickable;
                actor.person.ring.visible = false;
            });

            renderRoutes(primaryByTask);
            stage.setAttribute('data-campus-3d-agents', String(liveActors.size));
            requestRender();
        }

        // ── Motion (only verified active/testing work moves) ──
        const scratch = new THREE.Vector3();
        function advanceActors(dt, time) {
            let animating = false;
            actors.forEach((actor) => {
                actor.bubble.visible = false;
            });
            actors.forEach((actor) => {
                const step = actor.steps[0];
                if (step && step.pause !== undefined) {
                    animating = true;
                    actor.mode = 'meet';
                    step.pause -= dt;
                    if (coordinator) {
                        actor.facing = Math.atan2(coordinator.position.x - actor.position.x, coordinator.position.z - actor.position.z);
                        coordinator.facing = actor.facing + Math.PI;
                        coordinator.meeting = true;
                        coordinator.bubble.visible = true;
                        setLabelText(coordinator.bubble, `⇄ ${step.taskId || ''}`);
                    }
                    actor.bubble.visible = true;
                    setLabelText(actor.bubble, `⇄ ${step.taskId || ''}`);
                    if (step.pause <= 0) {
                        actor.steps.shift();
                        if (coordinator) {
                            coordinator.meeting = false;
                            coordinator.facing = coordinator.homeFacing;
                        }
                    }
                } else if (step) {
                    animating = true;
                    actor.mode = 'walk';
                    scratch.copy(step.to).sub(actor.position).setY(0);
                    const distance = scratch.length();
                    const travel = WALK_SPEED * dt;
                    if (distance > 0.001) {
                        actor.facing = Math.atan2(scratch.x, scratch.z);
                    }
                    if (distance <= travel) {
                        actor.position.copy(step.to);
                        if (step.room !== undefined) actor.room = step.room;
                        if (step.facing !== undefined) actor.facing = step.facing;
                        actor.steps.shift();
                    } else {
                        actor.position.addScaledVector(scratch.normalize(), travel);
                    }
                    actor.phase += dt * 11;
                }
                if (!actor.steps.length && actor.mode !== 'idle') {
                    actor.mode = 'arrived';
                }
                const working = actor.mode === 'arrived' && (actor.status === 'active' || actor.status === 'testing');
                if (working) {
                    animating = true;
                    actor.phase += dt * 10;
                }
                poseActor(actor, working, time);
            });
            return animating;
        }

        function poseActor(actor, working, time) {
            const {group, body, legs, arms, head} = actor.person;
            group.position.copy(actor.position);
            group.rotation.y = actor.facing;
            const walking = actor.mode === 'walk' && !reducedMotion.matches;
            const swing = walking ? Math.sin(actor.phase) * 0.65 : 0;
            legs[0].rotation.x = swing;
            legs[1].rotation.x = -swing;
            arms[0].rotation.x = -swing * 0.8;
            arms[1].rotation.x = swing * 0.8;
            body.position.y = walking ? Math.abs(Math.sin(actor.phase)) * 0.06 : 0;
            head.rotation.y = 0;
            if (working && !reducedMotion.matches) {
                arms[0].rotation.x = -1.05 + Math.sin(actor.phase * 1.3) * 0.14;
                arms[1].rotation.x = -1.05 + Math.sin(actor.phase * 1.3 + 1.8) * 0.14;
                head.rotation.y = Math.sin(time * 0.9) * 0.18;
            } else if (actor.mode === 'arrived' && actor.status && actor.status !== 'done') {
                arms[0].rotation.x = -0.35;
                arms[1].rotation.x = -0.35;
            }
        }

        // ── Camera, picking and frame scheduling ──
        function updateCamera() {
            const width = stage.clientWidth || 1;
            const height = stage.clientHeight || 1;
            const aspect = width / height;
            // Portrait stages turn the campus a quarter so the long boulevard
            // runs down the screen instead of shrinking to fit the width.
            const narrow = aspect < 1.1;
            const azimuth = view.azimuth + (narrow ? Math.PI / 2 : 0);
            const elevation = narrow ? Math.max(view.elevation, 1.12) : view.elevation;
            const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
            const distance = narrow
                ? Math.max(23 / (2 * Math.tan(halfFov) * aspect), 31.5 / (2 * Math.tan(halfFov)))
                : 37 * Math.pow(Math.max(1, 1.78 / aspect), 0.95);
            camera.aspect = aspect;
            const planar = Math.cos(elevation) * distance;
            camera.position.set(
                lookTarget.x + Math.sin(azimuth) * planar,
                Math.sin(elevation) * distance,
                lookTarget.z + Math.cos(azimuth) * planar,
            );
            camera.lookAt(lookTarget);
            camera.updateProjectionMatrix();
            labelsEl.classList.toggle('is-compact', width < 720);
        }

        const projected = new THREE.Vector3();
        let focusAnchor = null;
        function placeLabels() {
            const width = stage.clientWidth;
            const height = stage.clientHeight;
            labels.forEach((label) => {
                if (!label.visible) {
                    label.el.hidden = true;
                    return;
                }
                if (typeof label.anchor.copy === 'function' && !label.anchor.isVector3) {
                    label.anchor.copy(projected);
                } else {
                    projected.copy(label.anchor);
                }
                projected.project(camera);
                const offscreen = projected.z > 1 || Math.abs(projected.x) > 1.2 || Math.abs(projected.y) > 1.2;
                label.el.hidden = offscreen;
                if (offscreen) return;
                const x = (projected.x * 0.5 + 0.5) * width;
                const y = (-projected.y * 0.5 + 0.5) * height;
                label.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
                label.el.style.zIndex = String(Math.round((1 - projected.z) * 100000));
            });
            if (focusAnchor) {
                projected.copy(typeof focusAnchor === 'function' ? focusAnchor() : focusAnchor).project(camera);
                focusEl.hidden = projected.z > 1;
                focusEl.style.transform = `translate(${((projected.x * 0.5 + 0.5) * width).toFixed(1)}px, ${((-projected.y * 0.5 + 0.5) * height).toFixed(1)}px) translate(-50%, -50%)`;
            } else {
                focusEl.hidden = true;
            }
        }

        let frame = 0;
        let lastFrame = 0;
        function requestRender() {
            if (!active || frame) return;
            frame = window.requestAnimationFrame(renderFrame);
        }
        function renderFrame(now) {
            frame = 0;
            const dt = lastFrame ? Math.min(0.05, (now - lastFrame) / 1000) : 1 / 60;
            let animating = false;
            if (reducedMotion.matches) {
                actors.forEach((actor) => {
                    const last = actor.steps.filter((step) => step.to).pop();
                    if (last) {
                        placeActor(actor, last.to, last.facing ?? actor.facing);
                        if (last.room !== undefined) actor.room = last.room;
                    }
                    actor.bubble.visible = false;
                    if (actor.mode === 'walk' || actor.mode === 'meet') actor.mode = 'arrived';
                    poseActor(actor, false, now / 1000);
                });
            } else {
                animating = advanceActors(dt, now / 1000);
            }
            renderer.render(scene, camera);
            placeLabels();
            stage.setAttribute('data-campus-3d-animating', String(animating));
            if (animating && active && !document.hidden) {
                lastFrame = now;
                frame = window.requestAnimationFrame(renderFrame);
            } else {
                lastFrame = 0;
            }
        }

        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2();
        function pickAt(clientX, clientY) {
            const rect = renderer.domElement.getBoundingClientRect();
            pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
            raycaster.setFromCamera(pointer, camera);
            const hits = raycaster.intersectObjects(pickRoots, true);
            for (const hit of hits) {
                let node = hit.object;
                while (node) {
                    if (node.userData.pickActor) {
                        const button = node.userData.pickActor.button;
                        return button?.isConnected ? button : null;
                    }
                    if (node.userData.pickTarget) return node.userData.pickTarget;
                    node = node.parent;
                }
            }
            return null;
        }

        const drag = {id: null, x: 0, y: 0, moved: 0};
        const canvas = renderer.domElement;
        canvas.addEventListener('pointerdown', (event) => {
            drag.id = event.pointerId;
            drag.x = event.clientX;
            drag.y = event.clientY;
            drag.moved = 0;
        });
        canvas.addEventListener('pointermove', (event) => {
            if (drag.id !== event.pointerId) {
                canvas.style.cursor = pickAt(event.clientX, event.clientY) ? 'pointer' : 'grab';
                return;
            }
            const dx = event.clientX - drag.x;
            const dy = event.clientY - drag.y;
            drag.moved += Math.abs(dx) + Math.abs(dy);
            drag.x = event.clientX;
            drag.y = event.clientY;
            if (drag.moved < 6) return;
            if (!canvas.hasPointerCapture(event.pointerId)) canvas.setPointerCapture(event.pointerId);
            canvas.style.cursor = 'grabbing';
            view.azimuth = Math.max(-0.75, Math.min(0.75, view.azimuth - dx * 0.006));
            if (event.pointerType === 'mouse') {
                view.elevation = Math.max(0.55, Math.min(1.25, view.elevation + dy * 0.004));
            }
            updateCamera();
            requestRender();
        });
        function endDrag(event) {
            if (drag.id !== event.pointerId) return;
            const click = drag.moved < 6;
            drag.id = null;
            canvas.style.cursor = 'grab';
            if (click && event.type === 'pointerup') {
                const target = pickAt(event.clientX, event.clientY);
                if (target) target.click();
            }
        }
        canvas.addEventListener('pointerup', endDrag);
        canvas.addEventListener('pointercancel', endDrag);
        canvas.addEventListener('dblclick', () => {
            view.azimuth = 0;
            view.elevation = 0.9;
            updateCamera();
            requestRender();
        });

        // Keyboard focus stays on the semantic 2D controls; mirror it in 3D.
        campus.addEventListener('focusin', (event) => {
            if (!active || !map.contains(event.target)) return;
            const folder = folderViews.find((view) => view.el === event.target);
            const actor = actors.find((candidate) => candidate.button === event.target);
            focusAnchor = folder
                ? folder.labelAnchor.clone().setY(0.9)
                : actor
                    ? () => scratch.copy(actor.position).setY(0.9)
                    : null;
            requestRender();
        });
        campus.addEventListener('focusout', () => {
            focusAnchor = null;
            requestRender();
        });

        let syncQueued = false;
        const observer = new MutationObserver((records) => {
            // Ignore the scene's own label updates; only the 2D campus drives sync.
            if (records.every((record) => stage.contains(record.target))) return;
            if (syncQueued || !active) return;
            syncQueued = true;
            window.queueMicrotask(() => {
                syncQueued = false;
                sync();
            });
        });
        observer.observe(campus, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ['data-campus-state', 'data-campus-project-status', 'data-campus-manager-state'],
        });
        reducedMotion.addEventListener?.('change', requestRender);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) requestRender();
        });

        function resize() {
            const width = stage.clientWidth;
            const height = stage.clientHeight;
            if (!width || !height) return;
            renderer.setSize(width, height, false);
            updateCamera();
            requestRender();
        }
        if (typeof ResizeObserver === 'function') {
            new ResizeObserver(() => resize()).observe(stage);
        } else {
            window.addEventListener('resize', resize);
        }

        updateCamera();
        return {resize, sync};
    }
})();
// ── End Campus 3D Scene ──

const GH_REPO = 'pirajoke/agent-dashboard';
const GH_MODE_PATH = 'mode-request.json';
const LOCAL_API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:7777'
    : window.location.origin;

// ══════════════════════════════════════════════════════════════
// ── Systems Command Center: Mac Mini + MacBook Air/Pro + agent flow ──
// ══════════════════════════════════════════════════════════════
(function initSystemsCommandCenter() {
    const root = document.getElementById('command-center');
    if (!root) return;

    const state = {
        machines: {},
        tasks: [],
    };
    const AGENT_LABELS = {
        ROUTER: 'Router',
        PLANNER: 'Planner',
        BUILDER: 'Builder',
        TESTER: 'Tester',
        DEPLOYER: 'Deployer',
        VAULT: 'Vault',
        GITHUB: 'GitHub',
        SUPERVISOR: 'Supervisor',
    };

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));

    function commandText(value) {
        if (value == null) return '';
        if (typeof value === 'string') return value;
        try { return JSON.stringify(value); } catch (_) { return String(value); }
    }

    function compact(value, limit = 130) {
        const text = commandText(value).replace(/\s+/g, ' ').trim();
        return text.length > limit ? text.slice(0, limit - 3).trim() + '...' : text;
    }

    function shortTime(raw) {
        if (!raw) return '-';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return String(raw).slice(0, 16);
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    async function fetchJson(path, timeoutMs = 4500) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(path, {cache: 'no-store', signal: controller.signal});
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } finally {
            clearTimeout(timer);
        }
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

    function taskText(task) {
        const messages = (task.messages || []).map((m) => [m.sender, m.receiver, m.type, m.body, commandText(readMetadata(m))].join(' ')).join(' ');
        return `${task.description || ''} ${task.agent_role || ''} ${task.error || ''} ${commandText(task.result)} ${commandText(readMetadata(task))} ${messages}`.toLowerCase();
    }

    function normalizedTaskState(task) {
        const raw = String(task?.status || task?.state || '').toLowerCase();
        const outcome = `${task?.error || ''} ${commandText(task?.result)}`.toLowerCase();
        if (outcome.match(/\b(authentication_error|permission denied|fatal:|traceback|exception|failed|error: 4\d\d|error: 5\d\d|mmap failed|resource deadlock)\b/)) return 'failed';
        if (['done', 'complete', 'completed', 'success', 'succeeded'].includes(raw)) return 'done';
        if (['failed', 'error'].includes(raw)) return 'failed';
        if (['blocked', 'waiting', 'needs_input'].includes(raw)) return 'blocked';
        if (['running', 'in_progress', 'working', 'active'].includes(raw)) return 'running';
        return 'pending';
    }

    function deriveAgent(task) {
        const role = String(task?.agent_role || '').toUpperCase().replace(/[^A-Z_]/g, '');
        if (AGENT_LABELS[role]) return role;
        const text = taskText(task);
        if (text.match(/\b(pytest|test|selftest|smoke|compileall|validation)\b/)) return 'TESTER';
        if (text.match(/\b(deploy|launchd|restart|rollout|mac mini|macmini|service|runtime)\b/)) return 'DEPLOYER';
        if (text.match(/\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|source-aware)\b/)) return 'VAULT';
        if (text.match(/\b(github|git push|commit|pull request|linear|issue)\b/)) return 'GITHUB';
        if (text.match(/\b(plan|scope|breakdown|handoff|acceptance)\b/)) return 'PLANNER';
        if (text.match(/\b(route|router|telegram intake|intent)\b/)) return 'ROUTER';
        return 'BUILDER';
    }

    function failureReason(task) {
        const meta = readMetadata(task);
        if (meta.blocked_reason || meta.failure_reason) return compact(meta.blocked_reason || meta.failure_reason, 180);
        const candidates = [task?.error, task?.result, ...(task?.messages || []).map((m) => m.body)]
            .map(commandText)
            .filter(Boolean);
        const found = candidates
            .flatMap((text) => text.split(/\n+/))
            .map((line) => line.trim())
            .find((line) => /(authentication_error|permission denied|fatal:|traceback|exception|failed|error:|exit code [1-9]|mmap failed|resource deadlock|blocked)/i.test(line));
        return found ? compact(found, 180) : '';
    }

    function taskTitle(task) {
        return compact(task?.description || task?.title || 'No recent task', 118);
    }

    function serviceRows(data) {
        if (!data || typeof data !== 'object') return [];
        const rows = [];
        const sources = [
            ...(Array.isArray(data.services) ? data.services : []),
            ...(Array.isArray(data.services_detailed) ? data.services_detailed : []),
            ...(Array.isArray(data.items) ? data.items : []),
        ];
        sources.forEach((item) => {
            const name = item.name || item.label || item.service || 'service';
            const running = item.running === true || String(item.status || '').toLowerCase() === 'running' || item.port_ok === true;
            rows.push({
                name,
                status: item.status || (running ? 'running' : 'unknown'),
                running,
                detail: item.detail || item.label || (item.port ? `port ${item.port}` : ''),
            });
        });
        return rows;
    }

    function dedupeServices(groups) {
        const seen = new Set();
        const rows = [];
        groups.flat().forEach((svc) => {
            const key = String(svc.name || '').toLowerCase();
            if (!key || seen.has(key)) return;
            seen.add(key);
            rows.push(svc);
        });
        return rows;
    }

    function renderServices(el, services) {
        if (!el) return;
        if (!services.length) {
            el.innerHTML = '<div class="command-empty">No service data yet.</div>';
            return;
        }
        const important = services
            .slice()
            .sort((a, b) => Number(a.running) - Number(b.running))
            .slice(0, 9);
        el.innerHTML = important.map((svc) => `
            <div class="command-service ${svc.running ? 'is-running' : 'is-stopped'}">
                <span></span>
                <strong>${esc(svc.name)}</strong>
                <em>${esc(compact(svc.detail || svc.status, 48))}</em>
            </div>
        `).join('');
    }

    function authLabel(health) {
        const auth = health?.agent_auth || health?.runtime_auth || health?.claude_auth || null;
        if (!auth) return 'n/a';
        if (auth.status === 'ok' || auth.logged_in === true) return 'ready';
        if (auth.available === false) return 'missing';
        return 'blocked';
    }

    function machineTone(error, health, coreServices) {
        if (error) return 'offline';
        const status = String(health?.status || '').toLowerCase();
        const auth = authLabel(health);
        const criticalDown = coreServices.some((svc) => !svc.running);
        if (status && status !== 'ok') return 'warn';
        if (auth === 'blocked' || auth === 'missing') return 'warn';
        if (criticalDown) return 'warn';
        return 'online';
    }

    function renderMachine(id, label, health, serviceData, error) {
        const card = document.getElementById(`command-system-${id}`);
        if (!card) return;
        const statusEl = document.getElementById(`command-${id}-status`);
        const summaryEl = document.getElementById(`command-${id}-summary`);
        const countEl = document.getElementById(`command-${id}-services-count`);
        const authEl = document.getElementById(`command-${id}-auth`);
        const updatedEl = document.getElementById(`command-${id}-updated`);
        const servicesEl = document.getElementById(`command-${id}-services`);

        const coreServices = serviceRows(health);
        const extraServices = serviceRows(serviceData);
        const allServices = dedupeServices([coreServices, extraServices]);
        const running = allServices.filter((svc) => svc.running).length;
        const total = allServices.length;
        const tone = machineTone(error, health, coreServices);
        const auth = authLabel(health);

        card.classList.remove('is-online', 'is-warn', 'is-offline');
        card.classList.add(`is-${tone}`);
        if (statusEl) statusEl.textContent = error ? 'offline' : tone;
        if (countEl) countEl.textContent = total ? `${running}/${total}` : '-';
        if (authEl) authEl.textContent = auth;
        if (updatedEl) updatedEl.textContent = shortTime(health?.timestamp || health?.updated_at || serviceData?.updated_at);
        if (summaryEl) {
            if (error) {
                summaryEl.textContent = `${label} health unavailable: ${compact(error.message || error, 110)}`;
            } else {
                const down = allServices.filter((svc) => !svc.running).slice(0, 3).map((svc) => svc.name);
                summaryEl.textContent = down.length
                    ? `${running}/${total || 0} services running. Check: ${down.join(', ')}.`
                    : `${label} is reachable. Core services and auth look usable.`;
            }
        }
        renderServices(servicesEl, allServices);
        state.machines[id] = {tone, running, total, auth, error: error ? String(error.message || error) : ''};
    }

    function flowRoute(task) {
        if (!task) return [];
        const text = taskText(task);
        const route = ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'AGENT'];
        if (text.match(/\b(mac mini|macmini|macbook|air|launchd|deploy|runtime|service|health os|health api)\b/)) route.push('SYSTEM');
        if (text.match(/\b(obsidian|vault|memory\.md|todo\.md|status\.md|changelog\.md|claude\.md)\b/)) route.push('VAULT');
        if (text.match(/\b(github|git push|commit|pull request|pr\b|issue|linear)\b/)) route.push('GITHUB');
        if (!route.includes('SYSTEM')) route.push('SYSTEM');
        return route;
    }

    function renderFlow(tasks) {
        const flowTaskEl = document.getElementById('command-flow-task');
        const routeEl = document.getElementById('command-flow-route');
        const stateEl = document.getElementById('command-flow-state');
        const blockerEl = document.getElementById('command-flow-blocker');
        const logEl = document.getElementById('command-live-log');
        const task = tasks[0] || null;

        document.querySelectorAll('[data-command-flow-node]').forEach((node) => {
            node.classList.remove('is-active', 'is-blocked', 'is-done', 'is-running', 'is-pending', 'is-failed');
        });

        if (!task) {
            if (flowTaskEl) flowTaskEl.textContent = 'Waiting for Bridge';
            if (routeEl) routeEl.textContent = '-';
            if (stateEl) stateEl.textContent = '-';
            if (blockerEl) blockerEl.textContent = '-';
            if (logEl) logEl.innerHTML = '<div class="command-empty">No live flow events yet.</div>';
            return;
        }

        const agent = deriveAgent(task);
        const agentLabel = AGENT_LABELS[agent] || agent;
        const taskState = normalizedTaskState(task);
        const route = flowRoute(task);
        const blocker = failureReason(task);
        const systemNode = document.querySelector('[data-command-flow-node="SYSTEM"] span');
        const agentNodeTitle = document.querySelector('[data-command-flow-node="AGENT"] strong');
        const agentNodeDetail = document.querySelector('[data-command-flow-node="AGENT"] span');
        if (agentNodeTitle) agentNodeTitle.textContent = agentLabel;
        if (agentNodeDetail) agentNodeDetail.textContent = `${taskState} execution`;
        if (systemNode) {
            const text = taskText(task);
            if (text.includes('macbook pro') || text.includes('100.74.94.2')) {
                systemNode.textContent = 'MacBook Pro';
            } else if (text.includes('macbook air') || text.includes('100.118.34.14')) {
                systemNode.textContent = 'MacBook Air';
            } else {
                systemNode.textContent = 'Mac Mini / runtime';
            }
        }

        route.forEach((nodeId) => {
            const node = document.querySelector(`[data-command-flow-node="${nodeId}"]`);
            if (node) node.classList.add('is-active', `is-${taskState}`);
        });
        if (taskState === 'failed' || taskState === 'blocked') {
            route.slice(-2).forEach((nodeId) => {
                document.querySelector(`[data-command-flow-node="${nodeId}"]`)?.classList.add('is-blocked');
            });
        }

        if (flowTaskEl) flowTaskEl.textContent = taskTitle(task);
        if (routeEl) routeEl.textContent = route.map((nodeId) => nodeId === 'AGENT' ? agentLabel : nodeId).join(' -> ');
        if (stateEl) stateEl.textContent = taskState;
        if (blockerEl) blockerEl.textContent = blocker || 'none';
        if (logEl) {
            const events = [
                {time: task.created_at, actor: 'Bridge', body: `Task created: ${taskTitle(task)}`},
                ...(task.messages || []).slice(-5).map((m) => ({
                    time: m.created_at,
                    actor: `${m.sender || '?'} -> ${m.receiver || '?'}`,
                    body: compact(m.body || readMetadata(m).event || m.type, 150),
                })),
            ].filter((event) => event.time || event.body);
            logEl.innerHTML = events.map((event) => `
                <div class="command-log-row">
                    <span>${esc(shortTime(event.time))}</span>
                    <strong>${esc(event.actor)}</strong>
                    <em>${esc(event.body)}</em>
                </div>
            `).join('');
        }
    }

    function renderOverallStatus() {
        const statusEl = document.getElementById('command-status');
        if (!statusEl) return;
        const machines = Object.values(state.machines);
        const offline = machines.filter((machine) => machine.tone === 'offline').length;
        const warn = machines.filter((machine) => machine.tone === 'warn').length;
        const activeTasks = state.tasks.filter((task) => ['running', 'pending'].includes(normalizedTaskState(task))).length;
        if (offline) statusEl.textContent = `${offline} system offline`;
        else if (warn) statusEl.textContent = `${warn} system warning`;
        else statusEl.textContent = `green - ${activeTasks} queued`;
    }

    // A machine that answers neither endpoint is skipped for a while, so an
    // offline laptop doesn't hold every 7s refresh for its full timeout.
    const MACHINE_BACKOFF_MIN_MS = 60000;
    const MACHINE_BACKOFF_MAX_MS = 600000;
    const machineBackoff = {};

    async function refreshMachines(force = false) {
        const configs = [
            {id: 'mini', label: 'Mac Mini', health: '/api/health', services: '/api/local-services'},
            {id: 'air', label: 'MacBook Air', health: '/api/air/health', services: '/api/air/services/detailed'},
            {id: 'pro', label: 'MacBook Pro', health: '/api/pro/health', services: '/api/pro/services/detailed'},
        ];
        await Promise.all(configs.map(async (cfg) => {
            const backoff = machineBackoff[cfg.id];
            if (!force && backoff && Date.now() < backoff.until) return;
            const [healthResult, servicesResult] = await Promise.allSettled([
                fetchJson(cfg.health, cfg.id === 'air' ? 5500 : 4500),
                fetchJson(cfg.services, cfg.id === 'air' ? 5500 : 4500),
            ]);
            const health = healthResult.status === 'fulfilled' ? healthResult.value : null;
            const serviceData = servicesResult.status === 'fulfilled' ? servicesResult.value : null;
            const error = healthResult.status === 'rejected'
                ? healthResult.reason
                : (servicesResult.status === 'rejected' && !health ? servicesResult.reason : null);
            if (!health && !serviceData) {
                const delay = Math.min(backoff ? backoff.delay * 2 : MACHINE_BACKOFF_MIN_MS, MACHINE_BACKOFF_MAX_MS);
                machineBackoff[cfg.id] = {until: Date.now() + delay, delay};
            } else {
                delete machineBackoff[cfg.id];
            }
            renderMachine(cfg.id, cfg.label, health, serviceData, error);
        }));
    }

    async function refreshFlow() {
        try {
            const data = await fetchJson('/api/bridge/tasks?limit=18&include_messages=1', 4500);
            state.tasks = data.tasks || [];
            state.tasks.sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0));
            renderFlow(state.tasks);
        } catch (err) {
            state.tasks = [];
            renderFlow([]);
            const blockerEl = document.getElementById('command-flow-blocker');
            if (blockerEl) blockerEl.textContent = `Bridge unavailable: ${compact(err.message || err, 120)}`;
        }
    }

    let refreshInFlight = null;
    let forcedRefreshQueued = false;

    function refreshCommandCenter(force = false) {
        if (refreshInFlight) {
            if (force === true && !forcedRefreshQueued) {
                forcedRefreshQueued = true;
                refreshInFlight.then(() => {
                    forcedRefreshQueued = false;
                    refreshCommandCenter(true);
                });
            }
            return refreshInFlight;
        }
        const statusEl = document.getElementById('command-status');
        if (statusEl) statusEl.textContent = 'refreshing';
        refreshInFlight = Promise.all([refreshMachines(force === true), refreshFlow()])
            .then(renderOverallStatus)
            .finally(() => { refreshInFlight = null; });
        return refreshInFlight;
    }

    document.getElementById('command-refresh')?.addEventListener('click', () => refreshCommandCenter(true));
    window.SystemsCommandCenterRefresh = refreshCommandCenter;
    refreshCommandCenter();
    setInterval(refreshCommandCenter, 7000);
})();

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
    const opsServicesEl = document.getElementById('theater-ops-services');
    const opsLiveEl = document.getElementById('theater-ops-live');
    const opsBlockerEl = document.getElementById('theater-ops-blocker');
    const opsAuthEl = document.getElementById('theater-ops-auth');
    const opsNextEl = document.getElementById('theater-ops-next');
    const managerSprite = document.getElementById('manager-sprite');
    const managerDetails = document.getElementById('manager-details');
    const managerFields = Object.fromEntries(
        [...document.querySelectorAll('[data-manager-field]')].map((el) => [el.dataset.managerField, el])
    );
    if (!stage || !runnersEl || !currentEl || !storyEl) return;

    const LIVE_WINDOW_MS = 6 * 60 * 60 * 1000;

    const STATIONS = {
        USER: {x: 12, y: 55},
        JARVIS: {x: 28, y: 34},
        SUPERVISOR: {x: 39, y: 38},
        BRIDGE: {x: 44, y: 50},
        ROUTER: {x: 39, y: 38},
        PLANNER: {x: 39, y: 38},
        BUILDER: {x: 63, y: 32},
        TESTER: {x: 77, y: 48},
        DEPLOYER: {x: 86, y: 69},
        VAULT: {x: 52, y: 72},
        GITHUB: {x: 24, y: 76},
    };
    const LABELS = {
        USER: 'You',
        JARVIS: 'Jarvis',
        SUPERVISOR: 'Supervisor',
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
        SUPERVISOR: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE'],
        ROUTER: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'JARVIS'],
        PLANNER: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'PLANNER'],
        BUILDER: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'BUILDER'],
        TESTER: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'BUILDER', 'TESTER'],
        DEPLOYER: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'BUILDER', 'TESTER', 'DEPLOYER'],
        VAULT: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'VAULT'],
        GITHUB: ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE', 'BUILDER', 'GITHUB'],
    };
    const MANAGER_STATE_CLASSES = {
        'в очереди': 'queued',
        'работает': 'working',
        'готово': 'done',
        'нужно решение Марка': 'decision',
        'ошибка': 'error',
    };
    const MANAGER_VISUAL_CLASSES = ['is-idle', 'is-queued', 'is-working', 'is-done', 'is-decision', 'is-error'];
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

    function renderManagerEvent(projection) {
        if (!managerSprite || !managerDetails) return;
        const active = projection?.active === true
            && projection.details && projection.station
            && MANAGER_STATE_CLASSES[projection.state];
        const details = active ? projection.details : {
            project: '—',
            time: '—',
            status: 'idle',
            next_step: 'Нет свежего события.',
        };

        managerSprite.classList.remove(...MANAGER_VISUAL_CLASSES);
        managerSprite.classList.add(active ? `is-${MANAGER_STATE_CLASSES[projection.state]}` : 'is-idle');
        managerSprite.dataset.managerState = active ? projection.state : 'idle';
        managerSprite.style.setProperty('--manager-x', active ? String(projection.station.x) : '50');
        managerSprite.style.setProperty('--manager-y', active ? String(projection.station.y) : '52');
        managerSprite.title = active ? `${details.project} · ${details.status}` : 'MAIN MANAGER · idle';
        const stateLabel = managerSprite.querySelector('.manager-state');
        if (stateLabel) stateLabel.textContent = details.status;
        for (const field of ['project', 'time', 'status', 'next_step']) {
            if (managerFields[field]) managerFields[field].textContent = String(details[field] ?? '—');
        }
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

    function theaterTaskTime(task) {
        const raw = task?.updated_at || task?.completed_at || task?.claimed_at || task?.created_at || '';
        const time = new Date(raw).getTime();
        return Number.isNaN(time) ? 0 : time;
    }

    function theaterTaskAgeMs(task) {
        const time = theaterTaskTime(task);
        return time ? Date.now() - time : Number.POSITIVE_INFINITY;
    }

    function theaterIsLiveTask(task) {
        const state = theaterState(task);
        if (state === 'running' || state === 'pending') return true;
        if ((state === 'failed' || state === 'blocked') && theaterTaskAgeMs(task) <= LIVE_WINDOW_MS) return true;
        return false;
    }

    function theaterLastBlocker(tasks) {
        return [...tasks]
            .filter((task) => ['failed', 'blocked'].includes(theaterState(task)))
            .sort((a, b) => theaterTaskTime(b) - theaterTaskTime(a))[0] || null;
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
        if (text.match(/\b(supervisor|orchestrator|triage|route decision|who should handle|control room)\b/)) return 'SUPERVISOR';
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

    function theaterHumanBlocker(task) {
        if (!task) return 'none';
        const reason = theaterReason(task, theaterAgent(task));
        if (/authentication_error|invalid authentication credentials/i.test(reason)) {
            return 'Agent auth is broken: Claude/Codex credentials need refresh.';
        }
        return reason;
    }

    function theaterAgentAction(agent, state) {
        if (state === 'blocked' || state === 'failed') {
            if (agent === 'SUPERVISOR') return 'fix';
            if (agent === 'BRIDGE') return 'hold';
            return 'check';
        }
        const actions = {
            USER: 'ask',
            JARVIS: 'parse',
            SUPERVISOR: 'route',
            BRIDGE: 'queue',
            ROUTER: 'route',
            PLANNER: 'plan',
            BUILDER: 'code',
            TESTER: 'test',
            DEPLOYER: 'ship',
            VAULT: 'write',
            GITHUB: 'sync',
        };
        return actions[agent] || 'work';
    }

    function theaterAuthState(tasks, health) {
        const authTask = [...tasks]
            .filter((task) => /authentication_error|invalid authentication credentials|failed to authenticate/i.test(theaterTaskText(task)))
            .sort((a, b) => theaterTaskTime(b) - theaterTaskTime(a))[0];
        if (authTask && theaterTaskAgeMs(authTask) <= LIVE_WINDOW_MS) {
            return {
                state: 'blocked',
                text: 'Claude login required',
                blocker: 'Recent Bridge task failed because Claude CLI credentials are invalid.',
            };
        }
        const direct = health?.agent_auth || health?.runtime_auth || health?.claude_auth || null;
        if (direct && typeof direct === 'object') {
            const provider = direct.provider || 'Claude';
            if (direct.available === false || direct.status === 'missing') {
                return {
                    state: 'blocked',
                    text: `${provider} CLI missing`,
                    blocker: `${provider} CLI is not available on Mac Mini.`,
                };
            }
            if (direct.logged_in === true || direct.status === 'ok') {
                return {state: 'ok', text: `${provider} ready`, blocker: ''};
            }
            if (direct.logged_in === false || direct.status === 'blocked') {
                return {
                    state: 'blocked',
                    text: `${provider} login required`,
                    blocker: `${provider} CLI is logged out on Mac Mini.`,
                };
            }
            if (direct.error || direct.status === 'error') {
                return {
                    state: 'blocked',
                    text: `${provider} auth check failed`,
                    blocker: theaterCompact(direct.error || direct.message || `${provider} auth check failed`, 120),
                };
            }
        }
        if (authTask) {
            return {
                state: 'blocked',
                text: 'Claude login required',
                blocker: 'Claude CLI on Mac Mini is not authenticated.',
            };
        }
        return {state: 'unknown', text: 'not checked', blocker: ''};
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

    function updateTheaterPeople(tasks, selectedTask) {
        const personState = {};
        Object.keys(LABELS).forEach((agent) => { personState[agent] = []; });
        const focusRoute = selectedTask ? new Set(theaterRoute(selectedTask)) : new Set();
        tasks.slice(0, 16).forEach((task) => {
            const state = theaterState(task);
            theaterRoute(task).forEach((agent) => {
                if (personState[agent]) personState[agent].push(state);
            });
        });
        document.querySelectorAll('[data-theater-agent]').forEach((el) => {
            const agent = el.dataset.theaterAgent;
            const states = personState[agent] || [];
            el.classList.remove('is-active', 'is-running', 'is-pending', 'is-done', 'is-blocked', 'is-failed', 'is-focus-route', 'is-doing');
            delete el.dataset.action;
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
            const inFocus = focusRoute.has(agent);
            if (inFocus) {
                el.classList.add('is-focus-route', 'is-doing');
                el.dataset.action = theaterAgentAction(agent, state);
                const agentIndex = Math.max(0, Object.keys(LABELS).indexOf(agent));
                el.style.setProperty('--walk-delay', `${-0.18 * (agentIndex % 7)}s`);
            } else {
                el.style.removeProperty('--walk-delay');
            }
            if (label) {
                const neutralAgents = ['USER', 'JARVIS', 'SUPERVISOR', 'BRIDGE'];
                if (inFocus) label.textContent = state === 'blocked' ? 'fixing' : theaterAgentAction(agent, state);
                else if (neutralAgents.includes(agent)) label.textContent = `${states.length}`;
                else if (state === 'blocked') label.textContent = `check ${states.length}`;
                else if (state === 'running') label.textContent = `move ${states.length}`;
                else label.textContent = `${state} ${states.length}`;
            }
        });
    }

    function renderTheaterRunners(tasks, selectedTask) {
        const activeFirst = selectedTask ? [selectedTask] : [...tasks].sort((a, b) => {
            const rank = {running: 0, pending: 1, failed: 2, blocked: 2, done: 3, cancelled: 4};
            return (rank[theaterState(a)] ?? 5) - (rank[theaterState(b)] ?? 5);
        });
        const visible = activeFirst.slice(0, 1);
        runnersEl.innerHTML = visible.map((task) => {
            const state = theaterState(task);
            const agent = theaterAgent(task);
            const route = theaterRoute(task).join(',');
            const id = String(task.id || '');
            return `
                <button class="theater-runner theater-runner-${escTheater(state)}" data-task-id="${escTheater(id)}"
                    data-route="${escTheater(route)}" data-state="${escTheater(state)}"
                    data-runner-agent="${escTheater(agent)}" data-seed="${theaterSeed(id)}"
                    type="button" title="${escTheater(theaterTitle(task))}">
                    <span class="theater-mini-person" aria-hidden="true"></span>
                    <span class="theater-runner-label">focus task</span>
                </button>`;
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
        const liveTasks = tasks.filter(theaterIsLiveTask);
        if (!liveTasks.length) return null;
        const active = liveTasks.find((task) => ['running', 'pending'].includes(theaterState(task)));
        return active || liveTasks[0];
    }

    function renderOperatorStatus(tasks, liveTasks, health) {
        const services = Array.isArray(health?.services) ? health.services : [];
        const runningServices = services.filter((svc) => svc.status === 'running' && svc.port_ok !== false).length;
        const authState = theaterAuthState(tasks, health);
        const blocker = theaterLastBlocker(tasks);
        const blockerText = authState.blocker || theaterHumanBlocker(blocker);
        if (opsServicesEl) {
            opsServicesEl.textContent = services.length ? `${runningServices}/${services.length} running` : 'health unavailable';
        }
        if (opsLiveEl) {
            const stale = Math.max(0, tasks.length - liveTasks.length);
            opsLiveEl.textContent = `${liveTasks.length} live · ${stale} historical`;
        }
        if (opsBlockerEl) {
            opsBlockerEl.textContent = blockerText;
        }
        if (opsAuthEl) {
            opsAuthEl.textContent = authState.text;
        }
        if (opsNextEl) {
            if (!services.length) opsNextEl.textContent = 'Fix dashboard health API visibility first.';
            else if (authState.state === 'blocked' || /auth|credentials/i.test(blockerText)) {
                opsNextEl.textContent = 'Run claude auth login on Mac Mini, then send a real Builder smoke.';
            } else if (!liveTasks.length) {
                opsNextEl.textContent = 'Send a small Builder task from Telegram and watch it appear here.';
            } else {
                opsNextEl.textContent = 'Open the focused task and verify result/evidence.';
            }
        }
    }

    function renderTheater(tasks) {
        theaterTasks = tasks;
        const liveTasks = tasks.filter(theaterIsLiveTask);
        const selectedCandidate = liveTasks.find((task) => String(task.id) === String(theaterSelectedId));
        const selected = selectedCandidate || chooseTheaterTask(tasks);
        theaterSelectedId = selected ? String(selected.id || '') : null;
        const blocked = liveTasks.filter((task) => ['blocked', 'failed'].includes(theaterState(task))).length;
        if (statusEl) statusEl.textContent = `${liveTasks.length} live · ${tasks.length} total · ${blocked} blocked`;
        updateTheaterPeople(liveTasks, selected);
        renderTheaterRunners(liveTasks, selected);
        renderTheaterCurrent(selected);
        renderTheaterStory(selected);
    }

    async function refreshTheater() {
        if (statusEl) statusEl.textContent = 'loading';
        try {
            const [res, healthRes, managerRes] = await Promise.all([
                fetch('/api/bridge/tasks?limit=24&include_messages=1', {cache: 'no-store'}),
                fetch('/api/health', {cache: 'no-store'}).catch(() => null),
                fetch('/api/manager/events?limit=24', {cache: 'no-store'}).catch(() => null),
            ]);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const tasks = data.tasks || [];
            let health = null;
            if (healthRes && healthRes.ok) {
                try { health = await healthRes.json(); } catch (_) { health = null; }
            }
            let managerProjection = null;
            if (managerRes && managerRes.ok) {
                try { managerProjection = await managerRes.json(); } catch (_) { managerProjection = null; }
            }
            renderManagerEvent(managerProjection);
            renderTheater(tasks);
            renderOperatorStatus(tasks, tasks.filter(theaterIsLiveTask), health);
        } catch (err) {
            if (statusEl) statusEl.textContent = 'offline';
            currentEl.innerHTML = `<div class="theater-empty">Bridge unavailable: ${escTheater(err.message)}</div>`;
            storyEl.innerHTML = '<div class="theater-empty">No live events.</div>';
            renderOperatorStatus([], [], null);
            renderManagerEvent(null);
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
    if (managerSprite && managerDetails) {
        managerSprite.addEventListener('click', () => {
            const shouldOpen = managerDetails.hidden;
            managerDetails.hidden = !shouldOpen;
            managerSprite.setAttribute('aria-expanded', String(shouldOpen));
        });
    }
    if (refreshBtn) refreshBtn.addEventListener('click', refreshTheater);
    refreshTheater();
    setInterval(refreshTheater, 5000);
})();
