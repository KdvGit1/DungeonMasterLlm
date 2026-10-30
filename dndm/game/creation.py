"""
Character creation: ability scores, racial bonuses, starting gear, pregens.
"""

from __future__ import annotations

import random

from dndm.game.character import Character
from dndm.rules import data
from dndm.rules.core import ABILITIES, modifier

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_BUDGET = 27

# ability priority per class for auto-assigning the standard array
CLASS_PRIORITY = {
    "fighter": ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
    "barbarian": ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
    "rogue": ["dexterity", "constitution", "charisma", "wisdom", "intelligence", "strength"],
    "ranger": ["dexterity", "wisdom", "constitution", "strength", "intelligence", "charisma"],
    "paladin": ["strength", "charisma", "constitution", "wisdom", "dexterity", "intelligence"],
    "cleric": ["wisdom", "constitution", "strength", "charisma", "dexterity", "intelligence"],
    "wizard": ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],
    "bard": ["charisma", "dexterity", "constitution", "wisdom", "intelligence", "strength"],
}


class CreationError(ValueError):
    pass


def point_buy_cost(scores: dict[str, int]) -> int:
    total = 0
    for a in ABILITIES:
        v = scores.get(a, 8)
        if v not in POINT_BUY_COST:
            raise CreationError(f"{a}: puan satın almada 8-15 arası olmalı")
        total += POINT_BUY_COST[v]
    return total


def standard_array_for(cls: str) -> dict[str, int]:
    order = CLASS_PRIORITY.get(cls, ABILITIES)
    return {a: STANDARD_ARRAY[i] for i, a in enumerate(order)}


def validate_base_scores(scores: dict[str, int], method: str) -> None:
    if set(scores) != set(ABILITIES):
        raise CreationError("Altı yetenek puanının hepsi gerekli.")
    if method == "standard":
        if sorted(scores.values(), reverse=True) != STANDARD_ARRAY:
            raise CreationError("Standart dizi 15,14,13,12,10,8 değerlerinden oluşmalı.")
    elif method == "point_buy":
        cost = point_buy_cost(scores)
        if cost > POINT_BUY_BUDGET:
            raise CreationError(f"Puan bütçesi aşıldı ({cost}/{POINT_BUY_BUDGET}).")
    elif method == "rolled":
        if not all(3 <= v <= 18 for v in scores.values()):
            raise CreationError("Zarla atılan puanlar 3-18 arası olmalı.")
    else:
        raise CreationError(f"Bilinmeyen yöntem: {method}")


def roll_scores() -> list[int]:
    from dndm.rules.dice import roll
    return sorted((roll("4d6kh3").total for _ in range(6)), reverse=True)


def default_skills(cls: str, race: str) -> list[str]:
    c = data.classes()[cls]
    pref = {
        "fighter": ["athletics", "perception", "intimidation", "survival"],
        "barbarian": ["athletics", "perception", "survival", "intimidation"],
        "rogue": ["stealth", "sleight_of_hand", "perception", "deception", "acrobatics", "investigation"],
        "ranger": ["survival", "perception", "stealth", "nature"],
        "paladin": ["athletics", "persuasion", "insight", "religion"],
        "cleric": ["medicine", "insight", "religion", "persuasion"],
        "wizard": ["arcana", "investigation", "history", "insight"],
        "bard": ["persuasion", "performance", "deception", "insight", "perception"],
    }.get(cls, [])
    race_skills = set(data.races()[race].skill_proficiencies)
    allowed = [s for s in c.skill_choices["from"] if s not in race_skills]
    ordered = [s for s in pref if s in allowed] + [s for s in allowed if s not in pref]
    return ordered[: c.skill_choices["count"]]


def create_character(*, name: str, race: str, cls: str, base_scores: dict[str, int] | None = None,
                     method: str = "standard", skills: list[str] | None = None,
                     expertise: list[str] | None = None, gender: str = "", appearance: str = "",
                     personality: str = "", backstory: str = "", portrait: str = "",
                     player_id: str | None = None) -> Character:
    name = (name or "").strip()
    if not 1 <= len(name) <= 24:
        raise CreationError("İsim 1-24 karakter olmalı.")
    if race not in data.races():
        raise CreationError(f"Bilinmeyen ırk: {race}")
    if cls not in data.classes():
        raise CreationError(f"Bilinmeyen sınıf: {cls}")
    rdef, cdef = data.races()[race], data.classes()[cls]

    if base_scores is None:
        base_scores = standard_array_for(cls)
        method = "standard"
    validate_base_scores(base_scores, method)
    scores = dict(base_scores)
    for a, b in rdef.ability_bonus.items():
        scores[a] = min(20, scores.get(a, 10) + b)

    allowed = set(cdef.skill_choices["from"])
    count = cdef.skill_choices["count"] + rdef.extra_skills
    if skills is None:
        skills = default_skills(cls, race)
        if rdef.extra_skills:
            extra = [s for s in ("perception", "persuasion", "insight", "stealth", "athletics")
                     if s not in skills and s not in rdef.skill_proficiencies]
            skills += extra[: rdef.extra_skills]
    skills = list(dict.fromkeys(skills))
    if len(skills) > count:
        raise CreationError(f"En fazla {count} beceri seçebilirsin.")
    if sum(1 for s in skills if s not in allowed) > rdef.extra_skills:
        raise CreationError("Bu sınıf için geçersiz beceri seçimi.")

    exp: list[str] = []
    if cdef.expertise:
        exp = (expertise or [s for s in skills if s in ("stealth", "sleight_of_hand", "perception",
                                                         "deception", "persuasion")])[: cdef.expertise]
        exp = [s for s in exp if s in skills or s == "thieves_tools"]

    con = modifier(scores["constitution"])
    max_hp = max(1, cdef.hit_die + con + rdef.hp_per_level)

    ch = Character(name=name, race=race, cls=cls, abilities=scores, skill_proficiencies=skills,
                   expertise=exp, max_hp=max_hp, hp=max_hp, hit_dice=1, rank=cdef.default_rank,
                   gender=gender, appearance=appearance, personality=personality,
                   backstory=backstory, portrait=portrait, player_id=player_id)
    give_starting_equipment(ch)
    ch.resources = ch.max_resources()
    ch.spell_slots = ch.max_spell_slots()
    return ch


def give_starting_equipment(ch: Character) -> None:
    inv = ch.inventory
    for entry in ch.class_def.starting_equipment:
        if isinstance(entry, dict):
            iid, qty = next(iter(entry.items()))
        else:
            iid, qty = entry, 1
        inv.add(iid, qty)
    inv.add_coins(gp=10 + random.randint(0, 15))
    # auto-equip: armor, best melee or ranged weapon, shield
    armor = next((s for s in inv.items if s.definition and s.definition.type == "armor"), None)
    if armor:
        inv.equip(armor.uid, strength=ch.score("strength"))
    weapons = [s for s in inv.items if s.weapon_def is not None]
    if weapons:
        prefer_ranged = ch.rank == "back" and ch.cls in ("ranger",)
        def score(s):
            w = s.weapon_def
            ranged = w.is_ranged
            avg = sum((int(t.split("d")[0] or 1) * (int(t.split("d")[1]) + 1) / 2)
                      for t in (w.damage or "1d1").split("+") if "d" in t)
            return (ranged == prefer_ranged, avg)
        best = max(weapons, key=score)
        inv.equip(best.uid)
    shield = next((s for s in inv.items if s.definition and s.definition.type == "shield"), None)
    if shield:
        try:
            inv.equip(shield.uid)
        except Exception:
            pass


PREGENS = [
    dict(name="Kael Demirkol", race="human", cls="fighter", gender="erkek",
         appearance="Geniş omuzlu, yüzünde eski bir kılıç izi, kısa kesilmiş kara saç.",
         personality="Az konuşur, sözünü tutar, zayıfı korur.",
         backstory="Sınır kalesinde on yıl nöbet tuttu; komutanı ihanet edince kılıcını alıp yola çıktı.",
         portrait="🛡️"),
    dict(name="Lira Gölgeayak", race="half_elf", cls="rogue", gender="kadın",
         appearance="İnce yapılı, kapüşonlu, yeşil gözleri hep bir çıkış yolu arar.",
         personality="Alaycı, meraklı, parayı sever ama dostunu satmaz.",
         backstory="Liman şehrinin hırsızlar loncasından kaçtı; lonca hâlâ peşinde.",
         portrait="🗝️"),
    dict(name="Brenna Taşkalp", race="dwarf", cls="cleric", gender="kadın",
         appearance="Örgülü kızıl sakal halkalı, ağır kalkan, gümüş çekiç sembolü.",
         personality="Neşeli, inatçı, ölüleri onurlandırmaya önem verir.",
         backstory="Cüce dağ tapınağının şifacısı; kayıp kardeşinin izini sürüyor.",
         portrait="🔨"),
    dict(name="Thorne Yaprakgölge", race="elf", cls="ranger", gender="erkek",
         appearance="Uzun gümüş saçlı, yeşil pelerinli, sırtında uzun yay.",
         personality="Sakin, sabırlı, şehirlerden hoşlanmaz.",
         backstory="Ormanını yakan haydutların sonuncusunu arıyor.",
         portrait="🏹"),
    dict(name="Mira Kül", race="human", cls="wizard", gender="kadın",
         appearance="Mürekkep lekeli parmaklar, gözlükler, kenarları yanmış cübbe.",
         personality="Bilgiye aç, aceleci, deneylerinden vazgeçmez.",
         backstory="Akademiden yasak bir kitabı 'ödünç' aldığı için kovuldu.",
         portrait="🔥"),
    dict(name="Dorn Kanpençe", race="half_orc", cls="barbarian", gender="erkek",
         appearance="Dev cüsseli, dövmeli kollar, kırık bir diş.",
         personality="Gürültücü, cömert, öfkesi bir fırtına gibi gelip geçer.",
         backstory="Kabilesi tarafından sürgün edildi; yeni bir aile arıyor.",
         portrait="🪓"),
    dict(name="Aldric Işıkyemin", race="dragonborn", cls="paladin", gender="erkek",
         appearance="Bronz pullu, parlak zırhlı, pelerininde güneş arması.",
         personality="Onurlu, ciddi, adaletsizliğe dayanamaz.",
         backstory="Tapınağını yağmalayan tarikatı yok etmeye yemin etti.",
         portrait="☀️"),
    dict(name="Pip Tatlıdil", race="halfling", cls="bard", gender="erkek",
         appearance="Kıvırcık saçlı, renkli yelekli, lavtası hep omzunda.",
         personality="Şakacı, flörtöz, herkesle dost olur.",
         backstory="Bir soylunun düğününde fazla dürüst bir şarkı söyledi; şimdi kaçak.",
         portrait="🎻"),
]


def make_pregen(index: int, player_id: str | None = None) -> "Character":
    spec = dict(PREGENS[index % len(PREGENS)])
    return create_character(player_id=player_id, **spec)
