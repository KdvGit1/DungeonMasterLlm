import random

import pytest

from dndm.game.character import Character, Condition
from dndm.game.creation import (PREGENS, CreationError, create_character, make_pregen,
                                point_buy_cost)
from dndm.game.inventory import Inventory, InventoryError
from dndm.rules import dice


@pytest.fixture(autouse=True)
def seeded():
    dice.set_rng(random.Random(7))
    random.seed(7)
    yield
    dice.set_rng(random.SystemRandom())


# ── inventory ───────────────────────────────────────────────────

def test_stackables_merge_and_uniques_split():
    inv = Inventory()
    a = inv.add("arrow", 20)
    b = inv.add("arrow", 5)
    assert a is b and a.qty == 25
    inv.add("longsword", 2)
    assert len([s for s in inv.items if s.item_id == "longsword"]) == 2


def test_remove_partial_and_full():
    inv = Inventory()
    s = inv.add("potion_healing", 3)
    part = inv.remove(s.uid, 1)
    assert part.qty == 1 and s.qty == 2 and part.uid != s.uid
    inv.remove(s.uid, 2)
    assert inv.count("potion_healing") == 0
    with pytest.raises(InventoryError):
        inv.remove("nope", 1)


def test_cannot_remove_more_than_owned():
    inv = Inventory()
    s = inv.add("torch", 2)
    with pytest.raises(InventoryError):
        inv.remove(s.uid, 5)


def test_unknown_item_rejected():
    with pytest.raises(InventoryError):
        Inventory().add("lightsaber")


def test_custom_quest_item_and_find():
    inv = Inventory()
    key = inv.add_custom("Paslı Demir Anahtar", kind="quest", description="Değirmenin bodrumunu açar")
    assert key.item_id is None and key.rarity == "quest"
    assert inv.find("anahtar") is key
    assert inv.find("PASLI DEMİR ANAHTAR".lower()) is key


def test_coins():
    inv = Inventory()
    inv.add_coins(gp=2, sp=3, cp=4)
    assert inv.copper == 234
    assert inv.coins_tr() == "2 altın, 3 gümüş, 4 bakır"
    with pytest.raises(InventoryError):
        inv.add_coins(gp=-5)
    assert inv.can_afford(2.3) and not inv.can_afford(3)


def test_equip_two_handed_clears_shield():
    inv = Inventory()
    sh = inv.add("shield")
    sw = inv.add("longsword")
    inv.equip(sw.uid)
    inv.equip(sh.uid)
    assert inv.off_hand() is sh
    ga = inv.add("greataxe")
    inv.equip(ga.uid)
    assert inv.weapon() is ga and inv.off_hand() is None
    with pytest.raises(InventoryError):
        inv.equip(sh.uid)


def test_dual_wield_light_weapons():
    inv = Inventory()
    a = inv.add("shortsword")
    b = inv.add("dagger")
    inv.equip(a.uid)
    inv.equip(b.uid)
    assert inv.weapon() is a and inv.off_hand() is b


def test_consume_ammo():
    inv = Inventory()
    inv.add("arrow", 3)
    assert inv.consume("arrow", 2)
    assert inv.count("arrow") == 1
    assert not inv.consume("arrow", 2)


def test_removed_equipped_item_unequips():
    inv = Inventory()
    sw = inv.add("longsword")
    inv.equip(sw.uid)
    inv.remove(sw.uid)
    assert inv.weapon() is None and not inv.equipped


# ── creation ────────────────────────────────────────────────────

@pytest.mark.parametrize("i", range(len(PREGENS)))
def test_pregens_are_valid(i):
    ch = make_pregen(i)
    assert ch.hp == ch.max_hp > 0
    assert 10 <= ch.armor_class() <= 19
    assert ch.inventory.weapon() is not None
    pub = ch.to_public()
    assert pub["name"] and pub["attacks"]


def test_fighter_numbers():
    ch = create_character(name="Test", race="human", cls="fighter")
    # standard array STR15 +1 human = 16 → +3; chain mail 16 + defense style 1 + shield 2 = 19
    assert ch.abilities["strength"] == 16
    assert ch.armor_class() == 19
    prof = ch.weapon_profile()
    assert prof["to_hit"] == 3 + 2
    assert prof["damage"] == "1d8+3"
    # fighter array puts 14 in CON, +1 human = 15 → +2; d10 + 2
    assert ch.abilities["constitution"] == 15 and ch.max_hp == 12


def test_barbarian_unarmored_defense():
    ch = create_character(name="Ug", race="half_orc", cls="barbarian")
    dex, con = ch.mod("dexterity"), ch.mod("constitution")
    assert ch.inventory.armor() is None
    assert ch.armor_class() == 10 + dex + con


def test_rogue_expertise_and_finesse():
    ch = create_character(name="Sly", race="halfling", cls="rogue")
    assert len(ch.expertise) == 2
    sk = ch.expertise[0]
    assert ch.skill_bonus(sk) == ch.mod("dexterity" if sk in ("stealth", "sleight_of_hand") else
                                         {"perception": "wisdom", "deception": "charisma",
                                          "persuasion": "charisma"}[sk]) + 2 * ch.prof
    assert ch.weapon_profile()["ability"] == "dexterity"
    assert ch.sneak_attack_dice() == "1d6"


def test_wizard_spells_and_slots():
    ch = create_character(name="Mira", race="human", cls="wizard")
    assert ch.max_spell_slots() == {1: 2}
    known = ch.known_spells()
    assert "fire_bolt" in known and "magic_missile" in known and "fireball" not in known
    assert ch.spell_dc == 8 + 2 + ch.mod("intelligence")


def test_paladin_spells_start_at_level_2():
    ch = create_character(name="Ald", race="dragonborn", cls="paladin")
    assert ch.max_spell_slots() == {} and ch.known_spells() == []


def test_point_buy_validation():
    assert point_buy_cost({"strength": 15, "dexterity": 15, "constitution": 15,
                           "intelligence": 8, "wisdom": 8, "charisma": 8}) == 27
    with pytest.raises(CreationError):
        create_character(name="X", race="human", cls="fighter", method="point_buy",
                         base_scores={"strength": 15, "dexterity": 15, "constitution": 15,
                                      "intelligence": 15, "wisdom": 8, "charisma": 8})
    with pytest.raises(CreationError):
        create_character(name="", race="human", cls="fighter")


# ── HP, death, rests, levels ────────────────────────────────────

def test_damage_drop_and_death_saves():
    ch = create_character(name="Kael", race="human", cls="fighter")
    r = ch.take_damage(ch.hp + 2)
    assert r["dropped"] and ch.hp == 0 and ch.is_down and not ch.dead
    ch.take_damage(3)
    assert ch.death_saves.failures == 1
    ch.take_damage(3, critical=True)
    assert ch.dead


def test_massive_damage_kills_outright():
    ch = create_character(name="Kael", race="human", cls="wizard")
    r = ch.take_damage(ch.hp + ch.max_hp)
    assert r["died"] and ch.dead


def test_relentless_endurance_once():
    ch = create_character(name="Dorn", race="half_orc", cls="barbarian")
    r = ch.take_damage(ch.hp + 1)
    assert r.get("relentless") and ch.hp == 1
    r = ch.take_damage(5)
    assert ch.hp == 0 and r["dropped"]


def test_heal_from_zero_resets_saves():
    ch = create_character(name="K", race="human", cls="fighter")
    ch.take_damage(ch.hp + 1)
    ch.take_damage(1)
    assert ch.heal(5) == 5 and ch.death_saves.failures == 0


def test_rage_resistance():
    ch = create_character(name="Dorn", race="human", cls="barbarian")
    ch.add_condition(Condition(id="raging", rounds=10))
    r = ch.take_damage(10, damage_type="slashing")
    assert r["taken"] == 5


def test_death_save_outcomes_cover_all():
    ch = create_character(name="K", race="human", cls="fighter")
    seen = set()
    for _ in range(300):
        ch.hp = 0
        ch.dead = False
        ch.death_saves.successes = ch.death_saves.failures = 0
        seen.add(ch.roll_death_save()["result"])
    assert {"success", "fail", "revived", "double_fail"} <= seen


def test_level_up_flow():
    ch = create_character(name="Mira", race="human", cls="wizard")
    assert not ch.gain_xp(100)
    assert ch.gain_xp(200)
    info = ch.level_up()
    assert ch.level == 2 and info["hp_gain"] >= 1
    ch.gain_xp(600)
    info = ch.level_up()
    assert ch.max_spell_slots() == {1: 4, 2: 2}
    assert "scorching_ray" in info["new_spells"]


def test_asi_at_level_4():
    ch = create_character(name="K", race="human", cls="fighter")
    ch.xp = 2700
    for _ in range(3):
        ch.level_up()
    assert ch.level == 4 and ch.abilities["strength"] == 18


def test_long_rest_restores():
    ch = create_character(name="Brenna", race="dwarf", cls="cleric")
    ch.take_damage(5)
    ch.spell_slots[1] = 0
    ch.long_rest()
    assert ch.hp == ch.effective_max_hp and ch.spell_slots[1] == 2


def test_dwarf_poison_resistance():
    ch = create_character(name="B", race="dwarf", cls="cleric")
    assert ch.take_damage(8, damage_type="poison")["taken"] == 4


def test_character_roundtrip_json():
    ch = make_pregen(1)
    again = Character.model_validate_json(ch.model_dump_json())
    assert again.to_public() == ch.to_public()
