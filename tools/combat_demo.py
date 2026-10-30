"""
Real-model combat check: python -m tools.combat_demo [level] [monster:count ...]

Starts a scenario, then forces a fight (PC turns autoplayed) and writes every
combat beat narrated by the real GM, plus timings, to .runtime/playtests/.
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

from dndm.config import load_config
from dndm.game.combat.state import EnvFeature
from dndm.game.session import GameSession
from dndm.llm.client import OllamaClient


async def main(level: int, specs: list[dict]) -> Path:
    cfg = load_config()
    llm = OllamaClient(cfg.model, cfg.ollama_url, num_ctx=cfg.num_ctx, timeout=300)
    log: list[str] = []
    beats: list[tuple[float, str]] = []
    t_last = [time.time()]

    async def emit(msg, to):
        t = msg.get("t")
        if t == "combat_event" and msg["event"].get("text") and msg["event"]["type"] != "turn":
            log.append(f"  - {msg['event']['text']}")
        elif t == "narration_end":
            now = time.time()
            beats.append((now - t_last[0], msg["kind"]))
            t_last[0] = now
            log.append(f"\n**GM ({msg['kind']}, {beats[-1][0]:.1f} sn):** {msg['text']}\n")

    s = GameSession(llm, emit=emit)
    s.settings.auto_roll = True
    s.settings.dice_animation_ms = 0
    for i in range(3):
        p = s.join(f"Bot{i}")
        ch = s.set_character(p.id, {"pregen": [0, 2, 4][i]})
        while ch.level < level:
            ch.xp = [0, 300, 900, 2700, 6500][ch.level]
            ch.level_up()
        ch.long_rest()
    await s.start(scenario_id="degirmenkoyun_golgesi")
    t0 = time.time()
    feats = [EnvFeature(name="Devrik yük arabası", description="Yolun ortasında devrilmiş ağır bir araba.", effect="cover", damage=None),
             EnvFeature(name="Yağ fıçıları", description="Ateşe verilebilecek yağ fıçıları.", effect="hazard", damage="2d6",
                        damage_type="fire")]
    await s.start_combat(specs, features=feats, title="Kurt Patikası Pususu", ambush=True,
                         lead_in=("Kael: Haydutların ücret talebini reddedip kılıcını çekiyor.", []))
    while s.mode == "combat":
        await asyncio.sleep(0.5)
    await asyncio.gather(*list(s._tasks), return_exceptions=True)
    total = time.time() - t0
    combat_beats = [b for b, k in beats if k == "combat"]
    out = Path(".runtime/playtests") / f"{datetime.now():%Y%m%d_%H%M%S}_combat.md"
    head = [f"# Savaş denemesi — seviye {level} — {specs}", f"- Toplam süre: {total:.0f} sn",
            f"- Anlatım vuruşu: {len(combat_beats)}, ortalama {sum(combat_beats) / max(1, len(combat_beats)):.1f} sn",
            f"- Sonuç: {[ (c.name, c.hp, c.dead) for c in s.party() ]}", ""]
    out.write_text("\n".join(head + log), encoding="utf-8")
    await llm.aclose()
    return out


if __name__ == "__main__":
    lvl = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    sp = [{"monster": a.split(":")[0], "count": int(a.split(":")[1]), "name": None} for a in sys.argv[2:]] or \
        [{"monster": "bandit", "count": 3, "name": "Kurt Maskeli Haydut"}, {"monster": "thug", "count": 1, "name": "Kraz"}]
    for x in sp:
        if x["name"] is None:
            x.pop("name")
    print(asyncio.run(main(lvl, sp)))
