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
};

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
    addMessage('gm', '🧙 GM', gameData.gm_response);

    // Update panels
    updateNpcPanel(gameData.npcs || []);
    updateCharacterPanel();

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
        </div>` : ''}`;
}

/* ─── Send Action ───────────────────────────────────────── */

$('#btn-send').addEventListener('click', sendAction);
$('#chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAction();
    }
});

async function sendAction() {
    if (state.sending) return;

    const input = $('#chat-input');
    const action = input.value.trim();
    if (!action) return;

    state.sending = true;
    input.value = '';
    $('#btn-send').disabled = true;

    const playerName = state.character ? state.character.name : 'Oyuncu';
    addMessage('user', `⚔️ ${playerName}`, action);

    showLoading(true, 'GM düşünüyor...');

    try {
        const data = await API.post('/api/game/action', {
            action,
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
        addMessage('gm', '🧙 GM', data.gm_response);

        // Update NPC panel
        updateNpcPanel(data.npcs || []);
    } catch (err) {
        showLoading(false);
        addMessage('system', '', `⚠️ Bağlantı hatası: ${err.message}`);
    } finally {
        state.sending = false;
        $('#btn-send').disabled = false;
        input.focus();
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
        bgMusic.play().catch(() => {});
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
        bgMusic.play().catch(() => {});
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
