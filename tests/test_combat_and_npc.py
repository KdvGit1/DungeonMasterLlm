"""
tests/test_combat_and_npc.py
Tests for combat system and NPC creation.
Run directly: python tests/test_combat_and_npc.py
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import json
import random


# ─── Mock Classes ──────────────────────────────────────────────────────────────

class MockEnemy:
    """Minimal mock that acts like a real enemy dict from create_encounter."""
    def __init__(self, id=0, display_name="Bandit", hp=18, max_hp=18, ac=12,
                 attack_bonus=3, damage_str="1d6+2", xp=40, abilities=None,
                 behavior=None, status_effects=None, ability_cooldowns=None, fled=False):
        self.id = id
        self.display_name = display_name
        self.hp = hp
        self.max_hp = max_hp
        self.ac = ac
        self.attack_bonus = attack_bonus
        self.damage_str = damage_str
        self.xp = xp
        self.abilities = abilities or []
        self.behavior = behavior
        self.status_effects = status_effects or []
        self.ability_cooldowns = ability_cooldowns or {}
        self.fled = fled
        self._data = {
            "id": id, "display_name": display_name, "hp": hp, "max_hp": max_hp,
            "ac": ac, "attack_bonus": attack_bonus, "damage_str": damage_str,
            "xp": xp, "abilities": self.abilities, "behavior": self.behavior,
            "status_effects": self.status_effects,
            "ability_cooldowns": self.ability_cooldowns, "fled": fled,
        }

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def items(self):
        return self._data.items()

    def __repr__(self):
        return f"MockEnemy({self.display_name}, hp={self.hp})"


class MockGameState:
    def __init__(self):
        self.active_encounter = None
        self.is_combat = False
        self.characters = []
        self.session_id = None
        self.current_scene = ""
        self.current_node = None
        self.pending_item = None
        self.player_status_effects = {}
        self.skill_cooldowns = {}

    def start_encounter(self, encounter_state):
        self.active_encounter = encounter_state
        self.is_combat = True

    def end_encounter(self):
        self.active_encounter = None
        self.is_combat = False

    def add_player_status(self, player_name, effect_type, turns_left, **extra):
        if player_name not in self.player_status_effects:
            self.player_status_effects[player_name] = []
        effect = {"type": effect_type, "turns_left": turns_left}
        effect.update(extra)
        self.player_status_effects[player_name].append(effect)

    def tick_player_statuses(self, player_name):
        effects = self.player_status_effects.get(player_name, [])
        remaining = []
        for se in effects:
            se["turns_left"] -= 1
            if se["turns_left"] > 0:
                remaining.append(se)
        self.player_status_effects[player_name] = remaining

    def is_player_stunned(self, player_name):
        for se in self.player_status_effects.get(player_name, []):
            if se["type"] == "stun" and se.get("turns_left", 0) > 0:
                return True
        return False

    def get_player_dot_damage(self, player_name):
        total = 0
        for se in self.player_status_effects.get(player_name, []):
            if se["type"] == "dot" and se.get("turns_left", 0) > 0:
                total += se.get("dot_damage", 0)
        return total

    def set_skill_cooldown(self, player_name, skill_id, cooldown_turns):
        if cooldown_turns <= 0:
            return
        if player_name not in self.skill_cooldowns:
            self.skill_cooldowns[player_name] = {}
        self.skill_cooldowns[player_name][skill_id] = cooldown_turns

    def tick_skill_cooldowns(self, player_name):
        cds = self.skill_cooldowns.get(player_name, {})
        to_remove = []
        for skill_id, remaining in cds.items():
            cds[skill_id] = remaining - 1
            if cds[skill_id] <= 0:
                to_remove.append(skill_id)
        for key in to_remove:
            del cds[key]

    def get_skill_cooldown(self, player_name, skill_id):
        return self.skill_cooldowns.get(player_name, {}).get(skill_id, 0)

    def get_all_skill_cooldowns(self, player_name):
        return dict(self.skill_cooldowns.get(player_name, {}))


# ─── Test Cases ────────────────────────────────────────────────────────────────

def test_encounter_state_to_dict():
    from game.encounter_manager import EncounterState
    enemy = MockEnemy(id=0, display_name="Goblin", hp=10, max_hp=14, ac=12)
    state = EncounterState()
    state.enemies = [enemy]
    state.turn_number = 1
    state.is_active = True
    d = state.to_dict()
    assert d["turn_number"] == 1
    assert d["is_active"] == True
    assert len(d["enemies"]) == 1
    assert d["enemies"][0]["display_name"] == "Goblin"
    assert d["enemies"][0]["hp"] == 10
    print("PASS: test_encounter_state_to_dict")


def test_create_encounter_from_data():
    from game.encounter_manager import create_encounter, EncounterState
    data = {
        "enemies": [
            {"name": "Tavern Bouncer", "type": "guard"},
            {"name": "Bandit Leader", "type": "bandit"},
        ],
        "context": "A fight breaks out at the tavern."
    }
    state = create_encounter(data)
    assert isinstance(state, EncounterState)
    assert len(state.enemies) == 2
    assert state.context == "A fight breaks out at the tavern."
    assert state.enemies[0]["display_name"] == "Tavern Bouncer"
    assert state.enemies[0]["hp"] == 20
    assert state.enemies[0]["ac"] == 13
    assert state.enemies[1]["display_name"] == "Bandit Leader"
    assert state.enemies[1]["hp"] == 18
    print("PASS: test_create_encounter_from_data")


def test_get_alive_enemies():
    from game.encounter_manager import get_alive_enemies, EncounterState
    state = EncounterState()
    state.enemies = [
        MockEnemy(id=0, display_name="Alive", hp=10),
        MockEnemy(id=1, display_name="Dead", hp=0),
        MockEnemy(id=2, display_name="Fled", hp=5, fled=True),
        MockEnemy(id=3, display_name="Also Alive", hp=8),
    ]
    alive = get_alive_enemies(state)
    assert len(alive) == 2
    assert alive[0].display_name == "Alive"
    assert alive[1].display_name == "Also Alive"
    print("PASS: test_get_alive_enemies")


def test_is_encounter_over():
    from game.encounter_manager import is_encounter_over, EncounterState
    state = EncounterState()
    state.enemies = [MockEnemy(id=0, display_name="Dead", hp=0)]
    assert is_encounter_over(state) == True

    state.enemies = [
        MockEnemy(id=0, display_name="Alive", hp=10),
        MockEnemy(id=1, display_name="Fled", hp=5, fled=True),
    ]
    assert is_encounter_over(state) == False

    state.enemies = [
        MockEnemy(id=0, display_name="Fled1", hp=3, fled=True),
        MockEnemy(id=1, display_name="Fled2", hp=3, fled=True),
    ]
    assert is_encounter_over(state) == True
    print("PASS: test_is_encounter_over")


def test_parse_encounter_block_basic():
    from game.encounter_manager import parse_encounter_block
    gm_response = """
    The guard draws his sword!
    [ENCOUNTER]
    {
        "enemies": [
            {"name": "Town Guard", "type": "guard"},
            {"name": "Corporal", "type": "guard"}
        ],
        "context": "Two guards confront the players."
    }
    [/ENCOUNTER]
    The tension in the air is palpable.
    """
    result = parse_encounter_block(gm_response)
    assert result is not None
    assert len(result["enemies"]) == 2
    assert result["context"] == "Two guards confront the players."
    assert result["enemies"][0]["name"] == "Town Guard"
    assert result["enemies"][0]["type"] == "guard"
    print("PASS: test_parse_encounter_block_basic")


def test_parse_encounter_block_string_enemies():
    from game.encounter_manager import parse_encounter_block
    gm_response = "[ENCOUNTER]\n{\"enemies\": [\"goblin\", \"wolf\"], \"context\": \"Ambush!\"}\n[/ENCOUNTER]"
    result = parse_encounter_block(gm_response)
    assert result is not None
    assert len(result["enemies"]) == 2
    assert result["enemies"][0]["name"] == "goblin"
    assert result["enemies"][0]["type"] == "goblin"
    assert result["enemies"][1]["name"] == "wolf"
    assert result["enemies"][1]["type"] == "wolf"
    print("PASS: test_parse_encounter_block_string_enemies")


def test_strip_encounter_block():
    from game.encounter_manager import strip_encounter_block
    gm_response = """
    The guard attacks!
    [ENCOUNTER]
    {"enemies": [{"name": "Guard", "type": "guard"}]}
    [/ENCOUNTER]
    The battle begins!
    """
    clean = strip_encounter_block(gm_response)
    assert "[ENCOUNTER]" not in clean
    assert "[/ENCOUNTER]" not in clean
    assert "The guard attacks!" in clean
    assert "The battle begins!" in clean
    print("PASS: test_strip_encounter_block")


def test_parse_encounter_block_max_enemies():
    from game.encounter_manager import parse_encounter_block
    from game.monster_data import MAX_ENEMIES
    enemies = [{"name": f"Enemy{i}", "type": "bandit"} for i in range(10)]
    gm_response = f"[ENCOUNTER]{json.dumps({'enemies': enemies, 'context': 'Many enemies.'})}[/ENCOUNTER]"
    result = parse_encounter_block(gm_response)
    assert result is not None
    assert len(result["enemies"]) == MAX_ENEMIES
    print(f"PASS: test_parse_encounter_block_max_enemies (capped at {MAX_ENEMIES})")


def test_player_attack_target_basic():
    from game.combat import player_attack_target
    from game.encounter_manager import create_encounter
    data = {"enemies": [{"name": "Guard", "type": "guard"}], "context": "Fight!"}
    state = create_encounter(data)
    gs = MockGameState()
    gs.start_encounter(state)
    gs.characters = [{"name": "Hero", "abilities": {"strength": 16}}]
    msg, dmg, defeated, enc_over = player_attack_target(gs, "Hero", 0, session_id=None, user={})
    assert "Guard" in msg
    assert dmg >= 0
    print(f"PASS: test_player_attack_target_basic (damage={dmg})")


def test_player_attack_target_invalid_index():
    from game.combat import player_attack_target
    from game.encounter_manager import create_encounter
    data = {
        "enemies": [
            {"name": "Goblin1", "type": "goblin"},
            {"name": "Goblin2", "type": "goblin"},
        ],
        "context": "Fight!"
    }
    state = create_encounter(data)
    gs = MockGameState()
    gs.start_encounter(state)
    gs.characters = [{"name": "Hero", "abilities": {"strength": 14}}]
    msg, dmg, defeated, enc_over = player_attack_target(gs, "Hero", 99, session_id=None, user={})
    assert "Goblin1" in msg or "Goblin2" in msg
    print("PASS: test_player_attack_target_invalid_index")


def test_player_attack_no_encounter():
    from game.combat import player_attack_target
    gs = MockGameState()
    gs.active_encounter = None
    gs.is_combat = False
    gs.characters = [{"name": "Hero", "abilities": {"strength": 14}}]
    msg, dmg, defeated, enc_over = player_attack_target(gs, "Hero", 0, session_id=None, user={})
    assert "No active encounter" in msg
    assert dmg == 0
    print("PASS: test_player_attack_no_encounter")


def test_enemy_turn_all_no_encounter():
    from game.combat import enemy_turn_all
    gs = MockGameState()
    gs.active_encounter = None
    gs.is_combat = False
    player_targets = [{"name": "Hero", "ac": 12, "hp": 30, "max_hp": 30}]
    results = enemy_turn_all(gs, player_targets, session_id=None)
    assert results == []
    print("PASS: test_enemy_turn_all_no_encounter")


def test_enemy_turn_all_inactive_encounter():
    from game.combat import enemy_turn_all
    from game.encounter_manager import create_encounter
    data = {"enemies": [{"name": "Bandit", "type": "bandit"}], "context": "Fight"}
    state = create_encounter(data)
    state.is_active = False
    gs = MockGameState()
    gs.start_encounter(state)
    player_targets = [{"name": "Hero", "ac": 12, "hp": 30, "max_hp": 30}]
    results = enemy_turn_all(gs, player_targets, session_id=None)
    assert results == []
    print("PASS: test_enemy_turn_all_inactive_encounter")


def test_enemy_turn_all_combat_flag_false():
    """When game_state.is_combat=False but encounter exists (desync), return []."""
    from game.combat import enemy_turn_all
    from game.encounter_manager import create_encounter
    data = {"enemies": [{"name": "Bandit", "type": "bandit"}], "context": "Fight"}
    state = create_encounter(data)
    state.is_active = True
    gs = MockGameState()
    gs.start_encounter(state)
    gs.is_combat = False  # Desync!
    player_targets = [{"name": "Hero", "ac": 12, "hp": 30, "max_hp": 30}]
    results = enemy_turn_all(gs, player_targets, session_id=None)
    assert results == []
    print("PASS: test_enemy_turn_all_combat_flag_false")


def test_enemy_turn_all_all_players_dead():
    from game.combat import enemy_turn_all
    from game.encounter_manager import create_encounter
    data = {"enemies": [{"name": "Bandit", "type": "bandit"}], "context": "Fight"}
    state = create_encounter(data)
    gs = MockGameState()
    gs.start_encounter(state)
    player_targets = []
    results = enemy_turn_all(gs, player_targets, session_id=None)
    assert results == []
    print("PASS: test_enemy_turn_all_all_players_dead")


def test_generate_combat_summary():
    from game.encounter_manager import generate_combat_summary, create_encounter
    data = {
        "enemies": [{"name": "Goblin", "type": "goblin"}, {"name": "Wolf", "type": "wolf"}],
        "context": ""
    }
    state = create_encounter(data)
    state.enemies[0]["hp"] = 0
    state.enemies[1]["hp"] = 0
    state.turn_number = 3
    summary = generate_combat_summary(state, dead_players=["Hero"])
    assert "Goblin" in summary
    assert "Wolf" in summary
    assert "Hero" in summary
    assert "DEAD" in summary
    print("PASS: test_generate_combat_summary")


def test_get_total_xp():
    from game.encounter_manager import get_total_xp, create_encounter
    data = {
        "enemies": [
            {"name": "Guard", "type": "guard"},
            {"name": "Bandit", "type": "bandit"},
        ],
        "context": ""
    }
    state = create_encounter(data)
    state.enemies[0]["hp"] = 0
    total = get_total_xp(state)
    assert total == 40
    print(f"PASS: test_get_total_xp (total={total})")


def test_npc_manager_save_and_get():
    from game.npc_manager import save_npc, get_all_npcs
    test_session = "__test_session_npc_001__"
    public = {"role": "Guard", "appearance": "Tall man in armor", "personality": "Stern"}
    secret = "He is secretly a spy"
    ok = save_npc("Test NPC Guard", public, secret, test_session)
    assert ok is True
    npcs = get_all_npcs(test_session)
    guard = next((n for n in npcs if n["name"] == "Test NPC Guard"), None)
    assert guard is not None
    assert guard["public"]["role"] == "Guard"
    assert guard["secret"] == "He is secretly a spy"
    print("PASS: test_npc_manager_save_and_get")


def test_npc_manager_update_existing():
    from game.npc_manager import save_npc, get_all_npcs
    test_session = "__test_session_npc_002__"
    public1 = {"role": "Merchant", "appearance": "Fat", "personality": "Greedy"}
    public2 = {"role": "Merchant", "appearance": "Fat", "personality": "Generous"}
    save_npc("Merchant Joe", public1, "Secret1", test_session)
    save_npc("Merchant Joe", public2, "Secret2", test_session)
    npcs = get_all_npcs(test_session)
    merchant = next((n for n in npcs if n["name"] == "Merchant Joe"), None)
    assert merchant is not None
    assert merchant["public"]["personality"] == "Generous"
    assert merchant["secret"] == "Secret2"
    print("PASS: test_npc_manager_update_existing")


def test_npc_summary_secret():
    from game.npc_manager import get_npc_summary_secret
    npc = {
        "name": "Silas",
        "public": {
            "role": "Innkeeper",
            "appearance": "Short, bald, jovial",
            "personality": "Cheerful and helpful"
        },
        "secret": "He is actually a retired assassin"
    }
    summary = get_npc_summary_secret(npc)
    assert "Silas" in summary
    assert "Innkeeper" in summary
    assert "retired assassin" in summary
    assert "never reveal" in summary.lower() or "SECRET" in summary
    print("PASS: test_npc_summary_secret")


def test_npc_extractor_returns_list():
    from game.npc_extractor import extract_npcs_from_response
    result = extract_npcs_from_response(
        gm_response="The guard nods and walks away.",
        recent_messages=[{"role": "assistant", "content": "A guard appears."}],
        existing_npc_names=["Guard"],
        player_names=["Hero"]
    )
    assert isinstance(result, list)
    print(f"PASS: test_npc_extractor_returns_list (got {len(result)} NPCs)")


def test_parse_damage_basic():
    from game.monster_data import parse_damage
    for _ in range(20):
        r = parse_damage("1d6+2")
        assert 3 <= r <= 8
    for _ in range(20):
        r = parse_damage("2d4")
        assert 2 <= r <= 8
    for _ in range(20):
        r = parse_damage("1d12+3")
        assert 4 <= r <= 15
    print("PASS: test_parse_damage_basic")


def test_get_monster():
    from game.monster_data import get_monster
    goblin = get_monster("goblin")
    assert goblin["hp"] == 14
    assert goblin["ac"] == 12
    assert goblin["damage_str"] == "1d6+1"
    unknown = get_monster("dragon_king_extreme")
    assert unknown["hp"] == 18
    print("PASS: test_get_monster")


def test_get_ability_effect():
    from game.monster_data import get_ability_effect
    heal = get_ability_effect("heal_ally")
    assert heal is not None
    assert heal["effect"] == "heal_lowest_ally"
    assert heal["cooldown"] == 3
    rage = get_ability_effect("rage")
    assert rage is not None
    assert rage["trigger"] == "hp_below_50"
    assert rage["bonus"] == 3
    poison = get_ability_effect("poison_attack")
    assert poison is not None
    assert poison["effect"] == "dot"
    assert poison["dot_damage"] == 3
    print("PASS: test_get_ability_effect")


def test_player_status_effects():
    gs = MockGameState()
    gs.add_player_status("Hero", "stun", 2)
    gs.add_player_status("Hero", "dot", 3, dot_damage=5)
    assert gs.is_player_stunned("Hero") == True
    gs.tick_player_statuses("Hero")
    assert gs.is_player_stunned("Hero") == True
    gs.tick_player_statuses("Hero")
    assert gs.is_player_stunned("Hero") == False
    dot_dmg = gs.get_player_dot_damage("Hero")
    assert dot_dmg == 5
    print("PASS: test_player_status_effects")


def test_skill_cooldown_system():
    gs = MockGameState()
    gs.set_skill_cooldown("Hero", "fireball", 3)
    assert gs.get_skill_cooldown("Hero", "fireball") == 3
    gs.tick_skill_cooldowns("Hero")
    assert gs.get_skill_cooldown("Hero", "fireball") == 2
    gs.tick_skill_cooldowns("Hero")
    gs.tick_skill_cooldowns("Hero")
    assert gs.get_skill_cooldown("Hero", "fireball") == 0
    all_cds = gs.get_all_skill_cooldowns("Hero")
    assert "fireball" not in all_cds
    print("PASS: test_skill_cooldown_system")


def test_encounter_event_stunned_enemy_skips_turn():
    from game.encounter_manager import enemy_turn, create_encounter
    data = {"enemies": [{"name": "Assassin", "type": "assassin"}], "context": ""}
    state = create_encounter(data)
    state.enemies[0]["status_effects"] = [{"type": "stun", "turns_left": 1}]
    player_targets = [{"name": "Hero", "ac": 10, "hp": 30, "max_hp": 30}]
    results = enemy_turn(state, player_targets)
    assert len(results) == 1
    assert "stunned" in results[0]["message"].lower() or results[0]["damage"] == 0
    assert state.enemies[0]["status_effects"] == []
    print("PASS: test_encounter_event_stunned_enemy_skips_turn")


def test_encounter_event_rage_below_half_hp():
    from game.encounter_manager import enemy_turn, create_encounter
    data = {"enemies": [{"name": "Orc Berserker", "type": "orc"}], "context": ""}
    state = create_encounter(data)
    state.enemies[0]["hp"] = 5
    player_targets = [{"name": "Hero", "ac": 10, "hp": 30, "max_hp": 30}]
    results = enemy_turn(state, player_targets)
    assert len(results) >= 1
    print(f"PASS: test_encounter_event_rage_below_half_hp")


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Combat & NPC Test Suite")
    print("=" * 60 + "\n")

    tests = [
        test_encounter_state_to_dict,
        test_create_encounter_from_data,
        test_get_alive_enemies,
        test_is_encounter_over,
        test_parse_encounter_block_basic,
        test_parse_encounter_block_string_enemies,
        test_strip_encounter_block,
        test_parse_encounter_block_max_enemies,
        test_player_attack_target_basic,
        test_player_attack_target_invalid_index,
        test_player_attack_no_encounter,
        test_enemy_turn_all_no_encounter,
        test_enemy_turn_all_inactive_encounter,
        test_enemy_turn_all_combat_flag_false,
        test_enemy_turn_all_all_players_dead,
        test_generate_combat_summary,
        test_get_total_xp,
        test_npc_manager_save_and_get,
        test_npc_manager_update_existing,
        test_npc_summary_secret,
        test_npc_extractor_returns_list,
        test_parse_damage_basic,
        test_get_monster,
        test_get_ability_effect,
        test_player_status_effects,
        test_skill_cooldown_system,
        test_encounter_event_stunned_enemy_skips_turn,
        test_encounter_event_rage_below_half_hp,
    ]

    passed = 0
    failed = 0
    errors = []

    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((t.__name__, str(e)))
            print(f"FAIL: {t.__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        for name, err in errors:
            print(f"  FAIL: {name}: {err}")
        sys.exit(1)
    else:
        print("All tests passed!")
        sys.exit(0)
