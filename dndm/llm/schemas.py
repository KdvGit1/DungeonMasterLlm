"""
Pydantic schemas for structured LLM outputs.

These double as the JSON schema handed to Ollama's grammar-constrained
``format`` so the model physically cannot emit malformed JSON.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Skill = Literal[
    # 5e skills
    "athletics", "acrobatics", "sleight_of_hand", "stealth",
    "arcana", "history", "investigation", "nature", "religion",
    "animal_handling", "insight", "medicine", "perception", "survival",
    "deception", "intimidation", "performance", "persuasion",
    # raw ability checks / saves when no skill fits
    "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
]

Intent = Literal[
    "talk", "move", "explore", "investigate", "interact", "attack", "use_item",
    "take_item", "give_item", "rest", "trade", "stealth", "magic", "help", "other",
]

Advantage = Literal["none", "advantage", "disadvantage"]


class CheckRequest(BaseModel):
    skill: Skill
    dc: int = Field(ge=5, le=30, description="5 very easy, 10 easy, 15 medium, 20 hard, 25 very hard")
    advantage: Advantage = "none"
    reason: str = Field(description="One short sentence: why the outcome is uncertain")


class ActionRuling(BaseModel):
    player: str
    intent: Intent
    needs_check: bool = Field(description="true only if outcome is uncertain AND failure has a consequence")
    check: CheckRequest | None = None
    starts_combat: bool = False
    target: str | None = None
    item: str | None = None
    destination: str | None = None


class EnemyRef(BaseModel):
    name: str = Field(description="Narrative name, e.g. 'Kara Kurt haydudu'")
    kind: str = Field(description="Monster id from the provided list")
    count: int = Field(ge=1, le=8, default=1)


class Adjudication(BaseModel):
    """Benchmark-era compact schema (kept for the model benchmark)."""
    rulings: list[ActionRuling]
    enemies: list[EnemyRef] = Field(default_factory=list,
                                    description="Only if some ruling starts combat")


class ExtractedNPC(BaseModel):
    name: str
    role: str
    description: str


class ExtractedItem(BaseModel):
    name: str
    where: str = Field(description="Where it lies / who holds it")


class Extraction(BaseModel):
    new_npcs: list[ExtractedNPC] = Field(default_factory=list)
    items_in_scene: list[ExtractedItem] = Field(default_factory=list)
    places_mentioned: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list, description="Short new story facts worth remembering")


# ═════════════════════════════════════════════════════════════════
# Game-time schemas
# ═════════════════════════════════════════════════════════════════

ItemAction = Literal["none", "take", "give", "drop", "buy", "sell", "use", "equip"]
FeatureEffect = Literal["hazard", "cover", "obscure", "push_hazard", "high_ground", "trap"]


class BattlefieldFeature(BaseModel):
    name: str = Field(description="Short Turkish name, e.g. 'Çürük avize'")
    effect: FeatureEffect
    description: str = Field(description="One short Turkish sentence")


# small models sometimes write the *word* for "nothing" instead of null
_NULLISH = {"", "none", "null", "nil", "n/a", "na", "unknown", "-", "yok", "hiçbiri", "bilinmiyor", "belirsiz"}


def _nullish(v):
    if isinstance(v, str) and v.strip().strip(".").lower() in _NULLISH:
        return None
    return v


class ExploreRuling(BaseModel):
    player: str = Field(description="Character name exactly as listed")
    intent: Intent
    needs_check: bool = Field(description="true only if the outcome is uncertain AND failure matters")
    check: CheckRequest | None = None
    group_check: bool = Field(False, description="true if the whole party attempts this together (sneaking past, climbing)")
    target_npc: str | None = Field(None, description="Name of the NPC addressed/affected, if any")
    destination: str | None = Field(None, description="Location id from KNOWN PLACES, or a new place name if heading somewhere unknown")
    item_action: ItemAction = "none"
    item: str | None = Field(None, description="Item name involved (as written in inventory/scene lists)")
    item_to: str | None = Field(None, description="Recipient character name when giving an item")
    discovery: str | None = Field(None, description="Discovery id this action could uncover, from SECRETS HERE")
    time_minutes: int = Field(10, ge=0, le=600, description="How long the action takes in game time")
    rest: Literal["none", "short", "long"] = "none"

    _clean = field_validator("target_npc", "destination", "item", "item_to", "discovery", mode="before")(
        lambda v: _nullish(v))


class ExploreAdjudication(BaseModel):
    rulings: list[ExploreRuling]
    starts_combat: bool = Field(False, description="true only if a fight clearly starts now")
    encounter_id: str | None = Field(None, description="Id from POSSIBLE FIGHTS HERE if it matches, else null")
    enemies: list[EnemyRef] = Field(default_factory=list, description="If combat starts and no encounter_id fits")
    battlefield: list[BattlefieldFeature] = Field(default_factory=list,
                                                  description="If combat starts: 1-3 usable features of this place")
    ambush: bool = Field(False, description="true if the enemies attack the party by surprise")

    _clean = field_validator("encounter_id", mode="before")(lambda v: _nullish(v))


class GivenItem(BaseModel):
    to: str = Field(description="Character name who receives it")
    item: str = Field(description="Item name in Turkish as narrated")
    giver: str = Field("", description="Who gave it (NPC name) or 'found'")


class GivenGold(BaseModel):
    to: str
    amount_gp: float = Field(ge=0, le=1000)
    giver: str = ""


class PlaceRef(BaseModel):
    name: str
    description: str = ""


class QuestUpdate(BaseModel):
    name: str
    status: Literal["new", "done", "failed"]
    description: str = ""


class AttitudeChange(BaseModel):
    name: str
    attitude: Literal["friendly", "neutral", "wary", "hostile"]


class StoryExtraction(BaseModel):
    new_npcs: list[ExtractedNPC] = Field(default_factory=list,
                                         description="Named characters that appear for the first time (not players)")
    items_in_scene: list[ExtractedItem] = Field(default_factory=list,
                                                description="Notable takeable objects described as lying around")
    items_given: list[GivenItem] = Field(default_factory=list,
                                         description="Items an NPC explicitly HANDS to a player character in this text")
    gold_given: list[GivenGold] = Field(default_factory=list)
    places_mentioned: list[PlaceRef] = Field(default_factory=list,
                                             description="Named places mentioned that the party could travel to")
    facts: list[str] = Field(default_factory=list, description="Up to 3 short new clues/facts worth remembering (Turkish)")
    quest_updates: list[QuestUpdate] = Field(default_factory=list)
    attitude_changes: list[AttitudeChange] = Field(default_factory=list)
    npc_deaths: list[str] = Field(default_factory=list, description="Names of NPCs who clearly died in this text")


ImprovEffect = Literal["damage", "condition", "damage_condition", "push", "advantage_ally", "intimidate",
                       "use_feature", "none"]


class ImprovisedRuling(BaseModel):
    feasible: bool = Field(description="false if the action is impossible right now")
    explanation: str = Field(description="One short Turkish sentence (shown if not feasible)")
    check: CheckRequest | None = None
    effect: ImprovEffect = "none"
    target: str | None = Field(None, description="Enemy label or name affected")
    damage: Literal["1d4", "1d6", "2d6", "3d6", "4d6"] | None = None
    damage_type: Literal["bludgeoning", "piercing", "slashing", "fire", "cold", "acid", "lightning",
                         "thunder", "poison", "radiant", "necrotic", "force"] = "bludgeoning"
    condition: Literal["prone", "restrained", "blinded", "frightened", "grappled", "poisoned"] | None = None
    feature_id: str | None = None
    ally: str | None = Field(None, description="Ally character name who benefits, if any")
