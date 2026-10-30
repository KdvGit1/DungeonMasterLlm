import { Net, el, toast, paragraphs, PLAYER_COLORS, COND_ICONS, hpClass } from "/static/shared/net.js";
import { DiceTray } from "/static/shared/dice3d.js";

const net = new Net("table");
const $ = (id) => document.getElementById(id);
let state = null;
let catalog = null;
let selectedScenario = null;      // scenario id or "free"
let info = null;
let tray = null;
const diceQueue = [];
let diceBusy = false;
const narrations = {};            // id -> {text, kind}
let liveId = null;

// ── boot ─────────────────────────────────────────────────────────────────
async function boot() {
  info = await (await fetch("/api/info")).json();
  const url = info.join_urls[0];
  $("qr").src = `/api/qr.svg?url=${encodeURIComponent(url)}`;
  $("qr2").src = $("qr").src;
  $("join-url").textContent = url.replace("http://", "");
  $("join-url2").textContent = url.replace("http://", "");
  $("other-urls").textContent = info.join_urls.slice(1).map((u) => u.replace("http://", "")).join(" · ");
  $("llm-status").textContent = info.llm_ok ? `🧠 ${info.model}` : "⚠️ Model sunucusu kapalı";
  $("llm-status").className = "chip " + (info.llm_ok ? "ok" : "bad");
  catalog = await (await fetch("/api/catalog")).json();
  renderScenarios();
  renderSaves();
}

function renderScenarios() {
  const list = $("scenario-list");
  list.innerHTML = "";
  const items = [...catalog.scenarios.filter((s) => !s.broken),
    { id: "free", title: "✨ Serbest Macera", pitch: "Hazır senaryo yok — dünya siz oynadıkça yazılır. İsterseniz bir fikir verin." }];
  if (!selectedScenario) selectedScenario = items[0]?.id;
  for (const s of items) {
    const card = el("div", { class: "sc" + (s.id === selectedScenario ? " sel" : ""), onclick: () => {
      selectedScenario = s.id; renderScenarios(); } },
      el("div", { class: "t" }, s.title),
      el("div", { class: "p" }, s.pitch || ""),
      s.level_range ? el("div", { class: "faint small" }, `Seviye ${s.level_range[0]}–${s.level_range[1]} · ${s.players?.[0] || 1}–${s.players?.[1] || 6} oyuncu`) : null);
    list.append(card);
  }
  $("free-premise").classList.toggle("hidden", selectedScenario !== "free");
}

async function renderSaves() {
  const { saves } = await (await fetch("/api/saves")).json();
  const host = $("save-list");
  host.innerHTML = "";
  if (!saves.length) { host.append(el("div", { class: "faint small" }, "Henüz kayıt yok.")); return; }
  for (const s of saves.slice(0, 12)) {
    const when = s.saved_at ? new Date(s.saved_at * 1000).toLocaleString("tr-TR") : "";
    host.append(el("div", { class: "save-item" },
      el("div", {}, el("div", {}, s.title || s.id), el("div", { class: "faint small" }, `${s.characters.join(", ")} · ${when}`)),
      el("button", { class: "btn small", onclick: () => net.send({ op: "load_session", id: s.id }) }, "Yükle")));
  }
}

$("start-btn").onclick = () => {
  const payload = { op: "start" };
  if (selectedScenario && selectedScenario !== "free") payload.scenario_id = selectedScenario;
  else payload.premise = $("premise").value.trim();
  $("start-btn").disabled = true;
  $("start-btn").textContent = "Başlıyor…";
  net.send(payload);
};
for (const [id, key] of [["opt-autoroll", "auto_roll"], ["opt-showdc", "show_dc"], ["opt-mercy", "mercy"]]) {
  $(id).onchange = (e) => net.send({ op: "settings", settings: { [key]: e.target.checked } });
}
$("btn-save").onclick = () => net.send({ op: "save" });
$("btn-settings").onclick = openSettings;
$("s-close").onclick = () => $("settings-modal").classList.add("hidden");
$("s-new").onclick = () => {
  if (confirm("Mevcut oyun kaydedilip yeni bir oyun başlatılsın mı?")) {
    net.send({ op: "save" });
    net.send({ op: "new_session" });
    $("settings-modal").classList.add("hidden");
  }
};
for (const [id, key] of [["s-autoroll", "auto_roll"], ["s-showdc", "show_dc"], ["s-mercy", "mercy"]]) {
  $(id).onchange = (e) => net.send({ op: "settings", settings: { [key]: e.target.checked } });
}
$("s-model").onchange = (e) => net.send({ op: "set_model", model: e.target.value });

async function openSettings() {
  $("s-autoroll").checked = state.settings.auto_roll;
  $("s-showdc").checked = state.settings.show_dc;
  $("s-mercy").checked = state.settings.mercy;
  const cfg = await (await fetch("/api/config")).json();
  const sel = $("s-model");
  sel.innerHTML = "";
  for (const m of cfg.models.length ? cfg.models : [cfg.model]) sel.append(el("option", { value: m, selected: m === cfg.model }, m));
  const host = $("s-players");
  host.innerHTML = "";
  for (const p of state.players) {
    const ch = state.party.find((c) => c.player_id === p.id);
    host.append(el("div", { class: "kick-row" }, `${p.connected ? "🟢" : "⚪"} ${p.name}${ch ? " — " + ch.name : ""}`,
      el("button", { class: "btn small ghost", onclick: () => { if (confirm(`${p.name} masadan çıkarılsın mı?`)) net.send({ op: "kick", player_id: p.id }); } }, "Çıkar")));
  }
  $("settings-modal").classList.remove("hidden");
}

let pcSeats = 1;
$("pc-seat").onclick = (e) => { e.preventDefault(); window.open(`/play?seat=pc${pcSeats++}`, "_blank"); };
$("btn-join").onclick = () => $("join-modal").classList.remove("hidden");
$("btn-full").onclick = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();

// ── state ────────────────────────────────────────────────────────────────
net.on("state", (s) => {
  state = s;
  $("booting")?.remove();
  const inLobby = s.mode === "lobby";
  $("lobby").classList.toggle("hidden", !inLobby);
  $("game").classList.toggle("hidden", inLobby);
  if (inLobby) renderLobby(); else renderGame();
});
net.on("reset", () => { for (const k in narrations) delete narrations[k]; $("history").innerHTML = ""; renderSaves(); });
net.on("toast", (m) => toast(m.text, m.kind));
net.on("error", (m) => {
  toast(m.text, "error");
  $("start-btn").disabled = false;
  $("start-btn").textContent = "⚔️ Maceraya Başla";
});
net.on("close", () => toast("Sunucu bağlantısı koptu, yeniden bağlanılıyor…", "error", 2500));

function colorFor(pid) {
  const idx = (state?.players || []).findIndex((p) => p.id === pid);
  return PLAYER_COLORS[(idx < 0 ? 0 : idx) % PLAYER_COLORS.length];
}

function renderLobby() {
  const host = $("lobby-players");
  host.innerHTML = "";
  $("player-count").textContent = `${state.players.length}/6`;
  for (const p of state.players) {
    const ch = state.party.find((c) => c.player_id === p.id);
    host.append(el("div", { class: "lp" + (p.connected ? "" : " off"), style: { "--pc": colorFor(p.id) } },
      el("div", { class: "portrait" }, ch?.portrait || "❔"),
      el("div", {},
        el("div", { class: "nm" }, ch ? ch.name : p.name),
        el("div", { class: "muted small" }, ch ? `${ch.race_name} ${ch.class_name} · ${p.name}` : "karakter seçiyor…"))));
  }
  $("lobby-hint").classList.toggle("hidden", state.players.length > 0);
  $("start-btn").disabled = !state.party.length;
  $("opt-autoroll").checked = state.settings.auto_roll;
  $("opt-showdc").checked = state.settings.show_dc;
  $("opt-mercy").checked = state.settings.mercy;
}

function renderGame() {
  const w = state.world;
  $("g-title").textContent = state.title;
  if (w) {
    $("g-location").textContent = `📍 ${w.location.name}`;
    $("g-time").textContent = `🕯️ ${w.time}`;
  }
  const combat = state.mode === "combat" && state.combat;
  renderScene(w, combat);
  $("g-mode").textContent = combat ? "⚔️ Savaş" : "🧭 Keşif";
  $("g-mode").className = "chip " + (combat ? "bad" : "ok");
  // history from server (on first load / reconnect)
  if (!Object.keys(narrations).length && state.narration?.length) {
    for (const n of state.narration) narrations[n.id] = { text: n.text, kind: n.kind };
    const last = state.narration[state.narration.length - 1];
    rebuildHistory(last?.id);
    if (last) showNarration(last.text, last.kind, false);
  }
  renderParty(combat);
  renderPending();
  renderCombat(combat);
}

function renderScene(w, combat) {
  if (!w) return;
  $("scene").classList.toggle("combat", !!combat);
  $("sc-title").textContent = combat ? `⚔️ ${combat.title || w.location.name}` : w.location.name;
  const exits = (w.exits || []).map((x) => x.name).join(" · ");
  $("sc-sub").textContent = `${w.time}${exits ? "  —  Yollar: " + exits : ""}`;
  const chips = $("sc-chips");
  chips.innerHTML = "";
  for (const n of w.npcs_here || []) chips.append(el("span", { class: "chip gold", title: n.appearance || "" }, `👤 ${n.name}${n.role ? " · " + n.role : ""}`));
  for (const it of w.items_here || []) chips.append(el("span", { class: "chip" }, `✦ ${it.name}`));
  for (const q of (w.quests || []).filter((q) => q.status === "active")) chips.append(el("span", { class: "chip ok", title: q.hook }, `📜 ${q.name}`));
}

function renderParty(combat) {
  const host = $("party");
  host.innerHTML = "";
  const cur = combat ? combat.current : null;
  for (const c of state.party) {
    const pcState = combat ? combat.party.find((p) => p.id === c.id) : null;
    const down = c.hp <= 0 && !c.dead;
    const ready = state.pending?.[c.id];
    const conds = (c.conditions || []).map((x) => (typeof x === "string" ? x : x.id));
    host.append(el("div", { class: `pc${cur === "pc:" + c.id ? " current" : ""}${down ? " down" : ""}${c.dead ? " dead" : ""}`,
      style: { "--pc": colorFor(c.player_id) } },
      el("div", { class: "portrait" }, c.portrait || "🙂"),
      el("div", {},
        el("div", { class: "nm" }, c.name),
        el("div", { class: "sub" }, `${c.race_name} ${c.class_name} ${c.level}${combat ? ` · ${c.rank === "front" ? "ön saf" : "arka saf"}` : ""}`),
        el("div", { class: "stats" }, el("span", {}, `❤️ ${c.hp}/${c.max_hp}`), el("span", {}, `🛡️ ${c.ac}`),
          down ? el("span", { class: "saves-dots" }, ...dots(c.death_saves)) : null,
          c.dead ? el("span", { class: "chip bad" }, "ÖLÜ") : null, c.stable && down ? el("span", { class: "chip" }, "istikrarlı") : null),
        el("div", { class: `hpbar ${hpClass(c.hp, c.max_hp)}` }, el("div", { style: { width: `${Math.max(0, (100 * c.hp) / c.max_hp)}%` } })),
        conds.length ? el("div", { class: "conds" }, ...conds.map((k) => el("span", { class: "chip", title: k }, `${COND_ICONS[k] || "•"} ${k}`))) : null),
      !combat && ready ? el("span", { class: "ready-dot chip ok" }, ready.private ? "🤫 hazır" : "✓ hazır") : null));
  }
}

function dots(ds) {
  const out = [];
  for (let i = 0; i < 3; i++) out.push(el("i", { class: i < (ds?.successes || 0) ? "s" : "" }));
  out.push(document.createTextNode(" "));
  for (let i = 0; i < 3; i++) out.push(el("i", { class: i < (ds?.failures || 0) ? "f" : "" }));
  return out;
}

function renderPending() {
  const bar = $("pending-bar");
  bar.innerHTML = "";
  if (state.mode !== "exploration") return;
  if (state.busy) { bar.append(el("span", { class: "thinking" }, el("span", { class: "spinner" }), "GM düşünüyor…")); return; }
  const alive = state.party.filter((c) => !c.dead);
  for (const c of alive) {
    const p = state.pending?.[c.id];
    bar.append(el("span", { class: "pend" + (p ? " ready" : "") + (p?.private ? " whisper" : "") },
      `${c.portrait || ""} ${c.name}: ${p ? (p.private ? "gizli eylem 🤫" : "hazır ✓") : "düşünüyor…"}`));
  }
  const anyReady = Object.keys(state.pending || {}).length > 0;
  if (anyReady) bar.append(el("button", { class: "btn small", onclick: () => net.send({ op: "force_round" }) }, "⏩ Beklemeden devam"));
}

function renderCombat(combat) {
  $("combat-panel").classList.toggle("hidden", !combat);
  $("narration").classList.toggle("combat", !!combat);
  if (!combat) return;
  $("c-round").textContent = combat.round > 0 ? `${combat.round}. tur` : "Hazırlık";
  const ini = $("initiative");
  ini.innerHTML = "";
  for (const o of combat.order) {
    const out = ["dead", "fled", "surrendered"].includes(o.state);
    ini.append(el("div", { class: `ini ${o.side}${o.current ? " cur" : ""}${out ? " out" : ""}` },
      el("div", {}, o.side === "enemy" ? `[${o.label}]` : (o.portrait || "")), el("div", {}, o.name), el("div", { class: "faint" }, o.init ?? "")));
  }
  const cur = ini.querySelector(".cur");
  if (cur) cur.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  const en = $("enemies");
  en.innerHTML = "";
  for (const e of combat.enemies) {
    const out = e.state !== "active";
    en.append(el("div", { class: `en ${e.rank}${out ? " out" : ""}${e.boss ? " boss" : ""}` },
      el("div", { class: "lbl" }, e.label),
      el("div", {}, el("div", {}, e.name, e.boss ? " 👑" : ""), el("div", { class: "wound" }, `${e.wound} · ${e.rank === "front" ? "ön" : "arka"}`),
        e.conditions.length ? el("div", { class: "faint small" }, e.conditions.map((k) => COND_ICONS[k] || k).join(" ")) : null),
      el("div", { class: "hpbar", style: { width: "70px" } }, el("div", { style: { width: `${Math.round(e.hp_fraction * 100)}%` } }))));
  }
  const fe = $("features");
  fe.innerHTML = "";
  for (const f of combat.features || []) fe.append(el("span", { class: "chip gold", title: f.description }, `🏚️ ${f.name}`));
}

// ── narration ───────────────────────────────────────────────────────────
net.on("narration_start", (m) => {
  if (liveId && narrations[liveId]) pushHistory(liveId);
  liveId = m.id;
  narrations[m.id] = { text: "", kind: m.kind };
  const box = $("narration");
  box.innerHTML = "";
  box.append(el("p", { class: "cursor" }));
});
net.on("narration_chunk", (m) => {
  const n = narrations[m.id];
  if (!n) return;
  n.text += m.text;
  if (m.id === liveId) showNarration(n.text, n.kind, true);
});
net.on("narration_end", (m) => {
  narrations[m.id] = { text: m.text, kind: m.kind };
  if (m.id === liveId) showNarration(m.text, m.kind, false);
});
net.on("thinking", () => {
  const box = $("narration");
  if (!box.querySelector(".cursor")) {
    if (liveId && narrations[liveId]) { pushHistory(liveId); liveId = null; }
    box.innerHTML = "";
    box.append(el("p", { class: "muted-ink pulse" }, "Zar tutan eller, fısıldayan gölgeler… GM düşünüyor."));
  }
});

function showNarration(text, kind, streaming) {
  const box = $("narration");
  box.innerHTML = "";
  box.append(paragraphs(text));
  if (streaming) {
    const last = box.lastElementChild || box.appendChild(el("p"));
    last.classList.add("cursor");
  }
  box.classList.toggle("combat", kind?.startsWith("combat") || state?.mode === "combat");
  box.scrollTop = box.scrollHeight;
}

function pushHistory(id) {
  const n = narrations[id];
  if (!n || !n.text) return;
  const h = $("history");
  h.append(el("div", { class: "past" + (n.kind === "combat" ? " combat" : "") }, paragraphs(n.text)));
  while (h.children.length > 40) h.firstChild.remove();
  h.scrollTop = h.scrollHeight;
}

function rebuildHistory(exceptId) {
  const h = $("history");
  h.innerHTML = "";
  for (const n of state.narration) {
    if (n.id === exceptId) continue;
    h.append(el("div", { class: "past" + (n.kind === "combat" ? " combat" : "") }, paragraphs(n.text)));
  }
  h.scrollTop = h.scrollHeight;
  liveId = exceptId;
}

// ── combat log ──────────────────────────────────────────────────────────
net.on("combat_event", (m) => {
  const ev = m.event;
  if (!ev.text || ev.type === "turn") return;
  const cls = ev.type === "dead" ? "dead" : ev.type === "heal" || ev.type === "revive" ? "heal" : ev.type === "damage" ? "hit" : "";
  const log = $("event-log");
  log.append(el("div", { class: `ev ${cls}` }, ev.text));
  while (log.children.length > 120) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
});
net.on("check_result", (m) => {
  const log = $("event-log");
  log.append(el("div", { class: "ev" }, `🎲 ${m.text}`));
  log.scrollTop = log.scrollHeight;
  if (currentBanner && currentBanner.char_id === m.char_id && !$("dice-banner").classList.contains("hidden")) {
    setOutcome(m.result);
  } else {
    lastCheck[m.char_id] = m.result;
  }
});
const lastCheck = {};
let currentBanner = null;

function setOutcome(res) {
  const out = $("db-outcome");
  out.textContent = res.degree_tr;
  out.className = "outcome " + (res.success ? (res.degree === "critical_success" ? "crit" : "ok") : "bad");
}

// ── dice ────────────────────────────────────────────────────────────────
net.on("roll_request", (m) => {
  const w = $("roll-wait");
  w.textContent = `🎲 ${m.char}: ${m.label}${m.difficulty ? ` (${m.difficulty})` : ""} — zar bekleniyor…`;
  w.classList.remove("hidden");
});
net.on("dice", (m) => {
  $("roll-wait").classList.add("hidden");
  diceQueue.push(m);
  if (diceQueue.length > 8) diceQueue.splice(0, diceQueue.length - 8);
  pumpDice();
});

async function pumpDice() {
  if (diceBusy) return;
  const m = diceQueue.shift();
  if (!m) return;
  diceBusy = true;
  try {
    if (!tray) tray = new DiceTray($("dice-canvas"));
    const pc = state?.party?.find((c) => c.id === m.char_id || c.name === m.char);
    const color = pc ? colorFor(pc.player_id) : "#3a3a3a";
    const quick = m.quick && diceQueue.length > 0;
    const specs = m.roll.dice.map((d) => ({ sides: d.sides, value: d.value, kept: d.kept }));
    banner(m, null);
    if (document.hidden) {
      banner(m, true);              // nobody is watching: no animation, keep the queue moving
      await sleep(150);
    } else {
      await tray.roll(specs, { color, duration: quick ? 1.1 : m.quick ? 1.6 : 2.3 });
      banner(m, true);
      await sleep(quick ? 500 : 1900);
    }
    $("dice-banner").classList.add("hidden");
    tray.clear();
    tray.renderer.render(tray.scene, tray.camera);
  } catch (e) {
    console.error(e);
  }
  diceBusy = false;
  if (diceQueue.length) pumpDice();
}

function banner(m, done) {
  currentBanner = m;
  const b = $("dice-banner");
  b.classList.remove("hidden");
  $("db-who").textContent = m.char || "";
  $("db-what").textContent = m.label || "";
  const r = m.roll;
  const kept = r.dice.filter((d) => d.kept).map((d) => d.value);
  const mod = r.modifier ? ` ${r.modifier > 0 ? "+" : "−"} ${Math.abs(r.modifier)}` : "";
  $("db-total").textContent = done ? (r.dice.length === 1 && !r.modifier ? `${r.total}` : `${kept.join(" + ")}${mod} = ${r.total}`) : "…";
  const out = $("db-outcome");
  out.textContent = "";
  out.className = "outcome";
  if (done) {
    const nat = r.natural;
    if (nat === 20) { out.textContent = "DOĞAL 20!"; out.classList.add("crit"); }
    else if (nat === 1 && r.dice.some((d) => d.sides === 20)) { out.textContent = "DOĞAL 1…"; out.classList.add("bad"); }
    const res = lastCheck[m.char_id];
    if (res && res.roll && res.roll.total === r.total) { setOutcome(res); delete lastCheck[m.char_id]; }
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

boot();
