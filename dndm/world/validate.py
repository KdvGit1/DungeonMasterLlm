"""
Scenario validation: structure + "does this stay in a classic D&D world?"

Checks:
* structural problems (broken exits, unknown monsters/items, unreachable places)
* anachronisms / modern technology / sci-fi words (Turkish and English)
* proprietary setting names that would break originality (Forgotten Realms etc.)
* every NPC that can fight uses a stat block from the SRD-based monster list
"""

from __future__ import annotations

import re

from dndm.text import fold
from dndm.world.scenario import Scenario

ANACHRONISMS = [
    # modern tech
    "telefon", "bilgisayar", "internet", "elektrik", "otomobil", "otobüs", "uçak", "tren", "televizyon",
    "radyo", "tabanca", "tüfek", "silah sesi", "mermi", "bomba", "roket", "lazer", "robot", "plastik", "beton",
    "asfalt", "fabrika", "polis", "ambulans", "hastane", "kamera", "fotoğraf", "saat kulesi elektrikli",
    "smartphone", "computer", "electricity", "pistol", "rifle", "bullet", "gunpowder", "laser", "robot", "police",
    # sci-fi / other genres
    "uzay gemisi", "uzaylı", "spaceship", "alien", "cyborg", "nükleer", "nuclear", "zombi virüsü", "virus",
]
# names owned by specific published settings; the game should use its own
PROPRIETARY = [
    "faerun", "faerûn", "waterdeep", "baldur's gate", "neverwinter", "drizzt", "elminster", "forgotten realms",
    "greyhawk", "eberron", "ravenloft", "strahd", "barovia", "dragonlance", "krynn", "bahamut", "tiamat",
    "mordenkainen", "beholder", "mind flayer", "illithid", "githyanki", "displacer beast",
]


def _all_text(sc: Scenario) -> str:
    parts = [sc.title, sc.pitch, sc.premise, sc.opening, sc.style_notes, *sc.truths, *sc.endings, *sc.random_events]
    for loc in sc.locations.values():
        parts += [loc.name, loc.description, loc.gm_notes]
        for d in loc.discoveries:
            parts += [d.hint, d.reveals]
        for e in loc.encounters:
            parts += [e.when] + [str(x.get("name", "")) for x in e.enemies]
            parts += [str(f.get("name", "")) + " " + str(f.get("description", "")) for f in e.features]
    for n in sc.npcs.values():
        parts += [n.name, n.role, n.appearance, n.personality, n.voice, n.wants, n.secret, *n.knows]
    for f in sc.fronts.values():
        parts += [f.name, f.description, f.on_complete, *f.stages.values()]
    for q in sc.quests.values():
        parts += [q.name, q.hook, *q.objectives]
    return "\n".join(p for p in parts if p)


def lore_problems(sc: Scenario) -> list[str]:
    text = fold(_all_text(sc))
    out = []
    for word in ANACHRONISMS:
        if re.search(rf"\b{re.escape(fold(word))}", text):
            out.append(f"anachronism / genre break: '{word}'")
    for name in PROPRIETARY:
        if fold(name) in text:
            out.append(f"proprietary setting name: '{name}' (use an original name)")
    return out


def validate(sc: Scenario) -> list[str]:
    return sc.problems() + lore_problems(sc)
