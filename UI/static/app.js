'use strict';

const API_BASE = '';
const MAX_ATTACH_CHARS = 100000;

const state = {
    bots: [],
    currentBotId: null,
    settings: null,
    chatModel: 'fast',
    attachedFile: null,
    busy: {},
    mode: 'local_local',
    models: { catalog: null, installed: [], primary: '', secondary: '', filter: 'all' },
    skills: { installed: [], market: [], marketMeta: {}, filter: 'all', marketLoaded: false },
    mcps: { installed: [], market: [], filter: 'all', marketLoaded: false },
};

const $ = (id) => document.getElementById(id);
const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

const botList = $('botList');
const chatArea = $('chatArea');
const newBotBtn = $('newBotBtn');
const settingsBtn = $('settingsBtn');
const settingsModal = $('settingsModal');
const newBotModal = $('newBotModal');
const editBotModal = $('editBotModal');
const skillModal = $('skillModal');
const pullModal = $('pullModal');
const headerActions = $('headerActions');
const llmStatusPill = $('llmStatusPill');
const mcpStatusPill = $('mcpStatusPill');
const skillsPill = $('skillsPill');
const sidebarToggleBtn = $('sidebarToggleBtn');
const sidebarOverlay = $('sidebarOverlay');
const sidebarEl = $('sidebar');
const modeOptions = $('modeOptions');

const MARKET = {
    skills: { list: 'skillMarketList', chips: 'skillMarketChips', search: 'skillMarketSearch', note: 'skillMarketNote' },
    mcps: { list: 'mcpMarketList', chips: 'mcpMarketChips', search: 'mcpMarketSearch', note: 'mcpMarketNote' },
};

/* ── Helpers ─────────────────────────────────────────────────────── */

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

async function fetchJson(url, options) {
    try {
        const res = await fetch(`${API_BASE}${url}`, options);
        let data = {};
        try { data = await res.json(); } catch (_) { /* non-JSON body */ }
        return { ok: res.ok, status: res.status, data };
    } catch (err) {
        return { ok: false, status: 0, data: { error: err.message } };
    }
}

function sendJson(method, url, body) {
    return fetchJson(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
    });
}
const postJson = (url, body) => sendJson('POST', url, body);

function formatElapsed(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    if (total < 60) return `${total}s`;
    return `${Math.floor(total / 60)}m ${total % 60}s`;
}

function debounce(fn, wait) {
    let timer = null;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}

function setStatus(el, text, ok) {
    if (!el) return;
    el.textContent = text;
    el.className = 'llm-status' + (ok === true ? ' status-ok' : ok === false ? ' status-bad' : '');
}

function setPill(pill, text, level) {
    if (!pill) return;
    pill.className = `header-status ${level}`;
    pill.innerHTML = `<i class="fa-solid ${pill.dataset.icon || 'fa-circle'}" aria-hidden="true"></i><span>${escapeHtml(text)}</span>`;
}

function toast(message, type = 'info', ms = 3500) {
    let host = $('toastHost');
    if (!host) {
        host = document.createElement('div');
        host.id = 'toastHost';
        host.className = 'toast-host';
        document.body.appendChild(host);
    }
    const icons = { info: 'fa-circle-info', success: 'fa-circle-check', error: 'fa-circle-exclamation' };
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}" aria-hidden="true"></i><span>${escapeHtml(message)}</span>`;
    host.appendChild(el);
    setTimeout(() => {
        el.classList.add('leaving');
        setTimeout(() => el.remove(), 200);
    }, ms);
}

let lastFocused = null;

function openModal(modal) {
    if (!modal) return;
    lastFocused = document.activeElement;
    modal.classList.add('active');
    const content = modal.querySelector('.modal-content');
    const field = modal.querySelector('input[type="text"], textarea');
    if (field && modal !== settingsModal) field.focus();
    else if (content) { content.setAttribute('tabindex', '-1'); content.focus({ preventScroll: true }); }
}

function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove('active');
    if (lastFocused && lastFocused.isConnected) lastFocused.focus();
}

function makeKeyboardClickable(el, handler) {
    el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handler(e);
        }
    });
}

/* ── Sidebar drawer (mobile) ─────────────────────────────────────── */

function toggleSidebar(open) {
    const isOpen = open !== false && isMobile();
    if (sidebarToggleBtn) sidebarToggleBtn.setAttribute('aria-expanded', String(isOpen));
    if (sidebarEl) sidebarEl.classList.toggle('mobile-expanded', isOpen);
    if (sidebarOverlay) sidebarOverlay.classList.toggle('active', isOpen);
}

sidebarToggleBtn?.addEventListener('click', () => toggleSidebar(!sidebarEl.classList.contains('mobile-expanded')));
sidebarOverlay?.addEventListener('click', () => toggleSidebar(false));
$('sidebarCloseBtn')?.addEventListener('click', () => toggleSidebar(false));

/* ── Bots: sidebar ───────────────────────────────────────────────── */

function renderBotList() {
    if (!state.bots.length) {
        botList.innerHTML = '<p class="empty empty-pad">No bots yet. Create a new bot to get started.</p>';
        return;
    }
    botList.innerHTML = state.bots.map(bot => {
        const busy = !!state.busy[bot.id];
        return `
        <div class="bot-item${busy ? ' working' : ''}${bot.id === state.currentBotId ? ' active' : ''}" role="button" tabindex="0"
             data-testid="bot-item" data-bot-id="${escapeHtml(bot.id)}" data-bot-name="${escapeHtml(bot.name)}">
            <span class="bot-name"><i class="fa-solid fa-robot" aria-hidden="true"></i> ${escapeHtml(bot.name)}</span>
            <span class="bot-status">${busy ? 'working' : escapeHtml(bot.status || 'idle')}</span>
        </div>`;
    }).join('');
}

botList.addEventListener('click', (e) => {
    const item = e.target.closest('.bot-item');
    if (item) openBotChat(item.dataset.botId);
});
botList.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const item = e.target.closest('.bot-item');
    if (item) {
        e.preventDefault();
        openBotChat(item.dataset.botId);
    }
});

async function loadBots() {
    const { ok, data } = await fetchJson('/api/bots');
    if (!ok) {
        botList.innerHTML = '<p class="empty empty-pad">Failed to load bots.</p>';
        return;
    }
    state.bots = data.bots || data || [];
    renderBotList();
    if (!state.bots.length) {
        state.currentBotId = null;
        chatArea.innerHTML = '<div class="empty">Start by creating a new bot</div>';
    }
}

function setBotBusy(botId, busy) {
    state.busy[botId] = Math.max(0, (state.busy[botId] || 0) + (busy ? 1 : -1));
    const item = botList.querySelector(`.bot-item[data-bot-id="${CSS.escape(botId)}"]`);
    if (!item) return;
    const bot = state.bots.find(b => b.id === botId);
    item.classList.toggle('working', !!state.busy[botId]);
    const statusEl = item.querySelector('.bot-status');
    if (statusEl) statusEl.textContent = state.busy[botId] ? 'working' : (bot ? bot.status : 'idle');
}

function resolveSkillName(skillId) {
    if (!skillId) return 'none';
    const select = $('newBotSkill');
    const option = select && [...select.options].find(o => o.value === skillId);
    if (option && option.text !== '(none)') return option.text;
    return skillId.length > 20 ? skillId.substring(0, 8) : skillId;
}

function scheduleLabel(cfg) {
    if (!cfg) return 'No schedule';
    if (cfg.schedule_type === 'interval') return `Every ${cfg.interval_seconds || 3600}s`;
    if (cfg.schedule_type === 'cron') return `Cron ${cfg.cron_expression || ''}`.trim();
    return 'No schedule';
}

/* ── Bots: chat view ─────────────────────────────────────────────── */

function renderChatHistory(history, historyDiv) {
    historyDiv.innerHTML = '';
    history.forEach((msg, idx) => {
        const isUser = msg.role === 'user';
        const div = document.createElement('div');
        div.className = `message ${isUser ? 'message-user' : 'bot'}`;

        const time = msg.timestamp ? `<span class="message-time">${new Date(msg.timestamp).toLocaleTimeString()}</span>` : '';
        let elapsed = '';
        const prev = history[idx - 1];
        if (!isUser && prev && prev.role === 'user' && prev.timestamp && msg.timestamp) {
            elapsed = ` <span class="message-time"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${formatElapsed(new Date(msg.timestamp) - new Date(prev.timestamp))}</span>`;
        }

        div.innerHTML = `
            <div class="message-label">${isUser ? 'You' : 'Bot'}</div>
            <div class="message-content">${isUser ? escapeHtml(msg.content) : formatAssistantMessage(msg.content)}</div>
            <div>${time}${elapsed}</div>`;
        historyDiv.appendChild(div);
    });
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

function appendWorkingRow(historyDiv) {
    const row = document.createElement('div');
    row.className = 'message bot';
    row.innerHTML = '<div class="message-label">Bot</div><div class="message-content">Working…</div>';
    historyDiv.appendChild(row);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

function appendStarterPrompts(bot) {
    const chips = [];
    const taskPrompt = (bot.config && bot.config.task_prompt) || '';
    if (taskPrompt) chips.push(taskPrompt);
    chips.push('What can you do?');
    const wrap = document.createElement('div');
    wrap.className = 'starter-prompts';
    wrap.innerHTML = chips.map(text =>
        `<button type="button" class="starter-chip" title="${escapeHtml(text)}">${escapeHtml(text.length > 48 ? text.substring(0, 48) + '…' : text)}</button>`
    ).join('');
    wrap.querySelectorAll('.starter-chip').forEach((btn, i) => {
        btn.addEventListener('click', () => sendMessageText(bot.id, chips[i]));
    });
    chatArea.appendChild(wrap);
}

async function refreshChatHistory(botId) {
    if (state.currentBotId !== botId) return;
    const historyDiv = $('chatHistory');
    if (!historyDiv) return;
    const { ok, data } = await fetchJson(`/api/bots/${encodeURIComponent(botId)}`);
    if (!ok) return;
    renderChatHistory(data.conversation_history || [], historyDiv);
    if (state.busy[botId]) appendWorkingRow(historyDiv);
    const cached = state.bots.find(b => b.id === botId);
    if (cached) cached.conversation_history = data.conversation_history;
}

function reenableComposer() {
    const composer = document.querySelector('.chat-composer');
    if (!composer) return;
    const send = composer.querySelector('.btn-save');
    if (send) send.disabled = false;
    const runBtn = $('runTaskBtn');
    if (runBtn) runBtn.disabled = false;
    const input = $('userMessage');
    if (input) input.disabled = false;
}

function chatModelForSend() {
    const llm = (state.settings && state.settings.llm) || {};
    return state.chatModel === 'smart' && llm.secondary_model ? llm.secondary_model : null;
}

async function settleSend(botId, thinkingDiv, input, timer) {
    clearInterval(timer);
    setBotBusy(botId, false);
    if (input && input.isConnected) {
        input.disabled = false;
        input.focus();
    }
    if (state.currentBotId === botId) {
        reenableComposer();
        if (!thinkingDiv.isConnected) await refreshChatHistory(botId);
    }
    await loadBots();
}

function restorePills() {
    [llmStatusPill, mcpStatusPill, skillsPill].forEach(pill => {
        if (pill && headerActions && pill.parentElement !== headerActions) headerActions.appendChild(pill);
    });
}

function placePills(composer) {
    if (!isMobile()) return;
    [llmStatusPill, mcpStatusPill, skillsPill].forEach(pill => pill && composer.appendChild(pill));
}

function healthLine(health) {
    const { disk, memory, cpu } = health || {};
    if (!disk || !memory || !cpu) return '';
    return `<strong>Server Health:</strong><br>
        Disk: ${disk.free_gb}GB free of ${disk.total_gb}GB (${disk.usage_percent}% used)<br>
        Memory: ${memory.free_gb}GB free of ${memory.total_gb}GB (${memory.usage_percent}% used)<br>
        CPU: ${cpu.percent}%`;
}

async function openBotChat(botId) {
    const bot = state.bots.find(b => b.id === botId);
    if (!bot) return;
    toggleSidebar(false);
    state.currentBotId = botId;
    state.attachedFile = null;
    restorePills();
    botList.querySelectorAll('.bot-item').forEach(item => {
        item.classList.toggle('active', item.dataset.botId === botId);
    });

    chatArea.innerHTML = '';
    const cfg = bot.config || {};

    const infoDiv = document.createElement('div');
    infoDiv.className = 'bot-info';
    infoDiv.dataset.botId = bot.id;
    const actions = cfg.enabled
        ? [['edit', 'fa-pen', 'Edit'], ['disable', 'fa-ban', 'DISABLE']]
        : [['delete', 'fa-trash', 'Delete'], ['enable', 'fa-rotate-left', 'Re-Enable']];
    const actionsHtml = actions.map(([action, icon, label]) =>
        `<button type="button" class="btn-secondary small" data-bot-action="${action}" data-bot-id="${escapeHtml(bot.id)}"><i class="fa-solid ${icon}" aria-hidden="true"></i> ${label}</button>`
    ).join(' ');
    const lastRun = cfg.last_run ? new Date(cfg.last_run).toLocaleString() : 'never';
    infoDiv.innerHTML = `
        <span class="bot-meta">Skill: ${escapeHtml(resolveSkillName(bot.skill_id))} · Schedule: ${escapeHtml(scheduleLabel(cfg))} · Last run: ${escapeHtml(lastRun)} · Runs: ${cfg.run_count || 0}</span>
        <div class="bot-health-small" id="botHealth"></div>
        <div class="bot-actions">${actionsHtml}</div>`;
    chatArea.appendChild(infoDiv);

    const historyDiv = document.createElement('div');
    historyDiv.id = 'chatHistory';
    historyDiv.className = 'chat-history';
    chatArea.appendChild(historyDiv);
    renderChatHistory(bot.conversation_history || [], historyDiv);
    if (state.busy[botId]) appendWorkingRow(historyDiv);
    if (!(bot.conversation_history || []).length) appendStarterPrompts(bot);

    const llm = (state.settings && state.settings.llm) || {};
    const smartAvailable = !!llm.secondary_model;
    const switchHtml = llm.local_model ? `
        <div class="model-switch" role="group" aria-label="Model">
            <button type="button" data-model-choice="fast" class="${state.chatModel === 'fast' ? 'active' : ''}">Fast</button>
            <button type="button" data-model-choice="smart" class="${state.chatModel === 'smart' ? 'active' : ''}"${smartAvailable ? '' : ' disabled title="Set a secondary model in Settings to enable Smart"'}>Smart</button>
        </div>` : '';

    const composer = document.createElement('div');
    composer.className = 'chat-composer';
    composer.innerHTML = `
        <input type="text" id="userMessage" class="chat-input" placeholder="Type a message…" aria-label="Message" autocomplete="off" />
        ${switchHtml}
        <button type="button" class="btn-secondary small" id="attachFileBtn" title="Attach a text file" aria-label="Attach a file"><i class="fa-solid fa-paperclip" aria-hidden="true"></i></button>
        <button type="button" class="btn-save"><i class="fa-solid fa-paper-plane" aria-hidden="true"></i> Send</button>
        <button type="button" id="runTaskBtn" class="btn-run-task"><i class="fa-solid fa-play" aria-hidden="true"></i> Run Task</button>`;
    chatArea.appendChild(composer);

    const input = $('userMessage');
    const sendBtn = composer.querySelector('.btn-save');
    const runBtn = $('runTaskBtn');
    if (state.busy[botId]) {
        input.disabled = true;
        sendBtn.disabled = true;
        runBtn.disabled = true;
    } else {
        input.focus();
    }

    composer.querySelectorAll('[data-model-choice]').forEach(btn => btn.addEventListener('click', () => {
        state.chatModel = btn.dataset.modelChoice;
        composer.querySelectorAll('[data-model-choice]').forEach(b => b.classList.toggle('active', b === btn));
    }));
    $('attachFileBtn').addEventListener('click', () => $('fileAttachInput')?.click());
    sendBtn.addEventListener('click', () => sendMessage(input, botId));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendMessage(input, botId);
        }
    });
    runBtn.addEventListener('click', () => runBotTask(botId));
    placePills(composer);

    fetchJson('/api/server-health').then(({ ok, data }) => {
        const el = $('botHealth');
        if (ok && el && state.currentBotId === botId) el.innerHTML = healthLine(data);
    });
}

async function sendMessage(input, botId) {
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    await sendMessageText(botId, message, input);
}

async function sendMessageText(botId, message, input) {
    if (state.busy[botId]) return;
    const historyDiv = $('chatHistory');
    if (!historyDiv) return;
    if (input) input.disabled = true;
    document.querySelector('.starter-prompts')?.remove();

    const sentAt = new Date();
    const userDiv = document.createElement('div');
    userDiv.className = 'message message-user';
    userDiv.innerHTML = `
        <div class="message-label">You</div>
        <div class="message-content">${escapeHtml(message)}</div>
        <div class="message-time">${sentAt.toLocaleTimeString()}</div>`;
    historyDiv.appendChild(userDiv);

    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'message bot';
    thinkingDiv.innerHTML = '<div class="message-label">Bot</div><div class="message-content"><span class="elapsed-timer">0s …</span></div>';
    historyDiv.appendChild(thinkingDiv);
    historyDiv.scrollTop = historyDiv.scrollHeight;

    const timer = setInterval(() => {
        const span = thinkingDiv.querySelector('.elapsed-timer');
        if (span) span.textContent = `${formatElapsed(Date.now() - sentAt.getTime())} …`;
    }, 1000);

    setBotBusy(botId, true);
    const body = { message };
    if (state.attachedFile) body.attachments = [{ name: state.attachedFile.name, content: state.attachedFile.content }];
    const model = chatModelForSend();
    if (model) body.model = model;

    const { ok, status, data } = await postJson(`/api/bots/${encodeURIComponent(botId)}/chat`, body);
    if (thinkingDiv.isConnected) {
        const content = thinkingDiv.querySelector('.message-content');
        if (!ok || data.error) {
            content.textContent = data.error || `Request failed (${status || 'network error'})`;
        } else {
            const receivedAt = new Date();
            content.innerHTML = `
                ${formatAssistantMessage(data.response)}
                <span class="message-time">${receivedAt.toLocaleTimeString()}</span>
                <span class="message-time"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${formatElapsed(receivedAt - sentAt)}</span>`;
        }
        historyDiv.scrollTop = historyDiv.scrollHeight;
    }
    await settleSend(botId, thinkingDiv, input, timer);
}

async function runBotTask(botId) {
    if (state.busy[botId]) return;
    setBotBusy(botId, true);
    const { ok, data } = await postJson(`/api/bots/${encodeURIComponent(botId)}/run`, {});
    setBotBusy(botId, false);
    const viewing = state.currentBotId === botId;
    if (!ok || data.error) {
        const message = data.error || 'Failed to run task';
        if (viewing) toast(message, 'error');
        else console.warn('Background task failed for bot', botId, message);
    } else if (viewing) {
        toast(`Task completed: ${(data.response || '').substring(0, 120)}`, 'success', 5000);
        await refreshChatHistory(botId);
    }
    if (viewing) reenableComposer();
    await loadBots();
}

/* ── Bots: lifecycle ─────────────────────────────────────────────── */

async function setBotEnabled(botId, enabled) {
    const verb = enabled ? 'enable' : 'disable';
    if (!confirm(`Are you sure you want to ${verb} this bot?`)) return;
    const { ok } = await sendJson('PUT', `/api/bots/${encodeURIComponent(botId)}`, { enabled });
    if (!ok) {
        toast(`Could not ${verb} the bot.`, 'error');
        return;
    }
    const bot = state.bots.find(b => b.id === botId);
    if (bot) bot.config.enabled = enabled;
    openBotChat(botId);
}

async function deleteBot(botId) {
    if (!confirm('Are you sure you want to delete this bot? This action cannot be undone.')) return;
    const { ok, data } = await fetchJson(`/api/bots/${encodeURIComponent(botId)}`, { method: 'DELETE' });
    if (!ok) {
        toast(data.error || 'Could not delete the bot.', 'error');
        return;
    }
    if (state.currentBotId === botId) {
        state.currentBotId = null;
        restorePills();
        chatArea.innerHTML = '<div class="empty">Select a bot to begin</div>';
    }
    await loadBots();
    toast('Bot deleted.', 'success');
}

chatArea.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-bot-action]');
    if (!btn) return;
    const id = btn.dataset.botId;
    switch (btn.dataset.botAction) {
        case 'disable': setBotEnabled(id, false); break;
        case 'enable': setBotEnabled(id, true); break;
        case 'delete': deleteBot(id); break;
        case 'edit': openEditBot(id); break;
    }
});

async function loadSkillsForNewBot() {
    const select = $('newBotSkill');
    const editSelect = $('editBotSkill');
    const { ok, data } = await fetchJson('/api/skills/available');
    const skills = ok ? (data.skills || []) : [
        { id: 'demo', name: 'Demo Mode' },
        { id: 'general', name: 'General' },
    ];
    const html = '<option value="">(none)</option>' +
        skills.map(s => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`).join('');
    if (select) select.innerHTML = html;
    if (editSelect) editSelect.innerHTML = html;
}

function toggleEditScheduleGroups(schedule) {
    $('editScheduleOptions').style.display = schedule === 'interval' ? 'block' : 'none';
    $('editCronOptions').style.display = schedule === 'cron' ? 'block' : 'none';
}

async function openEditBot(botId) {
    const { ok, data: bot } = await fetchJson(`/api/bots/${encodeURIComponent(botId)}`);
    if (!ok) {
        toast('Could not load the bot for editing.', 'error');
        return;
    }
    await loadSkillsForNewBot();
    const cfg = bot.config || {};
    $('editBotId').value = bot.id;
    $('editBotName').value = bot.name || '';
    $('editBotSkill').value = bot.skill_id || '';
    $('editBotTaskPrompt').value = cfg.task_prompt || '';
    const schedule = cfg.schedule_type || 'none';
    $('editBotSchedule').value = schedule;
    $('editBotInterval').value = cfg.interval_seconds || 3600;
    $('editBotCron').value = cfg.cron_expression || '';
    toggleEditScheduleGroups(schedule);
    $('editBotStatus').textContent = '';
    toggleSidebar(false);
    openModal(editBotModal);
}

$('editBotSchedule')?.addEventListener('change', (e) => toggleEditScheduleGroups(e.target.value));

$('editBotForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const botId = $('editBotId').value;
    const schedule = $('editBotSchedule').value;
    const statusEl = $('editBotStatus');
    const { ok } = await sendJson('PUT', `/api/bots/${encodeURIComponent(botId)}`, {
        name: $('editBotName').value,
        skill_id: $('editBotSkill').value || '',
        task_prompt: $('editBotTaskPrompt').value,
        schedule_type: schedule,
        interval_seconds: schedule === 'interval' ? parseInt($('editBotInterval').value, 10) || 3600 : 0,
        cron_expression: schedule === 'cron' ? $('editBotCron').value : '',
    });
    if (!ok) {
        setStatus(statusEl, 'Failed to save bot.', false);
        return;
    }
    closeModal(editBotModal);
    await loadBots();
    openBotChat(botId);
    toast('Bot saved.', 'success');
});

newBotBtn?.addEventListener('click', () => {
    toggleSidebar(false);
    $('newBotForm').reset();
    $('scheduleOptions').style.display = 'none';
    openModal(newBotModal);
});

$('newBotSchedule')?.addEventListener('change', (e) => {
    $('scheduleOptions').style.display = e.target.value === 'interval' ? 'block' : 'none';
});

$('newBotForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const scheduleType = $('newBotSchedule').value;
    const { ok, data } = await postJson('/api/bots', {
        name: $('newBotName').value,
        skill_id: $('newBotSkill').value || '',
        task_prompt: $('newBotTaskPrompt').value,
        schedule_type: scheduleType,
        interval_seconds: scheduleType === 'interval' ? parseInt($('newBotInterval').value, 10) || 3600 : 0,
        enabled: $('newBotEnabled').checked,
    });
    if (!ok) {
        toast(data.error || 'Could not create the bot.', 'error');
        return;
    }
    closeModal(newBotModal);
    await loadBots();
    if (data.bot && data.bot.id) openBotChat(data.bot.id);
});

/* ── Attachments and chat search ─────────────────────────────────── */

function isCurrentModelVision() {
    const local = (state.settings?.llm?.local_model || '').toLowerCase();
    const secondary = (state.settings?.llm?.secondary_model || '').toLowerCase();
    const active = state.chatModel === 'smart' && secondary ? secondary : local;
    const visionKeywords = ['gemma3', 'llava', 'qwen2.5vl', 'vision', 'gpt-4o', 'claude-3', 'gemini'];
    return visionKeywords.some(k => active.includes(k)) || active.includes('vision') || active === '';
}

function renderAttachedChip() {
    let bar = $('attachedFileBar');
    const file = state.attachedFile;
    if (!file) {
        bar?.remove();
        return;
    }
    const composer = document.querySelector('.chat-composer');
    if (!composer) return;
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'attachedFileBar';
        bar.className = 'attached-file-bar';
        composer.before(bar);
    }
    const isImg = file.type === 'image';
    const icon = isImg
        ? `<img src="${file.content}" class="attached-image-thumb" alt="${escapeHtml(file.name)}">`
        : '<i class="fa-solid fa-file-lines" aria-hidden="true"></i>';
    const detail = isImg ? 'image' : `${file.content.length.toLocaleString()} chars`;
    bar.innerHTML = `
        ${icon}
        <span>Attached: ${escapeHtml(file.name)} (${detail})</span>
        <button type="button" class="btn-secondary small" id="detachFileBtn" aria-label="Remove attachment"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>`;
    $('detachFileBtn').addEventListener('click', () => {
        state.attachedFile = null;
        renderAttachedChip();
    });
}

$('fileAttachInput')?.addEventListener('change', (e) => {
    const input = e.target;
    const file = input.files[0];
    input.value = '';
    if (!file) return;

    if (file.type && file.type.startsWith('image/')) {
        if (!isCurrentModelVision()) {
            toast('Image attachments require a vision-capable model (e.g. gemma3, llava, qwen2.5vl).', 'error');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            toast('Image must be under 5MB.', 'error');
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            state.attachedFile = {
                name: file.name,
                type: 'image',
                content: String(reader.result || ''),
            };
            renderAttachedChip();
        };
        reader.onerror = () => toast('Could not read image file.', 'error');
        reader.readAsDataURL(file);
        return;
    }

    if (file.size > MAX_ATTACH_CHARS) {
        toast('That file is too large to attach (100,000 character limit).', 'error');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        const text = String(reader.result || '');
        if (text.includes('\0')) {
            toast('Only text files and images can be attached.', 'error');
            return;
        }
        state.attachedFile = { name: file.name, type: 'text', content: text.slice(0, MAX_ATTACH_CHARS) };
        renderAttachedChip();
    };
    reader.onerror = () => toast('Could not read that file.', 'error');
    reader.readAsText(file);
});

const chatSearchInput = $('chatSearchInput');
const chatSearchResults = $('chatSearchResults');

async function runChatSearch() {
    const query = chatSearchInput.value.trim();
    if (!query) {
        chatSearchResults.innerHTML = '';
        return;
    }
    const { ok, data } = await fetchJson(`/api/bots/search?q=${encodeURIComponent(query)}`);
    if (!ok) {
        chatSearchResults.innerHTML = '<p class="search-empty">Search failed.</p>';
        return;
    }
    const results = data.results || [];
    if (!results.length) {
        chatSearchResults.innerHTML = '<p class="search-empty">No matches.</p>';
        return;
    }
    chatSearchResults.innerHTML = results.map(r => `
        <div class="search-result" role="button" tabindex="0" data-bot-id="${escapeHtml(r.bot_id)}">
            <span class="search-result-bot">${escapeHtml(r.bot_name)}</span>
            <span class="search-result-role">${escapeHtml(r.role)}</span>
            <span class="search-result-text">${escapeHtml(r.snippet)}</span>
        </div>`).join('');
}

function openSearchResult(el) {
    chatSearchInput.value = '';
    chatSearchResults.innerHTML = '';
    openBotChat(el.dataset.botId);
}

chatSearchInput?.addEventListener('input', debounce(runChatSearch, 250));
chatSearchInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        chatSearchInput.value = '';
        chatSearchResults.innerHTML = '';
    }
});
chatSearchResults?.addEventListener('click', (e) => {
    const el = e.target.closest('.search-result');
    if (el) openSearchResult(el);
});
chatSearchResults?.addEventListener('keydown', (e) => {
    const el = e.target.closest('.search-result');
    if (el && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        openSearchResult(el);
    }
});

/* ── Markdown rendering for bot replies ──────────────────────────── */

// === formatAssistantMessage:begin ===
// Tight markdown renderer with no library and no HTML injection from model
// output: fenced code is pulled out first, the rest is escaped, then inline
// markdown and block structure are applied.
function formatAssistantMessage(text) {
    const codeBlocks = [];
    let body = String(text || '');
    body = body.replace(/```[^\n]*\n([\s\S]*?)(?:```|$)/g, (m, code) => {
        codeBlocks.push(code.replace(/\n$/, ''));
        return `\n@@CODE${codeBlocks.length - 1}@@\n`;
    });

    body = body.split('\n').map(line => line.replace(/[ \t]+$/, '')).join('\n');
    body = body.replace(/\n{3,}/g, '\n\n').trim();

    const inline = (s) => {
        let out = escapeHtml(s);
        out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
        // Render images created by MCPs and Skills
        out = out.replace(/!\[([^\]\n]*)\]\(([^)\s(]*(?:\([^)\s]*\)[^)\s]*)*)\)/g, (m, alt, url) => {
            if (/^(https?:\/\/|data:image\/|\/)/i.test(url)) {
                return `<figure class="chat-image-wrap"><img class="chat-image" src="${url}" alt="${alt || 'Image'}" loading="lazy"><figcaption class="chat-image-caption">${alt}</figcaption></figure>`;
            }
            return alt;
        });
        out = out.replace(/\[([^\]\n]+)\]\(([^)\s(]*(?:\([^)\s]*\)[^)\s]*)*)\)/g, (m, label, url) => {
            if (/^(https?:\/\/|mailto:|\/|#)/.test(url)) {
                return `<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
            }
            return label;
        });
        return out;
    };

    const blocks = [];
    let paragraph = [];
    let list = null;
    const flushParagraph = () => {
        if (paragraph.length) {
            blocks.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
            paragraph = [];
        }
    };
    const flushList = () => {
        if (list) {
            const items = list.items.map(item => `<li>${inline(item)}</li>`).join('');
            blocks.push(`<${list.tag}>${items}</${list.tag}>`);
            list = null;
        }
    };

    body.split('\n').forEach(line => {
        const codeMatch = line.match(/^@@CODE(\d+)@@$/);
        if (codeMatch) {
            flushParagraph(); flushList();
            blocks.push(`<pre><code>${escapeHtml(codeBlocks[Number(codeMatch[1])])}</code></pre>`);
            return;
        }
        const heading = line.match(/^#{1,6}\s+(.*)$/);
        if (heading) {
            flushParagraph(); flushList();
            blocks.push(`<h4>${inline(heading[1])}</h4>`);
            return;
        }
        const ul = line.match(/^[-*]\s+(.*)$/);
        const ol = line.match(/^\d+[.)]\s+(.*)$/);
        if (ul || ol) {
            flushParagraph();
            const tag = ul ? 'ul' : 'ol';
            if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
            list.items.push((ul || ol)[1]);
            return;
        }
        if (line.trim() === '') {
            flushParagraph(); flushList();
            return;
        }
        paragraph.push(line);
    });
    flushParagraph(); flushList();
    return blocks.join('');
}
// === formatAssistantMessage:end ===

/* ── Settings: modal, tabs, save ─────────────────────────────────── */

const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

function activateTab(name) {
    tabBtns.forEach(btn => {
        const active = btn.dataset.tab === name;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', String(active));
    });
    tabContents.forEach(content => content.classList.toggle('active', content.id === `tab-${name}`));
    if (name === 'mcp') loadInstalledMcps();
    if (name === 'skills') loadInstalledSkills();
}

tabBtns.forEach(btn => btn.addEventListener('click', () => activateTab(btn.dataset.tab)));

function openSettings(tab) {
    toggleSidebar(false);
    loadSettings();
    const current = document.querySelector('.tab-btn.active')?.dataset.tab || 'llm';
    activateTab(tab || current);
    openModal(settingsModal);
}

settingsBtn?.addEventListener('click', () => openSettings());

[[llmStatusPill, 'llm'], [mcpStatusPill, 'mcp'], [skillsPill, 'skills']].forEach(([pill, tab]) => {
    if (!pill) return;
    pill.addEventListener('click', () => openSettings(tab));
    makeKeyboardClickable(pill, () => openSettings(tab));
});

async function loadSettings() {
    const { ok, data: settings } = await fetchJson('/api/settings');
    if (!ok) return;
    state.settings = settings;
    const llm = settings.llm || {};
    $('settingsLocalModel').value = llm.local_model || 'llama3.2:3b';
    $('settingsSecondaryModel').value = llm.secondary_model || '';
    $('settingsSecondaryBaseUrl').value = llm.secondary_base_url || '';
    $('settingsSecondaryApiKey').value = llm.secondary_api_key || '';
    $('settingsRemoteBaseUrl').value = llm.remote_base_url || '';
    $('settingsRemoteApiKey').value = llm.remote_api_key || '';
    $('settingsRemoteModel').value = llm.remote_model || 'gpt-4o-mini';
    const gitUrlInput = $('settingsSkillsGitUrl');
    if (gitUrlInput) gitUrlInput.value = settings.skills?.git_url || '';
    $('settingsSchedulerEnabled').checked = settings.scheduler?.enabled !== false;
    $('settingsSchedulerTick').value = settings.scheduler?.tick_seconds || 30;
    loadLlmStatus();
    loadMcpStatus();
}

async function saveSettings() {
    const statusEl = $('settingsSaveStatus');
    const { ok, data } = await postJson('/api/settings', {
        llm: {
            local_model: $('settingsLocalModel').value,
            secondary_model: $('settingsSecondaryModel').value,
            secondary_base_url: $('settingsSecondaryBaseUrl').value,
            secondary_api_key: $('settingsSecondaryApiKey').value,
            remote_base_url: $('settingsRemoteBaseUrl').value,
            remote_api_key: $('settingsRemoteApiKey').value,
            remote_model: $('settingsRemoteModel').value,
        },
        scheduler: {
            enabled: $('settingsSchedulerEnabled').checked,
            tick_seconds: parseInt($('settingsSchedulerTick').value, 10) || 30,
        },
    });
    if (ok && data.success) {
        setStatus(statusEl, 'Settings saved ✓', true);
        await loadSettings();
        setTimeout(() => closeModal(settingsModal), 900);
    } else {
        setStatus(statusEl, 'Failed to save settings.', false);
    }
}

$('settingsForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const saveBtn = $('settingsSaveBtn');
    const original = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    try {
        await saveSettings();
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = original;
    }
});

/* ── Settings: LLM mode ──────────────────────────────────────────── */

function setLlmsCollapsed(collapsed) {
    const body = $('llmsBody');
    const btn = $('llmsCollapseBtn');
    if (body) body.style.display = collapsed ? 'none' : '';
    if (btn) {
        btn.setAttribute('aria-expanded', String(!collapsed));
        btn.innerHTML = `<i class="fa-solid fa-chevron-${collapsed ? 'right' : 'down'}" aria-hidden="true"></i>`;
        btn.title = collapsed ? 'Expand local models' : 'Collapse local models';
    }
}

$('llmsCollapseBtn')?.addEventListener('click', () => {
    setLlmsCollapsed($('llmsBody').style.display !== 'none');
});

function updateModeUI(modeKey) {
    const show = (id, visible) => {
        const el = $(id);
        if (el) el.style.display = visible ? '' : 'none';
    };
    const isCloud = modeKey === 'local_cloud';
    const isRemoteLocal = modeKey === 'local_remote_local';
    const showSection = isCloud || isRemoteLocal;
    show('modeSectionDivider', showSection);
    show('modeSection', showSection);
    $('modeSectionTitle').textContent = isCloud ? 'Cloud' : 'Remote Local';
    $('modeSectionHint').textContent = isCloud
        ? 'When the local model fails, chat falls back to the cloud endpoint below (secondary endpoint first, remote settings as fallback).'
        : 'When the local model fails, chat falls back to the Ollama host below.';
    show('modeSubCloud', isCloud);
    show('group-secondary-base-url', showSection);
    show('group-secondary-api-key', isCloud);
    show('modeSubRemote', isCloud);
    show('group-remote-base-url', isCloud);
    show('group-remote-api-key', isCloud);
    show('group-remote-model', isCloud);
    $('secondaryModelHint').textContent = isCloud
        ? 'Cloud model used when the local model fails.'
        : isRemoteLocal
            ? 'Model on the remote Ollama host.'
            : 'Second local model, for redundancy or specialized tasks.';
    setLlmsCollapsed(showSection);
}

async function saveMode(mode) {
    const { ok } = await postJson('/api/settings/modes', { mode });
    if (!ok) toast('Could not save the LLM mode.', 'error');
}

async function renderModeSelector() {
    if (!modeOptions) return;
    const { ok, data } = await fetchJson('/api/settings/modes');
    if (!ok) {
        modeOptions.innerHTML = '<p class="llm-status">Failed to load mode configurations.</p>';
        return;
    }
    state.mode = data.current_mode || 'local_local';
    modeOptions.innerHTML = Object.entries(data.modes || {}).map(([key, mode]) => `
        <button type="button" class="mode-switch ${key === state.mode ? 'mode-switch-active' : 'mode-switch-inactive'} mode-switch-${escapeHtml(key)}" data-mode="${escapeHtml(key)}" aria-pressed="${key === state.mode}">
            <span class="mode-switch-label">${escapeHtml(mode.name)}</span>
            <span class="mode-switch-description">${escapeHtml(mode.description)}</span>
        </button>`).join('');
    updateModeUI(state.mode);
}

modeOptions?.addEventListener('click', (e) => {
    const btn = e.target.closest('.mode-switch');
    if (!btn) return;
    state.mode = btn.dataset.mode;
    modeOptions.querySelectorAll('.mode-switch').forEach(s => {
        const active = s === btn;
        s.classList.toggle('mode-switch-active', active);
        s.classList.toggle('mode-switch-inactive', !active);
        s.setAttribute('aria-pressed', String(active));
    });
    updateModeUI(state.mode);
    saveMode(state.mode);
});

/* ── Settings: LLM and MCP status pills ──────────────────────────── */

async function loadLlmStatus() {
    const line = $('llmStatusLine');
    const banner = $('llmBanner');
    const { ok, data: status } = await fetchJson('/api/llm/status');
    if (!ok) {
        setPill(llmStatusPill, 'LLM status unknown', 'warn');
        return;
    }
    let text;
    let level;
    let bannerText = '';
    if (!status.running) {
        text = 'Ollama offline';
        level = 'bad';
        bannerText = 'Ollama is offline — start it with `ollama serve`, then pull a model from Settings → Local Models.';
        if (line) { line.textContent = status.error || 'Ollama is not reachable.'; line.className = 'llm-status status-bad'; }
    } else if (!status.configured_model_installed) {
        text = 'Ollama · model missing';
        level = 'warn';
        bannerText = `Ollama is running, but '${status.configured_model}' is not installed — pull it from Settings → Local Models.`;
        if (line) { line.textContent = bannerText; line.className = 'llm-status status-bad'; }
    } else {
        text = `Ollama · ${status.configured_model}`;
        level = 'ok';
        if (line) { line.textContent = `Ollama is running with ${status.models.length} model(s) installed.`; line.className = 'llm-status status-ok'; }
    }
    setPill(llmStatusPill, text, level);
    if (banner) {
        banner.style.display = bannerText ? 'block' : 'none';
        banner.textContent = bannerText;
    }
    refreshModelBrowser(status);
}

async function loadMcpStatus() {
    const { ok, data: status } = await fetchJson('/api/mcp/status');
    if (!ok) {
        setPill(mcpStatusPill, 'MCP status unknown', 'warn');
        return;
    }
    if (!status.running) setPill(mcpStatusPill, 'MCP offline', 'bad');
    else if (typeof status.count === 'number') setPill(mcpStatusPill, `MCP · ${status.count} server${status.count === 1 ? '' : 's'}`, 'ok');
    else setPill(mcpStatusPill, 'MCP · running', 'ok');
}

/* ── Settings: model browser and pull modal ──────────────────────── */

async function refreshModelBrowser(status) {
    if (!$('modelCatalogGrid') && !$('loadedModelsGrid')) return;
    const [statusRes, catalogRes, settingsRes] = await Promise.all([
        status ? Promise.resolve({ ok: true, data: status }) : fetchJson('/api/llm/status'),
        fetchJson('/api/llm/catalog'),
        fetchJson('/api/settings'),
    ]);
    if (!catalogRes.ok) return;
    const browser = state.models;
    browser.catalog = catalogRes.data;
    browser.installed = statusRes.data.models || [];
    browser.primary = settingsRes.data.llm?.local_model || '';
    browser.secondary = settingsRes.data.llm?.secondary_model || '';
    $('settingsLocalModel').value = browser.primary;
    $('settingsSecondaryModel').value = browser.secondary;
    renderModelBrowser();
}

function loadedModelCard(name, { primary, secondary }) {
    const safe = escapeHtml(name);
    let slot = '';
    if (name === primary) {
        slot = `<span class="mcp-badge mcp-badge-local">Primary</span>
            <button type="button" class="btn-icon" data-action="unset" data-slot="primary" data-model="${safe}" title="Unset primary" aria-label="Unset primary model"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>`;
    } else if (name === secondary) {
        slot = `<span class="mcp-badge mcp-badge-local">Secondary</span>
            <button type="button" class="btn-icon" data-action="unset" data-slot="secondary" data-model="${safe}" title="Unset secondary" aria-label="Unset secondary model"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>`;
    } else if (!(primary && secondary)) {
        slot = `<select data-assign="${safe}" aria-label="Assign model slot">
            <option value="">Assign…</option>
            <option value="primary">Primary</option>
            <option value="secondary">Secondary</option>
        </select>`;
    }
    return `<div class="model-card loaded">
        <div class="model-header">
            <span class="model-name">${safe}</span>
            <span class="mcp-badge status-active">Loaded</span>
        </div>
        <div class="model-actions">
            ${slot}
            <button type="button" class="btn-icon" data-action="unload" data-model="${safe}" title="Unload model" aria-label="Unload model"><i class="fa-solid fa-trash" aria-hidden="true"></i></button>
        </div>
    </div>`;
}

function renderModelBrowser() {
    const { catalog, installed, primary, secondary, filter } = state.models;
    if (!catalog) return;
    const installedSet = new Set(installed);

    const chipsBox = $('modelFilterChips');
    if (chipsBox) {
        const chips = ['all', ...(catalog.capabilities || [])];
        chipsBox.innerHTML = chips.map(c =>
            `<button type="button" class="chip${c === filter ? ' active' : ''}" data-chip="${escapeHtml(c)}">${c === 'all' ? 'All' : escapeHtml(c)}</button>`
        ).join('');
    }

    const loadedGrid = $('loadedModelsGrid');
    if (loadedGrid) {
        loadedGrid.innerHTML = installed.length
            ? installed.map(name => loadedModelCard(name, { primary, secondary })).join('')
            : '<p class="llm-status">Nothing loaded yet — pull a model below.</p>';
    }

    const grid = $('modelCatalogGrid');
    if (grid) {
        const shown = (catalog.models || []).filter(m => filter === 'all' || (m.capabilities || []).includes(filter));
        grid.innerHTML = shown.map(m => {
            const isInstalled = installedSet.has(m.name);
            const safe = escapeHtml(m.name);
            return `<div class="model-card${isInstalled ? ' loaded' : ''}"${isInstalled ? '' : ` data-pull="${safe}"`}>
                <div class="model-header">
                    <span class="model-name">${safe}</span>
                    <span class="model-size">${escapeHtml(m.size_gb)} GB</span>
                    ${m.name === catalog.default_model ? '<span class="mcp-badge mcp-badge-local">Default</span>' : ''}
                    ${isInstalled ? '<span class="mcp-badge status-active">Loaded</span>' : ''}
                </div>
                <div class="model-tags">${(m.capabilities || []).map(c => `<span class="tag">${escapeHtml(c)}</span>`).join('')}</div>
                <div class="model-blurb">${escapeHtml(m.blurb || '')}</div>
                ${isInstalled ? '' : `<button type="button" class="btn-save small" data-pull="${safe}"><i class="fa-solid fa-download" aria-hidden="true"></i> Pull</button>`}
            </div>`;
        }).join('') || '<p class="llm-status">No models match this filter.</p>';
    }

    const note = $('catalogNote');
    if (note) {
        note.textContent = (catalog.size_cap_gb
            ? `Showing models up to ${catalog.size_cap_gb} GB (available RAM: ${catalog.ram_available_gb} GB).` +
              (catalog.hidden_count ? ` ${catalog.hidden_count} larger model(s) hidden.` : '')
            : 'Host RAM size unknown — showing all models.') +
            ` Default model for this host: ${catalog.default_model}.`;
    }
    const linkBox = $('ollamaSearchLink');
    if (linkBox && catalog.ollama_search_url) {
        linkBox.innerHTML = `<a href="${escapeHtml(catalog.ollama_search_url)}" target="_blank" rel="noopener">Browse all models on ollama.com <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></a>`;
    }
}

async function patchLlmSettings(llm) {
    await postJson('/api/settings', { llm });
    await refreshModelBrowser();
    await loadLlmStatus();
}

$('modelFilterChips')?.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    state.models.filter = chip.dataset.chip;
    renderModelBrowser();
});

[$('loadedModelsGrid'), $('modelCatalogGrid')].forEach(grid => grid?.addEventListener('click', async (e) => {
    const unload = e.target.closest('[data-action="unload"]');
    if (unload) {
        const model = unload.dataset.model;
        if (!confirm(`Unload '${model}'? This deletes it from Ollama.`)) return;
        const { ok, data } = await fetchJson(`/api/llm/models/${encodeURIComponent(model)}`, { method: 'DELETE' });
        if (!ok) toast(data.error || 'Could not unload the model.', 'error');
        await refreshModelBrowser();
        await loadLlmStatus();
        return;
    }
    const unset = e.target.closest('[data-action="unset"]');
    if (unset) {
        await patchLlmSettings(unset.dataset.slot === 'primary' ? { local_model: '' } : { secondary_model: '' });
        return;
    }
    const pull = e.target.closest('[data-pull]');
    if (pull && grid === $('modelCatalogGrid')) openPullModal(pull.dataset.pull);
}));

[$('loadedModelsGrid')].forEach(grid => grid?.addEventListener('change', async (e) => {
    const select = e.target.closest('select[data-assign]');
    if (!select || !select.value) return;
    const model = select.dataset.assign;
    const { primary, secondary } = state.models;
    const patch = {};
    if (select.value === 'primary') {
        patch.local_model = model;
        if (secondary === model) patch.secondary_model = '';
    } else {
        patch.secondary_model = model;
        if (primary === model) patch.local_model = '';
    }
    await patchLlmSettings(patch);
}));

let pullPollTimer = null;

function stopPullPolling() {
    if (pullPollTimer) {
        clearInterval(pullPollTimer);
        pullPollTimer = null;
    }
}

async function openPullModal(model) {
    const statusEl = $('pullModalStatus');
    $('pullModalModel').textContent = model;
    statusEl.textContent = 'Starting pull…';
    openModal(pullModal);
    const { ok, data } = await postJson('/api/llm/pull', { model });
    if (!ok) {
        statusEl.textContent = data.error || 'Pull failed to start.';
        return;
    }
    statusEl.textContent = (data.job && data.job.detail) || 'Pulling…';
    stopPullPolling();
    pullPollTimer = setInterval(pollPullModal, 2000);
}

async function pollPullModal() {
    if (!pullModal.classList.contains('active')) {
        stopPullPolling();
        return;
    }
    const { ok, data } = await fetchJson('/api/llm/pull');
    const statusEl = $('pullModalStatus');
    if (!ok) {
        stopPullPolling();
        statusEl.textContent = 'Pull status check failed.';
        return;
    }
    const job = data.job || {};
    statusEl.textContent = job.detail || '';
    if (job.state === 'done' || job.state === 'error') {
        stopPullPolling();
        await refreshModelBrowser();
        await loadLlmStatus();
    }
}

$('pullModalClose')?.addEventListener('click', () => closeModal(pullModal));

/* ── Marketplace shared helpers (Skills and MCPs) ────────────────── */

const categoryOf = (item) => String(item.category || 'other').toLowerCase();

function switchSubTab(tabId, panelId) {
    const root = $(tabId);
    if (!root) return;
    root.querySelectorAll('.sub-tab').forEach(btn => {
        const active = btn.dataset.subtab === panelId;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', String(active));
    });
    root.querySelectorAll('.sub-panel').forEach(panel => panel.classList.toggle('active', panel.id === panelId));
    if (panelId === 'skills-marketplace') loadSkillMarket();
    if (panelId === 'mcps-marketplace') loadMcpMarket();
}

document.querySelectorAll('.sub-tab').forEach(btn => {
    btn.addEventListener('click', () => switchSubTab(btn.closest('.tab-content').id, btn.dataset.subtab));
});

document.querySelectorAll('[data-goto-subtab]').forEach(btn => {
    btn.addEventListener('click', () => switchSubTab(btn.closest('.tab-content').id, btn.dataset.gotoSubtab));
});

function metaHtml(item) {
    const meta = [];
    if (item.author) meta.push(`<span><i class="fa-regular fa-user" aria-hidden="true"></i> ${escapeHtml(item.author)}</span>`);
    if (item.category) meta.push(`<span><i class="fa-solid fa-tag" aria-hidden="true"></i> ${escapeHtml(item.category)}</span>`);
    if (item.stars) meta.push(`<span><i class="fa-solid fa-star" aria-hidden="true"></i> ${escapeHtml(item.stars)}</span>`);
    return meta.length ? `<div class="market-item-meta">${meta.join('')}</div>` : '';
}

function isInstalled(kind, item) {
    if (kind === 'skills') {
        const names = new Set(state.skills.installed.map(s => s.name.toLowerCase()));
        return names.has(String(item.name || '').toLowerCase());
    }
    const installed = state.mcps.installed;
    return installed.some(m => m.id === item.id || String(m.name).toLowerCase() === String(item.name || '').toLowerCase());
}

function marketItemHtml(kind, item) {
    const id = item.id || item.name;
    const installed = isInstalled(kind, item);
    const cardClass = kind === 'mcps' ? 'market-item mcp-card' : 'market-item skill-card';
    const label = installed ? 'Installed' : (kind === 'mcps' && item.requires_auth) ? 'Install (Auth)' : 'Install';
    const icon = installed ? 'fa-check' : 'fa-download';
    const safeId = escapeHtml(id);

    let authBadge = '';
    if (kind === 'mcps') {
        authBadge = item.requires_auth
            ? `<span class="auth-warning-tag" title="${escapeHtml(item.auth_note || 'Requires credentials')}"><i class="fa-solid fa-key" aria-hidden="true"></i> Auth Required</span>`
            : `<span class="auth-tag-none"><i class="fa-solid fa-circle-check" aria-hidden="true"></i> No Auth</span>`;
    }

    return `
    <article class="${cardClass}${installed ? ' is-installed' : ''}" data-mcp-id="${safeId}">
        <div class="market-item-body">
            <h4 class="market-item-title">${escapeHtml(item.name)} ${authBadge}</h4>
            <p class="market-item-desc">${escapeHtml(item.description || '')}</p>
            ${metaHtml(item)}
        </div>
        <div class="item-actions">
            ${item.source_url ? `<button type="button" class="icon-action" data-market-action="view" data-market-kind="${kind}" data-market-id="${safeId}" title="Open source" aria-label="Open ${escapeHtml(item.name)} source"><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button>` : ''}
            <button type="button" class="icon-action${installed ? ' done' : ''}" data-market-action="install" data-skill-install="${safeId}" data-market-kind="${kind}" data-market-id="${safeId}" title="${label}" aria-label="${label} ${escapeHtml(item.name)}"${installed ? ' disabled' : ''}><i class="fa-solid ${icon}" aria-hidden="true"></i></button>
        </div>
    </article>`;
}

function renderMarket(kind) {
    const cfg = MARKET[kind];
    const store = state[kind];
    const list = $(cfg.list);
    if (!list) return;
    const query = ($(cfg.search)?.value || '').trim().toLowerCase();

    const counts = {};
    if (kind === 'mcps') {
        const authCount = store.market.filter(i => i.requires_auth).length;
        const noAuthCount = store.market.filter(i => !i.requires_auth).length;
        if (authCount > 0) counts['auth required'] = authCount;
        if (noAuthCount > 0) counts['no auth'] = noAuthCount;
    }
    store.market.forEach(item => {
        const cat = categoryOf(item);
        counts[cat] = (counts[cat] || 0) + 1;
    });
    const chips = $(cfg.chips);
    if (chips) {
        chips.innerHTML = Object.keys(counts).sort().map(cat =>
            `<button type="button" class="chip${store.filter === cat ? ' active' : ''}" data-market-chip="${escapeHtml(cat)}" aria-pressed="${store.filter === cat}">${escapeHtml(cat)} <span class="chip-count">${counts[cat]}</span></button>`
        ).join('');
    }

    const matchesFilter = (item) => {
        if (store.filter === 'all') return true;
        if (kind === 'mcps') {
            if (store.filter === 'auth required') return !!item.requires_auth;
            if (store.filter === 'no auth') return !item.requires_auth;
        }
        return categoryOf(item) === store.filter;
    };

    const shown = store.market.filter(item =>
        matchesFilter(item) &&
        (!query || `${item.name} ${item.description || ''} ${item.author || ''} ${item.category || ''}`.toLowerCase().includes(query)));
    list.innerHTML = shown.length
        ? shown.map(item => marketItemHtml(kind, item)).join('')
        : `<p class="list-empty">${store.market.length ? 'No matches.' : 'Nothing to show yet.'}</p>`;

    const note = $(cfg.note);
    if (note) note.textContent = store.market.length ? `${shown.length} of ${store.market.length} shown` : '';
}

function bindMarket(kind, onInstall, onView) {
    const cfg = MARKET[kind];
    $(cfg.search)?.addEventListener('input', debounce(() => renderMarket(kind), 150));
    $(cfg.chips)?.addEventListener('click', (e) => {
        const chip = e.target.closest('[data-market-chip]');
        if (!chip) return;
        const store = state[kind];
        store.filter = store.filter === chip.dataset.marketChip ? 'all' : chip.dataset.marketChip;
        renderMarket(kind);
    });
    $(cfg.list)?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-market-action]');
        if (!btn || btn.disabled) return;
        const item = state[kind].market.find(i => String(i.id || i.name) === btn.dataset.marketId);
        if (!item) return;
        if (btn.dataset.marketAction === 'view') onView(item);
        else onInstall(item, btn);
    });
}

function openExternal(url) {
    if (/^https?:\/\//i.test(url || '')) window.open(url, '_blank', 'noopener');
}

function withBusyButton(btn, fn) {
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i>';
    return Promise.resolve(fn()).finally(() => {
        if (btn.isConnected) {
            btn.disabled = false;
            btn.innerHTML = original;
        }
    });
}

/* ── Skills ──────────────────────────────────────────────────────── */

function installedSkillHtml(skill) {
    const badge = { discovered: ['Discovered', 'local'], saved: ['Saved', 'saved'], env: ['Env', 'env'] }[skill.kind];
    const id = escapeHtml(skill.id);
    const control = skill.kind === 'discovered'
        ? `<button type="button" class="switch${skill.active ? ' on' : ''}" role="switch" aria-checked="${skill.active}" data-skill-action="toggle" data-skill-id="${id}" aria-label="${skill.active ? 'Disable' : 'Enable'} ${escapeHtml(skill.name)}" title="${skill.active ? 'Disable' : 'Enable'}"></button>`
        : '';
    const removable = skill.kind !== 'discovered'
        ? `<button type="button" class="icon-action danger" data-skill-action="remove" data-skill-kind="${skill.kind}" data-skill-id="${id}" title="Remove" aria-label="Remove ${escapeHtml(skill.name)}"><i class="fa-solid fa-trash" aria-hidden="true"></i></button>`
        : '';
    return `
    <article class="market-item installed${skill.active ? '' : ' is-disabled'}">
        <div class="market-item-body">
            <h4 class="market-item-title">${escapeHtml(skill.name)} <span class="skill-badge skill-badge-${badge[1]}">${badge[0]}</span></h4>
            <p class="market-item-desc">${escapeHtml(skill.description || '')}</p>
        </div>
        <div class="item-actions">${control}${removable}</div>
    </article>`;
}

function updateSkillsPill() {
    const active = state.skills.installed.filter(s => s.active).length;
    setPill(skillsPill, `Skills · ${active}`, 'ok');
}

function renderInstalledSkills() {
    const list = $('skillList');
    if (!list) return;
    const query = ($('skillInstalledSearch')?.value || '').trim().toLowerCase();
    const all = state.skills.installed;
    const shown = all.filter(s => !query || `${s.name} ${s.description}`.toLowerCase().includes(query));
    list.innerHTML = shown.length
        ? shown.map(installedSkillHtml).join('')
        : `<p class="list-empty">${all.length ? 'No matches.' : 'No skills installed'}</p>`;
    const active = all.filter(s => s.active).length;
    setStatus($('skillsGridNote'), all.length ? `${all.length} skill(s) · ${active} active` : '', all.length ? true : undefined);
    updateSkillsPill();
}

async function loadInstalledSkills() {
    const [discovered, saved, env] = await Promise.all([
        fetchJson('/api/skills/active'),
        fetchJson('/api/skills'),
        fetchJson('/api/env/vars?prefix=SKILL_'),
    ]);
    state.skills.installed = [
        ...(discovered.data.skills || []).map(s => ({
            kind: 'discovered', id: s.id || s.name, name: s.name || '', description: s.description || '', active: s.active !== false,
        })),
        ...(saved.data.skills || []).map(s => ({
            kind: 'saved', id: s.id, name: s.name || '', description: s.description || '', active: true,
        })),
        ...Object.entries(env.data.vars || {}).map(([key, value]) => ({
            kind: 'env', id: key, name: key.replace(/^SKILL_/, '').replace(/_/g, ' '), description: String(value), active: true,
        })),
    ];
    renderInstalledSkills();
    if (state.skills.marketLoaded) renderMarket('skills');
}

async function loadSkillMarket() {
    if (state.skills.marketLoaded) return;
    $('skillMarketList').innerHTML = '<p class="list-empty"><i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> Loading…</p>';
    const { ok, data } = await fetchJson('/api/skills/leaderboard');
    if (!ok) {
        $('skillMarketList').innerHTML = '<p class="list-empty">Could not load the marketplace.</p>';
        return;
    }
    state.skills.market = data.skills || [];
    state.skills.marketMeta = data;
    state.skills.marketLoaded = true;
    const link = $('skillMarketLink');
    if (link && /^https?:\/\//i.test(data.source_url || '')) {
        link.href = data.source_url;
        link.hidden = false;
    }
    renderMarket('skills');
}

async function installMarketSkill(item, btn) {
    await withBusyButton(btn, async () => {
        const { ok, data } = await postJson('/api/skills', {
            name: item.name,
            description: item.description || '',
            skills: [],
            abilities: [],
            system_prompt: '',
        });
        if (!ok) {
            toast(`Install failed: ${data.error || 'server error'}`, 'error');
            return;
        }
        toast(`'${item.name}' installed.`, 'success');
        await loadInstalledSkills();
        await loadSkillsForNewBot();
    });
}

bindMarket('skills', installMarketSkill, (item) => openExternal(item.source_url));

$('skillInstalledSearch')?.addEventListener('input', debounce(renderInstalledSkills, 150));

$('skillList')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-skill-action]');
    if (!btn) return;
    const id = btn.dataset.skillId;
    if (btn.dataset.skillAction === 'toggle') {
        const { ok, data } = await postJson(`/api/skills/toggle/${encodeURIComponent(id)}`);
        if (!ok) toast(data.error || 'Could not change the skill.', 'error');
    } else {
        if (!confirm('Remove this skill?')) return;
        const kind = btn.dataset.skillKind;
        const result = kind === 'env'
            ? await postJson(`/api/env/disable/${encodeURIComponent(id)}`)
            : await fetchJson(`/api/skills/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!result.ok) toast(result.data.error || 'Could not remove the skill.', 'error');
        else await loadSkillsForNewBot();
    }
    await loadInstalledSkills();
});

$('skillCreateBtn')?.addEventListener('click', () => {
    $('skillForm').reset();
    openModal(skillModal);
});

$('skillForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const split = (value) => value.split(',').map(s => s.trim()).filter(Boolean);
    const { ok, data } = await postJson('/api/skills', {
        name: $('skillName').value,
        description: $('skillDescription').value,
        skills: split($('skillSkills').value),
        abilities: split($('skillAbilities').value),
        system_prompt: $('skillSystemPrompt').value,
    });
    if (!ok) {
        toast(data.error || 'Could not save the skill.', 'error');
        return;
    }
    closeModal(skillModal);
    toast('Skill saved.', 'success');
    await loadInstalledSkills();
    await loadSkillsForNewBot();
});

$('skillsSyncToggleBtn')?.addEventListener('click', () => {
    const row = $('skillsGitRow');
    row.hidden = !row.hidden;
    if (!row.hidden) $('settingsSkillsGitUrl').focus();
});

$('skillsSyncBtn')?.addEventListener('click', async () => {
    const statusEl = $('skillsSyncStatus');
    const gitUrl = $('settingsSkillsGitUrl').value.trim();
    const btn = $('skillsSyncBtn');
    btn.disabled = true;
    setStatus(statusEl, 'Saving repo and syncing…');
    const saved = await postJson('/api/settings', { skills: { git_url: gitUrl } });
    const synced = saved.ok ? await postJson('/api/skills/refresh') : saved;
    btn.disabled = false;
    if (!synced.ok) {
        setStatus(statusEl, `Sync failed: ${synced.data.error || 'server error'}`, false);
        return;
    }
    setStatus(statusEl, `Synced — ${(synced.data.skills || []).length} skill(s) discovered.`, true);
    await loadInstalledSkills();
    await loadSkillsForNewBot();
});

/* ── MCP servers ─────────────────────────────────────────────────── */

function installedMcpHtml(mcp) {
    const enabled = mcp.enabled !== false;
    const id = escapeHtml(mcp.id);
    return `
    <article class="market-item installed${enabled ? '' : ' is-disabled'}">
        <div class="market-item-body">
            <h4 class="market-item-title"><span class="status-dot ${enabled ? 'on' : 'off'}" aria-hidden="true"></span>${escapeHtml(mcp.name || mcp.id)}</h4>
            <p class="market-item-desc">${escapeHtml(mcp.description || '')}</p>
            <div class="market-item-meta">
                ${mcp.endpoint ? `<span><i class="fa-solid fa-link" aria-hidden="true"></i> ${escapeHtml(mcp.endpoint)}</span>` : ''}
                ${mcp.method ? `<span>${escapeHtml(mcp.method)}</span>` : ''}
            </div>
        </div>
        <div class="item-actions">
            <button type="button" class="switch${enabled ? ' on' : ''}" role="switch" aria-checked="${enabled}" data-mcp-action="${enabled ? 'disable' : 'enable'}" data-mcp-id="${id}" aria-label="${enabled ? 'Disable' : 'Enable'} ${escapeHtml(mcp.name || mcp.id)}" title="${enabled ? 'Disable' : 'Enable'}"></button>
            <button type="button" class="icon-action danger" data-mcp-action="remove" data-mcp-id="${id}" title="Remove" aria-label="Remove ${escapeHtml(mcp.name || mcp.id)}"><i class="fa-solid fa-trash" aria-hidden="true"></i></button>
        </div>
    </article>`;
}

function renderInstalledMcps() {
    const list = $('mcpList');
    if (!list) return;
    const query = ($('mcpInstalledSearch')?.value || '').trim().toLowerCase();
    const all = state.mcps.installed;
    const shown = all.filter(m => !query || `${m.name} ${m.description || ''} ${m.endpoint || ''}`.toLowerCase().includes(query));
    list.innerHTML = shown.length
        ? shown.map(installedMcpHtml).join('')
        : `<p class="list-empty">${all.length ? 'No matches.' : 'No MCP servers installed'}</p>`;
}

async function loadInstalledMcps() {
    const { ok, data } = await fetchJson('/api/mcp/local');
    if (!ok) {
        $('mcpList').innerHTML = `<p class="list-empty">${escapeHtml(data.error || 'MCP service unreachable.')}</p>`;
        return;
    }
    state.mcps.installed = data.mcps || [];
    renderInstalledMcps();
    if (state.mcps.marketLoaded) renderMarket('mcps');
}

async function loadMcpMarket() {
    if (state.mcps.marketLoaded) return;
    $('mcpMarketList').innerHTML = '<p class="list-empty"><i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> Loading…</p>';
    const { ok, data } = await fetchJson('/api/mcp/remote');
    if (!ok) {
        $('mcpMarketList').innerHTML = '<p class="list-empty">Could not load the marketplace.</p>';
        return;
    }
    state.mcps.market = data.mcps || [];
    state.mcps.marketLoaded = true;
    renderMarket('mcps');
}

function setMcpAddOpen(open) {
    const body = $('mcpAddBody');
    if (!body) return;
    body.hidden = !open;
    $('mcpAddToggleBtn')?.setAttribute('aria-expanded', String(open));
}

function prefillMcpForm(entry) {
    $('mcpName').value = entry.name || '';
    $('mcpDescription').value = entry.description || '';
    $('mcpEndpoint').value = entry.endpoint || '';
    $('mcpMethod').value = entry.method || 'GET';
    setStatus($('mcpAddStatus'), entry.endpoint
        ? `'${entry.name}' ready — press Add Server to register it.`
        : `'${entry.name}' has no endpoint in the catalogue — enter its URL to continue.`);
    setMcpAddOpen(true);
    $('mcpEndpoint').focus();
}

function promptMcpAuth(item) {
    return new Promise((resolve) => {
        const modal = $('mcpAuthModal');
        if (!modal) {
            const key = window.prompt(`Enter API Key / Token for ${item.name}:`);
            resolve(key ? key.trim() : null);
            return;
        }
        const title = $('mcpAuthModalTitle');
        const desc = $('mcpAuthModalDesc');
        const idInput = $('mcpAuthServerId');
        const keyInput = $('mcpAuthKey');
        if (title) title.textContent = `Credentials for ${item.name}`;
        if (desc) desc.textContent = item.auth_note || 'This server requires an API key or token to authenticate.';
        if (idInput) idInput.value = item.id;
        if (keyInput) {
            keyInput.value = '';
            keyInput.placeholder = 'Enter API key or token';
        }
        openModal(modal);
        if (keyInput) keyInput.focus();

        const form = $('mcpAuthForm');
        const cancel = $('mcpAuthCancelBtn');
        const onSubmit = (e) => {
            e.preventDefault();
            cleanup();
            closeModal(modal);
            resolve(keyInput ? keyInput.value.trim() : '');
        };
        const onCancel = () => {
            cleanup();
            closeModal(modal);
            resolve(null);
        };
        const cleanup = () => {
            form?.removeEventListener('submit', onSubmit);
            cancel?.removeEventListener('click', onCancel);
        };
        form?.addEventListener('submit', onSubmit);
        cancel?.addEventListener('click', onCancel);
    });
}

// Auto-resolving endpoint requirements automatically
// One-click MCP installs, only asking for credentials when a server truly needs them
async function installMarketMcp(item, btn) {
    const authPayload = {};
    if (item.requires_auth) {
        const key = await promptMcpAuth(item);
        if (key === null) return; // User cancelled
        if (key) authPayload.auth_token = key;
    }

    await withBusyButton(btn, async () => {
        btn.textContent = 'Importing'; // Mobile import loading indicator
        // Resolving endpoint and importing remote MCP server
        const { ok, data } = await postJson(`/api/mcp/import/${encodeURIComponent(item.id)}`, authPayload);
        if (!ok) {
            toast(data.error || 'Import failed.', 'error');
            return;
        }
        toast(`'${item.name}' added to your MCP servers (one-click install).`, 'success');
        await loadInstalledMcps();
        loadMcpStatus();
    });
}

bindMarket('mcps', installMarketMcp, (item) => openExternal(item.source_url));

$('mcpInstalledSearch')?.addEventListener('input', debounce(renderInstalledMcps, 150));

$('mcpList')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-mcp-action]');
    if (!btn) return;
    const id = btn.dataset.mcpId;
    const action = btn.dataset.mcpAction;
    let result;
    if (action === 'remove') {
        if (!confirm('Remove this MCP server?')) return;
        result = await fetchJson(`/api/mcps/${encodeURIComponent(id)}`, { method: 'DELETE' });
    } else {
        result = await postJson(`/api/mcp/${action}/${encodeURIComponent(id)}`);
    }
    if (!result.ok) toast(result.data.error || 'MCP update failed.', 'error');
    await loadInstalledMcps();
    loadMcpStatus();
});

$('mcpAddToggleBtn')?.addEventListener('click', () => {
    const open = $('mcpAddBody').hidden;
    setMcpAddOpen(open);
    if (open) $('mcpName').focus();
});

$('mcpRefreshBtn')?.addEventListener('click', async () => {
    await loadInstalledMcps();
    await loadMcpStatus();
});

// UI sync function with Smithery & Official Registry for MCPs
$('mcpSyncBtn')?.addEventListener('click', async () => {
    const btn = $('mcpSyncBtn');
    await withBusyButton(btn, async () => {
        toast('Syncing MCP registry with Smithery & Official Registry…', 'info');
        const { ok, data } = await postJson('/api/mcp/sync');
        state.mcps.marketLoaded = false;
        await loadMcpMarket();
        if (ok) toast(`MCP Marketplace synced (${data.count || 0} servers).`, 'success');
        else toast('MCP Marketplace sync completed from cache.', 'info');
    });
});

// UI sync function with Smithery for Skills
$('skillSyncBtn')?.addEventListener('click', async () => {
    const btn = $('skillSyncBtn');
    await withBusyButton(btn, async () => {
        toast('Syncing Skills with Smithery…', 'info');
        const { ok, data } = await postJson('/api/skills/sync');
        state.skills.marketLoaded = false;
        await loadSkillMarket();
        if (ok) toast(`Skills Marketplace synced (${data.count || 0} skills).`, 'success');
        else toast('Skills Marketplace sync completed from cache.', 'info');
    });
});

$('mcpAddBtn')?.addEventListener('click', async () => {
    const statusEl = $('mcpAddStatus');
    const name = $('mcpName').value.trim();
    const endpoint = $('mcpEndpoint').value.trim();
    if (!name || !endpoint) {
        setStatus(statusEl, 'Name and endpoint URL are required.', false);
        return;
    }
    if (!/^https?:\/\//i.test(endpoint)) {
        setStatus(statusEl, 'Endpoint must start with http:// or https://', false);
        return;
    }
    const { ok, data } = await postJson('/api/mcps', {
        name,
        description: $('mcpDescription').value.trim(),
        endpoint,
        method: $('mcpMethod').value,
    });
    if (!ok) {
        setStatus(statusEl, `Add failed: ${data.error || 'server error'}`, false);
        return;
    }
    ['mcpName', 'mcpDescription', 'mcpEndpoint'].forEach(id => { $(id).value = ''; });
    setStatus(statusEl, '');
    setMcpAddOpen(false);
    toast(`'${name}' added to your MCP servers.`, 'success');
    await loadInstalledMcps();
    loadMcpStatus();
});

/* ── Global handlers ─────────────────────────────────────────────── */

document.querySelectorAll('.close-modal').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.closest('.modal')));
    makeKeyboardClickable(btn, () => closeModal(btn.closest('.modal')));
});

window.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) closeModal(e.target);
});

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const open = [...document.querySelectorAll('.modal.active')];
    if (open.length) {
        closeModal(open[open.length - 1]);
        return;
    }
    toggleSidebar(false);
});

window.addEventListener('resize', debounce(() => {
    if (!isMobile()) {
        toggleSidebar(false);
        restorePills();
    }
}, 150));

/* ── Init ────────────────────────────────────────────────────────── */

async function init() {
    await Promise.all([loadBots(), loadSkillsForNewBot(), loadSettings()]);
    renderModeSelector();
    loadInstalledSkills();
    loadInstalledMcps();
    toggleSidebar(false);
}

init();

// Helper notes: endpoint not found in catalogue, Resolving, Import, Use, Importing, Installing
