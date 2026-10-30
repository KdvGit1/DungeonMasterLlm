import random
from collections import Counter

import pytest

from dndm.game.character import Condition
from dndm.game.combat.ai import enemy_turn
from dndm.game.combat.autoplay import simulate
from dndm.game.combat.engine import CombatEngine, CombatError
from dndm.game.combat.state import EnvFeature
from dndm.game.creation import create_character, make_pregen
from dndm.rules import data, dice


@pytest.fixture(autouse=True)
def seeded():
    dice.set_rng(random.Random(42))
    random.seed(42)
    yield
    dice.set_rng(random.SystemRandom())


PARTY_ORDER = [0, 1, 2, 4, 5, 3, 6, 7]  # fighter, rogue, cleric, wizard, barbarian, ranger, paladin, bard


def party(n=4, level=1):
    chars = {}
    for i in PARTY_ORDER[:n]:
        ch = make_pregen(i)
        while ch.level < level:
            ch.xp = 64000
            ch.level_up()
        ch.long_rest()
        chars[ch.id] = ch
    return chars


def fresh(specs, n=4, level=1, features=None):
    p = party(n, level)
    enc = CombatEngine.build(specs, p, features=features)
    return CombatEngine(enc, p), p


def test_build_labels_and_hp():
    eng, _ = fresh([{"monster": "goblin", "count": 3}, {"monster": "goblin_boss", "count": 1, "name": "Grik"}])
    names = [e.name for e in eng.enc.enemies]
    assert names[:3] == ["Goblin 1", "Goblin 2", "Goblin 3"] and names[3] == "Grik"
    assert [e.label for e in eng.enc.enemies] == ["A", "B", "C", "D"]
    assert all(1 <= e.hp <= 12 for e in eng.enc.enemies[:3])


def test_initiative_groups_monsters_and_boss_acts_twice():
    eng, p = fresh([{"monster": "wolf", "count": 3}, {"monster": "young_green_dragon", "count": 1}])
    eng.roll_initiative()
    wolves = [e for e in eng.enc.enemies if e.monster_id == "wolf"]
    assert len({w.initiative for w in wolves}) == 1
    dragon = next(e for e in eng.enc.enemies if e.monster_id == "young_green_dragon")
    assert eng.enc.order.count(dragon.ref) == 2
    assert len(eng.enc.order) == 4 + 3 + 2


def _make_current(eng, ref):
    eng.enc.status = "active"
    if ref not in eng.enc.order:
        eng.enc.order.insert(0, ref)
    eng.enc.turn_index = eng.enc.order.index(ref)
    eng.start_turn()


def test_attack_requires_turn_and_reach():
    eng, p = fresh([{"monster": "goblin", "count": 1, "rank": "front"}, {"monster": "kobold", "count": 1, "rank": "back"}])
    eng.roll_initiative()
    fighter = next(c for c in p.values() if c.cls == "fighter")
    others = [r for r in eng.enc.order if r != f"pc:{fighter.id}"]
    eng.enc.turn_index = eng.enc.order.index(others[0])
    with pytest.raises(CombatError):
        eng.pc_attack(fighter.id, eng.enc.enemies[0].uid)
    _make_current(eng, f"pc:{fighter.id}")
    kobold = eng.enc.enemies[1]
    with pytest.raises(CombatError, match="arka safta"):
        eng.pc_attack(fighter.id, kobold.uid)


def test_attack_hit_and_crit_math():
    eng, p = fresh([{"monster": "ogre", "count": 1}])
    eng.roll_initiative()
    fighter = next(c for c in p.values() if c.cls == "fighter")
    _make_current(eng, f"pc:{fighter.id}")
    ogre = eng.enc.enemies[0]
    hp0 = ogre.hp
    nat20 = dice.DiceRoll(notation="1d20+5", dice=[dice.Die(20, 20)], modifier=5, total=25)
    ev = eng.pc_attack(fighter.id, ogre.uid, d20=nat20)
    assert ev[0].data["critical"] and ogre.hp < hp0
    assert len(ev[0].data["damage_rolls"][0]["dice"]) == 2  # 1d8 doubled
    eng.enc.turn.attacks_left = 1
    eng.enc.turn.action = 1
    nat1 = dice.DiceRoll(notation="1d20+5", dice=[dice.Die(20, 1)], modifier=5, total=6)
    hp1 = ogre.hp
    ev = eng.pc_attack(fighter.id, ogre.uid, d20=nat1)
    assert not ev[0].data["hit"] and ogre.hp == hp1


def test_paralyzed_target_auto_crit_and_advantage():
    eng, p = fresh([{"monster": "bandit", "count": 1}])
    eng.roll_initiative()
    fighter = next(c for c in p.values() if c.cls == "fighter")
    _make_current(eng, f"pc:{fighter.id}")
    b = eng.enc.enemies[0]
    b.add_condition(Condition(id="paralyzed", rounds=3))
    adv, reasons = eng.attack_advantage(f"pc:{fighter.id}", b.ref, ranged=False)
    assert adv == "advantage"
    hit10 = dice.DiceRoll(notation="1d20+5", dice=[dice.Die(20, 15)], modifier=5, total=20)
    ev = eng.pc_attack(fighter.id, b.uid, d20=hit10)
    assert ev[0].data["critical"]


def test_resistance_immunity_vulnerability():
    eng, p = fresh([{"monster": "skeleton", "count": 1}, {"monster": "specter", "count": 1}])
    sk, sp = eng.enc.enemies
    sk.hp = sk.max_hp = 50
    eng.damage(sk.ref, 10, "bludgeoning")
    assert sk.hp == 30  # vulnerable
    sk.hp = 50
    eng.damage(sk.ref, 10, "poison")
    assert sk.hp == 50  # immune
    sp.hp = sp.max_hp = 50
    eng.damage(sp.ref, 10, "slashing")
    assert sp.hp == 45  # nonmagical resistance
    eng.damage(sp.ref, 10, "slashing", magical=True)
    assert sp.hp == 35


def test_werewolf_needs_silver_or_magic():
    eng, _ = fresh([{"monster": "werewolf", "count": 1}])
    w = eng.enc.enemies[0]
    hp = w.hp
    eng.damage(w.ref, 10, "slashing")
    assert w.hp == hp
    eng.damage(w.ref, 10, "slashing", silvered=True)
    assert w.hp == hp - 10


def test_troll_regenerates_unless_burned():
    eng, p = fresh([{"monster": "troll", "count": 1}])
    eng.roll_initiative()
    t = eng.enc.enemies[0]
    eng.damage(t.ref, t.hp, "slashing")
    assert t.state == "down"
    _make_current(eng, t.ref)
    assert t.state == "active" and t.hp == 10
    eng.damage(t.ref, 10, "slashing")
    assert t.state == "down"
    eng.damage(t.ref, 1, "fire")
    _make_current(eng, t.ref)
    assert t.state == "dead"


def test_zombie_undead_fortitude_vs_radiant():
    survived = 0
    for _ in range(40):
        eng, _ = fresh([{"monster": "zombie", "count": 1}])
        z = eng.enc.enemies[0]
        z.hp = 3  # small hit → DC 5+3 = 8 CON save, usually passed
        eng.damage(z.ref, 3, "slashing")
        survived += z.state == "active"
        eng2, _ = fresh([{"monster": "zombie", "count": 1}])
        z2 = eng2.enc.enemies[0]
        eng2.damage(z2.ref, z2.hp, "radiant")
        assert z2.state == "dead"
    assert survived > 0


def test_opportunity_attack_when_retreating():
    eng, p = fresh([{"monster": "orc", "count": 2}])
    eng.roll_initiative()
    fighter = next(c for c in p.values() if c.cls == "fighter")
    _make_current(eng, f"pc:{fighter.id}")
    ev = eng.pc_move(fighter.id, "back")
    assert any("fırsat" in e.text for e in ev)
    assert fighter.rank == "back"
    # disengage avoids it
    eng2, p2 = fresh([{"monster": "orc", "count": 2}])
    eng2.roll_initiative()
    f2 = next(c for c in p2.values() if c.cls == "fighter")
    _make_current(eng2, f"pc:{f2.id}")
    eng2.pc_disengage(f2.id)
    ev = eng2.pc_move(f2.id, "back")
    assert not any("fırsat" in e.text for e in ev)


def test_wizard_spells():
    eng, p = fresh([{"monster": "goblin", "count": 3}])
    eng.roll_initiative()
    wiz = next(c for c in p.values() if c.cls == "wizard")
    _make_current(eng, f"pc:{wiz.id}")
    slots = wiz.spell_slots[1]
    ev = eng.pc_cast(wiz.id, "magic_missile", targets=[e.ref for e in eng.enc.enemies])
    assert wiz.spell_slots[1] == slots - 1
    assert sum(1 for e in ev if e.type == "damage") == 3
    with pytest.raises(CombatError):
        eng.pc_cast(wiz.id, "fire_bolt", targets=[eng.enc.enemies[0].ref])  # action already spent
    with pytest.raises(CombatError):
        eng.pc_cast(wiz.id, "fireball")  # unknown at level 1


def test_sleep_and_hold_person():
    eng, p = fresh([{"monster": "bandit", "count": 3}], level=3)
    eng.roll_initiative()
    wiz = next(c for c in p.values() if c.cls == "wizard")
    _make_current(eng, f"pc:{wiz.id}")
    eng.pc_cast(wiz.id, "sleep", rank="front")
    assert any(e.has_condition("asleep") for e in eng.enc.enemies)
    eng.enc.turn.action = 1
    awake = next((e for e in eng.enc.enemies if not e.has_condition("asleep")), eng.enc.enemies[0])
    eng.pc_cast(wiz.id, "hold_person", targets=[awake.ref])
    assert wiz.concentration == "hold_person"


def test_cleric_heals_downed_ally():
    eng, p = fresh([{"monster": "goblin", "count": 1}])
    eng.roll_initiative()
    cleric = next(c for c in p.values() if c.cls == "cleric")
    victim = next(c for c in p.values() if c.cls == "wizard")
    victim.take_damage(victim.hp + 1)
    assert victim.is_down
    _make_current(eng, f"pc:{cleric.id}")
    ev = eng.pc_cast(cleric.id, "healing_word", targets=[f"pc:{victim.id}"])
    assert victim.hp > 0 and any(e.type == "revive" for e in ev)
    # bonus action spell leaves the action available
    assert eng.enc.turn.action == 1


def test_rage_and_second_wind():
    eng, p = fresh([{"monster": "orc", "count": 1}], n=5)
    eng.roll_initiative()
    barb = next(c for c in p.values() if c.cls == "barbarian")
    _make_current(eng, f"pc:{barb.id}")
    eng.pc_feature(barb.id, "rage")
    assert barb.has_condition("raging") and barb.resources["rage"] == 1
    with pytest.raises(CombatError):
        eng.pc_feature(barb.id, "rage")
    fighter = next(c for c in p.values() if c.cls == "fighter")
    fighter.hp = 3
    _make_current(eng, f"pc:{fighter.id}")
    eng.pc_feature(fighter.id, "second_wind")
    assert fighter.hp > 3 and fighter.resources["second_wind"] == 0


def test_potion_and_death_save_flow():
    eng, p = fresh([{"monster": "goblin", "count": 1}])
    eng.roll_initiative()
    rogue = next(c for c in p.values() if c.cls == "rogue")
    rogue.inventory.add("potion_healing", 1)
    rogue.take_damage(rogue.hp + 1)
    _make_current(eng, f"pc:{rogue.id}")
    with pytest.raises(CombatError):
        eng.pc_attack(rogue.id, eng.enc.enemies[0].uid)
    ev = eng.death_save(rogue.id)
    assert ev[0].type == "death_save"


def test_environment_feature_hazard():
    feat = EnvFeature(name="Çürük Avize", effect="hazard", damage="3d6", damage_type="bludgeoning", rank="front")
    eng, p = fresh([{"monster": "bandit", "count": 3}], features=[feat])
    eng.roll_initiative()
    rogue = next(c for c in p.values() if c.cls == "rogue")
    _make_current(eng, f"pc:{rogue.id}")
    before = sum(e.hp for e in eng.enc.enemies)
    eng.pc_use_feature(rogue.id, feat.id, success=True)
    assert sum(e.hp for e in eng.enc.enemies) < before
    assert feat.uses == 0


def test_enemy_turn_runs_for_every_monster():
    for mid in data.monsters():
        eng, p = fresh([{"monster": mid, "count": 1}])
        eng.roll_initiative()
        e = eng.enc.enemies[0]
        _make_current(eng, e.ref)
        enemy_turn(eng, e)  # must not raise


def test_morale_surrender_and_flee():
    outcomes = Counter()
    for _ in range(60):
        eng, p = fresh([{"monster": "bandit_captain", "count": 1, "name": "Reis"}, {"monster": "bandit", "count": 3}])
        eng.roll_initiative()
        cap = eng.enc.enemies[0]
        eng.damage(cap.ref, cap.hp, "slashing")
        b = eng.enc.enemies[1]
        b.hp = 1
        _make_current(eng, b.ref)
        enemy_turn(eng, b)
        outcomes[b.state] += 1
    assert outcomes["surrendered"] + outcomes["fled"] > 0


def test_rewards_xp_and_loot_once():
    eng, p = fresh([{"monster": "goblin_boss", "count": 1}, {"monster": "goblin", "count": 2}])
    for e in eng.enc.enemies:
        eng.damage(e.ref, 999, "slashing")
    r = eng.rewards()
    assert r["xp_total"] == 200 + 50 + 50 and r["xp_each"] == 300 // 4
    assert eng.rewards()["loot"] == {"copper": 0, "items": []}


SCENARIOS = [
    ("lvl1 vs goblins", 1, [{"monster": "goblin", "count": 4}]),
    ("lvl1 vs wolves", 1, [{"monster": "wolf", "count": 3}]),
    ("lvl1 vs bandits+captain", 1, [{"monster": "bandit", "count": 3}, {"monster": "bandit_captain", "count": 1}]),
    ("lvl2 vs bugbear+goblins", 2, [{"monster": "bugbear", "count": 1}, {"monster": "goblin", "count": 3}]),
    ("lvl3 vs ogre+orcs", 3, [{"monster": "ogre", "count": 1}, {"monster": "orc", "count": 2}]),
    ("lvl3 vs cult", 3, [{"monster": "cult_fanatic", "count": 1}, {"monster": "cultist", "count": 4}]),
    ("lvl3 vs undead", 3, [{"monster": "ghoul", "count": 2}, {"monster": "skeleton", "count": 3}]),
    ("lvl5 vs troll", 5, [{"monster": "troll", "count": 1}]),
    ("lvl5 vs dragon", 5, [{"monster": "young_green_dragon", "count": 1}]),
    ("lvl5 vs mage+veterans", 5, [{"monster": "mage", "count": 1}, {"monster": "veteran", "count": 2}]),
]


@pytest.mark.parametrize("label,level,specs", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_simulated_battles_terminate(label, level, specs):
    results = Counter()
    for _ in range(25):
        eng, p = fresh(specs, n=4, level=level)
        results[simulate(eng)] += 1
    assert sum(results.values()) == 25
    # every scenario should be winnable at least sometimes and not a guaranteed stomp for the monsters
    assert results["victory"] > 0, results
