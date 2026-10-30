"""
Pydantic schemas for structured LLM outputs.

These double as the JSON schema handed to Ollama's grammar-constrained
``format`` so the model physically cannot emit malformed JSON.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
