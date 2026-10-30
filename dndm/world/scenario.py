"""
Sandbox scenario format.

A scenario is a *world*, not a script: locations connected by exits, NPCs with
wants and secrets, factions, discoveries that reward curiosity, quests that can
be ignored, and "fronts" — threats that advance on their own when the party
looks elsewhere. Nothing forces the players down a path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from dndm.paths import scenarios_dir


class CheckSpec(BaseModel):
    skill: str
    dc: int = 12


class Discovery(BaseModel):
    id: str
    hint: str = ""                          # what an attentive character notices
    check: CheckSpec | None = None          # None = found by simply looking/asking
    reveals: str                            # what is learned
    item: dict[str, Any] | None = None      # {"id": catalog id} or {"name","kind","description"}
    gold: int = 0
    leads_to: list[str] = Field(default_factory=list)   # location ids revealed
    xp: int = 25


class EncounterSpec(BaseModel):
    id: str
    when: str = ""                          # GM guidance on when this fight happens
    enemies: list[dict[str, Any]]           # [{"monster": id, "count": n, "name": ...}]
    features: list[dict[str, Any]] = Field(default_factory=list)
    once: bool = True
    boss: bool = False


class Location(BaseModel):
    id: str = ""
    name: str
    region: str = ""
    description: str
    gm_notes: str = ""
    exits: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    discoveries: list[Discovery] = Field(default_factory=list)
    encounters: list[EncounterSpec] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)     # lying around, pickable
    shop: list[dict[str, Any]] = Field(default_factory=list)      # [{"id": item, "price": gp}]
    hidden: bool = False
    safe_rest: bool = False
    danger: int = 0
    travel_hours: int = 0                   # hours to reach from an adjacent location
    outdoors: bool = True


class NPC(BaseModel):
    id: str = ""
    name: str
    race: str = "insan"
    role: str = ""
    appearance: str = ""
    personality: str = ""
    voice: str = ""
    wants: str = ""
    secret: str = ""
    knows: list[str] = Field(default_factory=list)
    attitude: Literal["friendly", "neutral", "wary", "hostile"] = "neutral"
    location: str | None = None
    monster: str | None = None              # stat block if a fight breaks out
    faction: str | None = None


class Faction(BaseModel):
    id: str = ""
    name: str
    goal: str
    attitude: str = "neutral"
    notes: str = ""


class Front(BaseModel):
    """A threat clock that ticks when time passes or events happen."""
    id: str = ""
    name: str
    description: str
    clock: int = 6
    per_day: float = 1
    stages: dict[int, str] = Field(default_factory=dict)
    on_complete: str = ""


class Quest(BaseModel):
    id: str = ""
    name: str
    hook: str
    objectives: list[str] = Field(default_factory=list)
    reward_xp: int = 100
    reward_gold: int = 0
    reward_items: list[str] = Field(default_factory=list)
    optional: bool = True
    giver: str | None = None


class Scenario(BaseModel):
    id: str = ""
    title: str
    pitch: str
    tone: str = "dark fantasy"
    players: list[int] = Field(default_factory=lambda: [1, 6])
    level_range: list[int] = Field(default_factory=lambda: [1, 4])
    premise: str
    truths: list[str] = Field(default_factory=list)
    start_location: str
    opening: str = ""
    locations: dict[str, Location]
    npcs: dict[str, NPC] = Field(default_factory=dict)
    factions: dict[str, Faction] = Field(default_factory=dict)
    fronts: dict[str, Front] = Field(default_factory=dict)
    quests: dict[str, Quest] = Field(default_factory=dict)
    endings: list[str] = Field(default_factory=list)
    random_events: list[str] = Field(default_factory=list)
    style_notes: str = ""

    @model_validator(mode="after")
    def _fill_ids(self):
        for coll in (self.locations, self.npcs, self.factions, self.fronts, self.quests):
            for k, v in coll.items():
                v.id = k
        return self

    def problems(self) -> list[str]:
        """Structural sanity checks (references between parts)."""
        from dndm.rules import data
        out: list[str] = []
        if self.start_location not in self.locations:
            out.append(f"start_location '{self.start_location}' does not exist")
        for lid, loc in self.locations.items():
            for ex in loc.exits:
                if ex not in self.locations:
                    out.append(f"{lid}: exit to unknown location '{ex}'")
                elif lid not in self.locations[ex].exits:
                    out.append(f"{lid} -> {ex}: exit is one-way (add the reverse exit)")
            for n in loc.npcs:
                if n not in self.npcs:
                    out.append(f"{lid}: unknown npc '{n}'")
            for d in loc.discoveries:
                for t in d.leads_to:
                    if t not in self.locations:
                        out.append(f"{lid}/{d.id}: leads_to unknown location '{t}'")
                if d.item and d.item.get("id") and d.item["id"] not in data.items():
                    out.append(f"{lid}/{d.id}: unknown catalog item {d.item['id']}")
            for enc in loc.encounters:
                for e in enc.enemies:
                    if e.get("monster") not in data.monsters():
                        out.append(f"{lid}/{enc.id}: unknown monster {e.get('monster')}")
            for it in loc.items + loc.shop:
                if it.get("id") and it["id"] not in data.items():
                    out.append(f"{lid}: unknown item {it['id']}")
        for nid, npc in self.npcs.items():
            if npc.location and npc.location not in self.locations:
                out.append(f"npc {nid}: unknown location {npc.location}")
            if npc.monster and npc.monster not in data.monsters():
                out.append(f"npc {nid}: unknown monster {npc.monster}")
            if npc.faction and npc.faction not in self.factions:
                out.append(f"npc {nid}: unknown faction {npc.faction}")
        for qid, q in self.quests.items():
            for it in q.reward_items:
                if it not in data.items():
                    out.append(f"quest {qid}: unknown reward item {it}")
        # every location reachable from start (through exits or discoveries)
        reachable = {self.start_location}
        frontier = [self.start_location]
        while frontier:
            cur = frontier.pop()
            loc = self.locations.get(cur)
            if not loc:
                continue
            nxt = list(loc.exits) + [t for d in loc.discoveries for t in d.leads_to]
            for n in nxt:
                if n not in reachable and n in self.locations:
                    reachable.add(n)
                    frontier.append(n)
        for lid in self.locations:
            if lid not in reachable:
                out.append(f"location '{lid}' is unreachable from the start")
        return out


def load_scenario(path: str | Path) -> Scenario:
    p = Path(path)
    if p.is_dir():
        p = p / "scenario.yaml"
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Scenario.model_validate(raw)


def list_scenarios() -> list[dict]:
    out = []
    root = scenarios_dir()
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        f = d / "scenario.yaml"
        if f.exists():
            try:
                sc = load_scenario(f)
                out.append({"id": d.name, "title": sc.title, "pitch": sc.pitch, "tone": sc.tone,
                            "players": sc.players, "level_range": sc.level_range})
            except Exception as exc:  # broken scenario files should not kill the lobby
                out.append({"id": d.name, "title": d.name, "pitch": f"(hatalı senaryo: {exc})", "broken": True})
    return out


def scenario_path(scenario_id: str) -> Path:
    p = scenarios_dir() / scenario_id
    if not p.resolve().is_relative_to(scenarios_dir().resolve()):
        raise ValueError("invalid scenario id")
    return p
