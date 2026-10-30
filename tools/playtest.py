"""
Autonomous playtest: AI players + the real AI GM + the real engine.

    python -m tools.playtest --scenario degirmenkoyun_golgesi --players 3 --rounds 12 \
        --personas investigator,brawler,free_spirit

Writes a readable transcript to .runtime/playtests/<timestamp>.md plus a JSON
log of every message, so narration quality, rule calls, inventory changes,
freedom and pacing can be reviewed after the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path

from dndm.config import load_config
from dndm.game.session import GameSession
from dndm.llm.client import LLMError, OllamaClient

PERSONAS = {
    "investigator": "Dikkatli bir araştırmacısın. İpuçlarını kovalar, insanlarla konuşur, eşyaları incelersin.",
    "brawler": "Sabırsız bir kavgacısın. Tehdit eder, kapı kırar, gerekirse ilk vuran olursun.",
    "thief": "Açgözlü bir hırsızsın. Değerli şeyleri gizlice cebe atar, kilit açar, kimseye güvenmezsin.",
    "free_spirit": "Ana göreve hiç umursamazsın. Köyde kendi işini kurmak, yerlilerle arkadaş olmak, "
                   "eğlenmek ve beklenmedik şeyler denemek istersin. GM'in seni zorla görevlere itmesine izin verme.",
    "diplomat": "Barışçıl bir arabulucusun. Her sorunu konuşarak, ikna ederek, anlaşma yaparak çözmeye çalışırsın.",
    "explorer": "Meraklı bir kaşifsin. Haritada görmediğin her yere gitmek, gizli geçitleri bulmak istersin.",
}

PLAYER_SYSTEM = """\
Bir D&D masasında bir oyuncusun. Karakterini oynuyorsun. Sadece karakterinin BU TUR ne yaptığını
1-2 kısa Türkçe cümleyle yaz (birinci tekil şahıs, örn. "Hancıya yaklaşıp kayıp kızı soruyorum.").
Zar atma, sonuç yazma, başkaları adına konuşma. Kısa ve somut ol. Bazen diyalog ekleyebilirsin.
Kişiliğin: {persona}
"""


class Recorder:
    def __init__(self):
        self.msgs: list[dict] = []
        self.toasts: list[str] = []

    async def __call__(self, msg: dict, to):
        if msg.get("t") in ("state",):
            return
        self.msgs.append({"at": time.time(), **msg})
        if msg.get("t") == "toast":
            self.toasts.append(msg["text"])


async def player_action(llm: OllamaClient, ch, persona: str, narration: str, others: str) -> str:
    sheet = ch.summary_for_llm() + f"; inventory: {ch.inventory.summary_for_llm()}"
    user = (f"KARAKTERİN: {sheet}\nGRUPTAKİLER: {others}\n\nGM'İN SON ANLATIMI:\n{narration[-1500:]}\n\n"
            "Bu tur ne yapıyorsun?")
    try:
        res = await llm.complete([{"role": "user", "content": user}], system=PLAYER_SYSTEM.format(persona=persona),
                                 temperature=0.95, max_tokens=90)
        text = res.text.strip().strip('"').split("\n")[0]
        return text[:300] or "Etrafa bakıyorum."
    except LLMError:
        return "Etrafıma dikkatle bakıyorum."


async def run(args) -> Path:
    cfg = load_config()
    model = args.model or cfg.model
    gm_llm = OllamaClient(model, cfg.ollama_url, num_ctx=cfg.num_ctx, timeout=300)
    pl_llm = OllamaClient(model, cfg.ollama_url, num_ctx=4096, timeout=300)
    rec = Recorder()
    s = GameSession(gm_llm, emit=rec)
    s.settings.auto_roll = True
    s.settings.dice_animation_ms = 0
    personas = (args.personas.split(",") if args.personas else list(PERSONAS))[: args.players]
    while len(personas) < args.players:
        personas.append(random.choice(list(PERSONAS)))
    players = []
    for i in range(args.players):
        p = s.join(f"Bot{i + 1}")
        p.connected = True
        s.set_character(p.id, {"pregen": [0, 1, 2, 4, 5, 3][i % 6]})
        players.append(p)

    out_dir = Path(".runtime/playtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md = out_dir / f"{stamp}_{args.scenario or 'free'}.md"
    lines: list[str] = [f"# Playtest {stamp} — {args.scenario or 'serbest'} — model {model}", ""]
    for p, per in zip(players, personas):
        ch = s.char_of_player(p.id)
        lines.append(f"- **{ch.name}** ({ch.race_name} {ch.class_name}) — persona: {per}")
    lines.append("")

    t0 = time.time()
    await s.start(scenario_id=args.scenario or None, premise=args.premise or "")
    lines += ["## Açılış", s.narration_log[-1]["text"] if s.narration_log else "", ""]
    round_times = []
    for rnd in range(1, args.rounds + 1):
        if s.mode == "combat":
            for p in players:
                p.connected = False   # autoplay their combat turns
            while s.mode == "combat":
                await asyncio.sleep(0.5)
            for p in players:
                p.connected = True
            lines += [f"### (savaş bitti — tur {rnd})", ""]
        alive = [p for p in players if not s.char_of_player(p.id).dead]
        if not alive:
            lines.append("**Tüm grup öldü.**")
            break
        last = s.narration_log[-1]["text"] if s.narration_log else ""
        others = ", ".join(s.char_of_player(p.id).name for p in alive)
        acts = await asyncio.gather(*[player_action(pl_llm, s.char_of_player(p.id), PERSONAS[personas[players.index(p)]],
                                                    last, others) for p in alive])
        lines.append(f"## Tur {rnd} — {s.world.loc(s.scenario).name} ({s.world.time_label()})")
        before = len(rec.msgs)
        tr = time.time()
        for p, a in zip(alive, acts):
            lines.append(f"> **{s.char_of_player(p.id).name}:** {a}")
            await s.submit_action(p.id, a)
        # wait for resolution (and any combat it starts)
        for _ in range(1200):
            await asyncio.sleep(0.25)
            if not s.busy and not s.pending and s.mode != "combat":
                break
            if s.mode == "combat":
                for p in players:
                    p.connected = False
        await asyncio.gather(*list(s._tasks), return_exceptions=True)
        round_times.append(time.time() - tr)
        for m in rec.msgs[before:]:
            t = m.get("t")
            if t == "check_result":
                lines.append(f"- 🎲 {m['text']}")
            elif t == "combat_event" and m["event"].get("text") and m["event"]["type"] not in ("turn",):
                lines.append(f"  - ⚔️ {m['event']['text']}")
            elif t == "toast":
                lines.append(f"- 📣 {m['text']}")
            elif t == "narration_end":
                lines += ["", f"**GM ({m['kind']}):** {m['text']}", ""]
            elif t == "error":
                lines.append(f"- ❗ HATA: {m['text']}")
        lines.append(f"_süre: {round_times[-1]:.1f} sn_")
        lines.append("")
        md.write_text("\n".join(lines), encoding="utf-8")

    lines += ["## Son durum", f"- Mekân: {s.world.loc(s.scenario).name}, {s.world.time_label()}",
              f"- Bilinen yerler: {', '.join(l.name for l in s.world.known_locations(s.scenario))}",
              f"- Bulunan keşifler: {', '.join(s.world.found) or '-'}",
              f"- Tanışılan NPC'ler: {', '.join(n.name for n in s.world.npcs.values() if n.met)}",
              f"- Tehdit saatleri: {s.world.clocks}",
              f"- Günlük: " + " | ".join(j.text for j in s.world.journal[-12:])]
    for p in players:
        ch = s.char_of_player(p.id)
        lines.append(f"- {ch.name}: HP {ch.hp}/{ch.effective_max_hp}, XP {ch.xp}, seviye {ch.level}, "
                     f"çanta: {ch.inventory.summary_for_llm()}")
    lines.append(f"- Toplam süre: {time.time() - t0:.0f} sn, tur ortalaması "
                 f"{(sum(round_times) / max(1, len(round_times))):.1f} sn")
    md.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / f"{stamp}.json").write_text(json.dumps(rec.msgs, ensure_ascii=False, default=str), encoding="utf-8")
    await gm_llm.aclose()
    await pl_llm.aclose()
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="degirmenkoyun_golgesi")
    ap.add_argument("--premise", default="")
    ap.add_argument("--players", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--personas", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args()
    if args.scenario in ("", "free", "none"):
        args.scenario = ""
    path = asyncio.run(run(args))
    print(path)


if __name__ == "__main__":
    main()
