"""
Encounter state (pure data, JSON-serialisable).

Party HP/conditions live on the ``Character`` objects; enemy state lives here.
Combatants are addressed by refs: ``pc:<char_id>`` and ``en:<uid>``.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from dndm.game.character import Condition
from dndm.rules import data

EnemyState = Literal["active", "down", "dead", "fled", "surrendered"]
EncounterStatus = Literal["setup", "active", "victory", "defeat", "fled", "parley"]


def _eid() -> str:
    return uuid.uuid4().hex[:6]


class Enemy(BaseModel):
    uid: str = Field(default_factory=_eid)
    monster_id: str
    name: str
    label: str = ""                       # "A", "B", ... shown on table
    hp: int
    max_hp: int
    rank: Literal["front", "back"] = "front"
    state: EnemyState = "active"
    conditions: list[Condition] = Field(default_factory=list)
    recharge_ready: dict[str, bool] = Field(default_factory=dict)
    slots: dict[int, int] = Field(default_factory=dict)
    reaction_used: bool = False
    took_fire_or_acid: bool = False
    concentration: str | None = None
    initiative: int = 0
    notes: dict[str, Any] = Field(default_factory=dict)

    @property
    def mdef(self):
        return data.monster(self.monster_id)

    @property
    def ref(self) -> str:
        return f"en:{self.uid}"

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    def has_condition(self, cid: str) -> bool:
        return any(c.id == cid for c in self.conditions)

    def add_condition(self, cond: Condition) -> None:
        self.conditions = [c for c in self.conditions if c.id != cond.id]
        self.conditions.append(cond)

    def remove_condition(self, cid: str) -> None:
        self.conditions = [c for c in self.conditions if c.id != cid]

    def armor_class(self) -> int:
        ac = self.mdef.ac
        for c in self.conditions:
            ac += int(c.data.get("ac_bonus", 0))
        return ac

    def hp_fraction(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0

    def wound_label(self) -> str:
        """Vague health description players see instead of exact numbers."""
        if self.state == "dead":
            return "ölü"
        if self.state in ("fled", "surrendered"):
            return {"fled": "kaçtı", "surrendered": "teslim oldu"}[self.state]
        f = self.hp_fraction()
        if f >= 1:
            return "yara almamış"
        if f > 0.75:
            return "sıyrık almış"
        if f > 0.5:
            return "yaralı"
        if f > 0.25:
            return "ağır yaralı"
        if self.hp > 0:
            return "can çekişiyor"
        return "yerde"

    def to_public(self) -> dict:
        return {"uid": self.uid, "ref": self.ref, "name": self.name, "label": self.label,
                "monster": self.mdef.name, "rank": self.rank, "state": self.state,
                "wound": self.wound_label(), "hp_fraction": round(self.hp_fraction(), 2),
                "conditions": [c.id for c in self.conditions], "boss": "boss" in self.mdef.tags,
                "ac_hint": self.mdef.ac}


class EnvFeature(BaseModel):
    """A usable piece of the battlefield ("rotten chandelier", "boiling cauldron")."""
    id: str = Field(default_factory=_eid)
    name: str
    description: str = ""
    effect: Literal["hazard", "cover", "obscure", "push_hazard", "high_ground", "trap"] = "hazard"
    damage: str | None = "2d6"
    damage_type: str = "bludgeoning"
    save: str = "dexterity"
    dc: int = 13
    rank: Literal["front", "back", "any"] = "front"
    uses: int = 1


class Event(BaseModel):
    type: str
    text: str = ""
    actor: str | None = None
    target: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class TurnState(BaseModel):
    ref: str = ""
    action: int = 1
    bonus: int = 1
    moved: bool = False
    attacks_left: int = 0
    sneak_used: bool = False
    disengaged: bool = False


class Encounter(BaseModel):
    id: str = Field(default_factory=_eid)
    status: EncounterStatus = "setup"
    title: str = ""
    context: str = ""
    enemies: list[Enemy] = Field(default_factory=list)
    party: list[str] = Field(default_factory=list)          # character ids
    fled_party: list[str] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)          # refs in initiative order (may repeat for bosses)
    initiatives: dict[str, int] = Field(default_factory=dict)
    round: int = 0
    turn_index: int = 0
    turn: TurnState = Field(default_factory=TurnState)
    features: list[EnvFeature] = Field(default_factory=list)
    log: list[Event] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)     # dramatic beats for the narrator
    loot_rolled: bool = False
    xp_awarded: int = 0
    twists: list[str] = Field(default_factory=list)
    sunlight: bool = False
    enemy_focus: str | None = None                           # char id enemies gang up on this round

    def enemy(self, uid: str) -> Enemy:
        uid = uid.removeprefix("en:")
        for e in self.enemies:
            if e.uid == uid:
                return e
        raise KeyError(uid)

    def active_enemies(self) -> list[Enemy]:
        return [e for e in self.enemies if e.is_active]

    def current_ref(self) -> str | None:
        if not self.order:
            return None
        return self.order[self.turn_index % len(self.order)]
