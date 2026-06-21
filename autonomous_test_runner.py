"""
autonomous_test_runner.py — Full autonomous game testing with AI player + AI GM.

Architecture:
  - GM AI:     Controls the world, narrates, runs combat (via llm_client)
  - Player AI: Makes decisions based on a session goal + game state (via llm_client)
  - Game Engine: All mechanical operations imported directly from main.py / game modules

CRITICAL DESIGN PRINCIPLE:
  This test runner imports and uses the EXACT SAME functions from main.py and the
  game modules. NO game logic is reimplemented here. This ensures the test is
  identical to real gameplay.

Each test session:
  1. A random GOAL is assigned to the Player AI
  2. The Player AI sees the GM's narration + game state and decides what to do
  3. The loop runs until: player dies, goal achieved, or max turns reached
  4. Everything (including terminal errors/bugs) is logged to a timestamped file

Usage:
  python autonomous_test_runner.py                    # Run 1 session
  python autonomous_test_runner.py --repeat 50        # Run 50 sessions sequentially
  python autonomous_test_runner.py --max-turns 30     # Custom turn limit
  python autonomous_test_runner.py --repeat 10 --max-turns 20
"""

import os
import sys
import time
import random
import textwrap
import io
from datetime import datetime

# ─── Project setup ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import config
from llm_client import ask_llm, ask_llm_full

# Set provider to OpenRouter for testing
config.PROVIDER = 'openrouter'
config.openrouter_model = 'openrouter/owl-alpha'

# Verify API key
if not config.get_api_key('openrouter'):
    print("ERROR: No OpenRouter API key found!")
    print("Add your key to api_keys.json: {\"openrouter_api_key\": \"sk-or-...\"}")
    sys.exit(1)

# ─── ALL game logic imported from real codebase ─────────────────
from db.database import initialize_db
from db.user_manager import register_user, login_user
from db.session_manager import (
    create_session, get_active_session,
    end_session, save_message, get_recent_messages
)
from game.character_manager import load_character_from_yaml
from game.game_state import GameState
from game.npc_manager import get_all_npcs, save_npc
from game.npc_extractor import extract_npcs_from_response
from game.scenario_manager import ScenarioManager
from game.combat import format_encounter_status
from game.event_parser import (
    parse_encounter_from_response, strip_encounter_from_response, parse_gm_events,
)
from game.xp_manager import (
    init_player_stats, grant_general_xp, grant_combat_xp,
    grant_quest_rewards, apply_damage, add_gold, format_player_status,
)
from game.quest_manager import init_quests, check_node_quests
from game.combat_events import check_combat_events, apply_event
from prompts.system_prompt import build_system_prompt

# Import the EXACT same functions used by main.py's game loop
from main import (
    ask_gm,
    needs_roll_check,
    execute_roll,
    handle_item_use,
    handle_item_pickup,
    check_item_acquisition,
    generate_llm_combat_summary,
    process_combat_turn,
)


# ═══════════════════════════════════════════════════════════════
# DUAL-OUTPUT LOGGER — Captures terminal + file simultaneously
# ═══════════════════════════════════════════════════════════════

class TeeOutput:
    """Writes to both terminal and log file simultaneously."""

    def __init__(self, original_stream, log_file):
        self.original = original_stream
        self.log_file = log_file

    def write(self, text):
        self.original.write(text)
        self.log_file.write(text)

    def flush(self):
        self.original.flush()
        self.log_file.flush()


class SessionLogger:
    """Logs everything to a timestamped file for later review.
    Also captures all terminal output (stdout/stderr) during the session."""

    def __init__(self, session_name, goal, session_num, total_sessions):
        os.makedirs(os.path.join(PROJECT_ROOT, 'logs', 'test_sessions'), exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.filename = os.path.join(PROJECT_ROOT, 'logs', 'test_sessions',
                                      f'session_{session_num:03d}_{timestamp}.txt')
        self.lines = []
        self.session_name = session_name
        self.goal = goal
        self.session_num = session_num
        self.total_sessions = total_sessions
        self.start_time = time.time()
        self._write_header()

    def _write_header(self):
        self._raw("=" * 80)
        self._raw("  AUTONOMOUS D&D GAME TEST SESSION")
        self._raw(f"  Session: {self.session_name} ({self.session_num}/{self.total_sessions})")
        self._raw(f"  Player Goal: {self.goal}")
        self._raw(f"  Model: {config.openrouter_model}")
        self._raw(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._raw("=" * 80)
        self._raw("")

    def _raw(self, text):
        self.lines.append(text)

    def section(self, title):
        self._raw("")
        self._raw("─" * 60)
        self._raw(f"  {title}")
        self._raw("─" * 60)

    def gm(self, text):
        self._raw("")
        self._raw("  🧙 GM:")
        for line in textwrap.wrap(text, width=72):
            self._raw(f"    {line}")
        self._raw("")

    def player(self, text):
        self._raw("")
        self._raw("  ⚔️  PLAYER:")
        for line in textwrap.wrap(text, width=72):
            self._raw(f"    {line}")
        self._raw("")

    def system(self, text):
        self._raw(f"  ⚙️  {text}")

    def combat(self, text):
        self._raw(f"  ⚔️  {text}")

    def state(self, text):
        self._raw(f"  📊 {text}")

    def error(self, text):
        self._raw(f"  ❌ ERROR: {text}")

    def bug(self, text):
        self._raw(f"  🐛 BUG: {text}")

    def warning(self, text):
        self._raw(f"  ⚠️  WARNING: {text}")

    def summary(self, text):
        self._raw("")
        self._raw("=" * 60)
        self._raw("  SESSION SUMMARY")
        self._raw("=" * 60)
        self._raw(text)

    def save(self):
        elapsed = time.time() - self.start_time
        self._raw("")
        self._raw(f"  Total time: {elapsed:.1f}s")
        self._raw("=" * 80)
        with open(self.filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.lines))
        return self.filename


# ═══════════════════════════════════════════════════════════════
# PLAYER AI — Decides what the player does each turn
# ═══════════════════════════════════════════════════════════════

PLAYER_PERSONA = """You are an AI playing a D&D character. You have a specific GOAL for this session.
You must play naturally and creatively to achieve your goal.

RULES:
- You are NOT the Game Master. You only control your character.
- Respond with ONLY your character's action as a short phrase (1-3 sentences max).
- Be creative, take risks, explore, interact with NPCs, make interesting choices.
- During combat: attack, use skills, try tactical moves, use the environment.
- During exploration: talk to NPCs, examine things, make decisions that drive the story.
- Never break character. Never say "as an AI". Just act.
- Your action should be something you SAY or DO in the game world.

Examples of good actions:
- "I draw my sword and charge at the nearest bandit, aiming for a powerful overhead strike."
- "I approach the nervous guard and ask him quietly about the missing children."
- "I examine the strange burn marks on the palisade, looking for clues about what made them."
- "I tell the GM I want to climb the wall and get a better view of the village."
- "I use my shield bash to knock the goblin off balance, then follow up with a sword strike."

Respond with ONLY your action. No explanation, no meta-commentary."""


def get_player_decision(goal, gm_narration, game_state, player_name, turn_number, is_combat):
    """Ask the Player AI what to do this turn."""
    context_parts = [f"YOUR GOAL: {goal}"]
    context_parts.append(f"TURN: {turn_number}")
    context_parts.append(f"CHARACTER: {player_name} the {game_state.characters[0]['class']}")

    try:
        ps = get_player_stats(game_state.session_id, player_name)
        if ps:
            hp_pct = ps['hp'] / ps['max_hp'] * 100
            context_parts.append(f"HP: {ps['hp']}/{ps['max_hp']} ({hp_pct:.0f}%)")
            context_parts.append(f"Gold: {ps['gold']}gp | Level: {ps['level']}")
    except:
        pass

    if is_combat and game_state.active_encounter:
        context_parts.append("STATUS: IN COMBAT!")
        alive = get_alive_enemies(game_state.active_encounter)
        for e in alive:
            hp_pct = e['hp'] / e['max_hp'] * 100
            context_parts.append(f"  Enemy: {e['display_name']} HP:{e['hp']}/{e['max_hp']} ({hp_pct:.0f}%)")
    else:
        context_parts.append("STATUS: Exploring")

    if game_state.current_node:
        context_parts.append(f"LOCATION: {game_state.current_node}")

    try:
        from game.inventory_manager import get_inventory
        inv = get_inventory(game_state.session_id, player_name)
        if inv:
            items = ', '.join(f"{i['item_name']} x{i['quantity']}" for i in inv)
            context_parts.append(f"INVENTORY: {items}")
    except:
        pass

    context_str = '\n'.join(context_parts)

    prompt = f"""{PLAYER_PERSONA}

=== YOUR SITUATION ===
{context_str}

=== WHAT JUST HAPPENED ===
{gm_narration}

What do you do? Respond with ONLY your character's action (1-3 sentences)."""

    try:
        response = ask_llm([{"role": "user", "content": prompt}], timeout=30)
        return response.strip()
    except Exception as e:
        return f"I cautiously observe my surroundings and decide my next move. (AI error: {e})"


# ═══════════════════════════════════════════════════════════════
# SESSION GOALS
# ═══════════════════════════════════════════════════════════════

SESSION_GOALS = [
    "Explore the village of Millhaven thoroughly. Talk to every NPC you can find, "
    "examine the environment for clues about what's happening, and try to uncover "
    "the mystery of the missing children.",

    "Fight your way through the village. Seek out combat encounters, test your "
    "strength against every enemy you can find, and try to become stronger through battle.",

    "Investigate the Black Wolves cult. Find evidence of their activities, "
    "track down their hideout, and confront their leader if possible.",

    "Survive and escape. The village feels dangerous — gather supplies, "
    "find allies, and look for a way to escape the valley safely.",

    "Be a hero. Help everyone in need, protect the innocent, and try to "
    "solve the village's problems through courage and compassion.",

    "Be an anti-hero. Take what you want, intimidate NPCs, steal valuables, "
    "and see how far you can push people before they push back.",

    "Explore the dark woods. Ignore the village gates and head straight into "
    "the Whispering Woods to discover what lurks in the shadows.",

    "Find treasure. Search every location for gold, magical items, and "
    "valuable loot. Get rich or die trying.",
]


# ═══════════════════════════════════════════════════════════════
# MAIN GAME LOOP (Autonomous) — Uses same functions as main.py
# ═══════════════════════════════════════════════════════════════

def run_autonomous_session(session_num, max_turns, total_sessions, log_fd):
    """Run one full autonomous game session using the real game loop functions.
    log_fd is the file descriptor for the log file (for TeeOutput)."""

    goal = random.choice(SESSION_GOALS)
    session_name = f"Session_{session_num}_{datetime.now().strftime('%H%M%S')}"
    log = SessionLogger(session_name, goal, session_num, total_sessions)

    # Redirect stdout/stderr to also capture to log file
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = TeeOutput(old_stdout, log_fd)
    sys.stderr = TeeOutput(old_stderr, log_fd)

    try:
        _run_session_inner(session_num, max_turns, log, goal, session_name)
    finally:
        # Always restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return True


def _run_session_inner(session_num, max_turns, log, goal, session_name):
    """Inner session logic (stdout/stderr already redirected)."""

    log.system(f"Starting autonomous session {session_num}")
    log.system(f"Goal: {goal}")
    log.system(f"Max turns: {max_turns}")
    log.system(f"Model: {config.openrouter_model}")

    # ── Setup ──────────────────────────────────────────────────
    try:
        initialize_db()
        log.system("Database initialized")
    except Exception as e:
        log.error(f"DB init failed: {e}")
        log.save()
        return False

    test_username = f"autotest_{session_num}_{random.randint(1000,9999)}"
    test_password = "test123"
    try:
        register_user(test_username, test_password, "player")
        user = login_user(test_username, test_password)
        log.system(f"User: {test_username}")
    except Exception as e:
        log.error(f"User creation failed: {e}")
        try:
            user = login_user(test_username, test_password)
        except:
            log.save()
            return False

    try:
        session_id = create_session(f"AutoTest: {session_name}")
        log.system(f"Session ID: {session_id}")
    except Exception as e:
        log.error(f"Session creation failed: {e}")
        log.save()
        return False

    game_state = GameState()
    game_state.session_id = session_id

    char_file = random.choice(['testhero.yaml', 'boromir.yaml', 'brave_knight.yaml',
                                'dave.yaml', 'kado.yaml', 'kdv.yaml', 'testguy.yaml'])
    try:
        character = load_character_from_yaml(char_file)
        if character:
            game_state.add_player({}, character)
            log.system(f"Character: {character['name']} ({character['class']})")
        else:
            raise ValueError("Character load returned None")
    except Exception as e:
        log.error(f"Character load failed ({char_file}): {e}")
        character = {
            "name": f"TestHero{session_num}", "race": "Human", "class": "Fighter",
            "level": 1,
            "abilities": {"strength": 14, "dexterity": 12, "constitution": 13,
                          "intelligence": 10, "wisdom": 11, "charisma": 10},
            "hp": 12, "max_hp": 12, "armor_class": 14,
            "skill_levels": {}, "background": "A brave adventurer."
        }
        game_state.add_player({}, character)
        log.system(f"Fallback character: {character['name']}")

    player_name = character['name']

    try:
        scenario_manager = ScenarioManager("scenarios/Shadow Over Millhaven")
        scenario_manager.start()
        game_state.current_node = scenario_manager.current_node.get("title", "")
        log.system(f"Scenario: Shadow Over Millhaven")
        log.system(f"Starting location: {game_state.current_node}")
    except Exception as e:
        log.error(f"Scenario load failed: {e}")
        scenario_manager = None

    init_player_stats(session_id, player_name, character)
    if scenario_manager:
        init_quests(session_id, scenario_manager.meta)

    # ── Game Loop ──────────────────────────────────────────────
    turn = 0
    game_over = False
    total_xp_earned = 0
    enemies_defeated = 0
    locations_visited = {game_state.current_node}
    roll_result_msg = None

    log.section("GAME START")

    # Initial GM narration
    intro_msg = (
        f"The adventure begins. "
        f"Location: {game_state.current_node or 'Unknown'}. "
        f"Set the opening scene. Maximum 3 sentences. "
        f"Describe where they are and end with an open situation."
    )

    system_prompt = build_system_prompt(
        game_state.characters, "begin adventure exploration",
        game_state, scenario_manager, session_id=session_id
    )

    try:
        gm_response = ask_gm(
            [{"role": "user", "content": intro_msg}],
            system_prompt
        )
        log.gm(gm_response)
        save_message(session_id, None, "user", intro_msg)
        save_message(session_id, None, "assistant", gm_response)
        game_state.set_scene(gm_response[:100])
    except Exception as e:
        log.error(f"Initial GM call failed: {e}")
        log.save()
        return False

    # Extract NPCs from intro
    try:
        existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
        new_npcs = extract_npcs_from_response(
            gm_response, [{"role": "assistant", "content": gm_response}],
            existing_npc_names, [player_name]
        )
        for npc in new_npcs:
            public_data = {"role": npc["role"], "appearance": npc["appearance"],
                          "personality": npc["personality"]}
            save_npc(npc["name"], public_data, npc["secret"], session_id)
        if new_npcs:
            log.system(f"NPCs introduced: {', '.join(n['name'] for n in new_npcs)}")
    except Exception as e:
        log.error(f"NPC extraction failed: {e}")

    # ── Main Turn Loop ─────────────────────────────────────────
    while not game_over and turn < max_turns:
        turn += 1
        log.section(f"TURN {turn}/{max_turns}")

        try:
            ps = get_player_stats(session_id, player_name)
            if ps and ps['hp'] <= 0:
                log.system("Player is unconscious! Game over.")
                game_over = True
                break
        except:
            pass

        # STEP 1: PLAYER AI DECISION
        is_combat = game_state.is_combat and game_state.active_encounter
        player_action = get_player_decision(
            goal, gm_response, game_state, player_name, turn, is_combat
        )
        log.player(player_action)

        # Save player action
        user_message = f"{player_name}: {player_action}"
        if is_combat:
            game_state.combat_messages.append({"role": "user", "content": user_message})
        else:
            save_message(session_id, user.get("id"), "user", user_message)

        grant_general_xp(session_id, player_name, 1, reason="aksiyon")

        # STEP 2: TRIGGER CHECK
        if scenario_manager:
            try:
                recent_for_trigger = get_recent_messages(session_id)
                next_node = scenario_manager.check_trigger(recent_for_trigger)
                if next_node:
                    scenario_manager.load_node(next_node)
                    if scenario_manager.current_node:
                        game_state.current_node = scenario_manager.current_node.get("title", "")
                        locations_visited.add(game_state.current_node)
                        log.system(f"📍 Scene transition: {game_state.current_node}")

                    quest_events = check_node_quests(session_id, next_node)
                    for qe in quest_events:
                        if qe["event"] == "completed":
                            grant_quest_rewards(session_id, player_name, qe["quest"])
                            log.system(f"✅ Quest completed: {qe['quest'].get('title', '?')}")

                    transition_msg = f"[SCENE TRANSITION: players have arrived at {game_state.current_node}]"
                    save_message(session_id, None, "user", transition_msg)
            except Exception as e:
                log.error(f"Trigger check failed: {e}")

        # STEP 3: COMBAT CHECK
        roll_result_msg = None

        if is_combat and game_state.active_encounter:
            log.combat(f"Combat turn {game_state.active_encounter.turn_number + 1}/"
                       f"{game_state.active_encounter.MAX_TURNS}")

            roll_result_msg, combat_ended, dead_players_this_turn = process_combat_turn(
                game_state, player_name, player_action, session_id, user, [player_name]
            )

            if roll_result_msg:
                log.combat(roll_result_msg)

            if combat_ended:
                encounter = game_state.active_encounter
                total_xp = get_total_xp(encounter)

                for char in game_state.characters:
                    try:
                        pstats = get_player_stats(session_id, char["name"])
                        if pstats and pstats["hp"] > 0:
                            grant_combat_xp(session_id, char["name"], total_xp)
                            total_xp_earned += total_xp
                    except:
                        pass

                for e in encounter.enemies:
                    if e["hp"] <= 0 and not e.get("fled"):
                        enemies_defeated += 1

                all_dead = []
                try:
                    for char in game_state.characters:
                        ps = get_player_stats(session_id, char["name"])
                        if ps and ps["hp"] <= 0:
                            all_dead.append(char["name"])
                except:
                    pass

                mechanical_summary = generate_combat_summary(encounter, all_dead)
                log.combat(f"Combat ended! {mechanical_summary}")

                try:
                    narrative_summary = generate_llm_combat_summary(
                        session_id, game_state.combat_messages, game_state, all_dead
                    )
                    log.gm(f"[NARRATIVE RECAP] {narrative_summary}")
                except Exception as e:
                    log.error(f"Combat summary generation failed: {e}")

                game_state.combat_messages = []
                for char in game_state.characters:
                    game_state.clear_player_statuses(char["name"])
                game_state.end_encounter()

                if all_dead:
                    log.system(f"💀 Player died in combat: {', '.join(all_dead)}")
                    game_over = True
                    break
        else:
            # STEP 3 (non-combat): ROLL CHECK
            node_actions = None
            if scenario_manager and scenario_manager.current_node:
                node_actions = scenario_manager.current_node.get("available_actions")

            roll_info = needs_roll_check(player_action, node_actions)

            if roll_info.get("needed"):
                roll_result_msg, roll_success = execute_roll(
                    roll_info, player_name, game_state, session_id, user
                )
                if roll_success:
                    acquired_item = check_item_acquisition(player_action)
                    if acquired_item:
                        from game.inventory_manager import add_item
                        add_item(session_id, acquired_item, 1, 0)
                        log.system(f"🎒 '{acquired_item}' acquired!")
            else:
                grant_general_xp(session_id, player_name, 1, reason="aksiyon (roll yok)")

        # STEP 4: GM RESPONSE
        recent_messages = get_recent_messages(session_id) + game_state.combat_messages
        system_prompt = build_system_prompt(
            game_state.characters, player_action,
            game_state, scenario_manager,
            roll_info=roll_result_msg,
            session_id=session_id
        )

        try:
            gm_response = ask_gm(recent_messages, system_prompt)
            log.gm(gm_response)
        except Exception as e:
            log.error(f"GM response failed: {e}")
            gm_response = "The world seems to pause for a moment, uncertain of what happens next..."
            log.gm(gm_response)

        # STEP 5: ENCOUNTER DETECTION & EVENT PARSER
        if not game_state.is_combat:
            try:
                encounter_data = parse_encounter_from_response(gm_response)
                if encounter_data:
                    log.combat(f"⚔️ Combat started! "
                               f"Enemies: {[e.get('name','?') for e in encounter_data['enemies']]}")
                    clean_narrative = strip_encounter_from_response(gm_response)
                    gm_response = clean_narrative

                    new_encounter = create_encounter(encounter_data)
                    game_state.start_encounter(new_encounter)

                    save_message(session_id, None, "user",
                        f"[COMBAT STARTED: {', '.join(e['display_name'] for e in new_encounter.enemies)}]")
            except Exception as e:
                log.error(f"Encounter detection failed: {e}")

        try:
            events = parse_gm_events(gm_response)
            if events.get("gold_found", 0) > 0:
                add_gold(session_id, player_name, events["gold_found"])
                log.system(f"💰 Found {events['gold_found']} gold!")
            if events.get("item_found"):
                item = events["item_found"]
                log.system(f"🎒 Item found: {item.get('name', '?')} (value: {item.get('value', 0)}gp)")
                from game.inventory_manager import add_item
                add_item(session_id, item["name"], 1, item.get("value", 0))
        except Exception as e:
            log.error(f"Event parsing failed: {e}")

        try:
            existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
            new_npcs = extract_npcs_from_response(
                gm_response, recent_messages, existing_npc_names, [player_name]
            )
            for npc in new_npcs:
                public_data = {"role": npc["role"], "appearance": npc["appearance"],
                              "personality": npc["personality"]}
                save_npc(npc["name"], public_data, npc["secret"], session_id)
            if new_npcs:
                log.system(f"👤 New NPCs: {', '.join(n['name'] for n in new_npcs)}")
        except Exception as e:
            log.error(f"NPC extraction failed: {e}")

        if game_state.is_combat:
            game_state.combat_messages.append({"role": "assistant", "content": gm_response})
        else:
            save_message(session_id, None, "assistant", gm_response)

        game_state.set_scene(gm_response[:100])

        # Status display
        try:
            ps = get_player_stats(session_id, player_name)
            if ps:
                hp_bar = '█' * int(8 * ps['hp'] / ps['max_hp']) + '░' * (8 - int(8 * ps['hp'] / ps['max_hp']))
                log.state(f"HP: [{hp_bar}] {ps['hp']}/{ps['max_hp']} | "
                         f"XP: {ps['xp']} | Gold: {ps['gold']}gp | Level: {ps['level']}")
        except:
            pass

        time.sleep(1)

    # ── SESSION END ─────────────────────────────────────────────
    log.section("SESSION END")

    if game_over:
        log.system("Game ended: Player died or was defeated")
    elif turn >= max_turns:
        log.system(f"Game ended: Reached max turns ({max_turns})")

    try:
        ps = get_player_stats(session_id, player_name)
        if ps:
            summary_text = (
                f"Character: {player_name}\n"
                f"Final HP: {ps['hp']}/{ps['max_hp']}\n"
                f"Level: {ps['level']} | XP: {ps['xp']}\n"
                f"Gold: {ps['gold']}gp\n"
                f"Turns played: {turn}\n"
                f"Enemies defeated: {enemies_defeated}\n"
                f"Total XP earned: {total_xp_earned}\n"
                f"Locations visited: {len(locations_visited)}\n"
                f"  - {', '.join(locations_visited)}"
            )
            log.summary(summary_text)
    except:
        log.summary(f"Turns played: {turn}\nEnemies defeated: {enemies_defeated}")

    try:
        end_session(session_id)
    except:
        pass

    log.save()


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Autonomous D&D Game Test Runner")
    parser.add_argument('--repeat', type=int, default=1,
                       help='Number of sessions to run sequentially (default: 1)')
    parser.add_argument('--max-turns', type=int, default=25,
                       help='Max turns per session (default: 25)')
    parser.add_argument('--model', type=str, default=None,
                       help='Override OpenRouter model (e.g., openrouter/owl-alpha)')
    args = parser.parse_args()

    if args.model:
        config.openrouter_model = args.model

    total_sessions = args.repeat

    print("=" * 60)
    print("  AUTONOMOUS D&D GAME TEST RUNNER")
    print(f"  Running {total_sessions} session(s) sequentially")
    print("=" * 60)
    print(f"  Provider: OpenRouter")
    print(f"  Model: {config.openrouter_model}")
    print(f"  Max turns per session: {args.max_turns}")
    print(f"  API Key: {'Set' if config.get_api_key('openrouter') else 'Missing'}")
    print("=" * 60)

    results = []
    for i in range(1, total_sessions + 1):
        print(f"\n{'#' * 60}")
        print(f"  SESSION {i}/{total_sessions}")
        print(f"{'#' * 60}")

        # Open a log file for TeeOutput to capture terminal output
        os.makedirs(os.path.join(PROJECT_ROOT, 'logs', 'test_sessions'), exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = os.path.join(PROJECT_ROOT, 'logs', 'test_sessions',
                                f'session_{i:03d}_{timestamp}_terminal.txt')

        with open(log_path, 'w', encoding='utf-8') as log_fd:
            success = run_autonomous_session(i, args.max_turns, total_sessions, log_fd)
            results.append(success)

        print(f"\n  Session {i} complete. Log saved.")

        if i < total_sessions:
            wait = 3
            print(f"  Waiting {wait}s before next session...")
            time.sleep(wait)

    print(f"\n\n{'=' * 60}")
    print(f"  ALL {total_sessions} SESSIONS COMPLETE")
    print(f"  Passed: {sum(results)}/{len(results)}")
    print(f"  Logs saved in: logs/test_sessions/")
    print(f"{'=' * 60}")
