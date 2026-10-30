"""
Game session orchestrator.

Owns players, characters, the world and the GM, and runs the two game modes:

* exploration — players post actions (public or whispered); when everyone is
  ready the round resolves: adjudicate → player dice taps → apply → narrate
  (streamed to every screen) → extract world facts in the background.
* combat — initiative order; the current player's phone gets an action menu,
  enemies act instantly, every beat is narrated briefly.

All client traffic is expressed as messages passed to ``emit`` (the server
fans them out over WebSockets). Each message is a dict with a ``t`` field.
"""

from __future__ import annotations

import asyncio
import re
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from dndm.game.character import Character
from dndm.game.combat.ai import enemy_turn
from dndm.game.combat.autoplay import auto_pc_turn
from dndm.game.combat.engine import CombatEngine, CombatError
from dndm.game.combat.state import Encounter, EnvFeature, Event
from dndm.game.creation import create_character, make_pregen
from dndm.game.inventory import InventoryError
from dndm.gm.master import GameMaster
from dndm.llm.client import LLMClient
from dndm.llm.schemas import ExploreAdjudication, ExploreRuling, StoryExtraction
from dndm.paths import user_dir
from dndm.rules import data
from dndm.rules.core import DEGREE_TR, CheckResult, dc_label, resolve_check, skill_or_ability_name
from dndm.rules.dice import DiceRoll, roll
from dndm.text import fold, similar, tr_lower, tr_upper
from dndm.world.scenario import Scenario, load_scenario, scenario_path
from dndm.world.state import WorldState

log = logging.getLogger("dndm.session")

Emit = Callable[[dict, list[str] | None], Awaitable[None]]


class Settings(BaseModel):
    auto_roll: bool = False            # roll for players automatically
    show_dc: bool = False              # reveal exact DCs to players
    roll_timeout: int = 45             # seconds before a pending roll auto-rolls
    turn_timeout: int = 120            # combat turn AFK timeout (autoplay)
    round_timeout: int = 0             # exploration: 0 = wait until all ready
    mercy: bool = True                 # total defeat → captured, not dead
    dice_animation_ms: int = 2600      # table animation time before results show
    language: str = "tr"


class Player(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    character_id: str | None = None
    connected: bool = False
    ready: bool = False
    is_host: bool = False
    joined_at: float = Field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "character_id": self.character_id,
                "connected": self.connected, "ready": self.ready, "is_host": self.is_host}


class PendingAction(BaseModel):
    text: str
    private: bool = False
    at: float = Field(default_factory=time.time)


@dataclass
class RollRequest:
    id: str
    player_id: str | None
    char_id: str
    label: str
    notation: str
    advantage: str
    future: asyncio.Future
    meta: dict = field(default_factory=dict)


MAX_PLAYERS = 6


class GameSession:
    def __init__(self, llm: LLMClient, *, emit: Emit | None = None, session_id: str | None = None):
        self.id = session_id or uuid.uuid4().hex[:8]
        self.llm = llm
        self.emit_fn = emit
        self.settings = Settings()
        self.players: dict[str, Player] = {}
        self.characters: dict[str, Character] = {}
        self.mode: str = "lobby"                 # lobby | exploration | combat | ended
        self.scenario: Scenario | None = None
        self.world: WorldState | None = None
        self.gm: GameMaster | None = None
        self.pending: dict[str, PendingAction] = {}     # char_id -> action
        self.rolls: dict[str, RollRequest] = {}
        self.engine: CombatEngine | None = None
        self.narration_log: list[dict] = []             # [{id, text, kind, at}]
        self.busy = False                               # a round / beat is resolving
        self.lock = asyncio.Lock()
        self._turn_waiter: asyncio.Event | None = None
        self._spec: dict[str, tuple[str, int, asyncio.Task]] = {}
        self.round_no = 0
        self._stall = 0
        self._last_progress: tuple[int, int] = (0, 0)
        self._tasks: set[asyncio.Task] = set()
        self.created_at = time.time()
        self.title = "Yeni Macera"

    # ═══════════════════════════════════════════════════════════
    # Messaging
    # ═══════════════════════════════════════════════════════════

    async def emit(self, msg: dict, to: list[str] | None = None) -> None:
        if self.emit_fn is not None:
            try:
                await self.emit_fn(msg, to)
            except Exception:  # never let a dead socket break the game loop
                log.exception("emit failed")

    async def toast(self, text: str, kind: str = "info", to: list[str] | None = None) -> None:
        await self.emit({"t": "toast", "text": text, "kind": kind}, to)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_log_task_error)
        return task

    def player_of_char(self, char_id: str) -> Player | None:
        return next((p for p in self.players.values() if p.character_id == char_id), None)

    def char_of_player(self, player_id: str) -> Character | None:
        p = self.players.get(player_id)
        return self.characters.get(p.character_id) if p and p.character_id else None

    def party(self) -> list[Character]:
        return [c for c in self.characters.values() if self.player_of_char(c.id) is not None]

    def living_party(self) -> list[Character]:
        return [c for c in self.party() if not c.dead]

    # ═══════════════════════════════════════════════════════════
    # Lobby
    # ═══════════════════════════════════════════════════════════

    def join(self, name: str, token: str | None = None) -> Player:
        if token:
            for p in self.players.values():
                if p.token == token:
                    return p
        name = (name or "").strip()[:20] or f"Oyuncu {len(self.players) + 1}"
        if len(self.players) >= MAX_PLAYERS:
            raise ValueError("Masa dolu (en fazla 6 oyuncu).")
        if any(p.name.lower() == name.lower() for p in self.players.values()):
            name = f"{name} {len(self.players) + 1}"
        p = Player(name=name, is_host=not self.players)
        self.players[p.id] = p
        return p

    def leave(self, player_id: str) -> None:
        p = self.players.pop(player_id, None)
        if p and p.character_id and self.mode == "lobby":
            self.characters.pop(p.character_id, None)

    def set_character(self, player_id: str, spec: dict) -> Character:
        p = self.players[player_id]
        if self.mode not in ("lobby", "exploration"):
            raise ValueError("Savaş sırasında karakter değiştirilemez.")
        if "pregen" in spec:
            ch = make_pregen(int(spec["pregen"]), player_id=player_id)
            if spec.get("name"):
                ch.name = str(spec["name"]).strip()[:24] or ch.name
        else:
            ch = create_character(
                name=spec.get("name", ""), race=spec.get("race", "human"), cls=spec.get("cls", "fighter"),
                base_scores=spec.get("scores"), method=spec.get("method", "standard"),
                skills=spec.get("skills"), gender=spec.get("gender", ""), appearance=spec.get("appearance", ""),
                personality=spec.get("personality", ""), backstory=spec.get("backstory", ""),
                portrait=spec.get("portrait", ""), player_id=player_id)
        if any(c.name.lower() == ch.name.lower() and c.id != p.character_id for c in self.characters.values()):
            ch.name = f"{ch.name} {len(self.characters) + 1}"
        if p.character_id:
            self.characters.pop(p.character_id, None)
        self.characters[ch.id] = ch
        p.character_id = ch.id
        if self.mode == "exploration" and self.gm:
            self.gm.party_level = self.party_level()
        return ch

    def party_level(self) -> int:
        lv = [c.level for c in self.party()]
        return round(sum(lv) / len(lv)) if lv else 1

    async def start(self, *, scenario_id: str | None = None, premise: str = "", start_name: str = "",
                    start_description: str = "") -> None:
        if self.mode != "lobby":
            raise ValueError("Oyun zaten başladı.")
        if not self.party():
            raise ValueError("En az bir oyuncunun karakteri olmalı.")
        if scenario_id:
            self.scenario = load_scenario(scenario_path(scenario_id))
            self.scenario.id = scenario_id
            self.world = WorldState.from_scenario(self.scenario)
            self.title = self.scenario.title
        else:
            self.scenario = None
            self.world = WorldState.free_mode(
                premise or "Klasik bir fantastik dünyada, küçük bir sınır kasabasında başlayan serbest macera.",
                start_name or "Yol Ayrımındaki Han",
                start_description or "Ana yolun çatallandığı yerde, rüzgârın dövdüğü ahşap bir han. İçeride ateş "
                                     "çıtırdıyor, yolcular fısıltıyla konuşuyor.")
            self.title = "Serbest Macera"
        self.gm = GameMaster(self.llm, self.world, self.scenario, party_level=self.party_level())
        self.mode = "exploration"
        await self.broadcast_state()
        opening = (self.scenario.opening if self.scenario and self.scenario.opening else "")
        names = ", ".join(c.name for c in self.party())
        instruction = ("This is the OPENING SCENE. Introduce the location vividly, show the party "
                       f"({names}) arriving or already present, hint at something unusual, and end on an open "
                       "situation. 120-200 words, Turkish." + (f" Opening guidance: {opening}" if opening else ""))
        await self._narrate(actions_block="", outcomes=[], notes=[], instruction=instruction, kind="opening")
        self.save()

    # ═══════════════════════════════════════════════════════════
    # State broadcasting
    # ═══════════════════════════════════════════════════════════

    def public_state(self, viewer: str | None = None) -> dict:
        sc, ws = self.scenario, self.world
        st: dict[str, Any] = {
            "t": "state", "session": self.id, "mode": self.mode, "title": self.title, "busy": self.busy,
            "players": [p.public() for p in self.players.values()],
            "party": [self._char_public(c, full=(viewer is not None and c.player_id == viewer) or viewer == "table")
                      for c in self.party()],
            "pending": {cid: {"ready": True, "private": a.private,
                              "text": (a.text if not a.private else "")} for cid, a in self.pending.items()},
            "settings": self.settings.model_dump(),
            "rolls": [{"id": r.id, "char_id": r.char_id, "label": r.label} for r in self.rolls.values()],
        }
        if ws:
            st["world"] = ws.public(sc)
            st["scenario"] = {"id": sc.id, "title": sc.title} if sc else None
        if self.engine and self.mode == "combat":
            st["combat"] = self.engine.public_state()
        if viewer and viewer != "table":
            ch = self.char_of_player(viewer)
            st["me"] = {"player_id": viewer, "character_id": ch.id if ch else None}
        st["narration"] = self.narration_log[-30:]
        return st

    def _char_public(self, c: Character, *, full: bool) -> dict:
        pub = c.to_public()
        if full:
            return pub
        keep = ("id", "name", "race_name", "class_name", "level", "hp", "max_hp", "ac", "conditions", "dead",
                "portrait", "player_id", "rank", "death_saves", "stable", "gender", "appearance")
        return {k: pub[k] for k in keep}

    async def broadcast_state(self) -> None:
        if self.emit_fn is None:
            return
        await self.emit(self.public_state("table"), ["table"])
        for pid in self.players:
            await self.emit(self.public_state(pid), [pid])

    # ═══════════════════════════════════════════════════════════
    # Dice requests
    # ═══════════════════════════════════════════════════════════

    async def request_roll(self, char_id: str, label: str, *, bonus: int = 0, advantage: str = "none",
                           dc: int | None = None, purpose: str = "check", sides: int = 20,
                           count: int = 1, private: bool = False) -> DiceRoll:
        """Ask the owner of ``char_id`` to tap 'roll'. Server rolls; table animates; returns the dice."""
        ch = self.characters[char_id]
        player = self.player_of_char(char_id)
        sign = "+" if bonus >= 0 else "-"
        notation = f"{count}d{sides}{sign}{abs(bonus)}" if bonus else f"{count}d{sides}"
        auto = self.settings.auto_roll or player is None or not player.connected
        audience = [player.id] if (private and player) else None   # secret rolls never reach the table
        rid = uuid.uuid4().hex[:8]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        req = RollRequest(rid, player.id if player else None, char_id, label, notation, advantage, fut,
                          meta={"purpose": purpose, "dc": dc})
        if not auto:
            self.rolls[rid] = req
            hint = (f"ZS {dc}" if self.settings.show_dc else dc_label(dc)) if dc else ""
            await self.emit({"t": "roll_request", "id": rid, "char_id": char_id, "char": ch.name, "label": label,
                             "notation": notation, "advantage": advantage, "difficulty": hint,
                             "timeout": self.settings.roll_timeout, "private": private},
                            audience)
            try:
                await asyncio.wait_for(asyncio.shield(fut), timeout=self.settings.roll_timeout)
            except asyncio.TimeoutError:
                pass
            self.rolls.pop(rid, None)
        r = roll(notation, advantage=advantage)  # type: ignore[arg-type]
        await self.emit({"t": "dice", "id": rid, "char_id": char_id, "char": ch.name, "label": label,
                         "roll": r.to_dict(), "advantage": advantage, "purpose": purpose,
                         "auto": auto or not fut.done(), "private": private}, audience)
        if not private:
            await asyncio.sleep(self.settings.dice_animation_ms / 1000)
        return r

    def answer_roll(self, player_id: str, roll_id: str) -> bool:
        req = self.rolls.get(roll_id)
        if not req or req.player_id != player_id or req.future.done():
            return False
        req.future.set_result(True)
        return True

    async def roll_check(self, ch: Character, key: str, dc: int, advantage: str = "none",
                         private: bool = False) -> CheckResult:
        bonus = ch.skill_bonus(key)
        guided = next((c for c in ch.conditions if c.id == "guided"), None)
        if guided:
            bonus += roll("1d4").total
            ch.remove_condition("guided")
        if ch.has_condition("pass_without_trace") and key == "stealth":
            bonus += 10
        armor = ch.inventory.armor()
        if key == "stealth" and armor and armor.definition and armor.definition.stealth_disadvantage:
            advantage = "none" if advantage == "advantage" else "disadvantage"
        for slot in ("boots", "cloak"):
            s = ch.inventory.equipped_stack(slot)
            if s and s.definition and key in (getattr(s.definition, "grants_advantage", None) or []):
                advantage = "none" if advantage == "disadvantage" else "advantage"
        label = f"{skill_or_ability_name(key)} zarı"
        r = await self.request_roll(ch.id, label, bonus=bonus, advantage=advantage, dc=dc, private=private)
        nat = r.natural or 0
        if nat == 20:
            degree = "critical_success"
        elif nat == 1:
            degree = "critical_failure"
        elif r.total >= dc:
            degree = "critical_success" if r.total >= dc + 10 else "success"
        else:
            degree = "critical_failure" if r.total <= dc - 10 else "failure"
        res = CheckResult(key=key, dc=dc, roll=r, bonus=bonus, total=r.total, degree=degree,  # type: ignore[arg-type]
                          advantage=advantage)  # type: ignore[arg-type]
        p = self.player_of_char(ch.id)
        await self.emit({"t": "check_result", "char": ch.name, "char_id": ch.id, "result": res.to_dict(),
                         "text": res.summary_tr(ch.name), "private": private},
                        [p.id] if (private and p) else None)
        if res.success:
            ch.gain_xp(5)
        return res

    # ═══════════════════════════════════════════════════════════
    # Exploration
    # ═══════════════════════════════════════════════════════════

    async def submit_action(self, player_id: str, text: str, *, private: bool = False) -> None:
        if self.mode != "exploration":
            raise ValueError("Şu an serbest eylem gönderilemez.")
        ch = self.char_of_player(player_id)
        if ch is None:
            raise ValueError("Önce bir karakter seç.")
        if ch.dead:
            raise ValueError("Karakterin öldü.")
        text = text.strip()
        if not text:
            raise ValueError("Eylem boş olamaz.")
        if len(text) > 600:
            text = text[:600]
        self.pending[ch.id] = PendingAction(text=text, private=private)
        await self.broadcast_state()
        if self._all_ready():
            self._spawn(self.resolve_round())
        else:
            self._speculate(ch, text)

    async def withdraw_action(self, player_id: str) -> None:
        ch = self.char_of_player(player_id)
        if ch and not self.busy:
            self.pending.pop(ch.id, None)
            await self.broadcast_state()

    async def force_round(self) -> None:
        if self.pending and not self.busy:
            self._spawn(self.resolve_round())

    def _all_ready(self) -> bool:
        if self.busy:
            return False
        actors = [c for c in self.living_party() if (p := self.player_of_char(c.id)) and p.connected]
        if not actors:
            actors = self.living_party()
        return bool(actors) and all(c.id in self.pending for c in actors)

    async def resolve_round(self) -> None:
        async with self.lock:
            if self.busy or not self.pending or self.mode != "exploration":
                return
            self.busy = True
            actions = dict(self.pending)
            self.pending.clear()
            try:
                await self.broadcast_state()
                await self._resolve_exploration(actions)
            finally:
                self.busy = False
                await self.broadcast_state()
                self.save()

    async def _resolve_exploration(self, actions: dict[str, PendingAction]) -> None:
        assert self.gm and self.world
        sc, ws = self.scenario, self.world
        party = self.living_party()
        by_name = {self.characters[cid].name: a for cid, a in actions.items()}
        await self.emit({"t": "thinking", "text": "GM düşünüyor..."}, None)
        adj = await self._adjudicate_with_speculation(actions, party)
        outcomes: list[str] = []
        notes: list[str] = []
        hours = 0.0
        moved_to: str | None = None

        # ── phase 1: plan every check ────────────────────────────
        group = next((r for r in adj.rulings if r.group_check and r.needs_check and r.check), None)
        plans: list[tuple[ExploreRuling, Character, Any, tuple[str, int, str] | None]] = []
        for ruling in adj.rulings:
            ch = next((c for c in party if c.name == ruling.player), None)
            if ch is None:
                continue
            disc = None
            if ruling.discovery:
                disc = next((d for d in ws.available_discoveries(sc) if d.id == ruling.discovery), None)
            spec = None
            if ruling is not group:
                if ruling.needs_check and ruling.check:
                    key, dc = ruling.check.skill, ruling.check.dc
                    if disc and disc.check:
                        key, dc = disc.check.skill, disc.check.dc
                    spec = (key, dc, ruling.check.advantage)
                elif disc and disc.check:
                    spec = (disc.check.skill, disc.check.dc, "none")
            plans.append((ruling, ch, disc, spec))
        secret = {name for name, a in by_name.items() if a.private}

        # ── phase 2: everyone rolls at the same time ─────────────
        async def no_roll():
            return None
        jobs = [self.roll_check(ch, *spec, private=ch.name in secret) if spec else no_roll()
                for _, ch, _, spec in plans]
        group_job = self._group_check(party, group) if group else no_roll()
        results, group_lines = await asyncio.gather(asyncio.gather(*jobs), group_job)
        if group_lines:
            outcomes += group_lines

        # ── phase 3: apply consequences in order ─────────────────
        private_out: dict[str, list[str]] = {n: [] for n in secret}
        rest_kind: str | None = None
        for (ruling, ch, disc, spec), result in zip(plans, results):
            hours = max(hours, ruling.time_minutes / 60)
            is_secret = ch.name in secret
            sink = private_out[ch.name] if is_secret else outcomes
            if result is not None:
                reason = f" — amaç: {ruling.check.reason}" if ruling.check else ""
                sink.append(f"{ch.name} — {skill_or_ability_name(spec[0])} (ZS {spec[1]}): "
                            f"{DEGREE_TR[result.degree]} (zar {result.natural}, toplam {result.total}){reason}")
            success = result is None or result.success
            if disc and success:
                sink += await self._apply_discovery(ch, disc, private=is_secret)
            if ruling.destination and success and moved_to is None and not is_secret:
                travel = await self._travel(ruling.destination)
                if travel:
                    moved_to, h, line = travel
                    hours = max(hours, h)
                    outcomes.append(line)
            if ruling.item_action != "none":
                line = self._apply_item_action(ch, ruling, success)
                if line:
                    sink.append(line)
            if ruling.rest != "none" and not is_secret:
                rest_kind = "long" if ruling.rest == "long" or rest_kind == "long" else "short"
        # resting: game time is shared, so the whole party rests together
        if rest_kind:
            hours = max(hours, 8 if rest_kind == "long" else 1)
            if rest_kind == "long" and ws.last_long_rest_day == ws.day and ws.day > 1:
                outcomes.append("The party already had a long rest today; they only catch a short breather.")
                rest_kind = "short"
            lines = [self._rest(c, rest_kind, mark=False) for c in party]
            if rest_kind == "long":
                ws.last_long_rest_day = ws.day
            outcomes.append(" / ".join(lines))
        # time & fronts
        notes += ws.advance_time(sc, hours)
        if moved_to:
            notes.append(f"The party has arrived at: {ws.loc(sc).name}. Describe the arrival.")
        # stall breaker: nothing changed for a while -> the world moves on its own
        progress = (moved_to is not None or len(ws.found) != self._last_progress[0]
                    or len(ws.journal) != self._last_progress[1] or adj.starts_combat)
        self._stall = 0 if progress else self._stall + 1
        self._last_progress = (len(ws.found), len(ws.journal))
        if self._stall >= 3:
            self._stall = 0
            twist = random.choice(sc.random_events) if sc and sc.random_events else ""
            notes.append("THE SCENE HAS STALLED for several rounds. Resolve the current standoff decisively and "
                         "introduce a NEW development (someone arrives, the situation changes, an opportunity or "
                         f"threat appears).{(' Possible event: ' + twist) if twist else ''}")
            # never let the story die on failed rolls: hand the party the easiest clue here
            avail = sorted(ws.available_discoveries(sc), key=lambda d: d.check.dc if d.check else 0)
            if avail and party:
                clue = avail[0]
                who = random.choice(party)
                outcomes += await self._apply_discovery(who, clue)
                notes.append(f"Deliver this clue NATURALLY through an NPC present or an event (not by luck of the "
                             f"dice): {clue.reveals}")
        # combat?
        if adj.starts_combat:
            await self._begin_combat_from_adjudication(adj, by_name, outcomes)
            return
        public = {n: a for n, a in by_name.items() if n not in secret}
        actions_block = "\n".join(f"{name}: {a.text}" for name, a in public.items())
        if secret:
            actions_block += ("\n(" + ", ".join(secret) + " quietly did something on their own this round. Do NOT "
                              "describe or hint at it; just keep them present in the scene.)")
        words = self.gm.words_for(max(1, len(public)))
        await self._narrate(actions_block=actions_block, outcomes=outcomes, notes=notes,
                            instruction=f"Narrate the results now, in Turkish, about {words} words (never more than "
                                        f"{words + 30}). Address every character's action within one flowing scene.",
                            kind="round", max_tokens=int(words * 2.6) + 80)
        for name in secret:
            await self._narrate_private(name, by_name[name].text, private_out[name])
        await self._post_narration(party)

    async def _narrate_private(self, name: str, action: str, outcomes: list[str]) -> None:
        """A whispered action: its outcome goes only to that player's phone, in second person."""
        assert self.gm
        ch = next((c for c in self.party() if c.name == name), None)
        player = self.player_of_char(ch.id) if ch else None
        if ch is None or player is None:
            return
        instruction = (f"PRIVATE MESSAGE that only {name} will read. In Turkish, speaking directly to them in "
                       "second person ('sen'), 40-90 words, narrate what happens with their SECRET action and its "
                       "outcome. Nobody else noticed unless an outcome says so.")
        nid = uuid.uuid4().hex[:8]
        to = [player.id]
        await self.emit({"t": "narration_start", "id": nid, "kind": "private"}, to)
        parts: list[str] = []
        async for piece in self.gm.narrate([ch], actions_block=f"{name} (secretly): {action}", outcomes=outcomes,
                                           notes=[], instruction=instruction, max_tokens=260, record=False):
            parts.append(piece)
            await self.emit({"t": "narration_chunk", "id": nid, "text": piece}, to)
        text = self.gm.polish("".join(parts), self.party())
        await self.emit({"t": "narration_end", "id": nid, "text": text, "kind": "private"}, to)
        # the GM remembers it as a secret so the story stays consistent
        self.gm.history.append({"role": "user", "content": f"(SECRET, known only to {name}) {name}: {action}"})
        self.gm.history.append({"role": "assistant", "content": f"(SECRET for {name}) {text}"[:1500]})

    # ── speculative adjudication ───────────────────────────────
    def _speculate(self, ch: Character, text: str) -> None:
        """Rule on one player's action while the others are still typing (uses idle GPU time)."""
        if self.gm is None or self.busy or len(self.living_party()) < 2:
            return
        old = self._spec.pop(ch.id, None)
        if old and not old[2].done():
            old[2].cancel()
        task = self._spawn(self.gm.adjudicate({ch.name: text}, self.living_party()))
        self._spec[ch.id] = (text, self.round_no, task)

    async def _adjudicate_with_speculation(self, actions: dict[str, PendingAction],
                                           party: list[Character]) -> ExploreAdjudication:
        assert self.gm
        rulings: list[ExploreRuling] = []
        extras: list[ExploreAdjudication] = []
        todo: dict[str, str] = {}
        for cid, a in actions.items():
            ch = self.characters[cid]
            spec = self._spec.get(cid)
            if spec and spec[0] == a.text and spec[1] == self.round_no:
                try:
                    pre = await asyncio.wait_for(asyncio.shield(spec[2]), timeout=60)
                    r = next((x for x in pre.rulings if x.player == ch.name), None)
                    if r is not None:
                        rulings.append(r)
                        extras.append(pre)
                        continue
                except Exception:
                    pass
            todo[ch.name] = a.text
        self._spec.clear()
        self.round_no += 1
        if todo:
            batch = await self.gm.adjudicate(todo, party)
            rulings += batch.rulings
            extras.append(batch)
        order = {self.characters[cid].name: i for i, cid in enumerate(actions)}
        rulings.sort(key=lambda r: order.get(r.player, 99))
        merged = ExploreAdjudication(rulings=rulings)
        fight = next((e for e in extras if e.starts_combat), None)
        if fight is not None:
            merged.starts_combat = True
            merged.encounter_id = fight.encounter_id
            merged.enemies = fight.enemies
            merged.battlefield = fight.battlefield
            merged.ambush = fight.ambush
        return merged

    async def _group_check(self, party: list[Character], ruling: ExploreRuling) -> list[str]:
        assert ruling.check
        results = await asyncio.gather(*[self.roll_check(c, ruling.check.skill, ruling.check.dc,
                                                         ruling.check.advantage) for c in party])
        ok = sum(1 for r in results if r.success)
        success = ok * 2 >= len(results)
        return [f"GROUP {skill_or_ability_name(ruling.check.skill)} (ZS {ruling.check.dc}): "
                f"{ok}/{len(results)} başarılı → {'GRUP BAŞARILI' if success else 'GRUP BAŞARISIZ'}"]

    async def _apply_discovery(self, ch: Character, disc, *, private: bool = False) -> list[str]:
        ws, sc = self.world, self.scenario
        assert ws
        if disc.id in ws.found:  # two characters went for the same secret this round
            return [f"{ch.name} also sees it."]
        out = [f"{ch.name} DISCOVERED (reveal this): {disc.reveals}"]
        revealed = ws.discover(sc, disc)
        if revealed:
            out.append("New places now known: " + ", ".join(revealed))
        if disc.item:
            stack = None
            try:
                if disc.item.get("id"):
                    stack = ch.inventory.add(disc.item["id"], int(disc.item.get("qty", 1)))
                else:
                    stack = ch.inventory.add_custom(disc.item.get("name", "Gizemli Eşya"),
                                                    kind=disc.item.get("kind", "quest"),
                                                    description=disc.item.get("description", ""))
            except InventoryError:
                stack = None
            if stack:
                out.append(f"{ch.name} TAKES and now holds '{stack.name}' (show how they get it in the scene)")
                await self.toast(f"🎒 {ch.name}: {stack.name} envantere eklendi", "item", self._aud(ch, private))
        if disc.gold:
            ch.inventory.add_coins(gp=disc.gold)
            out.append(f"{ch.name} found {disc.gold} gold")
        for c in self.living_party():
            c.gain_xp(disc.xp // max(1, len(self.living_party())))
        await self.toast(f"🔎 Yeni ipucu: {disc.reveals[:90]}", "clue", self._aud(ch, private))
        return out

    def _aud(self, ch: Character, private: bool) -> list[str] | None:
        p = self.player_of_char(ch.id)
        return [p.id] if (private and p) else None

    async def _travel(self, destination: str) -> tuple[str, float, str] | None:
        ws, sc = self.world, self.scenario
        assert ws
        loc = ws.find_location(sc, destination)
        if loc is None:
            secret = ws.find_adjacent_hidden(sc, destination)
            if secret is not None:
                ws.known.append(secret.id)
                ws.add_journal("place", f"Gizli bir yer bulundu: {secret.name}")
                loc = secret
        if loc is None:
            # unknown place: create it as an improvised location (freedom!) — but only for a real,
            # player-given name; id-like inventions from the referee ("koridor_girisi") are ignored
            if re.fullmatch(r"[a-z0-9_]+", destination.strip()) and "_" in destination:
                return None
            name = destination.strip().strip(".")
            name = tr_upper(name[0]) + name[1:] if name else name
            if not _is_proper_place(name) and sc is not None:
                return None
            loc = ws.add_dynamic_location(sc, name, f"{name} — oyuncuların keşfettiği yeni bir yer.")
        if loc.id == ws.location:
            return None
        if not ws.can_travel(sc, loc.id):
            if loc.hidden and loc.id not in ws.known:
                return None
            ws.known.append(loc.id) if loc.id not in ws.known else None
        hours = ws.move_to(sc, loc.id)
        return loc.id, hours, f"The party travels to {loc.name} ({hours} saat)."

    def _apply_item_action(self, ch: Character, r: ExploreRuling, success: bool) -> str | None:
        ws = self.world
        assert ws
        act, name = r.item_action, (r.item or "").strip()
        try:
            if act == "take" and success and name:
                st = ws.take_item(name)
                if st is None:
                    return f"{ch.name} looked for '{name}' but it is not here."
                ch.inventory.add_stack(st)
                self._spawn(self.toast(f"🎒 {ch.name}: {st.display_name()} aldı", "item"))
                return f"{ch.name} took {st.display_name()}."
            if act == "give" and name and r.item_to:
                to = next((c for c in self.party() if similar(c.name, r.item_to)), None)
                st = ch.inventory.find(name)
                if to is None or st is None or to.id == ch.id:
                    return None
                moved = ch.inventory.remove(st.uid, st.qty if st.stackable else 1)
                to.inventory.add_stack(moved)
                self._spawn(self.toast(f"🤝 {ch.name} → {to.name}: {moved.display_name()}", "item"))
                return f"{ch.name} gave {moved.display_name()} to {to.name}."
            if act == "drop" and name:
                st = ch.inventory.find(name)
                if st is None:
                    return None
                moved = ch.inventory.remove(st.uid, st.qty)
                ws.drop_item(moved)
                return f"{ch.name} dropped {moved.display_name()}."
            if act == "buy" and name:
                return self._buy(ch, name)
            if act == "sell" and name:
                return self._sell(ch, name)
            if act == "use" and name:
                st = ch.inventory.find(name)
                if st and st.definition and st.definition.effect == "heal":
                    ch.inventory.remove(st.uid, 1)
                    amt = roll(str(st.definition.amount)).total
                    got = ch.heal(amt)
                    return f"{ch.name} drank {st.name} and healed {got} HP."
            if act == "equip" and name:
                st = ch.inventory.find(name)
                if st:
                    return ch.inventory.equip(st.uid, strength=ch.score("strength"))
        except InventoryError as exc:
            return f"{ch.name}: {exc}"
        return None

    def _shop_here(self) -> list[dict]:
        if not self.scenario or not self.world:
            return []
        try:
            return self.world.loc(self.scenario).shop
        except KeyError:
            return []

    def _buy(self, ch: Character, name: str) -> str:
        shop = self._shop_here()
        match = None
        for entry in shop:
            d = data.items().get(entry["id"])
            if d and (similar(d.name, name) or similar(entry["id"].replace("_", " "), name)):
                match = (entry, d)
                break
        if match is None:
            # free mode / unlisted: allow buying common catalog gear at list price
            for iid, d in data.items().items():
                if d.rarity == "common" and d.type in ("weapon", "armor", "shield", "gear", "consumable", "ammo", "tool") \
                        and similar(d.name, name):
                    match = ({"id": iid, "price": d.value}, d)
                    break
        if match is None:
            return f"{ch.name} could not find '{name}' for sale here."
        entry, d = match
        price = float(entry.get("price", d.value))
        if not ch.inventory.can_afford(price):
            return f"{ch.name} cannot afford {d.name} ({price} altın)."
        ch.inventory.add_coins(gp=-price)
        qty = 20 if d.type == "ammo" else 1
        ch.inventory.add(entry["id"], qty)
        self._spawn(self.toast(f"🪙 {ch.name}: {d.name} satın aldı (-{price:g} altın)", "item"))
        return f"{ch.name} bought {d.name} for {price:g} gold."

    def _sell(self, ch: Character, name: str) -> str:
        st = ch.inventory.find(name)
        if st is None:
            return f"{ch.name} has no '{name}'."
        if st.kind == "quest":
            return f"{ch.name} cannot sell a quest item."
        price = round(max(0.01, st.value * 0.5), 2)
        ch.inventory.remove(st.uid, 1)
        ch.inventory.add_coins(gp=price)
        return f"{ch.name} sold {st.name} for {price:g} gold."

    def _rest(self, ch: Character, kind: str, *, mark: bool = True) -> str:
        ws = self.world
        assert ws
        if kind == "short":
            info = ch.short_rest()
            return f"{ch.name} took a short rest (healed {info['healed']})."
        if mark and ws.last_long_rest_day == ws.day and ws.day > 1:
            return f"{ch.name} cannot benefit from another long rest today."
        ch.long_rest()
        if mark:
            ws.last_long_rest_day = ws.day
        return f"{ch.name} took a long rest and is fully restored."

    async def _post_narration(self, party: list[Character]) -> None:
        """Background: extract facts, maybe summarize, level-up notices."""
        assert self.gm
        text = self.gm.last_narration
        if text:
            self._spawn(self._apply_extraction(text, party))
        if self.gm.needs_summary():
            self._spawn(self.gm.summarize())
        for c in party:
            if c.can_level_up():
                p = self.player_of_char(c.id)
                await self.toast(f"⭐ {c.name} seviye atlayabilir!", "level", [p.id] if p else None)

    async def _apply_extraction(self, narration: str, party: list[Character]) -> None:
        assert self.gm and self.world
        ex: StoryExtraction = await self.gm.extract(narration, party)
        ws, sc = self.world, self.scenario
        names = {c.name.lower() for c in party}
        changed = False
        for n in ex.new_npcs[:4]:
            if n.name.lower() in names or not n.name.strip():
                continue
            if ws.find_npc(n.name):
                ws.find_npc(n.name).met = True  # type: ignore[union-attr]
                continue
            ws.add_dynamic_npc(n.name, n.role, n.description)
            changed = True
        for it in ex.items_in_scene[:4]:
            if not any(similar(s.name, it.name) for c in party for s in c.inventory.items):
                ws.place_custom_item(it.name, description=it.where)
                changed = True
        budget = 60.0
        for g in ex.items_given[:3]:
            to = next((c for c in party if similar(c.name, g.to)), None)
            if to is None:
                continue
            if any(similar(s.name, g.item) for s in to.inventory.items):
                continue
            stack = self._catalog_or_custom(to, g.item, g.giver)
            if stack:
                await self.toast(f"🎒 {to.name}: {stack.name} ({g.giver or 'hediye'})", "item")
                changed = True
        for g in ex.gold_given[:2]:
            to = next((c for c in party if similar(c.name, g.to)), None)
            if to and g.amount_gp > 0:
                amt = min(g.amount_gp, budget)
                budget -= amt
                to.inventory.add_coins(gp=amt)
                await self.toast(f"🪙 {to.name}: +{amt:g} altın", "item")
                changed = True
        for p in ex.places_mentioned[:3]:
            if not _is_proper_place(p.name):
                continue
            loc = ws.find_location(sc, p.name) or ws.find_adjacent_hidden(sc, p.name)
            if loc is not None:
                if loc.id not in ws.known and not loc.hidden:
                    ws.known.append(loc.id)
                    ws.add_journal("place", f"Yeni bir yer duyuldu: {loc.name}")
                    changed = True
            elif sc is None:  # free mode: the world grows from the story
                ws.add_dynamic_location(sc, p.name, p.description or p.name, travel_hours=2)
                ws.add_journal("place", f"Yeni bir yer duyuldu: {p.name}")
                changed = True
        for f in ex.facts[:3]:
            ws.add_journal("clue", f)
            changed = True
        active_dynamic = sum(1 for k, v in ws.quests.items() if k.startswith("dq_") and v == "active")
        for q in ex.quest_updates[:1]:
            if q.status == "new" and (sc is not None and not any(similar(x.name, q.name) for x in sc.quests.values())):
                # scenario mode: only the scenario's own quests (or ones an NPC explicitly hands out in free mode)
                continue
            if q.status == "new" and active_dynamic >= 4:
                continue
            changed |= self._apply_quest_update(q.name, q.status, q.description)
        for a in ex.attitude_changes[:3]:
            npc = ws.find_npc(a.name)
            if npc:
                npc.attitude = a.attitude
        for dead in ex.npc_deaths[:3]:
            npc = ws.find_npc(dead)
            if npc:
                npc.alive = False
                changed = True
        for npc in ws.npcs_here():
            npc.met = True
        if changed:
            await self.broadcast_state()

    def _catalog_or_custom(self, ch: Character, name: str, giver: str):
        for iid, d in data.items().items():
            if similar(d.name, name) and d.rarity in ("common", "uncommon") and d.type != "magic":
                try:
                    return ch.inventory.add(iid)
                except InventoryError:
                    return None
        return ch.inventory.add_custom(name, kind="quest" if any(w in name.lower() for w in
                                                                  ("mektup", "anahtar", "harita", "defter", "not"))
                                       else "trinket", description=f"{giver} verdi" if giver else "")

    def _apply_quest_update(self, name: str, status: str, description: str) -> bool:
        ws, sc = self.world, self.scenario
        assert ws
        qid = None
        if sc:
            for k, q in sc.quests.items():
                if similar(q.name, name):
                    qid = k
                    break
        if qid is None:
            for k, q in ws.dynamic_quests.items():
                if similar(q.get("name", ""), name):
                    qid = k
                    break
        if qid is None and status == "new":
            qid = f"dq_{len(ws.dynamic_quests) + 1}"
            ws.dynamic_quests[qid] = {"name": name[:60], "hook": description[:300], "objectives": []}
        if qid is None:
            return False
        new = {"new": "active", "done": "done", "failed": "failed"}[status]
        if ws.quests.get(qid) == new:
            return False
        ws.quests[qid] = new
        ws.add_journal("quest", f"Görev {'alındı' if new == 'active' else 'tamamlandı' if new == 'done' else 'başarısız'}: {name}")
        if new == "done":
            xp, gold, items = 100, 0, []
            if sc and qid in sc.quests:
                q = sc.quests[qid]
                xp, gold, items = q.reward_xp, q.reward_gold, q.reward_items
            alive = self.living_party()
            for c in alive:
                c.gain_xp(xp // max(1, len(alive)) if xp > 300 else xp)
            if alive and gold:
                share = gold / len(alive)
                for c in alive:
                    c.inventory.add_coins(gp=share)
            for i, iid in enumerate(items):
                if alive:
                    alive[i % len(alive)].inventory.add(iid)
        return True

    # ═══════════════════════════════════════════════════════════
    # Narration plumbing
    # ═══════════════════════════════════════════════════════════

    async def _narrate(self, *, actions_block: str, outcomes: list[str], notes: list[str], instruction: str,
                       kind: str = "round", stream_fn=None, max_tokens: int = 520) -> str:
        assert self.gm
        nid = uuid.uuid4().hex[:8]
        await self.emit({"t": "narration_start", "id": nid, "kind": kind}, None)
        parts: list[str] = []
        gen = stream_fn if stream_fn is not None else self.gm.narrate(
            self.living_party() or self.party(), actions_block=actions_block, outcomes=outcomes, notes=notes,
            instruction=instruction, max_tokens=max_tokens)
        async for piece in gen:
            parts.append(piece)
            await self.emit({"t": "narration_chunk", "id": nid, "text": piece}, None)
        text = self.gm.last_narration if stream_fn is None else self.gm.polish("".join(parts), self.party())
        entry = {"id": nid, "text": text, "kind": kind, "at": time.time()}
        self.narration_log.append(entry)
        if len(self.narration_log) > 200:
            self.narration_log = self.narration_log[-200:]
        await self.emit({"t": "narration_end", "id": nid, "text": text, "kind": kind}, None)
        return text

    # ═══════════════════════════════════════════════════════════
    # Combat
    # ═══════════════════════════════════════════════════════════

    async def _begin_combat_from_adjudication(self, adj: ExploreAdjudication, by_name: dict[str, PendingAction],
                                              outcomes: list[str]) -> None:
        sc, ws = self.scenario, self.world
        assert ws
        specs: list[dict] = []
        features: list[EnvFeature] = []
        title = ""
        if adj.encounter_id:
            here = ws.loc(sc)
            enc_spec = next((e for e in here.encounters if e.id == adj.encounter_id), None)
            if enc_spec:
                specs = list(enc_spec.enemies)
                features = [EnvFeature(**f) for f in enc_spec.features]
                title = enc_spec.when[:60]
                ws.used_encounters.append(enc_spec.id)
        if not specs:
            specs = [{"monster": e.kind, "count": e.count, "name": e.name} for e in adj.enemies]
            specs = balance_specs(specs, self.living_party())
        if not features:
            for f in adj.battlefield[:3]:
                features.append(EnvFeature(name=f.name, description=f.description, effect=f.effect,
                                           damage="2d6" if f.effect in ("hazard", "push_hazard", "trap") else None,
                                           dc=12 + self.party_level() // 2))
        if not specs:
            return
        actions_block = "\n".join(f"{n}: {a.text}" for n, a in by_name.items())
        await self.start_combat(specs, features=features, title=title, ambush=adj.ambush,
                                lead_in=(actions_block, outcomes))

    async def start_combat(self, specs: list[dict], *, features: list[EnvFeature] | None = None, title: str = "",
                           ambush: bool = False, lead_in: tuple[str, list[str]] | None = None) -> None:
        party = {c.id: c for c in self.living_party()}
        enc = CombatEngine.build(specs, party, title=title, features=features or [])
        self.engine = CombatEngine(enc, party)
        self.mode = "combat"
        for c in party.values():
            c.remove_condition("dodging")
        await self.broadcast_state()
        foes = ", ".join(f"{e.name}" for e in enc.enemies)
        feats = "; ".join(f"{f.name} ({f.description})" for f in enc.features)
        actions_block, outcomes = lead_in or ("", [])
        instruction = (f"COMBAT STARTS NOW{' — AMBUSH! The enemies strike first.' if ambush else ''}. "
                       f"Describe the enemies ({foes}) appearing/attacking and the battlefield"
                       f"{(' including: ' + feats) if feats else ''}. 60-130 words, Turkish, tense and cinematic. "
                       "Do not describe anyone's attack results yet.")
        await self._narrate(actions_block=actions_block, outcomes=outcomes, notes=[], instruction=instruction,
                            kind="combat_start")
        # initiative: every player taps at once
        rolls = await asyncio.gather(*[
            self.request_roll(c.id, "İnisiyatif", bonus=c.initiative_bonus, purpose="initiative")
            for c in party.values()])
        pc_rolls = {c.id: r for c, r in zip(party.values(), rolls)}
        if ambush:
            for k in pc_rolls:
                pc_rolls[k] = roll(f"1d20{'+' if party[k].initiative_bonus >= 0 else ''}{party[k].initiative_bonus}",
                                   advantage="disadvantage")
        events = self.engine.roll_initiative(pc_rolls)
        await self._emit_events(events)
        self._spawn(self.combat_loop())

    async def combat_loop(self) -> None:
        eng = self.engine
        if eng is None:
            return
        eng.start_turn()
        pending_lines: list[str] = []
        while self.mode == "combat" and eng.enc.status == "active":
            ref = eng.current()
            if ref is None:
                break
            await self.broadcast_state()
            if eng.is_pc(ref):
                if pending_lines:
                    await self._combat_beat(pending_lines)
                    pending_lines = []
                ch = eng.pc(ref)
                await self._pc_turn(ch)
            else:
                e = eng.enc.enemy(ref)
                events = enemy_turn(eng, e)
                await self._emit_events(events)
                pending_lines += [ev.text for ev in events if ev.text and ev.type not in ("turn", "round")]
            if eng.enc.status != "active":
                break
            end_events = eng.end_turn()
            await self._emit_events(end_events)
            if eng.enc.status != "active":
                break
            start_events = eng.start_turn()
            await self._emit_events([e for e in start_events if e.type != "turn"])
        if pending_lines:
            await self._combat_beat(pending_lines)
        await self._end_combat()

    async def _pc_turn(self, ch: Character) -> None:
        """Wait for the player to act (commands arrive via combat_command). Handles dying & AFK."""
        eng = self.engine
        assert eng
        player = self.player_of_char(ch.id)
        if ch.hp <= 0 and not ch.dead and not ch.stable:
            r = await self.request_roll(ch.id, "Ölüm zarı", purpose="death_save")
            events = eng.death_save(ch.id, d20=r)
            await self._emit_events(events)
            await self._combat_beat([ev.text for ev in events])
            return
        if not ch.can_act or ch.hp <= 0:
            return
        if player is None or not player.connected:
            events = auto_pc_turn(eng, ch)
            await self._emit_events(events)
            if events:
                await self._combat_beat([ev.text for ev in events if ev.text])
            return
        self._turn_waiter = asyncio.Event()
        await self.emit({"t": "your_turn", "char_id": ch.id, "options": self.combat_options(ch)}, [player.id])
        await self.toast(f"⚔️ Sıra {ch.name}'de", "turn")
        try:
            await asyncio.wait_for(self._turn_waiter.wait(), timeout=self.settings.turn_timeout)
        except asyncio.TimeoutError:
            await self.toast(f"{ch.name} kararsız kaldı — içgüdüleriyle hareket ediyor", "info")
            events = auto_pc_turn(eng, ch)
            await self._emit_events(events)
            if events:
                await self._combat_beat([ev.text for ev in events if ev.text])
        finally:
            self._turn_waiter = None

    def combat_options(self, ch: Character) -> dict:
        eng = self.engine
        assert eng
        t = eng.enc.turn
        spells = []
        for sid in ch.known_spells():
            sp = data.spell(sid)
            if sp.model_extra.get("utility") and sp.kind == "utility":
                continue
            cost = sp.cast
            ok = (sp.level == 0 or any(n > 0 and lv >= sp.level for lv, n in ch.spell_slots.items())) and \
                ((cost == "action" and t.action > 0) or (cost == "bonus" and t.bonus > 0))
            spells.append({"id": sid, "name": sp.name, "level": sp.level, "cast": cost, "kind": sp.kind,
                           "target": sp.target, "available": ok, "damage": sp.damage, "heal": sp.heal})
        feats = []
        res = ch.resources
        def add(fid, name, cost, avail, needs_target=None):
            feats.append({"id": fid, "name": name, "cost": cost, "available": avail, "target": needs_target})
        if ch.has("second_wind"):
            add("second_wind", "İkinci Nefes", "bonus", res.get("second_wind", 0) > 0 and t.bonus > 0)
        if ch.has("action_surge"):
            add("action_surge", "Atılım", "free", res.get("action_surge", 0) > 0)
        if ch.has("rage"):
            add("rage", "Öfke", "bonus", res.get("rage", 0) > 0 and t.bonus > 0 and not ch.has_condition("raging"))
        if ch.has("reckless_attack"):
            add("reckless_attack", "Pervasız Saldırı", "free", not ch.has_condition("reckless"))
        if ch.has("lay_on_hands"):
            add("lay_on_hands", f"Elle Şifa ({res.get('lay_on_hands', 0)})", "action",
                res.get("lay_on_hands", 0) > 0 and t.action > 0, "ally")
        if ch.has("sacred_weapon"):
            add("sacred_weapon", "Kutsal Silah", "action", res.get("sacred_weapon", 0) > 0 and t.action > 0)
        if ch.has("bardic_inspiration"):
            add("bardic_inspiration", "Ozan İlhamı", "bonus", res.get("bardic_inspiration", 0) > 0 and t.bonus > 0, "ally")
        if ch.has("turn_undead"):
            add("turn_undead", "Ölümsüzleri Kov", "action", res.get("channel_divinity", 0) > 0 and t.action > 0)
        if ch.has("preserve_life"):
            add("preserve_life", "Yaşamı Koru", "action", res.get("channel_divinity", 0) > 0 and t.action > 0)
        if ch.has_condition("spiritual_weapon"):
            add("spiritual_weapon_attack", "Ruhani Silah Saldırısı", "bonus", t.bonus > 0, "enemy")
        if ch.has("cunning_action"):
            add("cunning_disengage", "Sinsi Kopma", "bonus", t.bonus > 0)
            add("cunning_hide", "Sinsi Saklanma", "bonus", t.bonus > 0)
        items = [{"uid": s.uid, "name": s.display_name(), "effect": s.definition.effect}
                 for s in ch.inventory.items if s.definition and s.definition.type == "consumable"]
        return {
            "turn": t.model_dump(), "attacks": ch.attack_options(), "spells": spells, "features": feats,
            "items": items, "rank": ch.rank, "can_smite": ch.has("divine_smite") and any(ch.spell_slots.values()),
            "slots": ch.spell_slots,
            "env": [f.model_dump() for f in eng.enc.features if f.uses != 0],
        }

    async def combat_command(self, player_id: str, cmd: dict) -> dict:
        """Handle a combat action from the current player's phone."""
        eng = self.engine
        ch = self.char_of_player(player_id)
        if self.mode != "combat" or eng is None or ch is None:
            raise CombatError("Savaş yok.")
        if eng.current() != f"pc:{ch.id}":
            raise CombatError("Sıra sende değil.")
        if self.busy:
            raise CombatError("Bir önceki eylem çözülüyor, bekle.")
        kind = cmd.get("type")
        self.busy = True
        try:
            events: list[Event] = []
            if kind == "attack":
                spec = eng.attack_roll_spec(ch.id, cmd["target"], cmd.get("weapon"))
                r = await self.request_roll(ch.id, f"Saldırı: {spec['weapon']} → {spec['target']}",
                                            bonus=spec["bonus"], advantage=spec["advantage"], purpose="attack")
                events = eng.pc_attack(ch.id, cmd["target"], weapon_uid=cmd.get("weapon"), d20=r,
                                       smite_level=cmd.get("smite"))
            elif kind == "cast":
                events = eng.pc_cast(ch.id, cmd["spell"], slot=cmd.get("slot"), targets=cmd.get("targets") or [],
                                     rank=cmd.get("rank"))
            elif kind == "feature":
                fid = cmd["feature"]
                if fid == "cunning_disengage":
                    events = eng.pc_disengage(ch.id, bonus=True)
                elif fid == "cunning_hide":
                    r = await self.request_roll(ch.id, "Gizlilik", bonus=ch.skill_bonus("stealth"))
                    events = eng.pc_hide(ch.id, bonus=True, d20=r)
                else:
                    events = eng.pc_feature(ch.id, fid, target_id=cmd.get("target"), amount=cmd.get("amount"))
            elif kind == "item":
                events = eng.pc_use_item(ch.id, cmd["uid"], target=cmd.get("target"))
            elif kind == "move":
                events = eng.pc_move(ch.id, cmd["rank"], disengage=bool(cmd.get("disengage")))
            elif kind == "dodge":
                events = eng.pc_dodge(ch.id)
            elif kind == "disengage":
                events = eng.pc_disengage(ch.id)
            elif kind == "help":
                events = eng.pc_help(ch.id, cmd["ally"])
            elif kind == "hide":
                r = await self.request_roll(ch.id, "Gizlilik", bonus=ch.skill_bonus("stealth"))
                events = eng.pc_hide(ch.id, d20=r)
            elif kind == "flee":
                b = max(ch.skill_bonus("athletics"), ch.skill_bonus("acrobatics"))
                r = await self.request_roll(ch.id, "Kaçış", bonus=b)
                events = eng.pc_flee(ch.id, d20=r)
            elif kind == "improvise":
                events = await self._improvise(ch, str(cmd.get("text", ""))[:300])
            elif kind == "end_turn":
                if self._turn_waiter:
                    self._turn_waiter.set()
                return {"ok": True}
            else:
                raise CombatError("Bilinmeyen komut.")
            await self._emit_events(events)
            lines = [ev.text for ev in events if ev.text]
            if lines:
                await self._combat_beat(lines)
            t = eng.enc.turn
            done = eng.enc.status != "active" or ch.hp <= 0 or (t.action <= 0 and t.bonus <= 0)
            if done and self._turn_waiter:
                self._turn_waiter.set()
            elif self._turn_waiter:
                await self.emit({"t": "your_turn", "char_id": ch.id, "options": self.combat_options(ch)}, [player_id])
            return {"ok": True}
        finally:
            self.busy = False
            await self.broadcast_state()

    async def _improvise(self, ch: Character, text: str) -> list[Event]:
        eng = self.engine
        assert eng and self.gm
        ruling = await self.gm.improvise(ch, text, eng.public_state())
        if not ruling.feasible:
            raise CombatError(ruling.explanation or "Bu şu an mümkün değil.")
        success, degree = True, "success"
        if ruling.check:
            res = await self.roll_check(ch, ruling.check.skill, max(8, min(20, ruling.check.dc)),
                                        ruling.check.advantage)
            success, degree = res.success, res.degree
        if ruling.effect == "use_feature" and ruling.feature_id:
            f = next((x for x in eng.enc.features if x.id == ruling.feature_id), None)
            if f:
                return eng.pc_use_feature(ch.id, f.id, success=success)
        cap = {1: "2d6", 2: "2d6", 3: "3d6", 4: "3d6"}.get(ch.level, "4d6")
        dmg = ruling.damage
        if dmg and _dice_count(dmg) > _dice_count(cap):
            dmg = cap
        target = None
        if ruling.target:
            target = next((e.uid for e in eng.enc.active_enemies()
                           if e.label == ruling.target.strip().upper() or similar(e.name, ruling.target)), None)
        ally = next((c.id for c in self.party() if ruling.ally and similar(c.name, ruling.ally)), None)
        return eng.improvised_effect(ch.id, success=success, degree=degree, effect=ruling.effect, target=target,
                                     damage=dmg, damage_type=ruling.damage_type, condition=ruling.condition,
                                     ally=ally, description=text)

    async def _emit_events(self, events: list[Event]) -> None:
        if not events:
            return
        for ev in events:
            d = ev.model_dump()
            roll_data = ev.data.get("roll")
            if roll_data and ev.type in ("attack", "save", "check", "death_save", "roll", "special"):
                await self.emit({"t": "dice", "id": uuid.uuid4().hex[:8], "char": self._name_for(ev.actor or ev.target),
                                 "label": ev.text.split(":")[0][:60], "roll": roll_data, "purpose": ev.type,
                                 "auto": True, "quick": True}, None)
            await self.emit({"t": "combat_event", "event": d}, None)
        await self.broadcast_state()

    def _name_for(self, ref: str | None) -> str:
        if not ref or not self.engine:
            return ""
        try:
            return self.engine.name_of(ref)
        except KeyError:
            return ""

    async def _combat_beat(self, lines: list[str]) -> None:
        if not self.gm or not lines:
            return
        eng = self.engine
        highlights = list(eng.enc.highlights) if eng else []
        if eng:
            eng.enc.highlights.clear()
        await self._narrate(actions_block="", outcomes=[], notes=[], instruction="", kind="combat",
                            stream_fn=self.gm.combat_beat(self.party(), lines[-12:], highlights[-4:]))

    async def _end_combat(self) -> None:
        eng = self.engine
        if eng is None:
            return
        status = eng.enc.status
        rewards = eng.rewards()
        ws = self.world
        outcomes: list[str] = []
        if status == "victory":
            for cid in rewards["survivors"]:
                self.characters[cid].gain_xp(rewards["xp_each"])
            loot = rewards["loot"]
            if ws:
                for iid in loot["items"]:
                    ws.place_custom_item(data.item(iid).name, item_id=iid)
                if loot["copper"]:
                    alive = [self.characters[c] for c in rewards["survivors"]]
                    share = loot["copper"] // max(1, len(alive))
                    for c in alive:
                        c.inventory.add_coins(cp=share)
            outcomes.append(f"VICTORY. Each survivor gains {rewards['xp_each']} XP.")
            if loot["items"]:
                outcomes.append("Loot lying on the ground: " + ", ".join(data.item(i).name for i in loot["items"]))
            if loot["copper"]:
                outcomes.append(f"Coins found and shared: {loot['copper'] // 100} altın")
            surrendered = [e.name for e in eng.enc.enemies if e.state == "surrendered"]
            if surrendered:
                outcomes.append("Surrendered enemies kneel before the party, waiting for their fate: "
                                + ", ".join(surrendered))
            for e in eng.enc.enemies:
                if e.state == "surrendered" and ws:
                    ws.add_dynamic_npc(e.name, f"teslim olmuş {e.mdef.name}", "Silahsız, diz çökmüş.")
        elif status == "fled":
            outcomes.append("The party escaped the battle.")
        elif status == "defeat":
            if self.settings.mercy:
                for c in self.party():
                    if c.dead:
                        continue
                    c.hp = max(c.hp, 1)
                    c.stable = False
                    c.death_saves.successes = c.death_saves.failures = 0
                outcomes.append("DEFEAT. The party is overwhelmed but NOT killed: they wake up later captured, "
                                "robbed or left for dead — describe a grim but survivable consequence.")
            else:
                outcomes.append("DEFEAT. The party has fallen.")
        dead = [c.name for c in self.party() if c.dead]
        if dead:
            outcomes.append("Fallen comrades: " + ", ".join(dead))
        self.mode = "exploration"
        self.engine = None
        for c in self.party():
            for cid in ("raging", "dodging", "reckless", "hidden", "helped", "blessed", "shield_spell",
                        "spiritual_weapon", "spirit_guardians", "marked", "frightened", "prone"):
                c.remove_condition(cid)
            c.concentration = None
            if c.rank != c.class_def.default_rank:
                c.rank = c.class_def.default_rank  # type: ignore[assignment]
        await self.broadcast_state()
        await self._narrate(actions_block="", outcomes=outcomes, notes=[],
                            instruction="The fight is over. Narrate the aftermath (80-150 words, Turkish): the "
                                        "silence after battle, wounds, what lies around, and an open situation.",
                            kind="combat_end")
        for c in self.party():
            if c.can_level_up():
                p = self.player_of_char(c.id)
                await self.toast(f"⭐ {c.name} seviye atlayabilir!", "level", [p.id] if p else None)
        self.save()

    # ═══════════════════════════════════════════════════════════
    # Character management outside combat
    # ═══════════════════════════════════════════════════════════

    async def inventory_command(self, player_id: str, cmd: dict) -> str:
        ch = self.char_of_player(player_id)
        if ch is None:
            raise InventoryError("Karakterin yok.")
        if self.mode == "combat" and cmd.get("type") not in ("unequip",):
            raise InventoryError("Savaşta envanter düzenlemesi kendi sıranda eşya kullanarak yapılır.")
        kind = cmd.get("type")
        ws = self.world
        msg = ""
        if kind == "equip":
            msg = ch.inventory.equip(cmd["uid"], strength=ch.score("strength"))
        elif kind == "unequip":
            ch.inventory.unequip_uid(cmd["uid"])
            msg = "Çıkarıldı."
        elif kind == "use":
            st = ch.inventory.get(cmd["uid"])
            d = st.definition
            if not d or d.type != "consumable":
                raise InventoryError("Bu eşya kullanılamaz.")
            if d.effect == "heal":
                ch.inventory.remove(st.uid, 1)
                got = ch.heal(roll(str(d.amount)).total)
                msg = f"{d.name} içildi: +{got} can."
            elif d.effect == "cure_poison":
                ch.inventory.remove(st.uid, 1)
                ch.remove_condition("poisoned")
                msg = "Zehir temizlendi."
            else:
                raise InventoryError("Bu eşya şimdi kullanılamaz.")
        elif kind == "give":
            to = self.characters.get(cmd["to"])
            if to is None or to.id == ch.id:
                raise InventoryError("Geçersiz alıcı.")
            st = ch.inventory.get(cmd["uid"])
            qty = int(cmd.get("qty") or st.qty)
            moved = ch.inventory.remove(st.uid, qty)
            to.inventory.add_stack(moved)
            msg = f"{moved.display_name()} → {to.name}"
            await self.toast(f"🤝 {ch.name} → {to.name}: {moved.display_name()}", "item")
        elif kind == "give_coins":
            to = self.characters.get(cmd["to"])
            gp = float(cmd.get("gp", 0))
            if to is None or gp <= 0:
                raise InventoryError("Geçersiz.")
            ch.inventory.add_coins(gp=-gp)
            to.inventory.add_coins(gp=gp)
            msg = f"{gp:g} altın → {to.name}"
        elif kind == "drop":
            if ws is None:
                raise InventoryError("Oyun başlamadı.")
            st = ch.inventory.get(cmd["uid"])
            moved = ch.inventory.remove(st.uid, int(cmd.get("qty") or st.qty))
            ws.drop_item(moved)
            msg = f"{moved.display_name()} yere bırakıldı."
        elif kind == "pickup":
            if ws is None:
                raise InventoryError("Oyun başlamadı.")
            st = ws.take_item(cmd["uid"])
            if st is None:
                raise InventoryError("Bu eşya artık burada değil.")
            ch.inventory.add_stack(st)
            msg = f"{st.display_name()} alındı."
            await self.toast(f"🎒 {ch.name}: {st.display_name()} aldı", "item")
        elif kind == "level_up":
            info = ch.level_up(cmd.get("asi"))
            msg = f"{ch.name} {info['level']}. seviyeye ulaştı! (+{info['hp_gain']} can)"
            await self.toast(f"⭐ {msg}", "level")
        else:
            raise InventoryError("Bilinmeyen komut.")
        await self.broadcast_state()
        self.save()
        return msg

    # ═══════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════

    def snapshot(self) -> dict:
        return {
            "id": self.id, "title": self.title, "created_at": self.created_at, "saved_at": time.time(),
            "mode": "exploration" if self.mode == "combat" else self.mode,
            "settings": self.settings.model_dump(),
            "players": [p.model_dump() for p in self.players.values()],
            "characters": [c.model_dump() for c in self.characters.values()],
            "scenario_id": self.scenario.id if self.scenario else None,
            "world": self.world.model_dump() if self.world else None,
            "history": self.gm.history if self.gm else [],
            "pending_summary": self.gm.pending_summary if self.gm else [],
            "last_narration": self.gm.last_narration if self.gm else "",
            "narration_log": self.narration_log[-60:],
        }

    def save(self) -> Path | None:
        try:
            d = user_dir() / "saves"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{self.id}.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
            return p
        except Exception:
            log.exception("save failed")
            return None

    @classmethod
    def load(cls, llm: LLMClient, session_id: str, *, emit: Emit | None = None) -> "GameSession":
        p = user_dir() / "saves" / f"{session_id}.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        s = cls(llm, emit=emit, session_id=raw["id"])
        s.title = raw.get("title", s.title)
        s.created_at = raw.get("created_at", s.created_at)
        s.settings = Settings.model_validate(raw.get("settings", {}))
        for pd in raw.get("players", []):
            pl = Player.model_validate(pd)
            pl.connected = False
            s.players[pl.id] = pl
        for cd in raw.get("characters", []):
            c = Character.model_validate(cd)
            s.characters[c.id] = c
        if raw.get("scenario_id"):
            s.scenario = load_scenario(scenario_path(raw["scenario_id"]))
            s.scenario.id = raw["scenario_id"]
        if raw.get("world"):
            s.world = WorldState.model_validate(raw["world"])
            s.gm = GameMaster(llm, s.world, s.scenario, party_level=s.party_level())
            s.gm.history = raw.get("history", [])
            s.gm.pending_summary = raw.get("pending_summary", [])
            s.gm.last_narration = raw.get("last_narration", "")
        s.narration_log = raw.get("narration_log", [])
        s.mode = raw.get("mode", "lobby")
        return s


def list_saves() -> list[dict]:
    d = user_dir() / "saves"
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": raw["id"], "title": raw.get("title", ""), "saved_at": raw.get("saved_at"),
                        "players": [pl["name"] for pl in raw.get("players", [])],
                        "characters": [c["name"] for c in raw.get("characters", [])]})
        except Exception:
            continue
    return out


def balance_specs(specs: list[dict], party: list[Character]) -> list[dict]:
    """Trim improvised encounters so they stay below the 5e 'deadly' threshold for this party."""
    deadly_per_level = {1: 100, 2: 200, 3: 400, 4: 500, 5: 1100, 6: 1400, 7: 1700, 8: 2100, 9: 2400, 10: 2800}
    budget = sum(deadly_per_level.get(c.level, 2800) for c in party) or 100
    specs = [dict(s) for s in specs if s.get("monster") in data.monsters()]

    def cost(ss: list[dict]) -> float:
        n = sum(s.get("count", 1) for s in ss)
        mult = 1 if n == 1 else 1.5 if n == 2 else 2 if n <= 6 else 2.5
        return sum(data.monster(s["monster"]).xp * s.get("count", 1) for s in ss) * mult

    while specs and cost(specs) > budget:
        biggest = max(specs, key=lambda s: data.monster(s["monster"]).xp * s.get("count", 1))
        if biggest.get("count", 1) > 1:
            biggest["count"] -= 1
        elif len(specs) > 1:
            specs.remove(biggest)
        else:
            break
    return specs


def _dice_count(notation: str) -> int:
    try:
        return int(notation.split("d")[0] or 1)
    except ValueError:
        return 1


def _log_task_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        log.error("background task failed", exc_info=exc)


_GENERIC_PLACE = {"içeri", "içerisi", "dışarı", "orası", "burası", "şurası", "kapı", "köy", "yol", "orman", "ev",
                  "oda", "yer", "meydan", "kasaba", "şehir", "kale", "mağara", "dağ", "ileri", "geri", "aşağı",
                  "yukarı", "ötesi", "arka", "ön"}


def _is_proper_place(name: str) -> bool:
    """Reject generic words the extractor sometimes reports as places ('İçerisi', 'Muhafızın koruduğu yer')."""
    n = (name or "").strip()
    if len(n) < 3 or len(n) > 40 or not n[0].isupper():
        return False
    words = [fold(w).strip("'’.,") for w in re.split(r"\s+", n) if w]
    if len(words) > 4:
        return False
    generic = {fold(g) for g in _GENERIC_PLACE}
    return not all(w in generic for w in words) and "yer" not in words[-1:]
