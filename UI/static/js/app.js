// Bot UI Application Logic

const API_BASE = '';
let globalBots = [];

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
    setupEventListeners();
}

// Load bots from API
async function loadBots() {
    const response = await fetch(`${API_BASE}/api/bots`);
    const data = await response.json();
    globalBots = data.bots || [];
    renderBotList(globalBots);
}

// Render bot list
function renderBotList(bots) {
    if (bots.length === 0) {
        botList.innerHTML = '<p style="padding: 20px; color: #666;">No bots yet. Create a new bot to get started.</p>';
        chatArea.innerHTML = '<div class="empty">Start by creating a new bot</div>';
        return;
    }
    botList.innerHTML = bots.map(bot => `
        <div class="bot-item" data-testid="bot-item" data-bot-id="${bot.id}" data-bot-name="${bot.name}" style="cursor: pointer; padding: 10px; border-bottom: 1px solid #e0e0e0;">
            <span style="font-weight: 500;">${bot.name}</span>
            <span style="font-size: 0.75rem; color: #666; margin-left: 10px;">${bot.status}</span>
        </div>
    `).join('');

    document.querySelectorAll('.bot-item').forEach(item => {
        item.addEventListener('click', () => openBotChat(item.dataset.botId));
    });
}

// Load personalities for the new-bot dropdown
async function loadPersonalitiesForNewBot() {
    try {
        const response = await fetch(`${API_BASE}/api/personalities`);
        const data = await response.json();
        const select = document.getElementById('newBotPersonality');
        select.innerHTML = '<option value="">(none - general assistant)</option>' +
            (data.personalities || []).map(p => `<option value="${p.id}">${p.name}</option>`).join('');
    } catch (e) {
        console.warn('Failed to load personalities', e);
    }
}

// Open bot chat
async function openBotChat(botId) {
    const bot = globalBots.find(b => b.id === botId);
    if (!bot) return;

    chatArea.innerHTML = '';

    const infoDiv = document.createElement('div');
    infoDiv.style = 'margin-bottom: 10px; padding: 10px; background: #e8f4fd; border-radius: 4px; font-size: 0.85rem;';
    infoDiv.innerHTML = `<strong>${bot.name}</strong> ${bot.personality_id ? '(Personality: ' + bot.personality_id.substring(0,8) + ')' : ''} | Status: <span id="botStatus">${bot.status}</span>`;
    chatArea.appendChild(infoDiv);

    const historyDiv = document.createElement('div');
    historyDiv.id = 'chatHistory';
    historyDiv.style = 'flex: 1; overflow-y: auto; padding: 10px;';
    chatArea.appendChild(historyDiv);

    (bot.conversation_history || []).forEach(msg => {
        const msgDiv = document.createElement('div');
        msgDiv.style = 'margin-bottom: 10px; padding: 8px; border-radius: 4px; max-width: 80%;' +
            (msg.role === 'user' ? 'background:#f0f0f0;margin-left:20px;' : 'background:#e8f4fd;');
        msgDiv.innerHTML = `<strong>${msg.role === 'user' ? 'You' : 'Bot'}:</strong> ${msg.content}`;
        historyDiv.appendChild(msgDiv);
    });

    const formDiv = document.createElement('div');
    formDiv.style = 'padding: 10px; border-top: 1px solid #eee; display:flex; gap:8px;';
    formDiv.innerHTML = `
        <input type="text" id="userMessage" placeholder="Type a message..." style="flex:1; padding: 8px; border: 1px solid #ddd; border-radius: 4px;" />
        <button class="btn-save" style="padding: 0 16px;">Send</button>
        <button id="runTaskBtn" class="btn-save" style="padding: 0 16px; background:#28a745;">Run Task</button>
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
    const userDiv = document.createElement('div');
    userDiv.style = 'margin-bottom: 10px; padding: 8px; background: #f0f0f0; border-radius: 4px; max-width: 80%; margin-left:20px;';
    userDiv.innerHTML = `<strong>You:</strong> ${message}`;
    historyDiv.appendChild(userDiv);

    const response = await fetch(`${API_BASE}/api/bots/${botId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    });

    const data = await response.json();
    input.disabled = false;
    input.focus();

    if (data.error) {
        alert(data.error);
        return;
    }

    const botDiv = document.createElement('div');
    botDiv.style = 'margin-bottom: 10px; padding: 8px; background: #e8f4fd; border-radius: 4px; max-width: 80%;';
    botDiv.innerHTML = `<strong>Bot:</strong> ${data.response}`;
    historyDiv.appendChild(botDiv);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

// Run bot's scheduled task
async function runBotTask(botId) {
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
    loadBots();
    const bot = globalBots.find(b => b.id === botId);
    if (bot) openBotChat(botId);
}

// Load marketplace
async function loadMarketplace() {
    const response = await fetch(`${API_BASE}/api/mcp/marketplace`);
    const data = await response.json();
    renderMarketplace(data.mcps || []);
}

// Render marketplace MCPs
function renderMarketplace(mcps) {
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

// Event Listeners
newBotBtn.addEventListener('click', () => {
    document.getElementById('newBotForm').reset();
    document.getElementById('scheduleOptions').style.display = 'none';
    newBotModal.classList.add('active');
});

settingsBtn.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.add('active');
});

document.getElementById('newBotSchedule').addEventListener('change', (e) => {
    document.getElementById('scheduleOptions').style.display = e.target.value === 'interval' ? 'block' : 'none';
});

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
    loadBots();
    await loadPersonalitiesForNewBot();
    closeModal(newBotModal);
});

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

settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await saveSettings();
});

// Modal handlers
closeModalBtns.forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.closest('.modal')));
});

window.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        closeModal(e.target);
    }
});

function closeModal(modal) {
    modal.classList.remove('active');
}

// Global state

init();
