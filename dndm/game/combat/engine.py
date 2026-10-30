"""
Combat engine — deterministic rules resolution.

All randomness goes through ``dndm.rules.dice`` so tests can seed it, and every
player-facing d20 can be pre-rolled by the orchestrator (the player taps "roll",
the server rolls, the table animates) and passed in.

Battlefield model: two ranks per side (front / back).
* Melee can only reach the enemy back rank when their front rank is empty.
* Ranged attacks from the front rank while engaged have disadvantage.
* Leaving the front rank while enemies are there provokes an opportunity attack
  unless the mover disengaged.
"""

from __future__ import annotations

import random
from typing import Iterable

from dndm.game.character import Character, Condition
from dndm.game.combat.conditions import info as cinfo
from dndm.game.combat.conditions import name_tr as cname
from dndm.game.combat.state import Encounter, Enemy, EnvFeature, Event, TurnState
from dndm.rules import data
from dndm.rules.core import combine_advantage, modifier
from dndm.rules.dice import Advantage, DiceRoll, double_dice, roll

PHYSICAL = {"bludgeoning", "piercing", "slashing"}
DAMAGE_TR = {
    "slashing": "kesici", "piercing": "delici", "bludgeoning": "ezici", "fire": "ateş", "cold": "soğuk",
    "lightning": "şimşek", "thunder": "gök gürültüsü", "poison": "zehir", "acid": "asit",
    "necrotic": "nekrotik", "radiant": "ışık", "force": "güç", "psychic": "zihinsel", "none": "",
}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class CombatError(ValueError):
    """Turkish, user-facing reason an action is not allowed."""


class CombatEngine:
    def __init__(self, enc: Encounter, party: dict[str, Character]):
        self.enc = enc
        self.party = party          # char_id -> Character (shared with the session)

    # ═══════════════════════════════════════════════════════════
    # Setup
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def build(enemy_specs: Iterable[dict], party: dict[str, Character], *, title: str = "",
              context: str = "", features: list[EnvFeature] | None = None) -> Encounter:
        """enemy_specs: [{"monster": id, "count": n, "name": optional narrative name}]"""
        enc = Encounter(title=title, context=context, party=list(party), features=features or [])
        idx = 0
        for spec in enemy_specs:
            mid = spec["monster"]
            mdef = data.monster(mid)
            count = max(1, min(int(spec.get("count", 1)), 8))
            base_name = (spec.get("name") or mdef.name).strip()
            hp_factor = float(spec.get("hp_factor", 1.0))
            for n in range(count):
                hp = max(1, round(roll(mdef.hp).total * hp_factor))
                name = base_name if count == 1 else f"{base_name} {n + 1}"
                rank = spec.get("rank") or mdef.behavior.get("rank", "front")
                e = Enemy(monster_id=mid, name=name, label=LETTERS[idx % 26], hp=hp, max_hp=hp, rank=rank)
                if mdef.spellcasting:
                    e.slots = {int(k): v for k, v in (mdef.spellcasting.get("slots") or {}).items()}
                for act in mdef.actions:
                    if act.get("recharge"):
                        e.recharge_ready[act["id"]] = True
                for att in mdef.attacks:
                    if att.recharge:
                        e.recharge_ready[att.id] = True
                enc.enemies.append(e)
                idx += 1
        # at least one enemy in the front rank
        if enc.enemies and not any(e.rank == "front" for e in enc.enemies):
            enc.enemies[0].rank = "front"
        return enc

    def roll_initiative(self, pc_rolls: dict[str, DiceRoll] | None = None) -> list[Event]:
        """Roll initiative; monsters of the same kind share one roll (5e). Bosses act twice."""
        pc_rolls = pc_rolls or {}
        events: list[Event] = []
        entries: list[tuple[int, int, str]] = []
        for cid in self.enc.party:
            ch = self.party[cid]
            if ch.dead:
                continue
            # pre-rolled dice from the player's tap already include the DEX modifier
            r = pc_rolls.get(cid) or roll(f"1d20{_signed(ch.initiative_bonus)}")
            total = r.total
            entries.append((total, ch.mod("dexterity"), f"pc:{cid}"))
            events.append(Event(type="roll", actor=f"pc:{cid}", text=f"{ch.name} inisiyatif: {total}",
                                data={"purpose": "initiative", "roll": r.to_dict(), "total": total}))
        group_rolls: dict[str, int] = {}
        for e in self.enc.enemies:
            dex = modifier(e.mdef.abilities.get("dexterity", 10))
            if e.monster_id not in group_rolls:
                r = roll(f"1d20{_signed(dex)}")
                group_rolls[e.monster_id] = r.total
                events.append(Event(type="roll", actor=e.ref, text=f"{e.mdef.name} inisiyatif: {r.total}",
                                    data={"purpose": "initiative", "roll": r.to_dict(), "total": r.total,
                                          "group": e.monster_id}))
            e.initiative = group_rolls[e.monster_id]
            entries.append((e.initiative, dex, e.ref))
            if "boss" in e.mdef.tags:
                entries.append((e.initiative - 10, dex, e.ref))
        entries.sort(key=lambda t: (t[0], t[1], random.random()), reverse=True)
        self.enc.order = [ref for _, _, ref in entries]
        self.enc.initiatives = {}
        for total, _, ref in entries:
            self.enc.initiatives.setdefault(ref, total)
        self.enc.status = "active"
        self.enc.round = 1
        self.enc.turn_index = 0
        self.enc.turn = self._fresh_turn(self.enc.order[0]) if self.enc.order else TurnState()
        events.append(Event(type="round", text="1. tur başlıyor", data={"round": 1, "order": self.order_public()}))
        self._log(events)
        return events

    # ═══════════════════════════════════════════════════════════
    # Lookups
    # ═══════════════════════════════════════════════════════════

    def name_of(self, ref: str) -> str:
        if ref.startswith("pc:"):
            return self.party[ref[3:]].name
        return self.enc.enemy(ref).name

    def is_pc(self, ref: str) -> bool:
        return ref.startswith("pc:")

    def pc(self, ref_or_id: str) -> Character:
        return self.party[ref_or_id.removeprefix("pc:")]

    def active_pcs(self) -> list[Character]:
        return [self.party[c] for c in self.enc.party
                if c not in self.enc.fled_party and not self.party[c].dead and self.party[c].hp > 0]

    def present_pcs(self) -> list[Character]:
        """PCs still on the battlefield (conscious or dying)."""
        return [self.party[c] for c in self.enc.party if c not in self.enc.fled_party and not self.party[c].dead]

    def front_enemies(self) -> list[Enemy]:
        return [e for e in self.enc.active_enemies() if e.rank == "front"]

    def front_pcs(self) -> list[Character]:
        return [c for c in self.active_pcs() if c.rank == "front"]

    def can_melee_reach_enemy(self, target: Enemy) -> bool:
        return target.rank == "front" or not self.front_enemies()

    def can_melee_reach_pc(self, target: Character) -> bool:
        return target.rank == "front" or not self.front_pcs()

    def order_public(self) -> list[dict]:
        out = []
        seen: dict[str, int] = {}
        for i, ref in enumerate(self.enc.order):
            seen[ref] = seen.get(ref, 0) + 1
            if self.is_pc(ref):
                ch = self.pc(ref)
                state = "dead" if ch.dead else ("fled" if ch.id in self.enc.fled_party else
                                                 ("down" if ch.hp <= 0 else "active"))
                out.append({"ref": ref, "name": ch.name, "side": "party", "state": state, "portrait": ch.portrait,
                            "init": self.enc.initiatives.get(ref), "current": i == self.enc.turn_index})
            else:
                e = self.enc.enemy(ref)
                out.append({"ref": ref, "name": e.name + (" (2. hamle)" if seen[ref] > 1 else ""),
                            "side": "enemy", "state": e.state, "label": e.label,
                            "init": self.enc.initiatives.get(ref), "current": i == self.enc.turn_index})
        return out

    # ═══════════════════════════════════════════════════════════
    # Turn flow
    # ═══════════════════════════════════════════════════════════

    def _fresh_turn(self, ref: str) -> TurnState:
        attacks = 1
        if self.is_pc(ref):
            ch = self.pc(ref)
            if ch.has("extra_attack"):
                attacks = 2
        return TurnState(ref=ref, attacks_left=attacks)

    def current(self) -> str | None:
        return self.enc.current_ref()

    def start_turn(self) -> list[Event]:
        """Start-of-turn upkeep for the current actor. Returns events (may include auto effects)."""
        ref = self.current()
        if ref is None:
            return []
        self.enc.turn = self._fresh_turn(ref)
        events = [Event(type="turn", actor=ref, text=f"Sıra: {self.name_of(ref)}",
                        data={"round": self.enc.round, "order": self.order_public()})]
        if self.is_pc(ref):
            ch = self.pc(ref)
            ch.remove_condition("dodging")
            ch.remove_condition("reckless")
            if ch.has_condition("heroism"):
                gain = max(1, ch.mod(ch.spell_ability or "charisma"))
                ch.temp_hp = max(ch.temp_hp, gain)
            # spirit guardians aura on enemies in the front rank
            sg = next((c for c in ch.conditions if c.id == "spirit_guardians"), None)
            if sg:
                events += self._aura_damage(ch, sg)
        else:
            e = self.enc.enemy(ref)
            e.reaction_used = False
            e.remove_condition("dodging")
            for aid, ready in list(e.recharge_ready.items()):
                if not ready:
                    need = next((a.get("recharge") for a in e.mdef.actions if a["id"] == aid), None) or \
                        next((a.recharge for a in e.mdef.attacks if a.id == aid), 6)
                    r = roll("1d6")
                    if r.total >= need:
                        e.recharge_ready[aid] = True
                        events.append(Event(type="info", actor=ref, text=f"{e.name} yeniden güç topladı!",
                                            data={"recharge": aid}))
            if "regeneration_10_fire_acid" in e.mdef.traits:
                if e.took_fire_or_acid:
                    if e.state == "down":
                        e.state = "dead"
                        events.append(Event(type="dead", target=ref, text=f"{e.name} alevler içinde kül oldu!"))
                elif e.state in ("active", "down"):
                    healed = min(10, e.max_hp - e.hp)
                    if healed > 0:
                        e.hp += healed
                        was_down = e.state == "down"
                        e.state = "active"
                        txt = (f"{e.name} yaraları kapanarak yeniden ayağa kalkıyor!" if was_down
                               else f"{e.name} yenileniyor (+{healed} HP)")
                        events.append(Event(type="heal", target=ref, text=txt, data={"amount": healed}))
                        if was_down:
                            self.enc.highlights.append(f"{e.name} regenerated and rose again — only fire or acid can finish it")
                e.took_fire_or_acid = False
        self._log(events)
        return events

    def end_turn(self) -> list[Event]:
        """End-of-turn saves and duration ticks, then advance to the next living actor."""
        events: list[Event] = []
        ref = self.current()
        if ref is not None:
            events += self._tick_conditions(ref)
        events += self._check_end()
        if self.enc.status != "active":
            self._log(events)
            return events
        # advance
        n = len(self.enc.order)
        for _ in range(n + 1):
            self.enc.turn_index += 1
            if self.enc.turn_index >= n:
                self.enc.turn_index = 0
                self.enc.round += 1
                self.enc.enemy_focus = None
                events.append(Event(type="round", text=f"{self.enc.round}. tur",
                                    data={"round": self.enc.round}))
                events += self._round_effects()
            nxt = self.current()
            if nxt and self._can_take_turn(nxt):
                break
        self._log(events)
        return events

    def _can_take_turn(self, ref: str) -> bool:
        if self.is_pc(ref):
            ch = self.pc(ref)
            return not ch.dead and ch.id not in self.enc.fled_party and not (ch.hp <= 0 and ch.stable)
        e = self.enc.enemy(ref)
        if e.state == "down" and "regeneration_10_fire_acid" in e.mdef.traits:
            return True
        return e.state == "active"

    def _round_effects(self) -> list[Event]:
        events: list[Event] = []
        for f in self.enc.features:
            if f.effect == "hazard" and f.uses < 0:  # persistent spreading hazards (fire)
                pass
        return events

    def _tick_conditions(self, ref: str) -> list[Event]:
        events: list[Event] = []
        holder = self.pc(ref) if self.is_pc(ref) else self.enc.enemy(ref)
        keep = []
        for c in holder.conditions:
            ended = False
            if c.save and c.dc:
                bonus = self._save_bonus(ref, c.save)
                r = roll(f"1d20{_signed(bonus)}")
                if r.total >= c.dc:
                    ended = True
                    events.append(Event(type="condition_end", target=ref,
                                        text=f"{self.name_of(ref)} {cname(c.id)} etkisinden kurtuldu "
                                             f"({r.total} vs ZS {c.dc})",
                                        data={"condition": c.id, "roll": r.to_dict()}))
            if not ended and c.rounds is not None:
                c.rounds -= 1
                if c.rounds <= 0:
                    ended = True
                    if c.id not in ("hidden", "helped", "mocked", "illuminated", "no_reactions"):
                        events.append(Event(type="condition_end", target=ref,
                                            text=f"{self.name_of(ref)}: {cname(c.id)} sona erdi",
                                            data={"condition": c.id}))
            if ended:
                if c.id in ("hold_person_target",):
                    pass
            else:
                keep.append(c)
        holder.conditions = keep
        if isinstance(holder, Character) and holder.concentration and \
                not any(c.data.get("concentration_of") == holder.id for c in self._all_conditions()):
            if holder.concentration not in [c.id for c in holder.conditions]:
                pass
        return events

    def _all_conditions(self):
        for c in self.enc.party:
            yield from self.party[c].conditions
        for e in self.enc.enemies:
            yield from e.conditions

    # ═══════════════════════════════════════════════════════════
    # Attack math
    # ═══════════════════════════════════════════════════════════

    def attack_advantage(self, attacker: str, target: str, *, ranged: bool) -> tuple[Advantage, list[str]]:
        sources: list[Advantage] = []
        reasons: list[str] = []
        a_conds = self._conds(attacker)
        t_conds = self._conds(target)
        for c in a_conds:
            ci = cinfo(c)
            if ci.attacker_dis:
                sources.append("disadvantage")
                reasons.append(f"{ci.name} (saldıran)")
            if ci.attacks_adv:
                sources.append("advantage")
                reasons.append(ci.name)
        for c in t_conds:
            ci = cinfo(c)
            if ci.attacks_have_adv:
                sources.append("advantage")
                reasons.append(f"hedef {ci.name.lower()}")
            if ci.melee_against_adv and not ranged:
                sources.append("advantage")
                reasons.append("hedef yerde")
            if ci.ranged_against_dis and ranged:
                sources.append("disadvantage")
                reasons.append("hedef yerde (uzak)")
            if c == "dodging":
                sources.append("disadvantage")
                reasons.append("hedef savunmada")
            if c == "invisible":
                sources.append("disadvantage")
                reasons.append("hedef görünmez")
        if ranged and self._engaged_in_melee(attacker):
            sources.append("disadvantage")
            reasons.append("yakın dövüşte menzilli saldırı")
        if not self.is_pc(attacker):
            e = self.enc.enemy(attacker)
            if "pack_tactics" in e.mdef.traits and sum(1 for x in self.front_enemies() if x.uid != e.uid) >= 1:
                sources.append("advantage")
                reasons.append("sürü taktiği")
            if "sunlight_sensitivity" in e.mdef.traits and self.enc.sunlight:
                sources.append("disadvantage")
                reasons.append("güneş ışığı")
        return combine_advantage(*sources) if sources else "none", reasons

    def _engaged_in_melee(self, ref: str) -> bool:
        if self.is_pc(ref):
            return self.pc(ref).rank == "front" and bool(self.front_enemies())
        e = self.enc.enemy(ref)
        return e.rank == "front" and bool(self.front_pcs())

    def _conds(self, ref: str) -> list[str]:
        if self.is_pc(ref):
            return [c.id for c in self.pc(ref).conditions]
        return [c.id for c in self.enc.enemy(ref).conditions]

    def _save_bonus(self, ref: str, ability: str) -> int:
        if self.is_pc(ref):
            return self.pc(ref).save_bonus(ability)
        e = self.enc.enemy(ref)
        return modifier(e.mdef.abilities.get(ability, 10))

    def _ac(self, ref: str) -> int:
        if self.is_pc(ref):
            return self.pc(ref).armor_class()
        return self.enc.enemy(ref).armor_class()

    def saving_throw(self, ref: str, ability: str, dc: int, *, advantage: Advantage = "none") -> tuple[bool, DiceRoll]:
        bonus = self._save_bonus(ref, ability)
        conds = self._conds(ref)
        if ability == "dexterity" and any(cinfo(c).dex_save_fail for c in conds):
            r = roll(f"1d20{_signed(bonus)}")
            return False, r
        if "blessed" in conds:
            bonus += roll("1d4").total
        if not self.is_pc(ref) and "magic_resistance" in self.enc.enemy(ref).mdef.traits:
            advantage = combine_advantage(advantage, "advantage")
        if self.is_pc(ref) and ability == "dexterity" and self.pc(ref).has("danger_sense"):
            advantage = combine_advantage(advantage, "advantage")
        if self.is_pc(ref) and ability == "constitution" and self.pc(ref).has("dwarven_resilience"):
            pass
        r = roll(f"1d20{_signed(bonus)}", advantage=advantage)
        return r.total >= dc, r

    # ═══════════════════════════════════════════════════════════
    # Damage & healing
    # ═══════════════════════════════════════════════════════════

    def damage(self, target: str, amount: int, dtype: str, *, critical: bool = False, magical: bool = False,
               silvered: bool = False, source: str = "") -> list[Event]:
        events: list[Event] = []
        if amount <= 0:
            return events
        tname = self.name_of(target)
        if self.is_pc(target):
            ch = self.pc(target)
            if ch.has_condition("uncanny_dodge_ready"):
                pass
            res = ch.take_damage(amount, damage_type=dtype, critical=critical)
            txt = f"{tname} {res['taken']} {DAMAGE_TR.get(dtype, dtype)} hasar aldı"
            if res.get("resisted"):
                txt += " (direnç)"
            events.append(Event(type="damage", target=target, text=txt,
                                data={"amount": res["taken"], "type": dtype, "hp": ch.hp, "max_hp": ch.effective_max_hp,
                                      "critical": critical}))
            if res.get("relentless"):
                events.append(Event(type="info", target=target, text=f"{tname} dişlerini sıkıp ayakta kalıyor! (Amansız Dayanıklılık)"))
                self.enc.highlights.append(f"{tname} refused to fall (relentless endurance)")
            if res.get("dropped"):
                events.append(Event(type="down", target=target, text=f"{tname} yere yığıldı! Ölüm zarları başlıyor."))
                self.enc.highlights.append(f"{tname} fell unconscious and is dying")
                self._break_concentration(ch)
            if res.get("died"):
                events.append(Event(type="dead", target=target, text=f"{tname} öldü."))
                self.enc.highlights.append(f"{tname} DIED")
            elif ch.hp > 0 and ch.concentration and res["taken"] > 0:
                ok, r = self.saving_throw(target, "constitution", max(10, res["taken"] // 2))
                if not ok:
                    events += self._break_concentration(ch)
            for c in list(ch.conditions):
                if cinfo(c.id).ends_on_damage:
                    ch.remove_condition(c.id)
                    events.append(Event(type="condition_end", target=target, text=f"{tname} sarsılarak kendine geldi"))
            return events

        e = self.enc.enemy(target)
        m = e.mdef
        mult = 1.0
        note = ""
        if dtype in m.immunities or (dtype in PHYSICAL and not magical and "nonmagical_physical" in m.immunities) \
                or (dtype in PHYSICAL and not silvered and not magical and "nonsilver_physical" in m.immunities):
            mult = 0
            note = " (bağışık!)"
        elif dtype in m.resistances or (dtype in PHYSICAL and not magical and "nonmagical_physical" in m.resistances) \
                or (dtype in PHYSICAL and not silvered and not magical and "nonsilver_physical" in m.resistances):
            mult = 0.5
            note = " (dirençli)"
        if dtype in m.vulnerabilities:
            mult = 2
            note = " (zayıf noktası!)"
        dealt = int(amount * mult)
        if dtype in ("fire", "acid"):
            e.took_fire_or_acid = True
        before = e.hp
        e.hp = max(0, e.hp - dealt)
        events.append(Event(type="damage", target=target, text=f"{tname} {dealt} {DAMAGE_TR.get(dtype, dtype)} hasar aldı{note}",
                            data={"amount": dealt, "type": dtype, "wound": e.wound_label(), "critical": critical,
                                  "hp_fraction": round(e.hp_fraction(), 2)}))
        for c in list(e.conditions):
            if cinfo(c.id).ends_on_damage and dealt > 0:
                e.remove_condition(c.id)
        if before > 0 and e.hp == 0:
            if "undead_fortitude" in m.traits and dtype != "radiant" and not critical:
                ok, r = self.saving_throw(target, "constitution", 5 + dealt)
                if ok:
                    e.hp = 1
                    events.append(Event(type="info", target=target, text=f"{tname} yere düşmeyi reddediyor, sendeleyerek doğruluyor!"))
                    return events
            if "regeneration_10_fire_acid" in m.traits and not e.took_fire_or_acid:
                e.state = "down"
                events.append(Event(type="down", target=target, text=f"{tname} yere yığıldı... ama eti kıpırdıyor."))
                self.enc.highlights.append(f"{tname} fell but its flesh is still knitting together")
            else:
                e.state = "dead"
                events.append(Event(type="dead", target=target, text=f"{tname} öldü!",
                                    data={"overkill": dealt - before, "critical": critical}))
                if critical or dealt - before >= 8:
                    self.enc.highlights.append(f"{source or 'Someone'} slew {tname} spectacularly "
                                               f"({'critical hit' if critical else 'massive overkill'})")
                else:
                    self.enc.highlights.append(f"{source or 'Someone'} killed {tname}")
                if "boss" in m.tags or "leader" in m.tags:
                    self.enc.highlights.append(f"The enemy leader {tname} has fallen — morale breaks")
        elif e.hp > 0 and e.hp_fraction() <= 0.5 < before / e.max_hp and "boss" in m.tags:
            self.enc.highlights.append(f"{tname} is badly wounded and becomes desperate and furious")
            e.notes["enraged"] = True
        return events

    def heal(self, target: str, amount: int, source: str = "") -> list[Event]:
        if not self.is_pc(target):
            e = self.enc.enemy(target)
            got = min(amount, e.max_hp - e.hp)
            e.hp += got
            return [Event(type="heal", target=target, text=f"{e.name} {got} can kazandı", data={"amount": got})]
        ch = self.pc(target)
        was_down = ch.hp <= 0
        got = ch.heal(amount)
        events = [Event(type="heal", target=target, text=f"{ch.name} {got} can kazandı ({ch.hp}/{ch.effective_max_hp})",
                        data={"amount": got, "hp": ch.hp, "max_hp": ch.effective_max_hp})]
        if was_down and ch.hp > 0:
            events.append(Event(type="revive", target=target, text=f"{ch.name} gözlerini açıyor!"))
            self.enc.highlights.append(f"{ch.name} was brought back from the brink by {source}")
        return events

    def _break_concentration(self, holder) -> list[Event]:
        spell_id = holder.concentration
        if not spell_id:
            return []
        holder.concentration = None
        owner = holder.id if isinstance(holder, Character) else holder.uid
        for c in self.enc.party:
            ch = self.party[c]
            ch.conditions = [x for x in ch.conditions if x.data.get("conc_owner") != owner]
        for e in self.enc.enemies:
            e.conditions = [x for x in e.conditions if x.data.get("conc_owner") != owner]
        if isinstance(holder, Character):
            holder.conditions = [x for x in holder.conditions if x.data.get("conc_owner") != owner]
        sp = data.spells().get(spell_id)
        return [Event(type="info", text=f"{holder.name} konsantrasyonunu kaybetti — {sp.name if sp else spell_id} bozuldu")]

    def _aura_damage(self, ch: Character, cond: Condition) -> list[Event]:
        aura = cond.data.get("aura") or {}
        events: list[Event] = []
        for e in self.front_enemies():
            dmg = roll(aura.get("damage", "3d8")).total
            ok, r = self.saving_throw(e.ref, aura.get("save", "wisdom"), ch.spell_dc)
            amount = dmg // 2 if ok else dmg
            events.append(Event(type="info", actor=f"pc:{ch.id}", target=e.ref,
                                text=f"Ruh muhafızları {e.name} üzerine iniyor", data={"save": r.to_dict(), "saved": ok}))
            events += self.damage(e.ref, amount, aura.get("damage_type", "radiant"), magical=True, source=ch.name)
        return events

    # ═══════════════════════════════════════════════════════════
    # PC actions
    # ═══════════════════════════════════════════════════════════

    def _require_turn(self, char_id: str, cost: str = "action") -> Character:
        ref = f"pc:{char_id}"
        if self.enc.status != "active":
            raise CombatError("Savaş aktif değil.")
        if self.current() != ref:
            raise CombatError("Sıra sende değil.")
        ch = self.party[char_id]
        if ch.hp <= 0:
            raise CombatError("Bilincin yerinde değil — ölüm zarı atman gerekiyor.")
        if not ch.can_act:
            raise CombatError("Bu tur hareket edemiyorsun.")
        t = self.enc.turn
        if cost == "action" and t.action <= 0:
            raise CombatError("Bu turki eylemini zaten kullandın.")
        if cost == "bonus" and t.bonus <= 0:
            raise CombatError("Bu turki bonus eylemini zaten kullandın.")
        return ch

    def attack_roll_spec(self, char_id: str, target_uid: str, weapon_uid: str | None = None) -> dict:
        """What d20 the player must roll (shown on the phone before tapping)."""
        ch = self.party[char_id]
        target = self.enc.enemy(target_uid)
        stack = ch.inventory.get(weapon_uid) if weapon_uid else None
        prof = ch.weapon_profile(stack)
        adv, reasons = self.attack_advantage(f"pc:{char_id}", target.ref, ranged=prof["ranged"])
        bonus = prof["to_hit"] + (max(0, ch.mod("charisma")) if ch.has_condition("sacred_weapon") else 0)
        return {"notation": f"1d20{_signed(bonus)}", "advantage": adv, "reasons": reasons, "bonus": bonus,
                "target": target.name, "weapon": prof["name"]}

    def pc_attack(self, char_id: str, target_uid: str, *, weapon_uid: str | None = None,
                  d20: DiceRoll | None = None, smite_level: int | None = None) -> list[Event]:
        ch = self._require_turn(char_id)
        t = self.enc.turn
        if t.attacks_left <= 0:
            raise CombatError("Saldırı hakkın kalmadı.")
        target = self.enc.enemy(target_uid)
        if not target.is_active:
            raise CombatError(f"{target.name} artık savaşmıyor.")
        stack = ch.inventory.get(weapon_uid) if weapon_uid else ch.inventory.weapon()
        prof = ch.weapon_profile(stack)
        if not prof["ranged"] and not self.can_melee_reach_enemy(target) and "reach" not in prof["properties"]:
            raise CombatError(f"{target.name} arka safta; önce ön saftakileri geçmelisin ya da menzilli saldır.")
        if prof.get("ammo"):
            if not ch.inventory.consume(prof["ammo"], 1):
                raise CombatError(f"{data.item(prof['ammo']).name} kalmadı!")
        ref = f"pc:{char_id}"
        adv, reasons = self.attack_advantage(ref, target.ref, ranged=prof["ranged"])
        bonus = prof["to_hit"] + (max(0, ch.mod("charisma")) if ch.has_condition("sacred_weapon") else 0)
        if d20 is None:
            d20 = roll(f"1d20{_signed(bonus)}", advantage=adv)
        nat = d20.natural or 0
        total = nat + bonus
        if ch.has_condition("blessed"):
            b = roll("1d4").total
            total += b
            reasons.append(f"kutsama +{b}")
        crit_range = 19 if ch.has("improved_critical") else 20
        ac = target.armor_class()
        hit = nat != 1 and (nat >= crit_range or total >= ac)
        crit = hit and (nat >= crit_range or (not prof["ranged"] and any(cinfo(c).melee_auto_crit
                                                                         for c in self._conds(target.ref))))
        t.attacks_left -= 1
        if t.attacks_left <= 0:
            t.action -= 1
        # consumed one-shot advantage sources
        for cid in ("hidden", "helped"):
            ch.remove_condition(cid)
        target.remove_condition("illuminated")
        events = [Event(type="attack", actor=ref, target=target.ref,
                        text=(f"{ch.name} → {target.name} ({prof['name']}): {nat}{_signed(total - nat)} = {total} "
                              f"vs ZS {ac} → " + ("KRİTİK!" if crit else "İSABET" if hit else "ISKA")),
                        data={"roll": d20.to_dict(), "total": total, "ac": ac, "hit": hit, "critical": crit,
                              "advantage": adv, "reasons": reasons, "weapon": prof["name"], "natural": nat})]
        if not hit:
            if nat == 1:
                self.enc.highlights.append(f"{ch.name} fumbled badly (natural 1)")
            self._log(events)
            return events
        dice = prof["damage_dice"]
        dmg_notation = double_dice(dice) if crit else dice
        dmg = roll(dmg_notation)
        amount = dmg.total + prof["damage_mod"]
        parts = [f"{prof['name']} {dmg.total}{_signed(prof['damage_mod'])}"]
        rolls = [dmg.to_dict()]
        if ch.has_condition("raging") and not prof["ranged"] and prof["ability"] == "strength":
            amount += 2
            parts.append("öfke +2")
        if crit and ch.has("savage_attacks") and not prof["ranged"]:
            extra = roll(dice)
            amount += extra.total
            rolls.append(extra.to_dict())
            parts.append(f"vahşi saldırı +{extra.total}")
        # sneak attack
        sneak = ch.sneak_attack_dice()
        if sneak and not t.sneak_used and ("finesse" in prof["properties"] or prof["ranged"]) and adv != "disadvantage":
            ally_engaged = any(c.id != ch.id and c.rank == "front" for c in self.active_pcs()) and target.rank == "front"
            if adv == "advantage" or ally_engaged:
                sn = roll(double_dice(sneak) if crit else sneak)
                amount += sn.total
                rolls.append(sn.to_dict())
                parts.append(f"sinsi saldırı +{sn.total}")
                t.sneak_used = True
                self.enc.highlights.append(f"{ch.name} found a weak spot for a sneak attack")
        # hunter's mark
        if target.has_condition("marked") and any(c.data.get("conc_owner") == ch.id for c in target.conditions):
            hm = roll("2d6" if crit else "1d6")
            amount += hm.total
            rolls.append(hm.to_dict())
            parts.append(f"avcının işareti +{hm.total}")
        # colossus slayer
        if ch.has("colossus_slayer") and target.hp < target.max_hp and not t.sneak_used:
            cs = roll("2d8" if crit else "1d8")
            amount += cs.total
            rolls.append(cs.to_dict())
            parts.append(f"dev avcısı +{cs.total}")
        events += self.damage(target.ref, amount, prof["type"], critical=crit, magical=prof["magic"] > 0,
                              silvered=bool(stack and "gümüş" in stack.name.lower()), source=ch.name)
        # flame tongue etc.
        if prof.get("extra_damage"):
            xd = roll(double_dice(prof["extra_damage"]) if crit else prof["extra_damage"])
            events += self.damage(target.ref, xd.total, prof.get("extra_damage_type") or "fire", magical=True, source=ch.name)
        # smites (spell-based next-hit riders and divine smite)
        events += self._apply_next_hit_riders(ch, target, crit)
        if smite_level and ch.has("divine_smite") and target.state in ("active", "down"):
            events += self._divine_smite(ch, target, smite_level, crit)
        dmg_ev = next((ev for ev in events[1:] if ev.type == "damage"), None)
        if dmg_ev is not None:
            dmg_ev.text += f" [{' + '.join(parts)}]"
        events[0].data["damage_rolls"] = rolls
        events[0].data["damage_total"] = amount
        self._log(events)
        return events

    def _apply_next_hit_riders(self, ch: Character, target: Enemy, crit: bool) -> list[Event]:
        events: list[Event] = []
        for c in list(ch.conditions):
            if c.id == "smite_ready":
                rider = c.data.get("next_hit", {})
                xd = roll(double_dice(rider.get("extra_damage", "2d6")) if crit else rider.get("extra_damage", "2d6"))
                events += self.damage(target.ref, xd.total, rider.get("damage_type", "thunder"), magical=True, source=ch.name)
                ok, r = self.saving_throw(target.ref, rider.get("save", "strength"), ch.spell_dc)
                if not ok and target.is_active:
                    target.add_condition(Condition(id=rider.get("condition", "prone"), rounds=1))
                    events.append(Event(type="condition", target=target.ref,
                                        text=f"Gök gürültüsü {target.name} adlı düşmanı yere serdi!"))
                ch.remove_condition("smite_ready")
            if c.id == "ensnaring_ready":
                ok, r = self.saving_throw(target.ref, "strength", ch.spell_dc)
                if not ok and target.is_active:
                    target.add_condition(Condition(id="restrained", rounds=10, save="strength", dc=ch.spell_dc,
                                                   data={"conc_owner": ch.id}))
                    events.append(Event(type="condition", target=target.ref,
                                        text=f"Dikenli sarmaşıklar {target.name} adlı düşmanı sarıyor!"))
                ch.remove_condition("ensnaring_ready")
        return events

    def _divine_smite(self, ch: Character, target: Enemy, level: int, crit: bool) -> list[Event]:
        if ch.spell_slots.get(level, 0) <= 0:
            return [Event(type="info", text=f"{level}. seviye büyü yuvası kalmadı, kutsal darbe yapılamadı")]
        ch.spell_slots[level] -= 1
        dice_n = min(5, 1 + level)
        if any(t in target.mdef.tags for t in ("undead", "fiend")):
            dice_n += 1
        notation = f"{dice_n * (2 if crit else 1)}d8"
        r = roll(notation)
        self.enc.highlights.append(f"{ch.name} unleashed a radiant divine smite")
        return [Event(type="info", actor=f"pc:{ch.id}", text=f"{ch.name} kutsal darbe indiriyor! (+{r.total} ışık)",
                      data={"roll": r.to_dict()})] + self.damage(target.ref, r.total, "radiant", magical=True,
                                                                  critical=crit, source=ch.name)

    # ── movement & tactical actions ─────────────────────────────

    def pc_move(self, char_id: str, rank: str, *, disengage: bool = False) -> list[Event]:
        ch = self._require_turn(char_id, cost="none")
        t = self.enc.turn
        if rank not in ("front", "back"):
            raise CombatError("Geçersiz saf.")
        if ch.rank == rank:
            raise CombatError("Zaten oradasın.")
        if t.moved:
            raise CombatError("Bu tur zaten yer değiştirdin.")
        if ch.has_condition("restrained") or ch.has_condition("grappled"):
            raise CombatError("Kıpırdayamıyorsun!")
        events: list[Event] = []
        ref = f"pc:{char_id}"
        if ch.rank == "front" and rank == "back" and not (disengage or t.disengaged):
            events += self._opportunity_attack_on_pc(ch)
        if ch.hp > 0:
            ch.rank = rank  # type: ignore[assignment]
        t.moved = True
        events.insert(0, Event(type="move", actor=ref, text=f"{ch.name} {'ön safa atıldı' if rank == 'front' else 'arka safa çekildi'}",
                               data={"rank": rank}))
        self._log(events)
        return events

    def _opportunity_attack_on_pc(self, ch: Character) -> list[Event]:
        candidates = [e for e in self.front_enemies() if not e.reaction_used and
                      not any(cinfo(c.id).incapacitated or cinfo(c.id).no_reactions for c in e.conditions)]
        if not candidates:
            return []
        e = random.choice(candidates)
        e.reaction_used = True
        att = next((a for a in e.mdef.attacks if not a.range), e.mdef.attacks[0])
        events = [Event(type="info", actor=e.ref, target=f"pc:{ch.id}", text=f"{e.name} fırsatı kaçırmıyor — fırsat saldırısı!")]
        events += self._monster_attack(e, ch, att)
        return events

    def pc_disengage(self, char_id: str, *, bonus: bool = False) -> list[Event]:
        ch = self._require_turn(char_id, cost="bonus" if bonus else "action")
        if bonus and not ch.has("cunning_action"):
            raise CombatError("Bunu bonus eylemle yapamazsın.")
        self._spend("bonus" if bonus else "action")
        self.enc.turn.disengaged = True
        return self._log([Event(type="action", actor=f"pc:{char_id}", text=f"{ch.name} geri çekilmeye hazırlanıyor (Kopma)")])

    def pc_dodge(self, char_id: str) -> list[Event]:
        ch = self._require_turn(char_id)
        self._spend("action")
        ch.add_condition(Condition(id="dodging", rounds=None))
        return self._log([Event(type="action", actor=f"pc:{char_id}", text=f"{ch.name} tamamen savunmaya geçti")])

    def pc_help(self, char_id: str, ally_id: str) -> list[Event]:
        ch = self._require_turn(char_id)
        if ally_id not in self.party or ally_id == char_id:
            raise CombatError("Geçersiz müttefik.")
        self._spend("action")
        self.party[ally_id].add_condition(Condition(id="helped", rounds=2))
        return self._log([Event(type="action", actor=f"pc:{char_id}", target=f"pc:{ally_id}",
                                text=f"{ch.name}, {self.party[ally_id].name} için bir açıklık yaratıyor")])

    def pc_hide(self, char_id: str, *, bonus: bool = False, d20: DiceRoll | None = None) -> list[Event]:
        ch = self._require_turn(char_id, cost="bonus" if bonus else "action")
        if bonus and not ch.has("cunning_action"):
            raise CombatError("Bunu bonus eylemle yapamazsın.")
        bonus_val = ch.skill_bonus("stealth")
        r = d20 or roll(f"1d20{_signed(bonus_val)}")
        total = (r.natural or 0) + bonus_val
        best_pp = max((10 + modifier(e.mdef.abilities.get("wisdom", 10)) + e.mdef.skills.get("perception", 0)
                       for e in self.enc.active_enemies()), default=10)
        self._spend("bonus" if bonus else "action")
        ok = total >= best_pp
        if ok:
            ch.add_condition(Condition(id="hidden", rounds=2))
        return self._log([Event(type="check", actor=f"pc:{char_id}",
                                text=f"{ch.name} gizlenmeye çalışıyor: {total} vs {best_pp} → {'GİZLENDİ' if ok else 'fark edildi'}",
                                data={"roll": r.to_dict(), "total": total, "dc": best_pp, "success": ok})])

    def pc_flee(self, char_id: str, d20: DiceRoll | None = None) -> list[Event]:
        """Leave the battle entirely. Must start from the back rank."""
        ch = self._require_turn(char_id)
        if ch.rank != "back":
            raise CombatError("Kaçmak için önce arka safa çekilmelisin.")
        n = len(self.enc.active_enemies())
        dc = min(20, 8 + 2 * n)
        key = "athletics" if ch.skill_bonus("athletics") >= ch.skill_bonus("acrobatics") else "acrobatics"
        b = ch.skill_bonus(key)
        r = d20 or roll(f"1d20{_signed(b)}")
        total = (r.natural or 0) + b
        self._spend("action")
        ok = total >= dc
        events = [Event(type="check", actor=f"pc:{char_id}",
                        text=f"{ch.name} kaçmaya çalışıyor: {total} vs ZS {dc} → {'KAÇTI' if ok else 'yolu kesildi'}",
                        data={"roll": r.to_dict(), "total": total, "dc": dc, "success": ok})]
        if ok:
            self.enc.fled_party.append(char_id)
            self.enc.highlights.append(f"{ch.name} escaped the battle")
        events += self._check_end()
        return self._log(events)

    def _spend(self, cost: str) -> None:
        t = self.enc.turn
        if cost == "action":
            t.action -= 1
            t.attacks_left = 0
        elif cost == "bonus":
            t.bonus -= 1

    # ── features ────────────────────────────────────────────────

    def pc_feature(self, char_id: str, feature: str, *, target_id: str | None = None,
                   amount: int | None = None) -> list[Event]:
        ref = f"pc:{char_id}"
        ch = self.party[char_id]
        res = ch.resources
        if feature == "second_wind":
            self._require_turn(char_id, "bonus")
            if res.get("second_wind", 0) <= 0:
                raise CombatError("İkinci Nefes kullanıldı (kısa dinlenmede yenilenir).")
            res["second_wind"] -= 1
            self._spend("bonus")
            r = roll(f"1d10+{ch.level}")
            return self._log([Event(type="feature", actor=ref, text=f"{ch.name} derin bir nefes alıp toparlanıyor (İkinci Nefes)",
                                    data={"roll": r.to_dict()})] + self.heal(ref, r.total, ch.name))
        if feature == "action_surge":
            self._require_turn(char_id, "none")
            if res.get("action_surge", 0) <= 0:
                raise CombatError("Atılım hakkın yok.")
            res["action_surge"] -= 1
            self.enc.turn.action += 1
            self.enc.turn.attacks_left += 2 if ch.has("extra_attack") else 1
            self.enc.highlights.append(f"{ch.name} surged with a burst of speed (action surge)")
            return self._log([Event(type="feature", actor=ref, text=f"{ch.name} ATILIM! Bir eylem daha kazandı")])
        if feature == "rage":
            self._require_turn(char_id, "bonus")
            if ch.has_condition("raging"):
                raise CombatError("Zaten öfkelisin!")
            if res.get("rage", 0) <= 0:
                raise CombatError("Öfke hakkın kalmadı.")
            res["rage"] -= 1
            self._spend("bonus")
            ch.add_condition(Condition(id="raging", rounds=10))
            self.enc.highlights.append(f"{ch.name} flew into a berserk RAGE")
            return self._log([Event(type="feature", actor=ref, text=f"{ch.name} ÖFKEYE kapılıyor! (+2 hasar, fiziksel direnç)")])
        if feature == "reckless_attack":
            self._require_turn(char_id, "none")
            if not ch.has("reckless_attack"):
                raise CombatError("Bu özelliğin yok.")
            ch.add_condition(Condition(id="reckless", rounds=None))
            return self._log([Event(type="feature", actor=ref, text=f"{ch.name} pervasızca saldırıyor (avantaj, ama açık veriyor)")])
        if feature == "lay_on_hands":
            self._require_turn(char_id)
            pool = res.get("lay_on_hands", 0)
            tgt = target_id or char_id
            target = self.party[tgt]
            need = target.effective_max_hp - target.hp
            give = min(pool, amount or need, need if need > 0 else 1)
            if give <= 0:
                raise CombatError("Şifa havuzun boş ya da hedef tam canlı.")
            res["lay_on_hands"] = pool - give
            self._spend("action")
            return self._log([Event(type="feature", actor=ref, target=f"pc:{tgt}",
                                    text=f"{ch.name} ellerini {target.name} üzerine koyuyor (Elle Şifa {give})")]
                             + self.heal(f"pc:{tgt}", give, ch.name))
        if feature == "sacred_weapon":
            self._require_turn(char_id)
            if res.get("sacred_weapon", 0) <= 0:
                raise CombatError("Kutsal Silah hakkın yok.")
            res["sacred_weapon"] -= 1
            self._spend("action")
            ch.add_condition(Condition(id="sacred_weapon", rounds=10))
            return self._log([Event(type="feature", actor=ref, text=f"{ch.name} silahını ilahi ışıkla kutsuyor (+{max(0, ch.mod('charisma'))} isabet)")])
        if feature == "bardic_inspiration":
            self._require_turn(char_id, "bonus")
            if res.get("bardic_inspiration", 0) <= 0:
                raise CombatError("İlham hakkın kalmadı.")
            if not target_id or target_id == char_id or target_id not in self.party:
                raise CombatError("İlham verecek bir müttefik seç.")
            res["bardic_inspiration"] -= 1
            self._spend("bonus")
            self.party[target_id].add_condition(Condition(id="inspired", rounds=100, data={"die": ch.bardic_die()}))
            return self._log([Event(type="feature", actor=ref, target=f"pc:{target_id}",
                                    text=f"{ch.name}, {self.party[target_id].name} için ilham verici bir nağme çalıyor ({ch.bardic_die()})")])
        if feature == "turn_undead":
            self._require_turn(char_id)
            if res.get("channel_divinity", 0) <= 0:
                raise CombatError("İlahi Kanal hakkın yok.")
            res["channel_divinity"] -= 1
            self._spend("action")
            events = [Event(type="feature", actor=ref, text=f"{ch.name} kutsal sembolünü kaldırıp ölümsüzleri kovuyor!")]
            for e in self.enc.active_enemies():
                if "undead" in e.mdef.tags:
                    ok, r = self.saving_throw(e.ref, "wisdom", ch.spell_dc)
                    if not ok:
                        if ch.has("destroy_undead") and e.mdef.cr <= 0.5:
                            e.state = "dead"
                            events.append(Event(type="dead", target=e.ref, text=f"{e.name} kutsal ışıkta toza dönüştü!"))
                        else:
                            e.state = "fled"
                            events.append(Event(type="flee", target=e.ref, text=f"{e.name} dehşet içinde kaçıyor!"))
            events += self._check_end()
            return self._log(events)
        if feature == "preserve_life":
            self._require_turn(char_id)
            if res.get("channel_divinity", 0) <= 0:
                raise CombatError("İlahi Kanal hakkın yok.")
            res["channel_divinity"] -= 1
            self._spend("action")
            budget = 5 * ch.level
            events = [Event(type="feature", actor=ref, text=f"{ch.name} yaşamı koruyor: {budget} can dağıtılıyor")]
            for pc in sorted(self.present_pcs(), key=lambda c: c.hp / c.effective_max_hp):
                cap = pc.effective_max_hp // 2 - pc.hp
                give = min(budget, max(0, cap))
                if give > 0:
                    events += self.heal(f"pc:{pc.id}", give, ch.name)
                    budget -= give
            return self._log(events)
        if feature == "spiritual_weapon_attack":
            self._require_turn(char_id, "bonus")
            sw = next((c for c in ch.conditions if c.id == "spiritual_weapon"), None)
            if not sw:
                raise CombatError("Ruhani silahın yok.")
            tgt = self.enc.enemy(target_id) if target_id else (self.front_enemies() or self.enc.active_enemies())[0]
            self._spend("bonus")
            return self._log(self._spell_attack(ch, tgt, sw.data.get("damage", "1d8"), "force", label="Ruhani silah",
                                                add_mod=True))
        raise CombatError(f"Bilinmeyen özellik: {feature}")

    # ── spells ──────────────────────────────────────────────────

    def pc_cast(self, char_id: str, spell_id: str, *, slot: int | None = None, targets: list[str] | None = None,
                rank: str | None = None) -> list[Event]:
        ch = self.party[char_id]
        if spell_id not in ch.known_spells():
            raise CombatError("Bu büyüyü bilmiyorsun.")
        sp = data.spell(spell_id)
        cost = {"action": "action", "bonus": "bonus", "reaction": "none"}[sp.cast]
        self._require_turn(char_id, cost)
        if sp.level > 0:
            slot = slot or sp.level
            if slot < sp.level:
                raise CombatError("Bu büyü için yuva seviyesi düşük.")
            if ch.spell_slots.get(slot, 0) <= 0:
                raise CombatError(f"{slot}. seviye büyü yuvan kalmadı.")
            ch.spell_slots[slot] -= 1
        else:
            slot = 0
        self._spend(cost)
        if sp.concentration:
            events = self._break_concentration(ch)
            ch.concentration = spell_id
        else:
            events = []
        events.append(Event(type="spell", actor=f"pc:{char_id}", text=f"{ch.name} {sp.name} büyüsünü yapıyor",
                            data={"spell": spell_id, "slot": slot}))
        events += self._resolve_spell(f"pc:{char_id}", sp, slot, targets or [], rank)
        events += self._check_end()
        return self._log(events)

    def _caster_numbers(self, caster_ref: str) -> tuple[int, int, int]:
        """(spell DC, spell attack bonus, casting ability modifier)"""
        if self.is_pc(caster_ref):
            ch = self.pc(caster_ref)
            return ch.spell_dc, ch.spell_attack, ch.mod(ch.spell_ability or "intelligence")
        e = self.enc.enemy(caster_ref)
        sc = e.mdef.spellcasting or {}
        return sc.get("dc", 12), sc.get("attack", 4), modifier(e.mdef.abilities.get(sc.get("ability", "wisdom"), 10))

    def _spell_dice(self, sp, slot: int, caster_ref: str, base: str | None) -> str:
        notation = base or "0"
        level = self.pc(caster_ref).level if self.is_pc(caster_ref) else int(max(1, self.enc.enemy(caster_ref).mdef.cr * 2))
        if sp.level == 0 and sp.scale and level >= 5:
            notation = f"{notation}+{sp.scale}"
        if sp.level > 0 and sp.upcast and slot > sp.level:
            for _ in range(slot - sp.level):
                notation = f"{notation}+{sp.upcast}"
        return notation

    def _resolve_spell(self, caster: str, sp, slot: int, targets: list[str], rank: str | None) -> list[Event]:
        dc, atk, mod = self._caster_numbers(caster)
        caster_is_pc = self.is_pc(caster)
        foes = self.enc.active_enemies() if caster_is_pc else []
        events: list[Event] = []

        def enemy_targets(n: int) -> list[str]:
            chosen = [t for t in targets if t.startswith("en:") or (caster_is_pc and not t.startswith("pc:"))]
            chosen = [t if t.startswith("en:") else f"en:{t}" for t in chosen]
            chosen = [t for t in chosen if self.enc.enemy(t).is_active]
            if not chosen:
                pool = (self.front_enemies() if sp.model_extra.get("front_only") else foes) or foes
                chosen = [e.ref for e in pool]
            return chosen[:n]

        def target_count(spec: str) -> int:
            return int(spec.split(":")[1]) if ":" in spec else 1

        kind = sp.kind
        if kind == "attack":
            rays = int(sp.model_extra.get("rays", 1)) + (int(sp.model_extra.get("upcast_rays", 0)) * max(0, slot - sp.level))
            tlist = enemy_targets(max(1, target_count(sp.target))) if caster_is_pc else self._monster_spell_targets(sp)
            for i in range(rays):
                tref = tlist[i % len(tlist)] if tlist else None
                if tref is None:
                    break
                events += self._spell_attack_ref(caster, tref, self._spell_dice(sp, slot, caster, sp.damage),
                                                 sp.damage_type or "force", sp, atk)
        elif kind == "save" and sp.damage:
            if sp.target == "rank":
                rank = rank or "front"
                tlist = ([e.ref for e in foes if e.rank == rank] if caster_is_pc
                         else [f"pc:{c.id}" for c in self.active_pcs() if c.rank == rank] or
                         [f"pc:{c.id}" for c in self.active_pcs()])
            else:
                tlist = enemy_targets(target_count(sp.target)) if caster_is_pc else self._monster_spell_targets(sp)
            dmg_roll = roll(self._spell_dice(sp, slot, caster, sp.damage))
            events.append(Event(type="roll", actor=caster, text=f"{sp.name} hasarı: {dmg_roll.total}",
                                data={"purpose": "damage", "roll": dmg_roll.to_dict()}))
            for tref in tlist:
                ok, r = self.saving_throw(tref, sp.save or "dexterity", dc)
                amount = (dmg_roll.total // 2 if sp.half else 0) if ok else dmg_roll.total
                events.append(Event(type="save", target=tref,
                                    text=f"{self.name_of(tref)} {'kurtarma zarını geçti' if ok else 'kaçamadı'} ({r.total} vs ZS {dc})",
                                    data={"roll": r.to_dict(), "success": ok}))
                events += self.damage(tref, amount, sp.damage_type or "force", magical=True, source=self.name_of(caster))
                on_fail = sp.model_extra.get("on_fail") or {}
                if not ok and on_fail and self._alive(tref):
                    if on_fail.get("condition"):
                        self._add_cond(tref, Condition(id=on_fail["condition"], rounds=on_fail.get("rounds", 1)))
                        events.append(Event(type="condition", target=tref, text=f"{self.name_of(tref)}: {cname(on_fail['condition'])}"))
                    if on_fail.get("push") and not self.is_pc(tref):
                        self.enc.enemy(tref).rank = "back"
                        events.append(Event(type="move", target=tref, text=f"{self.name_of(tref)} geriye savruldu!"))
        elif kind == "auto":
            missiles = int(sp.model_extra.get("missiles", 1)) + int(sp.model_extra.get("upcast_missiles", 0)) * max(0, slot - sp.level)
            tlist = enemy_targets(missiles) if caster_is_pc else self._monster_spell_targets(sp)
            for i in range(missiles):
                if not tlist:
                    break
                alive = [t for t in tlist if self._alive(t)] or ([e.ref for e in self.enc.active_enemies()] if caster_is_pc else [])
                if not alive:
                    break
                tref = alive[i % len(alive)]
                r = roll(sp.damage or "1d4+1")
                events += self.damage(tref, r.total, sp.damage_type or "force", magical=True, source=self.name_of(caster))
        elif kind == "heal":
            add = mod if sp.model_extra.get("add_mod") else 0
            if caster_is_pc and self.pc(caster).has("disciple_of_life") and sp.level > 0:
                add += 2 + sp.level
            if sp.target == "all_allies":
                tlist = [f"pc:{c.id}" for c in self.present_pcs()][:6] if caster_is_pc else \
                    [e.ref for e in self.enc.active_enemies()][:6]
            else:
                tlist = [t if t.startswith(("pc:", "en:")) else f"pc:{t}" for t in targets][:1] or \
                    ([f"pc:{min(self.present_pcs(), key=lambda c: c.hp / c.effective_max_hp).id}"] if caster_is_pc
                     else [min(self.enc.active_enemies(), key=lambda e: e.hp_fraction()).ref])
            eff = sp.effect or {}
            for tref in tlist:
                if eff.get("stabilize"):
                    if self.is_pc(tref):
                        ch = self.pc(tref)
                        if ch.hp <= 0 and not ch.dead:
                            ch.stable = True
                            events.append(Event(type="heal", target=tref, text=f"{ch.name} istikrara kavuştu"))
                    continue
                if eff.get("revive"):
                    events += self._revivify(caster, tref)
                    continue
                r = roll(self._spell_dice(sp, slot, caster, sp.heal))
                events += self.heal(tref, r.total + add, self.name_of(caster))
        elif kind in ("buff", "debuff", "summon", "utility"):
            events += self._apply_effect_spell(caster, sp, slot, targets, rank, dc)
        return events

    def _monster_spell_targets(self, sp) -> list[str]:
        pcs = self.active_pcs()
        if not pcs:
            return []
        n = int(sp.target.split(":")[1]) if ":" in sp.target else 1
        ordered = sorted(pcs, key=lambda c: (c.hp / c.effective_max_hp, c.armor_class()))
        return [f"pc:{c.id}" for c in ordered[:n]]

    def _alive(self, ref: str) -> bool:
        if self.is_pc(ref):
            ch = self.pc(ref)
            return not ch.dead and ch.hp > 0
        return self.enc.enemy(ref).is_active

    def _add_cond(self, ref: str, cond: Condition) -> None:
        holder = self.pc(ref) if self.is_pc(ref) else self.enc.enemy(ref)
        if not self.is_pc(ref) and cond.id in holder.mdef.condition_immunities:
            return
        holder.add_condition(cond)

    def _spell_attack_ref(self, caster: str, tref: str, notation: str, dtype: str, sp, atk: int) -> list[Event]:
        adv, reasons = self.attack_advantage(caster, tref, ranged=sp.ranged)
        if sp.model_extra.get("advantage_vs_metal") and self.is_pc(tref) and self.pc(tref).inventory.armor():
            adv = combine_advantage(adv, "advantage")
        r = roll(f"1d20{_signed(atk)}", advantage=adv)
        nat = r.natural or 0
        ac = self._ac(tref)
        # Shield spell reaction for wizards
        if self.is_pc(tref):
            ch = self.pc(tref)
            if nat != 20 and r.total >= ac and r.total < ac + 5 and "shield" in ch.known_spells() \
                    and ch.spell_slots.get(1, 0) > 0 and not ch.has_condition("shield_spell"):
                ch.spell_slots[1] -= 1
                ch.add_condition(Condition(id="shield_spell", rounds=1, data={"ac_bonus": 5}))
                ac += 5
        hit = nat != 1 and (nat == 20 or r.total >= ac)
        crit = hit and nat == 20
        events = [Event(type="attack", actor=caster, target=tref,
                        text=f"{sp.name} → {self.name_of(tref)}: {r.total} vs ZS {ac} → {'KRİTİK!' if crit else 'İSABET' if hit else 'ISKA'}",
                        data={"roll": r.to_dict(), "hit": hit, "critical": crit, "spell": sp.id})]
        if hit:
            d = roll(double_dice(notation) if crit else notation)
            events += self.damage(tref, d.total, dtype, critical=crit, magical=True, source=self.name_of(caster))
            on_hit = sp.model_extra.get("on_hit") or {}
            if on_hit.get("condition") and self._alive(tref):
                self._add_cond(tref, Condition(id=on_hit["condition"], rounds=on_hit.get("rounds", 1)))
        return events

    def _spell_attack(self, ch: Character, target: Enemy, notation: str, dtype: str, *, label: str,
                      add_mod: bool = False) -> list[Event]:
        atk = ch.spell_attack
        r = roll(f"1d20{_signed(atk)}")
        nat = r.natural or 0
        hit = nat != 1 and (nat == 20 or r.total >= target.armor_class())
        events = [Event(type="attack", actor=f"pc:{ch.id}", target=target.ref,
                        text=f"{label} → {target.name}: {r.total} → {'İSABET' if hit else 'ISKA'}",
                        data={"roll": r.to_dict(), "hit": hit})]
        if hit:
            d = roll(double_dice(notation) if nat == 20 else notation)
            amount = d.total + (ch.mod(ch.spell_ability or "wisdom") if add_mod else 0)
            events += self.damage(target.ref, amount, dtype, critical=nat == 20, magical=True, source=ch.name)
        return events

    def _apply_effect_spell(self, caster: str, sp, slot: int, targets: list[str], rank: str | None, dc: int) -> list[Event]:
        events: list[Event] = []
        owner = caster[3:]
        eff = sp.effect or {}
        rounds = sp.rounds or 10
        sid = sp.id
        caster_is_pc = self.is_pc(caster)
        if sid in ("bless", "aid", "heroism", "shield_of_faith", "invisibility", "pass_without_trace"):
            n = int(sp.target.split(":")[1]) if ":" in sp.target else (6 if sp.target == "all_allies" else 1)
            tlist = [t if t.startswith("pc:") else f"pc:{t}" for t in targets if t.removeprefix("pc:") in self.party][:n]
            if not tlist:
                tlist = [f"pc:{c.id}" for c in self.active_pcs()][:n]
            cid = {"bless": "blessed", "shield_of_faith": "shield_of_faith", "heroism": "heroism",
                   "invisibility": "invisible", "aid": "aid", "pass_without_trace": "pass_without_trace"}[sid]
            for t in tlist:
                ch = self.pc(t)
                data_ = {"conc_owner": owner} if sp.concentration else {}
                if sid == "shield_of_faith":
                    data_["ac_bonus"] = 2
                if sid == "aid":
                    bonus = 5 * (1 + max(0, slot - 2))
                    ch.max_hp_bonus = max(ch.max_hp_bonus, bonus)
                    ch.heal(bonus)
                ch.add_condition(Condition(id=cid, rounds=rounds, data=data_))
                events.append(Event(type="condition", target=t, text=f"{ch.name}: {cname(cid)}"))
        elif sid == "mage_armor":
            ch = self.pc(caster)
            ch.add_condition(Condition(id="mage_armor", rounds=rounds))
            events.append(Event(type="condition", target=caster, text=f"{ch.name} büyü zırhına büründü"))
        elif sid == "shield":
            ch = self.pc(caster)
            ch.add_condition(Condition(id="shield_spell", rounds=1, data={"ac_bonus": 5}))
        elif sid == "spirit_guardians":
            holder = self.pc(caster) if caster_is_pc else self.enc.enemy(caster)
            aura = dict(eff.get("aura", {}))
            if slot > 3:
                aura["damage"] = f"{3 + slot - 3}d8"
            holder.add_condition(Condition(id="spirit_guardians", rounds=rounds, data={"aura": aura, "conc_owner": owner}))
            events.append(Event(type="condition", target=caster, text="Işıltılı ruhlar etrafında dönmeye başladı"))
        elif sid == "spiritual_weapon":
            ch = self.pc(caster)
            dmg = "1d8" if slot < 4 else f"{1 + (slot - 2) // 2}d8"
            ch.add_condition(Condition(id="spiritual_weapon", rounds=rounds, data={"damage": dmg}))
            foes = self.enc.active_enemies()
            if foes:
                tgt = self.enc.enemy(targets[0]) if targets else foes[0]
                events += self._spell_attack(ch, tgt, dmg, "force", label="Ruhani silah", add_mod=True)
        elif sid in ("hunters_mark",):
            tref = targets[0] if targets else (self.front_enemies() or self.enc.active_enemies())[0].ref
            tref = tref if tref.startswith("en:") else f"en:{tref}"
            self.enc.enemy(tref).add_condition(Condition(id="marked", rounds=rounds, data={"conc_owner": owner}))
            events.append(Event(type="condition", target=tref, text=f"{self.name_of(tref)} avcının işaretini taşıyor"))
        elif sid in ("ensnaring_strike", "thunderous_smite"):
            ch = self.pc(caster)
            cid = "ensnaring_ready" if sid == "ensnaring_strike" else "smite_ready"
            ch.add_condition(Condition(id=cid, rounds=rounds, data={"next_hit": eff.get("next_hit", {}), "conc_owner": owner}))
            events.append(Event(type="condition", target=caster, text=f"{ch.name}: {cname(cid)}"))
        elif sid == "sleep":
            pool = roll(self._spell_dice(sp, slot, caster, sp.model_extra.get("pool", "5d8"))).total
            events.append(Event(type="roll", actor=caster, text=f"Uyku havuzu: {pool} can",
                                data={"purpose": "sleep_pool"}))
            cands = sorted([e for e in self.enc.active_enemies() if "undead" not in e.mdef.tags
                            and "charmed" not in e.mdef.condition_immunities], key=lambda e: e.hp)
            for e in cands:
                if e.hp <= pool:
                    pool -= e.hp
                    e.add_condition(Condition(id="asleep", rounds=10))
                    events.append(Event(type="condition", target=e.ref, text=f"{e.name} derin bir uykuya daldı"))
                else:
                    break
        elif sid in ("hold_person", "charm_person"):
            tref = targets[0] if targets else (self.enc.active_enemies()[0].ref if caster_is_pc else self._monster_spell_targets(sp)[0])
            if caster_is_pc and not tref.startswith("en:"):
                tref = f"en:{tref}"
            if caster_is_pc and "humanoid" not in self.enc.enemy(tref).mdef.tags:
                events.append(Event(type="info", text=f"{sp.name} yalnızca insansılara işler — etkisiz!"))
                return events
            ok, r = self.saving_throw(tref, "wisdom", dc)
            events.append(Event(type="save", target=tref, text=f"{self.name_of(tref)} iradesiyle direniyor: {r.total} vs ZS {dc} → {'direndi' if ok else 'BAŞARISIZ'}",
                                data={"roll": r.to_dict(), "success": ok}))
            if not ok:
                cid = "paralyzed" if sid == "hold_person" else "charmed"
                self._add_cond(tref, Condition(id=cid, rounds=rounds, save="wisdom" if sid == "hold_person" else None,
                                               dc=dc if sid == "hold_person" else None, data={"conc_owner": owner}))
                events.append(Event(type="condition", target=tref, text=f"{self.name_of(tref)}: {cname(cid)}!"))
                if sid == "hold_person":
                    self.enc.highlights.append(f"{self.name_of(tref)} froze in place, paralyzed by magic")
        elif sid in ("faerie_fire", "hypnotic_pattern"):
            rank = rank or "front"
            tlist = [e.ref for e in self.enc.active_enemies() if e.rank == rank] if caster_is_pc else \
                [f"pc:{c.id}" for c in self.active_pcs()]
            save = "dexterity" if sid == "faerie_fire" else "wisdom"
            cid = "outlined" if sid == "faerie_fire" else "charmed_incapacitated"
            for tref in tlist:
                ok, r = self.saving_throw(tref, save, dc)
                if not ok:
                    self._add_cond(tref, Condition(id=cid, rounds=rounds, data={"conc_owner": owner}))
                    events.append(Event(type="condition", target=tref, text=f"{self.name_of(tref)}: {cname(cid)}"))
                else:
                    events.append(Event(type="save", target=tref, text=f"{self.name_of(tref)} etkilenmedi"))
        elif sid == "misty_step":
            if caster_is_pc:
                ch = self.pc(caster)
                ch.rank = "back" if ch.rank == "front" else "front"
                events.append(Event(type="move", actor=caster, text=f"{ch.name} gümüşi bir sisle kaybolup {('arka' if ch.rank == 'back' else 'ön')} safta beliriyor"))
        elif sid == "guidance":
            tid = (targets[0] if targets else caster).removeprefix("pc:")
            self.party[tid].add_condition(Condition(id="guided", rounds=10, data={"check_bonus_die": "1d4"}))
        else:
            events.append(Event(type="info", text=f"{sp.name} savaşta özel bir etki yaratmadı."))
        return events

    def _revivify(self, caster: str, tref: str) -> list[Event]:
        ch = self.pc(tref)
        if not ch.dead:
            return [Event(type="info", text=f"{ch.name} ölü değil.")]
        healer = self.pc(caster)
        gems = sorted([s for s in healer.inventory.items if s.kind == "treasure" and s.value >= 300],
                      key=lambda s: s.value)
        if not gems:
            return [Event(type="info", text="Diriltme için en az 300 altın değerinde bir mücevher gerekiyor!")]
        healer.inventory.remove(gems[0].uid, 1)
        ch.dead = False
        ch.hp = 1
        ch.death_saves.successes = ch.death_saves.failures = 0
        self.enc.highlights.append(f"{ch.name} was RETURNED FROM DEATH by {healer.name}")
        return [Event(type="revive", target=tref, text=f"{ch.name} derin bir nefesle hayata geri dönüyor!")]

    # ── items ───────────────────────────────────────────────────

    def pc_use_item(self, char_id: str, uid: str, *, target: str | None = None) -> list[Event]:
        ch = self._require_turn(char_id)
        stack = ch.inventory.get(uid)
        d = stack.definition
        if d is None or d.type != "consumable":
            raise CombatError(f"{stack.name} kullanılabilir bir eşya değil.")
        eff = d.effect
        events: list[Event] = []
        ref = f"pc:{char_id}"
        if eff == "heal":
            tgt = target or ref
            if not tgt.startswith("pc:"):
                tgt = f"pc:{tgt}"
            if tgt != ref and self.pc(tgt).rank != ch.rank and self.pc(tgt).hp > 0:
                raise CombatError("İksiri vermek için aynı safta olmalısınız.")
            ch.inventory.remove(uid, 1)
            r = roll(str(d.amount))
            events.append(Event(type="item", actor=ref, target=tgt,
                                text=f"{ch.name} {'kendi' if tgt == ref else self.name_of(tgt)} için {d.name} kullanıyor",
                                data={"roll": r.to_dict()}))
            events += self.heal(tgt, r.total, ch.name)
        elif eff == "throw_damage":
            foes = self.enc.active_enemies()
            if not foes:
                raise CombatError("Hedef yok.")
            tgt = self.enc.enemy(target) if target else (self.front_enemies() or foes)[0]
            ch.inventory.remove(uid, 1)
            adv, _ = self.attack_advantage(ref, tgt.ref, ranged=True)
            r = roll(f"1d20{_signed(ch.mod('dexterity') + ch.prof)}", advantage=adv)
            hit = (r.natural or 0) != 1 and r.total >= tgt.armor_class()
            events.append(Event(type="attack", actor=ref, target=tgt.ref,
                                text=f"{ch.name} {d.name} fırlatıyor → {'İSABET' if hit else 'ISKA'}",
                                data={"roll": r.to_dict(), "hit": hit}))
            if hit:
                dmg = roll(str(d.amount)).total
                vs = getattr(d, "vs", None)
                if vs and not any(t in tgt.mdef.tags for t in vs):
                    dmg = 0
                events += self.damage(tgt.ref, dmg, d.damage_type or "fire", magical=True, source=ch.name)
        elif eff == "fire_breath":
            ch.inventory.remove(uid, 1)
            dmg = roll(str(d.amount)).total
            save = getattr(d, "save", {}) or {}
            events.append(Event(type="item", actor=ref, text=f"{ch.name} iksiri içip ağzından alev püskürtüyor!"))
            for e in self.front_enemies()[:3]:
                ok, r = self.saving_throw(e.ref, save.get("ability", "dexterity"), save.get("dc", 13))
                events += self.damage(e.ref, dmg // 2 if ok else dmg, "fire", magical=True, source=ch.name)
        elif eff == "cure_poison":
            ch.inventory.remove(uid, 1)
            ch.remove_condition("poisoned")
            events.append(Event(type="item", actor=ref, text=f"{ch.name} panzehiri içiyor"))
        elif eff == "invisible":
            ch.inventory.remove(uid, 1)
            ch.add_condition(Condition(id="invisible", rounds=600))
            events.append(Event(type="item", actor=ref, text=f"{ch.name} gözden kayboluyor!"))
        elif eff == "set_strength":
            ch.inventory.remove(uid, 1)
            ch.add_condition(Condition(id="giant_strength", rounds=600, data={"set_strength": 21}))
            ch.abilities["_strength_override"] = 21
            events.append(Event(type="item", actor=ref, text=f"{ch.name} kaslarının şiştiğini hissediyor (Dev Gücü)"))
        elif eff == "stabilize":
            tgt = target or ref
            tch = self.pc(tgt)
            if tch.hp > 0 or tch.dead:
                raise CombatError("Bu kişinin ilk yardıma ihtiyacı yok.")
            stack.charges = (stack.charges or 10) - 1
            if stack.charges <= 0:
                ch.inventory.remove(uid, 1)
            tch.stable = True
            events.append(Event(type="item", actor=ref, target=f"pc:{tch.id}", text=f"{ch.name}, {tch.name} adlı yoldaşının kanamasını durduruyor"))
        else:
            raise CombatError(f"{d.name} savaşta kullanılamaz.")
        self._spend("action")
        events += self._check_end()
        return self._log(events)

    # ── environment ─────────────────────────────────────────────

    def pc_use_feature(self, char_id: str, feature_id: str, *, success: bool, rank: str | None = None) -> list[Event]:
        """Resolve a battlefield feature after the player's improvised check (rolled by the orchestrator)."""
        ch = self._require_turn(char_id)
        f = next((x for x in self.enc.features if x.id == feature_id), None)
        if f is None or f.uses == 0:
            raise CombatError("Bu çevre unsuru artık kullanılamaz.")
        self._spend("action")
        events = [Event(type="feature_use", actor=f"pc:{char_id}", text=f"{ch.name} {f.name} kullanıyor → "
                                                                        f"{'BAŞARILI' if success else 'başarısız'}")]
        if success:
            f.uses -= 1
            events += self.apply_hazard(f, rank or (f.rank if f.rank != "any" else "front"), source=ch.name)
            self.enc.highlights.append(f"{ch.name} used the environment: {f.name}")
        events += self._check_end()
        return self._log(events)

    def apply_hazard(self, f: EnvFeature, rank: str, *, source: str, targets_enemy: bool = True) -> list[Event]:
        events: list[Event] = []
        victims = [e.ref for e in self.enc.active_enemies() if e.rank == rank] if targets_enemy else \
            [f"pc:{c.id}" for c in self.active_pcs() if c.rank == rank]
        dmg = roll(f.damage or "2d6").total if f.damage else 0
        for v in victims[:4]:
            ok, r = self.saving_throw(v, f.save, f.dc)
            amount = dmg // 2 if ok else dmg
            events.append(Event(type="save", target=v, text=f"{self.name_of(v)} {'son anda kaçtı' if ok else 'yakalandı'}",
                                data={"roll": r.to_dict(), "success": ok}))
            if amount:
                events += self.damage(v, amount, f.damage_type, source=source)
            if not ok and f.effect in ("trap", "push_hazard") and self._alive(v):
                self._add_cond(v, Condition(id="prone", rounds=1))
        return events

    def improvised_effect(self, char_id: str, *, success: bool, degree: str, effect: str, target: str | None,
                          damage: str | None = None, damage_type: str = "bludgeoning", condition: str | None = None,
                          ally: str | None = None, description: str = "") -> list[Event]:
        """Apply the bounded outcome of a free-text combat action (adjudicated by the LLM, rolled by players)."""
        ch = self._require_turn(char_id)
        self._spend("action")
        ref = f"pc:{char_id}"
        events = [Event(type="improvise", actor=ref, text=f"{ch.name}: {description[:120]} → "
                                                          f"{'BAŞARILI' if success else 'BAŞARISIZ'}",
                        data={"degree": degree})]
        if success:
            tref = None
            if target:
                tref = target if target.startswith(("en:", "pc:")) else f"en:{target}"
                if tref.startswith("en:") and not self.enc.enemy(tref).is_active:
                    tref = None
            if tref is None and self.enc.active_enemies():
                tref = (self.front_enemies() or self.enc.active_enemies())[0].ref
            if effect in ("damage", "damage_condition") and tref and damage:
                notation = double_dice(damage) if degree == "critical_success" else damage
                d = roll(notation)
                events += self.damage(tref, d.total, damage_type, critical=degree == "critical_success", source=ch.name)
            if effect in ("condition", "damage_condition") and tref and condition and self._alive(tref):
                self._add_cond(tref, Condition(id=condition, rounds=1 if condition != "restrained" else 2,
                                               save="strength" if condition in ("restrained", "grappled") else None,
                                               dc=ch.spell_dc if ch.spellcasting else 8 + ch.prof + ch.mod("strength")))
                events.append(Event(type="condition", target=tref, text=f"{self.name_of(tref)}: {cname(condition)}"))
            if effect == "push" and tref and tref.startswith("en:"):
                self.enc.enemy(tref).rank = "back"
                self._add_cond(tref, Condition(id="prone", rounds=1))
                events.append(Event(type="move", target=tref, text=f"{self.name_of(tref)} geriye fırlatıldı!"))
            if effect == "advantage_ally" and ally and ally in self.party:
                self.party[ally].add_condition(Condition(id="helped", rounds=2))
                events.append(Event(type="condition", target=f"pc:{ally}", text=f"{self.party[ally].name} avantaj kazandı"))
            if effect == "intimidate" and tref and tref.startswith("en:"):
                e = self.enc.enemy(tref)
                if "mindless" not in e.mdef.behavior.get("tactics", []):
                    self._add_cond(tref, Condition(id="frightened", rounds=2))
                    events.append(Event(type="condition", target=tref, text=f"{e.name} korkuyla geri çekiliyor"))
            self.enc.highlights.append(f"{ch.name} pulled off a creative move: {description[:80]}")
        events += self._check_end()
        return self._log(events)

    # ── dying ───────────────────────────────────────────────────

    def death_save(self, char_id: str, d20: DiceRoll | None = None) -> list[Event]:
        ch = self.party[char_id]
        ref = f"pc:{char_id}"
        if self.current() != ref or ch.hp > 0 or ch.dead or ch.stable:
            raise CombatError("Ölüm zarı gerekmiyor.")
        if d20 is not None:
            nat = d20.natural or d20.total
            res = _apply_death_save(ch, nat)
            out = {"roll": d20.to_dict(), "natural": nat, "result": res}
        else:
            out = ch.roll_death_save()
        label = {"success": "başarılı", "fail": "başarısız", "double_fail": "ÇİFT başarısızlık!",
                 "revived": "DOĞAL 20 — ayağa kalkıyor!", "stable": "istikrara kavuştu",
                 "dead": "son nefesini verdi..."}[out["result"]]
        events = [Event(type="death_save", actor=ref,
                        text=f"{ch.name} ölüm zarı: {out['natural']} → {label} "
                             f"({ch.death_saves.successes}✔ / {ch.death_saves.failures}✖)",
                        data=out)]
        if out["result"] == "dead":
            self.enc.highlights.append(f"{ch.name} DIED from their wounds")
        if out["result"] == "revived":
            self.enc.highlights.append(f"{ch.name} miraculously rose from the brink of death (natural 20)")
        events += self._check_end()
        return self._log(events)

    # ═══════════════════════════════════════════════════════════
    # Enemy actions
    # ═══════════════════════════════════════════════════════════

    def _monster_attack(self, e: Enemy, target: Character, att) -> list[Event]:
        tref = f"pc:{target.id}"
        ranged = bool(att.range)
        adv, reasons = self.attack_advantage(e.ref, tref, ranged=ranged)
        r = roll(f"1d20{_signed(att.hit)}", advantage=adv)
        nat = r.natural or 0
        ac = target.armor_class()
        if nat != 20 and r.total >= ac and r.total < ac + 5 and "shield" in target.known_spells() \
                and target.spell_slots.get(1, 0) > 0 and target.hp > 0 and not target.has_condition("shield_spell"):
            target.spell_slots[1] -= 1
            target.add_condition(Condition(id="shield_spell", rounds=1, data={"ac_bonus": 5}))
            ac += 5
            reaction = [Event(type="spell", actor=tref, text=f"{target.name} son anda Kalkan büyüsünü açıyor! (+5 ZS)")]
        else:
            reaction = []
        auto_crit = any(cinfo(c.id).melee_auto_crit for c in target.conditions) and not ranged
        hit = nat != 1 and (nat == 20 or r.total >= ac or (target.hp <= 0 and not ranged))
        crit = hit and (nat == 20 or auto_crit or (target.hp <= 0 and not ranged))
        events = reaction + [Event(type="attack", actor=e.ref, target=tref,
                                   text=f"{e.name} → {target.name} ({att.name}): {r.total} vs ZS {ac} → "
                                        + ("KRİTİK!" if crit else "İSABET" if hit else "ISKA"),
                                   data={"roll": r.to_dict(), "hit": hit, "critical": crit, "advantage": adv,
                                         "reasons": reasons, "weapon": att.name, "natural": nat})]
        if not hit or att.dmg == "0" and not att.on_hit:
            return events
        if att.dmg != "0":
            notation = double_dice(att.dmg) if crit else att.dmg
            amount = roll(notation).total
            if "brute" in e.mdef.traits:
                amount += roll(att.dmg.split("+")[0]).total
            if e.notes.get("enraged"):
                amount += 2
            if target.has("uncanny_dodge") and not target.has_condition("dodge_used") and target.hp > 0:
                amount //= 2
                target.add_condition(Condition(id="dodge_used", rounds=1))
                events.append(Event(type="info", target=tref, text=f"{target.name} son anda kıvrılarak darbenin yarısını savuşturuyor"))
            events += self.damage(tref, amount, att.type, critical=crit, source=e.name)
        oh = att.on_hit or {}
        if oh.get("extra_dmg") and target.hp >= 0 and not target.dead:
            xd = roll(oh["extra_dmg"]).total
            if oh.get("save"):
                ok, sr = self.saving_throw(tref, oh["save"], oh.get("dc", 11))
                if ok and oh.get("half"):
                    xd //= 2
                elif ok:
                    xd = 0
            if xd:
                events += self.damage(tref, xd, oh.get("extra_type", "poison"), source=e.name)
        if oh.get("condition") and not target.dead and target.hp > 0:
            immune = target.race == "elf" and "elf" in (oh.get("not_vs") or [])
            if not immune:
                if oh.get("save"):
                    ok, sr = self.saving_throw(tref, oh["save"], oh.get("dc", 11))
                else:
                    ok = False
                if not ok:
                    target.add_condition(Condition(id=oh["condition"], rounds=oh.get("rounds", 1 if oh["condition"] == "prone" else 10),
                                                   save=oh.get("save") if oh.get("save_ends") else
                                                   ("strength" if oh.get("escape_dc") else None),
                                                   dc=oh.get("dc") if oh.get("save_ends") else oh.get("escape_dc")))
                    events.append(Event(type="condition", target=tref, text=f"{target.name}: {cname(oh['condition'])}!"))
                    if oh["condition"] == "paralyzed":
                        self.enc.highlights.append(f"{target.name} is PARALYZED by {e.name}'s touch")
        if oh.get("max_hp_drain") and target.hp > 0:
            drained = min(target.max_hp - 1, events[-1].data.get("amount", 0) if events else 0)
            if drained > 0:
                target.max_hp_bonus -= drained
                events.append(Event(type="info", target=tref, text=f"{target.name} yaşam gücünün çekildiğini hissediyor (azami can -{drained})"))
        return events

    def monster_special(self, e: Enemy, action: dict) -> list[Event]:
        """Breath weapons, gazes, songs, engulf..."""
        events = [Event(type="special", actor=e.ref, text=f"{e.name}: {action['name']}!", data={"action": action["id"]})]
        e.recharge_ready[action["id"]] = False
        tgt = action.get("target", "one_player")
        pcs = self.active_pcs()
        if not pcs:
            return events
        if tgt == "all_players":
            victims = pcs
        elif tgt in ("rank", "front"):
            front = [c for c in pcs if c.rank == "front"]
            victims = front or pcs
        else:
            victims = [min(pcs, key=lambda c: c.hp)]
        dmg_total = roll(action["dmg"]).total if action.get("dmg") else 0
        for v in victims:
            vref = f"pc:{v.id}"
            ok, r = self.saving_throw(vref, action.get("save", "dexterity"), action.get("dc", 12))
            events.append(Event(type="save", target=vref, text=f"{v.name} {'direndi' if ok else 'direnemedi'} ({r.total} vs ZS {action.get('dc', 12)})",
                                data={"roll": r.to_dict(), "success": ok}))
            if dmg_total:
                amount = (dmg_total // 2 if action.get("half") else 0) if ok else dmg_total
                events += self.damage(vref, amount, action.get("type", "fire"), source=e.name)
            if not ok and action.get("condition") and not v.dead and v.hp > 0:
                v.add_condition(Condition(id=action["condition"], rounds=action.get("rounds", 2),
                                          save=action.get("save"), dc=action.get("dc")))
                events.append(Event(type="condition", target=vref, text=f"{v.name}: {cname(action['condition'])}"))
        self.enc.highlights.append(f"{e.name} unleashed {action['name']}")
        return events

    def monster_cast(self, e: Enemy, spell_id: str) -> list[Event]:
        sp = data.spell(spell_id)
        if sp.level > 0:
            lvl = min((lv for lv, n in e.slots.items() if n > 0 and lv >= sp.level), default=None)
            if lvl is None:
                return []
            e.slots[lvl] -= 1
        else:
            lvl = 0
        events = [Event(type="spell", actor=e.ref, text=f"{e.name} {sp.name} büyüsünü yapıyor!", data={"spell": spell_id})]
        targets: list[str] = []
        if sp.kind == "heal":
            hurt = [x for x in self.enc.active_enemies() if x.hp_fraction() < 0.6]
            if hurt:
                targets = [min(hurt, key=lambda x: x.hp_fraction()).ref]
        events += self._resolve_spell(e.ref, sp, lvl, targets, None)
        return events

    def _check_end(self) -> list[Event]:
        if self.enc.status != "active":
            return []
        if not self.enc.active_enemies():
            self.enc.status = "victory"
            return [Event(type="victory", text="Zafer! Düşmanlar alt edildi.")]
        if not self.active_pcs():
            if self.enc.fled_party and all(self.party[c].dead or self.party[c].hp <= 0 or c in self.enc.fled_party
                                           for c in self.enc.party) and \
                    any(c in self.enc.fled_party for c in self.enc.party):
                self.enc.status = "fled"
                return [Event(type="fled", text="Grup savaş alanından kaçtı.")]
            self.enc.status = "defeat"
            return [Event(type="defeat", text="Grup yenildi...")]
        return []

    # ═══════════════════════════════════════════════════════════
    # Rewards
    # ═══════════════════════════════════════════════════════════

    def rewards(self) -> dict:
        """XP for overcome enemies and rolled loot (once)."""
        overcome = [e for e in self.enc.enemies if e.state in ("dead", "fled", "surrendered", "down")]
        xp = sum(e.mdef.xp for e in overcome)
        loot = {"copper": 0, "items": []}
        if not self.enc.loot_rolled:
            for e in self.enc.enemies:
                if e.state not in ("dead", "surrendered", "down"):
                    continue
                spec = e.mdef.loot or {}
                if spec.get("gold"):
                    loot["copper"] += roll(spec["gold"]).total * 100
                for iid, p in (spec.get("items") or {}).items():
                    if random.random() < float(p):
                        loot["items"].append(iid)
            self.enc.loot_rolled = True
        survivors = [c for c in self.enc.party if not self.party[c].dead]
        each = xp // max(1, len(survivors))
        return {"xp_total": xp, "xp_each": each, "loot": loot, "survivors": survivors}

    # ═══════════════════════════════════════════════════════════
    # Misc
    # ═══════════════════════════════════════════════════════════

    def _log(self, events: list[Event]) -> list[Event]:
        self.enc.log.extend(events)
        if len(self.enc.log) > 400:
            self.enc.log = self.enc.log[-400:]
        return events

    def public_state(self) -> dict:
        return {
            "id": self.enc.id, "status": self.enc.status, "round": self.enc.round,
            "current": self.current(), "order": self.order_public(),
            "enemies": [e.to_public() for e in self.enc.enemies],
            "party": [{"id": c, "name": self.party[c].name, "rank": self.party[c].rank,
                       "hp": self.party[c].hp, "max_hp": self.party[c].effective_max_hp,
                       "ac": self.party[c].armor_class(), "dead": self.party[c].dead,
                       "fled": c in self.enc.fled_party, "portrait": self.party[c].portrait,
                       "death_saves": self.party[c].death_saves.model_dump(), "stable": self.party[c].stable,
                       "conditions": [x.id for x in self.party[c].conditions]}
                      for c in self.enc.party],
            "features": [f.model_dump() for f in self.enc.features if f.uses != 0],
            "turn": self.enc.turn.model_dump(),
            "title": self.enc.title,
        }


def _apply_death_save(ch: Character, nat: int) -> str:
    from dndm.game.character import DeathSaves
    if nat == 20:
        ch.hp = 1
        ch.death_saves = DeathSaves()
        return "revived"
    if nat == 1:
        ch.death_saves.failures += 2
        res = "double_fail"
    elif nat >= 10:
        ch.death_saves.successes += 1
        res = "success"
    else:
        ch.death_saves.failures += 1
        res = "fail"
    if ch.death_saves.failures >= 3:
        ch.dead = True
        return "dead"
    if ch.death_saves.successes >= 3:
        ch.stable = True
        return "stable"
    return res


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)
