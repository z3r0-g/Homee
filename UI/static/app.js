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
const marketplaceGrid = document.getElementById('marketplaceGrid');
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
    infoDiv.innerHTML = `<strong>${displayName}</strong> ${bot.personality_id ? '(Personality: ' + bot.personality_id.substring(0,8) + ')' : ''} | Status: <span id="botStatus">${bot.status}</span>${healthHtml} ${bot.config.enabled ? `<button class="btn-disable" onclick="disableBot('${bot.id}')">Disable</button>` : `<button class="btn-delete" onclick="deleteBot('${bot.id}')">Delete</button> <button class="btn-enable" onclick="enableBot('${bot.id}')">Re-enable</button>`}`;
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

// Load marketplace
async function loadMarketplace() {
    try {
        const response = await fetch(`${API_BASE}/api/mcp/marketplace`);
        const data = await response.json();
        renderMarketplace(data.mcps || []);
    } catch (e) {
        console.warn('Marketplace load failed', e);
    }
}

// Render marketplace MCPs
function renderMarketplace(mcps) {
    if (!marketplaceGrid) return;
    marketplaceGrid.innerHTML = mcps.map(mcp => `
        <div class="marketplace-card" data-mcp-id="${mcp.id}" data-mcp-name="${mcp.name}">
            <h4>${mcp.name}</h4>
            <p>${mcp.description}</p>
        </div>
    `).join('');

    document.querySelectorAll('.marketplace-card').forEach(card => {
        card.addEventListener('click', () => addMCPToBot(card.dataset.mcpId, card.dataset.mcpName));
    });
}

// Add MCP to bot
async function addMCPToBot(mcpId, mcpName) {
    alert('MCP ' + mcpName + ' would be added to the bot');
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
    if (data.success) {
        alert('Settings saved');
        closeModal(settingsModal);
    } else {
        alert('Failed to save settings');
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
        await saveSettings();
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

function closeModal(modal) {
    modal.classList.remove('active');
}

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
    const select = document.getElementById('settingsInstalledModels');
    const localModel = document.getElementById('settingsLocalModel');
    try {
        const response = await fetch(`${API_BASE}/api/llm/status`);
        const status = await response.json();
        let pillText, pillClass, bannerText = '';
        if (!status.running) {
            pillText = 'Ollama offline'; pillClass = 'bad';
            bannerText = 'Ollama is offline — start it with `ollama serve`, then pull a model from Settings → Models.';
            if (line) { line.textContent = status.error || 'Ollama is not reachable.'; line.className = 'llm-status bad'; }
        } else if (!status.configured_model_installed) {
            pillText = 'Ollama · model missing'; pillClass = 'warn';
            bannerText = `Ollama is running, but '${status.configured_model}' is not installed — pull it from Settings → Models.`;
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
        if (select) {
            const current = localModel ? localModel.value : status.configured_model;
            select.innerHTML = status.models.length
                ? status.models.map(m => `<option value="${escapeHtml(m)}"${m === current ? ' selected' : ''}>${escapeHtml(m)}</option>`).join('')
                : '<option value="">(no models detected)</option>';
        }
    } catch (e) {
        if (pill) { pill.textContent = 'LLM status unknown'; pill.className = 'header-status warn'; }
        console.warn('Failed to load LLM status', e);
    }
}

// Model pull: POST starts a background job; poll until it lands.
let pullPollTimer = null;
async function pollPullStatus() {
    const el = document.getElementById('pullStatus');
    const btn = document.getElementById('pullModelBtn');
    try {
        const response = await fetch(`${API_BASE}/api/llm/pull`);
        const job = (await response.json()).job || {};
        if (el) el.textContent = job.detail || '';
        if (job.state === 'done' || job.state === 'error') {
            if (pullPollTimer) { clearInterval(pullPollTimer); pullPollTimer = null; }
            if (btn) btn.disabled = false;
            await loadLlmStatus();
            if (job.state === 'done') {
                const select = document.getElementById('settingsInstalledModels');
                const localModel = document.getElementById('settingsLocalModel');
                if (select) select.value = job.model;
                if (localModel) localModel.value = job.model;
            }
        }
    } catch (e) {
        if (pullPollTimer) { clearInterval(pullPollTimer); pullPollTimer = null; }
        if (btn) btn.disabled = false;
        if (el) el.textContent = 'Pull status check failed.';
    }
}

async function startPull() {
    const input = document.getElementById('pullModelName');
    const el = document.getElementById('pullStatus');
    const btn = document.getElementById('pullModelBtn');
    const model = (input ? input.value.trim() : '') ||
        (document.getElementById('settingsLocalModel') || {}).value || '';
    if (!model) { if (el) el.textContent = 'Enter a model name first.'; return; }
    if (btn) btn.disabled = true;
    if (el) el.textContent = 'Starting pull…';
    try {
        const response = await fetch(`${API_BASE}/api/llm/pull`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
        const data = await response.json();
        if (!response.ok) {
            if (el) el.textContent = data.error || 'Pull failed to start.';
            if (btn) btn.disabled = false;
            return;
        }
        if (el) el.textContent = data.job.detail || 'Pulling…';
        if (pullPollTimer) clearInterval(pullPollTimer);
        pullPollTimer = setInterval(pollPullStatus, 2000);
    } catch (e) {
        if (el) el.textContent = `Pull failed: ${e.message}`;
        if (btn) btn.disabled = false;
    }
}

const pullBtn = document.getElementById('pullModelBtn');
if (pullBtn) pullBtn.addEventListener('click', startPull);
const installedSelect = document.getElementById('settingsInstalledModels');
if (installedSelect) installedSelect.addEventListener('change', () => {
    const localModel = document.getElementById('settingsLocalModel');
    if (localModel && installedSelect.value) localModel.value = installedSelect.value;
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
                <div class="mode-switch ${isActive ? 'mode-switch-active' : 'mode-switch-inactive'} ${colorClass}" data-mode="${key}">
                    <span class="mode-switch-label">${mode.name}</span>
                    <span class="mode-switch-description">${mode.description}</span>
                </div>
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
const MODE_FIELDS_FALLBACK = {
    local_local: ["local_model", "secondary_model"],
    local_cloud: ["local_model", "secondary_base_url", "secondary_api_key", "secondary_model"],
    local_remote_local: ["local_model", "secondary_base_url"],
};

function updateModeUI(modeKey) {
    const modes = Object.keys(modeConfigsCache).length ? modeConfigsCache : MODE_FIELDS_FALLBACK;
    const fields = (modes[modeKey] && modes[modeKey].fields) || MODE_FIELDS_FALLBACK.local_local;
    const show = (groupId, visible) => {
        const el = document.getElementById(groupId);
        if (el) el.style.display = visible ? '' : 'none';
    };
    show('group-local-model', true);
    show('group-secondary-model', fields.includes('secondary_model'));
    show('group-secondary-base-url', fields.includes('secondary_base_url'));
    show('group-secondary-api-key', fields.includes('secondary_api_key'));
    const showRemote = modeKey === 'local_cloud';
    show('group-remote-base-url', showRemote);
    show('group-remote-api-key', showRemote);
    show('group-remote-model', showRemote);
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
async function renderMCPMarketplace() {
    if (!marketplaceGrid) return;

    try {
        const response = await fetch(`${API_BASE}/api/mcp/list`);
        const data = await response.json();
        const mcps = data.mcps || [];

        let html = '';
        mcps.forEach(mcp => {
            const isRemote = mcp.type === 'remote';
            const badgeClass = isRemote ? 'mcp-badge-remote' : 'mcp-badge-local';
            const badgeText = isRemote ? 'Remote' : 'Local';

            html += '\n                <div class="mcp-card" data-mcp-id="' + mcp.id + '">';
            html += '\n                    <div class="mcp-header">';
            html += '\n                        <span class="mcp-name">' + mcp.name + '</span>';
            html += '\n                        <span class="mcp-badge ' + badgeClass + '">' + badgeText + '</span>';
            html += '\n                    </div>';
            html += '\n                    <div class="mcp-description">' + (mcp.description || '') + '</div>';
            html += '\n                    <div class="mcp-actions">';
            html += '\n                        <button class="btn-icon" data-mcp-action="import" data-mcp-id="' + mcp.id + '" title="Import">&#8671;</button>';
            html += '\n                        <button class="btn-icon" data-mcp-action="disable" data-mcp-id="' + mcp.id + '" title="Disable">&#10006;</button>';
            html += '\n                    </div>';
            html += '\n                </div>\n';
        });

        if (html === '') {
            html = '<p style="color: var(--color-muted);">No MCPs found. Add new MCP below.</p>';
        }

        marketplaceGrid.innerHTML = html;

        document.querySelectorAll('.mcp-card').forEach(card => {
            card.addEventListener('click', () => {
                card.classList.toggle('selected');
            });
            card.querySelectorAll('[data-mcp-action]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const action = btn.dataset.mcpAction;
                    const id = btn.dataset.mcpId;
                    if (action === 'import') await importMCP(id);
                    else if (action === 'disable') await disableMCP(id);
                });
            });
        });
    } catch (e) {
        console.warn('Failed to load MCP marketplace', e);
        marketplaceGrid.innerHTML = '<p style="color: var(--color-muted);">Failed to load MCP marketplace.</p>';
    }
}

// Import / disable an MCP via the settings service, then refresh the grid.
async function importMCP(mcpId) {
    try {
        const response = await fetch(`${API_BASE}/api/mcp/import/${mcpId}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Import failed');
        await renderMCPMarketplace();
    } catch (e) {
        console.warn('Failed to import MCP', e);
        alert('Failed to import MCP: ' + e.message);
    }
}

async function disableMCP(mcpId) {
    try {
        const response = await fetch(`${API_BASE}/api/mcp/disable/${mcpId}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Disable failed');
        await renderMCPMarketplace();
    } catch (e) {
        console.warn('Failed to disable MCP', e);
        alert('Failed to disable MCP: ' + e.message);
    }
}

// Render Agent Personalities
async function renderAgentPersonalities() {
    const personalityList = document.getElementById('personalityList');
    if (!personalityList) return;

    try {
        const envResponse = await fetch(`${API_BASE}/api/env/vars?prefix=AGENT_`);
        const envData = await envResponse.json();
        const agentVars = envData.vars || {};

        const agentsResponse = await fetch(`${API_BASE}/api/agents/active`);
        const agentsData = await agentsResponse.json();
        const activeAgents = agentsData.agents || [];

        let html = '';

        if (activeAgents.length > 0) {
            html += '<h4>Active Agents</h4>';
            html += '<div class="agent-item">';
            activeAgents.forEach(agent => {
                html += '\n                    <div class="agent-card" data-agent-id="' + agent.id + '">';
                html += '\n                        <div class="agent-header">';
                html += '\n                            <span class="agent-name">' + agent.name + '</span>';
                html += '\n                            <span class="agent-status ' + (agent.status === 'active' ? 'status-active' : 'status-inactive') + '">' + agent.status + '</span>';
                html += '\n                        </div>';
                html += '\n                        <div class="agent-controls">';
                html += '\n                            <button class="btn-icon" onclick="toggleAgent(' + agent.id + '" title="' + (agent.status === 'active' ? 'Disable' : 'Enable') + '">';
                html += '\n                                <span>' + (agent.status === 'active' ? '&#10006;' : '&#10003;') + '</span>';
                html += '\n                            </button>';
                html += '\n                            <button class="btn-icon" onclick="importAgentGit(' + agent.id + '" title="Import from Git">&#8635;</button>';
                html += '\n                        </div>';
                html += '\n                    </div>\n';
            });
            html += '</div>';
        }

        if (Object.keys(agentVars).length > 0) {
            html += '<h4>Personalities from Environment</h4>';
            html += '<div class="personality-item">';
            Object.entries(agentVars).forEach(([key, value]) => {
                const name = key.replace('AGENT_', '').replace(/_/g, ' ');
                html += '\n                    <div class="personality-card" data-personality-key="' + key + '">';
                html += '\n                        <span class="personality-name">' + name + '</span>';
                html += '\n                        <span class="personality-value">' + value.substring(0, 50) + (value.length > 50 ? '...' : '') + '</span>';
                html += '\n                        <button class="btn-secondary small" onclick="disableAgentPersonality(' + key + ')">Disable</button>';
                html += '\n                    </div>\n';
            });
            html += '</div>';
        }

        personalityList.innerHTML = html;
        addPersonalityListeners();
    } catch (e) {
        console.warn('Failed to load agent personalities', e);
        personalityList.innerHTML = '<p style="color: var(--color-muted);">Failed to load agent personalities.</p>';
    }
}

// Toggle agent active/inactive
async function toggleAgent(agentId) {
    try {
        const response = await fetch(`${API_BASE}/api/agents/toggle/${agentId}`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            renderAgentPersonalities();
        }
    } catch (e) {
        console.warn('Failed to toggle agent', e);
    }
}

// Disable agent personality from env var
async function disableAgentPersonality(varKey) {
    if (confirm('Disable this agent personality?')) {
        try {
            const response = await fetch(`${API_BASE}/api/env/disable/${varKey}`, { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                renderAgentPersonalities();
            }
        } catch (e) {
            console.warn('Failed to disable agent personality', e);
        }
    }
}

// Import agent from remote git source
async function importAgentGit(agentId) {
    if (confirm('Import agent configuration from remote git source?')) {
        try {
            const response = await fetch(`${API_BASE}/api/agents/import-git/${agentId}`, { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                alert('Agent imported from Git successfully');
                renderAgentPersonalities();
            } else {
                alert('Failed to import from Git: ' + (result.error || ''));
            }
        } catch (e) {
            console.warn('Failed to import agent from Git', e);
            alert('Failed to import from Git');
        }
    }
}

// Add event listeners for personality controls
function addPersonalityListeners() {
    document.querySelectorAll('.personality-card .btn-secondary').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const card = btn.closest('.personality-card');
            const key = card.dataset.personalityKey;
            if (key) {
                disableAgentPersonality(key);
            }
        });
    });
}

// Initialize MCP and Personalities
async function initMCPAndPersonalities() {
    await renderMCPMarketplace();
    await renderAgentPersonalities();
}