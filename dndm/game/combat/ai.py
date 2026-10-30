"""
Enemy tactics. Fast, rule-based decisions (no LLM) so enemy turns resolve
instantly; the narrator then dresses the results up.

Behaviour comes from ``monster.behavior``:
  morale  — flee/surrender threshold (fraction of HP) once things go badly
  tactics — tags such as focus_weakest, gang_up, hit_and_run, caster, healer,
            cowardly, surrender, fanatic, mindless, breath_first, commands_minions
"""

from __future__ import annotations

import random

from dndm.game.character import Character, Condition
from dndm.game.combat.conditions import info as cinfo
from dndm.game.combat.engine import CombatEngine
from dndm.game.combat.state import Enemy, Event
from dndm.rules import data


def enemy_turn(engine: CombatEngine, e: Enemy) -> list[Event]:
    enc = engine.enc
    events: list[Event] = []
    if not e.is_active:
        return events
    if any(cinfo(c.id).incapacitated for c in e.conditions):
        events.append(Event(type="info", actor=e.ref, text=f"{e.name} kıpırdayamıyor"))
        return engine._log(events)
    tactics = set(e.mdef.behavior.get("tactics", []))

    # bosses get a second, lighter slot each round: a single "legendary" attack
    if e.notes.get("acted_round") == enc.round:
        return engine._log(events + _legendary_action(engine, e, tactics))
    e.notes["acted_round"] = enc.round

    # 1. morale
    morale_ev = _morale_check(engine, e, tactics)
    if morale_ev:
        events += morale_ev
        events += engine._check_end()
        return engine._log(events)

    # frightened creatures try to back away
    if e.has_condition("frightened") and e.rank == "front" and "mindless" not in tactics:
        e.rank = "back"
        events.append(Event(type="move", actor=e.ref, text=f"{e.name} korkuyla geri çekiliyor"))

    # 2. leader rallies the troops once when hurt
    if "commands_minions" in tactics and not e.notes.get("rallied") and e.hp_fraction() < 0.6:
        allies = [x for x in enc.active_enemies() if x.uid != e.uid]
        if allies:
            e.notes["rallied"] = True
            for a in allies:
                a.add_condition(Condition(id="helped", rounds=2))
            events.append(Event(type="special", actor=e.ref, text=f"{e.name} adamlarına kükrüyor: \"Saldırın! Hepsini öldürün!\""))
            enc.highlights.append(f"{e.name} roared orders and rallied the remaining enemies")

    # 3. special actions (breath, gaze, song...)
    for act in e.mdef.actions:
        if not e.recharge_ready.get(act["id"], False):
            continue
        targets_ok = len(engine.active_pcs()) >= (2 if act.get("target") in ("all_players", "rank", "front") else 1)
        if targets_ok and ("breath_first" in tactics or random.random() < 0.6):
            events += engine.monster_special(e, act)
            events += engine._check_end()
            return engine._log(events)

    # 4. spellcasting
    if e.mdef.spellcasting and ("caster" in tactics or "healer" in tactics or random.random() < 0.5):
        cast = _choose_spell(engine, e, tactics)
        if cast:
            ev = engine.monster_cast(e, cast)
            if ev:
                events += ev
                events += engine._check_end()
                return engine._log(events)

    # 5. movement
    has_melee = any(not a.range for a in e.mdef.attacks)
    has_ranged = any(a.range for a in e.mdef.attacks)
    prefers_back = e.mdef.behavior.get("rank") == "back" and has_ranged
    if e.rank == "back" and has_melee and not prefers_back:
        e.rank = "front"
        events.append(Event(type="move", actor=e.ref, text=f"{e.name} öne atılıyor"))

    # 6. attacks (multiattack or best single attack)
    pcs = engine.active_pcs()
    if not pcs:
        # only dying characters left: brutes finish them, others wait
        dying = [c for c in engine.present_pcs() if c.hp <= 0 and not c.dead]
        if dying and ("hungry" in tactics or "frenzied" in tactics or "boss" in tactics):
            victim = random.choice(dying)
            att = _pick_attack(engine, e, victim)
            if att:
                events.append(Event(type="info", actor=e.ref, target=f"pc:{victim.id}",
                                    text=f"{e.name} yerdeki {victim.name} üzerine eğiliyor..."))
                events += engine._monster_attack(e, victim, att)
        events += engine._check_end()
        return engine._log(events)

    sequence = e.mdef.multiattack or [None]
    last_target: Character | None = None
    for att_id in sequence:
        if not engine.active_pcs():
            break
        target = _choose_target(engine, e, tactics, last_target)
        if target is None:
            break
        att = e.mdef.attack(att_id) if att_id else _pick_attack(engine, e, target)
        if att is None:
            break
        if not att.range and not engine.can_melee_reach_pc(target):
            ranged = next((a for a in e.mdef.attacks if a.range), None)
            if ranged:
                att = ranged
            else:
                target = _choose_target(engine, e, tactics, None, melee_only=True)
                if target is None:
                    break
        if att.recharge and not e.recharge_ready.get(att.id, True):
            att = next((a for a in e.mdef.attacks if not a.recharge), att)
        if att.recharge:
            e.recharge_ready[att.id] = False
        events += engine._monster_attack(e, target, att)
        last_target = target if target.hp > 0 else None

    # 7. hit and run
    if ("hit_and_run" in tactics or "nimble_escape" in e.mdef.traits) and e.rank == "front" \
            and has_ranged and e.hp_fraction() < 0.6:
        e.rank = "back"
        events.append(Event(type="move", actor=e.ref, text=f"{e.name} çevik bir hareketle geri sıçrıyor"))

    events += engine._check_end()
    return engine._log(events)


def _legendary_action(engine: CombatEngine, e: Enemy, tactics: set[str]) -> list[Event]:
    target = _choose_target(engine, e, tactics, None)
    if target is None:
        return []
    att = _pick_attack(engine, e, target)
    if att is None:
        return []
    events = [Event(type="info", actor=e.ref, text=f"{e.name} bir an bile durmuyor!")]
    events += engine._monster_attack(e, target, att)
    events += engine._check_end()
    return events


def _morale_check(engine: CombatEngine, e: Enemy, tactics: set[str]) -> list[Event]:
    if "mindless" in tactics or "fanatic" in tactics:
        return []
    threshold = float(e.mdef.behavior.get("morale", 0.3))
    if threshold <= 0:
        return []
    allies = [x for x in engine.enc.enemies if x.uid != e.uid]
    fallen = [x for x in allies if x.state in ("dead", "fled", "surrendered", "down")]
    leader_down = any(("leader" in x.mdef.tags or "boss" in x.mdef.tags) and x.state != "active" for x in allies)
    outnumbered = len(engine.active_pcs()) >= 2 * max(1, len(engine.enc.active_enemies()))
    badly_hurt = e.hp_fraction() < threshold
    going_badly = leader_down or (allies and len(fallen) >= len(allies) / 2) or outnumbered
    if not (badly_hurt and going_badly) and not (leader_down and "cowardly" in tactics):
        return []
    if "surrender" in tactics and "humanoid" in e.mdef.tags and random.random() < 0.7:
        e.state = "surrendered"
        e.add_condition(Condition(id="surrendered"))
        engine.enc.highlights.append(f"{e.name} threw down their weapon and begged for mercy")
        return [Event(type="surrender", actor=e.ref, text=f"{e.name} silahını yere atıp diz çöküyor: \"Merhamet!\"")]
    if "cowardly" in tactics or random.random() < 0.5:
        e.state = "fled"
        engine.enc.highlights.append(f"{e.name} fled in panic")
        return [Event(type="flee", actor=e.ref, text=f"{e.name} panik içinde kaçıyor!")]
    return []


def _reachable(engine: CombatEngine, e: Enemy, melee_only: bool = False) -> list[Character]:
    pcs = engine.active_pcs()
    has_ranged = any(a.range for a in e.mdef.attacks) or bool(e.mdef.spellcasting)
    if has_ranged and not melee_only:
        return pcs
    return [c for c in pcs if engine.can_melee_reach_pc(c)]


def _choose_target(engine: CombatEngine, e: Enemy, tactics: set[str], last: Character | None,
                   melee_only: bool = False) -> Character | None:
    cands = _reachable(engine, e, melee_only)
    if not cands:
        return None
    # never attack whoever charmed it (simplified: charmed enemies pick randomly)
    if last is not None and last in cands and last.hp > 0:
        return last
    if "gang_up" in tactics and engine.enc.enemy_focus:
        for c in cands:
            if c.id == engine.enc.enemy_focus:
                return c
    if "focus_weakest" in tactics or "boss" in tactics:
        choice = min(cands, key=lambda c: (c.hp, c.armor_class()))
    elif "focus_nearest" in tactics or "mindless" in tactics:
        front = [c for c in cands if c.rank == "front"] or cands
        choice = random.choice(front)
    else:
        # weighted: prefer front, lower AC, wounded
        def w(c: Character) -> float:
            return (2.0 if c.rank == "front" else 1.0) * (1.5 if c.hp < c.effective_max_hp / 2 else 1.0) \
                * max(0.5, (22 - c.armor_class()) / 8)
        choice = random.choices(cands, weights=[w(c) for c in cands])[0]
    if engine.enc.enemy_focus is None:
        engine.enc.enemy_focus = choice.id
    return choice


def _pick_attack(engine: CombatEngine, e: Enemy, target: Character):
    melee = [a for a in e.mdef.attacks if not a.range and a.dmg != "0"]
    ranged = [a for a in e.mdef.attacks if a.range and a.dmg != "0"]
    prefers_back = e.mdef.behavior.get("rank") == "back"
    if melee and engine.can_melee_reach_pc(target) and not (prefers_back and ranged and e.rank == "back"):
        return max(melee, key=lambda a: data_avg(a.dmg))
    if ranged:
        return max(ranged, key=lambda a: data_avg(a.dmg))
    return melee[0] if melee else None


def _choose_spell(engine: CombatEngine, e: Enemy, tactics: set[str]) -> str | None:
    spells = [data.spell(s) for s in (e.mdef.spellcasting or {}).get("spells", [])]

    def can_cast(sp) -> bool:
        return sp.level == 0 or any(n > 0 and lv >= sp.level for lv, n in e.slots.items())

    allies_hurt = [x for x in engine.enc.active_enemies() if x.hp_fraction() < 0.4]
    if allies_hurt:
        heals = [sp for sp in spells if sp.kind == "heal" and can_cast(sp)]
        if heals:
            return max(heals, key=lambda s: s.level).id
    pcs = engine.active_pcs()
    front = [c for c in pcs if c.rank == "front"]
    candidates = [sp for sp in spells if can_cast(sp) and sp.kind in ("attack", "save", "auto", "debuff", "buff")]
    if not candidates:
        return None
    if e.concentration:
        candidates = [sp for sp in candidates if not sp.concentration]
    aoe = [sp for sp in candidates if sp.target == "rank" and sp.damage and len(front) >= 2]
    if aoe and random.random() < 0.8:
        return max(aoe, key=lambda s: s.level).id
    leveled = [sp for sp in candidates if sp.level > 0 and sp.kind in ("attack", "save", "auto")]
    if leveled and random.random() < 0.6:
        return random.choice(leveled).id
    control = [sp for sp in candidates if sp.kind == "debuff" and sp.id == "hold_person"]
    if control and random.random() < 0.3:
        return control[0].id
    cantrips = [sp for sp in candidates if sp.level == 0]
    return random.choice(cantrips).id if cantrips else (candidates[0].id if candidates else None)


def data_avg(notation: str) -> float:
    from dndm.rules.dice import average
    try:
        return average(notation)
    except ValueError:
        return 0.0
