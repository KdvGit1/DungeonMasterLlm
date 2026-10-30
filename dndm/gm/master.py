"""
The AI Game Master: turns world state + player intent into rulings and prose.

Every call has a deterministic fallback so the table never stalls and an LLM
error message never leaks into the story (old bug #5).
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from dndm.game.character import Character
from dndm.gm import prompts
from dndm.gm.turkish import fix_common_tics, fix_name_suffixes, trim_to_sentence
from dndm.llm.client import LLMClient, LLMError
from dndm.llm.schemas import (ExploreAdjudication, ExploreRuling, ImprovisedRuling, StoryExtraction)
from dndm.rules import data
from dndm.world.scenario import Scenario
from dndm.world.state import WorldState

log = logging.getLogger("dndm.gm")

HISTORY_TURNS = 4          # verbatim exchanges kept in the narration prompt
SUMMARIZE_EVERY = 8        # fold older history into the summary every N exchanges

ATTACK_WORDS = re.compile(r"\b(saldır|vur|öldür|kes|bıçakla|ok at|ateş et|attack|kill|stab|shoot|hücum)", re.I)


class GameMaster:
    def __init__(self, llm: LLMClient, world: WorldState, scenario: Scenario | None, *,
                 party_level: int = 1):
        self.llm = llm
        self.world = world
        self.scenario = scenario
        self.party_level = party_level
        self.history: list[dict] = []        # [{"role": "user"|"assistant", "content": str}]
        self.pending_summary: list[dict] = []
        self.last_narration = ""

    # ═══════════════════════════════════════════════════════════
    # Context blocks
    # ═══════════════════════════════════════════════════════════

    def narrator_system(self, n_players: int) -> str:
        sc = self.scenario
        return prompts.NARRATOR_SYSTEM.format(
            n_players=n_players,
            tone=(f"Scenario tone: {sc.tone}." if sc else ""),
            premise=(self.world.premise or "Free adventure; invent a coherent world as you go.").strip(),
            style_notes=(f"\nSTYLE NOTES\n{sc.style_notes}" if sc and sc.style_notes else ""),
        )

    def scene_block(self, *, gm_only: bool = True) -> str:
        sc, ws = self.scenario, self.world
        here = ws.loc(sc)
        lines = [f"LOCATION: {here.name} — {ws.time_label()}{' (night)' if ws.is_night else ''}",
                 f"DESCRIPTION: {here.description.strip()}"]
        if gm_only and here.gm_notes:
            lines.append(f"GM NOTES (secret): {here.gm_notes.strip()}")
        exits = ws.exits(sc)
        if exits:
            lines.append("PATHS FROM HERE: " + ", ".join(f"{l.name}" for l in exits))
        npcs = ws.npcs_here()
        if npcs:
            lines.append("NPCs PRESENT:")
            for n in npcs:
                s = f"- {n.name} ({n.role}; attitude: {n.attitude})"
                if n.appearance:
                    s += f" looks: {n.appearance}"
                if n.personality:
                    s += f"; personality: {n.personality}"
                if n.voice:
                    s += f"; voice: {n.voice}"
                if gm_only and n.wants:
                    s += f"; wants: {n.wants}"
                if gm_only and n.secret:
                    s += f"; SECRET: {n.secret}"
                lines.append(s)
        items = ws.items_here()
        if items:
            lines.append("NOTABLE OBJECTS HERE: " + ", ".join(i.display_name() for i in items[:10]))
        hooks = [d.hint for d in ws.available_discoveries(sc) if d.hint]
        if hooks:
            lines.append("HOOKS HERE (make these noticeable in your descriptions; never reveal what they mean): "
                         + " | ".join(hooks[:6]))
        return "\n".join(lines)

    def party_block(self, party: list[Character]) -> str:
        return "PARTY:\n" + "\n".join(f"- {c.summary_for_llm()}" for c in party)

    def threats_block(self) -> str:
        sc, ws = self.scenario, self.world
        if not sc or not sc.fronts:
            return ""
        lines = ["THREATS IN MOTION (GM-only; show their effects, never explain them):"]
        for fid, f in sc.fronts.items():
            prog = ws.clocks.get(fid, 0)
            lines.append(f"- {f.name}: {prog:.1f}/{f.clock} — {f.description}")
        return "\n".join(lines)

    def memory_block(self) -> str:
        parts = []
        if self.world.summary:
            parts.append(f"STORY SO FAR: {self.world.summary}")
        recent_facts = [j.text for j in self.world.journal[-6:]]
        if recent_facts:
            parts.append("RECENT FACTS: " + " | ".join(recent_facts))
        return "\n".join(parts)

    def _known_places(self) -> str:
        sc, ws = self.scenario, self.world
        out = []
        exits = {l.id for l in ws.exits(sc)}
        for l in ws.known_locations(sc):
            if l.id == ws.location:
                continue
            out.append(f"{l.id}: {l.name}{' (adjacent)' if l.id in exits else ''}")
        return "; ".join(out) or "none"

    def _secrets_here(self) -> str:
        ds = self.world.available_discoveries(self.scenario)
        if not ds:
            return "none"
        out = []
        for d in ds:
            chk = f" [check {d.check.skill} DC {d.check.dc}]" if d.check else ""
            out.append(f"{d.id}: {d.hint or d.reveals[:80]}{chk}")
        return "; ".join(out)

    def _fights_here(self) -> str:
        try:
            here = self.world.loc(self.scenario)
        except KeyError:
            return "none"
        fights = [e for e in here.encounters if not (e.once and e.id in self.world.used_encounters)]
        return "; ".join(f"{e.id}: {e.when}" for e in fights) or "none"

    # ═══════════════════════════════════════════════════════════
    # Adjudication
    # ═══════════════════════════════════════════════════════════

    async def adjudicate(self, actions: dict[str, str], party: list[Character]) -> ExploreAdjudication:
        """actions: character name -> declared action (Turkish)."""
        monsters = ", ".join(sorted(data.monsters()))
        system = prompts.ADJUDICATOR_SYSTEM.format(monsters=monsters, level=self.party_level,
                                                   n_players=len(party))
        user = "\n".join([
            self.scene_block(),
            self.party_block(party),
            f"KNOWN PLACES: {self._known_places()}",
            f"SECRETS HERE: {self._secrets_here()}",
            f"POSSIBLE FIGHTS HERE: {self._fights_here()}",
            f"LAST NARRATION: {self.last_narration[-600:] or '(start of the adventure)'}",
            "",
            "PLAYER ACTIONS:",
            *[f"{name}: {text}" for name, text in actions.items()],
        ])
        try:
            adj, _ = await self.llm.structured([{"role": "user", "content": user}], ExploreAdjudication,
                                               system=system, temperature=0.15, max_tokens=900)
        except Exception as exc:  # LLM down, bad JSON, anything: the table must never stall
            log.warning("adjudication failed, using fallback: %s", exc)
            return self._fallback_adjudication(actions)
        return self._sanitize_adjudication(adj, actions, party)

    def _fallback_adjudication(self, actions: dict[str, str]) -> ExploreAdjudication:
        rulings = []
        fight = False
        for name, text in actions.items():
            attack = bool(ATTACK_WORDS.search(text))
            fight = fight or attack
            rulings.append(ExploreRuling(player=name, intent="attack" if attack else "other", needs_check=False))
        return ExploreAdjudication(rulings=rulings, starts_combat=fight)

    def _sanitize_adjudication(self, adj: ExploreAdjudication, actions: dict[str, str],
                               party: list[Character]) -> ExploreAdjudication:
        names = {c.name for c in party}
        fixed: list[ExploreRuling] = []
        seen = set()
        for r in adj.rulings:
            name = r.player if r.player in names else next(
                (n for n in names if n.split()[0].lower() in r.player.lower() or r.player.lower() in n.lower()), None)
            if name is None or name in seen or name not in actions:
                continue
            r.player = name
            if r.needs_check and r.check is None:
                r.needs_check = False
            if not r.needs_check:
                r.check = None
            seen.add(name)
            fixed.append(r)
        for name in actions:
            if name not in seen:
                fixed.append(ExploreRuling(player=name, intent="other", needs_check=False))
        adj.rulings = fixed
        valid_monsters = data.monsters()
        adj.enemies = [e for e in adj.enemies if e.kind in valid_monsters][:5]
        if adj.starts_combat and not adj.enemies and not adj.encounter_id:
            adj.starts_combat = False
        return adj

    # ═══════════════════════════════════════════════════════════
    # Narration
    # ═══════════════════════════════════════════════════════════

    def _narration_messages(self, party: list[Character], actions_block: str, outcomes: list[str],
                            notes: list[str], instruction: str) -> list[dict]:
        ctx = "\n".join(filter(None, [
            self.scene_block(),
            self.party_block(party),
            self.threats_block(),
            self.memory_block(),
        ]))
        turn = "\n".join(filter(None, [
            f"CONTEXT (GM-only):\n{ctx}",
            f"\nPLAYER ACTIONS:\n{actions_block}" if actions_block else "",
            "\nRESOLVED OUTCOMES (narrate faithfully):\n" + "\n".join(f"- {o}" for o in outcomes) if outcomes else "",
            "\nWORLD EVENTS TO WEAVE IN:\n" + "\n".join(f"- {n}" for n in notes) if notes else "",
            f"\n{instruction}",
        ]))
        msgs = []
        recent = self.history[-2 * HISTORY_TURNS:]
        for i, m in enumerate(recent):
            # keep the latest exchange whole, shorten older ones (prompt size = latency)
            limit = 1600 if i >= len(recent) - 2 else 700
            msgs.append({"role": m["role"], "content": m["content"][:limit]})
        msgs.append({"role": "user", "content": turn})
        return msgs

    async def narrate(self, party: list[Character], *, actions_block: str = "", outcomes: list[str] | None = None,
                      notes: list[str] | None = None, instruction: str = "Narrate now, in Turkish.",
                      max_tokens: int = 420, record: bool = True) -> AsyncIterator[str]:
        msgs = self._narration_messages(party, actions_block, outcomes or [], notes or [], instruction)
        system = self.narrator_system(len(party))
        collected: list[str] = []
        try:
            async for piece in self.llm.stream(msgs, system=system, temperature=0.75, max_tokens=max_tokens):
                collected.append(piece)
                yield piece
        except LLMError as exc:
            log.error("narration failed: %s", exc)
            if not collected:
                fallback = self._fallback_narration(outcomes or [], notes or [])
                collected.append(fallback)
                yield fallback
        text = self.polish("".join(collected), party)
        if record:
            self.record_exchange(actions_block, outcomes or [], text)
        self.last_narration = text

    def polish(self, raw: str, party: list[Character]) -> str:
        """Clean meta text, drop a cut-off final fragment, fix Turkish suffixes on known names."""
        names = [c.name for c in party] + [n.name for n in self.world.npcs.values()]
        return fix_common_tics(fix_name_suffixes(trim_to_sentence(clean_narration(raw)), names))

    @staticmethod
    def words_for(n_actors: int) -> int:
        return min(240, 70 + 45 * max(1, n_actors))

    def record_exchange(self, actions_block: str, outcomes: list[str], narration: str) -> None:
        user = actions_block or "(scene)"
        if outcomes:
            user += "\nOutcomes: " + " | ".join(outcomes)
        self.history.append({"role": "user", "content": user[:1500]})
        self.history.append({"role": "assistant", "content": narration[:2500]})
        self.pending_summary.extend(self.history[-2:])
        if len(self.history) > 4 * HISTORY_TURNS:
            self.history = self.history[-2 * HISTORY_TURNS:]

    @staticmethod
    def _fallback_narration(outcomes: list[str], notes: list[str]) -> str:
        lines = ["Bir anlığına dünya nefesini tutar; olaylar sessizce akar."]
        lines += outcomes[:6]
        lines += notes[:3]
        lines.append("Sıra yine sizde.")
        return " ".join(lines)

    # ═══════════════════════════════════════════════════════════
    # Extraction
    # ═══════════════════════════════════════════════════════════

    async def extract(self, narration: str, party: list[Character]) -> StoryExtraction:
        known = ", ".join(n.name for n in self.world.npcs.values()) or "none"
        system = prompts.EXTRACTOR_SYSTEM.format(players=", ".join(c.name for c in party), known_npcs=known)
        try:
            ex, _ = await self.llm.structured(
                [{"role": "user", "content": f"NARRATION:\n{narration}"}], StoryExtraction,
                system=system, temperature=0.1, max_tokens=700)
            return ex
        except LLMError as exc:
            log.warning("extraction failed: %s", exc)
            return StoryExtraction()

    # ═══════════════════════════════════════════════════════════
    # Combat helpers
    # ═══════════════════════════════════════════════════════════

    async def improvise(self, actor: Character, text: str, combat_state: dict) -> ImprovisedRuling:
        enemies = "; ".join(f"{e['label']}: {e['name']} ({e['rank']}, {e['wound']})"
                            for e in combat_state["enemies"] if e["state"] == "active")
        feats = "; ".join(f"{f['id']}: {f['name']} ({f['effect']}) — {f.get('description', '')}"
                          for f in combat_state.get("features", [])) or "none"
        allies = ", ".join(p["name"] for p in combat_state["party"] if p["id"] != actor.id)
        user = (f"{self.scene_block(gm_only=False)}\nACTOR: {actor.summary_for_llm()} (rank: {actor.rank})\n"
                f"ENEMIES: {enemies}\nALLIES: {allies}\nBATTLEFIELD FEATURES: {feats}\n\n"
                f"CREATIVE ACTION: {text}")
        try:
            r, _ = await self.llm.structured([{"role": "user", "content": user}], ImprovisedRuling,
                                             system=prompts.IMPROV_SYSTEM, temperature=0.2, max_tokens=400)
            return r
        except LLMError as exc:
            log.warning("improvise failed: %s", exc)
            return ImprovisedRuling(feasible=True, explanation="", check=None, effect="none")

    async def combat_beat(self, party: list[Character], log_lines: list[str], highlights: list[str]) -> AsyncIterator[str]:
        hl = ("Dramatic beats to emphasise: " + "; ".join(highlights)) if highlights else ""
        instruction = prompts.COMBAT_NARRATION_HINT.format(highlights=hl)
        async for piece in self.narrate(party, actions_block="", outcomes=log_lines, notes=[],
                                        instruction=instruction, max_tokens=160, record=False):
            yield piece

    # ═══════════════════════════════════════════════════════════
    # Memory
    # ═══════════════════════════════════════════════════════════

    def needs_summary(self) -> bool:
        return len(self.pending_summary) >= 2 * SUMMARIZE_EVERY

    async def summarize(self) -> None:
        if not self.pending_summary:
            return
        events = "\n".join(f"{'Oyuncular' if m['role'] == 'user' else 'GM'}: {m['content'][:700]}"
                           for m in self.pending_summary)
        user = f"PREVIOUS SUMMARY:\n{self.world.summary or '(none)'}\n\nNEW EVENTS:\n{events}"
        try:
            res = await self.llm.complete([{"role": "user", "content": user}], system=prompts.SUMMARY_SYSTEM,
                                          temperature=0.3, max_tokens=420)
            if res.text.strip():
                self.world.summary = clean_narration(res.text)[:2000]
                self.pending_summary = []
        except LLMError as exc:
            log.warning("summary failed: %s", exc)


_META_RE = re.compile(r"^\s*(\*\*)?(GM|DM|Anlatıcı|Narrator)\s*:\s*(\*\*)?", re.I | re.M)


def clean_narration(text: str) -> str:
    t = text.strip()
    t = _META_RE.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # drop accidental trailing option lists
    t = re.sub(r"\n\s*(?:\d+[.)]|[-*])\s+[^\n]+(?:\n\s*(?:\d+[.)]|[-*])\s+[^\n]+)+\s*$", "", t)
    return t.strip()
