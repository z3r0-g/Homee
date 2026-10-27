// Bot UI Application Logic

const API_BASE = '';
let globalBots = [];
let currentBotId = null;
let currentSettings = null;
let chatModelChoice = 'fast'; // 'fast' (primary) | 'smart' (secondary)
let attachedFile = null; // { name, content } for the open chat view only
const botBusy = {}; // botId -> in-flight op count

function formatElapsed(ms) {
    const totalSeconds = Math.max(0, Math.round(ms / 1000));
    if (totalSeconds < 60) {
        return `${totalSeconds}s`;
    }
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}m ${seconds}s`;
}

// DOM Elements
const botList = document.getElementById('botList');
const chatArea = document.getElementById('chatArea');
const newBotBtn = document.getElementById('newBotBtn');
const settingsBtn = document.getElementById('settingsBtn');
const personalityModal = document.getElementById('personalityModal');
const settingsModal = document.getElementById('settingsModal');
const newBotModal = document.getElementById('newBotModal');
const closeModalBtns = document.querySelectorAll('.close-modal');
const personalityForm = document.getElementById('personalityForm');
const newBotForm = document.getElementById('newBotForm');
const settingsForm = document.getElementById('settingsForm');
const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');
const modeOptions = document.getElementById('modeOptions');
const settings_llmMode = document.querySelector('input[name="llmMode"]');

// Initialize
async function init() {
    await loadBots();
    await loadPersonalitiesForNewBot();
    await loadSettings();
    setupTabNavigation();
    renderModeSelector();
    await initMCPAndPersonalities();
}

// Load bots from API
async function loadBots() {
    try {
        const response = await fetch(`${API_BASE}/api/bots`);
        const data = await response.json();
        globalBots = data.bots || data || [];
        renderBotList(globalBots);
    } catch (e) {
        console.warn('Failed to load bots', e);
        botList.innerHTML = '<p class="empty" style="padding: 20px;">Failed to load bots.</p>';
    }
}

// Render bot list
function renderBotList(bots) {
    if (bots.length === 0) {
        botList.innerHTML = '<p class="empty" style="padding: 20px;">No bots yet. Create a new bot to get started.</p>';
        chatArea.innerHTML = '<div class="empty">Start by creating a new bot</div>';
        return;
    }
    botList.innerHTML = bots.map(bot => `
        <div class="bot-item${botBusy[bot.id] ? ' working' : ''}" data-testid="bot-item" data-bot-id="${bot.id}" data-bot-name="${bot.name}">
            <span style="font-weight: 500;">${bot.name}</span>
            <span class="bot-status">${botBusy[bot.id] ? 'working' : bot.status}</span>
        </div>
    `).join('');

    document.querySelectorAll('.bot-item').forEach(item => {
        item.addEventListener('click', () => openBotChat(item.dataset.botId));
    });
}


// Per-bot working state: a bot with an in-flight chat or task shows
// "working" in the sidebar until its op settles, even while the user
// chats with another bot. Server status is never rewritten: this is
// purely the session's view of what it started, so a stale "working"
// can never survive a reload. renderBotList re-applies it on refresh.
function setBotBusy(botId, busy) {
    botBusy[botId] = Math.max(0, (botBusy[botId] || 0) + (busy ? 1 : -1));
    const item = document.querySelector(`.bot-item[data-bot-id="${botId}"]`);
    if (!item) return;
    const statusEl = item.querySelector('.bot-status');
    const bot = globalBots.find(b => b.id === botId);
    item.classList.toggle('working', !!botBusy[botId]);
    if (statusEl) statusEl.textContent = botBusy[botId] ? 'working' : (bot ? bot.status : 'idle');
}

// Personality label for the bot-info bar: prefer the saved-personality
// name from the new-bot dropdown; agent-direct ids (short names) show
// in full, long uuid-like ids fall back to the old 8-char prefix.
function resolvePersonalityName(personalityId) {
    if (!personalityId) return 'none';
    const select = document.getElementById('newBotPersonality');
    if (select) {
        const opt = [...select.options].find(o => o.value === personalityId);
        if (opt && opt.text !== '(none)') return opt.text;
    }
    return personalityId.length > 20 ? personalityId.substring(0, 8) : personalityId;
}

function scheduleLabel(cfg) {
    if (!cfg) return 'No schedule';
    if (cfg.schedule_type === 'interval') return `Every ${cfg.interval_seconds || 3600}s`;
    if (cfg.schedule_type === 'cron') return `Cron ${cfg.cron_expression || ''}`.trim();
    return 'No schedule';
}

// Shared by openBotChat and background-task completion: re-rendering a
// bot's history from the server is what makes a finished background
// reply appear without another click.
function renderChatHistory(history, historyDiv) {
    historyDiv.innerHTML = '';
    history.forEach((msg, idx) => {
        const msgDiv = document.createElement('div');
        const isUser = msg.role === 'user';
        msgDiv.className = `message ${isUser ? 'message-user' : 'bot'}`;

        const timeLabel = msg.timestamp ? ` <span class="message-time">${new Date(msg.timestamp).toLocaleTimeString()}</span>` : '';
        let elapsedLabel = '';
        if (!isUser && idx > 0 && history[idx - 1].role === 'user' && history[idx - 1].timestamp && msg.timestamp) {
            const ms = new Date(msg.timestamp) - new Date(history[idx - 1].timestamp);
            elapsedLabel = ` <span class="message-time">⏱ ${formatElapsed(ms)}</span>`;
        }

        msgDiv.innerHTML = `
            <div class="message-label">${isUser ? 'You' : 'Bot'}</div>
            <div class="message-content">${isUser ? escapeHtml(msg.content) : formatAssistantMessage(msg.content)}</div>
            <div>${timeLabel}${elapsedLabel}</div>
        `;
        historyDiv.appendChild(msgDiv);
    });
}

function appendWorkingRow(historyDiv) {
    const row = document.createElement('div');
    row.className = 'message bot';
    row.innerHTML = `
        <div class="message-label">Bot</div>
        <div class="message-content">Working…</div>
    `;
    historyDiv.appendChild(row);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

// Empty-chat suggestions: at most two chips, no config UI. The bot's
// task prompt (if it has one) plus a capabilities question.
function appendStarterPrompts(bot) {
    const chips = [];
    const taskPrompt = (bot.config && bot.config.task_prompt) || '';
    if (taskPrompt) chips.push(taskPrompt);
    chips.push('What can you do?');
    const wrap = document.createElement('div');
    wrap.className = 'starter-prompts';
    wrap.innerHTML = chips.map(text => `<button type="button" class="starter-chip" title="${escapeHtml(text)}">${escapeHtml(text.length > 48 ? text.substring(0, 48) + '…' : text)}</button>`).join('');
    wrap.querySelectorAll('.starter-chip').forEach((btn, i) => {
        btn.addEventListener('click', () => sendMessageText(bot.id, chips[i]));
    });
    chatArea.appendChild(wrap);
}

async function refreshChatHistory(botId) {
    if (currentBotId !== botId) return;
    const historyDiv = document.getElementById('chatHistory');
    if (!historyDiv) return;
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}`);
        if (!response.ok) return;
        const bot = await response.json();
        renderChatHistory(bot.conversation_history || [], historyDiv);
        if (botBusy[botId]) appendWorkingRow(historyDiv);
        const gbot = globalBots.find(b => b.id === botId);
        if (gbot) gbot.conversation_history = bot.conversation_history;
    } catch (e) {
        console.warn('Failed to refresh chat history', e);
    }
}

function reenableComposer() {
    const composer = document.querySelector('.chat-composer');
    if (!composer) return;
    const send = composer.querySelector('.btn-save');
    if (send) send.disabled = false;
    const runBtn = document.getElementById('runTaskBtn');
    if (runBtn) runBtn.disabled = false;
    const input = document.getElementById('userMessage');
    if (input) input.disabled = false;
}

// Fast sends no model (server default = primary). Smart sends the
// configured secondary model name; without one the Smart button is
// disabled at render, so this never fires unconfigured.
function chatModelForSend() {
    const llm = (currentSettings && currentSettings.llm) || {};
    if (chatModelChoice === 'smart' && llm.secondary_model) return llm.secondary_model;
    return null;
}

// Shared settle path for chat sends: clear the timer + busy flag,
// re-enable the live composer, refresh the history if the user came
// back to this bot mid-run (their thinking row is detached by then),
// then refresh the sidebar so "working" clears.
async function settleSend(botId, thinkingDiv, input, timer) {
    clearInterval(timer);
    setBotBusy(botId, false);
    if (input && input.isConnected) {
        input.disabled = false;
        input.focus();
    }
    if (currentBotId === botId) {
        reenableComposer();
        if (!thinkingDiv.isConnected) await refreshChatHistory(botId);
    }
    await loadBots();
}

// Load personalities for the new-bot dropdown
async function loadPersonalitiesForNewBot() {
    try {
        const response = await fetch(`${API_BASE}/api/agents/available-personalities`);
        if (!response.ok) {
            throw new Error('Server responded with ' + response.status);
        }
        const data = await response.json();
        const select = document.getElementById('newBotPersonality');
        if (select) {
            select.innerHTML = '<option value="">(none)</option>' +
                (data.personalities || []).map(p =>
                    `<option value="${p.id}">${p.name}</option>`
                ).join('');
            const editSelect = document.getElementById('editBotPersonality');
            if (editSelect) editSelect.innerHTML = select.innerHTML;
        }
    } catch (e) {
        console.warn('Failed to load available personalities', e);
        const select = document.getElementById('newBotPersonality');
        if (select) {
            select.innerHTML = '<option value="">(none)</option>' +
                '<option value="demo">Demo Mode</option>' +
                '<option value="general">General</option>';
            const editSelect = document.getElementById('editBotPersonality');
            if (editSelect) editSelect.innerHTML = select.innerHTML;
        }
    }
}

// Disable bot API
async function disableBot(botId) {
    if (!confirm('Are you sure you want to disable this bot?')) return;
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: false })
        });
        if (response.ok) {
            const bot = globalBots.find(b => b.id === botId);
            if (bot) {
                bot.config.enabled = false;
                openBotChat(botId);
            }
        } else {
            console.warn('Failed to disable bot', response);
        }
    } catch (e) {
        console.warn('Error disabling bot', e);
    }
}

// Delete bot API (only when bot is disabled)
async function deleteBot(botId) {
    if (!confirm('Are you sure you want to delete this bot? This action cannot be undone.')) return;
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            const botItem = document.querySelector(`[data-bot-id="${botId}"]`);
            if (botItem) botItem.remove();
            if (document.getElementById('chatArea').children[0]?.className === 'bot-info' && 
                document.getElementById('chatArea').children[0].getAttribute('data-bot-id') === botId) {
                chatArea.innerHTML = '';
                currentBotId = null;
            }
        } else {
            console.warn('Failed to delete bot', response);
        }
    } catch (e) {
        console.warn('Error deleting bot', e);
    }
}

// Enable bot API
async function enableBot(botId) {
    if (!confirm('Are you sure you want to enable this bot?')) return;
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: true })
        });
        if (response.ok) {
            const bot = globalBots.find(b => b.id === botId);
            if (bot) {
                bot.config.enabled = true;
                openBotChat(botId); // Re-open chat to show Disable button
            }
        } else {
            console.warn('Failed to enable bot', response);
        }
    } catch (e) {
        console.warn('Error enabling bot', e);
    }
}

// Open bot chat
async function openBotChat(botId) {
    const bot = globalBots.find(b => b.id === botId);
    if (!bot) return;
    currentBotId = botId;
    attachedFile = null;

    // Display name: add "Bot" suffix unless name already ends in "Bot" or "bot"
    const name = bot.name;
    const displayName = name.match(/bot$/i) ? name : `${name} Bot`;
    const chatStatus = document.querySelector('.chat-status');
    if (chatStatus) chatStatus.textContent = displayName;
    // The sidebar already styles .bot-item.active — mark the open bot.
    document.querySelectorAll('.bot-item').forEach(item => {
        item.classList.toggle('active', item.dataset.botId === botId);
    });

    // Fetch server health
    let healthHtml = "";
    try {
        const healthResponse = await fetch(`${API_BASE}/api/server-health`);
        if (healthResponse.ok) {
            const health = await healthResponse.json();
            const disk = health.disk;
            const memory = health.memory;
            const cpu = health.cpu;
            healthHtml = `
                <div class="bot-health-small">
                    <strong>Server Health:</strong><br>
                    Disk: ${disk.free_gb}GB free of ${disk.total_gb}GB (${disk.usage_percent}% used)<br>
                    Memory: ${memory.free_gb}GB free of ${memory.total_gb}GB (${memory.usage_percent}% used)<br>
                    CPU: ${cpu.percent}%
                </div>
            `;
        }
    } catch (e) {
        console.warn('Failed to load server health', e);
    }

    chatArea.innerHTML = '';

    const infoDiv = document.createElement('div');
    infoDiv.className = 'bot-info';
    infoDiv.dataset.botId = bot.id;
    const cfg = bot.config || {};
    const barActions = cfg.enabled
        ? `<button type="button" class="btn-secondary small" data-bot-action="edit" data-bot-id="${bot.id}">Edit</button> <button type="button" class="btn-secondary small" data-bot-action="disable" data-bot-id="${bot.id}">Disable</button>`
        : `<button type="button" class="btn-secondary small" data-bot-action="delete" data-bot-id="${bot.id}">Delete</button> <button type="button" class="btn-secondary small" data-bot-action="enable" data-bot-id="${bot.id}">Re-enable</button>`;
    infoDiv.innerHTML = `<span class="bot-meta">Skill: ${escapeHtml(resolvePersonalityName(bot.personality_id))} · Schedule: ${escapeHtml(scheduleLabel(cfg))} · Last run: ${escapeHtml(cfg.last_run ? new Date(cfg.last_run).toLocaleString() : 'never')} · Runs: ${cfg.run_count || 0}</span>${healthHtml} <div class="bot-actions">${barActions}</div>`;
    chatArea.appendChild(infoDiv);

    const historyDiv = document.createElement('div');
    historyDiv.id = 'chatHistory';
    historyDiv.className = 'chat-history';
    chatArea.appendChild(historyDiv);

    renderChatHistory(bot.conversation_history || [], historyDiv);
    if (botBusy[botId]) appendWorkingRow(historyDiv);
    if (!(bot.conversation_history || []).length) appendStarterPrompts(bot);

    const formDiv = document.createElement('div');
    formDiv.className = 'chat-composer';
    const llm = (currentSettings && currentSettings.llm) || {};
    const smartAvailable = !!llm.secondary_model;
    const switchHtml = llm.local_model ? `<div class="model-switch" role="group" aria-label="Model">
        <button type="button" data-model-choice="fast" class="${chatModelChoice === 'fast' ? 'active' : ''}">Fast</button>
        <button type="button" data-model-choice="smart" class="${chatModelChoice === 'smart' ? 'active' : ''}"${smartAvailable ? '' : ' disabled title="Set a secondary model in Settings to enable Smart"'}>Smart</button>
    </div>` : '';
    formDiv.innerHTML = `
        <input type="text" id="userMessage" class="chat-input" placeholder="Type a message..." />
        ${switchHtml}
        <button type="button" class="btn-secondary small" id="attachFileBtn" title="Attach a text file" aria-label="Attach a file">📎</button>
        <button class="btn-save">Send</button>
        <button id="runTaskBtn" class="btn-run-task">Run Task</button>
    `;
    chatArea.appendChild(formDiv);

    const input = document.getElementById('userMessage');
    const composerBusy = !!botBusy[botId];
    input.disabled = composerBusy;
    if (composerBusy) {
        formDiv.querySelector('.btn-save').disabled = true;
        document.getElementById('runTaskBtn').disabled = true;
    } else {
        input.focus();
    }

    formDiv.querySelectorAll('[data-model-choice]').forEach(btn => btn.addEventListener('click', () => {
        chatModelChoice = btn.dataset.modelChoice;
        formDiv.querySelectorAll('[data-model-choice]').forEach(b => b.classList.toggle('active', b === btn));
    }));

    const attachBtn = document.getElementById('attachFileBtn');
    if (attachBtn) attachBtn.addEventListener('click', () => {
        const fileInput = document.getElementById('fileAttachInput');
        if (fileInput) fileInput.click();
    });

    formDiv.querySelector('.btn-save').addEventListener('click', () => sendMessage(input, botId));
    input.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(input, botId); });

    document.getElementById('runTaskBtn').addEventListener('click', () => runBotTask(botId));
}

// Send message to bot
async function sendMessage(input, botId) {
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    await sendMessageText(botId, message, input);
}

// Core send path shared by the composer and starter chips: one in-flight
// op per bot. The fetch is never aborted on bot switch — it keeps
// running, the sidebar shows "working", and completion lands wherever
// the user is (in place, or via a history refresh on return).
async function sendMessageText(botId, message, input) {
    if (botBusy[botId]) return;
    const historyDiv = document.getElementById('chatHistory');
    if (!historyDiv) return;
    if (input) input.disabled = true;
    document.querySelector('.starter-prompts')?.remove();

    const sentAt = new Date();

    const userDiv = document.createElement('div');
    userDiv.className = 'message message-user';
    userDiv.innerHTML = `
        <div class="message-label">You</div>
        <div class="message-content">${escapeHtml(message)}</div>
        <div class="message-time">${sentAt.toLocaleTimeString()}</div>
    `;
    historyDiv.appendChild(userDiv);

    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'message bot';
    thinkingDiv.innerHTML = `
        <div class="message-label">Bot</div>
        <div class="message-content"><span class="elapsed-timer">0s …</span></div>
    `;
    historyDiv.appendChild(thinkingDiv);
    historyDiv.scrollTop = historyDiv.scrollHeight;

    const timer = setInterval(() => {
        const span = thinkingDiv.querySelector('.elapsed-timer');
        if (span) span.textContent = `${formatElapsed(Date.now() - sentAt.getTime())} …`;
    }, 1000);

    setBotBusy(botId, true);
    try {
        const body = { message };
        if (attachedFile) body.attachments = [{ name: attachedFile.name, content: attachedFile.content }];
        const model = chatModelForSend();
        if (model) body.model = model;
        const response = await fetch(`${API_BASE}/api/bots/${botId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const data = await response.json();
        if (data.error) {
            if (thinkingDiv.isConnected) thinkingDiv.querySelector('.message-content').textContent = data.error;
        } else if (thinkingDiv.isConnected) {
            const receivedAt = new Date();
            const elapsed = receivedAt - sentAt;
            thinkingDiv.querySelector('.message-content').innerHTML = `
                ${formatAssistantMessage(data.response)}
                <span class="message-time">${receivedAt.toLocaleTimeString()}</span>
                <span class="message-time">⏱ ${formatElapsed(elapsed)}</span>
            `;
            historyDiv.scrollTop = historyDiv.scrollHeight;
        }
        await settleSend(botId, thinkingDiv, input, timer);
    } catch (err) {
        if (thinkingDiv.isConnected) thinkingDiv.querySelector('.message-content').textContent = `Error: ${err.message}`;
        await settleSend(botId, thinkingDiv, input, timer);
    }
}

// Run bot's scheduled task. Like chat, it keeps running if the user
// switches bots: no alert yanked into another bot's view, no forced
// re-open — the sidebar clears "working" and the history refreshes
// only if the user is still looking at this bot.
async function runBotTask(botId) {
    if (botBusy[botId]) return;
    setBotBusy(botId, true);
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await response.json();
        setBotBusy(botId, false);
        if (data.error) {
            if (currentBotId === botId) alert(data.error);
            else console.warn('Background task failed for bot', botId, data.error);
        } else if (currentBotId === botId) {
            reenableComposer();
            alert('Task completed: ' + (data.response || '').substring(0, 200));
            await refreshChatHistory(botId);
        }
        await loadBots();
    } catch (e) {
        setBotBusy(botId, false);
        if (currentBotId === botId) {
            reenableComposer();
            alert('Failed to run task');
        } else {
            console.warn('Background task failed for bot', botId, e);
        }
        await loadBots();
    }
}

// Load settings
async function loadSettings() {
    try {
        const response = await fetch(`${API_BASE}/api/settings`);
        const settings = await response.json();
        currentSettings = settings;
        document.getElementById('settingsLocalModel').value = settings.llm?.local_model || 'qwen2.5:7b';
        document.getElementById('settingsSecondaryModel').value = settings.llm?.secondary_model || '';
        document.getElementById('settingsSecondaryBaseUrl').value = settings.llm?.secondary_base_url || '';
        document.getElementById('settingsSecondaryApiKey').value = settings.llm?.secondary_api_key || '';
        
        // Load LLM mode
        if (settings.llm?.mode) {
            const modeSelect = document.querySelector('input[name="llmMode"]');
            if (modeSelect) modeSelect.value = settings.llm.mode;
        }
        
        loadLlmStatus();
        loadMcpStatus();
        document.getElementById('settingsRemoteBaseUrl').value = settings.llm?.remote_base_url || '';
        document.getElementById('settingsRemoteApiKey').value = settings.llm?.remote_api_key || '';
        document.getElementById('settingsRemoteModel').value = settings.llm?.remote_model || 'gpt-4o-mini';
        const gitUrlInput = document.getElementById('settingsAgentsGitUrl');
        if (gitUrlInput) gitUrlInput.value = settings.agents?.git_url || '';
        document.getElementById('settingsSchedulerEnabled').checked = settings.scheduler?.enabled !== false;
        document.getElementById('settingsSchedulerTick').value = settings.scheduler?.tick_seconds || 30;
    } catch (e) {
        console.warn('Failed to load settings', e);
    }
}

// Save settings
async function saveSettings() {
    const settings = {
        llm: {
            local_model: document.getElementById('settingsLocalModel').value,
            secondary_model: document.getElementById('settingsSecondaryModel').value,
            secondary_base_url: document.getElementById('settingsSecondaryBaseUrl').value,
            secondary_api_key: document.getElementById('settingsSecondaryApiKey').value,
            remote_base_url: document.getElementById('settingsRemoteBaseUrl').value,
            remote_api_key: document.getElementById('settingsRemoteApiKey').value,
            remote_model: document.getElementById('settingsRemoteModel').value,
        },
        scheduler: {
            enabled: document.getElementById('settingsSchedulerEnabled').checked,
            tick_seconds: parseInt(document.getElementById('settingsSchedulerTick').value) || 30,
        },
    };
    
    // Get the selected LLM mode
    const modeSelect = document.querySelector('input[name="llmMode"]');
    if (modeSelect) {
        settings.llm.mode = modeSelect.value;
    }
    
    const response = await fetch(`${API_BASE}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    });
    const data = await response.json();
    const statusEl = document.getElementById('settingsSaveStatus');
    if (data.success) {
        // Inline confirmation, then close so the user actually sees it.
        if (statusEl) statusEl.textContent = 'Settings saved ✓';
        await loadSettings();
        setTimeout(() => closeModal(settingsModal), 900);
    } else {
        if (statusEl) statusEl.textContent = 'Failed to save settings.';
    }
}

// Event Listeners Setup
if (newBotBtn) {
    newBotBtn.addEventListener('click', () => {
        document.getElementById('newBotForm').reset();
        document.getElementById('scheduleOptions').style.display = 'none';
        newBotModal.classList.add('active');
    });
}

if (settingsBtn) {
    settingsBtn.addEventListener('click', () => {
        loadSettings();
        settingsModal.classList.add('active');
    });
}

const newBotScheduleEl = document.getElementById('newBotSchedule');
if (newBotScheduleEl) {
    newBotScheduleEl.addEventListener('change', (e) => {
        document.getElementById('scheduleOptions').style.display = e.target.value === 'interval' ? 'block' : 'none';
    });
}

if (newBotForm) {
    newBotForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const scheduleType = document.getElementById('newBotSchedule').value;
        const botData = {
            name: document.getElementById('newBotName').value,
            personality_id: document.getElementById('newBotPersonality').value || '',
            task_prompt: document.getElementById('newBotTaskPrompt').value,
            schedule_type: scheduleType,
            interval_seconds: scheduleType === 'interval' ? parseInt(document.getElementById('newBotInterval').value) || 3600 : 0,
            enabled: document.getElementById('newBotEnabled').checked,
        };
        await fetch(`${API_BASE}/api/bots`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(botData)
        });
        await loadBots();
        await loadPersonalitiesForNewBot();
        closeModal(newBotModal);
    });
}

async function openEditBot(botId) {
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}`);
        if (!response.ok) return;
        const bot = await response.json();
        await loadPersonalitiesForNewBot();
        document.getElementById('editBotId').value = bot.id;
        document.getElementById('editBotName').value = bot.name || '';
        document.getElementById('editBotPersonality').value = bot.personality_id || '';
        document.getElementById('editBotTaskPrompt').value = (bot.config && bot.config.task_prompt) || '';
        const schedule = (bot.config && bot.config.schedule_type) || 'none';
        document.getElementById('editBotSchedule').value = schedule;
        document.getElementById('editBotInterval').value = (bot.config && bot.config.interval_seconds) || 3600;
        document.getElementById('editBotCron').value = (bot.config && bot.config.cron_expression) || '';
        toggleEditScheduleGroups(schedule);
        document.getElementById('editBotStatus').textContent = '';
        document.getElementById('editBotModal').classList.add('active');
    } catch (e) {
        console.warn('Failed to open bot editor', e);
    }
}

function toggleEditScheduleGroups(schedule) {
    document.getElementById('editScheduleOptions').style.display = schedule === 'interval' ? 'block' : 'none';
    document.getElementById('editCronOptions').style.display = schedule === 'cron' ? 'block' : 'none';
}

const editBotForm = document.getElementById('editBotForm');
if (editBotForm) {
    editBotForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const botId = document.getElementById('editBotId').value;
        const scheduleType = document.getElementById('editBotSchedule').value;
        const payload = {
            name: document.getElementById('editBotName').value,
            personality_id: document.getElementById('editBotPersonality').value || '',
            task_prompt: document.getElementById('editBotTaskPrompt').value,
            schedule_type: scheduleType,
            interval_seconds: scheduleType === 'interval' ? parseInt(document.getElementById('editBotInterval').value) || 3600 : 0,
            cron_expression: scheduleType === 'cron' ? document.getElementById('editBotCron').value : '',
        };
        const statusEl = document.getElementById('editBotStatus');
        try {
            const response = await fetch(`${API_BASE}/api/bots/${botId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.ok) {
                const modal = document.getElementById('editBotModal');
                if (modal) closeModal(modal);
                await loadBots();
                openBotChat(botId);
            } else {
                if (statusEl) statusEl.textContent = 'Failed to save bot.';
            }
        } catch (err) {
            if (statusEl) statusEl.textContent = 'Failed to save bot.';
        }
    });
}

const editBotScheduleEl = document.getElementById('editBotSchedule');
if (editBotScheduleEl) {
    editBotScheduleEl.addEventListener('change', (e) => toggleEditScheduleGroups(e.target.value));
}

if (personalityForm) {
    personalityForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const personality = {
            name: document.getElementById('personalityName').value,
            description: document.getElementById('personalityDescription').value,
            skills: document.getElementById('personalitySkills').value.split(',').map(s => s.trim()).filter(s => s),
            abilities: document.getElementById('personalityAbilities').value.split(',').map(a => a.trim()).filter(a => a),
            system_prompt: document.getElementById('personalitySystemPrompt').value
        };
        await fetch(`${API_BASE}/api/personalities`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(personality)
        });
        await loadPersonalitiesForNewBot();
        closeModal(personalityModal);
    });
}

if (settingsForm) {
    settingsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const saveBtn = document.getElementById('settingsSaveBtn');
        const originalText = saveBtn ? saveBtn.textContent : '';
        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
        try {
            await saveSettings();
        } finally {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = originalText; }
        }
    });
}

// Modal handlers
closeModalBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const modal = btn.closest('.modal');
        if (modal) closeModal(modal);
    });
});

window.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        closeModal(e.target);
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal.active').forEach(closeModal);
    }
});

function closeModal(modal) {
    modal.classList.remove('active');
}

// Bot-detail actions (delegated: the info panel is rebuilt per bot).
if (chatArea) chatArea.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-bot-action]');
    if (!btn) return;
    const action = btn.dataset.botAction;
    const id = btn.dataset.botId;
    if (action === 'disable') disableBot(id);
    else if (action === 'delete') deleteBot(id);
    else if (action === 'enable') enableBot(id);
    else if (action === 'edit') openEditBot(id);
});

// Ask about a file: one text file per chat view, read client-side and
// sent along as context with every message while the view is open.
// The file is never stored server-side and never lands in history;
// switching bots or reloading drops it (openBotChat resets it).
const MAX_ATTACH_CHARS = 100_000;

function renderAttachedChip() {
    let bar = document.getElementById('attachedFileBar');
    if (!attachedFile) {
        if (bar) bar.remove();
        return;
    }
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'attachedFileBar';
        bar.className = 'attached-file-bar';
        const composer = document.querySelector('.chat-composer');
        if (composer) composer.before(bar);
        else return;
    }
    bar.innerHTML = `<span>Attached: ${escapeHtml(attachedFile.name)} (${attachedFile.content.length.toLocaleString()} chars)</span> <button type="button" class="btn-secondary small" id="detachFileBtn" aria-label="Remove attachment">×</button>`;
    document.getElementById('detachFileBtn').addEventListener('click', () => {
        attachedFile = null;
        renderAttachedChip();
    });
}

const fileAttachInput = document.getElementById('fileAttachInput');
if (fileAttachInput) fileAttachInput.addEventListener('change', () => {
    const file = fileAttachInput.files[0];
    fileAttachInput.value = '';
    if (!file) return;
    if (file.size > MAX_ATTACH_CHARS) {
        alert('That file is too large to attach (100,000 character limit).');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        const text = String(reader.result || '');
        if (text.includes('\0')) {
            alert('Only text files can be attached.');
            return;
        }
        attachedFile = { name: file.name, content: text.slice(0, MAX_ATTACH_CHARS) };
        renderAttachedChip();
    };
    reader.onerror = () => alert('Could not read that file.');
    reader.readAsText(file);
});

// Search across chats: one box, substring over all bots' history.
// Debounced; a result opens that bot's chat on click.
let chatSearchTimer = null;
const chatSearchInput = document.getElementById('chatSearchInput');
const chatSearchResults = document.getElementById('chatSearchResults');
if (chatSearchInput && chatSearchResults) {
    chatSearchInput.addEventListener('input', () => {
        clearTimeout(chatSearchTimer);
        const query = chatSearchInput.value.trim();
        if (!query) {
            chatSearchResults.innerHTML = '';
            return;
        }
        chatSearchTimer = setTimeout(async () => {
            try {
                const response = await fetch(`${API_BASE}/api/bots/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                const results = data.results || [];
                if (!results.length) {
                    chatSearchResults.innerHTML = '<p class="search-empty">No matches.</p>';
                    return;
                }
                chatSearchResults.innerHTML = results.map(r => `
                    <div class="search-result" data-bot-id="${escapeHtml(r.bot_id)}">
                        <span class="search-result-bot">${escapeHtml(r.bot_name)}</span>
                        <span class="search-result-role">${escapeHtml(r.role)}</span>
                        <span class="search-result-text">${escapeHtml(r.snippet)}</span>
                    </div>
                `).join('');
                chatSearchResults.querySelectorAll('.search-result').forEach(el => el.addEventListener('click', () => {
                    chatSearchInput.value = '';
                    chatSearchResults.innerHTML = '';
                    openBotChat(el.dataset.botId);
                }));
            } catch (e) {
                console.warn('Chat search failed', e);
            }
        }, 250);
    });
}

// Status pill opens Settings (it reports what Settings configures).
const llmStatusPill = document.getElementById('llmStatusPill');
if (llmStatusPill) llmStatusPill.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.add('active');
});

// MCP pill mirrors it, landing on the MCP tab instead of the default one.
const mcpStatusPill = document.getElementById('mcpStatusPill');
if (mcpStatusPill) mcpStatusPill.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.add('active');
    document.querySelector('.tab-btn[data-tab="mcp"]')?.click();
});

// Initialize application
init();
// ── LLM status (Ollama) ──────────────────────────────────────────────

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

// === formatAssistantMessage:begin ===
// LLM replies rendered as tight markdown, no library, and no HTML
// injection from model output. Pipeline: pull fenced code blocks out
// first (their whitespace stays verbatim), tighten the rest (trim,
// collapse 3+ newlines to 2, strip trailing spaces), escape HTML, then
// apply inline markdown and block structure (headings, lists, paragraphs).
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
    let list = null; // { tag, items }
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

// Fetch /api/llm/status and reflect it in the header pill, the Settings
// model list, and the first-run banner. Safe to call any time.
async function loadLlmStatus() {
    const pill = document.getElementById('llmStatusPill');
    const line = document.getElementById('llmStatusLine');
    const banner = document.getElementById('llmBanner');
    try {
        const response = await fetch(`${API_BASE}/api/llm/status`);
        const status = await response.json();
        let pillText, pillClass, bannerText = '';
        if (!status.running) {
            pillText = 'Ollama offline'; pillClass = 'bad';
            bannerText = 'Ollama is offline — start it with `ollama serve`, then pull a model from Settings → Local Models.';
            if (line) { line.textContent = status.error || 'Ollama is not reachable.'; line.className = 'llm-status bad'; }
        } else if (!status.configured_model_installed) {
            pillText = 'Ollama · model missing'; pillClass = 'warn';
            bannerText = `Ollama is running, but '${status.configured_model}' is not installed — pull it from Settings → Local Models.`;
            if (line) { line.textContent = bannerText; line.className = 'llm-status bad'; }
        } else {
            pillText = `Ollama · ${status.configured_model}`; pillClass = 'ok';
            if (line) { line.textContent = `Ollama is running with ${status.models.length} model(s) installed.`; line.className = 'llm-status ok'; }
        }
        if (pill) { pill.textContent = pillText; pill.className = `header-status ${pillClass}`; }
        if (banner) {
            if (bannerText) { banner.style.display = 'block'; banner.textContent = bannerText; }
            else banner.style.display = 'none';
        }
        // The model browser (cards, not a select) renders from the same
        // status payload; refresh it whenever status refreshes.
        refreshModelBrowser(status);
    } catch (e) {
        if (pill) { pill.textContent = 'LLM status unknown'; pill.className = 'header-status warn'; }
        console.warn('Failed to load LLM status', e);
    }
}

// ── MCP status (mirrors the LLM pill) ──────────────────────────────────
async function loadMcpStatus() {
    const pill = document.getElementById('mcpStatusPill');
    if (!pill) return;
    try {
        const response = await fetch(`${API_BASE}/api/mcp/status`);
        const status = await response.json();
        if (!status.running) {
            pill.textContent = 'MCP offline'; pill.className = 'header-status bad';
        } else if (typeof status.count === 'number') {
            pill.textContent = `MCP · ${status.count} server${status.count === 1 ? '' : 's'}`; pill.className = 'header-status ok';
        } else {
            pill.textContent = 'MCP · running'; pill.className = 'header-status ok';
        }
    } catch (e) {
        pill.textContent = 'MCP status unknown'; pill.className = 'header-status warn';
        console.warn('Failed to load MCP status', e);
    }
}

// ── Model browser (Settings → LLM Provider) ──────────────────────────
// Cards from /api/llm/catalog (sized to host RAM), green for installed,
// click a card to pull, unload icon on loaded cards, and a dropdown on
// loaded cards to fill the Primary / Secondary slots.
let modelBrowserState = { catalog: null, installed: [], primary: '', secondary: '', filter: 'all' };

async function refreshModelBrowser(status) {
    const grid = document.getElementById('modelCatalogGrid');
    const loadedGrid = document.getElementById('loadedModelsGrid');
    if (!grid && !loadedGrid) return;
    try {
        const [statusRes, catalogRes, settingsRes] = await Promise.all([
            status ? Promise.resolve({ json: async () => status }) : fetch(`${API_BASE}/api/llm/status`),
            fetch(`${API_BASE}/api/llm/catalog`),
            fetch(`${API_BASE}/api/settings`),
        ]);
        const st = await statusRes.json();
        const catalog = await catalogRes.json();
        const settings = await settingsRes.json();
        modelBrowserState.catalog = catalog;
        modelBrowserState.installed = st.models || [];
        modelBrowserState.primary = settings.llm?.local_model || '';
        modelBrowserState.secondary = settings.llm?.secondary_model || '';
        const localInput = document.getElementById('settingsLocalModel');
        const secInput = document.getElementById('settingsSecondaryModel');
        if (localInput) localInput.value = modelBrowserState.primary;
        if (secInput) secInput.value = modelBrowserState.secondary;
        renderModelBrowser();
    } catch (e) {
        console.warn('Failed to load model browser', e);
    }
}

function renderModelBrowser() {
    const { catalog, installed, primary, secondary, filter } = modelBrowserState;
    const grid = document.getElementById('modelCatalogGrid');
    const loadedGrid = document.getElementById('loadedModelsGrid');
    const note = document.getElementById('catalogNote');
    const linkBox = document.getElementById('ollamaSearchLink');
    const chipsBox = document.getElementById('modelFilterChips');
    if (!catalog) return;
    const installedSet = new Set(installed);

    if (chipsBox) {
        const chips = ['all', ...(catalog.capabilities || [])];
        chipsBox.innerHTML = chips.map(c =>
            `<button type="button" class="chip${c === filter ? ' active' : ''}" data-chip="${c}">${c === 'all' ? 'All' : c}</button>`
        ).join('');
        chipsBox.querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => {
            modelBrowserState.filter = chip.dataset.chip;
            renderModelBrowser();
        }));
    }

    // Loaded models: green, with unload + slot assignment.
    if (loadedGrid) {
        const bothFilled = Boolean(primary && secondary);
        if (!installed.length) {
            loadedGrid.innerHTML = '<p style="color: var(--color-muted);">Nothing loaded yet — pull a model below.</p>';
        } else {
            loadedGrid.innerHTML = installed.map(name => {
                const isPrimary = name === primary;
                const isSecondary = name === secondary;
                let slotHtml = '';
                if (isPrimary) {
                    slotHtml = `<span class="mcp-badge mcp-badge-local">Primary</span>
                        <button type="button" class="btn-icon" data-action="unset" data-slot="primary" data-model="${escapeHtml(name)}" title="Unset primary" aria-label="Unset primary model">&#10006;</button>`;
                } else if (isSecondary) {
                    slotHtml = `<span class="mcp-badge mcp-badge-local">Secondary</span>
                        <button type="button" class="btn-icon" data-action="unset" data-slot="secondary" data-model="${escapeHtml(name)}" title="Unset secondary" aria-label="Unset secondary model">&#10006;</button>`;
                } else if (!bothFilled) {
                    // Dropdowns stay visible until BOTH slots are filled.
                    slotHtml = `<select data-assign="${escapeHtml(name)}" aria-label="Assign model slot">
                        <option value="">Assign…</option>
                        <option value="primary">Primary</option>
                        <option value="secondary">Secondary</option>
                    </select>`;
                }
                return `<div class="model-card loaded">
                    <div class="model-header">
                        <span class="model-name">${escapeHtml(name)}</span>
                        <span class="mcp-badge status-active">Loaded</span>
                    </div>
                    <div class="model-actions">
                        ${slotHtml}
                        <button type="button" class="btn-icon" data-action="unload" data-model="${escapeHtml(name)}" title="Unload model" aria-label="Unload model">&#9167;</button>
                    </div>
                </div>`;
            }).join('');
        }
    }

    // Catalog cards: green when already installed, click to pull otherwise.
    if (grid) {
        const shown = (catalog.models || []).filter(m =>
            filter === 'all' || (m.capabilities || []).includes(filter));
        grid.innerHTML = shown.map(m => {
            const isInstalled = installedSet.has(m.name);
            const isDefault = m.name === catalog.default_model;
            return `<div class="model-card${isInstalled ? ' loaded' : ''}"${isInstalled ? '' : ` data-pull="${escapeHtml(m.name)}"`}>
                <div class="model-header">
                    <span class="model-name">${escapeHtml(m.name)}</span>
                    <span class="model-size">${m.size_gb} GB</span>
                    ${isDefault ? '<span class="mcp-badge mcp-badge-local">Default</span>' : ''}
                    ${isInstalled ? '<span class="mcp-badge status-active">Loaded</span>' : ''}
                </div>
                <div class="model-tags">${(m.capabilities || []).map(c => `<span class="tag">${escapeHtml(c)}</span>`).join('')}</div>
                <div class="model-blurb">${escapeHtml(m.blurb || '')}</div>
                ${isInstalled ? '' : '<div class="model-pull-hint">Click to pull</div>'}
            </div>`;
        }).join('') || '<p style="color: var(--color-muted);">No models match this filter.</p>';
    }

    if (note) {
        note.textContent = (catalog.size_cap_gb
            ? `Showing models up to ${catalog.size_cap_gb} GB (available RAM: ${catalog.ram_available_gb} GB).` +
              (catalog.hidden_count ? ` ${catalog.hidden_count} larger model(s) hidden.` : '')
            : 'Host RAM size unknown — showing all models.') +
            ` Default model for this host: ${catalog.default_model}.`;
    }
    if (linkBox && catalog.ollama_search_url) {
        linkBox.innerHTML = `<a href="${escapeHtml(catalog.ollama_search_url)}" target="_blank" rel="noopener">Browse all models on ollama.com</a>`;
    }
}

// Delegated actions for both model grids (they re-render often).
document.addEventListener('click', async (e) => {
    const unloadBtn = e.target.closest('[data-action="unload"]');
    if (unloadBtn) {
        const model = unloadBtn.dataset.model;
        if (!confirm(`Unload '${model}'? This deletes it from Ollama.`)) return;
        await fetch(`${API_BASE}/api/llm/models/${encodeURIComponent(model)}`, { method: 'DELETE' });
        await refreshModelBrowser();
        await loadLlmStatus();
        return;
    }
    const unsetBtn = e.target.closest('[data-action="unset"]');
    if (unsetBtn) {
        const patch = { llm: {} };
        if (unsetBtn.dataset.slot === 'primary') patch.llm.local_model = '';
        else patch.llm.secondary_model = '';
        await fetch(`${API_BASE}/api/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
        await refreshModelBrowser();
        await loadLlmStatus();
        return;
    }
    const card = e.target.closest('.model-card[data-pull]');
    if (card && document.getElementById('modelCatalogGrid')?.contains(card)) {
        openPullModal(card.dataset.pull);
    }
});
document.addEventListener('change', async (e) => {
    const select = e.target.closest('select[data-assign]');
    if (!select || !select.value) return;
    const model = select.dataset.assign;
    const slot = select.value;
    const patch = { llm: {} };
    if (slot === 'primary') {
        patch.llm.local_model = model;
        if (modelBrowserState.secondary === model) patch.llm.secondary_model = '';
    } else {
        patch.llm.secondary_model = model;
        if (modelBrowserState.primary === model) patch.llm.local_model = '';
    }
    await fetch(`${API_BASE}/api/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
    await refreshModelBrowser();
    await loadLlmStatus();
});

// ── Pull modal: click a card → modal shows live pull progress ─────────
let pullPollTimer = null;
async function openPullModal(model) {
    const modal = document.getElementById('pullModal');
    const modelEl = document.getElementById('pullModalModel');
    const statusEl = document.getElementById('pullModalStatus');
    if (!modal) return;
    if (modelEl) modelEl.textContent = model;
    if (statusEl) statusEl.textContent = 'Starting pull…';
    modal.classList.add('active');
    try {
        const response = await fetch(`${API_BASE}/api/llm/pull`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
        const data = await response.json();
        if (!response.ok) {
            if (statusEl) statusEl.textContent = data.error || 'Pull failed to start.';
            return;
        }
        if (statusEl) statusEl.textContent = data.job.detail || 'Pulling…';
        if (pullPollTimer) clearInterval(pullPollTimer);
        pullPollTimer = setInterval(pollPullModal, 2000);
    } catch (err) {
        if (statusEl) statusEl.textContent = `Pull failed: ${err.message}`;
    }
}
async function pollPullModal() {
    const modal = document.getElementById('pullModal');
    const statusEl = document.getElementById('pullModalStatus');
    if (!modal || !modal.classList.contains('active')) {
        if (pullPollTimer) { clearInterval(pullPollTimer); pullPollTimer = null; }
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/llm/pull`);
        const job = (await response.json()).job || {};
        if (statusEl) statusEl.textContent = job.detail || '';
        if (job.state === 'done' || job.state === 'error') {
            if (pullPollTimer) { clearInterval(pullPollTimer); pullPollTimer = null; }
            await refreshModelBrowser();
            await loadLlmStatus();
        }
    } catch (err) {
        if (pullPollTimer) { clearInterval(pullPollTimer); pullPollTimer = null; }
        if (statusEl) statusEl.textContent = 'Pull status check failed.';
    }
}
const pullModalClose = document.getElementById('pullModalClose');
if (pullModalClose) pullModalClose.addEventListener('click', () => {
    const modal = document.getElementById('pullModal');
    if (modal) closeModal(modal);
});

if (settingsBtn) settingsBtn.addEventListener('click', loadLlmStatus);
if (settingsBtn) settingsBtn.addEventListener('click', loadMcpStatus);

// Setup tab navigation
function setupTabNavigation() {
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Update active tab button
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Show corresponding tab content
            tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === 'tab-' + btn.dataset.tab) {
                    content.classList.add('active');
                }
            });
        });
    });
}

// Render LLM mode selector with 3-box switch control
async function renderModeSelector() {
    if (!modeOptions) return;

    try {
        const response = await fetch(`${API_BASE}/api/settings/modes`);
        const data = await response.json();
        const modes = Object.entries(data.modes || {});
        const currentMode = data.current_mode || 'local_local';
        modeConfigsCache = data.modes || {};

        // Set current mode in settings
        if (settings_llmMode) settings_llmMode.value = currentMode;

        let html = '';
        modes.forEach(([key, mode]) => {
            const isActive = key === currentMode;
            // Determine color class based on mode type
            let colorClass = '';
            if (key === 'local_local') colorClass = 'mode-switch-local_local';
            if (key === 'local_cloud') colorClass = 'mode-switch-local_cloud';
            if (key === 'local_remote_local') colorClass = 'mode-switch-local_remote_local';

            html += `
                <button type="button" class="mode-switch ${isActive ? 'mode-switch-active' : 'mode-switch-inactive'} ${colorClass}" data-mode="${key}">
                    <span class="mode-switch-label">${mode.name}</span>
                    <span class="mode-switch-description">${mode.description}</span>
                </button>
            `;
        });

        modeOptions.innerHTML = html;

        // Add click listeners to every switch (an inactive switch is the
        // one the user wants to click; the old selector only matched the
        // already-active switch, so switching did nothing).
        modeOptions.querySelectorAll(".mode-switch").forEach(switchEl => {
            switchEl.addEventListener("click", () => {
                const modeKey = switchEl.dataset.mode;
                if (settings_llmMode) settings_llmMode.value = modeKey;

                // Update UI based on mode
                updateModeUI(modeKey);

                // Save mode
                saveMode(modeKey);

                // Reset all switches to inactive, then activate clicked
                modeOptions.querySelectorAll(".mode-switch").forEach(s => {
                    s.classList.remove("mode-switch-active");
                    s.classList.add("mode-switch-inactive");
                });
                switchEl.classList.add("mode-switch-active");
                switchEl.classList.remove("mode-switch-inactive");
            });
        });
        // Reflect the current mode in the form right away.
        updateModeUI(currentMode);

    } catch (e) {
        console.warn("Failed to load modes", e);
        modeOptions.innerHTML = '<p style="color: var(--color-muted);">Failed to load mode configurations.</p>';
    }
}


// Show only the form fields the active mode actually uses. Field lists
// come from GET /api/settings/modes (the backend's MODE_CONFIGS); the
// remote/cloud block shows only for local_cloud. Every lookup is guarded
// so a missing group can never throw.
let modeConfigsCache = {};

function setLlmsCollapsed(collapsed) {
    const body = document.getElementById('llmsBody');
    const btn = document.getElementById('llmsCollapseBtn');
    if (body) body.style.display = collapsed ? 'none' : '';
    if (btn) {
        btn.setAttribute('aria-expanded', String(!collapsed));
        btn.innerHTML = collapsed ? '&#9654;' : '&#9650;';
        btn.title = collapsed ? 'Expand local models' : 'Collapse local models';
    }
}
const llmsCollapseBtn = document.getElementById('llmsCollapseBtn');
if (llmsCollapseBtn) llmsCollapseBtn.addEventListener('click', () => {
    const body = document.getElementById('llmsBody');
    setLlmsCollapsed(!(body && body.style.display === 'none'));
});

// Mode sections: the LLMs browser collapses so the Cloud / Remote Local
// section below the divider takes focus in those modes; Local + Local
// hides the section entirely (the two slots above are the whole story).
function updateModeUI(modeKey) {
    const show = (id, visible) => {
        const el = document.getElementById(id);
        if (el) el.style.display = visible ? '' : 'none';
    };
    const isCloud = modeKey === 'local_cloud';
    const isRemoteLocal = modeKey === 'local_remote_local';
    const showSection = isCloud || isRemoteLocal;
    show('modeSectionDivider', showSection);
    show('modeSection', showSection);
    const title = document.getElementById('modeSectionTitle');
    const hint = document.getElementById('modeSectionHint');
    if (title) title.textContent = isCloud ? 'Cloud' : 'Remote Local';
    if (hint) hint.textContent = isCloud
        ? 'When the local model fails, chat falls back to the cloud endpoint below (secondary endpoint first, remote settings as fallback).'
        : 'When the local model fails, chat falls back to the Ollama host below.';
    show('modeSubCloud', isCloud);
    show('group-secondary-base-url', showSection);
    show('group-secondary-api-key', isCloud);
    show('modeSubRemote', isCloud);
    show('group-remote-base-url', isCloud);
    show('group-remote-api-key', isCloud);
    show('group-remote-model', isCloud);
    const secHint = document.getElementById('secondaryModelHint');
    if (secHint) secHint.textContent = isCloud
        ? 'Cloud model used when the local model fails.'
        : isRemoteLocal
        ? 'Model on the remote Ollama host.'
        : 'Second local model, for redundancy or specialized tasks.';
    setLlmsCollapsed(showSection);
}

async function saveMode(mode) {
    try {
        await fetch(`${API_BASE}/api/settings/modes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode })
        });
    } catch (e) {
        console.warn('Failed to save mode', e);
    }
}

// First paint: show LLM readiness immediately, before any chat attempt.
loadLlmStatus();

// Render MCP Marketplace
// ── MCP Marketplace: Local (this host's MCP service) + Remote ────────
// The old tab called /api/mcp/list, /api/mcp/import/<id> and
// /api/mcp/disable/<id> — none of which existed — so it always failed,
// and there was no way to add an MCP at all. These routes exist now.
let remoteMcpCache = {};
let remoteMcpList = [];
let localMcpList = [];
let mcpFilter = 'all';

// ── MCP Marketplace: one grid for local + remote, filtered by pills ──
// Local cards show their enabled state (green, like loaded models);
// remote cards are the MCP service's built-ins plus the leaderboard
// snapshot. Search filters the cached lists (no refetch per keystroke).
async function loadMcps() {
    try {
        const [localRes, remoteRes] = await Promise.all([
            fetch(`${API_BASE}/api/mcp/local`),
            fetch(`${API_BASE}/api/mcp/remote`),
        ]);
        const localData = await localRes.json();
        const remoteData = await remoteRes.json();
        localMcpList = localData.mcps || [];
        remoteMcpList = remoteData.mcps || [];
        remoteMcpCache = {};
        remoteMcpList.forEach(m => { remoteMcpCache[m.id] = m; });
    } catch (e) {
        console.warn('Failed to load MCPs', e);
    }
    renderMcpGrid();
}

function renderMcpFilterChips() {
    const row = document.getElementById('mcpFilterChips');
    if (!row) return;
    const filters = [['all', 'All'], ['local', 'Local'], ['remote', 'Remote']];
    row.innerHTML = filters.map(([key, label]) => `<button type="button" class="chip${mcpFilter === key ? ' active' : ''}" data-mcp-filter="${key}">${label}</button>`).join('');
    row.querySelectorAll('[data-mcp-filter]').forEach(btn => btn.addEventListener('click', () => {
        mcpFilter = btn.dataset.mcpFilter;
        renderMcpFilterChips();
        renderMcpGrid();
    }));
}

function renderMcpGrid() {
    const grid = document.getElementById('mcpGrid');
    if (!grid) return;
    const query = (document.getElementById('mcpSearch')?.value || '').trim().toLowerCase();
    const local = localMcpList.map(m => ({ ...m, _kind: 'local' }));
    const remote = remoteMcpList.map(m => ({ ...m, _kind: 'remote' }));
    let shown = mcpFilter === 'local' ? local : mcpFilter === 'remote' ? remote : [...local, ...remote];
    if (query) {
        shown = shown.filter(m => [m.name, m.description, m.source, m.author, m.category].join(' ').toLowerCase().includes(query));
    }
    const note = document.getElementById('mcpGridNote');
    if (note) note.textContent = `${localMcpList.length} local · ${remoteMcpList.length} remote`;
    if (!shown.length) {
        grid.innerHTML = query
            ? `<p style="color: var(--color-muted);">No MCPs match '${escapeHtml(query)}'.</p>`
            : '<p style="color: var(--color-muted);">No MCPs found.</p>';
        return;
    }
    grid.innerHTML = shown.map(mcp => {
        if (mcp._kind === 'local') {
            return `
            <div class="mcp-card${mcp.enabled === false ? '' : ' enabled'}">
                <div class="mcp-header">
                    <span class="mcp-name">${escapeHtml(mcp.name)}</span>
                    <span class="mcp-badge mcp-badge-local">Local</span>
                    ${mcp.enabled === false ? '<span class="mcp-badge status-inactive">Disabled</span>' : ''}
                </div>
                <div class="mcp-description">${escapeHtml(mcp.description || '')}</div>
                <div class="mcp-description">${escapeHtml(mcp.endpoint || '')} · ${escapeHtml(mcp.method || 'GET')}</div>
                <div class="mcp-actions">
                    <button class="btn-icon" data-mcp-kind="local" data-mcp-action="${mcp.enabled === false ? 'enable' : 'disable'}" data-mcp-id="${escapeHtml(mcp.id)}" title="${mcp.enabled === false ? 'Enable' : 'Disable'}" aria-label="${mcp.enabled === false ? 'Enable MCP' : 'Disable MCP'}">${mcp.enabled === false ? '&#10003;' : '&#10006;'}</button>
                    <button class="btn-icon" data-mcp-kind="local" data-mcp-action="remove" data-mcp-id="${escapeHtml(mcp.id)}" title="Remove" aria-label="Remove MCP">&#128465;</button>
                </div>
            </div>`;
        }
        const isLeaderboard = mcp.source === 'Leaderboard';
        return `
            <div class="mcp-card">
                <div class="mcp-header">
                    <span class="mcp-name">${escapeHtml(mcp.name)}</span>
                    ${isLeaderboard ? `<span class="mcp-badge mcp-badge-leaderboard">#${mcp.rank}</span>` : '<span class="mcp-badge mcp-badge-remote">Remote</span>'}
                </div>
                <div class="mcp-description">${escapeHtml(mcp.description || '')}</div>
                <div class="mcp-description">${isLeaderboard ? `${escapeHtml(mcp.author || '')} · ${escapeHtml(mcp.category || '')} · ★ ${escapeHtml(mcp.stars || '')}` : `Source: ${escapeHtml(mcp.source || '')}${mcp.auth_note ? ` · ${escapeHtml(mcp.auth_note)}` : ''}`}</div>
                <div class="mcp-actions">
                    <button class="btn-secondary small" data-mcp-kind="remote" data-mcp-action="use" data-mcp-id="${escapeHtml(mcp.id)}">Use this</button>
                    ${mcp.endpoint ? `<button class="btn-secondary small" data-mcp-kind="remote" data-mcp-action="import" data-mcp-id="${escapeHtml(mcp.id)}">Import</button>` : ''}
                    ${isLeaderboard && mcp.source_url ? `<button class="btn-secondary small" data-mcp-kind="remote" data-mcp-action="view" data-mcp-id="${escapeHtml(mcp.id)}">View</button>` : ''}
                </div>
            </div>`;
    }).join('');
    grid.querySelectorAll('[data-mcp-action]').forEach(btn => btn.addEventListener('click', async () => {
        const action = btn.dataset.mcpAction;
        const kind = btn.dataset.mcpKind;
        const id = btn.dataset.mcpId;
        if (kind === 'local') {
            if (action === 'remove') {
                if (!confirm('Remove this MCP?')) return;
                await fetch(`${API_BASE}/api/mcps/${encodeURIComponent(id)}`, { method: 'DELETE' });
            } else {
                await fetch(`${API_BASE}/api/mcp/${action}/${encodeURIComponent(id)}`, { method: 'POST' });
            }
            await loadMcps();
            await loadMcpStatus();
            return;
        }
        const entry = remoteMcpCache[id];
        if (!entry) return;
        if (action === 'use') {
            prefillMcpForm(entry);
        } else if (action === 'import') {
            setMcpAddCollapsed(false);
            const res = await fetch(`${API_BASE}/api/mcp/import/${encodeURIComponent(entry.id)}`, { method: 'POST' });
            const result = await res.json();
            const statusEl = document.getElementById('mcpAddStatus');
            if (statusEl) statusEl.textContent = res.ok ? `'${entry.name}' imported to Local MCPs.` : (result.error || 'Import failed.');
            await loadMcps();
            await loadMcpStatus();
        } else if (action === 'view') {
            window.open(entry.source_url, '_blank', 'noopener');
        }
    }));
}

const mcpSearch = document.getElementById('mcpSearch');
if (mcpSearch) mcpSearch.addEventListener('input', renderMcpGrid);

function setMcpAddCollapsed(collapsed) {
    const body = document.getElementById('mcpAddBody');
    const btn = document.getElementById('mcpAddCollapseBtn');
    if (body) body.style.display = collapsed ? 'none' : '';
    if (btn) {
        btn.setAttribute('aria-expanded', String(!collapsed));
        btn.innerHTML = collapsed ? '&#9654;' : '&#9650;';
        btn.title = collapsed ? 'Expand add local MCP' : 'Collapse add local MCP';
    }
}
const mcpAddCollapseBtn = document.getElementById('mcpAddCollapseBtn');
if (mcpAddCollapseBtn) mcpAddCollapseBtn.addEventListener('click', () => {
    const body = document.getElementById('mcpAddBody');
    setMcpAddCollapsed(!(body && body.style.display === 'none'));
});
renderMcpFilterChips();

function prefillMcpForm(entry) {
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value || ''; };
    set('mcpName', entry.name);
    set('mcpDescription', entry.description);
    set('mcpEndpoint', entry.endpoint);
    set('mcpMethod', entry.method || 'GET');
    const statusEl = document.getElementById('mcpAddStatus');
    if (statusEl) statusEl.textContent = entry.endpoint
        ? `'${entry.name}' ready — press Add MCP to register it.`
        : `'${entry.name}' needs an endpoint URL — fill it in, then Add MCP.`;
    setMcpAddCollapsed(false);
    const endpointEl = document.getElementById('mcpEndpoint');
    if (endpointEl) endpointEl.focus();
}

const mcpAddBtn = document.getElementById('mcpAddBtn');
if (mcpAddBtn) mcpAddBtn.addEventListener('click', async () => {
    const nameEl = document.getElementById('mcpName');
    const descEl = document.getElementById('mcpDescription');
    const endpointEl = document.getElementById('mcpEndpoint');
    const methodEl = document.getElementById('mcpMethod');
    const statusEl = document.getElementById('mcpAddStatus');
    const name = nameEl ? nameEl.value.trim() : '';
    const endpoint = endpointEl ? endpointEl.value.trim() : '';
    if (!name || !endpoint) {
        if (statusEl) statusEl.textContent = 'Name and endpoint URL are required.';
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/mcps`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                description: descEl ? descEl.value.trim() : '',
                endpoint,
                method: methodEl ? methodEl.value : 'GET',
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Add failed');
        if (statusEl) statusEl.textContent = `'${name}' added to Local MCPs.`;
        if (nameEl) nameEl.value = '';
        if (descEl) descEl.value = '';
        if (endpointEl) endpointEl.value = '';
        await loadMcps();
        await loadMcpStatus();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Add failed: ${e.message}`;
    }
});

// Top Skills: the MCP Market skills leaderboard snapshot, shown
// alongside local skills. Discovery only — entries carry no repo
// URL, so cards link out instead of importing.
async function renderLeaderboardSkills() {
    const grid = document.getElementById('leaderboardSkillsGrid');
    if (!grid) return;
    try {
        const response = await fetch(`${API_BASE}/api/skills/leaderboard`);
        const data = await response.json();
        const skills = data.skills || [];
        if (!skills.length) {
            grid.innerHTML = '<p style="color: var(--color-muted);">Leaderboard unavailable.</p>';
            return;
        }
        grid.innerHTML = skills.map(s => `
            <div class="mcp-card">
                <div class="mcp-header">
                    <span class="mcp-name">${escapeHtml(s.name)}</span>
                    <span class="mcp-badge mcp-badge-leaderboard">#${s.rank}</span>
                </div>
                <div class="mcp-description">${escapeHtml(s.description || '')}</div>
                <div class="mcp-description">${escapeHtml(s.author || '')} · ${escapeHtml(s.category || '')} · ★ ${escapeHtml(s.stars || '')}</div>
                <div class="mcp-actions">
                    <button class="btn-secondary small" data-skill-view="${escapeHtml(data.source_url || '')}">View</button>
                </div>
            </div>`).join('');
        grid.querySelectorAll('[data-skill-view]').forEach(btn => btn.addEventListener('click', () => {
            window.open(btn.dataset.skillView, '_blank', 'noopener');
        }));
    } catch (e) {
        console.warn('Failed to load skills leaderboard', e);
        grid.innerHTML = '<p style="color: var(--color-muted);">Leaderboard unavailable.</p>';
    }
}

// ── Skills: local skills on by default, disableable ──────
// The old render used agent.id / agent.status, which /api/agents/active
// never returned — hence the literal "undefined" in every card — and its
// inline onclick handlers were unclosed calls, so the buttons did nothing.
async function renderAgentPersonalities() {
    const list = document.getElementById('personalityList');
    if (!list) return;
    try {
        const [agentsRes, envRes] = await Promise.all([
            fetch(`${API_BASE}/api/agents/active`),
            fetch(`${API_BASE}/api/env/vars?prefix=AGENT_`),
        ]);
        const agents = (await agentsRes.json()).agents || [];
        const agentVars = ((await envRes.json()).vars) || {};
        let html = '';
        if (agents.length > 0) {
            html += '<h4>Active Skills</h4><div class="agent-item">';
            agents.forEach(agent => {
                html += `
                    <div class="agent-card" data-agent-id="${escapeHtml(agent.id)}">
                        <div class="agent-header">
                            <span class="agent-name">${escapeHtml(agent.name)}</span>
                            <span class="mcp-badge ${agent.source === 'remote' ? 'mcp-badge-remote' : 'mcp-badge-local'}">${agent.source === 'remote' ? 'Remote' : 'Local'}</span>
                            <span class="agent-status ${agent.active ? 'status-active' : 'status-inactive'}">${agent.active ? 'Active' : 'Disabled'}</span>
                        </div>
                        <div class="agent-description">${escapeHtml(agent.description || '')}</div>
                        <div class="agent-controls">
                            <button class="btn-icon" data-agent-action="toggle" data-agent-id="${escapeHtml(agent.id)}" title="${agent.active ? 'Disable' : 'Enable'}" aria-label="${agent.active ? 'Disable skill' : 'Enable skill'}">${agent.active ? '&#10006;' : '&#10003;'}</button>
                            <button class="btn-icon" data-agent-action="import-git" data-agent-id="${escapeHtml(agent.id)}" title="Import from Git" aria-label="Import skill from Git">&#8635;</button>
                        </div>
                    </div>`;
            });
            html += '</div>';
        } else {
            html += '<p style="color: var(--color-muted);">No skills discovered.</p>';
        }
        if (Object.keys(agentVars).length > 0) {
            html += '<h4>Skills from Environment</h4><div class="personality-item">';
            Object.entries(agentVars).forEach(([key, value]) => {
                const name = key.replace('AGENT_', '').replace(/_/g, ' ');
                html += `
                    <div class="personality-card" data-personality-key="${escapeHtml(key)}">
                        <span class="personality-name">${escapeHtml(name)}</span>
                        <span class="personality-value">${escapeHtml(value.substring(0, 50))}${value.length > 50 ? '...' : ''}</span>
                        <button class="btn-secondary small" data-env-action="disable" data-env-key="${escapeHtml(key)}">Disable</button>
                    </div>`;
            });
            html += '</div>';
        }
        list.innerHTML = html;
        list.querySelectorAll('[data-agent-action]').forEach(btn => btn.addEventListener('click', async () => {
            const action = btn.dataset.agentAction;
            const id = btn.dataset.agentId;
            if (action === 'toggle') {
                await fetch(`${API_BASE}/api/agents/toggle/${encodeURIComponent(id)}`, { method: 'POST' });
                await renderAgentPersonalities();
            } else if (action === 'import-git') {
                if (!confirm('Import agent configuration from remote git source?')) return;
                const response = await fetch(`${API_BASE}/api/agents/import-git/${encodeURIComponent(id)}`, { method: 'POST' });
                const result = await response.json();
                const syncStatus = document.getElementById('agentsSyncStatus');
                if (result.success) {
                    if (syncStatus) syncStatus.textContent = 'Skill imported from Git.';
                    await renderAgentPersonalities();
                } else if (syncStatus) {
                    syncStatus.textContent = 'Failed to import from Git: ' + (result.error || '');
                }
            }
        }));
        list.querySelectorAll('[data-env-action="disable"]').forEach(btn => btn.addEventListener('click', async () => {
            if (!confirm('Disable this agent personality?')) return;
            try {
                const response = await fetch(`${API_BASE}/api/env/disable/${encodeURIComponent(btn.dataset.envKey)}`, { method: 'POST' });
                const result = await response.json();
                if (result.success) await renderAgentPersonalities();
            } catch (e) {
                console.warn('Failed to disable agent personality', e);
            }
        }));
    } catch (e) {
        console.warn('Failed to load agent personalities', e);
        list.innerHTML = '<p style="color: var(--color-muted);">Failed to load agent personalities.</p>';
    }
}

// Remote git repo for agents: save the URL, then re-discover (clone/pull).
const agentsSyncBtn = document.getElementById('agentsSyncBtn');
if (agentsSyncBtn) agentsSyncBtn.addEventListener('click', async () => {
    const input = document.getElementById('settingsAgentsGitUrl');
    const statusEl = document.getElementById('agentsSyncStatus');
    const gitUrl = input ? input.value.trim() : '';
    if (statusEl) statusEl.textContent = 'Saving repo and syncing…';
    try {
        await fetch(`${API_BASE}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agents: { git_url: gitUrl } })
        });
        const response = await fetch(`${API_BASE}/api/agents/refresh`, { method: 'POST' });
        const data = await response.json();
        if (statusEl) statusEl.textContent = `Synced — ${(data.agents || []).length} skill(s) discovered.`;
        await renderAgentPersonalities();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Sync failed: ${e.message}`;
    }
});

// Initialize MCP and Skills
async function initMCPAndPersonalities() {
    await loadMcps();
    await renderAgentPersonalities();
    await renderLeaderboardSkills();
}