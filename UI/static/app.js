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
const marketplaceModal = document.getElementById('marketplaceModal');
const settingsModal = document.getElementById('settingsModal');
const newBotModal = document.getElementById('newBotModal');
const closeModalBtns = document.querySelectorAll('.close-modal');
const personalityForm = document.getElementById('personalityForm');
const newBotForm = document.getElementById('newBotForm');
const settingsForm = document.getElementById('settingsForm');
const marketplaceGrid = document.getElementById('marketplaceGrid');

// Initialize
async function init() {
    await loadBots();
    await loadPersonalitiesForNewBot();
    await loadSettings();
    await loadMarketplace();
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
            <div class="message-content">${msg.content}</div>
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
        <div class="message-content">${message}</div>
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
        document.getElementById('settingsLlmProvider').value = settings.llm?.provider || 'local';
        document.getElementById('settingsLocalModel').value = settings.llm?.local_model || 'qwen2.5';
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
            provider: document.getElementById('settingsLlmProvider').value,
            local_model: document.getElementById('settingsLocalModel').value,
            remote_base_url: document.getElementById('settingsRemoteBaseUrl').value,
            remote_api_key: document.getElementById('settingsRemoteApiKey').value,
            remote_model: document.getElementById('settingsRemoteModel').value,
        },
        scheduler: {
            enabled: document.getElementById('settingsSchedulerEnabled').checked,
            tick_seconds: parseInt(document.getElementById('settingsSchedulerTick').value) || 30,
        },
    };
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