// Bot UI Application Logic

const API_BASE = '';
let globalBots = [];

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
const localMcpGrid = document.getElementById('localMcpGrid');
const remoteMcpGrid = document.getElementById('remoteMcpGrid');
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
        <div class="bot-item" data-testid="bot-item" data-bot-id="${bot.id}" data-bot-name="${bot.name}">
            <span style="font-weight: 500;">${bot.name}</span>
            <span class="bot-status">${bot.status}</span>
        </div>
    `).join('');

    document.querySelectorAll('.bot-item').forEach(item => {
        item.addEventListener('click', () => openBotChat(item.dataset.botId));
    });
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
        }
    } catch (e) {
        console.warn('Failed to load available personalities', e);
        const select = document.getElementById('newBotPersonality');
        if (select) {
            select.innerHTML = '<option value="">(none)</option>' +
                '<option value="demo">Demo Mode</option>' +
                '<option value="general">General</option>';
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
    infoDiv.innerHTML = `<strong>${displayName}</strong> ${bot.personality_id ? '(Personality: ' + bot.personality_id.substring(0,8) + ')' : ''} | Status: <span id="botStatus">${bot.status}</span>${healthHtml} ${bot.config.enabled ? `<button class="btn-disable" data-bot-action="disable" data-bot-id="${bot.id}">Disable</button>` : `<button class="btn-delete" data-bot-action="delete" data-bot-id="${bot.id}">Delete</button> <button class="btn-enable" data-bot-action="enable" data-bot-id="${bot.id}">Re-enable</button>`}`;
    chatArea.appendChild(infoDiv);

    const historyDiv = document.createElement('div');
    historyDiv.id = 'chatHistory';
    historyDiv.className = 'chat-history';
    chatArea.appendChild(historyDiv);

    const history = bot.conversation_history || [];
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
            <div class="message-content">${isUser ? escapeHtml(msg.content) : msg.content}</div>
            <div>${timeLabel}${elapsedLabel}</div>
        `;
        historyDiv.appendChild(msgDiv);
    });

    const formDiv = document.createElement('div');
    formDiv.className = 'chat-composer';
    formDiv.innerHTML = `
        <input type="text" id="userMessage" class="chat-input" placeholder="Type a message..." />
        <button class="btn-save">Send</button>
        <button id="runTaskBtn" class="btn-run-task">Run Task</button>
    `;
    chatArea.appendChild(formDiv);

    const input = document.getElementById('userMessage');
    input.focus();

    formDiv.querySelector('button').addEventListener('click', () => sendMessage(input, botId));
    input.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(input, botId); });

    document.getElementById('runTaskBtn').addEventListener('click', () => runBotTask(botId));
}

// Send message to bot
async function sendMessage(input, botId) {
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    input.disabled = true;

    const historyDiv = document.getElementById('chatHistory');
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

    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });

        const data = await response.json();
        clearInterval(timer);
        input.disabled = false;
        input.focus();

        if (data.error) {
            thinkingDiv.querySelector('.message-content').textContent = data.error;
            return;
        }

        const receivedAt = new Date();
        const elapsed = receivedAt - sentAt;
        thinkingDiv.querySelector('.message-content').innerHTML = `
            ${data.response}
            <span class="message-time">${receivedAt.toLocaleTimeString()}</span>
            <span class="message-time">⏱ ${formatElapsed(elapsed)}</span>
        `;
        historyDiv.scrollTop = historyDiv.scrollHeight;
        await loadBots();
    } catch (err) {
        clearInterval(timer);
        input.disabled = false;
        thinkingDiv.querySelector('.message-content').textContent = `Error: ${err.message}`;
    }
}

// Run bot's scheduled task
async function runBotTask(botId) {
    try {
        const response = await fetch(`${API_BASE}/api/bots/${botId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await response.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        alert('Task completed: ' + (data.response || '').substring(0, 200));
        await loadBots();
        const bot = globalBots.find(b => b.id === botId);
        if (bot) openBotChat(botId);
    } catch (e) {
        alert('Failed to run task');
    }
}

// Load settings
async function loadSettings() {
    try {
        const response = await fetch(`${API_BASE}/api/settings`);
        const settings = await response.json();
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
});

// Status pill opens Settings (it reports what Settings configures).
const llmStatusPill = document.getElementById('llmStatusPill');
if (llmStatusPill) llmStatusPill.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.add('active');
});

// Initialize application
init();
// ── LLM status (Ollama) ──────────────────────────────────────────────

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

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
            return `<div class="model-card${isInstalled ? ' loaded' : ''}"${isInstalled ? '' : ` data-pull="${escapeHtml(m.name)}"`}>
                <div class="model-header">
                    <span class="model-name">${escapeHtml(m.name)}</span>
                    <span class="model-size">${m.size_gb} GB</span>
                    ${isInstalled ? '<span class="mcp-badge status-active">Loaded</span>' : ''}
                </div>
                <div class="model-tags">${(m.capabilities || []).map(c => `<span class="tag">${escapeHtml(c)}</span>`).join('')}</div>
                <div class="model-blurb">${escapeHtml(m.blurb || '')}</div>
                ${isInstalled ? '' : '<div class="model-pull-hint">Click to pull</div>'}
            </div>`;
        }).join('') || '<p style="color: var(--color-muted);">No models match this filter.</p>';
    }

    if (note) {
        note.textContent = catalog.size_cap_gb
            ? `Showing models up to ${catalog.size_cap_gb} GB (available RAM: ${catalog.ram_available_gb} GB).` +
              (catalog.hidden_count ? ` ${catalog.hidden_count} larger model(s) hidden.` : '')
            : 'Host RAM size unknown — showing all models.';
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

async function renderLocalMcps() {
    const grid = document.getElementById('localMcpGrid');
    if (!grid) return;
    try {
        const response = await fetch(`${API_BASE}/api/mcp/local`);
        const data = await response.json();
        const mcps = data.mcps || [];
        if (!mcps.length) {
            grid.innerHTML = '<p style="color: var(--color-muted);">No local MCPs yet. Add one above.</p>';
            return;
        }
        grid.innerHTML = mcps.map(mcp => `
            <div class="mcp-card">
                <div class="mcp-header">
                    <span class="mcp-name">${escapeHtml(mcp.name)}</span>
                    <span class="mcp-badge mcp-badge-local">Local</span>
                    ${mcp.enabled === false ? '<span class="mcp-badge status-inactive">Disabled</span>' : ''}
                </div>
                <div class="mcp-description">${escapeHtml(mcp.description || '')}</div>
                <div class="mcp-description">${escapeHtml(mcp.endpoint || '')} · ${escapeHtml(mcp.method || 'GET')}</div>
                <div class="mcp-actions">
                    <button class="btn-icon" data-mcp-action="${mcp.enabled === false ? 'enable' : 'disable'}" data-mcp-id="${escapeHtml(mcp.id)}" title="${mcp.enabled === false ? 'Enable' : 'Disable'}" aria-label="${mcp.enabled === false ? 'Enable MCP' : 'Disable MCP'}">${mcp.enabled === false ? '&#10003;' : '&#10006;'}</button>
                    <button class="btn-icon" data-mcp-action="remove" data-mcp-id="${escapeHtml(mcp.id)}" title="Remove" aria-label="Remove MCP">&#128465;</button>
                </div>
            </div>`).join('');
        grid.querySelectorAll('[data-mcp-action]').forEach(btn => btn.addEventListener('click', async () => {
            const action = btn.dataset.mcpAction;
            const id = btn.dataset.mcpId;
            if (action === 'remove') {
                if (!confirm('Remove this MCP?')) return;
                await fetch(`${API_BASE}/api/mcps/${encodeURIComponent(id)}`, { method: 'DELETE' });
            } else {
                await fetch(`${API_BASE}/api/mcp/${action}/${encodeURIComponent(id)}`, { method: 'POST' });
            }
            await renderLocalMcps();
        }));
    } catch (e) {
        console.warn('Failed to load local MCPs', e);
        grid.innerHTML = '<p style="color: var(--color-muted);">MCP service unreachable.</p>';
    }
}

async function renderRemoteMcps() {
    const grid = document.getElementById('remoteMcpGrid');
    if (!grid) return;
    try {
        const response = await fetch(`${API_BASE}/api/mcp/remote`);
        const data = await response.json();
        const mcps = data.mcps || [];
        remoteMcpCache = {};
        mcps.forEach(m => { remoteMcpCache[m.id] = m; });
        grid.innerHTML = mcps.map(mcp => `
            <div class="mcp-card">
                <div class="mcp-header">
                    <span class="mcp-name">${escapeHtml(mcp.name)}</span>
                    <span class="mcp-badge mcp-badge-remote">Remote</span>
                </div>
                <div class="mcp-description">${escapeHtml(mcp.description || '')}</div>
                <div class="mcp-description">Source: ${mcp.source_url ? `<a href="${escapeHtml(mcp.source_url)}" target="_blank" rel="noopener">${escapeHtml(mcp.source)}</a>` : escapeHtml(mcp.source || '')}${mcp.auth_note ? ` · ${escapeHtml(mcp.auth_note)}` : ''}</div>
                <div class="mcp-actions">
                    <button class="btn-secondary small" data-mcp-action="use" data-mcp-id="${escapeHtml(mcp.id)}">Use this</button>
                    ${mcp.endpoint ? `<button class="btn-secondary small" data-mcp-action="import" data-mcp-id="${escapeHtml(mcp.id)}">Import</button>` : ''}
                </div>
            </div>`).join('') || '<p style="color: var(--color-muted);">No remote MCPs found.</p>';
        grid.querySelectorAll('[data-mcp-action]').forEach(btn => btn.addEventListener('click', async () => {
            const action = btn.dataset.mcpAction;
            const entry = remoteMcpCache[btn.dataset.mcpId];
            if (!entry) return;
            if (action === 'use') {
                prefillMcpForm(entry);
            } else if (action === 'import') {
                const res = await fetch(`${API_BASE}/api/mcp/import/${encodeURIComponent(entry.id)}`, { method: 'POST' });
                const result = await res.json();
                const statusEl = document.getElementById('mcpAddStatus');
                if (statusEl) statusEl.textContent = res.ok ? `'${entry.name}' imported to Local MCPs.` : (result.error || 'Import failed.');
                await renderLocalMcps();
            }
        }));
    } catch (e) {
        console.warn('Failed to load remote MCPs', e);
        grid.innerHTML = '<p style="color: var(--color-muted);">Failed to load remote marketplace.</p>';
    }
}

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
        await renderLocalMcps();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Add failed: ${e.message}`;
    }
});

// ── Agent Personalities: local agents on by default, disableable ──────
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
            html += '<h4>Active Agents</h4><div class="agent-item">';
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
                            <button class="btn-icon" data-agent-action="toggle" data-agent-id="${escapeHtml(agent.id)}" title="${agent.active ? 'Disable' : 'Enable'}" aria-label="${agent.active ? 'Disable agent' : 'Enable agent'}">${agent.active ? '&#10006;' : '&#10003;'}</button>
                            <button class="btn-icon" data-agent-action="import-git" data-agent-id="${escapeHtml(agent.id)}" title="Import from Git" aria-label="Import agent from Git">&#8635;</button>
                        </div>
                    </div>`;
            });
            html += '</div>';
        } else {
            html += '<p style="color: var(--color-muted);">No agents discovered.</p>';
        }
        if (Object.keys(agentVars).length > 0) {
            html += '<h4>Personalities from Environment</h4><div class="personality-item">';
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
                    if (syncStatus) syncStatus.textContent = 'Agent imported from Git.';
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
        if (statusEl) statusEl.textContent = `Synced — ${(data.agents || []).length} agent(s) discovered.`;
        await renderAgentPersonalities();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Sync failed: ${e.message}`;
    }
});

// Initialize MCP and Personalities
async function initMCPAndPersonalities() {
    await renderLocalMcps();
    await renderRemoteMcps();
    await renderAgentPersonalities();
}