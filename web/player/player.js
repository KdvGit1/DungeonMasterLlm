import { Net, el, toast, paragraphs, PLAYER_COLORS, COND_ICONS, hpClass } from "/static/shared/net.js";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "dndm_token";
const NAME_KEY = "dndm_name";
const net = new Net("player");

let me = null;            // player public info
let state = null;
let catalog = null;
let turnOptions = null;   // combat options when it's my turn
let pendingRoll = null;   // current roll request for me
const feedItems = {};     // narration id -> element
let liveId = null;
const PORTRAITS = ["🛡️", "🗡️", "🏹", "🔥", "🔨", "🪓", "☀️", "🎻", "🌙", "🐺", "🦉", "🌿", "💀", "👑", "⚗️", "🗝️"];

// ── join ─────────────────────────────────────────────────────────────────
function tryAutoJoin() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) net.send({ op: "join", token, name: localStorage.getItem(NAME_KEY) || "" });
}
net.on("open", () => { if (me || localStorage.getItem(TOKEN_KEY)) tryAutoJoin(); });
$("j-name").value = localStorage.getItem(NAME_KEY) || "";
$("j-go").onclick = () => {
  const name = $("j-name").value.trim();
  if (!name) { toast("Adını yazmalısın.", "error"); return; }
  localStorage.setItem(NAME_KEY, name);
  net.send({ op: "join", name, token: localStorage.getItem(TOKEN_KEY) || undefined });
};
$("j-name").addEventListener("keydown", (e) => { if (e.key === "Enter") $("j-go").click(); });

net.on("hello", (m) => {
  me = m.player;
  localStorage.setItem(TOKEN_KEY, m.token);
  $("c-hello").textContent = `Hoş geldin ${me.name}!`;
});
net.on("toast", (m) => toast(m.text, m.kind));
net.on("error", (m) => { toast(m.text, "error"); setBusy(false); });

// ── state ────────────────────────────────────────────────────────────────
net.on("state", (s) => {
  if (!me) return;
  state = s;
  const myChar = mine();
  const inLobby = s.mode === "lobby";
  show(inLobby || !myChar ? "s-char" : "s-game");
  if (inLobby || !myChar) renderCharScreen();
  else renderGame();
});

function show(id) {
  for (const s of ["s-join", "s-char", "s-game"]) $(s).classList.toggle("hidden", s !== id);
}
function mine() { return state?.party?.find((c) => c.player_id === me?.id) || null; }
function myColor() {
  const idx = (state?.players || []).findIndex((p) => p.id === me?.id);
  return PLAYER_COLORS[(idx < 0 ? 0 : idx) % PLAYER_COLORS.length];
}

// ── character selection ─────────────────────────────────────────────────
async function loadCatalog() {
  if (catalog) return catalog;
  catalog = await (await fetch("/api/catalog")).json();
  const race = $("cc-race"), cls = $("cc-class"), por = $("cc-portrait");
  for (const [k, r] of Object.entries(catalog.races)) race.append(el("option", { value: k }, r.name));
  for (const [k, c] of Object.entries(catalog.classes)) cls.append(el("option", { value: k }, c.name));
  for (const p of PORTRAITS) por.append(el("option", { value: p }, p));
  const desc = () => {
    const r = catalog.races[race.value], c = catalog.classes[cls.value];
    const bonus = Object.entries(r.bonus).map(([k, v]) => `${catalog.abilities[k]} +${v}`).join(", ");
    $("cc-race-d").textContent = `${r.description} (${bonus})`;
    $("cc-class-d").textContent = `${c.description} · Can zarı d${c.hit_die}`;
  };
  race.onchange = desc; cls.onchange = desc;
  desc();
  return catalog;
}

document.querySelectorAll(".seg-b").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".seg-b").forEach((x) => x.classList.toggle("on", x === b));
  $("c-pregen").classList.toggle("hidden", b.dataset.tab !== "pregen");
  $("c-custom").classList.toggle("hidden", b.dataset.tab !== "custom");
});

async function renderCharScreen() {
  await loadCatalog();
  const myChar = mine();
  $("c-wait").classList.toggle("hidden", !myChar);
  document.querySelector(".seg").classList.toggle("hidden", !!myChar);
  $("c-pregen").classList.toggle("hidden", !!myChar || document.querySelector(".seg-b.on").dataset.tab !== "pregen");
  $("c-custom").classList.toggle("hidden", !!myChar || document.querySelector(".seg-b.on").dataset.tab !== "custom");
  if (myChar) {
    $("c-chosen").innerHTML = "";
    $("c-chosen").append(el("div", { class: "pg" }, el("div", { class: "por" }, myChar.portrait || "🙂"),
      el("div", {}, el("div", { class: "nm" }, myChar.name), el("div", { class: "cl" }, `${myChar.race_name} ${myChar.class_name}`),
        el("div", { class: "st" }, `❤️ ${myChar.max_hp} · 🛡️ ${myChar.ac}`))));
    if (state.mode !== "lobby") $("c-wait").querySelector("p").textContent = "Oyun sürüyor — karakterin hazır.";
    return;
  }
  const host = $("c-pregen");
  if (!host.children.length) {
    const taken = new Set(state.party.map((c) => c.name));
    for (const p of catalog.pregens) {
      host.append(el("div", { class: "pg" + (taken.has(p.name) ? " faint" : ""), onclick: () => choosePregen(p) },
        el("div", { class: "por" }, p.portrait),
        el("div", {}, el("div", { class: "nm" }, p.name), el("div", { class: "cl" }, `${p.race} ${p.class}`),
          el("div", { class: "ds" }, p.backstory), el("div", { class: "st" }, `❤️ ${p.hp} · 🛡️ ${p.ac} · ${p.personality}`))));
    }
  }
}

function choosePregen(p) {
  ask(`${p.portrait} ${p.name}`, { input: true, value: p.name, placeholder: "Karakterin adı",
    body: `${p.race} ${p.class} — ${p.backstory}`, ok: "Bu kahramanla oyna" }).then((name) => {
    if (name === null) return;
    net.send({ op: "character", spec: { pregen: p.index, name: (name || "").trim() || p.name } });
  });
}

$("cc-go").onclick = () => {
  const name = $("cc-name").value.trim();
  if (!name) { toast("Karakterine bir isim ver.", "error"); return; }
  net.send({ op: "character", spec: {
    name, race: $("cc-race").value, cls: $("cc-class").value, gender: $("cc-gender").value,
    portrait: $("cc-portrait").value, appearance: $("cc-look").value.trim(),
    personality: $("cc-pers").value.trim(), backstory: $("cc-back").value.trim() } });
};
$("c-change").onclick = () => {
  if (state.mode !== "lobby") { toast("Oyun başladıktan sonra karakter değiştirilemez.", "error"); return; }
  $("c-wait").classList.add("hidden");
  document.querySelector(".seg").classList.remove("hidden");
  $("c-pregen").classList.remove("hidden");
};

// ── game ─────────────────────────────────────────────────────────────────
document.querySelectorAll(".tabbar button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabbar button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === b.dataset.tab));
  if (b.dataset.tab === "t-story") scrollFeed();
});

function renderGame() {
  const c = mine();
  document.documentElement.style.setProperty("--pc", myColor());
  $("me-portrait").textContent = c.portrait || "🙂";
  $("me-name").textContent = `${c.name} · ${c.class_name} ${c.level}`;
  $("me-hp").style.width = `${Math.max(0, (100 * c.hp) / c.max_hp)}%`;
  $("me-hp").parentElement.className = `hpbar ${hpClass(c.hp, c.max_hp)}`;
  $("me-hptext").textContent = `❤️ ${c.hp}/${c.max_hp}${c.temp_hp ? ` (+${c.temp_hp})` : ""}`;
  $("me-ac").textContent = c.ac;
  $("me-loc").textContent = state.world ? `📍 ${state.world.location.name}` : "";
  const combat = state.mode === "combat" ? state.combat : null;
  $("me-mode").textContent = combat ? "⚔️" : "🧭";
  $("me-mode").className = "chip " + (combat ? "bad" : "ok");
  if (!Object.keys(feedItems).length && state.narration?.length) {
    for (const n of state.narration) addGM(n.id, n.text, n.kind, false);
  }
  renderComposer(c, combat);
  renderCombatBox(c, combat);
  renderSheet(c);
  renderBag(c);
  renderJournal();
}

function renderComposer(c, combat) {
  const comp = $("composer");
  comp.classList.toggle("hidden", !!combat || c.dead);
  if (combat || c.dead) return;
  const pend = state.pending?.[c.id];
  const note = $("sent-note");
  if (state.busy) {
    note.className = "sent-note thinking-note";
    note.innerHTML = "";
    note.append(el("span", {}, "🎲 GM sonucu hazırlıyor…"), el("span", { class: "spinner" }));
  } else if (pend) {
    const alive = state.party.filter((x) => !x.dead);
    const ready = alive.filter((x) => state.pending[x.id]).length;
    note.className = "sent-note";
    note.innerHTML = "";
    note.append(el("span", {}, `✓ Eylemin gönderildi (${ready}/${alive.length} hazır)`),
      el("button", { class: "btn small ghost", onclick: () => net.send({ op: "withdraw" }) }, "Geri al"));
  } else {
    note.className = "sent-note hidden";
  }
  $("act").disabled = !!pend || state.busy;
  $("act-send").disabled = !!pend || state.busy;
  const q = $("quick");
  if (!q.children.length) {
    for (const t of ["Etrafa dikkatlice bakıyorum", "Yakındaki kişiyle konuşuyorum", "Kısa bir mola verip dinleniyorum",
      "Yerdeki eşyaları inceliyorum", "Burada güvenli bir yerde kamp kurup uyuyoruz"]) {
      q.append(el("button", { onclick: () => { $("act").value = t; $("act").focus(); } }, t));
    }
  }
}

$("act-send").onclick = () => {
  const text = $("act").value.trim();
  if (!text) return;
  net.send({ op: "action", text, private: $("act-private").checked });
  addMine(text, $("act-private").checked);
  $("act").value = "";
  $("act-private").checked = false;
};
$("act").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("act-send").click(); } });

function addMine(text, priv) {
  $("feed").append(el("div", { class: "msg me" }, priv ? "🤫 " : "", text));
  scrollFeed();
}

function addGM(id, text, kind, streaming) {
  let node = feedItems[id];
  if (!node) {
    node = el("div", { class: "msg gm parchment" + (kind?.startsWith("combat") ? " combat" : "") });
    feedItems[id] = node;
    $("feed").append(node);
  }
  node.innerHTML = "";
  node.append(paragraphs(text));
  if (streaming) (node.lastElementChild || node.appendChild(el("p"))).classList.add("cursor");
  scrollFeed();
}
function scrollFeed() { const f = $("feed"); f.scrollTop = f.scrollHeight; }

net.on("narration_start", (m) => { liveId = m.id; addGM(m.id, "", m.kind, true); });
net.on("narration_chunk", (m) => {
  const n = feedItems[m.id];
  if (!n) return;
  n._text = (n._text || "") + m.text;
  addGM(m.id, n._text, m.kind, true);
});
net.on("narration_end", (m) => addGM(m.id, m.text, m.kind, false));
net.on("check_result", (m) => {
  $("feed").append(el("div", { class: "msg sys" }, `🎲 ${m.text}`));
  scrollFeed();
  if (pendingRoll && pendingRoll.char_id === m.char_id && pendingRoll.done) showRollOutcome(m.result);
});

// show hit / miss on the roll card for my own attacks
net.on("combat_event", (m) => {
  const ev = m.event;
  const c = mine();
  if (!pendingRoll || !c || ev.type !== "attack" || ev.actor !== `pc:${c.id}`) return;
  const out = $("r-out");
  out.textContent = ev.data.critical ? "KRİTİK VURUŞ!" : ev.data.hit ? "İSABET!" : "ISKA";
  out.className = "r-out " + (ev.data.hit ? "ok" : "bad");
});

// ── combat ──────────────────────────────────────────────────────────────
net.on("your_turn", (m) => {
  turnOptions = m.options;
  if (navigator.vibrate) navigator.vibrate([80, 60, 80]);
  if (state) renderCombatBox(mine(), state.combat);
});

function renderCombatBox(c, combat) {
  const box = $("combat-box");
  box.classList.toggle("hidden", !combat);
  if (!combat) { turnOptions = null; return; }
  box.innerHTML = "";
  const line = el("div", { class: "turn-line" });
  for (const o of combat.order) {
    line.append(el("div", { class: `ini ${o.side}${o.current ? " cur" : ""}${["dead", "fled", "surrendered"].includes(o.state) ? " out" : ""}` },
      o.side === "enemy" ? `[${o.label}] ${o.name}` : `${o.portrait || ""} ${o.name}`));
  }
  box.append(line);
  const myTurn = combat.current === `pc:${c.id}`;
  if (c.dead) { box.append(el("div", { class: "dead-banner" }, "💀 Karakterin öldü. Masadan izlemeye devam et.")); return; }
  if (!myTurn) {
    const cur = combat.order.find((o) => o.current);
    box.append(el("div", { class: "muted small", style: { textAlign: "center" } }, cur ? `Sıra: ${cur.name}` : ""));
    for (const e of combat.enemies) box.append(enemyRow(e));
    turnOptions = null;
    return;
  }
  if (c.hp <= 0) { box.append(el("div", { class: "your-turn" }, "Yerdesin! Ölüm zarı bekleniyor…")); return; }
  box.append(el("div", { class: "your-turn" }, "⚔️ SIRA SENDE!"));
  const t = turnOptions?.turn || combat.turn;
  box.append(el("div", { class: "econ" },
    el("span", { class: "chip" + (t.action > 0 ? " on" : "") }, `Eylem ${t.action > 0 ? "●" : "○"}`),
    el("span", { class: "chip" + (t.bonus > 0 ? " on" : "") }, `Bonus ${t.bonus > 0 ? "●" : "○"}`),
    el("span", { class: "chip" + (!t.moved ? " on" : "") }, `Hareket ${!t.moved ? "●" : "○"}`),
    t.attacks_left > 1 ? el("span", { class: "chip gold" }, `${t.attacks_left} saldırı`) : null,
    el("span", { class: "chip" }, c.rank === "front" ? "Ön saf" : "Arka saf")));
  const grid = el("div", { class: "act-grid" });
  const add = (icon, label, fn, on = true) => grid.append(el("button", { class: "btn" + (on ? "" : " disabled"), onclick: fn }, el("b", {}, icon), label));
  const o = turnOptions || {};
  add("⚔️", "Saldır", () => pickAttack(combat), t.action > 0 || t.attacks_left > 0);
  add("✨", "Büyü", () => pickSpell(combat), (o.spells || []).some((s) => s.available));
  add("💪", "Yetenek", () => pickFeature(combat), (o.features || []).some((f) => f.available));
  add("🧪", "Eşya", () => pickItem(), t.action > 0 && (o.items || []).length > 0);
  add(c.rank === "front" ? "⬅️" : "➡️", c.rank === "front" ? "Geri çekil" : "Öne atıl", () => cmd({ type: "move", rank: c.rank === "front" ? "back" : "front" }), !t.moved);
  add("🛡️", "Savun", () => cmd({ type: "dodge" }), t.action > 0);
  add("🤝", "Yardım et", () => pickAlly("Kime yardım edeceksin?", (id) => cmd({ type: "help", ally: id })), t.action > 0);
  add("🌑", "Saklan", () => cmd({ type: "hide" }), t.action > 0);
  add("🏃", "Kaç", () => ask("Savaştan kaçmayı deneyecek misin?", { ok: "Kaç!" }).then((ok) => ok !== null && cmd({ type: "flee" })), t.action > 0 && c.rank === "back");
  add("🎭", "Yaratıcı", () => improvise(), t.action > 0);
  add("↩️", "Kopma", () => cmd({ type: "disengage" }), t.action > 0 && c.rank === "front");
  add("⏭️", "Turu Bitir", () => cmd({ type: "end_turn" }));
  box.append(grid);
  if ((o.env || []).length) box.append(el("div", { class: "muted small" }, "Çevrede: " + o.env.map((f) => `🏚️ ${f.name}`).join(", ") + " — 'Yaratıcı' ile kullanabilirsin."));
  for (const e of combat.enemies) box.append(enemyRow(e));
}

function enemyRow(e) {
  return el("div", { class: "enemy-row" + (e.state !== "active" ? " out" : "") },
    el("div", { class: "lbl" }, e.label),
    el("div", {}, el("div", {}, e.name, e.boss ? " 👑" : ""), el("div", { class: "muted small" }, `${e.wound} · ${e.rank === "front" ? "ön" : "arka"} saf`)),
    el("div", { class: "faint small" }, e.conditions.map((k) => COND_ICONS[k] || "").join("")));
}

let busy = false;
function setBusy(v) { busy = v; }
function cmd(c) {
  if (busy) return;
  net.send({ op: "combat", cmd: c });
  turnOptions = turnOptions ? { ...turnOptions } : null;
}

function picker(title, options) {
  $("pk-cancel").textContent = "Vazgeç";
  $("pk-cancel").onclick = closePicker;
  $("pk-title").textContent = title;
  const list = $("pk-list");
  list.innerHTML = "";
  for (const o of options) {
    list.append(el("button", { class: "btn" + (o.disabled ? " disabled" : ""), onclick: () => { $("picker").classList.add("hidden"); o.fn(); } },
      el("div", {}, o.label, o.sub ? el("small", {}, o.sub) : null)));
  }
  $("picker").classList.remove("hidden");
}
$("pk-cancel").onclick = () => closePicker();

function activeEnemies(combat, melee) {
  const front = combat.enemies.filter((e) => e.state === "active" && e.rank === "front");
  return combat.enemies.filter((e) => e.state === "active").map((e) => ({ ...e, unreachable: melee && e.rank === "back" && front.length > 0 }));
}

function pickAttack(combat) {
  const atks = turnOptions?.attacks || [];
  const go = (a) => {
    const targets = activeEnemies(combat, !a.ranged);
    picker(`${a.name} — hedef seç`, targets.map((e) => ({
      label: `[${e.label}] ${e.name}`, sub: `${e.wound}${e.unreachable ? " · yakın dövüşle ulaşılamaz" : ""}`, disabled: e.unreachable,
      fn: async () => {
        let smite = null;
        if (turnOptions?.can_smite && !a.ranged) {
          smite = (await ask("Kutsal Darbe eklensin mi?", { body: "İsabet ederse 1. seviye büyü yuvası harcar, +2d8 ışık hasarı.", ok: "Evet, kutsal darbe!", cancel: "Hayır" })) !== null ? 1 : null;
        }
        cmd({ type: "attack", target: e.uid, weapon: a.uid, smite });
      } })));
  };
  if (atks.length <= 1) go(atks[0] || { name: "Yumruk", ranged: false, uid: null });
  else picker("Hangi silah?", atks.map((a) => ({ label: a.name, sub: `${a.to_hit >= 0 ? "+" : ""}${a.to_hit} isabet · ${a.damage} ${a.ranged ? "· menzilli" : ""}`, fn: () => go(a) })));
}

function pickSpell(combat) {
  const spells = (turnOptions?.spells || []);
  picker("Büyü seç", spells.map((s) => ({
    label: `${s.level === 0 ? "◌" : "◉".repeat(s.level)} ${s.name}`, disabled: !s.available,
    sub: [s.cast === "bonus" ? "bonus eylem" : "eylem", s.damage ? `hasar ${s.damage}` : "", s.heal ? `şifa ${s.heal}` : ""].filter(Boolean).join(" · "),
    fn: () => targetSpell(s, combat) })));
}

function targetSpell(s, combat) {
  const send = (targets, rank) => cmd({ type: "cast", spell: s.id, targets, rank });
  if (s.kind === "heal" || ["ally", "allies:3"].includes(s.target) || (s.kind === "buff" && s.target !== "self" && s.target !== "all_allies")) {
    pickAlly(`${s.name} — kime?`, (id) => send([`pc:${id}`]), true);
  } else if (s.target === "rank") {
    picker(`${s.name} — hangi saf?`, [{ label: "Ön saf", fn: () => send([], "front") }, { label: "Arka saf", fn: () => send([], "back") }]);
  } else if (s.target === "enemy" || s.target.startsWith("enemies")) {
    picker(`${s.name} — hedef`, activeEnemies(combat, false).map((e) => ({ label: `[${e.label}] ${e.name}`, sub: e.wound, fn: () => send([`en:${e.uid}`]) })));
  } else {
    send([]);
  }
}

function pickFeature(combat) {
  const fs = turnOptions?.features || [];
  picker("Yetenek kullan", fs.map((f) => ({
    label: f.name, sub: f.cost === "bonus" ? "bonus eylem" : f.cost === "free" ? "ücretsiz" : "eylem", disabled: !f.available,
    fn: () => {
      if (f.target === "ally") pickAlly(`${f.name} — kime?`, (id) => cmd({ type: "feature", feature: f.id, target: id }), true);
      else if (f.target === "enemy") picker("Hedef", activeEnemies(combat, false).map((e) => ({ label: `[${e.label}] ${e.name}`, fn: () => cmd({ type: "feature", feature: f.id, target: e.uid }) })));
      else cmd({ type: "feature", feature: f.id });
    } })));
}

function pickItem() {
  const items = turnOptions?.items || [];
  picker("Eşya kullan", items.map((i) => ({ label: i.name, fn: () => {
    if (i.effect === "heal" || i.effect === "stabilize") pickAlly(`${i.name} — kime?`, (id) => cmd({ type: "item", uid: i.uid, target: `pc:${id}` }), true);
    else cmd({ type: "item", uid: i.uid });
  } })));
}

function pickAlly(title, fn, includeSelf = false) {
  const c = mine();
  const allies = state.party.filter((p) => !p.dead && (includeSelf || p.id !== c.id));
  picker(title, allies.map((p) => ({ label: `${p.portrait || ""} ${p.name}${p.id === c.id ? " (sen)" : ""}`, sub: `❤️ ${p.hp}/${p.max_hp}`, fn: () => fn(p.id) })));
}

function improvise() {
  const env = (turnOptions?.env || []).map((f) => f.name).join(", ");
  ask("🎭 Yaratıcı hamle", { input: true, multiline: true, placeholder: "Örn. Avizenin ipini kesip haydutların üstüne düşürüyorum",
    body: env ? `Çevrede kullanılabilecekler: ${env}` : "Ortamı, eşyaları ya da düşmanın zayıflığını kullan.", ok: "Dene!" })
    .then((text) => { if (text && text.trim()) cmd({ type: "improvise", text: text.trim() }); });
}

// ── dice ────────────────────────────────────────────────────────────────
net.on("roll_request", (m) => {
  const c = mine();
  if (!c || m.char_id !== c.id) return;
  pendingRoll = { ...m, done: false };
  $("r-label").textContent = m.label;
  $("r-diff").textContent = [m.difficulty ? `Zorluk: ${m.difficulty}` : "", m.advantage === "advantage" ? "✅ Avantajlı (2 zar, yüksek olan)" : m.advantage === "disadvantage" ? "⚠️ Dezavantajlı (2 zar, düşük olan)" : ""].filter(Boolean).join(" · ");
  $("r-btn").classList.remove("hidden", "rolling");
  $("r-result").classList.add("hidden");
  $("roll-modal").classList.remove("hidden");
  if (navigator.vibrate) navigator.vibrate(120);
  const bar = $("r-timer");
  bar.style.transition = "none"; bar.style.width = "100%";
  requestAnimationFrame(() => { bar.style.transition = `width ${m.timeout}s linear`; bar.style.width = "0%"; });
});
$("r-btn").onclick = () => {
  if (!pendingRoll) return;
  net.send({ op: "roll", id: pendingRoll.id });
  $("r-btn").classList.add("rolling");
};
net.on("dice", (m) => {
  if (!pendingRoll || m.id !== pendingRoll.id) return;
  pendingRoll.done = true;
  $("r-btn").classList.add("hidden");
  $("r-result").classList.remove("hidden");
  const r = m.roll;
  $("r-num").textContent = r.total;
  const kept = r.dice.filter((d) => d.kept).map((d) => d.value);
  const mod = r.modifier ? ` ${r.modifier > 0 ? "+" : "−"} ${Math.abs(r.modifier)}` : "";
  $("r-out").textContent = r.dice.length > 1 || r.modifier ? `(${r.dice.map((d) => d.kept ? d.value : `~${d.value}~`).join(", ")}${mod})` : "";
  $("r-out").className = "r-out";
  if (r.natural === 20) { $("r-out").textContent = "DOĞAL 20!"; $("r-out").className = "r-out ok"; }
  if (r.natural === 1) { $("r-out").textContent = "DOĞAL 1…"; $("r-out").className = "r-out bad"; }
  setTimeout(closeRoll, 3800);
});
function showRollOutcome(res) {
  $("r-out").textContent = res.degree_tr;
  $("r-out").className = "r-out " + (res.success ? "ok" : "bad");
}
function closeRoll() { $("roll-modal").classList.add("hidden"); pendingRoll = null; }

// ── sheet ───────────────────────────────────────────────────────────────
function renderSheet(c) {
  const host = $("t-sheet");
  host.innerHTML = "";
  const abil = el("div", { class: "abil" });
  const names = { strength: "GÜÇ", dexterity: "ÇEV", constitution: "DAY", intelligence: "ZEK", wisdom: "BİL", charisma: "KAR" };
  for (const k of ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]) {
    const v = (c.abilities || {})[k];
    if (v === undefined) continue;
    abil.append(el("div", {}, el("small", {}, names[k] || k), el("b", {}, (c.mods[k] >= 0 ? "+" : "") + c.mods[k]), el("small", {}, v)));
  }
  const xpPct = c.xp_next ? Math.min(100, (100 * c.xp) / c.xp_next) : 100;
  host.append(
    el("div", { class: "card" },
      el("h3", {}, `${c.portrait || ""} ${c.name}`),
      el("div", { class: "muted small" }, `${c.race_name} ${c.class_name} · Seviye ${c.level} · ${c.gender || ""}`),
      el("div", { class: "muted small", style: { marginTop: "6px" } }, `XP ${c.xp}${c.xp_next ? ` / ${c.xp_next}` : ""}`),
      el("div", { class: "hpbar mid" }, el("div", { style: { width: `${xpPct}%` } })),
      c.can_level_up ? el("button", { class: "btn primary", style: { marginTop: "10px", width: "100%" }, onclick: () => net.send({ op: "inventory", cmd: { type: "level_up" } }) }, "⭐ Seviye Atla!") : null),
    el("div", { class: "kv" },
      el("div", {}, el("b", {}, `${c.hp}/${c.max_hp}`), "Can"), el("div", {}, el("b", {}, c.ac), "Zırh"),
      el("div", {}, el("b", {}, (c.initiative >= 0 ? "+" : "") + c.initiative), "İnisiyatif"), el("div", {}, el("b", {}, `+${c.prof}`), "Uzmanlık")),
    el("div", { class: "card" }, el("h3", {}, "Yetenekler"), abil),
    el("div", { class: "card" }, el("h3", {}, "Saldırılar"),
      el("div", { class: "list" }, ...c.attacks.map((a) => el("div", { class: "item" }, el("div", {}, el("div", { class: "nm" }, a.name), el("div", { class: "meta" }, `${a.to_hit >= 0 ? "+" : ""}${a.to_hit} isabet · ${a.damage} ${a.ranged ? "· menzilli" : ""}`)))))),
  );
  if (c.spells?.length) {
    const slots = Object.entries(c.max_spell_slots || {}).map(([lv, n]) => `${lv}. seviye: ${(c.spell_slots || {})[lv] ?? 0}/${n}`).join(" · ");
    host.append(el("div", { class: "card" }, el("h3", {}, "Büyüler"), el("div", { class: "muted small" }, `ZS ${c.spell_dc} · Saldırı +${c.spell_attack}${slots ? " · " + slots : ""}`),
      el("div", { class: "muted", style: { marginTop: "6px" } }, c.spells.join(", "))));
  }
  const skills = el("div", { class: "skills" });
  for (const [k, s] of Object.entries(c.skills)) skills.append(el("div", { class: s.proficient ? "p" : "" }, `${s.bonus >= 0 ? "+" : ""}${s.bonus} ${s.name}${s.expertise ? " ★" : ""}`));
  host.append(el("div", { class: "card" }, el("h3", {}, "Beceriler"), skills));
  if (c.conditions?.length) host.append(el("div", { class: "card" }, el("h3", {}, "Durumlar"), el("div", {}, c.conditions.map((x) => `${COND_ICONS[x.id] || "•"} ${x.id}`).join(" · "))));
  const res = Object.entries(c.max_resources || {});
  if (res.length) host.append(el("div", { class: "card" }, el("h3", {}, "Kaynaklar"), el("div", { class: "muted" }, res.map(([k, mx]) => `${k}: ${c.resources[k] ?? 0}/${mx}`).join(" · "))));
  if (c.backstory || c.personality) host.append(el("div", { class: "card" }, el("h3", {}, "Hikâyem"), el("div", { class: "muted" }, c.personality), el("div", {}, c.backstory)));
}

// ── bag ─────────────────────────────────────────────────────────────────
function inv(cmd_) { net.send({ op: "inventory", cmd: cmd_ }); }

function renderBag(c) {
  const host = $("t-bag");
  host.innerHTML = "";
  const invd = c.inventory;
  host.append(el("div", { class: "card row" }, el("div", { class: "coins grow" }, `🪙 ${invd.coins}`),
    el("button", { class: "btn small", onclick: () => giveCoins(c) }, "Altın ver")));
  const items = [...invd.items].sort((a, b) => (b.equipped_slot ? 1 : 0) - (a.equipped_slot ? 1 : 0));
  const list = el("div", { class: "list" });
  for (const it of items) {
    const acts = el("div", { class: "acts" });
    if (it.equippable) acts.append(el("button", { class: "btn small", onclick: () => inv({ type: it.equipped_slot ? "unequip" : "equip", uid: it.uid }) }, it.equipped_slot ? "Çıkar" : "Kuşan"));
    if (it.usable) acts.append(el("button", { class: "btn small", onclick: () => inv({ type: "use", uid: it.uid }) }, "Kullan"));
    acts.append(el("button", { class: "btn small ghost", onclick: () => giveItem(c, it) }, "Ver"));
    acts.append(el("button", { class: "btn small ghost", onclick: () => ask(`${it.name} yere bırakılsın mı?`, { ok: "Bırak" }).then((ok) => ok !== null && inv({ type: "drop", uid: it.uid })) }, "Bırak"));
    list.append(el("div", { class: "item" + (it.equipped_slot ? " eq" : "") + (it.kind === "quest" ? " quest" : "") },
      el("div", {}, el("div", { class: "nm" }, it.name, it.equipped_slot ? " ⚔️" : ""),
        el("div", { class: "meta" }, [it.rarity_tr, it.damage ? `hasar ${it.damage}` : "", it.value ? `${it.value} altın` : "", it.description].filter(Boolean).join(" · "))),
      acts));
  }
  host.append(el("div", { class: "card" }, el("h3", {}, `Çanta (${invd.weight} lb)`), items.length ? list : el("div", { class: "muted" }, "Boş.")));
  const here = state.world?.items_here || [];
  if (here.length) {
    const l2 = el("div", { class: "list" });
    for (const it of here) l2.append(el("div", { class: "item" }, el("div", {}, el("div", { class: "nm" }, it.name), el("div", { class: "meta" }, it.description || it.rarity_tr)),
      el("button", { class: "btn small primary", onclick: () => inv({ type: "pickup", uid: it.uid }) }, "Al")));
    host.append(el("div", { class: "card" }, el("h3", {}, "📍 Burada yerde"), l2));
  }
}

function giveItem(c, it) {
  pickAlly(`${it.name} — kime vereceksin?`, async (id) => {
    let qty = it.qty;
    if (it.qty > 1) {
      const q = parseInt(await ask(`Kaç tane? (en fazla ${it.qty})`, { input: true, value: String(it.qty), type: "number" }), 10);
      if (!q) return;
      qty = Math.min(q, it.qty);
    }
    inv({ type: "give", uid: it.uid, to: id, qty });
  });
}
function giveCoins(c) {
  pickAlly("Kime altın vereceksin?", async (id) => {
    const gp = parseFloat(await ask("Kaç altın?", { input: true, value: "1", type: "number" }));
    if (gp > 0) inv({ type: "give_coins", to: id, gp });
  });
}

// ── journal ─────────────────────────────────────────────────────────────
function renderJournal() {
  const host = $("t-journal");
  host.innerHTML = "";
  const w = state.world;
  if (!w) return;
  host.append(el("div", { class: "card" }, el("h3", {}, `📍 ${w.location.name}`), el("div", { class: "muted small" }, w.time),
    w.exits.length ? el("div", { style: { marginTop: "6px" } }, "Buradan gidilebilir: ", w.exits.map((x) => x.name).join(", ")) : null));
  if (w.quests.length) host.append(el("div", { class: "card" }, el("h3", {}, "Görevler"),
    el("div", { class: "list" }, ...w.quests.map((q) => el("div", { class: "journal-entry quest" }, el("b", {}, q.name), ` — ${q.status === "active" ? "sürüyor" : q.status === "done" ? "tamamlandı ✓" : "başarısız ✗"}`, el("div", { class: "muted small" }, q.hook))))));
  if (w.npcs_met.length) host.append(el("div", { class: "card" }, el("h3", {}, "Tanıdıklar"),
    el("div", { class: "list" }, ...w.npcs_met.map((n) => el("div", { class: "journal-entry npc" }, el("b", {}, n.name), n.role ? ` — ${n.role}` : "", n.alive ? "" : " ✝", el("div", { class: "muted small" }, n.appearance || ""))))));
  if (w.known.length) host.append(el("div", { class: "card" }, el("h3", {}, "Bilinen Yerler"),
    el("div", {}, w.known.map((k) => `${k.visited ? "✓" : "?"} ${k.name}`).join(" · "))));
  const j = [...w.journal].reverse();
  if (j.length) host.append(el("div", { class: "card" }, el("h3", {}, "Notlar"),
    el("div", { class: "list" }, ...j.map((e) => el("div", { class: `journal-entry ${e.kind}` }, `${e.day}. gün — ${e.text}`)))));
}


// ── in-app dialog (no native prompt/confirm) ────────────────────────────
function ask(title, { input = false, multiline = false, value = "", placeholder = "", body = "", ok = "Tamam", cancel = "Vazgeç", type = "text" } = {}) {
  return new Promise((resolve) => {
    $("pk-title").textContent = title;
    const list = $("pk-list");
    list.innerHTML = "";
    if (body) list.append(el("div", { class: "muted" }, body));
    let field = null;
    if (input) {
      field = multiline ? el("textarea", { rows: 3, placeholder }) : el("input", { placeholder, type, inputmode: type === "number" ? "decimal" : null });
      field.value = value;
      list.append(field);
      setTimeout(() => field.focus(), 50);
    }
    const done = (v) => { $("picker").classList.add("hidden"); $("pk-cancel").onclick = closePicker; resolve(v); };
    list.append(el("button", { class: "btn primary", onclick: () => done(field ? field.value : true) }, ok));
    $("pk-cancel").textContent = cancel;
    $("pk-cancel").onclick = () => done(null);
    $("picker").classList.remove("hidden");
  });
}
function closePicker() { $("picker").classList.add("hidden"); }

// boot
if (!localStorage.getItem(TOKEN_KEY)) show("s-join");
else show("s-join");
