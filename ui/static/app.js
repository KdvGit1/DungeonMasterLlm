/* ═══════════════════════════════════════════════════════════
   DungeonMaster AI — Frontend Application
   ═══════════════════════════════════════════════════════════ */

const API = {
    post: async (url, body) => {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return res.json();
    },
    get: async (url) => {
        const res = await fetch(url);
        return res.json();
    },
};

/* ─── STATE ─────────────────────────────────────────────── */

const state = {
    user: null,
    sessionId: null,
    character: null,
    scenarioTitle: '',
    nodeTitle: '',
    sending: false,
    modelReady: false,
};

// Model status checker
async function checkModelStatus() {
    try {
        const res = await API.get('/api/translate/status');
        const st = $('#model-status');
        if (res.status === 'ready') {
            st.textContent = 'Model hazır';
            st.classList.add('ready');
            state.modelReady = true;
        } else if (res.status === 'loading') {
            st.textContent = 'Çeviri modeli yükleniyor... (NLLB-200)';
            st.classList.remove('ready');
            setTimeout(checkModelStatus, 2000);
        } else if (res.status === 'error') {
            st.textContent = '❌ Model yüklenemedi';
            st.classList.remove('ready');
        } else {
            st.textContent = 'Model durumu bekliyor...';
            setTimeout(checkModelStatus, 2000);
        }
    } catch (e) {
        setTimeout(checkModelStatus, 5000);
    }
}
// Started later after config save

/* ─── DOM HELPERS ───────────────────────────────────────── */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function showScreen(id) {
    $$('.screen').forEach((s) => s.classList.remove('active'));
    const screen = $(`#${id}`);
    if (screen) screen.classList.add('active');

    // Show music control only on game screen
    const mc = $('#music-control');
    if (id === 'screen-game') {
        mc.classList.add('visible');
    } else {
        mc.classList.remove('visible');
    }
}

function showError(id, msg) {
    const el = $(`#${id}`);
    if (el) el.textContent = msg;
}

function showLoading(show, text) {
    const overlay = $('#loading-overlay');
    const textEl = overlay.querySelector('.loading-text');
    if (text) textEl.textContent = text;
    overlay.style.display = show ? 'flex' : 'none';
}

/* ═══════════════════════════════════════════════════════════
   CONFIG SCREEN
   ═══════════════════════════════════════════════════════════ */

async function loadConfig() {
    showLoading(true, "Ayarlar yükleniyor...");
    try {
        const configData = await API.get('/api/config');
        
        const llmSelect = $('#config-llm-model');
        llmSelect.innerHTML = '';
        for (const [key, val] of Object.entries(configData.models)) {
            llmSelect.innerHTML += `<option value="${val}" ${val === configData.current_model ? 'selected' : ''}>${key} (${val})</option>`;
        }

        const transSelect = $('#config-translator-model');
        transSelect.innerHTML = '';
        for (const [key, val] of Object.entries(configData.translators)) {
            transSelect.innerHTML += `<option value="${val}" ${val === configData.current_translator ? 'selected' : ''}>${key} (${val})</option>`;
        }

        $('#config-target-language').value = configData.target_language || 'Turkish';
        
        showScreen('screen-config');
    } catch(e) {
        console.error("Config load error", e);
    }
    showLoading(false);
}

// Check configuration on load instead of checkModelStatus right away
document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
});

$('#btn-save-config').addEventListener('click', async () => {
    showLoading(true, "Ayarlar kaydediliyor...");
    const payload = {
        model: $('#config-llm-model').value,
        translator: $('#config-translator-model').value,
        target_language: $('#config-target-language').value.trim() || 'Turkish'
    };
    
    await API.post('/api/config', payload);
    showLoading(false);
    
    // Now start checking model 
    setTimeout(checkModelStatus, 1000);
    showScreen('screen-login');
});

/* ═══════════════════════════════════════════════════════════
   LOGIN
   ═══════════════════════════════════════════════════════════ */

$('#btn-login').addEventListener('click', () => doLogin('login'));
$('#btn-register').addEventListener('click', () => doLogin('register'));

$('#login-password').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doLogin('login');
});

async function doLogin(action) {
    const username = $('#login-username').value.trim();
    const password = $('#login-password').value.trim();
    showError('login-error', '');

    if (!username || !password) {
        showError('login-error', 'Kullanıcı adı ve şifre gerekli');
        return;
    }

    const data = await API.post('/api/login', { username, password, action });
    if (data.error) {
        showError('login-error', data.error);
        return;
    }

    state.user = data;
    showScreen('screen-session');
    loadSessions();
}

/* ═══════════════════════════════════════════════════════════
   SESSIONS
   ═══════════════════════════════════════════════════════════ */

async function loadSessions() {
    const data = await API.get('/api/sessions');
    if (data.active_session) {
        $('#active-session-box').style.display = 'flex';
        $('#active-session-name').textContent = data.active_session.session_name;
        $('#new-session-box').style.display = 'none';
    } else {
        $('#active-session-box').style.display = 'none';
        $('#new-session-box').style.display = 'flex';
    }
}

$('#btn-continue-session').addEventListener('click', async () => {
    const data = await API.post('/api/sessions/continue', {});
    if (data.success) {
        state.sessionId = data.session_id;
        showScreen('screen-character');
        loadCharacterList();
    }
});

$('#btn-new-session').addEventListener('click', () => {
    $('#active-session-box').style.display = 'none';
    $('#new-session-box').style.display = 'flex';
});

$('#btn-create-session').addEventListener('click', async () => {
    const name = $('#session-name-input').value.trim() || 'Web Session';
    const data = await API.post('/api/sessions', { name });
    if (data.success) {
        state.sessionId = data.session_id;
        showScreen('screen-character');
        loadCharacterList();
    }
});

/* ═══════════════════════════════════════════════════════════
   CHARACTERS
   ═══════════════════════════════════════════════════════════ */

async function loadCharacterList() {
    const data = await API.get('/api/characters');
    const list = $('#character-list');
    list.innerHTML = '';

    if (data.characters && data.characters.length > 0) {
        data.characters.forEach((filename) => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<div class="card-title">📜 ${filename.replace('.yaml', '')}</div>`;
            card.addEventListener('click', () => loadCharacter(filename));
            list.appendChild(card);
        });
    } else {
        list.innerHTML = '<p style="color:var(--text-secondary);text-align:center">Kayıtlı karakter yok</p>';
    }
}

async function loadCharacter(filename) {
    showLoading(true, 'Karakter yükleniyor...');
    const data = await API.post('/api/characters/load', { filename });
    showLoading(false);

    if (data.error) {
        alert(data.error);
        return;
    }

    state.character = data.character;
    showScreen('screen-scenario');
    loadScenarioList();
}

$('#btn-new-character').addEventListener('click', async () => {
    const creator = $('#character-creator');
    creator.style.display = creator.style.display === 'none' ? 'block' : 'none';

    // Populate options
    const opts = await API.get('/api/characters/options');
    const raceSelect = $('#cc-race');
    const classSelect = $('#cc-class');
    raceSelect.innerHTML = '';
    classSelect.innerHTML = '';

    for (const [key, race] of Object.entries(opts.races)) {
        raceSelect.innerHTML += `<option value="${key}">${race.display}</option>`;
    }
    for (const [key, cls] of Object.entries(opts.classes)) {
        classSelect.innerHTML += `<option value="${key}">${cls.display} — ${cls.tip}</option>`;
    }

    // Abilities
    const abGrid = $('#cc-abilities');
    abGrid.innerHTML = '';
    const abilityNames = { strength: 'Güç', dexterity: 'Çeviklik', constitution: 'Anayasa', intelligence: 'Zeka', wisdom: 'Bilgelik', charisma: 'Karizma' };
    for (const [key, display] of Object.entries(abilityNames)) {
        abGrid.innerHTML += `
            <div class="ability-item">
                <label>${display}</label>
                <input type="number" min="8" max="15" value="10" data-ability="${key}">
            </div>`;
    }
});

$('#btn-create-char').addEventListener('click', async () => {
    const name = $('#cc-name').value.trim();
    if (!name) { alert('İsim gerekli'); return; }

    const abilities = {};
    $$('#cc-abilities input').forEach((inp) => {
        abilities[inp.dataset.ability] = parseInt(inp.value) || 10;
    });

    showLoading(true, 'Karakter oluşturuluyor...');
    const data = await API.post('/api/characters/create', {
        name,
        race: $('#cc-race').value,
        class: $('#cc-class').value,
        background: $('#cc-background').value.trim() || 'Mysterious adventurer',
        abilities,
    });
    showLoading(false);

    if (data.error) { alert(data.error); return; }

    state.character = data.character;
    showScreen('screen-scenario');
    loadScenarioList();
});

/* ═══════════════════════════════════════════════════════════
   SCENARIOS
   ═══════════════════════════════════════════════════════════ */

async function loadScenarioList() {
    const data = await API.get('/api/scenarios');
    const list = $('#scenario-list');
    list.innerHTML = '';

    if (data.scenarios && data.scenarios.length > 0) {
        data.scenarios.forEach((s) => {
            const card = document.createElement('div');
            card.className = 'card';
            const desc = s.description.length > 100 ? s.description.substring(0, 100) + '...' : s.description;
            card.innerHTML = `
                <div class="card-title">📖 ${s.title}</div>
                <div class="card-desc">${desc}</div>`;
            card.addEventListener('click', () => startScenario(s.path));
            list.appendChild(card);
        });
    } else {
        list.innerHTML = '<p style="color:var(--text-secondary);text-align:center">Senaryo bulunamadı</p>';
    }
}

$('#btn-free-play').addEventListener('click', () => startScenario(''));

async function startScenario(path) {
    showLoading(true, 'Senaryo yükleniyor...');
    const data = await API.post('/api/scenarios/start', { path });

    if (data.error) {
        showLoading(false);
        alert(data.error);
        return;
    }

    // Start the game
    showLoading(true, 'GM sahneyi hazırlıyor...');
    const gameData = await API.post('/api/game/start', {});
    showLoading(false);

    if (gameData.error) {
        alert(gameData.error);
        return;
    }

    state.scenarioTitle = gameData.scenario_title || 'Macera';
    state.nodeTitle = gameData.node_title || '';

    // Switch to game screen
    showScreen('screen-game');
    initGameScreen(gameData);
    startMusic();
}

/* ═══════════════════════════════════════════════════════════
   GAME SCREEN
   ═══════════════════════════════════════════════════════════ */

function initGameScreen(gameData) {
    // Header
    $('#scenario-title').textContent = state.scenarioTitle;
    if (state.nodeTitle) {
        $('#node-title').textContent = state.nodeTitle;
        $('#node-title').style.display = 'inline';
    } else {
        $('#node-title').style.display = 'none';
    }

    // Clear chat
    $('#chat-messages').innerHTML = '';

    // Add GM intro message
    addDualMessage('gm', '🧙 GM', gameData.gm_response_tr, gameData.gm_response);

    // Update panels
    updateNpcPanel(gameData.npcs || []);
    if (gameData.player_status) {
        // Backend returns an array of formatted status strings or parsed data. 
        // For right now, let's keep the old updateCharacterPanel but enhance it.
    }
    updateCharacterPanel(gameData.player_status);
    updateInventoryPanel(gameData.inventory);

    // Focus input
    $('#chat-input').focus();
}

/* ─── Messages ──────────────────────────────────────────── */

function addMessage(type, sender, text) {
    const container = $('#chat-messages');
    const msg = document.createElement('div');

    if (type === 'system') {
        msg.className = 'message message-system';
        msg.innerHTML = `<div class="message-text">${text}</div>`;
    } else {
        const cls = type === 'user' ? 'message-user' : 'message-gm';
        msg.className = `message ${cls}`;
        msg.innerHTML = `
            <div class="message-sender">${sender}</div>
            <div class="message-text">${escapeHtml(text)}</div>`;
    }

    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

function addDualMessage(type, sender, textTr, textEn) {
    const container = $('#chat-messages');
    const msg = document.createElement('div');

    const cls = type === 'user' ? 'message-user' : 'message-gm';
    msg.className = `message ${cls}`;

    msg.innerHTML = `
        <div class="message-sender">${sender}</div>
        <div class="text-tr">${escapeHtml(textTr || textEn)}</div>
        <div class="text-en">${escapeHtml(textEn)}</div>`;

    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

function addRollMessage(roll) {
    const container = $('#chat-messages');
    const msg = document.createElement('div');
    msg.className = 'message message-system';

    let outcomeClass = '';
    let outcomeIcon = '';
    switch (roll.outcome) {
        case 'CRITICAL SUCCESS': outcomeClass = 'critical-success'; outcomeIcon = '⭐'; break;
        case 'CRITICAL FAILURE': outcomeClass = 'critical-failure'; outcomeIcon = '💀'; break;
        case 'SUCCESS': outcomeClass = 'success'; outcomeIcon = '✅'; break;
        case 'FAILURE': outcomeClass = 'failure'; outcomeIcon = '❌'; break;
    }

    msg.innerHTML = `
        <div class="roll-result">
            <div>🎲 ${capitalize(roll.ability)} check vs DC ${roll.dc}</div>
            <div>Zar: ${roll.roll} | Modifier: ${roll.modifier >= 0 ? '+' : ''}${roll.modifier} | Toplam: ${roll.total}</div>
            <div class="roll-outcome ${outcomeClass}">${outcomeIcon} ${roll.outcome}</div>
        </div>`;

    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

/* ─── NPC Panel ─────────────────────────────────────────── */

function updateNpcPanel(npcs) {
    const list = $('#npc-list');
    list.innerHTML = '';

    if (!npcs || npcs.length === 0) {
        list.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8rem;text-align:center;padding:1rem">Henüz NPC yok</p>';
        return;
    }

    // Reverse to show newest first
    const reversed = [...npcs].reverse();
    reversed.forEach((npc) => {
        const card = document.createElement('div');
        card.className = 'npc-card';
        const pub = npc.public || {};
        card.innerHTML = `
            <div class="npc-name">${escapeHtml(npc.name)}</div>
            <div class="npc-role">${escapeHtml(pub.role || '')}</div>
            <div class="npc-detail">
                ${pub.appearance ? `<div><strong>Görünüm:</strong> ${escapeHtml(pub.appearance)}</div>` : ''}
                ${pub.personality ? `<div><strong>Kişilik:</strong> ${escapeHtml(pub.personality)}</div>` : ''}
            </div>`;
        list.appendChild(card);
    });
}

/* ─── Character Panel ───────────────────────────────────── */

function updateCharacterPanel() {
    const sheet = $('#character-sheet');
    const c = state.character;
    if (!c) {
        sheet.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:1rem">Karakter yok</p>';
        return;
    }

    const abilities = c.abilities || {};
    const abilityLabels = {
        strength: 'GÜÇ', dexterity: 'ÇVK', constitution: 'ANA',
        intelligence: 'ZKA', wisdom: 'BLG', charisma: 'KRZ',
    };

    let abilitiesHtml = '';
    for (const [key, label] of Object.entries(abilityLabels)) {
        const score = abilities[key] || 10;
        const mod = Math.floor((score - 10) / 2);
        const modStr = mod >= 0 ? `+${mod}` : `${mod}`;
        abilitiesHtml += `
            <div class="ability-box">
                <div class="ability-box-label">${label}</div>
                <div class="ability-box-score">${score}</div>
                <div class="ability-box-mod">${modStr}</div>
            </div>`;
    }

    sheet.innerHTML = `
        <div class="char-section">
            <div class="char-name">${escapeHtml(c.name)}</div>
            <div class="char-meta">${escapeHtml(c.race || '')} ${escapeHtml(c.class || '')} • Seviye ${c.level || 1}</div>
        </div>
        <div class="char-section">
            <div class="char-stat-row">
                <span class="char-stat-label">HP</span>
                <span class="char-stat-value hp">❤️ ${c.hp || c.max_hp || '?'} / ${c.max_hp || '?'}</span>
            </div>
            <div class="char-stat-row">
                <span class="char-stat-label">Zırh Sınıfı</span>
                <span class="char-stat-value ac">🛡️ ${c.armor_class || '?'}</span>
            </div>
        </div>
        <div class="char-section">
            <div class="char-stat-label" style="margin-bottom:0.4rem">Yetenekler</div>
            <div class="ability-grid-sheet">${abilitiesHtml}</div>
        </div>
        ${c.background ? `
        <div class="char-section">
            <div class="char-stat-label" style="margin-bottom:0.25rem">Arka Plan</div>
            <div style="font-size:0.8rem;color:var(--text-secondary)">${escapeHtml(c.background)}</div>
        </div>` : ''}
        <div class="char-section" style="margin-top:0.5rem">
            <div class="char-stat-row">
                <span class="char-stat-label">Seviye ${c.level || 1}</span>
                <span class="char-stat-value" style="font-size:0.8rem; color:var(--text-secondary)">${c.xp || 0} / ${c.xp_to_next || 100} XP</span>
            </div>
            <div class="char-stat-bar-container">
                <div class="char-stat-bar-fill" style="width: ${Math.min(100, Math.max(0, ((c.xp || 0) / (c.xp_to_next || 100)) * 100))}%"></div>
            </div>
        </div>`;
}

function updateInventoryPanel(inventoryData) {
    const sheet = $('#inventory-sheet');
    
    if (!inventoryData) {
        sheet.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:1rem">Envanter boş</p>';
        return;
    }

    let html = '';
    
    // Gold
    const gold = inventoryData.gold || 0;
    html += `
        <div class="gold-display">
            🪙 ${gold} Altın
        </div>
    `;

    // Items
    const items = inventoryData.items || [];
    if (items.length === 0) {
        html += '<p style="color:var(--text-secondary);font-size:0.8rem;text-align:center;">Çantan boş.</p>';
    } else {
        items.forEach(item => {
            html += `
                <div class="inventory-item">
                    <div class="inventory-item-details">
                        <span class="inventory-item-name">${escapeHtml(item.name)}</span>
                        <span class="inventory-item-qty">Miktar: ${item.quantity || 1}</span>
                    </div>
                    <button class="inventory-item-use-btn" onclick="useItem('${escapeHtml(item.name)}')">Kullan</button>
                </div>
            `;
        });
    }

    sheet.innerHTML = html;
}

window.useItem = function(itemName) {
    const input = $('#chat-input');
    input.value = `kullan ${itemName}`;
    sendAction();
};

function handleCombatStatus(combatData) {
    const container = $('#combat-status-container');
    if (!combatData) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';
    
    const hpPercent = Math.max(0, Math.min(100, (combatData.enemy_hp / combatData.enemy_max_hp) * 100));
    
    container.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-end;">
            <div class="combat-enemy-name">⚔️ ${escapeHtml(combatData.enemy_name)}</div>
            <div style="font-size:0.8rem; color: #ffaaa;">HP: ${combatData.enemy_hp} / ${combatData.enemy_max_hp}</div>
        </div>
        <div class="combat-enemy-hp-bar">
            <div class="combat-enemy-hp-fill" style="width: ${hpPercent}%"></div>
        </div>
    `;
}

function handleItemPickup(pendingItem) {
    const container = $('#item-pickup-container');
    if (!pendingItem) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = `
        <div class="item-pickup-info">
            <strong>🎁 Eşya Bulundu:</strong> ${escapeHtml(pendingItem.name)}
        </div>
        <div class="pickup-btn-group">
            <button class="btn btn-primary" style="padding: 0.4rem 0.8rem;" onclick="respondToItemPickup(true)">Al</button>
            <button class="btn btn-secondary" style="padding: 0.4rem 0.8rem;" onclick="respondToItemPickup(false)">Bırak</button>
        </div>
    `;
}

window.respondToItemPickup = async function(accept) {
    const container = $('#item-pickup-container');
    container.style.display = 'none';
    
    showLoading(true, accept ? 'Eşya alınmaya çalışılıyor...' : 'Es geçiliyor...');
    
    try {
        const playerName = state.character ? state.character.name : 'Oyuncu';
        const res = await API.post('/api/game/pickup', { accept, player_name: playerName });
        
        showLoading(false);
        
        if (res.msg) {
            addMessage('system', '', res.msg);
        }
        
        if (res.roll) {
            addRollMessage(res.roll);
        }
        
        // Update Inventory and Status
        if (res.inventory) updateInventoryPanel(res.inventory);
        if (res.player_status) updateCharacterPanel(res.player_status);
        
    } catch(err) {
        showLoading(false);
        addMessage('system', '', `⚠️ Bağlantı hatası: ${err.message}`);
    }
};

/* ─── Input Live Translation ──────────────────────────────────── */

let debounceTimer = null;
const chatInput = $('#chat-input');
const translationPreview = $('#translation-preview');

chatInput.addEventListener('input', () => {
    const text = chatInput.value.trim();
    if (!text) {
        translationPreview.textContent = '';
        return;
    }

    if (!state.modelReady) {
        translationPreview.textContent = '... (Model bekleniyor)';
        return;
    }

    clearTimeout(debounceTimer);
    translationPreview.textContent = 'Çevriliyor...';

    debounceTimer = setTimeout(async () => {
        try {
            const res = await API.post('/api/translate', { text: text, direction: 'tr-en' });
            if (res.translated) {
                translationPreview.textContent = res.translated;
            } else {
                translationPreview.textContent = 'Çeviri yok';
            }
        } catch (e) {
            translationPreview.textContent = '';
        }
    }, 500);
});

/* ─── Send Action ───────────────────────────────────────── */

$('#btn-send').addEventListener('click', sendAction);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAction();
    }
});

async function sendAction() {
    if (state.sending) return;

    const actionTr = chatInput.value.trim();
    if (!actionTr) return;

    // Get the translated text (or fallback to original if not ready)
    const actionEn = translationPreview.textContent && translationPreview.textContent !== 'Çevriliyor...' && translationPreview.textContent !== '... (Model bekleniyor)' && translationPreview.textContent !== 'Çeviri yok'
        ? translationPreview.textContent
        : actionTr;

    state.sending = true;
    chatInput.value = '';
    translationPreview.textContent = '';
    $('#btn-send').disabled = true;

    const playerName = state.character ? state.character.name : 'Oyuncu';
    addDualMessage('user', `⚔️ ${playerName}`, actionTr, actionEn);

    showLoading(true, 'GM düşünüyor...');

    try {
        const data = await API.post('/api/game/action', {
            action: actionEn, // Send ENGLISH action to the backend
            player_name: playerName,
        });

        showLoading(false);

        if (data.error) {
            addMessage('system', '', `⚠️ ${data.error}`);
            return;
        }

        // Scene transition
        if (data.transition) {
            addMessage('system', '', `📍 Sahne değişimi: ${data.transition.new_node_title}`);
            state.nodeTitle = data.transition.new_node_title;
            $('#node-title').textContent = state.nodeTitle;
            $('#node-title').style.display = 'inline';
        }

        // Roll result
        if (data.roll) {
            addRollMessage(data.roll);
        }

        // GM response
        addDualMessage('gm', '🧙 GM', data.gm_response_tr, data.gm_response);

        // Update NPC panel
        updateNpcPanel(data.npcs || []);
        
        // Update Player Status & Inventory
        // First we must update state.character if it changed (HP, XP)
        if (data.player_status) {
            // Our backend `main.py` stores the character data in GameState. 
            // In a better approach `api_game_action` should return the raw character object.
            // For now, let's refetch it if we want it perfectly, or assume it's updated in the session.
            // Actually, we can fetch state if we need to.
            API.get('/api/game/state').then(st => {
                 if (st.characters && st.characters.length > 0) {
                     state.character = st.characters[0];
                     updateCharacterPanel();
                 }
            });
        }
        
        if (data.inventory) {
            updateInventoryPanel(data.inventory);
        }

        // Combat & Logs
        if (data.logs && data.logs.length > 0) {
            data.logs.forEach(msg => {
                if (msg) addMessage('system', '', msg);
            });
        }
        
        handleCombatStatus(data.combat_status);
        handleItemPickup(data.pending_item);

    } catch (err) {
        showLoading(false);
        addMessage('system', '', `⚠️ Bağlantı hatası: ${err.message}`);
    } finally {
        state.sending = false;
        $('#btn-send').disabled = false;
        chatInput.focus();
    }
}

/* ═══════════════════════════════════════════════════════════
   MUSIC
   ═══════════════════════════════════════════════════════════ */

const bgMusic = $('#bg-music');
const volumeSlider = $('#volume-slider');
const volumeLabel = $('#volume-label');
const musicIcon = $('#music-icon');

let musicStarted = false;

// Set initial volume
bgMusic.volume = 0.3;

volumeSlider.addEventListener('input', () => {
    const val = parseInt(volumeSlider.value);
    bgMusic.volume = val / 100;
    volumeLabel.textContent = `${val}%`;

    if (val === 0) {
        musicIcon.textContent = '🔇';
        musicIcon.classList.add('muted');
    } else {
        musicIcon.textContent = '🎵';
        musicIcon.classList.remove('muted');
    }
});

musicIcon.addEventListener('click', () => {
    if (bgMusic.paused) {
        bgMusic.play().catch(() => { });
        musicIcon.textContent = '🎵';
        musicIcon.classList.remove('muted');
    } else {
        bgMusic.pause();
        musicIcon.textContent = '🔇';
        musicIcon.classList.add('muted');
    }
});

function startMusic() {
    if (!musicStarted) {
        bgMusic.play().catch(() => {
            // Autoplay blocked — user must click
            console.log('Autoplay blocked, user interaction needed');
        });
        musicStarted = true;
    }
}

// Try to play on any user interaction (for autoplay policy)
document.addEventListener('click', () => {
    if (musicStarted && bgMusic.paused && parseInt(volumeSlider.value) > 0) {
        bgMusic.play().catch(() => { });
    }
}, { once: true });

/* ═══════════════════════════════════════════════════════════
   UTILS
   ═══════════════════════════════════════════════════════════ */

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}
