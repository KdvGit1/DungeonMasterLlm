"""
Development LLM: canned but plausible Turkish output so the UI can be exercised
end-to-end (including combat) without a GPU. Enabled with `python -m dndm --fake-llm`.
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import AsyncIterator

from pydantic import BaseModel

from dndm.llm.client import LLMResult

NARR = [
    "Yağmur ahşap kepenkleri dövüyor. Ocaktaki ateş titreşirken gölgeler duvarlarda uzayıp kısalıyor. "
    "Köşedeki yaşlı adam başını kaldırıp size uzun uzun bakıyor, sonra bir şey fısıldıyor ama sesi gök gürültüsünde kayboluyor.",
    "Çamurlu yolda ilerledikçe ağaçlar sıklaşıyor. Uzakta bir kurt uluyor; ona bir başkası cevap veriyor. "
    "Patikanın kenarında yarı gömülü, paslı bir kılıç kabzası göze çarpıyor.",
    "Kapı gıcırdayarak açılıyor. İçerisi küf ve eski kan kokuyor. Duvardaki meşale son nefesini veriyor ve karanlık, "
    "sanki canlıymış gibi üzerinize doğru eğiliyor.",
]
COMBAT = ["Çelik çeliğe çarpıyor, kıvılcımlar karanlığı yırtıyor!", "Darbe hedefini buluyor; bir inilti, sonra sessizlik.",
          "Kılıç havayı yarıyor ama düşman son anda geri çekiliyor.", "Kan çamura karışırken savaşın uğultusu yükseliyor."]


class DevLLM:
    model = "dev-fake"

    async def complete(self, messages, *, system=None, temperature=0.8, max_tokens=600) -> LLMResult:
        await asyncio.sleep(0.2)
        return LLMResult(text="Grup köye vardı, ipuçlarını topladı ve tehlikenin büyüdüğünü fark etti.")

    async def stream(self, messages, *, system=None, temperature=0.8, max_tokens=600, stats=None) -> AsyncIterator[str]:
        last = messages[-1]["content"] if messages else ""
        text = random.choice(COMBAT) if ("COMBAT BEAT" in last or max_tokens < 200) else random.choice(NARR)
        for word in text.split(" "):
            await asyncio.sleep(0.03)
            yield word + " "

    async def structured(self, messages, schema: type[BaseModel], *, system=None, temperature=0.2, max_tokens=800):
        await asyncio.sleep(0.3)
        name = schema.__name__
        last = messages[-1]["content"] if messages else ""
        if name == "ExploreAdjudication":
            actions = re.findall(r"^([^\n:]{2,40}): (.+)$", last.split("PLAYER ACTIONS:")[-1], re.M)
            rulings, fight = [], False
            for who, act in actions:
                low = act.lower()
                if any(w in low for w in ("saldır", "vur", "öldür")):
                    fight = True
                    rulings.append({"player": who, "intent": "attack", "needs_check": False})
                elif any(w in low for w in ("ikna", "kandır", "gizli", "sessizce", "tırman", "ara")):
                    skill = "persuasion" if "ikna" in low else "deception" if "kandır" in low else \
                        "stealth" if ("gizli" in low or "sessizce" in low) else "athletics" if "tırman" in low else "investigation"
                    rulings.append({"player": who, "intent": "other", "needs_check": True,
                                    "check": {"skill": skill, "dc": 13, "advantage": "none", "reason": "belirsiz"}})
                else:
                    rulings.append({"player": who, "intent": "talk", "needs_check": False})
            obj = {"rulings": rulings, "starts_combat": fight,
                   "enemies": [{"name": "Haydut", "kind": "bandit", "count": 2}, {"name": "Kurt", "kind": "wolf", "count": 1}] if fight else [],
                   "battlefield": [{"name": "Devrik araba", "effect": "cover", "description": "Yolun ortasında devrilmiş bir araba."},
                                   {"name": "Yanan fener", "effect": "hazard", "description": "Kancaya asılı yağ dolu bir fener."}] if fight else []}
            return schema.model_validate(obj), LLMResult(text="{}")
        if name == "ImprovisedRuling":
            obj = {"feasible": True, "explanation": "", "check": {"skill": "athletics", "dc": 12, "advantage": "none", "reason": "zor"},
                   "effect": "damage_condition", "damage": "2d6", "damage_type": "bludgeoning", "condition": "prone"}
            return schema.model_validate(obj), LLMResult(text="{}")
        return schema.model_validate({}), LLMResult(text="{}")

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
