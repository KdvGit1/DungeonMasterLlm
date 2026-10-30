"""
Simple scripted policy for player characters — used by the combat simulation
tests (balance + crash hunting) and as the AFK fallback when a player does not
act in time.
"""

from __future__ import annotations

import random

from dndm.game.character import Character
from dndm.game.combat.engine import CombatEngine, CombatError
from dndm.game.combat.state import Event
from dndm.rules import data


def auto_pc_turn(engine: CombatEngine, ch: Character) -> list[Event]:
    events: list[Event] = []
    ref = f"pc:{ch.id}"
    if engine.enc.status != "active":
        return events
    if ch.hp <= 0:
        if not ch.stable and not ch.dead:
            return engine.death_save(ch.id)
        return events
    if not ch.can_act:
        return events

    def attempt(fn, *a, **kw) -> bool:
        try:
            events.extend(fn(*a, **kw))
            return True
        except CombatError:
            return False

    # emergency healing
    dying = [c for c in engine.present_pcs() if c.hp <= 0 and not c.dead]
    hurt = [c for c in engine.active_pcs() if c.hp < c.effective_max_hp * 0.35]
    heal_spells = [s for s in ch.known_spells() if data.spell(s).kind == "heal" and data.spell(s).heal]
    if (dying or hurt) and heal_spells:
        for sid in sorted(heal_spells, key=lambda s: data.spell(s).cast != "bonus"):
            sp = data.spell(sid)
            if ch.spell_slots.get(sp.level, 0) > 0:
                tgt = (dying or hurt)[0]
                if attempt(engine.pc_cast, ch.id, sid, targets=[f"pc:{tgt.id}"]):
                    break
    if ch.resources.get("lay_on_hands", 0) > 0 and dying and engine.enc.turn.action > 0:
        attempt(engine.pc_feature, ch.id, "lay_on_hands", target_id=dying[0].id)
    potion = next((s for s in ch.inventory.items if s.item_id == "potion_healing"), None)
    if potion and ch.hp < ch.effective_max_hp * 0.3 and engine.enc.turn.action > 0:
        attempt(engine.pc_use_item, ch.id, potion.uid)

    # bonus-action buffs
    if ch.has("rage") and not ch.has_condition("raging") and ch.resources.get("rage", 0) > 0:
        attempt(engine.pc_feature, ch.id, "rage")
    if ch.has("second_wind") and ch.hp < ch.effective_max_hp * 0.5 and ch.resources.get("second_wind", 0) > 0:
        attempt(engine.pc_feature, ch.id, "second_wind")
    if ch.has_condition("spiritual_weapon") and engine.enc.turn.bonus > 0:
        attempt(engine.pc_feature, ch.id, "spiritual_weapon_attack")

    foes = engine.enc.active_enemies()
    if not foes or engine.enc.turn.action <= 0:
        return events

    # casters: damage spell if slots left (AoE when crowded)
    dmg_spells = [s for s in ch.known_spells()
                  if data.spell(s).kind in ("attack", "save", "auto") and data.spell(s).damage]
    if dmg_spells and ch.cls in ("wizard", "cleric", "bard"):
        front = engine.front_enemies()
        best = None
        for sid in dmg_spells:
            sp = data.spell(sid)
            if sp.level > 0 and ch.spell_slots.get(sp.level, 0) <= 0:
                continue
            if sp.target == "rank" and len(front) < 2:
                continue
            if sp.model_extra.get("front_only") and ch.rank != "front":
                continue
            if best is None or sp.level > data.spell(best).level:
                best = sid
        if best and (data.spell(best).level == 0 or random.random() < 0.7):
            target = min(foes, key=lambda e: e.hp)
            if attempt(engine.pc_cast, ch.id, best, targets=[target.ref], rank="front"):
                return events

    # weapons
    while engine.enc.turn.attacks_left > 0 and engine.enc.active_enemies():
        foes = engine.enc.active_enemies()
        opts = ch.attack_options()
        reachable = [e for e in foes if engine.can_melee_reach_enemy(e)]
        melee = next((o for o in opts if not o["ranged"]), None)
        ranged = next((o for o in opts if o["ranged"]), None)
        if melee and reachable and (ch.rank == "front" or not ranged):
            if ch.rank == "back" and not engine.enc.turn.moved:
                attempt(engine.pc_move, ch.id, "front")
            target = min(reachable, key=lambda e: e.hp)
            ok = attempt(engine.pc_attack, ch.id, target.uid, weapon_uid=melee["uid"])
        elif ranged:
            target = min(foes, key=lambda e: e.hp)
            ok = attempt(engine.pc_attack, ch.id, target.uid, weapon_uid=ranged["uid"])
        else:
            ok = attempt(engine.pc_dodge, ch.id)
        if not ok:
            attempt(engine.pc_dodge, ch.id)
            break
    return events


def simulate(engine: CombatEngine, max_rounds: int = 30) -> str:
    """Run a whole fight with autoplay PCs and AI enemies. Returns final status."""
    from dndm.game.combat.ai import enemy_turn
    if engine.enc.status == "setup":
        engine.roll_initiative()
    engine.start_turn()
    guard = 0
    while engine.enc.status == "active" and engine.enc.round <= max_rounds:
        guard += 1
        if guard > 2000:
            raise RuntimeError("combat simulation did not terminate")
        ref = engine.current()
        if ref and engine.is_pc(ref):
            auto_pc_turn(engine, engine.pc(ref))
        elif ref:
            enemy_turn(engine, engine.enc.enemy(ref))
        if engine.enc.status != "active":
            break
        engine.end_turn()
        if engine.enc.status != "active":
            break
        engine.start_turn()
    return engine.enc.status
