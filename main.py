import os
import re
import time
import json
from db.database import initialize_db
from db.user_manager import register_user, login_user
from db.session_manager import (
    create_session, get_active_session,
    end_session, save_message, get_recent_messages
)
from game.character_manager import load_character_from_yaml
from game.game_state import GameState
from game.dice import d20, get_modifier
from game.npc_manager import get_all_npcs, save_npc
from game.npc_extractor import extract_npcs_from_response
from game.scenario_manager import ScenarioManager
from game.combat import player_attack, enemy_attack, format_encounter_status
from game.encounter_manager import (
    parse_encounter_block, strip_encounter_block, create_encounter,
    get_alive_enemies, is_encounter_over, get_total_xp, generate_combat_summary,
    is_combat_finished, enemy_turn
)
from game.event_parser import parse_encounter_from_response, strip_encounter_from_response
from game.inventory_manager import use_item, add_item, display_inventory
from game.xp_manager import (
    init_player_stats, grant_general_xp, grant_ability_xp,
    grant_combat_xp, grant_quest_rewards, apply_damage, add_gold, format_player_status
)
from game.quest_manager import init_quests, check_node_quests
from game.event_parser import parse_gm_events
from prompts.system_prompt import build_system_prompt
from rag.retriever import get_relevant_rules
from rag.ingest import ingest
from game.character_creator import create_character
from llm_client import ask_llm_full, ask_llm, stream_llm
import requests
import config

# ─── LLM CLIENT (shared via llm_client.py) ───────────────────────────────────
# ask_gm is now a thin wrapper around ask_llm_full for CLI display

def ask_gm(messages, system_prompt):
    """Send a streaming GM request. Uses llm_client (Ollama or OpenRouter)."""
    return ask_llm_full(messages, system_prompt)

# ─── ZAR GEREKLİ Mİ? ─────────────────────────────────────────────────────────

def needs_roll_check(action, node_available_actions=None):
    print("\n" + "─" * 40)
    print(f"🎯 DEBUG needs_roll_check")
    print(f"   Eylem: '{action}'")

    examples = get_relevant_rules(f"dice roll ability check required: {action}")
    if not examples:
        examples = "No examples found."
    print(f"   RAG sonucu (ilk 200 kr): {str(examples)[:200]}")

    node_context = ""
    if node_available_actions:
        node_context = f"\nSCENE SPECIFIC ACTIONS (use these DCs if action matches):\n{node_available_actions}"
        print(f"   Node actions mevcut: EVET")
    else:
        print(f"   Node actions mevcut: HAYIR")

    prompt = f"""You are a D&D rules judge. Decide if this player action requires a dice roll.

PLAYER ACTION: "{action}"

DICE ROLL REFERENCE:
{examples}
{node_context}

Rules:
- Uncertain outcomes (persuading, sneaking, investigating, attacking, jumping, lying) → need a roll
- Certain outcomes (talking normally, walking, entering a room, looking around casually) → no roll

Respond with ONLY valid JSON, no explanation, no markdown:
If roll needed: {{"needed": true, "ability": "charisma", "dc": 12}}
If no roll:     {{"needed": false}}"""

    try:
        response = ask_llm([{"role": "user", "content": prompt}])
        answer = response.strip()
        print(f"   AI ham cevap: '{answer}'")
        answer = re.sub(r'```json|```', '', answer).strip()
        match = re.search(r'\{.*?\}', answer, re.DOTALL)
        if match:
            answer = match.group(0)
            print(f"   JSON parse edildi: '{answer}'")
        else:
            print(f"   ⚠️  JSON bulunamadı, roll yok sayılıyor")
            return {"needed": False}

        data = json.loads(answer)
        if data.get("needed"):
            result_info = {
                "needed": True,
                "ability": data.get("ability", "strength").lower(),
                "dc": int(data.get("dc", 12))
            }
            print(f"   ✅ Roll GEREKLİ → {result_info}")
            return result_info

        print(f"   ⏭️  Roll GEREKMİYOR")
        return {"needed": False}

    except Exception as e:
        print(f"   ❌ needs_roll_check HATA: {e}")
        return {"needed": False}
    finally:
        print("─" * 40)

# ─── ZAR AT ──────────────────────────────────────────────────────────────────

def execute_roll(roll_info, player_name, game_state, session_id, user):
    ability = roll_info["ability"]
    dc = roll_info["dc"]

    ability_map = {
        "dex": "dexterity", "str": "strength", "con": "constitution",
        "wis": "wisdom", "int": "intelligence", "cha": "charisma"
    }
    ability = ability_map.get(ability, ability)

    print(f"\nDEBUG execute_roll: ability={ability}, dc={dc}")

    char = game_state.characters[0]
    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    print(f"DEBUG execute_roll: karakter={char.get('name')}, score={score}, modifier={modifier}")

    roll_result = d20()
    total = roll_result + modifier

    print("\n" + "─" * 50)
    print(f"🎲 {ability.capitalize()} check vs DC {dc}")
    print(f"   Zar: {roll_result} | Modifier: {modifier:+d} | Toplam: {total} | DC: {dc}")

    success = False
    if roll_result == 20:
        outcome_label = "CRITICAL SUCCESS"
        success = True
        print("   ⭐ KRİTİK BAŞARI!")
    elif roll_result == 1:
        outcome_label = "CRITICAL FAILURE"
        print("   💀 KRİTİK BAŞARISIZLIK!")
    elif total >= dc:
        outcome_label = "SUCCESS"
        success = True
        print("   ✅ BAŞARILI")
    else:
        outcome_label = "FAILURE"
        print("   ❌ BAŞARISIZ")

    if success:
        grant_ability_xp(session_id, player_name, ability, amount=5)

    grant_general_xp(session_id, player_name, 2, reason="roll yapıldı")

    roll_message = (
        f"Player: {player_name}\n"
        f"Action required: {ability} check vs DC {dc}\n"
        f"Roll: {roll_result} + {modifier} (modifier) = {total}\n"
        f"Result: {outcome_label}"
    )

    db_message = (
        f"{player_name} rolled {ability}: "
        f"{roll_result} + {modifier} = {total} vs DC {dc} ({outcome_label})"
    )
    if game_state.is_combat:
        game_state.combat_messages.append({"role": "user", "content": db_message})
    else:
        save_message(session_id, user.get("id"), "user", db_message)
    print(f"\nDEBUG execute_roll → GM'e gidecek mesaj:\n{roll_message}")
    return roll_message, success

# ─── EŞYA ALMA ───────────────────────────────────────────────────────────────

def handle_item_pickup(game_state, player_name, session_id, user):
    item = game_state.pending_item
    if not item:
        return None

    print(f"\n🎒 EŞYA BULUNDU: {item['name']} (value: {item.get('value', 0)}gp)")
    choice = input(f"Almak ister misin? (e/h): ").strip().lower()

    if choice != "e":
        game_state.pending_item = None
        return f"{player_name} decides to leave the {item['name']} behind."

    roll_info = {"ability": "dexterity", "dc": 10}
    roll_msg, success = execute_roll(roll_info, player_name, game_state, session_id, user)

    if success:
        add_item(session_id, item["name"], 1, item.get("value", 0))
        result_msg = f"{player_name} successfully picks up the {item['name']}!"
        print(f"   ✅ {item['name']} envantere eklendi!")
    else:
        result_msg = f"{player_name} fumbles and fails to grab the {item['name']}."
        print(f"   ❌ {item['name']} alınamadı.")

    game_state.pending_item = None
    return result_msg

# ─── BAŞARILI ROLL SONRASI EŞYA EDİNME ──────────────────────────────────────
# Item acquisition is now handled entirely by LLM via parse_gm_events().
# The old keyword-based check_item_acquisition was removed because it
# produced false positives (e.g. "Grik'i hedf" matched as an item name).
# LLM does a much better job at determining whether the player actually
# picked up an item vs just performing a combat action.

# ─── EŞYA KULLANMA ───────────────────────────────────────────────────────────

def handle_item_use(action, player_name, session_id, game_state):
    match_en = re.search(r'\buse\b\s+(?:my\s+|the\s+)?(.+)', action, re.IGNORECASE)
    match_tr = re.search(r'(.+?)\s*(?:kullan|kullanıyorum|kullandım)', action, re.IGNORECASE)

    item_name = None
    if match_en:
        item_name = match_en.group(1).strip().rstrip('.')
    elif match_tr:
        item_name = match_tr.group(1).strip().lstrip('I').strip()

    if not item_name:
        return False, None

    success, msg = use_item(session_id, item_name)
    print(f"\n🎒 EŞYA KULLANIMI: '{item_name}' → {msg}")

    if success:
        grant_general_xp(session_id, player_name, 1, reason="eşya kullanıldı")
        return True, f"{player_name} uses {item_name}."
    else:
        print(msg)
        return False, None

# ─── GİRİŞ EKRANI ────────────────────────────────────────────────────────────

def login_screen():
    print("\n⚔️  DUNGEON MASTER AI  ⚔️")
    print("─" * 30)
    print("1. Giriş yap")
    print("2. Kayıt ol")
    choice = input("\nSeçim: ").strip()

    username = input("Kullanıcı adı: ").strip()
    password = input("Şifre: ").strip()

    if choice == "2":
        user = register_user(username, password, "player")
        if not user:
            print("Kayıt başarısız.")
            return None
        return login_user(username, password)
    else:
        return login_user(username, password)

# ─── KARAKTER YÜKLE ──────────────────────────────────────────────────────────

def load_player_characters(game_state):
    os.makedirs(config.character_dir, exist_ok=True)
    files = [f for f in os.listdir(config.character_dir) if f.endswith('.yaml')]

    while True:
        print("\n🧙 KARAKTER YÜKLE")
        print("─" * 30)
        print("1. Yeni karakter oluştur")

        if files:
            print("2. Mevcut karakter yükle")
            choice = input("\nSeçim (1/2): ").strip()
        else:
            print("  (Kayıtlı karakter yok)")
            choice = "1"

        if choice == "1":
            character = create_character()
            if character:
                game_state.add_player({}, character)
                return character

        elif choice == "2":
            print("\nKarakter dosyaları:")
            for i, f in enumerate(files, 1):
                print(f"  {i}. {f}")

            selected = input("Numara veya dosya adı: ").strip()
            if not selected:
                continue

            if selected.isdigit():
                idx = int(selected) - 1
                if 0 <= idx < len(files):
                    selected = files[idx]
                else:
                    print("⚠️  Geçersiz numara.")
                    continue

            if not selected.endswith('.yaml'):
                selected += '.yaml'

            character = load_character_from_yaml(selected)
            if character:
                game_state.add_player({}, character)
                print(f"✅ {character['name']} oyuna katıldı!")
                another = input("Başka karakter eklemek ister misin? (e/h): ").strip().lower()
                if another == "e":
                    files = [f for f in os.listdir(config.character_dir) if f.endswith('.yaml')]
                    continue
                return character
            else:
                print("⚠️  Karakter yüklenemedi.")
                continue
        else:
            print("⚠️  Geçersiz seçim.")
            continue

# ─── SENARYO SEÇ ─────────────────────────────────────────────────────────────

def select_scenario():
    print("\n📖 SENARYO")
    print("─" * 30)
    choice = input("Bir senaryo takip etmek istiyor musun? (e/h): ").strip().lower()

    if choice != "e":
        print("ℹ️  Serbest mod — hayal gücüne bırakıldı.")
        return None

    scenarios_root = "scenarios"
    if not os.path.exists(scenarios_root):
        print("⚠️  'scenarios/' klasörü bulunamadı, serbest mod.")
        return None

    found = []
    for entry in sorted(os.listdir(scenarios_root)):
        entry_path = os.path.join(scenarios_root, entry)
        meta_path = os.path.join(entry_path, "scenario.yaml")
        if os.path.isdir(entry_path) and os.path.exists(meta_path):
            try:
                import yaml
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f)
                title = meta.get("title", entry)
                description = meta.get("description", "")
            except Exception:
                title = entry
                description = ""
            found.append({"path": entry_path, "title": title, "description": description})

    if not found:
        print("⚠️  Hiç senaryo bulunamadı, serbest mod.")
        return None

    print("\nMevcut senaryolar:")
    for i, s in enumerate(found, 1):
        desc_short = s["description"][:60] + "..." if len(s["description"]) > 60 else s["description"]
        print(f"  {i}. {s['title']}")
        if desc_short:
            print(f"     {desc_short}")

    while True:
        selected = input("\nNumara ile seçin: ").strip()
        if selected.isdigit():
            idx = int(selected) - 1
            if 0 <= idx < len(found):
                chosen = found[idx]
                break
        print("⚠️  Geçersiz seçim.")

    try:
        sm = ScenarioManager(chosen["path"])
        sm.start()
        print(f"✅ Senaryo yüklendi: {chosen['title']}")
        return sm
    except Exception as e:
        print(f"⚠️  Senaryo yüklenirken hata: {e}")
        return None

def generate_llm_combat_summary(session_id, combat_messages, game_state, dead_players=None):
    print(f"🐞 DEBUG [Combat/CLI]: generate_llm_combat_summary called with {len(combat_messages)} messages")
    dead_players = dead_players or []
    prompt = (
        "Summarize the following combat encounter in a short, narrative, and engaging paragraph. "
        "The summary should read like a story, describing the flow of battle, who did what, and how it ended. "
        "Focus on the narrative, not mechanical numbers.\n\n"
        "Combat Log:\n"
    )
    for msg in combat_messages:
        role = "Player" if msg["role"] == "user" else "Game Master"
        prompt += f"{role}: {msg['content']}\n"

    if dead_players:
        prompt += f"\nNote: The following players died or fell unconscious during the battle: {', '.join(dead_players)}. Incorporate this tragedy into the narrative."

    summary = ask_llm([{"role": "user", "content": "Please summarize the combat."}], prompt)
    print(f"🐞 DEBUG [Combat/CLI]: NARRATIVE SUMMARY GENERATED:\n{summary}\n")
    return summary

# ─── COMBAT TURN PROCESSOR ───────────────────────────────────────────────────
# This is the core combat engine for CLI. It processes ONE full round of combat:
# player action → enemy response → check termination → repeat.

def process_combat_turn(game_state, player_name, action, session_id, user, player_names_list):
    """
    Process a single combat turn for one player.
    Returns: (roll_result_msg, combat_ended, dead_players_this_turn)
    """
    roll_result_msg = None
    dead_players_this_turn = []

    encounter = game_state.active_encounter
    if not encounter or not encounter.is_active:
        return None, True, []

    # Increment turn counter
    encounter.turn_number += 1
    print(f"\n⚔️  COMBAT TURN {encounter.turn_number}/{encounter.MAX_TURNS}")
    print(format_encounter_status(game_state))

    # ── CHECK STUCK COMBAT ──
    # If no damage has been dealt for too many turns, force resolution
    if encounter.turn_number > encounter._last_damage_turn + encounter.STUCK_COMBAT_THRESHOLD:
        print(f"🐞 DEBUG [Combat]: Stuck combat detected! No damage for {encounter.STUCK_COMBAT_THRESHOLD} turns. Forcing resolution.")
        # Enemies lose interest and flee
        for e in get_alive_enemies(encounter):
            e["fled"] = True
        encounter.last_significant_event = "The enemies, seeing no progress, retreat into the shadows."
        roll_result_msg = "⚡ COMBAT RESOLVED: The enemies break off their attack and flee! (Stuck combat auto-resolution)"
        return roll_result_msg, True, []

    # ── CHECK IF PLAYER IS TRYING TO FLEE ──
    action_lower = action.lower().strip()
    flee_keywords = ["flee", "run away", "escape", "retreat", "kaç", "kaçış", "sığın"]
    is_fleeing = any(kw in action_lower for kw in flee_keywords)

    if is_fleeing:
        # Flee attempt: roll d20 + dexterity modifier vs DC 12
        char = next((c for c in game_state.characters if c['name'] == player_name), None)
        if not char:
            char = game_state.characters[0] if game_state.characters else {"abilities": {}}
        dex_score = char.get("abilities", {}).get("dexterity", 10)
        dex_mod = (dex_score - 10) // 2
        flee_roll = d20()
        flee_total = flee_roll + dex_mod
        flee_dc = 12

        print(f"\n🏃 FLEE ATTEMPT: d20({flee_roll}) + {dex_mod} (DEX) = {flee_total} vs DC {flee_dc}")

        if flee_roll == 20 or flee_total >= flee_dc:
            # Successful flee
            encounter.player_fled = True
            roll_result_msg = f"🏃 {player_name} successfully flees from combat! (Roll: {flee_roll}+{dex_mod}={flee_total} vs DC {flee_dc})"
            print(f"   ✅ FLEE SUCCESSFUL")
            return roll_result_msg, True, []
        else:
            # Failed flee — player loses their action this turn
            roll_result_msg = f"🏃 {player_name} tries to flee but fails! (Roll: {flee_roll}+{dex_mod}={flee_total} vs DC {flee_dc}) The enemies block the escape route!"
            print(f"   ❌ FLEE FAILED")
            # Continue to enemy turn (player wasted their action)

            # Enemy turn
            player_targets = _build_player_targets(game_state, session_id, user)
            if player_targets:
                enemy_results = enemy_turn(encounter, player_targets, session_id)
                for er in enemy_results:
                    if er["damage"] > 0 and er.get("target_player"):
                        is_down, new_hp = apply_damage(session_id, er["target_player"], er["damage"])
                        encounter.total_damage_dealt_to_players += er["damage"]
                        record_damage(encounter)
                        roll_result_msg += f"\n{er['message']}"
                        if is_down:
                            roll_result_msg += f"\n{er['target_player']} has fallen unconscious!"
                            dead_players_this_turn.append(er["target_player"])

            # Check termination
            combat_finished, reason = is_combat_finished(encounter, player_targets)
            if combat_finished:
                return roll_result_msg, True, dead_players_this_turn
            return roll_result_msg, False, dead_players_this_turn

    # ── PLAYER ATTACK ──
    alive_enemies = get_alive_enemies(encounter)
    if not alive_enemies:
        return None, True, []

    attack_msg, damage, enemy_defeated = player_attack(game_state, player_name, session_id, user)
    roll_result_msg = attack_msg

    if damage > 0:
        encounter.total_damage_dealt_to_enemies += damage
        record_damage(encounter)

    # Check if ALL enemies are defeated after player attack
    if is_encounter_over(encounter):
        print(f"🐞 DEBUG [Combat/CLI]: All enemies defeated!")
        return roll_result_msg, True, []

    # ── ENEMY TURN ──
    player_targets = _build_player_targets(game_state, session_id, user)

    enemy_results = enemy_turn(encounter, player_targets, session_id)

    # Apply enemy damage to players
    for er in enemy_results:
        if er["damage"] > 0 and er.get("target_player"):
            is_down, new_hp = apply_damage(session_id, er["target_player"], er["damage"])
            encounter.total_damage_dealt_to_players += er["damage"]
            record_damage(encounter)
            roll_result_msg += f"\n{er['message']}"
            if is_down:
                roll_result_msg += f"\n{er['target_player']} has fallen unconscious!"
                dead_players_this_turn.append(er["target_player"])
                print(f"   💀 {er['target_player']} bilinci kaybetti!")

    # ── COMBAT EVENTS (dynamic mid-combat events) ──
    from game.combat_events import check_combat_events, apply_event
    player_stats_list = []
    try:
        from game.xp_manager import get_player_stats
        for char in game_state.characters:
            ps = get_player_stats(session_id, char["name"])
            if ps:
                player_stats_list.append({"name": char["name"], "hp": ps["hp"], "max_hp": ps["max_hp"]})
    except:
        pass

    events_triggered = check_combat_events(encounter, encounter.turn_number, player_stats_list)
    for evt in events_triggered:
        evt_msg = apply_event(encounter, evt, player_stats_list)
        if evt_msg:
            roll_result_msg += f"\n⚡ {evt_msg}"
            encounter.last_significant_event = evt_msg
            if evt["effect"] == "add_ally":
                from game.xp_manager import heal
                for char in game_state.characters:
                    heal(session_id, char["name"], evt.get("ally_heal", 5))
            if evt["effect"] == "aoe_damage":
                aoe_dmg = evt.get("aoe_damage", 4)
                for char in game_state.characters:
                    aoe_result = apply_damage(session_id, char["name"], aoe_dmg)
                    record_damage(encounter)

    # ── STATUS EFFECT TICKS ──
    for char in game_state.characters:
        game_state.tick_player_statuses(char["name"])
        game_state.tick_skill_cooldowns(char["name"])
        dot_dmg = game_state.get_player_dot_damage(char["name"])
        if dot_dmg > 0:
            is_down, _ = apply_damage(session_id, char["name"], dot_dmg)
            record_damage(encounter)
            roll_result_msg += f"\n☠️ Poison deals {dot_dmg} damage to {char['name']}!"
            if is_down:
                roll_result_msg += f"\n{char['name']} has fallen unconscious from poison!"
                if char["name"] not in dead_players_this_turn:
                    dead_players_this_turn.append(char["name"])

    # ── CHECK COMBAT TERMINATION ──
    combat_finished, reason = is_combat_finished(encounter, player_targets)
    if combat_finished:
        print(f"🐞 DEBUG [Combat/CLI]: Combat finished! Reason: {reason}")
        return roll_result_msg, True, dead_players_this_turn

    return roll_result_msg, False, dead_players_this_turn


def _build_player_targets(game_state, session_id, user):
    """Build player target list for enemy attacks. Shared helper."""
    player_targets = []
    for char in game_state.characters:
        pstats = None
        try:
            from game.xp_manager import get_player_stats
            pstats = get_player_stats(session_id, char["name"])
        except:
            pass
        hp = pstats["hp"] if pstats else char.get("hp", 10)
        max_hp = pstats["max_hp"] if pstats else char.get("max_hp", 10)
        player_targets.append({
            "name": char["name"],
            "ac": char.get("armor_class", 12),
            "hp": hp,
            "max_hp": max_hp,
        })
    return player_targets


# ─── ANA OYUN DÖNGÜSÜ ────────────────────────────────────────────────────────

def game_loop(user, session_id, game_state, scenario_manager):
    print("\n🎲 Macera başlıyor...\n")
    print("─" * 50)

    valid_names = [c['name'].lower() for c in game_state.characters]
    names_display = ", ".join([c['name'] for c in game_state.characters])
    player_names_list = [c['name'] for c in game_state.characters]

    for char in game_state.characters:
        init_player_stats(session_id, char["name"], char)

    if scenario_manager:
        init_quests(session_id, scenario_manager.meta)

    if scenario_manager and scenario_manager.current_node:
        node = scenario_manager.current_node
        intro_message = (
            f"The adventure begins. "
            f"Location: {node.get('title', 'Unknown')}. "
            f"Set the opening scene. Maximum 3 sentences."
        )
    else:
        intro_message = (
            "The players have just begun their adventure. "
            "Set the scene. Maximum 3 sentences. "
            "Describe where they are and end with an open situation."
        )

    system_prompt = build_system_prompt(
        game_state.characters, "begin adventure exploration",
        game_state, scenario_manager, session_id=session_id
    )

    print("\n" + "═" * 50)
    print("🔍 DEBUG — SYSTEM PROMPT (ilk 800 karakter)")
    print("═" * 50)
    print(system_prompt[:800])
    print("═" * 50 + "\n")

    npcs = get_all_npcs(session_id)
    print(f"🔍 DEBUG — BAŞLANGIÇ NPC'LERİ ({len(npcs)} adet):")
    if npcs:
        for npc in npcs:
            print(f"   • {npc['name']} | {npc['public'].get('role','?')}")
    else:
        print("   (henüz NPC yok)")
    print()

    print("⏳ GM başlangıç sahnesini hazırlıyor...\n")
    gm_intro = ask_gm(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )

    existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(
        gm_intro, [{"role": "assistant", "content": gm_intro}],
        existing_npc_names, player_names_list
    )
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    game_state.set_scene(gm_intro[:100])
    if scenario_manager and scenario_manager.current_node:
        game_state.current_node = scenario_manager.current_node.get("title", "")

    print("\n" + "─" * 50)
    save_message(session_id, None, "user", intro_message)
    save_message(session_id, None, "assistant", gm_intro)

    for char in game_state.characters:
        print(format_player_status(session_id, char["name"]))

    while True:

        # ── Karakter adı ──
        while True:
            print(f"\nAktif karakterler: {names_display}")
            player_name = input("Karakter adı (veya 'quit' / 'inventory'): ").strip()

            if player_name.lower() == "quit":
                return

            if player_name.lower() in ("inventory", "envanter", "i"):
                display_inventory(session_id)
                continue

            if not player_name:
                print("⚠️  Karakter adı boş olamaz.")
                continue

            if player_name.lower() in valid_names:
                player_name = next(
                    c['name'] for c in game_state.characters
                    if c['name'].lower() == player_name.lower()
                )
                break
            else:
                print(f"⚠️  '{player_name}' bulunamadı. Geçerli: {names_display}")

        # ── Eylem ──
        action = input(f"{player_name} ne yapıyor? > ").strip()

        if not action:
            print("⚠️  Eylem boş olamaz.")
            continue

        if action.lower() == "quit":
            return

        # ─ Eşya kullanma kontrolü ─
        item_used, item_gm_msg = handle_item_use(action, player_name, session_id, game_state)
        if not item_used and re.search(r'\buse\b|kullan', action, re.IGNORECASE) and item_gm_msg is None:
            continue

        user_message = f"{player_name}: {action}"
        if game_state.is_combat:
            game_state.combat_messages.append({"role": "user", "content": user_message})
        else:
            save_message(session_id, user.get("id"), "user", user_message)

        if item_used and item_gm_msg:
            if game_state.is_combat:
                game_state.combat_messages.append({"role": "user", "content": item_gm_msg})
            else:
                save_message(session_id, None, "user", item_gm_msg)

        grant_general_xp(session_id, player_name, 1, reason="aksiyon")

        # ════════════════════════════════════════════════════
        # ADIM 1: TRIGGER CHECK
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("📍 ADIM 1 — TRIGGER CHECK")
        print("═" * 50)

        if scenario_manager:
            current_id = scenario_manager.current_node.get('id', '?') if scenario_manager.current_node else '?'
            current_title = scenario_manager.current_node.get('title', '?') if scenario_manager.current_node else '?'
            print(f"   Mevcut node: {current_id} — {current_title}")

            recent_for_trigger = get_recent_messages(session_id)
            next_node = scenario_manager.check_trigger(recent_for_trigger)
            print(f"   Trigger sonucu: {next_node if next_node else 'YOK'}")

            if next_node:
                scenario_manager.load_node(next_node)
                if scenario_manager.current_node:
                    game_state.current_node = scenario_manager.current_node.get("title", "")

                quest_events = check_node_quests(session_id, next_node)
                for qe in quest_events:
                    if qe["event"] == "completed":
                        grant_quest_rewards(session_id, player_name, qe["quest"])

                transition_msg = f"[SCENE TRANSITION: players have arrived at {scenario_manager.current_node.get('title', next_node)}]"
                save_message(session_id, None, "user", transition_msg)
        else:
            print("   Senaryo yok — trigger atlandı")

        # ════════════════════════════════════════════════════
        # ADIM 2: COMBAT PROCESSING
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("⚔️  ADIM 2 — COMBAT CHECK")
        print("═" * 50)

        roll_result_msg = None
        combat_just_started = False

        if game_state.is_combat and game_state.active_encounter:
            # Process the full combat turn (player attack + enemy response)
            roll_result_msg, combat_ended, dead_players_this_turn = process_combat_turn(
                game_state, player_name, action, session_id, user, player_names_list
            )

            if combat_ended:
                # Generate combat summaries
                encounter = game_state.active_encounter
                total_xp = get_total_xp(encounter)

                # Grant XP to all alive players
                for char in game_state.characters:
                    pstats = None
                    try:
                        from game.xp_manager import get_player_stats
                        pstats = get_player_stats(session_id, char["name"])
                    except:
                        pass
                    if pstats and pstats["hp"] > 0:
                        grant_combat_xp(session_id, char["name"], total_xp)

                # Build dead players list
                all_dead = []
                try:
                    from game.xp_manager import get_player_stats
                    for char in game_state.characters:
                        ps = get_player_stats(session_id, char["name"])
                        if ps and ps["hp"] <= 0:
                            all_dead.append(char["name"])
                except:
                    pass

                mechanical_summary = generate_combat_summary(encounter, all_dead)
                narrative_summary = generate_llm_combat_summary(
                    session_id, game_state.combat_messages, game_state, all_dead
                )
                final_summary = f"{mechanical_summary}\n\n[NARRATIVE RECAP]\n{narrative_summary}"
                save_message(session_id, None, "assistant", final_summary)
                game_state.combat_messages = []

                # Clear status effects after combat
                for char in game_state.characters:
                    game_state.clear_player_statuses(char["name"])

                game_state.end_encounter()
                print("\n⚔️  SAVAŞ BİTTİ!")
                print(f"   Toplam XP: {total_xp}")
                if all_dead:
                    print(f"   💀 Ölen: {', '.join(all_dead)}")

        else:
            # Not in combat — check if GM response should start combat
            # (Combat is initiated via [ENCOUNTER] block in GM response, handled in ADIM 4/5)
            print("   ⏭️  Aktif savaş yok")

        # ════════════════════════════════════════════════════
        # ADIM 3: ROLL CHECK (non-combat actions)
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🎲 ADIM 3 — ROLL CHECK")
        print("═" * 50)

        # Skip roll check during combat — combat handles its own rolls
        if not game_state.is_combat:
            node_actions = None
            if scenario_manager and scenario_manager.current_node:
                node_actions = scenario_manager.current_node.get("available_actions")
                print(f"   Node available_actions: {'mevcut' if node_actions else 'YOK'}")

            roll_info = needs_roll_check(action, node_actions)

            if roll_info.get("needed"):
                roll_result_msg, roll_success = execute_roll(roll_info, player_name, game_state, session_id, user)
            else:
                print("   ⏭️  Zar atılmadı")
                grant_general_xp(session_id, player_name, 1, reason="aksiyon (roll yok)")
        else:
            print("   ⏭️  Combat aktif — roll check atlandı (combat motoru zar attı)")

        # ════════════════════════════════════════════════════
        # ADIM 4: GM CEVABI
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🧙 ADIM 4 — GM CEVABI")
        print("═" * 50)

        recent_messages = get_recent_messages(session_id) + game_state.combat_messages
        system_prompt = build_system_prompt(
            game_state.characters, action,
            game_state, scenario_manager,
            roll_info=roll_result_msg, session_id=session_id
        )

        print(f"🐞 DEBUG [Combat/CLI]: Requesting GM response. (Combat? {game_state.is_combat})")
        print(f"   System prompt uzunluğu: {len(system_prompt)} karakter")
        print("⏳ GM düşünüyor...\n")
        gm_response = ask_gm(recent_messages, system_prompt)

        # ════════════════════════════════════════════════════
        # ADIM 5: ENCOUNTER DETECTION & EVENT PARSER
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🔍 ADIM 5 — EVENT PARSER & ENCOUNTER DETECTION")
        print("═" * 50)

        # Check for [ENCOUNTER] block to start combat
        if not game_state.is_combat:
            encounter_data = parse_encounter_from_response(gm_response)
            if encounter_data:
                print(f"🐞 DEBUG: [ENCOUNTER] block detected! Starting combat...")
                clean_narrative = strip_encounter_from_response(gm_response)
                gm_response = clean_narrative

                new_encounter = create_encounter(encounter_data)
                game_state.start_encounter(new_encounter)
                combat_just_started = True

                # Save the encounter start as a system message
                save_message(session_id, None, "user",
                    f"[COMBAT STARTED: {', '.join(e['display_name'] for e in new_encounter.enemies)}]")

        # Parse for items, gold, quest hints
        events = parse_gm_events(gm_response)
        print(f"   Parser sonucu: {events}")

        if events.get("gold_found", 0) > 0:
            add_gold(session_id, player_name, events["gold_found"])

        if events.get("item_found"):
            game_state.pending_item = events["item_found"]
            pickup_result = handle_item_pickup(game_state, player_name, session_id, user)
            if pickup_result:
                save_message(session_id, None, "user", pickup_result)

        # ── NPC Extraction ──
        existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
        new_npcs = extract_npcs_from_response(gm_response, recent_messages, existing_npc_names, player_names_list)
        for npc in new_npcs:
            public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
            save_npc(npc["name"], public_data, npc["secret"], session_id)

        npcs_after = get_all_npcs(session_id)
        print(f"\n🔎 NPC Extractor — tur sonrası: {len(npcs_after)} NPC")

        game_state.set_scene(gm_response[:100])

        if game_state.is_combat:
            game_state.combat_messages.append({"role": "assistant", "content": gm_response})
        else:
            save_message(session_id, None, "assistant", gm_response)

        # ── Durum göster ──
        print("\n" + "─" * 50)
        for char in game_state.characters:
            print(format_player_status(session_id, char["name"]))
        if game_state.is_combat and game_state.active_encounter:
            print(format_encounter_status(game_state))
        print("─" * 50)

# ─── ANA FONKSİYON ───────────────────────────────────────────────────────────

def main():
    initialize_db()
    ingest()

    user = login_screen()
    if user is None:
        print("Giriş başarısız.")
        return

    print(f"\nHoş geldin {user['username']}! Rol: {user['role']}")

    active = get_active_session()
    if active:
        print(f"\nAktif oturum bulundu: {active['session_name']}")
        choice = input("Devam et? (e/h): ").strip().lower()
        if choice == "e":
            session_id = active["id"]
        else:
            session_name = input("Yeni oturum adı: ").strip()
            session_id = create_session(session_name)
    else:
        session_name = input("Oturum adı: ").strip()
        session_id = create_session(session_name)

    print(f"DEBUG session_id: {session_id}")

    game_state = GameState()
    game_state.session_id = session_id

    load_player_characters(game_state)

    if not game_state.characters:
        print("⚠️  Hiç karakter yüklenmedi, çıkılıyor.")
        return

    print(f"\nDEBUG yüklenen karakterler ({len(game_state.characters)} adet):")
    for c in game_state.characters:
        print(f"   • {c.get('name')} | {c.get('class','?')} | abilities: {c.get('abilities',{})}")

    scenario_manager = select_scenario()

    if scenario_manager:
        print(f"\nDEBUG senaryo: {scenario_manager.meta.get('title','?')}")
        print(f"DEBUG başlangıç node: {scenario_manager.current_node.get('id','?') if scenario_manager.current_node else 'YOK'}")
    else:
        print("\nDEBUG senaryo: YOK (serbest mod)")

    game_loop(user, session_id, game_state, scenario_manager)

    end_session(session_id)
    print("\nGörüşürüz adventurer! ⚔️")

if __name__ == "__main__":
    main()
