"""
Runtime world state: where the party is, what they know, who they met,
how far the threats have advanced, what lies on the ground.

Works with a scenario (sandbox) or in free mode, where every place and NPC is
created on the fly from the GM's narration.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from dndm.game.inventory import ItemStack
from dndm.rules import data
from dndm.text import norm_key, similar
from dndm.world.scenario import Discovery, Location, Scenario

TIME_OF_DAY = [(5, "şafak"), (8, "sabah"), (12, "öğle"), (15, "ikindi"), (18, "akşam"), (21, "gece"), (24, "gece yarısı")]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", norm_key(name)).strip("_")
    return (s or "yer")[:32] + "_" + uuid.uuid4().hex[:4]


class NPCState(BaseModel):
    id: str
    name: str
    role: str = ""
    appearance: str = ""
    personality: str = ""
    voice: str = ""
    wants: str = ""
    secret: str = ""
    knows: list[str] = Field(default_factory=list)
    attitude: str = "neutral"
    location: str | None = None
    alive: bool = True
    met: bool = False
    dynamic: bool = False
    monster: str | None = None
    notes: list[str] = Field(default_factory=list)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role, "appearance": self.appearance,
                "attitude": self.attitude, "alive": self.alive, "notes": self.notes[-5:]}


class JournalEntry(BaseModel):
    kind: Literal["clue", "quest", "npc", "place", "event", "item"] = "event"
    text: str
    day: int = 1


class WorldState(BaseModel):
    scenario_id: str | None = None
    premise: str = ""
    location: str
    visited: list[str] = Field(default_factory=list)
    known: list[str] = Field(default_factory=list)
    dynamic_locations: dict[str, Location] = Field(default_factory=dict)
    npcs: dict[str, NPCState] = Field(default_factory=dict)
    found: list[str] = Field(default_factory=list)
    used_encounters: list[str] = Field(default_factory=list)
    clocks: dict[str, float] = Field(default_factory=dict)
    fired_stages: list[str] = Field(default_factory=list)
    quests: dict[str, str] = Field(default_factory=dict)       # id -> active/done/failed
    dynamic_quests: dict[str, dict] = Field(default_factory=dict)
    scene_items: dict[str, list[ItemStack]] = Field(default_factory=dict)
    day: int = 1
    hour: int = 18
    last_long_rest_day: int = 0
    journal: list[JournalEntry] = Field(default_factory=list)
    summary: str = ""
    flags: dict[str, Any] = Field(default_factory=dict)

    # ── construction ────────────────────────────────────────────
    @classmethod
    def from_scenario(cls, sc: Scenario) -> "WorldState":
        ws = cls(scenario_id=sc.id, premise=sc.premise, location=sc.start_location)
        for nid, n in sc.npcs.items():
            ws.npcs[nid] = NPCState(id=nid, name=n.name, role=n.role, appearance=n.appearance,
                                    personality=n.personality, voice=n.voice, wants=n.wants, secret=n.secret,
                                    knows=list(n.knows), attitude=n.attitude, location=n.location, monster=n.monster)
        for fid in sc.fronts:
            ws.clocks[fid] = 0
        for qid, q in sc.quests.items():
            if not q.optional:
                ws.quests[qid] = "active"
        ws._arrive(sc, sc.start_location)
        for lid, loc in sc.locations.items():
            for it in loc.items:
                ws._place_item(lid, it)
        return ws

    @classmethod
    def free_mode(cls, premise: str, start_name: str, start_description: str) -> "WorldState":
        lid = _slug(start_name)
        ws = cls(scenario_id=None, premise=premise, location=lid)
        ws.dynamic_locations[lid] = Location(id=lid, name=start_name, description=start_description, safe_rest=True)
        ws.visited.append(lid)
        ws.known.append(lid)
        return ws

    # ── locations ───────────────────────────────────────────────
    def loc(self, sc: Scenario | None, lid: str | None = None) -> Location:
        lid = lid or self.location
        if lid in self.dynamic_locations:
            return self.dynamic_locations[lid]
        if sc and lid in sc.locations:
            return sc.locations[lid]
        raise KeyError(lid)

    def all_locations(self, sc: Scenario | None) -> dict[str, Location]:
        out = dict(sc.locations) if sc else {}
        out.update(self.dynamic_locations)
        return out

    def exits(self, sc: Scenario | None) -> list[Location]:
        here = self.loc(sc)
        out = []
        for ex in here.exits:
            try:
                target = self.loc(sc, ex)
            except KeyError:
                continue
            if not target.hidden or ex in self.known:
                out.append(target)
        return out

    def known_locations(self, sc: Scenario | None) -> list[Location]:
        out = []
        for lid in self.known:
            try:
                out.append(self.loc(sc, lid))
            except KeyError:
                pass
        return out

    def find_location(self, sc: Scenario | None, query: str) -> Location | None:
        if not query:
            return None
        allloc = self.all_locations(sc)
        if query in allloc:
            return allloc[query]
        for loc in allloc.values():
            if (loc.id in self.known or not loc.hidden) and similar(loc.name, query):
                return loc
        return None

    def can_travel(self, sc: Scenario | None, lid: str) -> bool:
        if lid == self.location:
            return False
        here = self.loc(sc)
        if lid in here.exits:
            target = self.loc(sc, lid)
            return not target.hidden or lid in self.known
        # known places can be travelled to directly (party knows the way)
        return lid in self.known

    def move_to(self, sc: Scenario | None, lid: str) -> int:
        """Move the party. Returns hours spent travelling."""
        target = self.loc(sc, lid)
        here = self.loc(sc)
        hours = target.travel_hours if lid in here.exits else max(1, target.travel_hours or 2)
        if target.region and here.region and target.region == here.region and not target.travel_hours:
            hours = 0
        self._arrive(sc, lid)
        return hours

    def _arrive(self, sc: Scenario | None, lid: str) -> None:
        self.location = lid
        if lid not in self.visited:
            self.visited.append(lid)
        if lid not in self.known:
            self.known.append(lid)
        loc = self.loc(sc, lid)
        for ex in loc.exits:
            try:
                t = self.loc(sc, ex)
            except KeyError:
                continue
            if not t.hidden and ex not in self.known:
                self.known.append(ex)

    def add_dynamic_location(self, sc: Scenario | None, name: str, description: str, *,
                             connect_to: str | None = None, travel_hours: int = 1) -> Location:
        existing = self.find_location(sc, name)
        if existing:
            return existing
        lid = _slug(name)
        loc = Location(id=lid, name=name.strip()[:60], description=description.strip()[:600],
                       travel_hours=travel_hours)
        src = connect_to or self.location
        loc.exits.append(src)
        self.dynamic_locations[lid] = loc
        try:
            s = self.loc(sc, src)
            if lid not in s.exits:
                s.exits.append(lid)
        except KeyError:
            pass
        if lid not in self.known:
            self.known.append(lid)
        return loc

    # ── NPCs ────────────────────────────────────────────────────
    def npcs_here(self) -> list[NPCState]:
        return [n for n in self.npcs.values() if n.location == self.location and n.alive]

    def find_npc(self, query: str) -> NPCState | None:
        if not query:
            return None
        for n in self.npcs.values():
            if n.id == query or norm_key(n.name) == norm_key(query):
                return n
        for n in self.npcs.values():
            if similar(n.name, query) or any(similar(part, query) for part in n.name.split() if len(part) > 2):
                return n
        return None

    def add_dynamic_npc(self, name: str, role: str = "", description: str = "", *, location: str | None = None) -> NPCState:
        existing = self.find_npc(name)
        if existing:
            return existing
        nid = _slug(name)
        n = NPCState(id=nid, name=name.strip()[:40], role=role.strip()[:60], appearance=description.strip()[:300],
                     location=location or self.location, dynamic=True, met=True)
        self.npcs[nid] = n
        self.add_journal("npc", f"{n.name} ile tanışıldı{f' ({n.role})' if n.role else ''}.")
        return n

    # ── discoveries ─────────────────────────────────────────────
    def available_discoveries(self, sc: Scenario | None) -> list[Discovery]:
        try:
            loc = self.loc(sc)
        except KeyError:
            return []
        return [d for d in loc.discoveries if d.id not in self.found]

    def discover(self, sc: Scenario | None, d: Discovery) -> list[str]:
        """Mark found; reveal linked places. Returns names of newly revealed places."""
        if d.id in self.found:
            return []
        self.found.append(d.id)
        self.add_journal("clue", d.reveals)
        revealed = []
        for lid in d.leads_to:
            if lid not in self.known:
                self.known.append(lid)
                try:
                    revealed.append(self.loc(sc, lid).name)
                except KeyError:
                    pass
        return revealed

    # ── scene items ─────────────────────────────────────────────
    def _place_item(self, lid: str, spec: dict) -> ItemStack | None:
        if spec.get("id"):
            d = data.items().get(spec["id"])
            if not d:
                return None
            st = ItemStack(item_id=spec["id"], name=spec.get("name", d.name), qty=int(spec.get("qty", 1)),
                           kind=d.type, value=d.value, rarity=d.rarity, magic_bonus=int(spec.get("magic_bonus", 0)),
                           base=spec.get("base"), description=spec.get("description", ""))
        else:
            st = ItemStack(item_id=None, name=spec.get("name", "Eşya"), kind=spec.get("kind", "trinket"),
                           description=spec.get("description", ""), value=float(spec.get("value", 0)),
                           qty=int(spec.get("qty", 1)), rarity="quest" if spec.get("kind") == "quest" else "common")
        self.scene_items.setdefault(lid, []).append(st)
        return st

    def items_here(self) -> list[ItemStack]:
        return self.scene_items.get(self.location, [])

    def drop_item(self, stack: ItemStack) -> None:
        self.scene_items.setdefault(self.location, []).append(stack)

    def take_item(self, query: str, qty: int | None = None) -> ItemStack | None:
        items = self.items_here()
        found = None
        for s in items:
            if s.uid == query or norm_key(s.name) == norm_key(query) or (s.item_id and s.item_id == query):
                found = s
                break
        if found is None:
            for s in items:
                if similar(s.name, query):
                    found = s
                    break
        if found is None:
            return None
        if qty is None or qty >= found.qty:
            items.remove(found)
            return found
        found.qty -= qty
        return found.model_copy(update={"uid": uuid.uuid4().hex[:10], "qty": qty})

    def place_custom_item(self, name: str, *, description: str = "", kind: str = "trinket",
                          item_id: str | None = None) -> ItemStack | None:
        if item_id and item_id in data.items():
            return self._place_item(self.location, {"id": item_id})
        for s in self.items_here():
            if similar(s.name, name):
                return s
        return self._place_item(self.location, {"name": name.strip()[:60], "kind": kind, "description": description})

    # ── time & fronts ───────────────────────────────────────────
    def time_label(self) -> str:
        label = TIME_OF_DAY[-1][1]
        for h, name in TIME_OF_DAY:
            if self.hour < h:
                label = name
                break
        return f"{self.day}. gün, {label}"

    @property
    def is_night(self) -> bool:
        return self.hour >= 21 or self.hour < 5

    def advance_time(self, sc: Scenario | None, hours: float) -> list[str]:
        """Move the clock; fronts advance. Returns narrator notes about threats escalating."""
        if hours <= 0:
            return []
        total = self.hour + hours
        days_passed = int(total // 24)
        self.hour = int(total % 24)
        self.day += days_passed
        notes: list[str] = []
        if sc:
            for fid, front in sc.fronts.items():
                before = self.clocks.get(fid, 0)
                after = min(front.clock, before + front.per_day * hours / 24)
                self.clocks[fid] = after
                for stage, text in sorted(front.stages.items()):
                    key = f"{fid}:{stage}"
                    if before < stage <= after and key not in self.fired_stages:
                        self.fired_stages.append(key)
                        notes.append(f"[{front.name}] {text}")
                        self.add_journal("event", text)
                if before < front.clock <= after and f"{fid}:done" not in self.fired_stages:
                    self.fired_stages.append(f"{fid}:done")
                    notes.append(f"[{front.name} TAMAMLANDI] {front.on_complete}")
        return notes

    def advance_front(self, sc: Scenario | None, fid: str, amount: float) -> list[str]:
        if not sc or fid not in sc.fronts:
            return []
        front = sc.fronts[fid]
        before = self.clocks.get(fid, 0)
        after = max(0.0, min(front.clock, before + amount))
        self.clocks[fid] = after
        notes = []
        for stage, text in sorted(front.stages.items()):
            key = f"{fid}:{stage}"
            if before < stage <= after and key not in self.fired_stages:
                self.fired_stages.append(key)
                notes.append(f"[{front.name}] {text}")
        return notes

    # ── journal ─────────────────────────────────────────────────
    def add_journal(self, kind: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if any(j.text == text for j in self.journal[-30:]):
            return
        self.journal.append(JournalEntry(kind=kind, text=text[:400], day=self.day))  # type: ignore[arg-type]
        if len(self.journal) > 300:
            self.journal = self.journal[-300:]

    def public(self, sc: Scenario | None) -> dict:
        here = self.loc(sc)
        return {
            "location": {"id": here.id, "name": here.name},
            "time": self.time_label(), "day": self.day, "hour": self.hour,
            "exits": [{"id": l.id, "name": l.name, "visited": l.id in self.visited} for l in self.exits(sc)],
            "known": [{"id": l.id, "name": l.name, "visited": l.id in self.visited} for l in self.known_locations(sc)],
            "npcs_here": [n.public() for n in self.npcs_here()],
            "npcs_met": [n.public() for n in self.npcs.values() if n.met],
            "items_here": [s.to_public() for s in self.items_here()],
            "journal": [j.model_dump() for j in self.journal[-60:]],
            "quests": self.quest_list(sc),
        }

    def quest_list(self, sc: Scenario | None) -> list[dict]:
        out = []
        for qid, status in self.quests.items():
            if sc and qid in sc.quests:
                q = sc.quests[qid]
                out.append({"id": qid, "name": q.name, "status": status, "hook": q.hook, "objectives": q.objectives})
            elif qid in self.dynamic_quests:
                q = self.dynamic_quests[qid]
                out.append({"id": qid, "name": q.get("name", qid), "status": status, "hook": q.get("hook", ""),
                            "objectives": q.get("objectives", [])})
        return out
