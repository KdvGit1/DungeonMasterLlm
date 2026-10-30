"""
Player characters: stats, derived values, HP/death saves, resources, leveling.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from dndm.game.inventory import Inventory
from dndm.rules import data
from dndm.rules.core import (ABILITIES, SKILL_ABILITY, SKILL_TR, ability_for, modifier,
                             proficiency_bonus)
from dndm.rules.dice import roll

XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000]
MAX_LEVEL = 10

FULL_CASTER_SLOTS = {1: {1: 2}, 2: {1: 3}, 3: {1: 4, 2: 2}, 4: {1: 4, 2: 3}, 5: {1: 4, 2: 3, 3: 2},
                     6: {1: 4, 2: 3, 3: 3}, 7: {1: 4, 2: 3, 3: 3}, 8: {1: 4, 2: 3, 3: 3},
                     9: {1: 4, 2: 3, 3: 3}, 10: {1: 4, 2: 3, 3: 3}}
HALF_CASTER_SLOTS = {1: {}, 2: {1: 2}, 3: {1: 3}, 4: {1: 3}, 5: {1: 4, 2: 2}, 6: {1: 4, 2: 2},
                     7: {1: 4, 2: 3}, 8: {1: 4, 2: 3}, 9: {1: 4, 2: 3, 3: 2}, 10: {1: 4, 2: 3, 3: 2}}

Rank = Literal["front", "back"]


def _cid() -> str:
    return uuid.uuid4().hex[:8]


class Condition(BaseModel):
    id: str
    rounds: int | None = None          # None = until removed
    source: str = ""
    save: str | None = None            # ability to repeat save at end of turn
    dc: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class DeathSaves(BaseModel):
    successes: int = 0
    failures: int = 0


class Character(BaseModel):
    id: str = Field(default_factory=_cid)
    name: str
    race: str
    cls: str
    level: int = 1
    xp: int = 0
    abilities: dict[str, int]
    skill_proficiencies: list[str] = Field(default_factory=list)
    expertise: list[str] = Field(default_factory=list)
    max_hp: int
    hp: int
    temp_hp: int = 0
    max_hp_bonus: int = 0
    hit_dice: int = 1
    death_saves: DeathSaves = Field(default_factory=DeathSaves)
    stable: bool = False
    dead: bool = False
    conditions: list[Condition] = Field(default_factory=list)
    resources: dict[str, int] = Field(default_factory=dict)      # remaining uses
    spell_slots: dict[int, int] = Field(default_factory=dict)    # remaining by level
    concentration: str | None = None
    inventory: Inventory = Field(default_factory=Inventory)
    rank: Rank = "front"
    gender: str = ""
    appearance: str = ""
    personality: str = ""
    backstory: str = ""
    portrait: str = ""
    player_id: str | None = None
    notes: list[str] = Field(default_factory=list)

    # ── definitions ─────────────────────────────────────────────
    @property
    def race_def(self):
        return data.races()[self.race]

    @property
    def class_def(self):
        return data.classes()[self.cls]

    @property
    def race_name(self) -> str:
        return self.race_def.name

    @property
    def class_name(self) -> str:
        return self.class_def.name

    @property
    def features(self) -> list[str]:
        return self.class_def.features_up_to(self.level) + list(self.race_def.traits)

    def has(self, feature: str) -> bool:
        return feature in self.features

    # ── core numbers ────────────────────────────────────────────
    @property
    def prof(self) -> int:
        return proficiency_bonus(self.level)

    def score(self, ability: str) -> int:
        base = self.abilities.get(ability, 10)
        for slot in ("hands", "neck"):
            s = self.inventory.equipped_stack(slot)
            d = s.definition if s else None
            setv = getattr(d, "set_ability", None) if d else None
            if setv and ability in setv:
                base = max(base, setv[ability])
        return base

    def mod(self, ability: str) -> int:
        return modifier(self.score(ability))

    def skill_bonus(self, key: str) -> int:
        ability = ability_for(key)
        bonus = self.mod(ability)
        if key in SKILL_ABILITY:
            proficient = key in self.skill_proficiencies or key in self.race_def.skill_proficiencies
            if proficient:
                bonus += self.prof * (2 if key in self.expertise else 1)
            elif self.has("jack_of_all_trades"):
                bonus += self.prof // 2
        return bonus

    def save_bonus(self, ability: str) -> int:
        bonus = self.mod(ability)
        if ability in self.class_def.saves:
            bonus += self.prof
        for slot in ("cloak", "ring1", "ring2"):
            s = self.inventory.equipped_stack(slot)
            d = s.definition if s else None
            if d is not None:
                bonus += int(getattr(d, "save_bonus", 0) or 0)
        return bonus

    @property
    def initiative_bonus(self) -> int:
        return self.mod("dexterity")

    @property
    def passive_perception(self) -> int:
        return 10 + self.skill_bonus("perception")

    @property
    def effective_max_hp(self) -> int:
        return self.max_hp + self.max_hp_bonus

    # ── armor class ─────────────────────────────────────────────
    def armor_class(self, extra: int = 0) -> int:
        dex = self.mod("dexterity")
        armor = self.inventory.armor()
        ad = armor.definition if armor else None
        if ad is not None and ad.ac is not None:
            cap = ad.dex_cap
            dex_part = dex if cap is None else min(dex, cap)
            ac = ad.ac + dex_part + armor.magic_bonus
            if self.has("fighting_style_defense"):
                ac += 1
        elif self.has("unarmored_defense") and self.class_def.unarmored_defense:
            ac = 10 + sum(self.mod(a) for a in self.class_def.unarmored_defense)
        else:
            ac = 10 + dex
            if self.has_condition("mage_armor"):
                ac = max(ac, 13 + dex)
        off = self.inventory.off_hand()
        od = off.definition if off else None
        if od is not None and od.ac_bonus:
            ac += od.ac_bonus
        for slot in ("cloak", "ring1", "ring2"):
            s = self.inventory.equipped_stack(slot)
            d = s.definition if s else None
            if d is not None and d.ac_bonus:
                ac += d.ac_bonus
        for c in self.conditions:
            ac += int(c.data.get("ac_bonus", 0))
        return ac + extra

    # ── weapons ─────────────────────────────────────────────────
    def proficient_with(self, weapon_id: str) -> bool:
        w = data.items().get(weapon_id)
        if w is None or w.category is None:
            return False
        allowed = self.class_def.weapons
        group = "simple" if w.category.startswith("simple") else "martial"
        return group in allowed or weapon_id in allowed

    def weapon_profile(self, stack=None) -> dict:
        """Attack bonus / damage for a weapon stack (default: equipped main hand, else unarmed)."""
        stack = stack if stack is not None else self.inventory.weapon()
        wdef = stack.weapon_def if stack else None
        if wdef is None:
            mod = self.mod("strength")
            return {"name": "Yumruk", "to_hit": mod + self.prof, "damage": f"1+{max(0, mod)}" if mod > 0 else "1",
                    "damage_dice": "1", "damage_mod": max(0, mod), "type": "bludgeoning", "ranged": False,
                    "ability": "strength", "properties": [], "uid": None, "magic": 0}
        props = wdef.properties
        ranged = wdef.is_ranged
        if ranged:
            ability = "dexterity"
        elif "finesse" in props:
            ability = "dexterity" if self.mod("dexterity") >= self.mod("strength") else "strength"
        else:
            ability = "strength"
        mod = self.mod(ability)
        magic = stack.magic_bonus if stack else 0
        to_hit = mod + magic + (self.prof if self.proficient_with(wdef.id) else 0)
        dmg_mod = mod + magic
        if ranged and self.has("fighting_style_archery"):
            to_hit += 2
        off = self.inventory.off_hand()
        off_is_weapon = off is not None and off.weapon_def is not None
        if not ranged and self.has("fighting_style_dueling") and "two_handed" not in props and not off_is_weapon:
            dmg_mod += 2
        dice = wdef.damage or "1"
        if "versatile" in props and wdef.versatile and self.inventory.off_hand() is None:
            dice = wdef.versatile
        sign = "+" if dmg_mod >= 0 else "-"
        return {
            "name": stack.display_name() if stack else wdef.name, "to_hit": to_hit,
            "damage": f"{dice}{sign}{abs(dmg_mod)}" if dmg_mod else dice,
            "damage_dice": dice, "damage_mod": dmg_mod, "type": wdef.damage_type or "bludgeoning",
            "ranged": ranged, "ability": ability, "properties": props, "uid": stack.uid if stack else None,
            "magic": magic, "range": wdef.range, "ammo": wdef.ammo,
            "extra_damage": getattr(stack.definition, "extra_damage", None) if stack and stack.definition else None,
            "extra_damage_type": getattr(stack.definition, "extra_damage_type", None)
            if stack and stack.definition else None,
        }

    def attack_options(self) -> list[dict]:
        """All weapons in the pack the character could swing/shoot this turn."""
        opts = []
        seen = set()
        main = self.inventory.weapon()
        if main:
            opts.append(self.weapon_profile(main))
            seen.add(main.uid)
        for s in self.inventory.items:
            if s.uid in seen or s.weapon_def is None:
                continue
            p = self.weapon_profile(s)
            if p["ammo"] and self.inventory.count(p["ammo"]) == 0:
                continue
            opts.append(p)
            seen.add(s.uid)
        if not opts:
            opts.append(self.weapon_profile(None))
        return opts

    # ── spellcasting ────────────────────────────────────────────
    @property
    def spellcasting(self) -> dict | None:
        sc = self.class_def.spellcasting
        if not sc or self.level < sc.get("from_level", 1):
            return None
        return sc

    @property
    def spell_ability(self) -> str | None:
        sc = self.spellcasting
        return sc["ability"] if sc else None

    @property
    def spell_dc(self) -> int:
        a = self.spell_ability
        return 8 + self.prof + (self.mod(a) if a else 0)

    @property
    def spell_attack(self) -> int:
        a = self.spell_ability
        return self.prof + (self.mod(a) if a else 0)

    def max_spell_slots(self) -> dict[int, int]:
        sc = self.spellcasting
        if not sc:
            return {}
        table = FULL_CASTER_SLOTS if sc["type"] == "full" else HALF_CASTER_SLOTS
        return dict(table.get(self.level, {}))

    def known_spells(self) -> list[str]:
        if not self.spellcasting:
            return []
        max_slot = max(self.max_spell_slots() or {0: 0})
        known = list(self.class_def.cantrips)
        for sid in self.class_def.spells_up_to(self.level):
            if data.spell(sid).level <= max_slot:
                known.append(sid)
        if self.race_def.model_extra and self.race_def.model_extra.get("bonus_cantrip") and "fire_bolt" not in known:
            known.append("fire_bolt")
        return known

    # ── resources ───────────────────────────────────────────────
    def max_resources(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for rid, spec in self.class_def.resources.items():
            if self.level < spec.get("from_level", 1):
                continue
            if "uses" in spec:
                out[rid] = spec["uses"]
            elif "uses_by_level" in spec:
                val = 0
                for lvl, n in sorted(spec["uses_by_level"].items()):
                    if self.level >= lvl:
                        val = n
                out[rid] = val
            elif "pool_per_level" in spec:
                out[rid] = spec["pool_per_level"] * self.level
            elif spec.get("uses_formula") == "cha":
                out[rid] = max(1, self.mod("charisma"))
            elif spec.get("uses_formula") == "1+cha":
                out[rid] = 1 + max(0, self.mod("charisma"))
        return out

    def sneak_attack_dice(self) -> str | None:
        return f"{(self.level + 1) // 2}d6" if self.has("sneak_attack") else None

    def bardic_die(self) -> str:
        return "1d6" if self.level < 5 else "1d8"

    # ── conditions ──────────────────────────────────────────────
    def has_condition(self, cid: str) -> bool:
        return any(c.id == cid for c in self.conditions)

    def add_condition(self, cond: Condition) -> None:
        self.conditions = [c for c in self.conditions if c.id != cond.id]
        self.conditions.append(cond)

    def remove_condition(self, cid: str) -> None:
        self.conditions = [c for c in self.conditions if c.id != cid]

    # ── HP, damage, death ───────────────────────────────────────
    @property
    def is_down(self) -> bool:
        return self.hp <= 0 and not self.dead

    @property
    def can_act(self) -> bool:
        if self.dead or self.hp <= 0:
            return False
        return not any(c.id in ("paralyzed", "stunned", "asleep", "incapacitated", "petrified",
                                "charmed_incapacitated") for c in self.conditions)

    def take_damage(self, amount: int, *, damage_type: str = "", critical: bool = False) -> dict:
        """Apply damage with resistances, temp HP, massive damage and death-save failures."""
        result = {"raw": amount, "taken": 0, "dropped": False, "died": False, "resisted": False}
        if amount <= 0 or self.dead:
            return result
        resist = set(self.race_def.resistances)
        if self.has_condition("raging") and damage_type in ("bludgeoning", "piercing", "slashing"):
            resist |= {damage_type}
        if damage_type and damage_type in resist:
            amount //= 2
            result["resisted"] = True
        if self.hp <= 0:
            # hit while dying: automatic death-save failure(s)
            self.death_saves.failures += 2 if critical else 1
            self.stable = False
            if amount >= self.effective_max_hp or self.death_saves.failures >= 3:
                self.dead = True
                result["died"] = True
            result["taken"] = amount
            return result
        if self.temp_hp:
            absorbed = min(self.temp_hp, amount)
            self.temp_hp -= absorbed
            amount -= absorbed
        result["taken"] = amount
        self.hp -= amount
        if self.hp <= 0:
            overflow = -self.hp
            self.hp = 0
            if self.has("relentless_endurance") and not self.resources.get("relentless_used") \
                    and overflow < self.effective_max_hp:
                self.hp = 1
                self.resources["relentless_used"] = 1
                result["relentless"] = True
                return result
            if overflow >= self.effective_max_hp:
                self.dead = True
                result["died"] = True
            else:
                result["dropped"] = True
                self.death_saves = DeathSaves()
                self.stable = False
            self.concentration = None
        return result

    def heal(self, amount: int) -> int:
        if self.dead or amount <= 0:
            return 0
        before = self.hp
        self.hp = min(self.effective_max_hp, self.hp + amount)
        if before <= 0 < self.hp:
            self.death_saves = DeathSaves()
            self.stable = False
        return self.hp - before

    def roll_death_save(self) -> dict:
        r = roll("1d20")
        nat = r.natural or r.total
        out = {"roll": r.to_dict(), "natural": nat, "result": ""}
        if nat == 20:
            self.hp = 1
            self.death_saves = DeathSaves()
            out["result"] = "revived"
        elif nat == 1:
            self.death_saves.failures += 2
            out["result"] = "double_fail"
        elif nat >= 10:
            self.death_saves.successes += 1
            out["result"] = "success"
        else:
            self.death_saves.failures += 1
            out["result"] = "fail"
        if self.death_saves.failures >= 3:
            self.dead = True
            out["result"] = "dead"
        elif self.death_saves.successes >= 3:
            self.stable = True
            out["result"] = "stable"
        return out

    # ── rests ───────────────────────────────────────────────────
    def short_rest(self) -> dict:
        spent = 0
        healed = 0
        while self.hp < self.effective_max_hp // 2 and self.hit_dice > 0 and not self.dead:
            self.hit_dice -= 1
            spent += 1
            healed += self.heal(max(1, roll(f"1d{self.class_def.hit_die}").total + self.mod("constitution")))
        for rid, spec in self.class_def.resources.items():
            if spec.get("recharge") == "short_rest" or \
                    (spec.get("recharge_from_level_5") == "short_rest" and self.level >= 5):
                if rid in self.max_resources():
                    self.resources[rid] = self.max_resources()[rid]
        if self.cls == "wizard" and self.resources.get("arcane_recovery", 0) > 0:
            mx = self.max_spell_slots()
            for lvl in sorted(mx):
                if self.spell_slots.get(lvl, 0) < mx[lvl]:
                    self.spell_slots[lvl] = self.spell_slots.get(lvl, 0) + 1
                    self.resources["arcane_recovery"] -= 1
                    break
        return {"hit_dice_spent": spent, "healed": healed}

    def long_rest(self) -> None:
        if self.dead:
            return
        self.hp = self.effective_max_hp
        self.temp_hp = 0
        self.hit_dice = min(self.level, self.hit_dice + max(1, self.level // 2))
        self.resources = self.max_resources()
        self.spell_slots = self.max_spell_slots()
        self.death_saves = DeathSaves()
        self.stable = False
        self.conditions = [c for c in self.conditions if c.rounds is None and c.id not in
                           ("poisoned", "frightened", "prone", "raging")]

    # ── XP & levels ─────────────────────────────────────────────
    def xp_for_next(self) -> int | None:
        return XP_THRESHOLDS[self.level] if self.level < MAX_LEVEL else None

    def can_level_up(self) -> bool:
        nxt = self.xp_for_next()
        return nxt is not None and self.xp >= nxt

    def gain_xp(self, amount: int) -> bool:
        self.xp += max(0, amount)
        return self.can_level_up()

    def level_up(self, asi: dict[str, int] | None = None) -> dict:
        if not self.can_level_up():
            raise ValueError("not enough XP")
        old_features = set(self.class_def.features_up_to(self.level))
        old_spells = set(self.known_spells())
        self.level += 1
        hd = self.class_def.hit_die
        gain = max(1, hd // 2 + 1 + self.mod("constitution") + self.race_def.hp_per_level)
        self.max_hp += gain
        self.hp += gain
        self.hit_dice += 1
        if self.level in (4, 8):
            asi = asi or self._default_asi()
            for k, v in asi.items():
                self.abilities[k] = min(20, self.abilities.get(k, 10) + v)
        for rid, mx in self.max_resources().items():
            self.resources[rid] = mx
        slots = self.max_spell_slots()
        for lvl, n in slots.items():
            self.spell_slots[lvl] = n
        return {
            "level": self.level, "hp_gain": gain,
            "new_features": [f for f in self.class_def.features_up_to(self.level) if f not in old_features],
            "new_spells": [s for s in self.known_spells() if s not in old_spells],
            "asi": asi if self.level in (4, 8) else None,
        }

    def _default_asi(self) -> dict[str, int]:
        prim = self.class_def.primary[0]
        if self.abilities.get(prim, 10) <= 18:
            return {prim: 2}
        return {"constitution": 2}

    # ── presentation ────────────────────────────────────────────
    def status_line(self) -> str:
        if self.dead:
            return f"{self.name}: ÖLÜ"
        cond = ", ".join(c.id for c in self.conditions)
        return (f"{self.name} ({self.race_name} {self.class_name} {self.level}): "
                f"HP {self.hp}/{self.effective_max_hp}, AC {self.armor_class()}"
                + (f", durum: {cond}" if cond else ""))

    def summary_for_llm(self) -> str:
        bits = [f"{self.name} — {self.race_name} {self.class_name} (level {self.level})",
                f"HP {self.hp}/{self.effective_max_hp}" + (" DOWN/dying" if self.is_down else "")
                + (" DEAD" if self.dead else "")]
        if self.gender:
            bits.append(f"gender: {self.gender}")
        if self.appearance:
            bits.append(f"looks: {self.appearance}")
        if self.personality:
            bits.append(f"personality: {self.personality}")
        if self.conditions:
            bits.append("conditions: " + ", ".join(c.id for c in self.conditions))
        w = self.inventory.weapon()
        if w:
            bits.append(f"wields {w.display_name()}")
        return "; ".join(bits)

    def to_public(self) -> dict:
        nxt = self.xp_for_next()
        return {
            "id": self.id, "name": self.name, "race": self.race, "race_name": self.race_name,
            "cls": self.cls, "class_name": self.class_name, "level": self.level, "xp": self.xp,
            "xp_next": nxt, "abilities": self.abilities,
            "mods": {a: self.mod(a) for a in ABILITIES},
            "skills": {k: {"name": SKILL_TR[k], "bonus": self.skill_bonus(k),
                           "proficient": k in self.skill_proficiencies or k in self.race_def.skill_proficiencies,
                           "expertise": k in self.expertise} for k in SKILL_ABILITY},
            "saves": {a: self.save_bonus(a) for a in ABILITIES},
            "hp": self.hp, "max_hp": self.effective_max_hp, "temp_hp": self.temp_hp,
            "ac": self.armor_class(), "prof": self.prof, "initiative": self.initiative_bonus,
            "passive_perception": self.passive_perception,
            "death_saves": self.death_saves.model_dump(), "stable": self.stable, "dead": self.dead,
            "conditions": [c.model_dump() for c in self.conditions],
            "resources": self.resources, "max_resources": self.max_resources(),
            "spell_slots": self.spell_slots, "max_spell_slots": self.max_spell_slots(),
            "spells": self.known_spells(), "spell_dc": self.spell_dc if self.spellcasting else None,
            "spell_attack": self.spell_attack if self.spellcasting else None,
            "concentration": self.concentration,
            "inventory": self.inventory.to_public(), "rank": self.rank,
            "attacks": [{k: v for k, v in a.items() if k in ("name", "to_hit", "damage", "type", "ranged", "uid")}
                        for a in self.attack_options()],
            "features": self.features, "gender": self.gender, "appearance": self.appearance,
            "personality": self.personality, "backstory": self.backstory, "portrait": self.portrait,
            "player_id": self.player_id, "can_level_up": self.can_level_up(),
        }
