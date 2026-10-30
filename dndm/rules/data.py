"""
Typed access to the YAML game data (items, races, classes, spells, monsters).

Loaded once and cached. ``validate_all()`` cross-checks references and is run
by the test-suite so broken data never ships.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dndm.paths import data_dir
from dndm.rules.dice import parse as parse_dice


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class ItemDef(_Base):
    id: str = ""
    name: str
    type: str
    value: float = 0
    weight: float = 0
    rarity: str = "common"
    stack: bool = False
    # weapons
    category: str | None = None
    damage: str | None = None
    damage_type: str | None = None
    properties: list[str] = Field(default_factory=list)
    versatile: str | None = None
    range: list[int] | None = None
    ammo: str | None = None
    # armor / shields
    armor_type: str | None = None
    ac: int | None = None
    dex_cap: int | None = None
    str_req: int | None = None
    stealth_disadvantage: bool = False
    ac_bonus: int | None = None
    # consumables / magic
    effect: str | None = None
    amount: str | int | None = None
    slot: str | None = None
    attune: bool = False

    @property
    def is_weapon(self) -> bool:
        return self.type == "weapon" or (self.type == "magic" and getattr(self, "base", None) is not None)

    @property
    def is_ranged(self) -> bool:
        return bool(self.category and self.category.endswith("ranged"))


class RaceDef(_Base):
    id: str = ""
    name: str
    description: str = ""
    ability_bonus: dict[str, int] = Field(default_factory=dict)
    speed: int = 30
    darkvision: bool = False
    skill_proficiencies: list[str] = Field(default_factory=list)
    resistances: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    hp_per_level: int = 0
    extra_skills: int = 0


class ClassDef(_Base):
    id: str = ""
    name: str
    description: str = ""
    hit_die: int
    primary: list[str]
    saves: list[str]
    armor: list[str] = Field(default_factory=list)
    weapons: list[str] = Field(default_factory=list)
    skill_choices: dict[str, Any]
    features: dict[int, list[str]] = Field(default_factory=dict)
    resources: dict[str, dict] = Field(default_factory=dict)
    spellcasting: dict[str, Any] | None = None
    cantrips: list[str] = Field(default_factory=list)
    spells: dict[int, list[str]] = Field(default_factory=dict)
    starting_equipment: list[Any] = Field(default_factory=list)
    default_rank: str = "front"
    expertise: int = 0
    unarmored_defense: list[str] | None = None

    def features_up_to(self, level: int) -> list[str]:
        out: list[str] = []
        for lvl in sorted(self.features):
            if lvl <= level:
                out.extend(self.features[lvl])
        return out

    def spells_up_to(self, level: int) -> list[str]:
        out: list[str] = []
        for lvl in sorted(self.spells):
            if lvl <= level:
                out.extend(self.spells[lvl])
        return out


class SpellDef(_Base):
    id: str = ""
    name: str
    level: int
    school: str
    cast: str = "action"
    kind: str
    target: str = "enemy"
    ranged: bool = True
    damage: str | None = None
    damage_type: str | None = None
    heal: str | None = None
    save: str | None = None
    half: bool = False
    scale: str | None = None
    upcast: str | None = None
    concentration: bool = False
    rounds: int | None = None
    condition: str | None = None
    effect: dict[str, Any] = Field(default_factory=dict)
    utility: bool = False


class MonsterAttack(_Base):
    id: str
    name: str
    hit: int
    dmg: str
    type: str
    range: list[int] | None = None
    recharge: int | None = None
    on_hit: dict[str, Any] = Field(default_factory=dict)


class MonsterDef(_Base):
    id: str = ""
    name: str
    cr: float
    xp: int
    ac: int
    hp: str
    abilities: dict[str, int]
    attacks: list[MonsterAttack]
    multiattack: list[str] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    spellcasting: dict[str, Any] | None = None
    traits: list[str] = Field(default_factory=list)
    resistances: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    skills: dict[str, int] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    loot: dict[str, Any] = Field(default_factory=dict)
    behavior: dict[str, Any] = Field(default_factory=dict)
    homebrew: bool = False

    def attack(self, attack_id: str) -> MonsterAttack:
        for a in self.attacks:
            if a.id == attack_id:
                return a
        raise KeyError(f"{self.id} has no attack {attack_id}")


def _load(name: str) -> dict:
    path = Path(data_dir()) / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _typed(name: str, model: type[_Base]) -> dict[str, Any]:
    raw = _load(name)
    return {k: model.model_validate({**v, "id": k}) for k, v in raw.items()}


@lru_cache(maxsize=None)
def items() -> dict[str, ItemDef]:
    return _typed("items", ItemDef)


@lru_cache(maxsize=None)
def races() -> dict[str, RaceDef]:
    return _typed("races", RaceDef)


@lru_cache(maxsize=None)
def classes() -> dict[str, ClassDef]:
    return _typed("classes", ClassDef)


@lru_cache(maxsize=None)
def spells() -> dict[str, SpellDef]:
    return _typed("spells", SpellDef)


@lru_cache(maxsize=None)
def monsters() -> dict[str, MonsterDef]:
    return _typed("monsters", MonsterDef)


def item(item_id: str) -> ItemDef:
    return items()[item_id]


def monster(monster_id: str) -> MonsterDef:
    return monsters()[monster_id]


def spell(spell_id: str) -> SpellDef:
    return spells()[spell_id]


def validate_all() -> list[str]:
    """Return a list of human-readable problems (empty = data is consistent)."""
    problems: list[str] = []
    its, sps, mons = items(), spells(), monsters()

    def check_dice(where: str, notation: str | None) -> None:
        if not notation or notation in ("0", "mod"):
            return
        try:
            parse_dice(str(notation))
        except ValueError as e:
            problems.append(f"{where}: bad dice {notation!r} ({e})")

    for iid, it in its.items():
        check_dice(f"item {iid}.damage", it.damage)
        check_dice(f"item {iid}.versatile", it.versatile)
        if isinstance(it.amount, str):
            check_dice(f"item {iid}.amount", it.amount)
        if it.ammo and it.ammo not in its:
            problems.append(f"item {iid}: unknown ammo {it.ammo}")
        base = getattr(it, "base", None)
        if base and base not in its:
            problems.append(f"item {iid}: unknown base {base}")
        spell_ref = getattr(it, "spell", None)
        if spell_ref and spell_ref not in sps:
            problems.append(f"item {iid}: unknown spell {spell_ref}")

    for cid, c in classes().items():
        for sid in c.cantrips + [s for lst in c.spells.values() for s in lst]:
            if sid not in sps:
                problems.append(f"class {cid}: unknown spell {sid}")
        for entry in c.starting_equipment:
            iid = next(iter(entry)) if isinstance(entry, dict) else entry
            if iid not in its:
                problems.append(f"class {cid}: unknown starting item {iid}")

    for sid, s in sps.items():
        for f in ("damage", "heal", "scale", "upcast"):
            check_dice(f"spell {sid}.{f}", getattr(s, f))

    for mid, m in mons.items():
        check_dice(f"monster {mid}.hp", m.hp)
        ids = {a.id for a in m.attacks}
        for a in m.attacks:
            if a.dmg != "0":
                check_dice(f"monster {mid}.{a.id}", a.dmg)
        for ma in m.multiattack:
            if ma not in ids:
                problems.append(f"monster {mid}: multiattack refers to unknown attack {ma}")
        if m.spellcasting:
            for sid in m.spellcasting.get("spells", []):
                if sid not in sps:
                    problems.append(f"monster {mid}: unknown spell {sid}")
        for iid in (m.loot.get("items") or {}):
            if iid not in its:
                problems.append(f"monster {mid}: unknown loot item {iid}")
    return problems
