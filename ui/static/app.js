/* ═══════════════════════════════════════════════════════════
   DungeonMaster AI — Multiplayer Frontend
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
    username: null,
    character: null,
    roomCode: null,
    isHost: false,
    scenarioTitle: '',
    nodeTitle: '',
    scenarioPath: '',
    sending: false,
    modelReady: false,
    gameStarted: false,
    lastRoundNumber: -1,
    pollTimer: null,
    hasSubmitted: false,
    // Track which player submissions we've already displayed this round
    displayedSubmissions: new Set(),
};

/* ─── POINT-BUY COST TABLE ──────────────────────────────── */

const POINT_BUY_COSTS = { 8:0, 9:1, 10:2, 11:3, 12:4, 13:5, 14:7, 15:9 };
const POINT_BUY_TOTAL = 27;

function getPointCost(score) {
    return POINT_BUY_COSTS[score] !== undefined ? POINT_BUY_COSTS[score] : 99;
}

/* ─── DOM HELPERS ───────────────────────────────────────── */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function showScreen(id) {
    $$('.screen').forEach((s) => s.classList.remove('active'));
    const screen = $(`#${id}`);
    if (screen) screen.classList.add('active');

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

/* ═══════════════════════════════════════════════════════════
   LOGIN (first screen)
   ═══════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
    showScreen('screen-login');
});

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

    state.username = data.username;
    $('#lobby-welcome').textContent = `Hoş geldin, ${state.username}!`;
    showScreen('screen-lobby');
}

/* ═══════════════════════════════════════════════════════════
   LOBBY — CREATE / JOIN ROOM
   ═══════════════════════════════════════════════════════════ */

$('#btn-create-room').addEventListener('click', async () => {
    state.isHost = true;
    showScreen('screen-host-config');
    await loadConfigForHost();
});

$('#btn-join-room').addEventListener('click', () => {
    const code = $('#join-room-code').value.trim().toUpperCase();
    if (!code || code.length < 4) {
        showError('lobby-error', 'Geçerli bir oda kodu girin');
        return;
    }
    state.roomCode = code;
    state.isHost = false;
    showScreen('screen-character');
    loadCharacterList('join');
});

$('#join-room-code').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#btn-join-room').click();
});

/* ═══════════════════════════════════════════════════════════
   HOST CONFIG
   ═══════════════════════════════════════════════════════════ */

async function loadConfigForHost() {
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
    } catch(e) {
        console.error("Config load error", e);
    }
}

$('#btn-save-config').addEventListener('click', async () => {
    showLoading(true, "Ayarlar kaydediliyor ve model başlatılıyor...");

    const payload = {
        model: $('#config-llm-model').value,
        translator: $('#config-translator-model').value,
        target_language: $('#config-target-language').value.trim() || 'Turkish'
    };
    await API.post('/api/config', payload);

    // Start translator loading in background
    API.post('/api/config/init', {}).catch(() => {});
    setTimeout(checkModelStatus, 1000);

    showLoading(false);

    showScreen('screen-character');
    loadCharacterList('host');
});

/* ═══════════════════════════════════════════════════════════
   CHARACTERS — with Point-Buy System
   ═══════════════════════════════════════════════════════════ */

let _charAction = 'host';

async function loadCharacterList(action) {
    _charAction = action || _charAction;
    const data = await API.get('/api/characters');
    const list = $('#character-list');
    list.innerHTML = '';

    if (data.characters && data.characters.length > 0) {
        data.characters.forEach((filename) => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<div class="card-title">📜 ${filename.replace('.yaml', '')}</div>`;
            card.addEventListener('click', () => selectCharacter(filename));
            list.appendChild(card);
        });
    } else {
        list.innerHTML = '<p style="color:var(--text-secondary);text-align:center">Kayıtlı karakter yok</p>';
    }
}

async function selectCharacter(filename) {
    showLoading(true, 'Karakter yükleniyor...');
    const data = await API.post('/api/characters/load', { filename });
    showLoading(false);

    if (data.error) {
        alert(data.error);
        return;
    }

    state.character = data.character;

    if (_charAction === 'host') {
        await createRoomWithCharacter();
    } else {
        await joinRoomWithCharacter();
    }
}

$('#btn-new-character').addEventListener('click', async () => {
    const creator = $('#character-creator');
    creator.style.display = creator.style.display === 'none' ? 'block' : 'none';

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

    // Build point-buy ability grid
    buildPointBuyGrid();
});

function buildPointBuyGrid() {
    const abGrid = $('#cc-abilities');
    abGrid.innerHTML = '';
    const abilityNames = {
        strength: 'Güç', dexterity: 'Çeviklik', constitution: 'Dayanıklılık',
        intelligence: 'Zeka', wisdom: 'Bilgelik', charisma: 'Karizma'
    };

    for (const [key, display] of Object.entries(abilityNames)) {
        abGrid.innerHTML += `
            <div class="ability-item point-buy-row" data-ability="${key}">
                <label>${display}</label>
                <div class="point-buy-controls">
                    <button type="button" class="pb-btn pb-minus" data-ability="${key}">−</button>
                    <span class="pb-score" data-ability="${key}">8</span>
                    <button type="button" class="pb-btn pb-plus" data-ability="${key}">+</button>
                    <span class="pb-cost" data-ability="${key}">(0)</span>
                </div>
            </div>`;
    }

    // Points remaining display
    abGrid.innerHTML += `
        <div class="point-buy-remaining" id="pb-remaining">
            Kalan Puan: <strong>${POINT_BUY_TOTAL}</strong> / ${POINT_BUY_TOTAL}
        </div>`;

    // Cost reference table
    abGrid.innerHTML += `
        <div class="point-buy-table">
            <span class="pb-table-title">Maliyet Tablosu:</span>
            <span>8→0 9→1 10→2 11→3 12→4 13→5 14→7 15→9</span>
        </div>`;

    // Add event listeners
    abGrid.querySelectorAll('.pb-minus').forEach(btn => {
        btn.addEventListener('click', () => adjustAbility(btn.dataset.ability, -1));
    });
    abGrid.querySelectorAll('.pb-plus').forEach(btn => {
        btn.addEventListener('click', () => adjustAbility(btn.dataset.ability, 1));
    });
}

function adjustAbility(ability, delta) {
    const scoreEl = $(`.pb-score[data-ability="${ability}"]`);
    const costEl = $(`.pb-cost[data-ability="${ability}"]`);
    let current = parseInt(scoreEl.textContent);
    let newScore = current + delta;

    // Clamp to valid range
    if (newScore < 8 || newScore > 15) return;

    // Check if we have enough points
    const totalUsed = getTotalPointsUsed(ability, newScore);
    if (totalUsed > POINT_BUY_TOTAL) return;

    scoreEl.textContent = newScore;
    costEl.textContent = `(${getPointCost(newScore)})`;

    updatePointsRemaining();
}

function getTotalPointsUsed(changedAbility, newValue) {
    let total = 0;
    $$('.pb-score').forEach(el => {
        const ab = el.dataset.ability;
        const score = (ab === changedAbility) ? newValue : parseInt(el.textContent);
        total += getPointCost(score);
    });
    return total;
}

function updatePointsRemaining() {
    let totalUsed = 0;
    $$('.pb-score').forEach(el => {
        totalUsed += getPointCost(parseInt(el.textContent));
    });
    const remaining = POINT_BUY_TOTAL - totalUsed;
    const el = $('#pb-remaining');
    if (el) {
        el.innerHTML = `Kalan Puan: <strong>${remaining}</strong> / ${POINT_BUY_TOTAL}`;
        el.style.color = remaining === 0 ? '#4caf50' : (remaining < 0 ? '#e74c3c' : 'var(--text-gold)');
    }
}

$('#btn-create-char').addEventListener('click', async () => {
    const name = $('#cc-name').value.trim();
    if (!name) { alert('İsim gerekli'); return; }

    // Collect point-buy scores
    const abilities = {};
    $$('.pb-score').forEach(el => {
        abilities[el.dataset.ability] = parseInt(el.textContent);
    });

    // Validate total points
    let totalUsed = 0;
    for (const score of Object.values(abilities)) {
        totalUsed += getPointCost(score);
    }
    if (totalUsed > POINT_BUY_TOTAL) {
        alert(`Çok fazla puan harcadınız! ${totalUsed}/${POINT_BUY_TOTAL}`);
        return;
    }

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

    if (_charAction === 'host') {
        await createRoomWithCharacter();
    } else {
        await joinRoomWithCharacter();
    }
});

/* ─── Room Creation & Joining ──────────────────────────── */

async function createRoomWithCharacter() {
    showLoading(true, 'Oda oluşturuluyor...');
    const data = await API.post('/api/room/create', {
        username: state.username,
        session_name: `Room ${state.username}`,
    });

    if (data.error) {
        showLoading(false);
        alert(data.error);
        return;
    }

    state.roomCode = data.room_code;

    await API.post('/api/room/join', {
        room_code: state.roomCode,
        username: state.username,
        character: state.character,
    });
    showLoading(false);

    showRoomScreen();
}

async function joinRoomWithCharacter() {
    showLoading(true, 'Odaya katılınıyor...');
    const data = await API.post('/api/room/join', {
        room_code: state.roomCode,
        username: state.username,
        character: state.character,
    });
    showLoading(false);

    if (data.error) {
        alert(data.error);
        showScreen('screen-lobby');
        return;
    }

    state.isHost = (data.host === state.username);
    showRoomScreen();
}

/* ═══════════════════════════════════════════════════════════
   ROOM WAITING SCREEN
   ═══════════════════════════════════════════════════════════ */

function showRoomScreen() {
    showScreen('screen-room');

    $('#room-code-display').textContent = state.roomCode;

    if (state.isHost) {
        $('#room-scenario-section').style.display = 'block';
        $('#btn-start-game').style.display = 'inline-block';
        $('#room-waiting-msg').style.display = 'none';
        loadRoomScenarios();
    } else {
        $('#room-scenario-section').style.display = 'none';
        $('#btn-start-game').style.display = 'none';
        $('#room-waiting-msg').style.display = 'block';
    }

    startRoomPolling();
}

function startRoomPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollRoomStatus, 2000);
    pollRoomStatus();
}

async function pollRoomStatus() {
    if (!state.roomCode) return;

    try {
        const data = await API.get(`/api/room/status?room_code=${state.roomCode}`);

        if (data.players) {
            updateRoomPlayersList(data.players);
        }

        // If game started and we haven't transitioned yet
        if (data.game_started && !state.gameStarted) {
            state.gameStarted = true;
            clearInterval(state.pollTimer);

            if (!state.isHost) {
                showScreen('screen-game');

                if (data.round_result) {
                    const rr = data.round_result;
                    state.scenarioTitle = rr.scenario_title || 'Macera';
                    state.nodeTitle = rr.node_title || '';
                    state.lastRoundNumber = data.round_number || 0;
                    initGameScreen(rr);
                } else {
                    state.scenarioTitle = 'Macera';
                    state.nodeTitle = '';
                    initGameScreen({gm_response_tr: '', gm_response: '', npcs: [], player_statuses: {}, inventories: {}});
                }
                startGamePolling();
                startMusic();
            }
            return; // Don't process game-state checks in the same tick
        }

        // Game is running — handle submission and round updates
        if (state.gameStarted) {
            if (data.round_processing) {
                showWaiting(true, 'Tüm oyuncular mesajını gönderdi, GM düşünüyor...');
            } else if (data.submission) {
                updateSubmissionStatus(data.submission);
            }

            // New round result
            if (data.round_result && data.round_number > state.lastRoundNumber) {
                state.lastRoundNumber = data.round_number;
                state.hasSubmitted = false;
                state.displayedSubmissions.clear();
                handleRoundResult(data.round_result);
            }
        }

    } catch (e) {
        console.error("Poll error:", e);
    }
}

function updateRoomPlayersList(players) {
    const list = $('#room-players-list');
    if (!list) return;

    list.innerHTML = '';
    for (const [uname, info] of Object.entries(players)) {
        const isMe = uname === state.username;
        const isHostUser = state.isHost && uname === state.username;
        const card = document.createElement('div');
        card.className = `room-player-card ${isMe ? 'is-me' : ''}`;
        card.innerHTML = `
            <div class="room-player-name">${escapeHtml(info.name)} ${isHostUser ? '👑' : ''}</div>
            <div class="room-player-meta">${escapeHtml(info.race)} ${escapeHtml(info.class)}</div>
            <div class="room-player-user">@${escapeHtml(uname)}</div>
        `;
        list.appendChild(card);
    }
}

async function loadRoomScenarios() {
    const data = await API.get('/api/scenarios');
    const list = $('#room-scenario-list');
    list.innerHTML = '';

    if (data.scenarios && data.scenarios.length > 0) {
        data.scenarios.forEach((s) => {
            const card = document.createElement('div');
            card.className = 'card';
            const desc = s.description.length > 80 ? s.description.substring(0, 80) + '...' : s.description;
            card.innerHTML = `
                <div class="card-title">📖 ${s.title}</div>
                <div class="card-desc">${desc}</div>`;
            card.addEventListener('click', () => {
                $$('#room-scenario-list .card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                state.scenarioPath = s.path;
            });
            list.appendChild(card);
        });
    }
}

$('#btn-room-free-play').addEventListener('click', () => {
    $$('#room-scenario-list .card').forEach(c => c.classList.remove('selected'));
    state.scenarioPath = '';
});

$('#btn-start-game').addEventListener('click', async () => {
    showLoading(true, 'GM sahneyi hazırlıyor...');

    const data = await API.post('/api/room/start', {
        room_code: state.roomCode,
        username: state.username,
        scenario_path: state.scenarioPath,
    });

    showLoading(false);

    if (data.error) {
        alert(data.error);
        return;
    }

    state.gameStarted = true;
    state.scenarioTitle = data.scenario_title || 'Macera';
    state.nodeTitle = data.node_title || '';
    state.lastRoundNumber = data.round_number || 0;

    clearInterval(state.pollTimer);
    showScreen('screen-game');
    initGameScreen(data);
    startGamePolling();
    startMusic();
});

/* ═══════════════════════════════════════════════════════════
   GAME SCREEN
   ═══════════════════════════════════════════════════════════ */

function startGamePolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollGameStatus, 2000);
}

async function pollGameStatus() {
    if (!state.roomCode || !state.gameStarted) return;

    try {
        const data = await API.get(`/api/room/status?room_code=${state.roomCode}`);

        if (data.submission) {
            updateSubmissionStatus(data.submission);
        }

        if (data.round_processing) {
            showWaiting(true, 'Tüm oyuncular mesajını gönderdi, GM düşünüyor...');
        }

        // New round result — only if we haven't processed this round yet
        if (data.round_result && data.round_number > state.lastRoundNumber) {
            state.lastRoundNumber = data.round_number;
            state.hasSubmitted = false;
            state.displayedSubmissions.clear();
            handleRoundResult(data.round_result);
        }
    } catch (e) {
        console.error("Game poll error:", e);
    }
}

function initGameScreen(gameData) {
    $('#scenario-title').textContent = state.scenarioTitle;
    if (state.nodeTitle) {
        $('#node-title').textContent = state.nodeTitle;
        $('#node-title').style.display = 'inline';
    } else {
        $('#node-title').style.display = 'none';
    }

    $('#chat-messages').innerHTML = '';
    addDualMessage('gm', '🧙 GM', gameData.gm_response_tr, gameData.gm_response);
    updateNpcPanel(gameData.npcs || []);
    updateAllPlayersStatus(gameData.player_statuses || {});
    // Update character panel with XP data if available
    const myName = state.character ? state.character.name : '';
    const myXpData = (gameData.xp_data && gameData.xp_data[myName]) ? gameData.xp_data[myName] : null;
    updateCharacterPanel(myXpData);
    if (gameData.inventories && gameData.inventories[myName]) {
        updateInventoryPanel(gameData.inventories[myName]);
    }

    updateRoundIndicator();
    showWaiting(false);
    enableInput();
    $('#chat-input').focus();
}

function handleRoundResult(result) {
    showLoading(false);
    showWaiting(false);

    // Show rolls
    if (result.rolls) {
        for (const [pname, roll] of Object.entries(result.rolls)) {
            addRollMessage(roll, pname);
        }
    }

    // Show combat logs
    if (result.combat_logs) {
        for (const [pname, logs] of Object.entries(result.combat_logs)) {
            logs.forEach(msg => {
                if (msg) addMessage('system', '', `[${pname}] ${msg}`);
            });
        }
    }

    // Scene transition
    if (result.transition) {
        addMessage('system', '', `📍 Sahne değişimi: ${result.transition.new_node_title}`);
        state.nodeTitle = result.transition.new_node_title;
        $('#node-title').textContent = state.nodeTitle;
        $('#node-title').style.display = 'inline';
    }

    // GM response (only part shown from round result — player actions were shown live)
    addDualMessage('gm', '🧙 GM', result.gm_response_tr, result.gm_response);

    // Update panels
    updateNpcPanel(result.npcs || []);
    updateAllPlayersStatus(result.player_statuses || {});

    const myName = state.character ? state.character.name : '';
    if (result.inventories && result.inventories[myName]) {
        updateInventoryPanel(result.inventories[myName]);
    }

    handleCombatStatus(result.combat_status);
    updateRoundIndicator();

    // Update character panel with fresh XP data
    if (result.xp_data && result.xp_data[myName]) {
        updateCharacterPanel(result.xp_data[myName]);
    }

    enableInput();
}

function updateSubmissionStatus(submission) {
    if (!state.gameStarted) return;

    // Show other players' actions as they submit (live display)
    if (submission.submitted) {
        for (const [pname, action] of Object.entries(submission.submitted)) {
            if (!state.displayedSubmissions.has(pname)) {
                state.displayedSubmissions.add(pname);
                if (action === 'PASS') {
                    addMessage('system', '', `⏭️ ${pname} turu geçti.`);
                } else {
                    addMessage('user', `⚔️ ${pname}`, action);
                }
            }
        }
    }

    // Update waiting indicator
    if (state.hasSubmitted && submission.waiting_for && submission.waiting_for.length > 0) {
        showWaiting(true, `Bekleniyor: ${submission.waiting_for.join(', ')}`);
    } else if (state.hasSubmitted && submission.all_ready) {
        showWaiting(true, 'Tüm oyuncular mesajını gönderdi, GM düşünüyor...');
    }
}

function showWaiting(show, text) {
    const indicator = $('#waiting-indicator');
    if (show) {
        indicator.style.display = 'flex';
        if (text) $('#waiting-text').textContent = text;
    } else {
        indicator.style.display = 'none';
    }
}

function updateRoundIndicator() {
    const el = $('#round-indicator');
    if (el) {
        el.textContent = `Round ${Math.max(1, state.lastRoundNumber + 1)}`;
    }
}

function enableInput() {
    state.sending = false;
    state.hasSubmitted = false;
    $('#btn-send').disabled = false;
    $('#btn-pass').disabled = false;
    $('#chat-input').disabled = false;
    $('#chat-input').focus();
}

function disableInput() {
    state.sending = true;
    state.hasSubmitted = true;
    $('#btn-send').disabled = true;
    $('#btn-pass').disabled = true;
    $('#chat-input').disabled = true;
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

function addRollMessage(roll, playerName) {
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

    const label = playerName ? `${playerName} — ` : '';

    msg.innerHTML = `
        <div class="roll-result">
            <div>🎲 ${label}${capitalize(roll.ability)} check vs DC ${roll.dc}</div>
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

/* ─── Players Status Panel ──────────────────────────────── */

function updateAllPlayersStatus(statuses) {
    const list = $('#players-status-list');
    if (!list) return;
    list.innerHTML = '';

    for (const [pname, statusStr] of Object.entries(statuses)) {
        const isMe = state.character && state.character.name === pname;
        const card = document.createElement('div');
        card.className = `player-status-card ${isMe ? 'is-me' : ''}`;
        card.innerHTML = `<div class="player-status-text">${escapeHtml(statusStr)}</div>`;
        list.appendChild(card);
    }
}

/* ─── Character Panel ───────────────────────────────────── */

const ABILITY_THRESHOLDS = [0, 50, 150, 300, 500, 750];

function calculateAbilityProgress(currentXp) {
    if (!currentXp) currentXp = 0;
    
    // Find the current tier
    let currentTierIdx = 0;
    for (let i = 0; i < ABILITY_THRESHOLDS.length; i++) {
        if (currentXp >= ABILITY_THRESHOLDS[i]) {
            currentTierIdx = i;
        }
    }
    
    // If max level
    if (currentTierIdx >= ABILITY_THRESHOLDS.length - 1) {
        return { percent: 100, text: 'MAX', isMax: true };
    }
    
    const tierStart = ABILITY_THRESHOLDS[currentTierIdx];
    const tierEnd = ABILITY_THRESHOLDS[currentTierIdx + 1];
    const totalInTier = tierEnd - tierStart;
    const currentInTier = currentXp - tierStart;
    
    let percent = (currentInTier / totalInTier) * 100;
    percent = Math.max(0, Math.min(100, percent));
    
    return { 
        percent: percent, 
        text: `${currentXp}/${tierEnd}`, 
        isMax: false 
    };
}

function updateCharacterPanel(xpData) {
    const sheet = $('#character-sheet');
    const c = state.character;
    if (!c) {
        sheet.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:1rem">Karakter yok</p>';
        return;
    }

    const abilities = c.abilities || {};
    const abilityXp = (xpData && xpData.ability_xp) ? xpData.ability_xp : {};
    
    const abilityLabels = {
        strength: 'GÜÇ', dexterity: 'ÇVK', constitution: 'ANA',
        intelligence: 'ZKA', wisdom: 'BLG', charisma: 'KRZ',
    };

    let abilitiesHtml = '';
    for (const [key, label] of Object.entries(abilityLabels)) {
        const score = abilities[key] || 10;
        const mod = Math.floor((score - 10) / 2);
        const modStr = mod >= 0 ? `+${mod}` : `${mod}`;
        
        const prog = calculateAbilityProgress(abilityXp[key]);
        
        abilitiesHtml += `
            <div class="ability-box">
                <div class="ability-box-label">${label}</div>
                <div class="ability-box-score">${score}</div>
                <div class="ability-box-mod">${modStr}</div>
                
                <div class="ability-xp-container" title="${prog.text} XP">
                    <div class="ability-xp-bar">
                        <div class="ability-xp-fill ${prog.isMax ? 'max' : ''}" style="width: ${prog.percent}%"></div>
                    </div>
                    <div class="ability-xp-text">${prog.text}</div>
                </div>
            </div>`;
    }

    // Default to character's level/xp if we don't have fresh backend data yet
    const displayLevel = xpData ? xpData.level : (c.level || 1);
    
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

function updateInventoryPanel(inventoryItems) {
    const sheet = $('#inventory-sheet');

    if (!inventoryItems || inventoryItems.length === 0) {
        sheet.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:1rem">Envanter boş</p>';
        return;
    }

    let html = '';
    inventoryItems.forEach(item => {
        html += `
            <div class="inventory-item">
                <div class="inventory-item-details">
                    <span class="inventory-item-name">${escapeHtml(item.item_name)}</span>
                    <span class="inventory-item-qty">x${item.quantity || 1} [${item.rarity}]</span>
                </div>
                <button class="inventory-item-use-btn" onclick="useItem('${escapeHtml(item.item_name)}')">Kullan</button>
            </div>
        `;
    });

    sheet.innerHTML = html;
}

window.useItem = function(itemName) {
    const input = $('#chat-input');
    input.value = `use ${itemName}`;
    sendAction();
};

function handleCombatStatus(combatData) {
    const container = $('#combat-status-container');
    if (!combatData) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';
    const hp = combatData.hp || 0;
    const maxHp = combatData.max_hp || 1;
    const hpPercent = Math.max(0, Math.min(100, (hp / maxHp) * 100));

    container.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-end;">
            <div class="combat-enemy-name">⚔️ ${escapeHtml(combatData.enemy_name)}</div>
            <div style="font-size:0.8rem; color: #ffaaaa;">HP: ${hp} / ${maxHp}</div>
        </div>
        <div class="combat-enemy-hp-bar">
            <div class="combat-enemy-hp-fill" style="width: ${hpPercent}%"></div>
        </div>
    `;
}

/* ─── Input Live Translation ──────────────────────────── */

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

$('#btn-pass').addEventListener('click', passTurn);

async function sendAction() {
    if (state.sending || state.hasSubmitted) return;

    const actionTr = chatInput.value.trim();
    if (!actionTr) return;

    const actionEn = translationPreview.textContent && translationPreview.textContent !== 'Çevriliyor...' && translationPreview.textContent !== '... (Model bekleniyor)' && translationPreview.textContent !== 'Çeviri yok'
        ? translationPreview.textContent
        : actionTr;

    disableInput();
    chatInput.value = '';
    translationPreview.textContent = '';

    // Show own action immediately in chat and mark as displayed
    const myName = state.character ? state.character.name : 'Oyuncu';
    addMessage('user', `⚔️ ${myName}`, actionEn);
    state.displayedSubmissions.add(myName);

    try {
        const data = await API.post('/api/game/action', {
            room_code: state.roomCode,
            username: state.username,
            action: actionEn,
        });

        if (data.error) {
            addMessage('system', '', `⚠️ ${data.error}`);
            enableInput();
            return;
        }

        if (data.waiting) {
            showWaiting(true, data.message || 'Diğer oyuncular bekleniyor...');
        } else if (data.success && data.gm_response) {
            // Round completed — I was the last to submit
            // Update lastRoundNumber IMMEDIATELY to prevent polling duplication
            state.lastRoundNumber = data.round_number;
            state.hasSubmitted = false;
            state.displayedSubmissions.clear();
            handleRoundResult(data);
        }

    } catch (err) {
        addMessage('system', '', `⚠️ Bağlantı hatası: ${err.message}`);
        enableInput();
    }
}

async function passTurn() {
    if (state.sending || state.hasSubmitted) return;

    disableInput();

    // Show own pass immediately in chat and mark as displayed
    const myName = state.character ? state.character.name : 'Oyuncu';
    addMessage('system', '', `⏭️ ${myName} turu geçti.`);
    state.displayedSubmissions.add(myName);

    try {
        const data = await API.post('/api/game/pass', {
            room_code: state.roomCode,
            username: state.username,
        });

        if (data.error) {
            addMessage('system', '', `⚠️ ${data.error}`);
            enableInput();
            return;
        }

        if (data.waiting) {
            showWaiting(true, data.message || 'Diğer oyuncular bekleniyor...');
        } else if (data.success && data.gm_response) {
            // Round completed — I was the last to submit
            state.lastRoundNumber = data.round_number;
            state.hasSubmitted = false;
            state.displayedSubmissions.clear();
            handleRoundResult(data);
        }

    } catch (err) {
        addMessage('system', '', `⚠️ Bağlantı hatası: ${err.message}`);
        enableInput();
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
            console.log('Autoplay blocked, user interaction needed');
        });
        musicStarted = true;
    }
}

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
