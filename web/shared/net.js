// WebSocket client with automatic reconnect and a tiny pub/sub.

export class Net {
  constructor(role) {
    this.role = role;
    this.handlers = {};
    this.queue = [];
    this.retry = 0;
    this.connected = false;
    this.connect();
    setInterval(() => this.send({ op: "ping" }), 25000);
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/ws?role=${this.role}`);
    this.ws.onopen = () => {
      this.connected = true;
      this.retry = 0;
      this.emit("open");
      const q = this.queue; this.queue = [];
      q.forEach((m) => this.send(m));
    };
    this.ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this.emit(msg.t, msg);
      this.emit("*", msg);
    };
    this.ws.onclose = () => {
      this.connected = false;
      this.emit("close");
      const delay = Math.min(8000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), delay);
    };
    this.ws.onerror = () => { try { this.ws.close(); } catch {} };
  }

  send(msg) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg));
    else if (msg.op !== "ping") this.queue.push(msg);
  }

  on(t, fn) { (this.handlers[t] ||= []).push(fn); return this; }
  emit(t, msg) { (this.handlers[t] || []).forEach((fn) => { try { fn(msg); } catch (e) { console.error(e); } }); }
}

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function toast(text, kind = "info", ms = 4200) {
  let host = document.querySelector(".toast-host");
  if (!host) { host = el("div", { class: "toast-host" }); document.body.append(host); }
  const t = el("div", { class: `toast ${kind}` }, text);
  host.append(t);
  setTimeout(() => { t.style.transition = "opacity .4s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 400); }, ms);
}

export function paragraphs(text) {
  const frag = document.createDocumentFragment();
  String(text || "").split(/\n{2,}/).forEach((para) => {
    if (para.trim()) frag.append(el("p", {}, para.trim()));
  });
  return frag;
}

export const PLAYER_COLORS = ["#8c2b25", "#25588c", "#2f7a3f", "#7a4a9c", "#a8701e", "#1f7a7a"];
export const COND_ICONS = {
  prone: "🔻", restrained: "🕸️", grappled: "✊", paralyzed: "⚡", asleep: "💤", stunned: "💫", frightened: "😱",
  poisoned: "🤢", blinded: "🙈", charmed: "💗", invisible: "👻", hidden: "🌑", dodging: "🛡️", raging: "🔥",
  blessed: "✨", illuminated: "🌟", outlined: "🧚", mocked: "🤡", helped: "🤝", reckless: "😤", marked: "🎯",
  surrendered: "🏳️", shield_of_faith: "🔰", heroism: "🦸", spirit_guardians: "👼", spiritual_weapon: "🗡️",
  inspired: "🎵", mage_armor: "🔮", sacred_weapon: "⚔️", charmed_incapacitated: "🌀",
};

export function hpClass(hp, max) {
  const f = max ? hp / max : 0;
  return f > 0.6 ? "good" : f > 0.3 ? "mid" : "";
}
